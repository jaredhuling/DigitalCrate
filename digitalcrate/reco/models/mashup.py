"""Mashup choice: which part to deal into a slot, learned from what you saved and kept over what you re-rolled.

    ch = fit(con)                                   # or fit(con, until=t): only what was known before t
    mean, sd = ch.score(stem, track, bar0, n, x)    # x: the six features stems.features computes at pick time
    M, S = ch.scores(stem, tracks, X)               # the same for many candidates at once

A Bayesian logistic regression with the starting guesses (stems.W0) as a fixed offset, so it deals exactly as W0
does until the log says otherwise, and moves only as far as the evidence carries it:

    logit = W0 . x + b[stem] + d . z(x) + (g + g[stem]) * z(taste)

    b      per-stem base rate, prior N(0, 3^2) (it doesn't change the order within a slot)
    d      corrections to the guesses, on standardized features, prior N(0, tau^2)
    taste  the sample taste regression (taste.py) applied to the stem's sound: what you starred, disliked and kept
           listening to among library samples, carried into Mashup through the CLAP space samples and stems share
    g      its weight, shared by every stem, with per-stem departures: priors N(0, s^2) and N(0, s_stem^2)

tau, s and s_stem are chosen by the Laplace approximation of the marginal likelihood on a small grid, so a fit on
little data stays near W0. With no Mashup events every correction is at its prior mean (0): the mean is W0 . x.

Training labels are the harness's (reco.tasks.MashupPart): one per event, re-saves of an already saved part and
repeats within a session dropped; saves, keeps, locks and snapshots are positive, re-rolls and removals negative,
all weighted the same. "sound" (x[4]) is recomputed for training events from the events known at fit time, each
with its own song left out. At pick time pass x as stems.features computes it.

Measured as mashup.chooser (reco eval --task mashup_part): ahead of W0 and of the live learned weights on songs it
never saw, mostly through the taste term on pitched stems; forward in time it is no better than either, within wide
intervals. Fit once and cache it (a fit takes about 2 s, most of it the sample taste model).
"""
import itertools

import numpy as np

from ... import stems
from ...taste import _sig

W0 = np.asarray(stems.W0, float)
FEATURES = list(stems.FEATURES)
STEMS = stems.STEMS
I_SOUND = FEATURES.index("sound")
D = len(W0)

GRID = dict(tau=(0.05, 0.15, 0.4, 1.0), s=(0.1, 0.3, 1.0), s_stem=(0.05, 0.3))
PRIOR_B = 3.0  # prior sd of the per-stem intercepts


def x6(x):
    """Older events have five features (no 'still'): padded with 0, as stems.weights does."""
    x = [] if x is None else [float(v) for v in x]
    return (x + [0.0] * D)[:D]


# ---------------------------------------------------------------- what is learned from

def _events(con, until=None):
    """The harness's Mashup examples (reco.tasks.MashupPart) from before until that have features."""
    from ..tasks import MashupPart
    return [e for e in MashupPart().examples(con) if e.context.get("x") and (until is None or (e.ts or 0) < until)]


def sound_centroids(con, emb, until=None):
    """Per stem: (liked, disliked) unit centres of the stem embeddings in stem_events, weighted as logged: exactly
    stems._taste, restricted to events before until."""
    acc = {}
    q, a = "SELECT stem, track, y, w FROM stem_events", ()
    if until is not None:
        q, a = q + " WHERE ts < ?", (until,)
    for r in con.execute(q, a):
        e = emb(r["track"], r["stem"])
        d = acc.setdefault(r["stem"], [np.zeros(512), np.zeros(512)])
        d[1 if r["y"] else 0] += (r["w"] or 0) * e
    unit = lambda v: v / np.linalg.norm(v) if np.linalg.norm(v) > 0 else None
    return {s: (unit(d[0]), unit(d[1])) for s, d in acc.items()}


def sound(cent, emb, track, stem):
    dis, like = cent.get(stem, (None, None))
    e = emb(track, stem)
    return (float(e @ like) if like is not None else 0.0) - (float(e @ dis) if dis is not None else 0.0)


def taste_direction(con, until=None):
    """The sample taste regression's direction in CLAP space: (mu, P, sd, beta) so that a stem embedding e scores
    beta . ((e - mu) P / sd); None when the taste model has too little to fit."""
    from ... import taste
    from ..eval import using
    with using(taste, "_db", lambda: con):
        lib = taste._library(con)
        if lib is None:
            return None
        lab = taste.item_labels(con, None, lib["durs"], until=until)
        r = taste.fit(None, labels=lab) or {}
    if r.get("beta") is None:
        return None
    fz = lib["fz"]
    return (fz.mu.astype(float), fz.P.astype(float), fz.sd.astype(float), np.asarray(r["beta"], float)[:fz.P.shape[1]])


# ---------------------------------------------------------------- the regression

def _design(stem_idx, Z, T, n_stems=len(STEMS)):
    """Columns: stem intercepts, z(x), z(taste), z(taste) per stem (W0 . x is a fixed offset, not a column)."""
    n = len(Z)
    S = np.zeros((n, n_stems))
    S[np.arange(n), stem_idx] = 1
    return np.hstack([S, Z, T[:, None], T[:, None] * S])


def _prior(tau, s, s_stem, n_stems=len(STEMS)):
    sd = np.r_[np.full(n_stems, PRIOR_B), np.full(D, tau), s, np.full(n_stems, s_stem)]
    return np.zeros(len(sd)), 1 / sd ** 2


def map_fit(X, y, w, m, prec, off=None, iters=50):
    """MAP of a weighted logistic regression logit = off + X theta with prior theta ~ N(m, diag(1/prec)): theta, its
    covariance (Laplace) and the log marginal likelihood (Laplace)."""
    off = np.zeros(len(y)) if off is None else off
    th = m.copy()
    A = np.diag(prec)

    def obj(t):
        z = off + X @ t
        return float((w * (np.logaddexp(0, z) - y * z)).sum()) + 0.5 * float((prec * (t - m) ** 2).sum())

    f = obj(th)
    for _ in range(iters):
        p = _sig(off + X @ th)
        g = X.T @ (w * (p - y)) + prec * (th - m)
        H = (X * (w * p * (1 - p))[:, None]).T @ X + A
        step = np.linalg.solve(H, g)
        t = 1.0
        while t > 1e-6:  # Newton with backtracking (the posterior is log-concave)
            f2 = obj(th - t * step)
            if f2 <= f:
                break
            t /= 2
        th, f = th - t * step, f2
        if np.abs(t * step).max() < 1e-7:
            break
    p = _sig(off + X @ th)
    H = (X * (w * p * (1 - p))[:, None]).T @ X + A
    ev = -f + 0.5 * float(np.log(prec).sum()) - 0.5 * float(np.linalg.slogdet(H)[1])
    return th, np.linalg.inv(H), ev


class Chooser:
    """A fitted model. score / scores: the posterior mean and sd of the logit that a candidate part is kept."""

    def __init__(self, theta, cov, mu, sd, tdir=None, tstat=(0.0, 1.0), n=0, hyper=None, emb=None, cent=None, w0=None):
        self.theta, self.cov, self.mu, self.sd = theta, cov, mu, sd
        self.tdir, self.tstat, self.n, self.hyper = tdir, tstat, n, hyper or {}
        self.cent = cent or {}  # the 'sound' centres known at fit time (for scoring logged events, as the harness does)
        self._emb = emb or stems._emb
        self._t = {}
        self.w0 = W0 if w0 is None else np.asarray(w0, float)  # the fixed offset's weights (W0, or W0 without 'sound')
        k = len(STEMS)
        d = theta[k:k + D]
        self._g, self._gs = float(theta[k + D]), theta[k + D + 1:]
        # the mean on raw x: W0 . x + d . (x - mu) / sd + b[stem] + g[stem] t  ==  w . x + c[stem, song]
        self._w = self.w0 + d / sd
        self._c = -float((d * mu / sd).sum())

    def taste(self, track, stem):
        """The sample taste score of this stem's sound, standardized as in training (0 where unknown). tdir is the old
        regression's direction (mu, P, sd, beta), or a function (track, stem) -> raw score or None (the shared model)."""
        key = (int(track), stem)
        if key not in self._t:
            v = 0.0
            if callable(self.tdir) and stem in STEMS:
                raw = self.tdir(int(track), stem)
                v = 0.0 if raw is None or not np.isfinite(raw) else (raw - self.tstat[0]) / self.tstat[1]
            elif self.tdir is not None and stem in STEMS:
                e = self._emb(int(track), stem)
                if np.any(e):
                    mu, P, sd, beta = self.tdir
                    v = (float(beta @ (((e - mu) @ P) / sd)) - self.tstat[0]) / self.tstat[1]
            self._t[key] = v
        return self._t[key]

    def linear(self, stem, track):
        """(w, c): for this stem and song the mean is w . x + c. With no data: (W0, 0)."""
        c = self._c
        if stem in STEMS:
            si = STEMS.index(stem)
            c += float(self.theta[si]) + (self._g + float(self._gs[si])) * self.taste(track, stem)
        return self._w, c

    def _phi(self, stem, tracks, X):
        k, n = len(STEMS), len(tracks)
        S = np.zeros((n, k))
        T = np.zeros(n)
        if stem in STEMS:
            S[:, STEMS.index(stem)] = 1
            T = np.array([self.taste(t, stem) for t in tracks])
        return np.hstack([S, (X - self.mu) / self.sd, T[:, None], T[:, None] * S])

    def scores(self, stem, tracks, X, sd=True):
        """(means, sds) for candidates of one stem: tracks[i] with features X[i] (stems.features' six)."""
        tracks = list(tracks)
        X = np.asarray(X, float).reshape(len(tracks), D)
        F = self._phi(stem, tracks, X)
        M = X @ self.w0 + F @ self.theta
        return M, (self._sd(F) if sd else None)

    def _sd(self, F):
        """The posterior sd of the logit, leaving out the stem's base rate: it is shared by every candidate of a
        slot, so it changes neither their order nor which of them is the more uncertain."""
        k = len(STEMS)
        G, C = F[:, k:], self.cov[k:, k:]
        return np.sqrt(np.maximum(((G @ C) * G).sum(1), 0))

    def score(self, stem, track, bar0, n, x, context=None):
        """(mean, sd) for one part. bar0, n and context are not used yet: the six features carry what is known at
        pick time; context is where tempo, key and the other parts playing go once impressions log them."""
        w, c = self.linear(stem, track)
        x = np.asarray(x6(x), float)
        F = self._phi(stem, [track], x[None])[0]
        return float(w @ x + c), float(self._sd(F[None])[0])

    def about(self):
        k = len(STEMS)
        return dict(n=self.n, hyper=self.hyper, corrections=bool(np.any(self.theta[k:k + D])),
                    weights=dict(zip(FEATURES, np.round(self._w, 3).tolist())),
                    taste=dict(zip(STEMS, np.round(self._g + self._gs, 3).tolist())),
                    base=dict(zip(STEMS, np.round(self.theta[:k], 3).tolist())))


def no_data(emb=None):
    """The model before any Mashup event: the mean is W0 . x exactly."""
    m, prec = _prior(GRID["tau"][0], GRID["s"][0], GRID["s_stem"][0])
    return Chooser(m, np.diag(1 / prec), np.zeros(D), np.ones(D), emb=emb)


def fit(con, until=None, emb=None, tdir="taste", corrections=True, w0=None):
    """A Chooser from the Mashup events in con (those before until), with the sample taste known then.
    emb(track, stem) -> unit CLAP vector (default stems._emb); tdir: a taste_direction() result, a function
    (track, stem) -> raw taste score (shared_taste()), None to leave the sample taste out, or "taste" to fit the old
    regression's direction from con. corrections=False: d fixed at 0 (no learned corrections to the guesses: only the
    taste weights g, g[stem] are learned, and the stem intercepts, which don't change an order). w0: the offset's
    weights (default W0)."""
    emb = emb or stems._emb
    w0 = W0 if w0 is None else np.asarray(w0, float)
    ex = _events(con, until)
    if not ex:
        ch = no_data(emb)
        ch.tdir, ch.w0, ch._w = (tdir if not isinstance(tdir, str) else None), w0, w0.copy()
        return ch
    if isinstance(tdir, str):
        tdir = taste_direction(con, until)
    stem_idx = np.array([STEMS.index(e.item[2]) for e in ex])
    X = np.array([x6(e.context["x"]) for e in ex], float)
    X[:, I_SOUND] = _loso_sound(con, emb, until, ex)
    y = np.array([float(e.label > 0) for e in ex])
    w = np.ones(len(ex))  # one per event (the logged weights measured worse)
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 1e-6, sd, 1.0)
    T, tstat = np.zeros(len(ex)), (0.0, 1.0)
    if callable(tdir):
        raw = np.array([np.nan if (v := tdir(int(e.item[1]), e.item[2])) is None else float(v) for e in ex])
    elif tdir is not None:
        mu_t, P, sd_t, beta = tdir
        raw = np.array([float(beta @ (((v - mu_t) @ P) / sd_t)) if np.any(v) else np.nan
                        for v in (emb(e.item[1], e.item[2]) for e in ex)])
    if tdir is not None:
        ok = np.isfinite(raw)
        if ok.sum() > 1:
            tstat = (float(raw[ok].mean()), float(raw[ok].std() + 1e-9))
            T = np.where(ok, (np.nan_to_num(raw) - tstat[0]) / tstat[1], 0.0)
    F = _design(stem_idx, (X - mu) / sd, T)
    k = len(STEMS)
    keep = np.ones(F.shape[1], bool)
    if not corrections:
        keep[k:k + D] = False  # no d columns: the guesses as they are
        mu, sd = np.zeros(D), np.ones(D)
    best = None
    for tau, s, s_stem in itertools.product(GRID["tau"] if corrections else GRID["tau"][:1], GRID["s"], GRID["s_stem"]):
        m, prec = _prior(tau, s, s_stem)
        th, cov, ev = map_fit(F[:, keep], y, w, m[keep], prec[keep], off=X @ w0)
        if best is None or ev > best[2]:
            best = (th, cov, ev, dict(s=s, s_stem=s_stem, **(dict(tau=tau) if corrections else {})))
    th, cov, ev, hyper = best
    if not corrections:  # back to the full layout, d = 0 with no uncertainty
        full, C_ = np.zeros(len(keep)), np.zeros((len(keep), len(keep)))
        full[keep] = th
        C_[np.ix_(keep, keep)] = cov
        th, cov = full, C_
    return Chooser(th, cov, mu, sd, tdir, tstat, len(ex), dict(hyper, evidence=round(ev, 2)), emb=emb,
                   cent=sound_centroids(con, emb, until), w0=w0)


def shared_taste(t):
    """The shared taste model (reco.models.taste.Taste) as a Chooser's taste: (track, stem) -> the latent taste of the
    stem's sound, song and artist (None without an embedding). Scores are cached per stem of a song."""
    cache = {}

    def f(track, stem):
        key = (int(track), stem)
        if key not in cache:
            m, _ = t.score([("part", int(track), stem, 0, 4)])
            cache[key] = float(m[0]) if np.isfinite(m[0]) else None
        return cache[key]

    def prime(keys):
        """Score many (track, stem) at once (one call instead of one per stem)."""
        todo = [(int(a), b) for a, b in keys if (int(a), b) not in cache]
        if todo:
            m, _ = t.score([("part", a, b, 0, 4) for a, b in todo])
            for key, v in zip(todo, m):
                cache[key] = float(v) if np.isfinite(v) else None
    f.prime = prime
    return f


def taste_only(con, t, until=None, emb=None, sound=True):
    """The dice's model: W0 . x plus the shared taste term, no learned corrections (fit(corrections=False)).
    t: a fitted reco.models.taste.Taste (None: plain W0). sound=False: W0 with the 'sound' weight set to 0."""
    w0 = W0.copy()
    if not sound:
        w0[I_SOUND] = 0.0
    tf = shared_taste(t) if t is not None else None
    if tf is not None:
        ex = _events(con, until)
        tf.prime({(e.item[1], e.item[2]) for e in ex})
    return fit(con, until, emb=emb, tdir=tf, corrections=False, w0=w0)


def _loso_sound(con, emb, until, ex):
    """'sound' for each training event with its own song's events left out of the centres, as a song new to the
    log meets it (with them in, a saved part's own save pulls the liked centre toward it and the weight learned for
    'sound' is inflated)."""
    q, a = "SELECT stem, track, y, w FROM stem_events", ()
    if until is not None:
        q, a = q + " WHERE ts < ?", (until,)
    tot, per = {}, {}
    for r in con.execute(q, a):
        e = (r["w"] or 0) * emb(r["track"], r["stem"])
        k = 1 if r["y"] else 0
        tot.setdefault(r["stem"], np.zeros((2, 512)))[k] += e
        per.setdefault((r["stem"], r["track"]), np.zeros((2, 512)))[k] += e
    out = []
    for e in ex:
        s, t = e.item[2], e.item[1]
        c = tot.get(s, np.zeros((2, 512))) - per.get((s, t), np.zeros((2, 512)))
        v = emb(t, s)
        n0, n1 = np.linalg.norm(c[0]), np.linalg.norm(c[1])
        out.append((float(v @ c[1]) / n1 if n1 > 1e-9 else 0.0) - (float(v @ c[0]) / n0 if n0 > 1e-9 else 0.0))
    return np.array(out)


# ---------------------------------------------------------------- in the harness

def loso_sound(con, emb, until=None):
    """(track, stem) -> 'sound' with that song's own events left out of the centres (as a song new to the log meets
    them). Reads stem_events before until once."""
    q, a = "SELECT stem, track, y, w FROM stem_events", ()
    if until is not None:
        q, a = q + " WHERE ts < ?", (until,)
    tot, per = {}, {}
    try:
        rows = con.execute(q, a).fetchall()
    except Exception:
        rows = []
    for r in rows:
        e = (r["w"] or 0) * emb(r["track"], r["stem"])
        k = 1 if r["y"] else 0
        tot.setdefault(r["stem"], np.zeros((2, 512)))[k] += e
        per.setdefault((r["stem"], int(r["track"])), np.zeros((2, 512)))[k] += e

    def f(track, stem):
        c = tot.get(stem, np.zeros((2, 512))) - per.get((stem, int(track)), np.zeros((2, 512)))
        v = emb(int(track), stem)
        n0, n1 = np.linalg.norm(c[0]), np.linalg.norm(c[1])
        return (float(v @ c[1]) / n1 if n1 > 1e-9 else 0.0) - (float(v @ c[0]) / n0 if n0 > 1e-9 else 0.0)
    return f


def _train_taste(train, surfaces=("samples", "mashup")):
    """The shared taste model fitted on the fold's masked database (one per fold and evidence set)."""
    from . import taste as T
    key = ("shared_taste", tuple(surfaces))
    if key not in train.cache:
        train.cache[key] = T.fit(train.con, train.until, surfaces=surfaces)
    return train.cache[key]


def taste_harness_model(name, sound="train", surfaces=("samples", "mashup")):
    """W0 . x + the shared taste term (no corrections) as a harness Model. sound: how 'sound' (x[4]) is scored for the
    held-out events: "train" (the centres of the fold's training events), "loso" (the same, the event's own song left
    out) or "none" (its weight set to 0)."""
    from ..eval import Model

    def fit_(train):
        t = _train_taste(train, surfaces)
        ch = taste_only(train.con, t, train.until, sound=sound != "none")
        snd = loso_sound(train.con, ch._emb, train.until) if sound == "loso" else None

        def score(items, ctx):
            if t is not None:
                ch.tdir.prime({(it[1], it[2]) for it in items})
            out = np.zeros(len(items))
            for i, (it, c) in enumerate(zip(items, ctx)):
                x = x6((c or {}).get("x"))
                x[I_SOUND] = snd(it[1], it[2]) if snd else sound_(ch, it) if sound == "train" else 0.0
                out[i] = ch.score(it[2], it[1], it[3], it[4], x)[0]
            return out
        return score
    ev = "samples and Mashup" if "mashup" in surfaces else "samples only"
    return Model(name, fit_, about=f"W0 . x + the shared taste of the stem's sound ({ev}), no learned corrections; "
                                   f"'sound' {dict(train='from training events', loso='own song left out', none='off')[sound]}")


def sound_(ch, it):
    return sound(ch.cent, ch._emb, it[1], it[2])


def harness_models():
    """Every Mashup candidate the harness measures."""
    return [harness_model("mashup.chooser"), taste_harness_model("mashup.taste"),
            taste_harness_model("mashup.taste_loso", sound="loso"),
            taste_harness_model("mashup.taste_nosound", sound="none"),
            taste_harness_model("mashup.taste_samples", sound="loso", surfaces=("samples",))]


def harness_model(name="mashup.chooser"):
    """The Chooser as a harness Model: fitted on the fold's masked database, scoring held-out events by their frozen
    features with 'sound' recomputed from the fold's training events (the frozen one saw held-out labels)."""
    from ..eval import Model

    def fit_(train):
        if "taste_dir" not in train.cache:
            train.cache["taste_dir"] = taste_direction(train.con, train.until)
        ch = fit(train.con, train.until, tdir=train.cache["taste_dir"])

        def score(items, ctx):
            out = np.zeros(len(items))
            for i, (it, c) in enumerate(zip(items, ctx)):
                x = x6((c or {}).get("x"))
                x[I_SOUND] = sound(ch.cent, ch._emb, it[1], it[2])
                out[i] = ch.score(it[2], it[1], it[3], it[4], x)[0]
            return out
        return score
    return Model(name, fit_, about="W0 as the prior of a Bayesian logistic regression, plus the sample taste of the "
                                   "stem's sound (reco/models/mashup.py)")
