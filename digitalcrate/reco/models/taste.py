"""The shared taste model: one Bayesian model of the sound you like, usable by every surface (docs/plans/recommend.md).

    from digitalcrate.reco.models import taste as T
    t = T.fit(con, until=None)          # about 10 s on the full library
    mean, sd = t.score(items)           # latent taste (logit scale) and its posterior sd, for any item with a CLAP
                                        # embedding: ("sample", path), ("part", track, stem, bar0, n), ("song", id),
                                        # ("video", id); NaN for an item without one
    p = t.proba(items)                  # P(you'd star it, having heard it), calibrated
    t.about()                           # what was learned: the size of each effect, the data, the fit time

The model (a hierarchical Bayesian logistic regression, Laplace posterior):

    logit P(star | heard) = b + sound . z(CLAP) + kernel . k(CLAP) + meta . m + song[s] + artist[a]

  sound     the first 32 principal directions of CLAP over the library, whitened
  kernel    a smooth nonlinear term: a Gaussian-process prior on CLAP (RBF on the unit sphere, length 0.5 in squared
            distance) through 400 landmark samples (Nystrom). Taste is several moods, not one direction
  meta      category, kind, duration, quality, loudness, key strength, has a tempo; stem source, subtype, instrument,
            the song's genre, dominance, loop quality, grain, the song's vocal and clean fractions. Standardized over
            the library, so a missing value (a stem part has no category) is the average
  song, artist   random effects: each song's and artist's offset, shrunk toward 0 by how much songs differ (partial
            pooling) rather than the mean label of a song's rated samples. A song you never rated gets 0 and the song
            variance added to its uncertainty
  priors    one Gaussian prior per block, its precision set by the evidence (MacKay's updates), so the amount of
            smoothing follows the amount of data: no hand-set weights

What counts as evidence:
  samples   a favorite (or a sample in a collection) is a 1; a sample you heard and didn't star (or ✕'d, or unstarred)
            is a 0. Samples you never heard are not used: "unheard is not disliked". The probability is therefore
            "would you star it once heard", which is what the held-out test asks
  Mashup    each stem of a song you used: 1 if a part of it was ever saved, kept, locked, snapshotted or in a saved
            mix, else 0 if re-rolled or removed. Its own intercept (offset) and a trust factor on the same sound, song
            and artist terms: the slope of the Mashup outcomes on the taste learned from samples alone (0 to 1; below
            0.05 the Mashup evidence is left out; 0.44 on the library today). So a song you keep in Mashup lifts its
            samples, and the reverse

Calibration: Platt scaling fitted on cross-fitted predictions (5 folds by song inside the training data, the prior
precisions held at the full fit's), applied to the posterior predictive probability (probit approximation).

Measured on the harness's sample_taste task (193 favorites, 3,390 heard and not starred; runs under _data/reco/runs),
against the live blend: AUC by song +0.018 / +0.029 (standard seeds / three fresh seeds, the latter's interval clear of
zero), forward in time +0.078 [+0.023, +0.126], by sample +0.009 (no worse); average precision +0.04 to +0.08; expected
calibration error 0.025 vs 0.15 for the live probability, log loss 0.17 vs 0.30. A fit takes about 10 s on the full
library (25k samples), 8 s of it the two evidence-tuned fits, the rest the calibration's five.
Tried and left out: labels from listening behavior (the live rule, or a continuation stage "replayed or not" sharing
the latent taste), unheard samples as weak negatives, the song's Discogs style embedding, sound directions per
category, 64 or 128 principal directions, fixed prior precisions, scout finds as evidence.
"""
import time
from collections import Counter

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.linalg.lapack import dpotri
import scipy.sparse as sp

from .. import log as L
from ..items import Items, artist_key

K_SOUND = 32          # principal directions of CLAP
N_LANDMARKS = 400     # kernel landmarks (Nystrom)
ELL2 = 0.5            # kernel length scale, squared (in squared distance between unit vectors: median pair 1.6)
CATS = ["Vocals", "Vocal Atmospheres", "Pads & Atmospheres", "Chords & Keys", "Melodies & Leads", "Textures & Field",
        "Bass & Sub", "Percussion", "Strings & Orchestral"]
KINDS = ["loop", "free", "phrase", "oneshot"]
POSITIVE_PART = ("save", "kept", "lock", "snap", "in_saved_mix")
NEGATIVE_PART = ("reroll", "remove")
STEM_SOURCE = {"vocals": "vocals", "drums": "drums", "other": "other", "bass": "bass"}  # a stem part's source column
_LIB = {}


def _sig(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def _probit(m, s):
    """The posterior predictive logit of a logistic model with a Gaussian logit (MacKay's approximation)."""
    return m / np.sqrt(1 + np.pi * s ** 2 / 8)


# ---------------------------------------------------------------- the library's features (label-free, cached)

def library(con, seed=0):
    """Every library sample's features and links, kept until samples are added or removed."""
    key = tuple(con.execute("SELECT COUNT(*), MAX(rowid) FROM samples").fetchone()) + (seed,)
    if _LIB.get("key") == key:
        return _LIB
    cols = {r[1] for r in con.execute("PRAGMA table_info(samples)")}
    tcols = {r[1] for r in con.execute("PRAGMA table_info(tracks)")}
    opt = lambda c, have, t: f"{t}.{c}" if c in have else f"NULL AS {c}"
    rows = con.execute(f"""SELECT s.path, s.clap, s.category, s.kind, s.dur, s.quality, s.loudness, s.key_strength,
                                  s.bpm, s.track_id, t.artist, {opt('source', cols, 's')}, {opt('subtype', cols, 's')},
                                  {opt('instrument', cols, 's')}, {opt('dominance', cols, 's')},
                                  {opt('loop_q', cols, 's')}, {opt('grain', cols, 's')}, {opt('genre', tcols, 't')},
                                  {opt('vocal_frac', tcols, 't')}, {opt('clean_frac', tcols, 't')}
                           FROM samples s JOIN tracks t ON t.id=s.track_id
                           WHERE s.path NOT LIKE '_Reference/%' AND s.clap IS NOT NULL""").fetchall()
    if not rows:
        return None
    E = np.stack([np.frombuffer(r["clap"], np.float16).astype(np.float32) for r in rows])
    E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-9
    mu = E.mean(0)
    Zc = (E - mu).astype(np.float64)
    w, V = np.linalg.eigh(Zc.T @ Zc)
    k = min(K_SOUND, len(E) - 1)
    P = V[:, ::-1][:, :k]
    sd = np.sqrt(np.maximum(w[::-1][:k], 1e-12) / len(E)) + 1e-9
    rng = np.random.default_rng(seed)
    Lm = E[rng.choice(len(E), min(N_LANDMARKS, len(E)), replace=False)].astype(np.float64)
    ev, U = np.linalg.eigh(np.exp(-(2 - 2 * Lm @ Lm.T) / (2 * ELL2)))
    keep = ev > 1e-6 * ev.max()

    # metadata: sample columns, then song columns (a part or a song has only the latter)
    g = lambda c, d: np.array([r[c] if r[c] is not None else d for r in rows], float)
    sample_cols, song_cols, names = [], [], []
    for c, levels in (("category", CATS), ("kind", KINDS)):
        for v in levels:
            sample_cols.append(np.array([r[c] == v for r in rows], float)); names.append(f"{c}={v}")
    for c, v in (("log duration", np.log1p(g("dur", 5))), ("quality", g("quality", .5)),
                 ("loudness", g("loudness", -20)), ("key strength", g("key_strength", .5)),
                 ("has a tempo", (g("bpm", 0) > 0) * 1.0)):
        sample_cols.append(v); names.append(c)
    levels = {}
    for c, top in (("source", 6), ("subtype", 10), ("instrument", 12)):
        levels[c] = [v for v, _ in Counter(r[c] for r in rows if r[c]).most_common(top)]
        for v in levels[c]:
            sample_cols.append(np.array([r[c] == v for r in rows], float)); names.append(f"{c}={v}")
    for c in ("dominance", "loop_q", "grain"):
        v = np.array([r[c] if r[c] is not None else np.nan for r in rows], float)
        h = np.isfinite(v)
        sample_cols += [np.where(h, v, np.nanmean(v) if h.any() else 0), h * 1.0]; names += [c, f"has {c}"]
    n_sample = len(sample_cols)
    levels["genre"] = [v for v, _ in Counter(r["genre"] for r in rows if r["genre"]).most_common(12)]
    for v in levels["genre"]:
        song_cols.append(np.array([r["genre"] == v for r in rows], float)); names.append(f"genre={v}")
    for c in ("vocal_frac", "clean_frac"):
        v = np.array([r[c] if r[c] is not None else np.nan for r in rows], float)
        h = np.isfinite(v)
        song_cols += [np.where(h, v, np.nanmean(v) if h.any() else 0), h * 1.0]; names += [c, f"has {c}"]
    M = np.stack(sample_cols + song_cols, 1)
    mmu, msd = M.mean(0), M.std(0)
    msd = np.where(msd > 1e-9, msd, 1.0)
    tid = np.array([r["track_id"] for r in rows])
    art = [artist_key(r["artist"]) for r in rows]
    _LIB.clear()
    _LIB.update(key=key, paths=[r["path"] for r in rows], E=E, mu=mu, P=P, sd=sd, Lm=Lm,
                T=U[:, keep] / np.sqrt(ev[keep]), M=(M - mmu) / msd, mmu=mmu, msd=msd, names=names, n_sample=n_sample,
                levels=levels, tid=tid, art=art, t2a=dict(zip(tid.tolist(), art)),
                dur={r["path"]: r["dur"] or 0 for r in rows})
    _LIB["pos"] = {p: i for i, p in enumerate(_LIB["paths"])}
    _LIB["first_song"] = {}
    for i, t in enumerate(tid.tolist()):
        _LIB["first_song"].setdefault(t, i)
    return _LIB


def _sound(lib, E):
    """[intercept | whitened principal directions | kernel features] for unit CLAP rows."""
    Z = ((E - lib["mu"]) @ lib["P"]) / lib["sd"]
    F = np.exp(-(2 - 2 * E @ lib["Lm"].T) / (2 * ELL2)) @ lib["T"]
    return np.hstack([np.ones((len(E), 1)), Z, F])


def _song_meta(lib, track):
    """The song columns of the metadata (genre, vocal and clean fractions) for a song, standardized; zeros if unknown."""
    i = lib["first_song"].get(track)
    out = np.zeros(lib["M"].shape[1])
    if i is not None:
        out[lib["n_sample"]:] = lib["M"][i, lib["n_sample"]:]
    return out


# ---------------------------------------------------------------- evidence

def evidence(con, until=None):
    """What you told it, before until: (sample paths -> 1 / 0, Mashup (track, stem) -> 1 / 0). A favorite or a
    collection member is 1; heard (a listen, a ✕, an unstar) and not starred is 0. A Mashup stem is 1 if a part of it
    was ever saved, kept, locked, snapshotted or in a saved mix, else 0 if one was re-rolled or removed."""
    samples, parts = {}, {}
    for it in L.interactions(con, until=until, surfaces=["samples", "mashup"]):
        if it.kind == "sample":
            if it.action in ("favorite", "collect"):
                samples[it.item[1]] = 1.0
            elif it.action in ("listen", "dislike", "unstar") and it.item[1] not in samples:
                samples[it.item[1]] = 0.0
        elif it.kind == "part":
            k = (it.item[1], it.item[2])
            if it.action in POSITIVE_PART:
                parts[k] = 1.0
            elif it.action in NEGATIVE_PART:
                parts.setdefault(k, 0.0)
    # a favorite's own row wins over its listens whatever the order; a star taken back is no longer in favorites
    fav = {it.item[1] for it in L.interactions(con, until=until, tables=["favorites", "collection_items"])}
    for p in fav:
        samples[p] = 1.0
    return samples, parts


# ---------------------------------------------------------------- the fit: logistic GLMM, Laplace, evidence updates

def glmm(X, groups, y, blocks, alpha=None, eb=True, iters=15, theta=None):
    """MAP fit of a logistic model with a Gaussian prior per block of columns and random-intercept groups, the Laplace
    posterior covariance, and MacKay's evidence updates of each block's precision (eb).
    X: dense (n, p) design; groups: [(level index per row, -1 for none; n levels; value per row)]; blocks: column
    slices of X with their own prior (columns in no block, the intercepts, get a nearly flat prior).
    -> (theta, cov, alpha per block, all blocks as slices of theta)"""
    n, pf = X.shape
    G = [sp.csr_matrix((v[gi >= 0], (np.flatnonzero(gi >= 0), gi[gi >= 0])), shape=(n, ng)) for gi, ng, v in groups]
    GT = [g.T.tocsr() for g in G]
    off = np.cumsum([0, pf] + [g.shape[1] for g in G])
    p = off[-1]
    allb = list(blocks) + [slice(off[k + 1], off[k + 2]) for k in range(len(G))]
    alpha = np.ones(len(allb)) if alpha is None else np.array(alpha, float)
    th = np.zeros(p) if theta is None else theta.copy()

    def lin(th):
        m = X @ th[:pf]
        for k, g in enumerate(G):
            m = m + g @ th[off[k + 1]:off[k + 2]]
        return m

    def hess(W, A):
        H = np.zeros((p, p))
        XW = X * W[:, None]
        H[:pf, :pf] = X.T @ XW
        for k in range(len(G)):
            s = slice(off[k + 1], off[k + 2])
            H[s, :pf] = GT[k] @ XW
            H[:pf, s] = H[s, :pf].T
            for j in range(k + 1):
                t = slice(off[j + 1], off[j + 2])
                H[s, t] = (GT[k] @ G[j].multiply(W[:, None])).toarray()
                H[t, s] = H[s, t].T
        H[np.diag_indices(p)] += A
        return H

    def grad(r, A, th):
        g = np.empty(p)
        g[:pf] = X.T @ r
        for k in range(len(G)):
            g[off[k + 1]:off[k + 2]] = GT[k] @ r
        return g + A * th

    for _ in range(iters if eb else 1):
        A = np.full(p, 1e-2)
        for b, a in zip(allb, alpha):
            A[b] = a
        for _ in range(40):
            pr = _sig(lin(th))
            c = cho_factor(hess(pr * (1 - pr), A), lower=True)
            step = cho_solve(c, grad(pr - y, A, th))
            th -= step
            if np.abs(step).max() < 1e-4:
                break
        S, info = dpotri(c[0], lower=1)  # the inverse from the last Cholesky factor (th moved by < 1e-4 since)
        S = np.tril(S) + np.tril(S, -1).T
        if not eb:
            break
        new = alpha.copy()
        for k, b in enumerate(allb):
            nb = b.stop - b.start
            if nb:
                gam = nb - alpha[k] * np.trace(S[b, b])  # how many of the block's parameters the data determines
                new[k] = np.clip(max(gam, 1e-3) / max(float(th[b] @ th[b]), 1e-9), 1e-2, 1e4)
        done = np.allclose(np.log(new), np.log(alpha), atol=0.02)
        alpha = new
        if done:
            break
    return th, S, alpha, allb


class Taste:
    """A fitted shared taste model. score(items) -> (mean, sd) of the latent taste; proba(items) -> calibrated
    P(star | heard). Built by fit()."""

    def __init__(self, lib, items):
        self.lib, self.items = lib, items

    # ---------------------------------------------------------------- design rows
    def _rows(self, items):
        """(X rows without the stage intercepts, song ids, artist keys, ok) for any items."""
        lib = self.lib
        n = len(items)
        X = np.zeros((n, self.pf))
        songs, arts, ok = [None] * n, [None] * n, np.zeros(n, bool)
        lib_i = [lib["pos"].get(it[1]) if it[0] in ("sample", "move") else None for it in items]
        have = [k for k, i in enumerate(lib_i) if i is not None]
        if have:
            r = np.array([lib_i[k] for k in have])
            X[have] = np.hstack([_sound(lib, lib["E"][r].astype(np.float64)), lib["M"][r]])
            ok[have] = True
            for k, i in zip(have, r):
                songs[k], arts[k] = int(lib["tid"][i]), lib["art"][i]
        rest = [k for k in range(n) if lib_i[k] is None]
        if rest:
            Ec, m = self.items.clap([items[k] for k in rest])
            for j, k in enumerate(rest):
                if not m[j]:
                    continue
                it = tuple(items[k])
                tr = self.items.song_of(it)
                meta = _song_meta(lib, tr) if tr is not None else np.zeros(lib["M"].shape[1])
                if it[0] == "part":
                    src = STEM_SOURCE.get(str(it[2]))
                    for v in lib["levels"].get("source", []):
                        c = lib["names"].index(f"source={v}")
                        meta[c] = ((v == src) - lib["mmu"][c]) / lib["msd"][c]
                X[k] = np.r_[_sound(lib, Ec[j:j + 1].astype(np.float64))[0], meta]
                ok[k] = True
                songs[k] = tr
                arts[k] = (lib["t2a"].get(tr) or self.items.artist_of(it)) if tr is not None else None
        return X, songs, arts, ok

    def score(self, items):
        """(mean, sd) of the latent taste (logit of P(star | heard), before calibration) for any items; NaN where an
        item has no CLAP embedding. The sd is the posterior's: larger for sounds unlike anything you rated, and for a
        song or artist you never rated (their prior variance is added)."""
        items = [tuple(it) for it in items]
        return self._predict(*self._rows(items))

    def score_like(self, E, path):
        """(mean, sd) for CLAP embeddings E (rows) as if each were the library sample at path: its metadata, song and
        artist with this sound (the edit suggestions' critic scores renders of a sample this way). NaN if path is not
        a library sample."""
        lib = self.lib
        E = np.atleast_2d(np.asarray(E, np.float64))
        E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
        i = lib["pos"].get(path)
        n = len(E)
        if i is None:
            return np.full(n, np.nan), np.full(n, np.nan)
        X = np.hstack([_sound(lib, E), np.repeat(lib["M"][i][None], n, 0)])
        return self._predict(X, [int(lib["tid"][i])] * n, [lib["art"][i]] * n, np.ones(n, bool))

    def _predict(self, X, songs, arts, ok):
        pf, th, S = self.pf, self.th, self.S
        mean = X @ th[:pf]
        var = ((X @ S[:pf, :pf]) * X).sum(1)
        var += self.residual * np.maximum(0, 1 - (X[:, self.kern] ** 2).sum(1))  # kernel beyond the landmarks
        js = []
        for (kind, lv, b, a), keys in zip(self.groups, (songs, arts)):
            j = np.array([lv.get(k, -1) if k is not None else -1 for k in keys], int)
            h = j >= 0
            jj = np.where(h, b.start + np.maximum(j, 0), -1)
            mean[h] += th[jj[h]]
            var[h] += S[jj[h], jj[h]] + 2 * (X[h] * S[:pf, jj[h]].T).sum(1)
            var[~h] += 1 / a
            js.append(jj)
        if len(js) == 2:
            both = (js[0] >= 0) & (js[1] >= 0)
            var[both] += 2 * S[js[0][both], js[1][both]]
        mean[~ok] = np.nan
        sd = np.sqrt(np.maximum(var, 0))
        sd[~ok] = np.nan
        return mean, sd

    def proba(self, items):
        """Calibrated P(you'd star it, having heard it); NaN where an item has no CLAP embedding."""
        m, s = self.score(items)
        a, b = self.platt
        return _sig(a * _probit(m, s) + b)

    def about(self):
        names = ["sound", "kernel", "meta", "song", "artist"]
        return dict(n=self.n, n_pos=self.n_pos, n_parts=self.n_parts, trust=round(self.trust, 3),
                    prior_sd={k: round(float(1 / np.sqrt(a)), 3) for k, a in zip(names, self.alpha)},
                    platt=[round(float(x), 3) for x in self.platt], seconds=round(self.seconds, 1))


def _design(lib, rows):
    return np.hstack([_sound(lib, lib["E"][rows].astype(np.float64)), lib["M"][rows]])


def _fit_core(t, Xs, songs, ys, stage, trust, alpha=None, eb=True):
    """One GLMM fit of the stacked evidence: rows of stage 1 (Mashup) scaled by trust, with their own intercept."""
    lib = t.lib
    lam = np.where(stage == 1, trust, 1.0)
    X = Xs * lam[:, None]
    X[:, 0] = stage == 0
    X = np.hstack([X, (stage == 1)[:, None] * 1.0])
    arts = [lib["t2a"].get(s) if s is not None else None for s in songs]
    lv_s = {v: k for k, v in enumerate(sorted({s for s in songs if s is not None}))}
    lv_a = {v: k for k, v in enumerate(sorted({a for a in arts if a}))}
    groups = [(np.array([lv_s.get(s, -1) if s is not None else -1 for s in songs]), len(lv_s), lam),
              (np.array([lv_a.get(a, -1) if a else -1 for a in arts]), len(lv_a), lam)]
    th, S, al, allb = glmm(X, groups, ys, [t.snd, t.kern, t.meta], alpha=alpha, eb=eb)
    return th, S, al, allb, lv_s, lv_a


def fit(con, until=None, seed=0, surfaces=("samples", "mashup"), calibrate=True):
    """Fit the shared taste model on what con holds (before until: unix seconds). -> Taste, or None if there is too
    little to learn from (fewer than 3 favorites or 3 heard-and-not-starred samples)."""
    t0 = time.time()
    lib = library(con, seed)
    if lib is None:
        return None
    samples, parts = evidence(con, until)
    lab = [(lib["pos"][p], y) for p, y in sorted(samples.items()) if p in lib["pos"]]
    if sum(y for _, y in lab) < 3 or sum(1 - y for _, y in lab) < 3:
        return None
    t = Taste(lib, Items(con))
    k = lib["P"].shape[1]
    nk = lib["T"].shape[1]
    t.snd, t.kern, t.meta = slice(1, 1 + k), slice(1 + k, 1 + k + nk), slice(1 + k + nk, 1 + k + nk + lib["M"].shape[1])
    t.pf = t.meta.stop
    rows = np.array([i for i, _ in lab])
    Xs = _design(lib, rows)
    ys = np.array([y for _, y in lab], float)
    songs = [int(s) for s in lib["tid"][rows]]
    stage = np.zeros(len(rows), int)
    t.n, t.n_pos, t.n_parts = len(rows), int(ys.sum()), 0
    if "mashup" in surfaces and parts:
        ks = sorted(parts)
        Xp, s_p, _, okp = t._rows([("part", tr, st, 0, 4) for tr, st in ks])
        if okp.sum() >= 3:
            Xs = np.vstack([Xs, Xp[okp]])
            ys = np.r_[ys, [parts[q] for q, g in zip(ks, okp) if g]]
            songs += [s for s, g in zip(s_p, okp) if g]
            stage = np.r_[stage, np.ones(int(okp.sum()), int)]
            t.n_parts = int(okp.sum())
    smp = stage == 0
    th, S, al, allb, lv_s, lv_a = _fit_core(t, Xs[smp], [s for s, g in zip(songs, smp) if g], ys[smp], stage[smp], 1.0)
    trust = 0.0
    if t.n_parts:
        # how strongly the taste learned from samples shows in Mashup choices: a logistic fit of each stem's outcome on
        # its sample-taste score (sound, song, artist), with its own intercept; then one joint fit with that trust
        f = _latent(t, th, Xs[~smp], [s for s, g in zip(songs, smp) if not g], lv_s, lv_a, allb)
        trust = float(np.clip(_logit1(f, ys[~smp])[0], 0.0, 1.0))
        if trust > 0.05:
            th, S, al, allb, lv_s, lv_a = _fit_core(t, Xs, songs, ys, stage, trust, alpha=al)
        else:  # Mashup choices say nothing about this taste (yet): left out
            Xs, songs, ys, stage = Xs[smp], [s for s, g in zip(songs, smp) if g], ys[smp], stage[smp]
            t.n_parts, trust = 0, 0.0
    t.th, t.S, t.alpha, t.trust = th, S, al, trust
    t.groups = [("song", lv_s, allb[3], al[3]), ("artist", lv_a, allb[4], al[4])]
    t.residual = 1 / al[1]
    t.platt = (1.0, 0.0)
    if calibrate:
        t.platt = _platt(t, Xs, songs, ys, stage, seed)
    t.seconds = time.time() - t0
    return t


def _latent(t, th, X, songs, lv_s, lv_a, allb):
    m = X[:, :t.pf] @ th[:t.pf]
    for s_, (lv, b) in zip((songs, [t.lib["t2a"].get(s) if s is not None else None for s in songs]),
                          ((lv_s, allb[3]), (lv_a, allb[4]))):
        for i, key in enumerate(s_):
            j = lv.get(key) if key is not None else None
            if j is not None:
                m[i] += th[b.start + j]
    return m


def _logit1(f, y, prior=1.0, iters=100):
    """MAP of y ~ Bernoulli(sigmoid(a f + b)) with a ~ N(1, 1/prior) and a nearly flat prior on b (Newton with step
    halving). -> (a, b)"""
    f0 = f.mean() if len(f) else 0.0
    x = f - f0

    def obj(a, c):
        z = a * x + c
        return float((np.logaddexp(0, z) - y * z).sum() + prior * (a - 1) ** 2 / 2 + 1e-4 * c * c / 2)

    a, c = 1.0, float(np.log((y.mean() + 1e-3) / (1 - y.mean() + 1e-3))) if len(y) else 0.0
    cur = obj(a, c)
    for _ in range(iters):
        p = _sig(a * x + c)
        g = np.array([((p - y) * x).sum() + prior * (a - 1), (p - y).sum() + 1e-4 * c])
        W = p * (1 - p)
        H = np.array([[(W * x * x).sum() + prior, (W * x).sum()], [(W * x).sum(), W.sum() + 1e-4]])
        step = np.linalg.solve(H, g)
        k = 1.0
        while k > 1e-4 and obj(a - k * step[0], c - k * step[1]) > cur:
            k /= 2
        a, c = a - k * step[0], c - k * step[1]
        new = obj(a, c)
        if cur - new < 1e-10:
            break
        cur = new
    return a, c - a * f0


def _platt(t, Xs, songs, ys, stage, seed, k=5):
    """Platt scaling on cross-fitted predictive logits of the sample rows: folds by song, priors held at the full
    fit's (one Newton solve per fold, no evidence updates)."""
    smp = np.flatnonzero(stage == 0)
    us = sorted({songs[i] for i in smp})
    np.random.default_rng(seed).shuffle(us)
    fold = {s: j % k for j, s in enumerate(us)}
    f = np.array([fold[songs[i]] for i in smp])
    oof = np.zeros(len(smp))
    for j in range(k):
        te = smp[f == j]
        if not len(te) or ys[np.setdiff1d(np.arange(len(ys)), te)].sum() < 3:
            return 1.0, 0.0
        tr = np.setdiff1d(np.arange(len(ys)), te)
        th, S, al, allb, lv_s, lv_a = _fit_core(t, Xs[tr], [songs[i] for i in tr], ys[tr], stage[tr], t.trust,
                                                alpha=t.alpha, eb=False)
        m = _latent(t, th, Xs[te], [songs[i] for i in te], lv_s, lv_a, allb)
        var = ((Xs[te] @ S[:t.pf, :t.pf]) * Xs[te]).sum(1) + 1 / al[3]  # held-out songs: an unseen song's variance
        oof[f == j] = _probit(m, np.sqrt(var))
    a, b = _logit1(oof, ys[smp], prior=1e-3)
    return (float(a), float(b)) if a > 0 else (1.0, 0.0)


# ---------------------------------------------------------------- the harness

def harness_models():
    """The harness Models for the sample tasks (reco/tasks.py)."""
    from ..eval import Model

    def fit_(train):
        t = fit(train.con, train.until)
        if t is None:
            return lambda items, ctx: np.full(len(items), np.nan)
        return lambda items, ctx: t.proba(items)
    return [Model("reco.taste", fit_, proba=True,
                  about="shared taste: hierarchical Bayesian logistic on CLAP + kernel + metadata, song and artist "
                        "effects, Mashup evidence, calibrated")]
