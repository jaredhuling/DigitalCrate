"""Taste model: learns what you like from stars, dislikes and listening behaviour.

Two parts:
 1. Sound taste — Bayesian logistic regression (Laplace approximation) on PCA-reduced CLAP embeddings +
    engineered features, giving a mean *and* an uncertainty per sample (used for exploration), blended with
    a multi-mood nearest-favourite similarity (your taste is several moods, not one average).
 2. Technique taste — Beta posteriors per manipulation technique / amount, from stars & dislikes on
    variations. mangle.py draws variation families from these instead of hand-set weights.

Unrated library samples act as weak negatives (positive-unlabelled learning). Recent events can be up-weighted
for a "today's vibe" ranking.

Since the switch-over (docs/plans/recommend.md) the samples surfaces are ranked by the shared taste model
(reco/models/taste.py, kept fitted by reco/live.py) when the switch says samples: new (the default): scores_payload
and cached_scores serve its score. This model stays for "today's vibe" (it weighs recent events; the shared model
doesn't), for the Taste page's explanations of what was learned, and as the fallback before the shared model's first
fit, or with the switch at samples: old.
"""
import json
import re
import time
from pathlib import Path

import numpy as np

from . import config as C
from .db import connect

CATS = ["Vocals", "Vocal Atmospheres", "Pads & Atmospheres", "Chords & Keys", "Melodies & Leads",
        "Textures & Field", "Bass & Sub", "Percussion", "Strings & Orchestral"]
KINDS = ["loop", "free", "phrase", "oneshot"]
TECH_FILE = C.DATA_DIR / "technique_taste.json"
N_PCA = 64  # 32 -> 64 lifted held-out accuracy (held-out test)


def _db():
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS events (ts REAL, path TEXT, sample_id TEXT, type TEXT,
                   value REAL, context TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS events_path ON events(path)")
    con.execute("CREATE TABLE IF NOT EXISTS embeddings (path TEXT PRIMARY KEY, clap BLOB)")
    con.execute("""CREATE TABLE IF NOT EXISTS favorites (path TEXT PRIMARY KEY, sample_id TEXT,
                   label TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    return con


def log_event(path, type_, value=None, sample_id=None, context=None):
    con = _db()
    con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                (time.time(), path, sample_id, type_, value, json.dumps(context) if context else None))
    con.commit()


# ---------------------------------------------------------------- labels from events

PASSED_OVER = 0.2  # weight of "short, played once, passed over while you starred others" (0.15-0.3 tested best)


def item_labels(con, recent_hours=None, durs=None, until=None):
    """Aggregate events into (path -> (y, weight)). Explicit signals dominate implicit ones. until: only what you'd
    told it before this time (unix seconds), as the model knew you then (for the time-forward accuracy test)."""
    now = time.time() if until is None else until
    lab = {}
    if until is None:
        fav = {r["path"] for r in con.execute("SELECT path FROM favorites")}
    else:
        fav = {r["path"] for r in con.execute("SELECT path FROM favorites WHERE strftime('%s', added_at) < ?",
                                              (str(int(until)),))}
    if durs is None:
        durs = {r["path"]: r["dur"] or 0 for r in con.execute("SELECT path, dur FROM samples")}
    # short samples you passed over: played once and never again, in a session (events < 10 min apart) where you
    # starred something else. A 1-second clip can't be skipped, so this is the only "not this one" it can get.
    # Held-out test (every heard sample's labels hidden in its own fold): AUC 0.765 -> 0.775, better in 13 of 15 folds.
    session, starred, plays, sess_of, last = 0, {}, {}, {}, None
    for r in con.execute("SELECT * FROM events WHERE ts < ? ORDER BY ts", (now + 1,)):
        if last is not None and r["ts"] - last > 600:
            session += 1
        last = r["ts"]
        if r["type"] == "star":
            starred.setdefault(session, set()).add(r["path"])
        elif r["type"] == "listen":
            plays[r["path"]] = plays.get(r["path"], 0) + 1
            sess_of.setdefault(r["path"], set()).add(session)
    for r in con.execute("SELECT * FROM events WHERE ts < ? ORDER BY ts", (now + 1,)):
        age_d = (now - r["ts"]) / 86400
        w_time = np.exp(-age_d / 60)  # slow decay: taste drifts over months
        if recent_hours and (now - r["ts"]) < recent_hours * 3600:
            w_time *= 4
        d = lab.setdefault(r["path"], {"pos": 0.0, "neg": 0.0, "dislike": None, "secs": 0.0, "plays": 0, "skip": 0.0})
        t, v = r["type"], r["value"]
        if t == "dislike":
            d["dislike"] = bool(v)
        elif t == "unstar":
            d["neg"] += 0.5 * w_time
        elif t == "listen":
            # "played 70% through" is automatic for a half-second one-shot and rare for a long loop, so it
            # mostly taught the model "short = liked". Count real listening time and replays instead.
            frac = v or 0
            dur = durs.get(r["path"], 0)
            d["secs"] += frac * dur * w_time
            d["plays"] += w_time
            if dur > 3 and frac < 0.15:
                d["skip"] += w_time
    out = {}
    for p, d in lab.items():
        if d["dislike"]:
            out[p] = (0, 1.5)
        elif p in fav:
            continue
        else:
            if d["plays"] >= 3 or d["secs"] >= 12:
                d["pos"] += 0.5
            elif d["plays"] and d["skip"] >= d["plays"] - 1e-9:
                d["neg"] += 0.5
            net = d["pos"] - d["neg"]
            if abs(net) > 0.05:
                out[p] = (1 if net > 0 else 0, min(1.0, abs(net)))
            elif plays.get(p) == 1 and durs.get(p, 9) <= 3 and any(starred.get(s, set()) - {p} for s in sess_of.get(p, ())):
                out[p] = (0, PASSED_OVER)
    from .collections_ import members
    for p in members(con):  # in a collection: liked, a bit less than a star; a ✕ still wins
        if p not in fav and not (p in out and out[p][0] == 0 and out[p][1] >= 1.5):
            out[p] = (1, max(1.2, out.get(p, (1, 0))[1]))
    for p in fav:
        out[p] = (1, 1.5)
    return out


# ---------------------------------------------------------------- features

def _variation_meta(path):
    """Technique + amount from a variation file's sidecar."""
    j = (C.LIB_ROOT / path).with_suffix(".json")
    if not j.exists():
        return None
    info = json.loads(j.read_text())
    return info


def embed_paths(con, paths):
    """CLAP embeddings for arbitrary library files (variations), cached in the DB."""
    have = {r["path"]: np.frombuffer(r["clap"], np.float16).astype(np.float32)
            for r in con.execute(f"SELECT * FROM embeddings WHERE path IN ({','.join('?' * len(paths))})", paths)} \
        if paths else {}
    todo = [p for p in paths if p not in have and (C.LIB_ROOT / p).exists()]
    if todo:
        import soundfile as sf
        from scipy.signal import resample_poly
        from . import models
        cl = models.clap()
        clips = []
        for p in todo:
            y, sr = sf.read(str(C.LIB_ROOT / p), dtype="float32", always_2d=True)
            m = y.mean(1)
            if len(m) > sr * 10:
                mid = len(m) // 2
                m = m[mid - sr * 5: mid + sr * 5]
            clips.append(resample_poly(m, 48000, sr).astype(np.float32))
        E = cl.embed_audio(clips)
        for p, e in zip(todo, E):
            con.execute("INSERT OR REPLACE INTO embeddings VALUES (?,?)", (p, e.astype(np.float16).tobytes()))
            have[p] = e
        con.commit()
    return have


class Featurizer:
    def __init__(self, E_all):
        mu = E_all.mean(0)
        Z = E_all - mu
        # principal directions from the 512x512 covariance (same subspace as an SVD of all samples, ~25x faster)
        w, V = np.linalg.eigh(Z.T @ Z)
        self.mu, self.P = mu, V[:, ::-1][:, :N_PCA]
        self.scale = Z @ self.P
        self.sd = self.scale.std(0) + 1e-6

    def batch(self, E, metas):
        """__call__ for many rows at once."""
        z = ((E - self.mu) @ self.P) / self.sd
        n = len(metas)
        cat = np.zeros((n, len(CATS))); kind = np.zeros((n, len(KINDS)))
        ci = {c: k for k, c in enumerate(CATS)}; ki = {c: k for k, c in enumerate(KINDS)}
        for r, m in enumerate(metas):
            if m.get("category") in ci:
                cat[r, ci[m["category"]]] = 1
            if m.get("kind") in ki:
                kind[r, ki[m["kind"]]] = 1
        g = lambda k, d: np.array([m.get(k) or d for m in metas], float)
        eng = np.stack([np.log1p(g("dur", 5)) - 1.6, g("centroid", 1500) / 3000 - 0.5, g("flatness", 0.02) * 10,
                        g("pratio", 0.1), np.array([m.get("scale") == "minor" for m in metas], float),
                        np.array([bool(m.get("variation")) for m in metas], float)], 1)
        return np.hstack([z, cat, kind, eng])

    def __call__(self, emb, meta):
        z = ((emb - self.mu) @ self.P) / self.sd
        cat = np.zeros(len(CATS)); kind = np.zeros(len(KINDS))
        if meta.get("category") in CATS:
            cat[CATS.index(meta["category"])] = 1
        if meta.get("kind") in KINDS:
            kind[KINDS.index(meta["kind"])] = 1
        eng = np.array([np.log1p(meta.get("dur") or 5) - 1.6, (meta.get("centroid") or 1500) / 3000 - 0.5,
                        (meta.get("flatness") or 0.02) * 10, meta.get("pratio") or 0.1,
                        1.0 if meta.get("scale") == "minor" else 0.0, 1.0 if meta.get("variation") else 0.0])
        return np.concatenate([z, cat, kind, eng])


# ---------------------------------------------------------------- Bayesian logistic regression

def _sig(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def fit_blr(X, y, w, prior_var=1.0, iters=30):
    d = X.shape[1]
    beta = np.zeros(d)
    A0 = np.eye(d) / prior_var
    for _ in range(iters):
        p = _sig(X @ beta)
        g = X.T @ (w * (p - y)) + A0 @ beta
        H = (X * (w * p * (1 - p))[:, None]).T @ X + A0
        step = np.linalg.solve(H, g)
        beta -= step
        if np.abs(step).max() < 1e-6:
            break
    p = _sig(X @ beta)
    H = (X * (w * p * (1 - p))[:, None]).T @ X + A0
    return beta, np.linalg.inv(H)


def predict(X, beta, cov):
    m = X @ beta
    s = ((X @ cov) * X).sum(1)  # the diagonal of X cov X^T without building it
    return _sig(m / np.sqrt(1 + np.pi * s / 8)), np.sqrt(s)


# ---------------------------------------------------------------- full fit

_LIB = {}


# Gradient-boosted trees, averaged with the regression (held-out: +0.014 AUC, +0.010 on new songs). Unweighted:
# with sample weights scikit-learn's trees fit ~8x slower. The Taste page tracks regression, trees and the average
# separately, so it shows whether the trees pull ahead (or fall behind) as ratings accumulate.
TREES = True
TREE_BG = 15  # unheard samples per favourite as the trees' "probably not" examples


def _trees(Xl, yl, X_all, unl, n_pos, rng):
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from threadpoolctl import threadpool_limits
        tb = rng.choice(unl, size=min(len(unl), TREE_BG * max(1, n_pos)), replace=False)
        with threadpool_limits(2):  # stay light while mining runs share the machine
            clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                 l2_regularization=1.0, random_state=0)
            clf.fit(np.vstack([Xl, X_all[tb]]), np.r_[yl, np.zeros(len(tb))])
            _trees.last = clf  # kept for scoring audio outside the library (suggest.py)
            return clf.predict_proba(X_all)[:, 1]
    except Exception as e:  # the regression alone still works
        print(f"taste: trees skipped ({e})")
        return None


N_STYLE = 8  # dimensions of the song's Discogs-EffNet style embedding used as features


def _extra_features(con, rows):
    """Per-sample columns after the base features: quality, loudness, key confidence, has a tempo (standardised), and
    the song's audio style (the first N_STYLE principal directions of its Discogs-EffNet embedding; zeros if the song
    hasn't been tagged yet). Held-out tests: quality +0.006 AUC, style +0.004 (see fit)."""
    g = lambda k, d: np.array([r[k] if r[k] is not None else d for r in rows], float)
    z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
    q = np.stack([z(g("quality", .5)), z(g("loudness", -20)), z(g("key_strength", .5)), (g("bpm", 0) > 0) * 1.0], 1)
    sty = np.zeros((len(rows), N_STYLE))
    try:
        from .styles import embeddings
        ids, SE, _ = embeddings(con)
        if len(ids) > N_STYLE:
            Z = SE - SE.mean(0)
            w, V = np.linalg.eigh(Z.T @ Z)
            P = Z @ V[:, ::-1][:, :N_STYLE]
            P /= P.std(0) + 1e-6
            at = {t: i for i, t in enumerate(ids)}
            for k, r in enumerate(rows):
                if r["track_id"] in at:
                    sty[k] = P[at[r["track_id"]]]
    except Exception:
        pass
    return np.hstack([q, sty])


def _library(con):
    """Every sample's embedding, metadata and features, kept between calls until samples are added or removed."""
    key = tuple(con.execute("SELECT COUNT(*), MAX(rowid) FROM samples").fetchone())
    if _LIB.get("key") != key:
        rows = con.execute("""SELECT s.path, s.clap, s.category, s.kind, s.dur, s.centroid, s.flatness, s.pratio,
                                     s.scale, s.quality, s.loudness, s.key_strength, s.bpm, s.track_id
                              FROM samples s JOIN tracks t ON t.id=s.track_id
                              WHERE s.path NOT LIKE '_Reference/%'""").fetchall()
        if not rows:
            return None
        E = np.stack([np.frombuffer(r["clap"], np.float16).astype(np.float32) for r in rows])
        metas = [dict(category=r["category"], kind=r["kind"], dur=r["dur"], centroid=r["centroid"],
                      flatness=r["flatness"], pratio=r["pratio"], scale=r["scale"]) for r in rows]
        fz = Featurizer(E)
        paths = [r["path"] for r in rows]
        _LIB.clear()
        extra = _extra_features(con, rows)
        _LIB.update(key=key, paths=paths, E=E, fz=fz, X=np.hstack([fz.batch(E, metas), extra]), extra=extra,
                    tid=np.array([r["track_id"] for r in rows]), meta=dict(zip(paths, metas)),
                    pos={p: i for i, p in enumerate(paths)},
                    durs={r[0]: r[1] or 0 for r in con.execute("SELECT path, dur FROM samples")})
    return _LIB


def fit(recent_hours=None, verbose=False, labels=None):
    con = _db()
    L = _library(con)
    if L is None:
        return None
    rows = [dict(path=p) for p in L["paths"]]
    E, fz, meta = L["E"], L["fz"], dict(L["meta"])
    emb = {p: E[i] for p, i in L["pos"].items()}
    labels = labels if labels is not None else item_labels(con, recent_hours, L["durs"])

    # variation files: embed + inherit metadata from their source sample
    var_paths = [p for p in labels if p.startswith("Variations/")]
    vrows = {r["path"]: r for r in con.execute("SELECT * FROM variants")} if var_paths else {}
    if var_paths:
        emb.update(embed_paths(con, var_paths))
        for p in var_paths:
            src = con.execute("SELECT s.* FROM samples s JOIN variants v ON v.sample_id=s.id WHERE v.path=?",
                              (p,)).fetchone()
            meta[p] = dict(meta.get(src["path"], {}) if src else {}, variation=True, src=src["path"] if src else None)
    lp = [p for p in labels if p in emb]
    n_pos = sum(labels[p][0] for p in lp)
    X_all = L["X"]
    result = dict(n_labels=len(lp), n_pos=int(n_pos), paths=[r["path"] for r in rows])

    # similarity: how close each sample is to its single closest liked one (held-out tests: k=1 beat k=3, and
    # subtracting closeness to ✕'d samples here hurt; the regression already learns from them)
    pos = [emb[p] for p in lp if labels[p][0] == 1]
    knn = np.zeros(len(rows))
    if pos:
        knn = (E @ np.stack(pos).T).max(1)
    result["knn"] = knn
    LP = L["pos"]

    def row_of(p):
        if p in LP:
            return X_all[LP[p]]
        src = meta[p].get("src")
        ex = L["extra"][LP[src]] if src in LP else np.zeros(L["extra"].shape[1])
        return np.r_[fz(emb[p], meta[p]), ex]

    if len(lp) >= 8 and n_pos >= 3:
        # PU learning: random unlabelled samples as weak negatives
        rng = np.random.default_rng(0)
        unl = [i for i, r in enumerate(rows) if r["path"] not in labels]
        # 60 per favourite at weight 0.1 (was 20 at 0.05): +0.012 held-out AUC, better in every fold
        bg = rng.choice(unl, size=min(len(unl), 60 * max(1, n_pos)), replace=False) if unl else []
        Xl = np.stack([row_of(p) for p in lp])
        yl = np.array([labels[p][0] for p in lp], float)
        X = np.vstack([Xl, X_all[bg]])
        y = np.r_[yl, np.zeros(len(bg))]
        w = np.r_[[labels[p][1] for p in lp], np.full(len(bg), 0.1)]
        beta, cov = fit_blr(X, y, w)
        prob, unc = predict(X_all, beta, cov)
        result.update(prob=prob, unc=unc, beta=beta, cov=cov)
        z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
        kz, pz = z(knn), z(prob)
        tz = None
        if TREES:
            tp = _trees(Xl, yl, X_all, unl, n_pos, rng)
            tz = z(tp) if tp is not None else None
        # songs you've rated lift (or sink) their other samples: the mean label of the song's rated samples
        song = np.zeros(len(rows))
        tid = L["tid"]
        acc = {}
        for p in lp:
            if p in LP:
                acc.setdefault(tid[LP[p]], []).append(labels[p][0])
        for t, v in acc.items():
            song[tid == t] = np.mean(v)
        sz = (song - song.mean()) / (song.std() + 1e-9)
        # held-out (2,386 heard, 144 favourites): 0.781 -> 0.822 (regression) -> 0.836 (with trees);
        # songs you haven't touched 0.758 -> 0.787 -> 0.797
        model = z(pz + tz) if tz is not None else pz
        result["parts"] = dict(regression=pz, trees=tz, knn=kz, song=sz)
        # for scoring audio that isn't in the library (suggest.py): the models and each part's library scale
        sm = (pz + tz) if tz is not None else pz
        result["critic"] = dict(trees=getattr(_trees, "last", None) if tz is not None else None, pos_E=np.stack(pos),
                                prob=(float(prob.mean()), float(prob.std() + 1e-9)),
                                tree=(float(tp.mean()), float(tp.std() + 1e-9)) if tz is not None else None,
                                sum=(float(sm.mean()), float(sm.std() + 1e-9)),
                                knn=(float(knn.mean()), float(knn.std() + 1e-9)))
        result["score"] = 0.7 * model + 0.3 * kz + 0.3 * sz
        rng2 = np.random.default_rng()
        bt = rng2.multivariate_normal(beta, cov)
        result["discover"] = X_all @ bt  # Thompson sample: optimistic where uncertain
    else:
        result["score"] = knn
        result["unc"] = np.ones(len(rows))
        result["discover"] = knn + np.random.default_rng().normal(0, 0.15, len(rows))
    if verbose:
        report(result, labels, lp, emb, fz, meta)
    return result


def report(res, labels, lp, emb, fz, meta):
    """Honest check: hide a fifth of the samples you've rated or played, fit on the rest, and ask whether your
    hidden favourites outrank the hidden ones you heard but didn't star. (Scoring the training labels themselves
    would mostly measure "short clips get played to the end".)"""
    print(f"labels: {res['n_labels']} ({res['n_pos']} positive)")
    fav = {r["path"] for r in _db().execute("SELECT path FROM favorites")}
    if len([p for p in lp if p in fav]) < 15:
        print("held-out evaluation needs ~15+ favourites; keep starring.")
        return
    from scipy.stats import rankdata
    X = np.stack([fz(emb[p], meta[p]) for p in lp])
    y = np.array([labels[p][0] for p in lp]); w = np.array([labels[p][1] for p in lp])
    star = np.array([p in fav for p in lp])
    aucs = []
    for f in range(5):
        te = np.arange(len(lp)) % 5 == f
        b, c = fit_blr(X[~te], y[~te], w[~te])
        s = predict(X[te], b, c)[0]
        r = rankdata(s); t = star[te]; n1 = t.sum(); n0 = len(t) - n1
        if n1 and n0:
            aucs.append((r[t].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    print(f"held-out AUC (favourites vs heard-but-not-starred): {np.mean(aucs):.2f} (0.5 = guessing)")


# ---------------------------------------------------------------- technique taste

def technique_posteriors(prior):
    """Beta posterior per technique and per 'technique:amount' from events on variation files."""
    con = _db()
    labels = item_labels(con)
    post = {t: [1 + 2 * v, 3.0] if v > 0 else [0.5, 6.0] for t, v in prior.items()}
    for path, (y, w) in labels.items():
        if not path.startswith("Variations/"):
            continue
        info = _variation_meta(path)
        if not info or not info.get("technique"):
            continue
        keys = [info["technique"]]
        amt = next((re.findall(r"[+-]\d+", s)[0] for s in info.get("chain", []) if re.search(r"[+-]\d+", s)), None)
        if amt:
            keys.append(f"{info['technique']}:{amt}")
        for k in keys:
            a, b = post.setdefault(k, [1.0, 1.0])
            post[k] = [a + w * y, b + w * (1 - y)]
    TECH_FILE.parent.mkdir(parents=True, exist_ok=True)
    TECH_FILE.write_text(json.dumps(post, indent=1))
    return post


_FIT = {}


def compact(payload):
    """The page's copy: scores keyed by sample id in two arrays (a quarter of the size of path-keyed maps)."""
    if not payload:
        return payload
    con = _db()
    ids = dict(con.execute("SELECT path, id FROM samples"))
    keys = [p for p in payload["score"] if p in ids]
    return dict(n_labels=payload["n_labels"], n_pos=payload["n_pos"], disliked=payload["disliked"],
                ids=[ids[p] for p in keys], score=[round(payload["score"][p], 3) for p in keys],
                discover=[round(payload["discover"][p], 3) for p in keys], policy=payload.get("policy"))


NEW, OLD, FALLBACK = "reco.taste", "taste", "taste (new model not fitted yet)"


def _disliked(con):
    """Samples whose latest ✕ is on (as item_labels reads them)."""
    return sorted(r[0] for r in con.execute("SELECT path FROM events WHERE type='dislike' GROUP BY path "
                                            "HAVING MAX(ts) = MAX(CASE WHEN value = 1 THEN ts END)"))


def _new_fit():
    """The shared taste model's current fit when the switch says samples: new (None otherwise, or before its first
    fit; a refit is started in the background when your ratings changed, never waited for)."""
    try:
        from .reco import live
        if live.policy("samples") != "new":
            return None
        return live.fitted()
    except Exception as e:
        print("taste: the shared model is unavailable:", e)
        return None


def scores_payload(recent_hours=None):
    """Scores for the browser: the shared taste model's (see the top), or this module's when the switch says samples:
    old, for "today's vibe" (recent_hours), and until the shared model's first fit. policy says which."""
    f = _new_fit() if recent_hours is None else None
    if f is not None:
        z, d = f.z, f.discover()
        ok = np.isfinite(z)
        return dict(n_labels=f.t.n, n_pos=f.t.n_pos, policy=NEW,
                    score={p: round(float(z[i]), 4) for i, p in enumerate(f.paths) if ok[i]},
                    discover={p: round(float(d[i]), 4) for i, p in enumerate(f.paths) if ok[i]},
                    disliked=_disliked(_db()))
    out = _old_payload(recent_hours)
    if out and recent_hours is None:
        try:
            from .reco import live
            out["policy"] = OLD if live.policy("samples") == "old" else FALLBACK
        except Exception:
            out["policy"] = OLD
    return out


def _old_payload(recent_hours=None):
    """This module's scores. The model is refit only when your ratings, listening or the samples change (a
    listen counts, so it stays current); otherwise the last fit is reused and only 'discover' is re-drawn."""
    con = _db()
    L = _library(con)
    if L is None:
        return {}
    labels = item_labels(con, recent_hours, L["durs"])
    key = (L["key"], recent_hours, hash(frozenset((p, round(w, 3), y) for p, (y, w) in labels.items())))
    res = _FIT.get(recent_hours)
    if not res or res["_key"] != key:
        res = fit(recent_hours, labels=labels)
        if res is None:
            return {}
        res["_key"] = key
        _FIT[recent_hours] = res
    if "beta" in res:
        res["discover"] = L["X"] @ np.random.default_rng().multivariate_normal(res["beta"], res["cov"])
    disliked = {p for p, (y, w) in labels.items() if y == 0 and w >= 1.5}
    return dict(n_labels=res["n_labels"], n_pos=res["n_pos"],
                score={p: round(float(s), 4) for p, s in zip(res["paths"], res["score"])},
                discover={p: round(float(s), 4) for p, s in zip(res["paths"], res["discover"])},
                disliked=sorted(disliked))


def cached_scores():
    """The last fit's scores ({path: score}) and disliked paths, without refitting: for callers on a click path (the
    Mashup's one-shot dice), where a few seconds' wait for a fresh fit isn't worth it. None if nothing was fitted yet
    in this process: then a fit is started in the background for the next call. The shared model's scores when the
    switch says samples: new and it has been fitted."""
    f = _new_fit()
    if f is not None:
        return {p: float(v) for p, v in zip(f.paths, f.z) if np.isfinite(v)}
    res = _FIT.get(None)
    if res is None:
        import threading
        if not getattr(cached_scores, "_busy", False):
            cached_scores._busy = True

            def go():
                try:
                    _old_payload(None)
                finally:
                    cached_scores._busy = False
            threading.Thread(target=go, daemon=True).start()
        return None
    return dict(zip(res["paths"], (float(x) for x in res["score"])))


def why(path):
    """"Why this?" for one sample: how it ranks, which parts of the model put it there (the score is 0.7 x the
    model + 0.3 x closeness to a favourite + 0.3 x its song), the samples you liked that it's closest to, what you
    did with its song, and what in the regression pushed it up or down (its sound, its type, quality, the song's
    style...). Every number comes from the same fit that ranks the page."""
    _old_payload(None)
    res, con = _FIT.get(None), _db()
    L = _library(con)
    if not res or L is None or path not in L["pos"]:
        return dict(error="no taste model yet, or not a library sample")
    i = L["pos"][path]
    sc = np.asarray(res["score"])
    out = dict(path=path, top=round(float(100 * (sc > sc[i]).mean()), 1), n_labels=res["n_labels"], n_pos=res["n_pos"])
    f = _new_fit()
    if f is not None and path in f.pos and np.isfinite(f.z[f.pos[path]]):
        # the rank is the shared model's (what orders the page); the parts and reasons below are the earlier model's
        z = f.z[np.isfinite(f.z)]
        out.update(top=round(float(100 * (z > f.z[f.pos[path]]).mean()), 1), n_labels=f.t.n, n_pos=f.t.n_pos,
                   model=NEW, note="ranked by the shared taste model; the breakdown is the earlier model's")
    labels = item_labels(con, None, L["durs"])
    pos = [p for p, (y, w) in labels.items() if y == 1 and p in L["pos"] and p != path]
    if pos:
        P = np.array([L["pos"][p] for p in pos])
        s = L["E"][P] @ L["E"][i] / (np.linalg.norm(L["E"][P], axis=1) * np.linalg.norm(L["E"][i]) + 1e-9)
        out["like"] = [dict(path=pos[k], sim=round(float(s[k]), 2)) for k in np.argsort(-s)[:6]]
    tid = L["tid"][i]
    same = [labels[p][0] for p, k in L["pos"].items() if L["tid"][k] == tid and p in labels and p != path]
    out["song"] = dict(liked=int(sum(same)), passed=int(len(same) - sum(same)))
    parts = res.get("parts")
    if parts:
        model = parts["regression"] + parts["trees"] if parts.get("trees") is not None else parts["regression"]
        model = (model - model.mean()) / (model.std() + 1e-9)
        out["parts"] = dict(model=round(float(0.7 * model[i]), 2), close=round(float(0.3 * parts["knn"][i]), 2),
                            song=round(float(0.3 * parts["song"][i]), 2))
    if "beta" in res:  # the regression's reasons: each group of features' pull on this sample vs the average one
        X = L["X"]
        c = res["beta"] * (X[i] - X.mean(0))
        n0 = N_PCA
        groups = [("its sound", slice(0, n0)), ("its type (" + (L["meta"][path].get("category") or "") + ")",
                                                slice(n0, n0 + len(CATS)))]
        k0 = n0 + len(CATS)
        groups.append((f"being a {L['meta'][path].get('kind') or ''}", slice(k0, k0 + len(KINDS))))
        e0 = k0 + len(KINDS)
        from .taste_report import ENG
        groups += [(ENG[j], slice(e0 + j, e0 + j + 1)) for j in range(6)]  # ENG's last four name the extra columns
        x0 = e0 + 6
        groups += [("recording quality", slice(x0, x0 + 1)), ("loudness", slice(x0 + 1, x0 + 2)),
                   ("a clear key", slice(x0 + 2, x0 + 3)), ("a steady tempo", slice(x0 + 3, x0 + 4)),
                   ("the song's style", slice(x0 + 4, x0 + 4 + N_STYLE))]
        g = sorted(((n, float(c[s].sum())) for n, s in groups), key=lambda x: -abs(x[1]))
        out["reasons"] = [dict(what=n, pull=round(v, 2)) for n, v in g[:5] if abs(v) > 0.05]
    return out
