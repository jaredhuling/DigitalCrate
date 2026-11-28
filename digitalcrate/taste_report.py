"""The taste model explained, for the Taste page (/taste): how well it predicts you, what it has learned, what it is
learning from, where it's unsure, and how all that changes over time.

Accuracy is measured honestly: every sample you've heard is put in one of five groups; for each group, everything
you told the model about those samples (stars, ✕, skips, listening) is hidden, the model is fitted on the rest, and it
must rank the group's favourites above the group's heard-but-not-starred samples (AUC: 0.5 is guessing, 1.0 is
perfect). Hiding every label of the group, not just the stars, keeps a rule from being graded on samples it labelled
itself. Five folds, two shuffles. Two simple rankings are measured the same way for context: sample quality alone,
and random. Each result is kept in `taste_history`, so the page can show the trend as you rate more.

Since the switch-over the model in use is the shared taste model (reco/models/taste.py) unless the switch says
samples: old (reco/live.py). Its accuracy is measured by the harness (reco eval, in the background: the same folds by
sample, and forward in time) and written to `taste_history`, its rows listed in `taste_history_model` as "reco.taste"
(the earlier model's rows are the others). "What it has learned" (weights and words) still reads the earlier model, and says so: the shared model's
effects are not read out yet. "How well each recommender predicts you" shows the harness's latest run of every task.

"What it has learned" reads the fitted model:
  - the category, kind and sound-feature weights directly (log-odds: + means more likely to be one you'd star);
  - words: descriptions like "warm analog synth pad" are embedded with CLAP (the same space the samples live in)
    and scored by the model, so its taste can be read in plain language. Approximate: text and audio embeddings
    aren't identical, so treat the order as a hint, not a measurement.
"""
import json
import time

import numpy as np

from . import config as C

from .taste import CATS, KINDS, N_PCA, _db, _library, _new_fit, _old_payload, fit, item_labels

ENG = ["longer", "brighter", "noisier / breathier", "more pitched", "minor key", "a variation (reworked)",
       "cleaner (quality score)", "louder", "clearer key", "has a steady tempo"]
WORDS = [
    "a woman singing softly", "a man singing softly", "a choir", "soulful r&b vocals", "a breathy whispered voice",
    "a vocal chop", "operatic singing", "spoken words", "humming", "a gospel choir",
    "a warm analog synth pad", "a bright digital synth", "an ambient drone", "slow sustained strings",
    "a solo piano", "a rhodes electric piano", "an acoustic guitar", "a distorted electric guitar", "a church organ",
    "a jazz saxophone", "a muted trumpet", "a harp", "a music box", "a flute", "a bass line", "a deep sub bass",
    "a drum loop", "a crisp snare", "a kick drum", "hi-hats", "vinyl crackle", "tape hiss", "field recording of rain",
    "dark, ominous music", "sad, melancholic music", "ethereal, angelic sound", "warm, nostalgic, lo-fi sound",
    "happy, uplifting music", "aggressive, intense music", "dreamy, hazy, reverb-drenched", "dry and close",
    "romantic, sensual", "tense, suspenseful", "playful, quirky", "cinematic and epic", "minimal and sparse",
    "busy and dense", "medieval chant", "bossa nova", "1970s soul", "1990s r&b", "classical orchestra", "jazz trio",
]


def _auc(y, s):
    from scipy.stats import rankdata
    r = rankdata(s)
    n1 = y.sum(); n0 = len(y) - n1
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else None


def accuracy(con=None, folds=5, seeds=2):
    con = con or _db()
    L = _library(con)
    labels = item_labels(con, None, L["durs"])
    pos = L["pos"]
    fav = [r[0] for r in con.execute("SELECT path FROM favorites") if r[0] in pos]
    heard = {r[0] for r in con.execute("SELECT DISTINCT path FROM events WHERE type='listen'") if r[0] in pos}
    if len(fav) < 10:
        return dict(auc=None, note=f"needs about 10 favourites to measure (you have {len(fav)})", n_fav=len(fav))
    q = np.array([0.0] * len(L["paths"]))
    for r in con.execute("SELECT path, quality FROM samples"):
        if r[0] in pos:
            q[pos[r[0]]] = r[1] or 0
    res, base, alone = [], [], {"regression": [], "trees": []}
    allh = sorted(heard | set(fav))
    favs = set(fav)
    for seed in range(seeds):
        f = np.array(allh); np.random.default_rng(seed).shuffle(f)
        for k in range(folds):
            hide = set(f[k::folds].tolist())
            lab = {p: v for p, v in labels.items() if p not in hide}
            r = fit(None, labels=lab)
            cand = sorted(hide)  # this group's favourites vs this group's heard, never starred
            y = np.array([p in favs for p in cand])
            idx = [pos[p] for p in cand]
            a = _auc(y, np.asarray(r["score"])[idx])
            b = _auc(y, q[idx])
            if a is not None:
                res.append(a); base.append(b)
                P = r.get("parts") or {}
                for m in alone:  # the same blend with only one of the two models, on the same fold
                    if P.get(m) is not None:
                        s = 0.7 * P[m] + 0.3 * P["knn"] + 0.3 * P["song"]
                        alone[m].append(_auc(y, s[idx]))
    return dict(auc=round(float(np.mean(res)), 3), se=round(float(np.std(res) / np.sqrt(len(res))), 3),
                quality_auc=round(float(np.mean(base)), 3), n_fav=len(fav), n_heard=len(heard),
                **{f"auc_{m}": round(float(np.mean(v)), 3) if v else None for m, v in alone.items()})


def _history(con):
    con.execute("""CREATE TABLE IF NOT EXISTS taste_history (ts REAL, n_labels INTEGER, n_pos INTEGER, n_fav INTEGER,
                   n_dislike INTEGER, auc REAL, quality_auc REAL)""")
    have = {r[1] for r in con.execute("PRAGMA table_info(taste_history)")}
    for c in ("auc_regression", "auc_trees", "se"):  # the two models on their own; se: the measurement's own wobble
        if c not in have:
            con.execute(f"ALTER TABLE taste_history ADD COLUMN {c} REAL")
    # which model a row measured: rows listed here as "reco.taste" are the shared model's, the rest the earlier one's
    # (a side table, so the history table itself stays as it was)
    con.execute("CREATE TABLE IF NOT EXISTS taste_history_model (ts REAL PRIMARY KEY, model TEXT)")
    return con


NEW_ROWS = "ts IN (SELECT ts FROM taste_history_model WHERE model='reco.taste')"


_CACHE = {}
FORWARD = C.DATA_DIR / "taste_forward.json"
import threading
_MEASURING = threading.Event()


MEASURE_GAP = 900  # seconds between two background measurements of the shared model (one takes a few minutes)
_JOB = {}


def _job_alive():
    import os
    pid = _JOB.get("pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a finished child is a zombie until reaped
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True
    except OSError:
        return False


def measure_new_soon(sig):
    """Measure the shared model in the background (the harness: reco eval --task sample_taste, by sample and forward
    in time; a few minutes, in its own process at low priority). explain() writes the history row once it lands."""
    if _job_alive() or time.time() - _JOB.get("when", 0) < MEASURE_GAP:
        return
    try:
        from .serve import start_job, _saved_jobs
        jid = start_job("reco", ["eval", "--task", "sample_taste", "--split", "sample", "--split", "forward",
                                 "--model", "reco.taste", "--model", "quality"], "measuring your taste model")
        _JOB.update(pid=_saved_jobs().get(jid, {}).get("pid"), when=time.time(), sig=list(sig))
    except Exception as e:
        print("taste: could not start the measurement:", e)


def eval_all():
    """Every task of the harness, in the background (the Taste page's "measure again") -> the job's id."""
    from .serve import start_job, _saved_jobs
    jid = start_job("reco", ["eval"], "measuring every recommender")
    _JOB.update(pid=_saved_jobs().get(jid, {}).get("pid"), when=time.time(), all=True)
    return jid


def _new_history(con, sig):
    """Write the history row (and the forward test) from the newest harness run of the shared model on sample_taste,
    if it isn't written yet. -> True if a row was added."""
    try:
        from .reco.eval import latest
        r = latest("sample_taste")
    except Exception:
        return False
    sp = ((r or {}).get("splits") or {}).get("sample") or {}
    m = (sp.get("models") or {}).get("reco.taste")
    if not m or (m["metrics"].get("auc") or {}).get("mean") is None:
        return False
    if con.execute(f"SELECT 1 FROM taste_history WHERE {NEW_ROWS} AND ts >= ?", (r["when"] - 1,)).fetchone():
        return False
    auc = m["metrics"]["auc"]
    folds = [v for v in auc.get("folds") or [] if v is not None]
    se = float(np.std(folds) / np.sqrt(len(folds))) if len(folds) > 1 else None
    q = ((sp.get("models") or {}).get("quality") or {}).get("metrics", {}).get("auc", {}).get("mean")
    s = list(_JOB.get("sig") or sig)
    con.execute("""INSERT INTO taste_history (ts, n_labels, n_pos, n_fav, n_dislike, auc, quality_auc, se)
                   VALUES (?,?,?,?,?,?,?,?)""", (r["when"], *s, auc["mean"], q, se))
    con.execute("INSERT OR REPLACE INTO taste_history_model VALUES (?, 'reco.taste')", (r["when"],))
    con.commit()
    fw = (r["splits"].get("forward") or {})
    fm = (fw.get("models") or {}).get("reco.taste")
    if fm and fw.get("folds"):
        qf = ((fw["models"].get("quality") or {}).get("metrics", {}).get("auc", {}).get("folds") or [])
        res = []
        for k, (fd, a) in enumerate(zip(fw["folds"], fm["metrics"]["auc"]["folds"])):
            if a is None:
                continue
            n1, n0 = fd["pos"], fd["neg"]
            q1, q2 = a / (2 - a), 2 * a * a / (1 + a)  # Hanley & McNeil, as forward()
            se_ = np.sqrt(max(0.0, (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / max(1, n1 * n0)))
            res.append(dict(t=fd["until"], n_test=fd["n"], n_fav=n1, n_train=fd["train"], auc=round(a, 3),
                            quality_auc=round(qf[k], 3) if k < len(qf) and qf[k] is not None else None,
                            se=round(float(se_), 3)))
        FORWARD.write_text(json.dumps(dict(sig=s, when=r["when"], model="reco.taste", results=res)))
    _CACHE.clear()
    return True


def recommenders():
    """The harness's newest run of every task, for the page: per task and split, the model in use, the task's
    reference (the one it replaced) and the best other model, each with its main metric and interval and its difference
    from the reference; or why there is too little data."""
    from .reco import live
    from .reco.eval import latest
    from .reco.tasks import TASKS
    st = live.settings()
    use = dict(sample_taste="reco.taste" if st["samples"] == "new" else "taste",
               new_songs="reco.taste" if st["samples"] == "new" else "taste",
               mashup_part={"new": "mashup.taste", "w0": "mashup.W0", "old": "mashup.learned"}[st["mashup"]])
    out = []
    for name, r in latest().items():
        task = TASKS.get(name)
        if task is None:
            continue
        met = task.primary[0]
        ref = r.get("reference")
        cur = use.get(name, ref)
        splits = []
        for sp, e in r["splits"].items():
            c = e.get("counts") or {}
            d = dict(split=sp, n=c.get("measured", c.get("n")), pos=c.get("measured_pos", c.get("pos")),
                     neg=c.get("measured_neg", c.get("neg")), groups=c.get("groups"))
            if e.get("insufficient"):
                d["insufficient"] = e["insufficient"]
                splits.append(d)
                continue
            M = e.get("models") or {}

            def row(n, role):
                v = M.get(n)
                if not v:
                    return None
                mm = v["metrics"].get(met) or {}
                vs = (v.get("vs_ref") or {}).get(met)
                return dict(model=n, role=role, mean=mm.get("mean"), ci=mm.get("ci"),
                            vs=vs and dict(diff=vs["diff"], ci=vs.get("ci"), won=vs["won"], of=vs["of"]))
            rows = [row(cur, "in use")]
            if ref != cur:
                rows.append(row(ref, "replaced" if name in use else "reference"))
            others = [(v["metrics"].get(met, {}).get("mean") or 0, n) for n, v in M.items()
                      if n not in (cur, ref, "random")]
            if others:
                rows.append(row(max(others)[1], "best other"))
            d["rows"] = [x for x in rows if x]
            splits.append(d)
        out.append(dict(task=name, about=r.get("about"), metric=met, when=r.get("when"), quick=r.get("quick"), reference=ref,
                        splits=splits))
    order = list(TASKS)
    return sorted(out, key=lambda t: order.index(t["task"]))


def measure_soon(sig):
    """Measure accuracy in a background thread (10-15 s) and add it to the history."""
    if _MEASURING.is_set():
        return
    _MEASURING.set()

    def go():
        try:
            con = _history(_db())
            acc = accuracy(con)
            if acc.get("auc") is not None:
                con.execute("""INSERT INTO taste_history (ts, n_labels, n_pos, n_fav, n_dislike, auc, quality_auc,
                               auc_regression, auc_trees, se) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (time.time(), *sig, acc["auc"], acc["quality_auc"], acc.get("auc_regression"),
                             acc.get("auc_trees"), acc.get("se")))
                con.commit()
            try:  # the time-forward test, kept with the signature it was measured at
                FORWARD.write_text(json.dumps(dict(sig=list(sig), when=time.time(), results=forward(con))))
            except Exception as e:
                print("forward accuracy failed:", e)
            _CACHE.clear()
        finally:
            _MEASURING.clear()
    threading.Thread(target=go, daemon=True).start()


def _edits():
    try:
        from .suggest import stats
        return stats()
    except Exception:
        return None


def explain():
    con = _history(_db())
    L = _library(con)
    if L is None:
        return dict(ready=False)
    labels = item_labels(con, None, L["durs"])
    _old_payload(None)  # fits (or reuses) the earlier model: what it learned is read from it
    from .taste import _FIT
    res = _FIT.get(None) or {}
    new = _new_fit()
    try:
        from .reco.eval import RUNS
        runs = max((f.name for f in RUNS.glob("*-sample_taste.json")), default=None)
    except Exception:
        runs = None
    key = (res.get("_key"), new.key if new is not None else None, new.when if new is not None else None, runs)
    if _CACHE.get("key") == key and not _MEASURING.is_set() and not _job_alive():
        return dict(_CACHE["value"], edits=_edits(), recommenders=_recos(), settings=_settings())

    # what it learns from
    fav = {r[0] for r in con.execute("SELECT path FROM favorites")}
    kinds = dict(favourites=0, dislikes=0, liked_by_listening=0, skipped=0)
    for p, (y, w) in labels.items():
        if p in fav:
            kinds["favourites"] += 1
        elif y == 1:
            kinds["liked_by_listening"] += 1
        elif w >= 1.5:
            kinds["dislikes"] += 1
        else:
            kinds["skipped"] += 1
    n_listen = con.execute("SELECT COUNT(*) FROM events WHERE type='listen'").fetchone()[0]

    # accuracy: the last measurement; a new one runs in the background when your ratings changed since
    # the history of the model in use (the shared one's rows have model = "reco.taste")
    mq = NEW_ROWS if new is not None else f"NOT {NEW_ROWS}"
    last = con.execute(f"SELECT * FROM taste_history WHERE {mq} ORDER BY ts DESC LIMIT 1").fetchone()
    if new is not None:
        sig = (new.t.n, new.t.n_pos, len(fav), kinds["dislikes"])
    else:
        sig = (res.get("n_labels"), res.get("n_pos"), len(fav), kinds["dislikes"])
    if new is not None and _new_history(con, sig):  # a measurement landed
        last = con.execute(f"SELECT * FROM taste_history WHERE {mq} ORDER BY ts DESC LIMIT 1").fetchone()
    stale = not last or (last["n_labels"], last["n_pos"], last["n_fav"], last["n_dislike"]) != sig
    if stale:
        measure_new_soon(sig) if new is not None else measure_soon(sig)
    measuring = _MEASURING.is_set() or (new is not None and _job_alive())
    acc = dict(auc=last["auc"], quality_auc=last["quality_auc"], when=last["ts"], auc_regression=last["auc_regression"],
               auc_trees=last["auc_trees"]) if last else dict(auc=None)
    acc.update(measuring=measuring, n_fav=len(fav), model="reco.taste" if new is not None else "taste")
    hist = [dict(r) for r in con.execute(f"SELECT * FROM taste_history WHERE {mq} ORDER BY ts")]
    fwd = None
    try:
        fwd = json.loads(FORWARD.read_text())
        if (fwd.get("model") == "reco.taste") != (new is not None):
            fwd = None  # measured on the other model: shown again once this one is measured
    except Exception:
        if not _MEASURING.is_set() and new is None:  # never measured yet: once, in the background
            def go():
                try:
                    FORWARD.write_text(json.dumps(dict(sig=list(sig), when=time.time(), results=forward(_db()))))
                    _CACHE.clear()
                except Exception as e:
                    print("forward accuracy failed:", e)
            threading.Thread(target=go, daemon=True).start()
    try:
        src = sources(con)
    except Exception:
        src = []

    learned = {}
    if "beta" in res:
        beta, fz = res["beta"], L["fz"]
        b_eng = beta[N_PCA + len(CATS) + len(KINDS):]
        # these weights are "with the sound held equal": e.g. among samples that sound alike, the longer one
        learned["features"] = sorted([[e, round(float(b), 2)] for e, b in zip(ENG, b_eng)], key=lambda x: -x[1])
        from .models import clap
        T = clap().embed_text(tuple(WORDS))
        Z = ((T / np.linalg.norm(T, axis=1, keepdims=True)) * np.linalg.norm(L["E"], axis=1).mean() - fz.mu) @ fz.P / fz.sd
        sw = Z @ beta[:N_PCA]
        sw = (sw - sw.mean()) / (sw.std() + 1e-9)
        o = np.argsort(-sw)
        learned["words_up"] = [[WORDS[i], round(float(sw[i]), 2)] for i in o[:10]]
        learned["words_down"] = [[WORDS[i], round(float(sw[i]), 2)] for i in o[::-1][:10]]

    if learned and new is not None:
        learned["from"] = "the earlier model (taste.py): the shared model's effects aren't read out yet"

    # examples
    paths = L["paths"]
    score = np.asarray(res.get("score", np.zeros(len(paths))))
    unc = np.asarray(res.get("unc", np.zeros(len(paths))))
    if new is not None:  # ranked by the model in use: its posterior mean, and its sd for "teach it the most"
        ix = np.array([new.pos.get(p, -1) for p in paths])
        h = ix >= 0
        zz = np.where(h, new.z[np.maximum(ix, 0)], np.nan)
        score = np.where(np.isfinite(zz), zz, np.nanmin(new.z) - 1)
        unc = np.where(h, new.sd[np.maximum(ix, 0)], 0.0)
    heard = {r[0] for r in con.execute("SELECT DISTINCT path FROM events")}
    info = {r["path"]: dict(path=r["path"], id=r["id"], cat=r["category"], sub=r["subtype"], artist=r["artist"],
                            title=r["title"])
            for r in con.execute("""SELECT s.path, s.id, s.category, s.subtype, t.artist, t.title
                                    FROM samples s JOIN tracks t ON t.id=s.track_id""")}
    pct = np.argsort(np.argsort(score)) / max(1, len(score) - 1)  # percentile of each sample's score
    def ex(i, why=None):
        d = dict(info.get(paths[i], dict(path=paths[i])), pct=round(float(pct[i]) * 100))
        if why:
            d["why"] = why
        return d
    order = np.argsort(-score)
    unheard, seen_song = [], set()
    for i in order:  # one sample per song, so the lists show variety
        if paths[i] in heard or paths[i] in labels:
            continue
        song = (info.get(paths[i], {}).get("artist"), info.get(paths[i], {}).get("title"))
        if song in seen_song:
            continue
        seen_song.add(song); unheard.append(i)
        if len(unheard) >= 3000:
            break
    examples = dict(
        top=[ex(i) for i in unheard[:8]],
        unsure=[ex(i) for i in sorted(unheard[:2000], key=lambda i: -unc[i])[:8]],
        missed=[ex(i, "you starred it") for i in
                sorted([L["pos"][p] for p in fav if p in L["pos"]], key=lambda i: score[i])[:6]],
        wrong=[ex(i, "you said not for me") for i in
               sorted([L["pos"][p] for p, (y, w) in labels.items() if y == 0 and w >= 1.5 and p in L["pos"]],
                      key=lambda i: -score[i])[:6]],
    )
    by_cat, by_kind = {}, {}
    meta = L["meta"]
    for i, p in enumerate(paths):
        m = meta.get(p, {})
        if m.get("category"):
            by_cat.setdefault(m["category"], []).append(pct[i] * 100)
        if m.get("kind"):
            by_kind.setdefault(m["kind"], []).append(pct[i] * 100)
    edits = _edits()
    value = dict(ready=True, accuracy=acc, edits=edits, history=hist, forward=fwd, sources=src, signals=dict(kinds, listens=n_listen,
                 labelled=res.get("n_labels"), positive=res.get("n_pos")), learned=learned, examples=examples,
                 by_category=sorted([[c, round(float(np.mean(v))), len(v)] for c, v in by_cat.items()],
                                    key=lambda x: -x[1]),
                 by_kind=sorted([[c, round(float(np.mean(v))), len(v)] for c, v in by_kind.items()], key=lambda x: -x[1]),
                 model=("the shared taste model: a hierarchical Bayesian logistic regression on CLAP sound (32 "
                        "directions and a smooth nonlinear term), the sample's type and measurements, with song and "
                        "artist effects, learning from samples and from what you keep in Mashup (reco/models/taste.py)")
                 if new is not None else
                 "Bayesian logistic regression on CLAP sound features (64 dimensions), category, kind, ten sound "
                 "measurements and the song's style, blended 70/30 with closeness to your nearest favourite, "
                 "plus a lift for songs you've starred samples from")
    _CACHE.update(key=key, value=value)
    return dict(value, recommenders=_recos(), settings=_settings())


def _recos():
    try:
        return dict(tasks=recommenders(), running=_job_alive() and bool(_JOB.get("all")))
    except Exception as e:
        return dict(tasks=[], error=str(e), running=False)


def _settings():
    from .reco import live
    return dict(current=live.settings(), choices={k: list(v) for k, v in live.CHOICES.items()}, about=live.ABOUT)


def forward(con=None, min_fav=18):
    """Time-forward accuracy: how well the model, as it knew you at a moment, ranks what you heard *next*.

    The cross-validated AUC above shuffles all your history, and it drifts down for reasons that aren't the model
    getting worse: as recommendations improve you mostly hear samples the model already likes, so telling your stars
    from the rest gets harder (the test gets harder, not the model worse), and older ratings describe older taste.
    This replays your history instead: train on everything before a cutoff, then test on the samples you first heard
    after it (★ vs heard and not starred). It is still shaped by what you chose to hear; sources() is the test that
    isn't (star rates by where a sample was played from, against random). Cutoffs fall where about min_fav new favourites have come in."""
    con = con or _db()
    L = _library(con)
    pos = L["pos"]
    favs = {r[0] for r in con.execute("SELECT path FROM favorites") if r[0] in pos}
    first = {}
    for r in con.execute("SELECT path, MIN(ts) t FROM events WHERE type IN ('listen','star') GROUP BY path"):
        if r["path"] in pos:
            first[r["path"]] = r["t"]
    q = np.zeros(len(L["paths"]))
    for r in con.execute("SELECT path, quality FROM samples"):
        if r[0] in pos:
            q[pos[r[0]]] = r[1] or 0
    order = sorted(first, key=first.get)
    out, chunk, start = [], [], None
    for p in order:
        chunk.append(p)
        if sum(q in favs for q in chunk) >= min_fav:
            out.append(chunk)
            chunk = []
    res = []
    for k, ch in enumerate(out[1:], 1):  # the first chunk has nothing before it to learn from
        cut = first[ch[0]]
        lab = item_labels(con, None, L["durs"], until=cut)
        if sum(1 for v in lab.values() if v[0] == 1) < 10:
            continue
        r = fit(None, labels=lab)
        y = np.array([p in favs for p in ch])
        idx = [pos[p] for p in ch]
        a = _auc(y, np.asarray(r["score"])[idx])
        b = _auc(y, q[idx])
        if a is not None:
            n1, n0 = int(y.sum()), int(len(y) - y.sum())  # Hanley & McNeil (1982): how much an AUC this size wobbles
            q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
            se = np.sqrt(max(0.0, (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)))
            res.append(dict(t=cut, n_test=len(ch), n_fav=n1, n_train=len(lab), auc=round(a, 3),
                            quality_auc=round(b, 3), se=round(float(se), 3)))
    return res


def sources(con=None):
    """Where your stars come from: for every sample whose first play was logged with where it was played from (a crate
    pick, a crate wildcard, the list under a sort, galaxy, search…), the share you then starred or ✕'d. The direct
    measure of whether recommendations help: "for you" and crate picks should beat best quality, random and wildcards."""
    con = con or _db()
    fav = {r[0] for r in con.execute("SELECT path FROM favorites")}
    nope = {r[0] for r in con.execute("SELECT path FROM events WHERE type='dislike' AND value=1")}
    first = {}
    for r in con.execute("SELECT path, context FROM events WHERE type='listen' AND context IS NOT NULL ORDER BY ts"):
        if r["path"] in first:
            continue
        try:
            src = json.loads(r["context"]).get("src")
        except Exception:
            src = None
        if src:
            first[r["path"]] = src
    by = {}
    for p, src in first.items():
        d = by.setdefault(src, [0, 0, 0])
        d[0] += 1
        d[1] += p in fav
        d[2] += p in nope
    return sorted(([k, n, round(st / n, 3), round(no / n, 3)] for k, (n, st, no) in by.items()), key=lambda x: -x[1])
