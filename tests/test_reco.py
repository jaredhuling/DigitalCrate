"""The recommendation log, item store and evaluation harness, on a throwaway library (never the real one)."""
import json
import sqlite3
import time

import numpy as np
import pytest

from digitalcrate.db import SCHEMA
from digitalcrate.reco import eval as E
from digitalcrate.reco import log as L
from digitalcrate.reco.tasks import MashupPart, NewSongs, SampleTaste

T0 = 1_700_000_000.0
CATS = ["Vocals", "Pads & Atmospheres", "Chords & Keys"]


def _library(path, n_tracks=12, per=5, seed=0):
    """A small library: tracks, samples with CLAP-like embeddings, and a history on every surface."""
    rng = np.random.default_rng(seed)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("""CREATE TABLE stem_events (ts REAL, kind TEXT, stem TEXT, track INTEGER, bar0 INTEGER, n INTEGER,
                   x TEXT, y INTEGER, w REAL)""")
    con.execute("""CREATE TABLE edit_ratings (ts REAL, path TEXT, sample_id TEXT, source TEXT, move TEXT, family TEXT,
                   material TEXT, arm TEXT, params TEXT, delta BLOB, close REAL, rating INTEGER, reason TEXT)""")
    con.execute("CREATE TABLE collection_items (collection TEXT, path TEXT, sample_id TEXT, added_at REAL)")
    con.execute("CREATE TABLE stem_mixes (name TEXT PRIMARY KEY, state TEXT, updated_at TEXT)")
    for c, t in (("mode", "TEXT"), ("seen", "INTEGER"), ("emb", "BLOB")):  # added to yt_scout by ytscout._db
        con.execute(f"ALTER TABLE yt_scout ADD COLUMN {c} {t}")
    paths = []
    for t in range(1, n_tracks + 1):
        con.execute("INSERT INTO tracks (id, path, artist, title, bpm, key) VALUES (?,?,?,?,?,?)",
                    (t, f"m/{t}.mp3", f"Artist {t % 4}", f"Song {t}", 90 + t, "C"))
        for k in range(per):
            e = rng.normal(size=512); e /= np.linalg.norm(e)
            p = f"{CATS[k % 3]}/s{t}_{k}.wav"
            con.execute("""INSERT INTO samples (id, track_id, category, kind, dur, centroid, flatness, pratio, scale,
                           quality, loudness, key_strength, bpm, clap, path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"id{t}_{k}", t, CATS[k % 3], "loop", 4.0, 1500, 0.02, 0.1, "minor", float(rng.random()),
                         -20, 0.5, 90, e.astype(np.float16).tobytes(), p))
            paths.append(p)
    ts = T0
    for i, p in enumerate(paths[:45]):  # three sessions of listening (an hour apart), stars on every fourth
        ts += 30 if i % 15 else 3600
        con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (ts, p, None, "listen", 0.9, None))
        if i % 4 == 0:
            con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (ts + 5, p, None, "star", 1, None))
            con.execute("INSERT INTO favorites (path, added_at) VALUES (?, ?)",
                        (p, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts + 5))))
        elif i % 7 == 0:
            con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (ts + 5, p, None, "dislike", 1, None))
    con.execute("INSERT INTO collection_items VALUES (?,?,?,?)", ("c", paths[46], None, ts + 10))
    x = [0.9, -0.1, 0, 0.8, 0.0, 0.5]
    for k, (kind, y, w) in enumerate([("reroll", 0, 0.4), ("save", 1, 1.2), ("save", 1, 1.2), ("kept", 1, 0.4)]):
        con.execute("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)",
                    (ts + 100 + k, kind, "bass", 3, 8, 4, json.dumps(x), y, w))
    con.execute("INSERT INTO stem_mixes VALUES (?,?,?)",
                ("a working title", json.dumps(dict(slots=dict(bass=dict(stem="bass", track=3, bar0=8, n=4)))),
                 "2023-11-14 22:20:00"))
    con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (ts + 200, paths[0], None, "suggest", 1,
                json.dumps(dict(move="wash", family="space", arm="critic", material="vocal", action="apply"))))
    con.execute("INSERT INTO edit_ratings (ts, path, move, family, material, arm, params, rating) VALUES (?,?,?,?,?,?,?,?)",
                (ts + 210, paths[0], "wash", "space", "vocal", "critic", "{}", 1))
    con.execute("INSERT INTO pair_votes VALUES (?,?,?)", ("id1_0-id2_1", 4, ts + 300))
    con.execute("INSERT INTO yt_scout (id, title, score, status, created_at, seen) VALUES (?,?,?,?,?,?)",
                ("vid1", "a find", 1.2, "ingested", "2023-11-15 06:00:00", 1))
    con.commit()
    return con, paths


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RUNS", tmp_path / "runs")
    con, paths = _library(tmp_path / "t.sqlite")
    con.close()
    src = E.Source(tmp_path / "t.sqlite")
    yield src, paths
    src.close()


def test_adapters_read_every_surface(lib):
    src, paths = lib
    its = L.interactions(src.con)
    acts = {(i.surface, i.action) for i in its}
    assert {("samples", "listen"), ("samples", "star"), ("samples", "favorite"), ("samples", "dislike"),
            ("samples", "collect"), ("mashup", "save"), ("mashup", "reroll"), ("mashup", "in_saved_mix"),
            ("edits", "apply"), ("edits", "rate"), ("pairs", "vote"), ("scout", "ingested")} <= acts
    assert [i.ts for i in its] == sorted(i.ts for i in its)
    assert len({i.session for i in its if i.action == "listen"}) == 3          # an hour's gap starts a new session
    vote = next(i for i in its if i.action == "vote")
    assert vote.item == ("pair", "Vocals/s1_0.wav", "Pads & Atmospheres/s2_1.wav") and vote.value == 4
    assert next(i for i in its if i.action == "reroll").item == ("part", 3, "bass", 8, 4)
    mix = next(i for i in its if i.action == "in_saved_mix")
    assert "a working title" not in json.dumps(mix.context)                     # names stay out of the log
    fav = next(i for i in its if i.action == "favorite")
    star = next(i for i in its if i.action == "star" and i.item == fav.item)
    assert abs(fav.ts - star.ts) < 1                                            # text timestamps are read as UTC
    s = L.summary(src.con)
    assert s["counts"][("samples", "listen")] == 45 and s["counts"][("mashup", "save")] == 2


def test_items_link_samples_songs_and_artists(lib):
    from digitalcrate.reco.items import Items
    src, paths = lib
    it = Items(src.con)
    assert it.song_of(("sample", paths[0])) == 1 and it.song_of(("part", 3, "bass", 8, 4)) == 3
    assert it.artist_of(("sample", paths[0])) == "artist 1" and 1 in it.songs_of("ARTIST  1")
    assert set(it.samples_of(2)) == {p for p in paths if "/s2_" in p}
    E_, ok = it.clap([("sample", paths[0]), ("sample", "gone.wav"), ("song", 2), ("pair", paths[0], paths[1])])
    assert ok.tolist() == [True, False, True, True] and abs(np.linalg.norm(E_[0]) - 1) < 1e-3 and not E_[1].any()
    S, ok = it.style([("sample", paths[0])])
    assert not ok[0] and not S.any()                                            # never style-tagged: zeros + mask
    X, mask, names = it.numeric([("sample", paths[0]), ("video", "vid1")])
    assert mask[0, names.index("quality")] and not mask[1].any()


def test_metrics_match_hand_computed_values():
    y, s = np.array([1, 0, 1, 0], bool), np.array([.9, .8, .3, .1])
    assert E.auc(y, s) == pytest.approx(0.75)
    assert E.auc([1, 0], [.5, .5]) == pytest.approx(0.5)                       # a tie counts half
    assert E.average_precision(y, s) == pytest.approx((1 + 2 / 3) / 2)
    tie = np.arange(4)
    assert E.ndcg_at(y.astype(float), s, 2, tie) == pytest.approx(1 / (1 + 1 / np.log2(3)))
    assert E.recall_at(y, s, 2, tie) == pytest.approx(0.5)
    w = np.array([1.0, 1.0])
    assert E.log_loss(np.array([1.0, 0.0]), np.array([.8, .2]), w) == pytest.approx(-np.log(.8))
    assert E.ece(np.array([1.0, 0.0]), np.array([.8, .2]), w) == pytest.approx(0.2)
    # a weight of 2 is the example counted twice (what the bootstrap relies on)
    w2 = np.array([2.0, 1, 1, 1])
    assert E.auc(y, s, w2) == pytest.approx(E.auc(np.r_[y, True], np.r_[s, .9]))
    # the prepared form gives the same numbers; within a query only pairs from the same query count
    q = np.array(["a", "a", "b", "b"])
    m = E.Prep(y, s, q=q, ks=(1,)).metrics()
    assert m["auc"] == pytest.approx(0.75) and m["ap"] == pytest.approx((1 + 2 / 3) / 2)
    assert m["qauc"] == pytest.approx(1.0) and m["ndcg@1"] == pytest.approx(1.0) and m["queries"] == 2
    assert E.Prep(y, s, q=q).metrics(w2)["auc"] == pytest.approx(E.auc(y, s, w2))
    assert E.auc([1, 1], [.2, .3]) is None                                      # one class: no number


def test_splits_are_deterministic_and_match_the_taste_page(lib):
    src, paths = lib
    ex = SampleTaste().examples(src.con)
    a = SampleTaste().folds(ex, "sample")
    assert [f.test for f in a] == [f.test for f in SampleTaste().folds(ex, "sample")]
    # taste_report.accuracy: sorted paths, shuffled with default_rng(seed), every fifth from k
    for f in a:
        seed, k = int(f.name[1]), int(f.name[3])
        arr = np.array(sorted(e.item[1] for e in ex))
        np.random.default_rng(seed).shuffle(arr)
        assert {ex[i].item[1] for i in f.test} == set(arr[k::5].tolist())
        assert not set(f.test) & set(f.train) and len(f.test) + len(f.train) == len(ex)
    song = SampleTaste().folds(ex, "song")
    for f in song:  # by song: a song is never on both sides
        assert not {ex[i].group for i in f.test} & {ex[i].group for i in f.train}
    task = NewSongs()  # new songs: only held-out samples whose song has nothing at all in training
    for f in task.folds(ex, "sample"):
        tr = E.Train(src.masked(f.hide(ex)), [ex[i] for i in f.train], f, task.name)
        kept = [ex[i] for i in f.test if task.keep(tr, ex[i])]
        assert not {e.group for e in kept} & {ex[i].group for i in f.train} and len(kept) < len(f.test)
    for f in E.forward(ex, min_pos=3):
        assert all(ex[i].ts < f.until for i in f.train) and all(ex[i].ts >= f.until for i in f.test)


def _memorizer():
    """Scores what it was told: 1 for a sample it can see starred, 0 for one it saw otherwise, 0.5 if unseen."""
    def fit(train):
        fav = {r[0] for r in train.con.execute("SELECT path FROM favorites")}
        seen = {r[0] for r in train.con.execute("SELECT path FROM events")}
        return lambda items, ctx: np.array([1.0 if it[1] in fav else 0.0 if it[1] in seen else 0.5 for it in items])
    return E.Model("memorize", fit)


def test_held_out_labels_cannot_leak(lib):
    src, paths = lib
    for split in ("sample", "song", "forward"):
        task = SampleTaste()
        task.min_pos, task.min_class = 3, 2  # a tiny library
        r = E.evaluate(task, [_memorizer()], [split], src=src, boot=20, save=False, verbose=False)
        m = r["splits"][split]["models"]["memorize"]["metrics"]["auc"]
        assert m["mean"] == pytest.approx(0.5), split                           # it never sees a held-out label
    # ...and it does memorize what it is allowed to see: scored on its own training items it is perfect
    con = src.masked()
    s = _memorizer().fit(E.Train(con, [], E.Fold("all", "all", [], []), "t"))
    ex = SampleTaste().examples(src.con)
    assert E.auc([e.label > 0 for e in ex], s([e.item for e in ex], None)) == pytest.approx(1.0)
    # the masked database: no hidden rows, nothing after the cut, label tables unreachable through the attachment
    hide = {("sample", paths[0])}
    m = src.masked(hide, until=T0 + 3700)
    assert not m.execute("SELECT COUNT(*) FROM events WHERE path=?", (paths[0],)).fetchone()[0]
    assert m.execute("SELECT MAX(ts) FROM events").fetchone()[0] < T0 + 3700
    assert m.execute("SELECT status FROM yt_scout").fetchone()[0] is None      # the find stays, its label doesn't
    assert m.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == len(paths)
    with pytest.raises(sqlite3.OperationalError):
        m.execute("SELECT * FROM lib.events")
    with pytest.raises(sqlite3.OperationalError):                               # and the library itself is read-only
        src.con.execute("DELETE FROM events")


def test_the_live_taste_model_runs_inside_the_harness(lib):
    from digitalcrate import taste
    src, paths = lib
    taste._LIB.clear()
    try:
        task = SampleTaste()
        task.min_class = 5
        r = E.evaluate(task, ["taste", "taste.regression", "quality", "random"], ["song"], src=src, boot=20,
                       save=True, verbose=False)
        e = r["splits"]["song"]
        assert set(e["models"]) == {"taste", "taste.regression", "quality", "random"}
        assert e["models"]["taste"]["coverage"] == 1.0 and "vs_ref" in e["models"]["random"]
        assert E.latest("sample_taste")["data"]["hash"] == src.signature()["hash"]
        assert "sample_taste / song" in E.table(E.latest())
    finally:
        taste._LIB.clear()


def test_mashup_examples_drop_re_saves(lib):
    src, paths = lib
    task = MashupPart()
    ex = task.examples(src.con)
    assert [e.label for e in ex] == [0.0, 1.0, 1.0]                             # reroll, save, kept: the second save went
    assert all(e.query == ex[0].query and e.group == 3 for e in ex) and "re-saves" in task.notes[0]
    assert "x" in ex[0].context and "kind" not in ex[0].context                 # the scorer never sees the label


def test_impressions_round_trip(tmp_path):
    con = sqlite3.connect(tmp_path / "i.sqlite")
    con.row_factory = sqlite3.Row
    assert L.impressions(con) == []                                             # no table yet: nothing, no error
    a, b = ("part", 3, "bass", 8, 4), ("part", 5, "bass", 0, 4)
    i = L.impression(con, "mashup", dict(bpm=90, key="Am"), [(a, 1.2, 0.7), dict(item=b, score=0.4, p=0.3)],
                     policy=dict(model="W0", version=1))
    L.chose(con, i, a)
    j = L.impression(con, "samples", {}, [(("sample", "x.wav"), 0.5, 1.0)], chosen=("sample", "x.wav"), ts=1.0)
    got = L.impressions(con)
    assert [g["id"] for g in got] == [j, i]                                     # oldest first
    assert got[1]["shown"][0] == dict(item=a, score=1.2, p=0.7) and got[1]["shown"][1]["item"] == b
    assert got[1]["chosen"] == a and got[1]["policy"] == dict(model="W0", version=1)
    assert got[1]["context"] == dict(bpm=90, key="Am")
    assert [g["id"] for g in L.impressions(con, surface="samples")] == [j]


# ---------------------------------------------------------------- Mashup: impressions for every deal, outcomes tied to them

class _Draw:
    """An rng that remembers the chances it was given and draws the index asked for."""
    def __init__(self, at=0):
        self.at, self.p = at, None

    def choice(self, a, p=None):
        self.p = np.asarray(p, float)
        return (np.arange(a) if np.isscalar(a) else np.asarray(a))[self.at]


@pytest.fixture
def mashup(tmp_path, monkeypatch):
    """The stem mixer on its own throwaway database: 12 prepared songs and a few dozen one-shots and pads."""
    from digitalcrate import stems, taste
    from digitalcrate.db import SCHEMA
    from test_units import _fake_stem_song
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    monkeypatch.setattr(stems, "SHOWN", 3)          # so that some candidates fall outside what an impression lists
    monkeypatch.setattr(taste, "cached_scores", lambda: {})

    def _con():
        c = sqlite3.connect(tmp_path / "t.sqlite")
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={})
    stems._EMB.clear()
    stems._OS["n"] = -1
    stems._PADS["n"] = -1
    stems._STASH.clear()
    for t in range(1, 13):
        _fake_stem_song(tmp_path, t, 96 + t, 0, "major", (t * 5) % 12)
    con = _con()
    con.executescript(SCHEMA)
    con.execute("ALTER TABLE samples ADD COLUMN parent_id TEXT")                    # (as db.connect adds it)
    con.execute("INSERT INTO tracks (id, path, artist, title) VALUES (1, 'm/1.wav', 'A', 'T')")
    rng = np.random.default_rng(1)
    for i in range(50):
        cat, dur, kind = (("Vocals", 0.8, "oneshot") if i < 25 else ("Pads & Atmospheres", 3.0, "loop"))
        con.execute("""INSERT INTO samples (id, track_id, category, kind, dur, key, scale, key_from, chroma, path)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""", (f"s{i}", 1, cat, kind, dur, "C", "major", "file",
                                                          json.dumps(rng.random(12).round(3).tolist()), f"{cat}/s{i}.wav"))
    con.commit()
    yield stems, con
    con.close()
    stems._LIB.update(n=-1, lib={})
    stems._OS["n"] = -1
    stems._PADS["n"] = -1


STATE = dict(bpm=100, key=None, slots=dict(other=dict(stem="other", track=1, bar0=0, n=4, k=1, off=0),
                                           drums=dict(stem="drums", track=2, bar0=4, n=4, k=1, off=0)))


def _sums_to_one(rec):
    shown = sum(s["p"] for s in rec["shown"])
    return shown + rec["context"]["rest"]["p"]


def test_a_deal_records_every_candidate_with_its_exact_chance(mashup):
    stems, con = mashup
    draw, rec = _Draw(at=2), {}
    part = stems.pick("bass", STATE, rng=draw, slot="bass", rec=rec, avoid=[5])
    P = draw.p / draw.p.sum()
    assert len(rec["shown"]) == 3 and rec["context"]["rest"]["n"] >= 5
    assert [s["p"] for s in rec["shown"]] == pytest.approx(P[:3].tolist())       # the very chances the draw used
    assert rec["context"]["rest"]["p"] == pytest.approx(P[3:].sum())
    assert _sums_to_one(rec) == pytest.approx(1.0)
    assert rec["chosen"] == L.part(part["track"], "bass", part["bar0"], 4) == rec["shown"][2]["item"]
    assert rec["context"]["p"] == pytest.approx(P[2]) and rec["context"]["x"] == rec["shown"][2]["x"]
    c = rec["context"]
    assert c["slot"] == "bass" and c["role"] == "bass" and c["bpm"] == 100 and c["n"] == 4 and c["song"] is None
    assert [1, "other", 0, 4, 1.0] == c["others"][0][:5] and c["others"][1][1] == "drums"
    assert 5 in c["avoid"] and {1, 2} <= set(c["playing"])                          # what sat out, and why
    assert all(s["item"][1] not in (1, 2, 5) for s in rec["shown"])
    assert rec["policy"]["model"] == "stems.pick" and len(rec["policy"]["w"]) == 6
    i = stems.deal(rec, "mashup.dice", "dice")
    got = L.impressions(con, surface="mashup.dice")
    assert [g["id"] for g in got] == [i] and got[0]["chosen"] == rec["chosen"] and got[0]["context"]["via"] == "dice"
    assert got[0]["shown"][0]["x"] == rec["shown"][0]["x"]                          # a candidate's features are kept
    # you chose the song: its best part, for certain
    rec = {}
    part = stems.pick("bass", STATE, slot="bass", track=7, rec=rec)
    assert rec["shown"][0]["p"] == 1.0 and _sums_to_one(rec) == pytest.approx(1.0) and rec["context"]["song"] == 7
    assert rec["chosen"][1] == 7 == part["track"]
    # a one-shot and a pad: their draws too, chances summing to one over everything on offer
    for fn, role in ((stems.oneshot, "oneshot"), (stems.pad, "pad")):
        draw, rec = _Draw(at=4), {}
        part = fn(STATE, 2, rng=draw, rec=rec, slot="x")
        P = draw.p / draw.p.sum()
        assert [s["p"] for s in rec["shown"]] == pytest.approx(P[:3].tolist()), role
        assert _sums_to_one(rec) == pytest.approx(1.0) and rec["chosen"] == ("sample", part["sample"])
        assert rec["context"]["p"] == pytest.approx(P[4]) and rec["policy"]["model"] == f"stems.{role}"
    rec = {}
    assert stems.oneshot(STATE, 1, path="Vocals/s3.wav", rec=rec)["sample"] == "Vocals/s3.wav"
    assert rec["shown"][0]["p"] == 1.0 and rec["chosen"] == ("sample", "Vocals/s3.wav")
    # the best-fits list is a ranking: listed with scores, no chances, and what you clicked becomes its chosen item
    rec = {}
    out = stems.top_fits("bass", STATE, "bass", top=3, rec=rec)
    assert [s["item"][1] for s in rec["shown"]] == [q["track"] for q in out] and rec["shown"][0]["p"] is None
    li = stems.deal(rec, "mashup.best_list", "best")
    stems.listed(li, 1)
    assert L.impressions(con, surface="mashup.best_list")[0]["chosen"] == rec["shown"][1]["item"]
    # a prefetched deal is written only once it is played
    rec = {}
    stems.pick("vocals", STATE, slot="vocals", rec=rec)
    tok = stems.deal(rec, "mashup.dice", "pre", pre=True)
    assert not L.impressions(con, surface="mashup.dice")[1:]
    j = stems.dealt(tok, "all")
    got = L.impressions(con, surface="mashup.dice")[-1]
    assert got["id"] == j and got["context"]["via"] == "all" and "prefetched" in got["context"]
    assert stems.dealt(tok) is None and stems.dealt("nonsense") is None


def test_a_deal_goes_on_when_its_record_cannot_be_written(mashup, monkeypatch, capsys):
    stems, con = mashup
    rec = {}
    assert stems.pick("bass", STATE, slot="bass", rec=rec)
    monkeypatch.setattr(L, "impression", lambda *a, **k: 1 / 0)
    assert stems.deal(rec, "mashup.dice", "dice") is None and "not recorded" in capsys.readouterr().err


def test_outcomes_are_tied_to_their_deal(mashup):
    stems, con = mashup
    rec = {}
    part = stems.pick("bass", STATE, slot="bass", rec=rec)
    i = stems.deal(rec, "mashup.dice", "dice")
    q = dict(track=part["track"], stem="bass", bar0=part["bar0"], n=4, k=part["k"])
    n = stems.outcomes([dict(imp=i, slot="bass", role="bass", part=q, action="heard", value=30, secs=30.4),
                        dict(imp=i, slot="bass", role="bass", part=q, action="replaced", secs=41.2, by="dice"),
                        dict(imp=None, slot="x", role="oneshot", part=dict(sample="Vocals/s1.wav"), action="starred",
                             value=1, secs=3),
                        dict(imp=None, slot="y", role="oneshot", part=dict(sample="stem:3:other:8:4:1:0:0:0"),
                             action="removed", secs=0)])
    assert n == 4
    its = L.interactions(con, tables=["reco_outcomes"])
    assert [(t.surface, t.action) for t in its] == [("mashup", a) for a in ("heard", "replaced", "starred", "removed")]
    assert its[1].item == rec["chosen"] and its[1].context["imp"] == i and its[1].context["secs"] == 41.2
    assert its[1].context["by"] == "dice" and its[0].value == 30
    assert its[2].item == ("sample", "Vocals/s1.wav") and its[3].item == ("part", 3, "other", 8, 4)
    assert [o["action"] for o in L.outcomes(con, imp=i)] == ["heard", "replaced"]
    # an undo is not a judgment: it is recorded as such, and teaches the live model nothing
    before = con.execute("SELECT COUNT(*) FROM stem_events").fetchone()[0]
    stems.outcomes([dict(imp=i, slot="bass", role="bass", part=q, action="undone", secs=2, by="undo"),
                    dict(imp=i, slot="bass", role="bass", part=q, action="restored", secs=41.2, by="undo")])
    assert con.execute("SELECT COUNT(*) FROM stem_events").fetchone()[0] == before
    assert {o["action"] for o in L.outcomes(con, imp=i)} == {"heard", "replaced", "undone", "restored"}


def test_saving_again_adds_nothing(mashup):
    stems, con = mashup
    st = json.loads(json.dumps(STATE))
    outs = lambda s: [dict(imp=None, slot=k, role=p["stem"], part=p, action="saved", secs=1) for k, p in s["slots"].items()]
    saves = lambda: con.execute("SELECT COUNT(*) FROM stem_events WHERE kind='save'").fetchone()[0]
    stems.save("my mix", st, st, outs(st))
    assert saves() == 2 and len(L.outcomes(con, action="saved")) == 2
    stems.save("my mix", st, st, outs(st))                                          # unchanged: nothing more
    assert saves() == 2 and len(L.outcomes(con, action="saved")) == 2
    old = dict(st["slots"]["other"])
    st["slots"]["other"] = dict(old, track=3)
    stems.save("my mix", st, st, outs(st))                                          # one new part: one more
    assert saves() == 3 and len(L.outcomes(con, action="saved")) == 3
    st["slots"]["other"] = old                                                      # swapped back: already saved
    st["slots"]["twin"] = dict(old)                                                 # and twice in one mix: once
    stems.save("my mix", st, st, outs(st))
    assert saves() == 3 and len(L.outcomes(con, action="saved")) == 3
    stems.save("another", st, st, outs(st))                                         # another mix: its own yes
    assert saves() == 5 and len(L.outcomes(con, action="saved")) == 5
    assert "my mix" not in json.dumps([o["context"] for o in L.outcomes(con)])      # names stay out of the log
    assert {o["context"]["mix"] for o in L.outcomes(con)} == {stems._mix_tag("my mix"), stems._mix_tag("another")}


def test_the_log_reads_outcomes_and_the_summary_shows_the_new_surfaces(lib, capsys):
    src, paths = lib
    con = sqlite3.connect(src.path)
    con.row_factory = sqlite3.Row
    a = ("part", 3, "bass", 8, 4)
    i = L.impression(con, "mashup.dice", dict(slot="bass"), [dict(item=a, score=1.0, p=1.0)], a)
    L.outcome(con, i, "mashup", a, "replaced", None, dict(secs=4.0, by="dice"), ts=T0 + 5000)
    con.close()
    its = L.interactions(src.con)
    r = next(t for t in its if t.action == "replaced")
    assert r.surface == "mashup" and r.item == a and r.context["imp"] == i and r.context["_src"][0] == "reco_outcomes"
    L.print_summary(src.con)
    out = capsys.readouterr().out
    assert "mashup.dice" in out and "replaced" in out
    m = src.masked({a})                                                             # the harness hides it like any label
    assert not m.execute("SELECT COUNT(*) FROM reco_outcomes").fetchone()[0]
    assert src.masked().execute("SELECT COUNT(*) FROM reco_outcomes").fetchone()[0] == 1
