"""The shared taste model (reco/models/taste.py), on throwaway data (never the real library)."""
import json
import sqlite3
import time

import numpy as np
import pytest

from digitalcrate import stems
from digitalcrate.db import SCHEMA
from digitalcrate.reco import eval as E
from digitalcrate.reco.models import taste as T
from digitalcrate.reco.tasks import SampleTaste

T0 = 1_700_000_000.0


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _library(path, star=True, seed=0):
    """Twelve songs of ten samples. Songs 1-8 are heard: their first seven samples sit in one region of the sound space
    (you star those with the most of one quality of sound), the last three in a region you never heard. Songs 9-12 are never
    heard. star=False: the same library without the star on Vocals/s1_0.wav."""
    rng = np.random.default_rng(seed)
    ca, cb, u = _unit(rng.normal(size=(3, 512)))
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("""CREATE TABLE stem_events (ts REAL, kind TEXT, stem TEXT, track INTEGER, bar0 INTEGER, n INTEGER,
                   x TEXT, y INTEGER, w REAL)""")
    heard, far = [], []
    for t in range(1, 13):
        con.execute("INSERT INTO tracks (id, path, artist, title, genre) VALUES (?,?,?,?,?)",
                    (t, f"m/{t}.mp3", f"Artist {t % 5}", f"Song {t}", ["Jazz", "Soul"][t % 2]))
        for k in range(10):
            region = ca if k < 7 else cb
            mood = rng.normal()  # how much of the sound you like it has
            e = _unit(3 * region + 1.5 * mood * u + rng.normal(size=512) / np.sqrt(512) * 2)
            p = f"{['Vocals', 'Pads & Atmospheres'][k % 2]}/s{t}_{k}.wav"
            con.execute("""INSERT INTO samples (id, track_id, category, kind, dur, quality, loudness, key_strength, bpm,
                           source, clap, path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"id{t}_{k}", t, p.split("/")[0], "loop", 4.0, float(rng.random()), -20, 0.5, 90, "vocals",
                         e.astype(np.float16).tobytes(), p))
            if t <= 8 and k < 7:
                heard.append((p, mood))
            elif k >= 7:
                far.append(p)
    ts = T0
    cut = np.quantile([s for _, s in heard], 0.7)
    for i, (p, s) in enumerate(heard):
        ts += 40
        con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (ts, p, None, "listen", 0.9, None))
        if s > cut and (star or p != "Vocals/s1_0.wav"):
            con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (ts + 5, p, None, "star", 1, None))
            con.execute("INSERT INTO favorites (path, added_at) VALUES (?, ?)",
                        (p, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts + 5))))
    for k, (kind, y, tr) in enumerate([("save", 1, 2), ("reroll", 0, 3), ("save", 1, 4), ("reroll", 0, 5),
                                       ("reroll", 0, 6), ("kept", 1, 7)]):
        con.execute("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)",
                    (ts + 100 + k, kind, "vocals", tr, 0, 4, json.dumps([0] * 6), y, 1.0))
    con.commit()
    return con, [p for p, _ in heard], far


@pytest.fixture
def lib(tmp_path, monkeypatch):
    T._LIB.clear()
    emb = {}

    def fake_emb(track, stem):  # stands in for the stems' own embeddings (files on disk)
        if (track, stem) not in emb:
            emb[track, stem] = _unit(np.random.default_rng(100 + int(track)).normal(size=512)).astype(np.float32)
        return emb[track, stem]
    monkeypatch.setattr(stems, "_emb", fake_emb)
    con, heard, far = _library(tmp_path / "t.sqlite")
    yield con, heard, far
    con.close()
    T._LIB.clear()


def test_fit_and_score_any_item(lib):
    con, heard, far = lib
    t = T.fit(con)
    assert t is not None and t.n == len(heard) and t.n_pos >= 10 and t.n_parts == 6  # the vocal stems of songs 2-7
    assert 0 <= t.trust <= 1
    items = [("sample", heard[0]), ("sample", far[0]), ("sample", "gone.wav"), ("part", 2, "vocals", 0, 4),
             ("song", 3), ("song", 99), ("video", "never-seen")]
    m, sd = t.score(items)
    assert m.shape == sd.shape == (len(items),)
    ok = np.isfinite(m)
    assert ok.tolist() == [True, True, False, True, True, False, False]  # no CLAP embedding: NaN, not an error
    assert (sd[ok] > 0).all()
    p = t.proba(items)
    assert ((p[ok] > 0) & (p[ok] < 1)).all() and np.isnan(p[~ok]).all()
    a = t.about()
    assert set(a["prior_sd"]) == {"sound", "kernel", "meta", "song", "artist"} and a["n_pos"] == t.n_pos
    # what it learned ranks the favorites above the rest of what was heard
    fav = {r[0] for r in con.execute("SELECT path FROM favorites")}
    s = t.score([("sample", q) for q in heard])[0]
    assert E.auc([q in fav for q in heard], s) > 0.8


def test_uncertainty_grows_away_from_what_you_rated(lib, monkeypatch):
    con, heard, far = lib
    monkeypatch.setattr(stems, "_emb", lambda track, stem: np.zeros(512, np.float32))  # only samples rated
    t = T.fit(con)
    same_songs = [q for q in far if int(q.split("/s")[1].split("_")[0]) <= 8]  # unheard sounds in songs you rated
    sd_near = t.score([("sample", q) for q in heard])[1]
    sd_far = t.score([("sample", q) for q in same_songs])[1]
    assert sd_far.mean() > sd_near.mean() + 0.1
    # the same kind of sound in a song you never rated: the song's effect is unknown too
    rated = t.score([("sample", f"Vocals/s{k}_{j}.wav") for k in range(1, 9) for j in (0, 2, 4, 6)])[1]
    new = t.score([("sample", f"Vocals/s{k}_{j}.wav") for k in range(9, 13) for j in (0, 2, 4, 6)])[1]
    assert new.mean() > rated.mean()


def test_held_out_labels_cannot_leak(tmp_path, monkeypatch):
    """Two libraries that differ only in one star: hide that sample and the model's view of it is identical."""
    monkeypatch.setattr(stems, "_emb", lambda track, stem: np.zeros(512, np.float32))
    scores = []
    for star in (True, False):
        T._LIB.clear()
        con, heard, far = _library(tmp_path / f"t{star}.sqlite", star=star)
        con.close()
        src = E.Source(tmp_path / f"t{star}.sqlite")
        try:
            m = src.masked({("sample", "Vocals/s1_0.wav")})
            t = T.fit(m)
            assert "Vocals/s1_0.wav" not in T.evidence(m)[0]
            scores.append(t.score([("sample", "Vocals/s1_0.wav"), ("sample", heard[5])]))
            m.close()
        finally:
            src.close()
    assert np.allclose(scores[0][0], scores[1][0]) and np.allclose(scores[0][1], scores[1][1])
    T._LIB.clear()


def test_runs_inside_the_harness(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stems, "_emb", lambda track, stem: np.zeros(512, np.float32))
    T._LIB.clear()
    con, heard, far = _library(tmp_path / "t.sqlite")
    con.close()
    src = E.Source(tmp_path / "t.sqlite")
    try:
        task = SampleTaste()
        task.min_class, task.min_pos = 5, 4
        assert "reco.taste" in {m.name for m in task.models()}
        r = E.evaluate(task, ["reco.taste", "random"], ["song", "forward"], src=src, boot=20, save=False, verbose=False)
        e = r["splits"]["song"]["models"]["reco.taste"]
        assert e["coverage"] == 1.0 and e["metrics"]["auc"]["mean"] > 0.6 and e["metrics"]["ece"]["mean"] is not None
    finally:
        src.close()
        T._LIB.clear()


def test_deterministic_given_a_seed(lib):
    con, heard, far = lib
    items = [("sample", q) for q in heard[:10] + far[:5]] + [("part", 4, "vocals", 0, 4)]
    a = T.fit(con, seed=0).score(items)
    T._LIB.clear()
    b = T.fit(con, seed=0).score(items)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
    c = T.fit(con, seed=1).score(items)  # another seed: other kernel landmarks, a slightly different model
    assert not np.array_equal(a[0], c[0])


def test_until_sees_only_the_past(lib):
    con, heard, far = lib
    cut = T0 + 40 * 20 + 1
    samples, parts = T.evidence(con, until=cut)
    assert len(samples) == 20 and not parts  # the Mashup events came later
    t = T.fit(con, until=cut)
    assert t.n == 20 and t.n_parts == 0 and t.trust == 0.0
