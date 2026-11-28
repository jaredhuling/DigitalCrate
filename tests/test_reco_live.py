"""The switch-over: what the app serves from the reco models (reco/live.py), the parts you turned down
(reco/rejected.py), the Mashup dice's taste term (reco/models/mashup.taste_only), on throwaway data."""
import json
import sqlite3

import numpy as np
import pytest

from digitalcrate import stems
from digitalcrate.reco import eval as E
from digitalcrate.reco import live
from digitalcrate.reco import log as L
from digitalcrate.reco.models import mashup as M
from digitalcrate.reco.rejected import Rejections
import digitalcrate.reco.rejected as R

from test_reco import STATE, _Draw, mashup  # noqa: F401  (the Mashup fixture)

DAY = 86400.0
NOW = 1_800_000_000.0


# ---------------------------------------------------------------- parts you turned down

def test_a_rejection_costs_more_each_time_and_fades():
    one = Rejections([(NOW - 60, 5, "bass", 8, 4, 1.0)], [], NOW)
    three = Rejections([(NOW - k * 3600, 5, "bass", 8, 4, 1.0) for k in (1, 2, 3)], [], NOW)
    old = Rejections([(NOW - 3 * R.PART_HALF_LIFE * DAY, 5, "bass", 8, 4, 1.0)], [], NOW)
    p1, p3 = one.penalty(5, "bass", 8, 4), three.penalty(5, "bass", 8, 4)
    assert p1 > 0.9 * R.PART_PENALTY and p3 > p1                          # grows with the number of rejections
    assert p3 <= R.PART_CAP + R.SONG_CAP                                  # but not without bound
    assert old.penalty(5, "bass", 8, 4) < p1 / 6                          # fades over days
    many = Rejections([(NOW - k * 3600, 5, "bass", 8, 4, 1.0) for k in range(1, 30)], [], NOW)
    assert many.penalty(5, "bass", 8, 4) == pytest.approx(R.PART_CAP + R.SONG_CAP, rel=1e-3)


def test_what_counts_as_the_same_part_and_the_song():
    rj = Rejections([(NOW - 60, 5, "bass", 8, 4, 1.0)], [], NOW)
    same, overlap, other_bars = rj.penalty(5, "bass", 8, 4), rj.penalty(5, "bass", 10, 4), rj.penalty(5, "bass", 20, 4)
    assert overlap == pytest.approx(same)                                 # overlapping bars: the same part
    assert 0 < other_bars < same / 3                                      # the song's other parts: a mild version
    assert rj.penalty(5, "vocals", 8, 4) == 0 and rj.penalty(6, "bass", 8, 4) == 0   # other stem, other song: none
    # one rejection logged twice (an outcome and its legacy event, seconds apart) counts once
    twice = Rejections([(NOW - 60, 5, "bass", 8, 4, 1.0), (NOW - 58, 5, "bass", 8, 4, 1.0)], [], NOW)
    assert twice.penalty(5, "bass", 8, 4) == pytest.approx(same)


def test_anything_kept_clears_it():
    down = [(NOW - 60, 5, "bass", 8, 4, 1.0)] * 1 + [(NOW - 7200, 5, "bass", 8, 4, 1.0)]
    kept_part = Rejections(down, [(5, "bass", 8, 4)], NOW)
    assert kept_part.penalty(5, "bass", 8, 4) == 0 and kept_part.penalty(5, "bass", 20, 4) == 0
    kept_elsewhere = Rejections(down, [(5, "bass", 24, 4)], NOW)        # the song's stem was kept, other bars
    assert kept_elsewhere.penalty(5, "bass", 20, 4) == 0                 # no song penalty
    assert kept_elsewhere.penalty(5, "bass", 8, 4) > 0                   # these bars were still turned down


def test_it_reads_the_outcomes_and_the_legacy_log(tmp_path):
    con = sqlite3.connect(tmp_path / "r.sqlite")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE stem_events (ts REAL, kind TEXT, stem TEXT, track INTEGER, bar0 INTEGER, n INTEGER,
                   x TEXT, y INTEGER, w REAL)""")
    ev = [(NOW - 100, "reroll", "bass", 3, 0, 4), (NOW - 100, "save", "other", 4, 0, 4),
          (NOW - 90, "reroll", "other", 4, 0, 4), (NOW - 80, "dislike", "drums", 9, 0, 4)]
    con.executemany("INSERT INTO stem_events VALUES (?,?,?,?,?,?,'[]',0,1)", ev)
    a, b, c = L.part(7, "vocals", 0, 4), L.part(8, "vocals", 0, 4), L.part(11, "vocals", 0, 4)
    L.outcome(con, None, "mashup", a, "replaced", None, dict(by="dice", secs=4), ts=NOW - 50)    # quick: turned down
    L.outcome(con, None, "mashup", b, "replaced", None, dict(by="dice", secs=300), ts=NOW - 50)  # heard 5 min: not
    L.outcome(con, None, "mashup", c, "replaced", None, dict(by="new", secs=2), ts=NOW - 50)     # a new mix: not
    L.outcome(con, None, "mashup", L.part(12, "bass", 0, 4), "rated", -1, dict(secs=10), ts=NOW - 40)
    L.outcome(con, None, "mashup", L.part(13, "bass", 0, 4), "replaced", None, dict(by="dice", secs=1), ts=NOW - 40)
    L.outcome(con, None, "mashup", L.part(13, "bass", 0, 4), "locked", None, dict(secs=1), ts=NOW - 30)
    rj = Rejections.load(con, NOW)
    assert rj.penalty(3, "bass", 0, 4) > 0.9 and rj.penalty(4, "other", 0, 4) == 0   # saved once: never penalized
    assert 0 < rj.penalty(9, "drums", 0, 4) < rj.penalty(3, "bass", 0, 4)           # a thumbs-down mix: half
    assert rj.penalty(7, "vocals", 0, 4) > 0.9 and rj.penalty(8, "vocals", 0, 4) == 0 == rj.penalty(11, "vocals", 0, 4)
    assert rj.penalty(12, "bass", 0, 4) > 0.9 and rj.penalty(13, "bass", 0, 4) == 0
    assert Rejections.load(sqlite3.connect(":memory:")).penalty(3, "bass", 0, 4) == 0  # no tables yet: nothing


def test_the_dice_stops_dealing_a_part_you_keep_throwing_out(mashup):
    stems_, con = mashup
    st = json.loads(json.dumps(STATE))

    def chances():
        rec = {}
        stems_.pick("bass", st, slot="bass", rec=rec, rng=np.random.default_rng(0))
        return {s["item"][1]: s["p"] for s in rec["shown"]}, rec
    stems_.SHOWN = 40
    before, rec = chances()
    assert rec["policy"]["mashup"] == "new" and rec["policy"]["rejected"] == 0
    fav = max(before, key=before.get)                                    # the song it deals most
    item = next(s["item"] for s in rec["shown"] if s["item"][1] == fav)
    for k in range(3):
        L.outcome(con, None, "mashup", item, "replaced", None, dict(by="dice", secs=2))
        con.execute("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)",
                    (1e9 + 1000 * k, "reroll", "bass", item[1], item[3], item[4], "[]", 0, 0.4))  # long ago: faded
    con.commit()
    after, rec = chances()
    assert rec["policy"]["rejected"] >= 3
    assert after.get(fav, 0) < before[fav] / 3                          # dealt far less now
    live.set_setting("mashup", "w0")                                     # W0 alone: the same penalty
    w0, rec = chances()
    assert rec["policy"]["mashup"] == "w0" and rec["policy"]["rejected"] >= 3 and w0.get(fav, 0) < before[fav] / 3
    live.set_setting("mashup", "old")                                    # the old dice: as it was, no penalty
    old, rec = chances()
    assert rec["policy"]["mashup"] == "old" and "rejected" not in rec["policy"] and len(rec["policy"]["w"]) == 6


# ---------------------------------------------------------------- the dice's taste term

def _ev_db(path, n=240, seed=0):
    rng = np.random.default_rng(seed)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE stem_events (ts REAL, kind TEXT, stem TEXT, track INTEGER, bar0 INTEGER, n INTEGER,
                   x TEXT, y INTEGER, w REAL)""")
    rows = []
    for i in range(n):
        stem, track = M.STEMS[i % 4], int(rng.integers(1, 30))
        keep = track % 3 == 0 if stem != "drums" else rng.random() < 0.2  # pitched stems: kept by "taste" (track % 3)
        x = [rng.uniform(.4, 1), -rng.uniform(0, .3), -float(rng.integers(0, 4)), rng.uniform(.5, 1), 0.0, .5]
        rows.append((1.7e9 + 40 * i, "kept" if keep else "reroll", stem, track, 0, 4, json.dumps(x), int(keep), .4))
    con.executemany("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return con


class _T:
    """A stand-in for the shared taste model: songs whose id is a multiple of three sound like what you like."""
    def score(self, items):
        m = np.array([1.5 if it[1] % 3 == 0 else -0.5 for it in items], float)
        return m, np.ones(len(items))


def _emb(track, stem):
    e = np.random.default_rng(int(track) * 10 + M.STEMS.index(stem)).normal(size=512)
    return e / np.linalg.norm(e)


def test_the_dice_score_is_w0_plus_taste_and_nothing_else(tmp_path):
    con = _ev_db(tmp_path / "a.sqlite")
    ch = M.taste_only(con, _T(), emb=_emb)
    assert np.array_equal(ch._w, M.W0) and not ch.about()["corrections"]     # no learned corrections: d = 0
    tracks = list(range(1, 30))
    X = np.random.default_rng(3).uniform(0, 1, (len(tracks), 6))
    mean, _ = ch.scores("vocals", tracks, X)
    t = np.array([ch.taste(tr, "vocals") for tr in tracks])
    si = M.STEMS.index("vocals")
    g = ch._g + ch._gs[si]
    base = ch.theta[si]
    assert np.allclose(mean, X @ M.W0 + base + g * t)                          # exactly W0 . x + a taste term
    assert g > 0.3                                                           # what you keep is what it likes
    assert g > ch._g + ch._gs[M.STEMS.index("drums")]                        # (drums were kept at random)
    # no Mashup events, or no taste model: plain W0
    empty = _ev_db(tmp_path / "b.sqlite", n=0)
    for c in (M.taste_only(empty, _T(), emb=_emb), M.taste_only(con, None, emb=_emb)):
        m0, _ = c.scores("bass", tracks, X)
        assert np.array_equal(np.argsort(-m0, kind="stable"), np.argsort(-(X @ M.W0), kind="stable"))
    nos = M.taste_only(con, _T(), emb=_emb, sound=False)
    assert nos._w[M.I_SOUND] == 0 and np.array_equal(np.delete(nos._w, M.I_SOUND), np.delete(M.W0, M.I_SOUND))


def test_sound_with_the_songs_own_events_left_out(tmp_path):
    con = _ev_db(tmp_path / "a.sqlite", n=0)
    con.executemany("INSERT INTO stem_events VALUES (?,?,?,?,?,?,?,?,?)",
                    [(1.0, "save", "bass", 1, 0, 4, "[]", 1, 1.0), (2.0, "reroll", "bass", 2, 0, 4, "[]", 0, 1.0)])
    f = M.loso_sound(con, _emb)
    # song 1's own save is left out of its centres: what is left is song 2's re-roll
    assert f(1, "bass") == pytest.approx(-float(_emb(1, "bass") @ _emb(2, "bass")), abs=1e-6)
    assert f(3, "bass") == pytest.approx(float(_emb(3, "bass") @ _emb(1, "bass")) - float(_emb(3, "bass") @ _emb(2, "bass")),
                                         abs=1e-6)


# ---------------------------------------------------------------- the switch, and what the page is served

def test_the_switch(tmp_path):
    assert live.settings() == dict(samples="new", mashup="new")             # the default
    assert live.set_setting("mashup", "w0")["mashup"] == "w0" and live.policy("mashup") == "w0"
    assert live.settings()["samples"] == "new"
    with pytest.raises(ValueError):
        live.set_setting("mashup", "sometimes")
    live.SETTINGS.write_text("not json")
    assert live.settings() == dict(samples="new", mashup="new")             # a broken file: the defaults


class _Fit:
    def __init__(self, paths):
        self.paths = paths
        self.mean = np.linspace(-3, 1, len(paths))
        self.sd = np.full(len(paths), 0.5)
        self.key, self.chooser, self.seconds = None, None, 1.0

        class t:
            n, n_pos = 40, 7
        self.t = t


def test_scores_come_from_the_shared_model_and_fall_back(monkeypatch, tmp_path):
    from digitalcrate import taste
    paths = [f"Vocals/s{i}.wav" for i in range(20)]
    con = sqlite3.connect(tmp_path / "t.sqlite")
    con.execute("CREATE TABLE events (ts REAL, path TEXT, sample_id TEXT, type TEXT, value REAL, context TEXT)")
    con.execute("INSERT INTO events VALUES (1, 'Vocals/s19.wav', NULL, 'dislike', 1, NULL)")
    con.commit()
    monkeypatch.setattr(taste, "_db", lambda: con)
    monkeypatch.setattr(taste, "_old_payload", lambda recent_hours=None: dict(
        n_labels=1, n_pos=1, score={p: 0.0 for p in paths}, discover={p: 0.0 for p in paths}, disliked=[]))
    p = taste.scores_payload(None)
    assert p["policy"] == taste.FALLBACK                                    # nothing fitted yet: the old scores
    f = _Fit(paths)
    live._S["fit"] = live.Fit(f.t, paths, f.mean, f.sd, None)
    p = taste.scores_payload(None)
    assert p["policy"] == "reco.taste" and p["n_labels"] == 40 and p["disliked"] == ["Vocals/s19.wav"]
    z = np.array([p["score"][q] for q in paths])
    assert abs(z.mean()) < 1e-3 and abs(z.std() - 1) < 1e-2 and np.all(np.diff(z) > 0)  # standardized, same order
    assert p["discover"] != taste.scores_payload(None)["discover"]          # discover: a fresh draw each time
    assert taste.cached_scores()[paths[-1]] == pytest.approx(z[-1], abs=1e-3)
    assert "policy" not in taste.scores_payload(3)                          # today's vibe: the earlier model
    live.set_setting("samples", "old")
    assert taste.scores_payload(None)["policy"] == taste.OLD


def test_one_impression_per_served_ranking(tmp_path):
    con = sqlite3.connect(tmp_path / "i.sqlite")
    con.row_factory = sqlite3.Row
    d = {f"s{i}.wav": float(i) for i in range(80)}
    payload = dict(score=d, discover={k: -v for k, v in d.items()}, disliked=["s79.wav"], policy="reco.taste")
    tok = live.served(payload, fav={"s78.wav"})
    assert not L.impressions(con)                                           # nothing written until the page has it
    assert live.record(tok, con) == 2
    got = {g["surface"]: g for g in L.impressions(con)}
    fy = got["samples.for_you"]
    assert [s["item"][1] for s in fy["shown"]][:3] == ["s77.wav", "s76.wav", "s75.wav"]   # starred, ✕'d: left out
    assert len(fy["shown"]) == live.SERVED_N and fy["policy"]["model"] == "reco.taste"
    assert got["samples.discover"]["context"]["draw"] == live.DISCOVER
    assert live.record(tok, con) == 0                                       # a token counts once
    assert live.record(live.served(payload, fav={"s78.wav"}), con) == 0     # the same rankings again: not logged
    assert live.record("last", con) == 0
    payload["discover"]["s60.wav"] = 999.0                                  # a new draw: a new discover impression
    live.served(payload, fav={"s78.wav"})
    assert live.record("last", con) == 1
    assert len(L.impressions(con, surface="samples.discover")) == 2


def test_the_taste_page_reads_the_harness(tmp_path, monkeypatch):
    from digitalcrate import taste_report as TR
    monkeypatch.setattr(E, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(TR, "FORWARD", tmp_path / "fwd.json")
    m = lambda v, d=None: dict(metrics=dict(auc=dict(mean=v, ci=[v - .05, v + .05], folds=[v - .01, v + .01])),
                               vs_ref=d and dict(auc=dict(diff=d, ci=[d - .02, d + .02], won=9, of=10)))
    res = dict(task="sample_taste", about="favorites", when=1.7e9, reference="taste", quick=False, splits=dict(
        sample=dict(counts=dict(n=100, pos=20, neg=80, groups=100, folds=10),
                    models={"taste": m(.80), "reco.taste": m(.81, .01), "quality": m(.55, -.25), "random": m(.5, -.3)}),
        forward=dict(counts=dict(n=50, pos=18, neg=32, groups=40, folds=2),
                     folds=[dict(name="t1", until=1.6e9, train=30, n=25, pos=9, neg=16),
                            dict(name="t2", until=1.65e9, train=60, n=25, pos=9, neg=16)],
                     models={"taste": dict(metrics=dict(auc=dict(mean=.7, folds=[.7, .7]))),
                             "reco.taste": dict(metrics=dict(auc=dict(mean=.75, folds=[.74, .76]))),
                             "quality": dict(metrics=dict(auc=dict(mean=.5, folds=[.5, .5])))})))
    E.write(res)
    E.write(dict(task="pair", about="pairs", when=1.7e9, reference="pair.clap", splits=dict(
        source=dict(counts=dict(n=8, pos=2, neg=6, groups=2, folds=0), insufficient="too little data to say anything"))))
    got = {t["task"]: t for t in TR.recommenders()}
    rows = got["sample_taste"]["splits"][0]["rows"]
    assert [r["role"] for r in rows] == ["in use", "replaced", "best other"]
    assert rows[0]["model"] == "reco.taste" and rows[0]["vs"]["diff"] == .01 and rows[2]["model"] == "quality"
    assert "insufficient" in got["pair"]["splits"][0]
    live.set_setting("samples", "old")
    assert TR.recommenders()[0]["splits"][0]["rows"][0]["model"] == "taste"
    # the history row of the model in use, from the harness run
    con = TR._history(sqlite3.connect(tmp_path / "h.sqlite"))
    con.row_factory = sqlite3.Row
    assert TR._new_history(con, (100, 20, 20, 3))
    assert not TR._new_history(con, (100, 20, 20, 3))                       # once
    r = con.execute("SELECT * FROM taste_history").fetchone()
    assert con.execute("SELECT model FROM taste_history_model WHERE ts=?", (r["ts"],)).fetchone()[0] == "reco.taste"
    assert "model" not in r.keys() and r["auc"] == .81 and r["quality_auc"] == .55 and r["n_fav"] == 20
    fw = json.loads(TR.FORWARD.read_text())
    assert fw["model"] == "reco.taste" and [x["auc"] for x in fw["results"]] == [.74, .76]
    assert fw["results"][0]["n_train"] == 30 and fw["results"][0]["quality_auc"] == .5


def test_audio_outside_the_library_is_scored_as_the_sample_it_came_from(tmp_path, monkeypatch):
    """The edit suggestions' critic: a render of a sample, scored with that sample's type, song and artist."""
    from test_reco_taste import _library
    from digitalcrate.reco.models import taste as T
    from digitalcrate import suggest, taste
    T._LIB.clear()
    monkeypatch.setattr(stems, "_emb", lambda track, stem: np.zeros(512, np.float32))
    con, heard, far = _library(tmp_path / "t.sqlite")
    t = T.fit(con)
    i = t.lib["pos"][heard[0]]
    m1, s1 = t.score([("sample", heard[0])])
    m2, s2 = t.score_like(t.lib["E"][i][None], heard[0])
    assert m2[0] == pytest.approx(m1[0], abs=1e-6) and s2[0] == pytest.approx(s1[0], abs=1e-6)
    assert np.isnan(t.score_like(t.lib["E"][i][None], "gone.wav")[0][0])
    mean, sd = t.score([("sample", p) for p in t.lib["paths"]])
    live._S["fit"] = live.Fit(t, list(t.lib["paths"]), mean, sd, None)
    c = suggest.Critic(heard[0])
    assert c.ok() and c.new is not None
    z = c.score(t.lib["E"][[i, t.lib["pos"][far[0]]]])
    assert z[0] == pytest.approx(live._S["fit"].z[i], abs=1e-6)                 # the scale "for you" is served on
    T._LIB.clear()
