"""The Mashup choice model (reco/models/mashup.py), on throwaway data (never the real library)."""
import json
import sqlite3

import numpy as np
import pytest

from digitalcrate import stems
from digitalcrate.reco import eval as E
from digitalcrate.reco.models import mashup as M
from digitalcrate.reco.tasks import MashupPart

T0 = 1_700_000_000.0
EMB = {}


def emb(track, stem):
    """A fixed random unit vector per stem of a song (stands in for stems._emb)."""
    if (track, stem) not in EMB:
        e = np.random.default_rng(int(track) * 10 + M.STEMS.index(stem)).normal(size=512)
        EMB[track, stem] = e / np.linalg.norm(e)
    return EMB[track, stem]


def tdir(k=4):
    """A taste direction in the shape taste_direction() returns: (mu, P, sd, beta)."""
    rng = np.random.default_rng(1)
    return np.zeros(512), rng.normal(size=(512, k)), np.ones(k), rng.normal(size=k)


def _db(path, events):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE stem_events (ts REAL, kind TEXT, stem TEXT, track INTEGER, bar0 INTEGER, n INTEGER,
                   x TEXT, y INTEGER, w REAL)""")
    con.executemany("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)", events)
    con.commit()
    return con


def _events(n=240, seed=0, fit_matters=True):
    """Sessions of deals: a part is kept when its harmony fit is high (if fit_matters), else re-rolled."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        stem = M.STEMS[i % 4]
        x = [rng.uniform(0.4, 1), -rng.uniform(0, 0.3), -float(rng.integers(0, 4)), rng.uniform(0.5, 1), 0.0,
             rng.uniform(0, 1)]
        keep = (x[3] > 0.85) if fit_matters else (rng.random() < 0.15)
        track, bar0 = int(rng.integers(1, 30)), 4 * int(rng.integers(0, 8))
        out.append((T0 + 40 * i, "kept" if keep else "reroll", stem, track, bar0, 4, json.dumps(x), int(keep), 0.4))
    return out


def _cands(n=50, seed=3):
    rng = np.random.default_rng(seed)
    X = np.c_[rng.uniform(0.4, 1, n), -rng.uniform(0, 0.3, n), -rng.integers(0, 4, n), rng.uniform(0.5, 1, n),
              rng.normal(0, 0.1, n), rng.uniform(0, 1, n)]
    return list(rng.integers(1, 30, n)), X


def test_no_data_is_exactly_w0(tmp_path):
    con = _db(tmp_path / "a.sqlite", [])
    ch = M.fit(con, emb=emb, tdir=tdir())
    tracks, X = _cands()
    for stem in M.STEMS:
        mean, sd = ch.scores(stem, tracks, X)
        assert np.array_equal(mean, X @ stems.W0)                                # the same numbers, so the same order
        assert np.array_equal(np.argsort(-mean, kind="stable"), np.argsort(-(X @ stems.W0), kind="stable"))
        assert (sd > 0).all()                                                    # unsure, as it should be
        m1, s1 = ch.score(stem, tracks[0], 0, 4, X[0])
        assert m1 == pytest.approx(float(X[0] @ stems.W0)) and s1 == pytest.approx(sd[0])
    assert M.no_data().linear("bass", 7) == (pytest.approx(stems.W0), 0.0)
    # older five-feature rows are padded, as stems.weights does
    assert ch.score("bass", 1, 0, 4, X[0][:5])[0] == pytest.approx(float(X[0][:5] @ stems.W0[:5]))


def test_shapes_determinism_and_the_fast_paths_agree(tmp_path):
    con = _db(tmp_path / "a.sqlite", _events())
    a = M.fit(con, emb=emb, tdir=tdir())
    b = M.fit(con, emb=emb, tdir=tdir())
    assert np.array_equal(a.theta, b.theta) and a.hyper == b.hyper              # deterministic
    tracks, X = _cands()
    mean, sd = a.scores("other", tracks, X)
    assert mean.shape == sd.shape == (len(tracks),) and np.isfinite(mean).all() and (sd >= 0).all()
    one = np.array([a.score("other", t, 0, 4, x)[0] for t, x in zip(tracks, X)])
    lin = np.array([a.linear("other", t)[0] @ x + a.linear("other", t)[1] for t, x in zip(tracks, X)])
    assert np.allclose(mean, one) and np.allclose(mean, lin)
    assert a.n == len(MashupPart().examples(con)) and set(a.about()["taste"]) == set(M.STEMS)


def test_it_learns_what_the_events_say_and_stays_near_w0_when_they_say_nothing(tmp_path):
    w_fit = M.fit(_db(tmp_path / "a.sqlite", _events(400)), emb=emb, tdir=None)
    noise = M.fit(_db(tmp_path / "b.sqlite", _events(400, fit_matters=False)), emb=emb, tdir=None)
    i = M.FEATURES.index("fit")
    assert w_fit._w[i] > stems.W0[i] + 1                                        # kept when fit is high: fit counts more
    assert abs(noise._w[i] - stems.W0[i]) < abs(w_fit._w[i] - stems.W0[i])       # noise moves it less


def test_refit_never_sees_events_after_the_cut(tmp_path):
    ev = _events()
    cut = ev[150][0]
    full = _db(tmp_path / "a.sqlite", ev)
    early = _db(tmp_path / "b.sqlite", [e for e in ev if e[0] < cut])
    a, b = M.fit(full, until=cut, emb=emb, tdir=tdir()), M.fit(early, emb=emb, tdir=tdir())
    assert np.allclose(a.theta, b.theta) and a.n == b.n == len(MashupPart().examples(early))
    assert all(np.allclose(a.cent[s][k], b.cent[s][k]) for s in a.cent for k in (0, 1) if a.cent[s][k] is not None)
    # a later event that contradicts everything changes nothing before the cut
    later = [(t, "save", s, tr, b0, n, x, 1, 1.2) for t, _, s, tr, b0, n, x, _, _ in ev[150:]]
    flipped = _db(tmp_path / "c.sqlite", ev[:150] + later)
    assert np.allclose(M.fit(flipped, until=cut, emb=emb, tdir=tdir()).theta, a.theta)


def test_runs_in_the_harness_without_seeing_held_out_labels(tmp_path, monkeypatch):
    from test_reco import _library
    from digitalcrate import taste
    monkeypatch.setattr(E, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stems, "_emb", emb)
    con, _ = _library(tmp_path / "t.sqlite")
    con.executemany("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)",
                    [(T0 + 9000 + t, k, s, tr, b0, n, x, y, w) for t, k, s, tr, b0, n, x, y, w in _events(200)])
    con.commit()
    con.close()
    src = E.Source(tmp_path / "t.sqlite")
    taste._LIB.clear()
    try:
        task = MashupPart()
        task.min_class = 5
        r = E.evaluate(task, ["mashup.W0", "mashup.chooser"], ["song"], src=src, boot=20, save=False, verbose=False)
        got = r["splits"]["song"]["models"]["mashup.chooser"]
        assert got["coverage"] == 1.0 and got["metrics"]["auc"]["mean"] is not None
        # every held-out song's events are gone from what the model is fitted on
        ex = task.examples(src.con)
        fd = E.kfold(ex, 5, (0,))[0]
        m = src.masked(fd.hide(ex))
        held = {ex[i].group for i in fd.test}
        assert not {r[0] for r in m.execute("SELECT DISTINCT track FROM stem_events")} & held
        assert M.fit(m, emb=emb, tdir=None).n == len([e for e in ex if e.group not in held])
    finally:
        taste._LIB.clear()
        src.close()
