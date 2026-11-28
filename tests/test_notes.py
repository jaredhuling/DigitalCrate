"""The notes and tuning of a sample (notes.py), and Mashup's harmony fit for one-shots and pads built on them."""
import numpy as np
import pytest

from test_reco import STATE, mashup  # noqa: F401  (the throwaway stem mixer)

SR = 22050


def _tone(hz, secs=1.5):
    t = np.arange(int(SR * secs)) / SR
    return (0.4 * np.sin(2 * np.pi * hz * t) + 0.2 * np.sin(2 * np.pi * 2 * hz * t)).astype(np.float32)


def test_tuning_and_notes_of_a_tone():
    """A tone on the grid reads as in tune; one a third of a semitone sharp or flat reads as that, and its note is
    still named right (the 12-note chroma would smear it over two)."""
    from digitalcrate import notes as N
    for cents in (0, 33, -33):
        f = N.fine(_tone(440 * 2 ** (cents / 1200)))
        got, clarity = N.tuning(f)
        assert abs(N.apart(got, cents)) < 10 and clarity > N.STEADY, (cents, got, clarity)
        p = N.profile(f)
        assert int(np.argmax(p)) == 9 and p[9] > 0.6 and abs(p.sum() - 1) < 1e-6      # A, whatever the tuning
    assert N.tuning(np.zeros(36)) == (0.0, 0.0) and not N.profile(np.zeros(36)).any()     # silence: no opinion
    assert N.apart(45, -45) == -10 and N.apart(-45, 45) == 10 and N.apart(10, 0) == 10    # the short way round


def test_what_a_note_is_worth_against_a_bar(mashup, monkeypatch):
    """Chord tones of the other tracks' bars count for a sample, notes outside the key against it; a one-shot track's
    own notes join the harmony for the others, but not for itself."""
    stems, con = mashup
    from digitalcrate import notes as N
    lib = stems.library()
    m = lib[1]
    monkeypatch.setitem(m, "chords", ["C"] * (len(m["bars"]) - 1))
    state = dict(STATE, key="C")
    W, cents = stems.cycle_target(state, 2, con=con)
    assert W.shape == (2, 12) and cents is None                       # (no song tuning measured here)
    assert all(W[0, i] == stems.CHORD for i in (0, 4, 7))             # C E G
    assert W[0, 2] == stems.SCALE and W[0, 5] == stems.AVOID          # D is in the key; F rubs against E
    assert W[0, 1] == stems.OUT and W[0, 6] == stems.OUT              # C#, F#: outside C major
    assert stems.cycle_target(dict(bpm=100, slots={}), 2, con=con) == (None, None)   # nothing pitched: no target
    # a one-shot on D# in another track makes D# a tone of the bar it hits, for the others only
    path = con.execute("SELECT path FROM samples WHERE chroma IS NOT NULL AND parent_id IS NULL LIMIT 1").fetchone()[0]
    f = np.zeros(36, np.float32)
    f[9] = 1.0                                                         # D#, in tune
    N._tables(con)
    con.execute("INSERT INTO sample_notes VALUES (?, ?, 0, 0.3)", (path, f.tobytes()))
    con.commit()
    state["slots"] = dict(state["slots"], os1=dict(stem="oneshot", sample=path, semis=0, steps=[16], n=2))
    W2, _ = stems.cycle_target(state, 2, con=con)
    assert W2[1, 3] == stems.CHORD and W2[0, 3] == stems.OUT           # the bar it hits (step 16 = bar 2)
    assert stems.cycle_target(state, 2, skip="os1", con=con)[0][1, 3] == stems.OUT


def test_the_fit_prefers_chord_tones_and_tunes_the_sample(mashup, monkeypatch):
    """Of three measured one-shots (on a chord tone, outside the key, a chord tone but 30 cents sharp), the fit ranks
    the chord tones first, the out-of-key one last, and the sharp one comes with -30 cents. The old fit is still there."""
    stems, con = mashup
    from digitalcrate import notes as N
    from digitalcrate.reco import live
    lib = stems.library()
    monkeypatch.setitem(lib[1], "chords", ["C"] * (len(lib[1]["bars"]) - 1))
    monkeypatch.setattr(live, "policy", lambda s: "new")
    state = dict(STATE, key="C")
    rows = stems._oneshots(con)["rows"]
    N._tables(con)

    def put(i, pos, cents):
        f = np.full(36, 0.01, np.float32)
        f[pos] = 1.0
        con.execute("UPDATE samples SET key_from='none' WHERE path=?", (rows[i]["path"],))   # played as it is
        con.execute("INSERT OR REPLACE INTO sample_notes VALUES (?, ?, ?, 0.3)", (rows[i]["path"], f.tobytes(), cents))
    put(0, 3 * 7, 0.0)        # G
    put(1, 3 * 6, 0.0)        # F#
    put(2, 3 * 4 + 1, 30.0)   # E, a third of a semitone sharp
    con.commit()
    stems._OS["n"] = -1
    N._N["n"] = -1
    got = {name: stems.oneshot(state, 1, path=rows[i]["path"]) for name, i in (("g", 0), ("fs", 1), ("e", 2))}
    assert got["g"]["why"]["fit"] > 0.9 and got["e"]["why"]["fit"] > 0.9 and got["fs"]["why"]["fit"] == 0
    assert got["g"]["ct"] == 0 and got["e"]["ct"] == -30
    assert all(0 <= v <= 1 for p in got.values() for v in p["fit"])
    monkeypatch.setattr(live, "policy", lambda s: "old")
    old = stems.oneshot(state, 1, path=rows[2]["path"])
    assert old["ct"] == 0 and 0 <= old["why"]["fit"] <= 1
