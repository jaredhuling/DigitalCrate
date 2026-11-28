"""Today's models as harness Models, calling the existing code unchanged on the masked training database.

Existing code that opens its own connection (taste.fit -> taste._db, suggest.edit_model -> taste._db) is pointed at
the masked database for the duration of the fit (eval.using), so it reads only what the fold allows.

    samples   taste (the live "for you" score) and its parts: regression, trees, knn (nearest favorite), song; the
              two one-model blends the Taste page reports; the regression's probability; quality; random
    mashup    W0 (the starting guesses), learned (stems.weights refit on the fold's events), each on the features frozen
              at log time; harmony fit alone; the sound feature as frozen and as recomputed from training events only
    edits     the Beta priors per move and family (suggest._learned), the edit model (suggest.edit_model), the arm
              (critic over wildcard), the stored closeness, random
    pairs     the "goes well with" score in each mode (clap, learned, blend: build.compat_block), plain CLAP cosine,
              the arrangement model's raw vibe, random
    scout     the stored scores (score, taste, vocal), the taste vector refit on favorites known at the time, random
"""
import numpy as np

from .eval import Model, random_model, using

NAN = float("nan")


def _const(n):
    return np.full(n, NAN)


# ---------------------------------------------------------------- samples

def _taste_fit(train):
    """One taste fit per fold, shared by every model that reads a part of it."""
    if "taste" not in train.cache:
        from .. import taste
        con = train.con
        with using(taste, "_db", lambda: con):
            lib = taste._library(con)
            lab = taste.item_labels(con, None, lib["durs"], until=train.until)
            r = taste.fit(None, labels=lab)
        train.cache["taste"] = (r or {}, dict(lib["pos"]))
    return train.cache["taste"]


def _z(v):
    return (v - v.mean()) / (v.std() + 1e-9)


def taste_model(name, pick, proba=False, about=""):
    def fit(train):
        r, pos = _taste_fit(train)
        v = pick(r)
        if v is None:
            return lambda items, ctx: _const(len(items))
        v = np.asarray(v, float)
        return lambda items, ctx: np.array([v[pos[it[1]]] if it[1] in pos else NAN for it in items])
    return Model(name, fit, proba, about)


def _part(name):
    return lambda r: (r.get("parts") or {}).get(name)


def _blend(name):
    def f(r):
        P = r.get("parts") or {}
        if P.get(name) is None:
            return None
        return 0.7 * P[name] + 0.3 * P["knn"] + 0.3 * P["song"]  # as taste_report.accuracy's auc_regression / auc_trees
    return f


def quality_model():
    def fit(train):
        q = dict(train.con.execute("SELECT path, quality FROM samples").fetchall())
        return lambda items, ctx: np.array([q.get(it[1]) if q.get(it[1]) is not None else NAN for it in items], float)
    return Model("quality", fit, about="the sample's quality score alone")


def sample_models():
    return [taste_model("taste", lambda r: r.get("score"), about="the live score: 0.7 model + 0.3 knn + 0.3 song"),
            taste_model("taste.regression", _part("regression"), about="Bayesian logistic regression alone (z)"),
            taste_model("taste.trees", _part("trees"), about="gradient-boosted trees alone (z)"),
            taste_model("taste.knn", _part("knn"), about="closeness to the nearest liked sample"),
            taste_model("taste.song", _part("song"), about="mean label of the song's rated samples"),
            taste_model("taste.reg_blend", _blend("regression"), about="the blend with the regression as its model"),
            taste_model("taste.trees_blend", _blend("trees"), about="the blend with the trees as its model"),
            taste_model("taste.prob", lambda r: r.get("prob"), proba=True,
                        about="the regression's probability (calibration is against PU negatives)"),
            quality_model(), random_model()]


# ---------------------------------------------------------------- Mashup

def _X(ctx):
    """The six features frozen at log time (older rows have five: padded with 0, as stems.weights does)."""
    from .. import stems
    d = len(stems.W0)
    return np.array([((c.get("x") or []) + [0.0] * d)[:d] for c in ctx], float).reshape(len(ctx), d)


def _sound_train(train, items):
    """The 'like - dislike sound' feature, recomputed from the training events only (stems._taste on the masked db)."""
    from .. import stems
    if "stem_taste" not in train.cache:
        train.cache["stem_taste"] = stems._taste(train.con)
    tz = train.cache["stem_taste"]
    out = []
    for it in items:
        dis, like = tz.get(it[2], (None, None))
        e = stems._emb(it[1], it[2])
        out.append((float(e @ like) if like is not None else 0.0) - (float(e @ dis) if dis is not None else 0.0))
    return np.array(out)


def mashup_models():
    from .. import stems
    i_sound, i_fit = stems.FEATURES.index("sound"), stems.FEATURES.index("fit")

    def w0(train):
        return lambda items, ctx: _X(ctx) @ stems.W0

    def learned(train):
        w, n = stems.weights(train.con)  # the guesses until 12 events, then the ridge fit pulled toward them
        return lambda items, ctx: _X(ctx) @ w

    def w0_honest(train):
        def score(items, ctx):
            X = _X(ctx)
            X[:, i_sound] = _sound_train(train, items)
            return X @ stems.W0
        return score

    return [Model("mashup.W0", w0, about="the starting weights on the frozen features"),
            Model("mashup.learned", learned, about="stems.weights() refit on the fold's events (what deals today)"),
            Model("mashup.W0_sound_train", w0_honest, about="W0 with 'sound' recomputed from training events only"),
            Model("mashup.fit", lambda t: (lambda items, ctx: _X(ctx)[:, i_fit]), about="harmony fit alone"),
            Model("mashup.sound_frozen", lambda t: (lambda items, ctx: _X(ctx)[:, i_sound]),
                  about="'sound' as frozen at log time (saw earlier events of the same song)"),
            Model("mashup.sound_train", lambda t: (lambda items, ctx: _sound_train(t, items)),
                  about="'sound' from the training events only"),
            random_model()]


# ---------------------------------------------------------------- edits

def edit_models():
    def priors(train):
        from .. import suggest
        cache = {}

        def score(items, ctx):
            out = []
            for it, c in zip(items, ctx):
                mat = c.get("material") or "melodic"
                if mat not in cache:
                    cache[mat] = suggest._learned(train.con, mat)
                mprior, fprior, _ = cache[mat]
                fams = (c.get("family") or "none").split("+")
                types = suggest._types(it[2]) or [it[2]]
                out.append(0.6 * float(np.mean([fprior(f) for f in fams]))  # as suggest()'s judge weighs them
                           + 0.8 * float(np.mean([mprior(t) for t in types])))
            return np.array(out)
        return score

    def model(train):
        from .. import suggest, taste
        con = train.con
        suggest._EM.clear()
        try:
            with using(taste, "_db", lambda: con):
                pred, info = suggest.edit_model(con)
        finally:
            suggest._EM.clear()  # never leave a fold's model cached in the module
        if pred is None:
            return lambda items, ctx: _const(len(items))
        return lambda items, ctx: np.array([pred(c["delta"], c.get("params") or {}, c.get("material"))
                                            if c.get("delta") is not None else NAN for c in ctx])

    return [Model("edit.priors", priors, about="Beta priors per move and family, as suggest() weighs them"),
            Model("edit.model", model, about="suggest.edit_model on the fold's ratings (needs 8+, 3 of each)"),
            Model("edit.arm", lambda t: (lambda items, ctx: np.array([{"critic": 1.0, "wildcard": 0.0}.get(c.get("arm"), NAN)
                                                                      for c in ctx])), about="critic pick over wildcard"),
            Model("edit.close", lambda t: (lambda items, ctx: np.array([c.get("close") if c.get("close") is not None
                                                                        else NAN for c in ctx], float)),
                  about="closeness to the original (stored with a rating only)"),
            random_model()]


# ---------------------------------------------------------------- pairs

_PAIR = {}


def _pairs(con):
    from .. import build
    key = tuple(con.execute("SELECT COUNT(*), MAX(rowid) FROM samples").fetchone())
    if _PAIR.get("key") != key:
        d = build.load(con)
        _PAIR.clear()
        _PAIR.update(key=key, d=d, pos={r["path"]: i for i, r in enumerate(d["rows"])}, rows={})
    return _PAIR


def _pair_row(con, a, mode):
    """The compat_block row of source sample a against the whole library (the learned score is scaled per row)."""
    from .. import build
    P = _pairs(con)
    if (a, mode) not in P["rows"]:
        i = P["pos"].get(a)
        if i is None or (mode in ("learned", "blend") and P["d"].get("Fa") is None):
            P["rows"][a, mode] = None
        elif mode == "cosine":
            E = P["d"]["emb"]
            P["rows"][a, mode] = E @ E[i] / (np.linalg.norm(E, axis=1) * np.linalg.norm(E[i]) + 1e-9)
        elif mode == "vibe":
            P["rows"][a, mode] = P["d"]["Fa"][i] @ P["d"]["Gb"].T
        else:
            P["rows"][a, mode] = build.compat_block(P["d"], np.array([i]), mode=mode)["score"][0]
    return P["rows"][a, mode]


def pair_model(mode, about=""):
    def fit(train):
        def score(items, ctx):
            P = _pairs(train.con)
            out = []
            for it in items:
                row, j = _pair_row(train.con, it[1], mode), P["pos"].get(it[2])
                out.append(float(row[j]) if row is not None and j is not None else NAN)
            return np.array(out)
        return score
    return Model(f"pair.{mode}", fit, about=about)


def pair_models():
    return [pair_model("clap", "today's default: harmony x tempo x (role + CLAP closeness)"),
            pair_model("learned", "the same with the arrangement model's vibe"),
            pair_model("blend", "the same with 60% arrangement + 40% closeness"),
            pair_model("cosine", "plain CLAP cosine"),
            pair_model("vibe", "the arrangement model's raw score"),
            random_model()]


# ---------------------------------------------------------------- scout

def scout_stored(col, about=""):
    def fit(train):
        v = {r[0]: r[1] for r in train.con.execute(f"SELECT id, {col} FROM yt_scout")}
        return lambda items, ctx: np.array([v.get(it[1]) if v.get(it[1]) is not None else NAN for it in items], float)
    return Model(f"scout.{col}", fit, about=about)


def scout_models():
    def taste_now(train):
        from .. import ytscout
        vec = {m: ytscout._taste_vec(train.con, m) for m in ("voice", "pads", "guided")}

        def score(items, ctx):
            E, ok = train.items().clap(items)
            out = []
            for e, k, c in zip(E, ok, ctx):
                v = vec.get(c.get("mode") or "voice")
                out.append(float(e @ v) if k and v is not None else NAN)
            return np.array(out)
        return score

    return [scout_stored("score", "the score it was ranked by when found"),
            scout_stored("taste", "closeness to your favorites' mean, when found"),
            scout_stored("vocal", "how much it sounded like clean singing"),
            Model("scout.taste_now", taste_now, about="closeness to the mean of the favorites known before the cut"),
            random_model()]


# ---------------------------------------------------------------- candidates (reco/models), beside the baselines

_mashup_baselines = mashup_models


def mashup_models():
    from .models.mashup import harness_models
    return _mashup_baselines() + harness_models()


_sample_baselines = sample_models


def sample_models():
    from .models.taste import harness_models
    return _sample_baselines() + harness_models()
