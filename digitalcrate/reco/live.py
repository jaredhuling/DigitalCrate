"""What the app serves from the reco models: the switch between models, and the shared taste model kept fitted.

    settings()                    {"samples": "new" | "old", "mashup": "new" | "w0" | "old"}  (reco/settings.json)
    set_setting(surface, value)
    fitted()                      the latest fit of the shared taste model (a Fit) or None; never waits for one:
                                  a refit starts in the background when your ratings, listening or Mashup log changed
    sample_scores()               (paths, z, mean, sd, fit) of every library sample, or None before the first fit
    chooser()                     the Mashup dice's taste term (reco.models.mashup.taste_only), or None
    served(payload) / record(token)   one impression per "for you" / discover ranking the page was served

The samples surfaces ("for you", discover, sets, Fits my track, drum kits, Mashup one-shots and pads, the edit
suggestions' critic) read taste.scores_payload / cached_scores, which serve this model's score when samples is "new":
the posterior mean, standardized over the library (so it sits on the same scale as the old blend), and for discover a
draw from each sample's posterior (mean + sd x a standard normal, standardized the same way): a Thompson draw per
sample, re-drawn on every request. Until the first fit lands (about 10-15 s after the server starts) the old model's
scores are served and say so (policy "taste (new model not fitted yet)").
"""
import hashlib
import json
import threading
import time

import numpy as np

from .. import config as C

SETTINGS = C.DATA_DIR / "reco" / "settings.json"
CHOICES = dict(samples=("new", "old"), mashup=("new", "w0", "old"))
ABOUT = dict(samples=dict(new="the shared taste model (reco/models/taste.py)",
                          old="the earlier blend: regression + trees + nearest favorite + song (taste.py)"),
             mashup=dict(new="the starting guesses (W0) + the shared taste of the stem's sound; parts you turned down "
                             "dealt less",
                         w0="the starting guesses (W0) alone; parts you turned down dealt less",
                         old="the learned weights (stems.weights), as before the switch-over"))
MIN_GAP = 30          # seconds between two refits (listening changes the evidence all the time)
DISCOVER = "thompson per sample: mean + sd x N(0, 1), standardized as the score"
SAMPLE_MODEL = "reco.taste"
SERVED_N = 50         # samples kept per served ranking
MASHUP_SOUND = True   # the dice keeps its 'sound' feature (closeness to the stems you kept minus those you threw out),
                      # each song's own events left out; with it off the harness measured a little worse (recommend.md)


def _con():
    """A connection the fit keeps (its item store reads the library lazily, from whichever thread scores)."""
    import sqlite3
    from ..db import connect
    connect().close()  # (the tables, as every module expects them)
    con = sqlite3.connect(C.DB_PATH, timeout=60, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------- the switch

def settings():
    try:
        got = json.loads(SETTINGS.read_text())
    except Exception:
        got = {}
    return {k: got.get(k) if got.get(k) in v else v[0] for k, v in CHOICES.items()}


def set_setting(surface, value):
    if surface not in CHOICES or value not in CHOICES[surface]:
        raise ValueError(f"{surface}: one of {', '.join(CHOICES.get(surface, ()))}")
    s = settings()
    s[surface] = value
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=1))
    return s


def policy(surface):
    return settings()[surface]


# ---------------------------------------------------------------- the shared taste model, refitted in the background

class Fit:
    def __init__(self, t, paths, mean, sd, key, chooser=None, seconds=0.0):
        self.t, self.paths, self.mean, self.sd, self.key = t, paths, mean, sd, key
        ok = np.isfinite(mean)
        self.mu, self.scale = float(mean[ok].mean()), float(mean[ok].std() + 1e-9)
        self.z = np.where(ok, (mean - self.mu) / self.scale, np.nan)
        self.chooser, self.seconds, self.when = chooser, seconds, time.time()
        self.pos = {p: i for i, p in enumerate(paths)}

    def discover(self, rng=None):
        rng = rng or np.random.default_rng()
        return (self.mean + self.sd * rng.standard_normal(len(self.mean)) - self.mu) / self.scale


_S = dict(fit=None, busy=False, last=0.0, key=None, error=None, checked=0.0)
CHECK_EVERY = 2.0     # seconds: how often a request looks whether the evidence changed
_LOCK = threading.Lock()


def evidence_key(con):
    """What the fit depends on: the label tables' sizes and last rows, and the library's."""
    out = []
    for t in ("events", "favorites", "collection_items", "stem_events", "stem_mixes", "samples"):
        try:
            out.append(tuple(con.execute(f"SELECT COUNT(*), MAX(rowid) FROM {t}").fetchone()))
        except Exception:
            out.append(None)
    return tuple(out)


def refit(con=None):
    """Fit now (in this thread) -> the Fit, also kept as the current one. None if there is too little to learn from."""
    from .models import mashup as MM, taste as T
    t0 = time.time()
    con = con or _con()
    key = evidence_key(con)
    t = T.fit(con)
    if t is None:
        return None
    t.items._samples(), t.items._tracks()  # loaded here, not on the first request
    paths = list(t.lib["paths"])
    mean, sd = t.score([("sample", p) for p in paths])
    ch = None
    try:
        ch = MM.taste_only(con, t, sound=MASHUP_SOUND)
    except Exception as e:
        print(f"reco: Mashup taste term not fitted ({type(e).__name__}: {e})")
    f = Fit(t, paths, mean, sd, key, ch, time.time() - t0)
    _S.update(fit=f, key=key, error=None)
    return f


def _go():
    try:
        refit()
        f = _S["fit"]
        if f is not None and f.chooser is not None:  # each song's stems scored ahead of the first roll
            try:
                from .. import stems
                f.chooser.tdir.prime([(t, s) for t, m in stems.library().items() for s in m["stems"]
                                      if s in stems.STEMS])
            except Exception as e:
                print(f"reco: Mashup taste not primed ({type(e).__name__}: {e})")
    except Exception as e:
        _S["error"] = f"{type(e).__name__}: {e}"
        print("reco: taste refit failed:", _S["error"])
    finally:
        _S.update(busy=False, last=time.time())


def fitted(con=None, background=True):
    """The current Fit (or None before the first). Starts a refit in the background when the evidence changed (at
    most one at a time, and not within MIN_GAP seconds of the last)."""
    if background and time.time() - _S["checked"] >= CHECK_EVERY:
        _S["checked"] = time.time()
        try:
            from ..db import connect
            c = con or connect()
            try:
                key = evidence_key(c)
            finally:
                if con is None:
                    c.close()
            with _LOCK:
                due = key != _S["key"] and not _S["busy"] and (
                    _S["fit"] is None or time.time() - _S["last"] >= MIN_GAP)
                if due:
                    _S["busy"] = True
            if due:
                threading.Thread(target=_go, daemon=True, name="reco-taste").start()
        except Exception as e:
            print("reco: could not check the taste model:", e)
    return _S["fit"]


def busy():
    return _S["busy"]


def chooser():
    f = _S["fit"]
    return f.chooser if f is not None else None


def reset():
    """Forget the fit (tests)."""
    _S.update(fit=None, busy=False, last=0.0, key=None, error=None, checked=0.0)
    _SERVED.clear()


# ---------------------------------------------------------------- impressions of the sample rankings

_SERVED = {}  # token -> (surface, shown, context, policy); the page reports which one it put on screen


def served(payload, fav=(), n=SERVED_N):
    """Remember the "for you" and discover rankings in a payload as served (the top n of each, unrated, not starred)
    -> a token the page sends back once it has them (record()). Nothing is written here."""
    if not payload or not payload.get("score"):
        return None
    bad = set(payload.get("disliked") or ()) | set(fav)
    out = []
    for surface, col in (("samples.for_you", "score"), ("samples.discover", "discover")):
        d = payload.get(col) or {}
        top = sorted((p for p in d if p not in bad and not p.startswith("_Reference")), key=lambda p: -d[p])[:n]
        if not top:
            continue
        sig = hashlib.sha1(json.dumps(top).encode()).hexdigest()[:12]
        out.append((surface, [(("sample", p), d[p], None) for p in top],
                    dict(sig=sig, n=len(d) - len(bad & set(d)), col=col,
                         draw=DISCOVER if col == "discover" and payload.get("policy") == SAMPLE_MODEL else None),
                    dict(model=payload.get("policy"), version=1, settings=settings())))
    if not out:
        return None
    tok = hashlib.sha1("".join(o[2]["sig"] for o in out).encode()).hexdigest()[:12]
    _SERVED[tok] = out
    _SERVED["last"] = tok
    while len(_SERVED) > 16:
        _SERVED.pop(next(k for k in _SERVED if k != "last"))
    return tok


_LAST_SIG = {}


def record(token, con=None):
    """The page has the rankings of this token: one impression per ranking, unless the last one of that surface had
    the same content. -> how many were written."""
    from . import log as L
    token = str(token or "")
    if token == "last":  # (a page that doesn't send its token: the most recent ranking served)
        token = _SERVED.pop("last", None) or ""
    got = _SERVED.pop(token, None)
    if not got:
        return 0
    own = con is None
    if own:
        from ..db import connect
        con = connect()
    n = 0
    try:
        con.execute("PRAGMA busy_timeout = 3000")
        for surface, shown, ctx, pol in got:
            if _LAST_SIG.get(surface) is None:
                try:
                    r = con.execute("SELECT context FROM reco_impressions WHERE surface=? ORDER BY id DESC LIMIT 1",
                                    (surface,)).fetchone()
                    _LAST_SIG[surface] = json.loads(r[0]).get("sig") if r else ""
                except Exception:
                    _LAST_SIG[surface] = ""
            if _LAST_SIG[surface] == ctx["sig"]:
                continue
            L.impression(con, surface, ctx, shown, policy=pol)
            _LAST_SIG[surface] = ctx["sig"]
            n += 1
    except Exception as e:
        print("reco: ranking not recorded:", e)
    finally:
        if own:
            con.close()
    return n
