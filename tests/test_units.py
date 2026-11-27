"""Fast checks of the pure parts: genre mapping, key parsing, the stretch and tuning engines."""
import numpy as np
import pytest

from conftest import SR, tone
from digitalcrate import genre
from digitalcrate.conform import parse_key
from digitalcrate.stretch import repitch, shift


@pytest.mark.parametrize("tag, fam", [
    ("Techno", "Electronic"),
    ("Disco/Deep House/Funk", "Electronic"),      # compound tag: Electronic beats Soul
    ("Ambient/Dark Ambient/Drone", "Ambient"),
    ("Broken Beat / Nu-Jazz, Classic House", "Electronic"),
    ("R&B", "Soul & R&B"),
    ("Folk Rock", "Folk"),
    ("Classical", "Classical"),
    ("Lo-Fi", "Other"),
    ("", None),
    (None, None),
])
def test_from_tag(tag, fam):
    assert genre.from_tag(tag) == fam


def test_family_order_of_evidence():
    ov = {"vladislav delay": "Electronic"}
    cons = {"gas": "Ambient"}
    assert genre.family("Vladislav  Delay", "Blues", ov, cons) == "Electronic"   # override beats a wrong tag
    assert genre.family("Gas", None, ov, cons) == "Ambient"                      # untagged: artist consensus
    assert genre.family("Gas", "Minimal", ov, cons) == "Electronic"              # a real tag beats consensus
    assert genre.family("Nobody", None, ov, cons) is None                        # left to the audio


@pytest.mark.parametrize("k, out", [("Fm", (5, "minor")), ("Ab", (8, "major")), ("C#m", (1, "minor"))])
def test_parse_key(k, out):
    assert parse_key(k) == out


def test_repitch_changes_length_like_tape():
    y = tone(440, 2.0)
    up = repitch(y, 12)                                  # an octave up = half as long
    assert abs(up.shape[1] / y.shape[1] - 0.5) < 0.01


def test_signalsmith_keeps_length_on_pitch_and_stretches_on_time():
    y = tone(440, 2.0)
    z, eng = shift(y, 3, 1.0, engine="signalsmith")
    assert eng == "signalsmith" and abs(z.shape[1] - y.shape[1]) < SR * 0.05
    z, _ = shift(y, 0, 1.25, engine="signalsmith")
    assert abs(z.shape[1] / y.shape[1] - 1.25) < 0.02


def test_auto_engine():
    y = tone(440, 1.0)
    assert shift(y, 2, 1.0)[1] == "repitch"
    assert shift(y, 0, 1.1)[1] == "signalsmith"


def _f0(y):
    import librosa
    f, v, _ = librosa.pyin(y[0], fmin=150, fmax=1000, sr=SR)
    return np.nanmedian(f[v])


def test_tune_pulls_a_flat_note_into_key():
    from digitalcrate.retune import tune
    flat = 440 * 2 ** (-0.4 / 12)                         # A, 40 cents flat
    y = tone(flat, 2.0)
    z = tune(y, "A", strength=1.0, speed_ms=0)
    before, after = abs(1200 * np.log2(_f0(y) / 440)), abs(1200 * np.log2(_f0(z) / 440))
    assert after < before / 2


def test_stems_are_aligned(tmp_path, monkeypatch):
    """Stems of different lengths come out trimmed to one length, with one shared gain, plus a reference mix."""
    import base64, io
    import soundfile as sf
    from digitalcrate import combos
    monkeypatch.setattr(combos.C, "ABLETON_SAMPLES", tmp_path)

    def wav(n, amp):
        b = io.BytesIO()
        sf.write(b, np.full((n, 2), amp, np.float32), 44100, format="WAV", subtype="FLOAT")
        return base64.b64encode(b.getvalue()).decode()
    r = combos.write_stems("Test", [dict(label="MEL a", wav=wav(44100, .9)), dict(label="KEYS b", wav=wav(44000, .6))],
                           key="Fm", bpm=80, reveal=False)
    files = sorted((tmp_path / "Sketches" / "Test (Fm, 80 bpm)").glob("*.wav"))
    assert [f.name for f in files] == ["00 mix (reference).wav", "01 MEL a.wav", "02 KEYS b.wav"]
    a, b = (sf.read(str(f))[0] for f in files[1:])
    assert len(a) == len(b) == 44000
    assert abs(a.max() / b.max() - 1.5) < 1e-3  # balance kept
    assert sf.read(str(files[0]))[0].max() <= 0.891


def test_harmony_theory():
    """Chord names are spelled for the key, Roman numerals are right, and fit prefers chords whose tones sound."""
    from digitalcrate.harmony import _vocab, _fit
    v = _vocab(5, "minor", "soulful")  # F minor
    names = {c["name"]: c["roman"] for c in v}
    assert names.get("Dbmaj9") == "bVImaj9" and names.get("Fm9") == "i9" and "C#maj9" not in names
    w = np.zeros(12); w[[0, 4, 7]] = 1 / 3  # C E G sounding
    plain = _vocab(0, "major", "plain")
    best = max(plain, key=lambda c: _fit(c, w))
    assert best["root"] == 0 and best["q"] in ("", "add9")
    clash = next(c for c in plain if c["root"] == 4)  # E minor over C E G: C is a semitone above B -> penalised
    assert _fit(clash, w) < _fit(best, w)


def test_voicings_use_only_chord_tones():
    """Every voiced note belongs to its chord (a 5-note voicing once fell back to wrong notes), root in the bass."""
    from digitalcrate.harmony import _vocab, _voicing, QUAL
    for tonic, mode in ((5, "minor"), (8, "major"), (2, "minor")):
        for style in ("soulful", "dark", "ethereal", "plain"):
            prev = None
            for ch in _vocab(tonic, mode, style):
                v = _voicing(ch, prev, 57, 76)
                assert {n % 12 for n in v} <= {(ch["root"] + i) % 12 for i in QUAL[ch["q"]]}, ch["name"]
                assert v[0] % 12 == ch["root"] and v[0] < min(v[1:])
                prev = v[1:]


def test_whisper_hallucinations_are_dropped():
    from digitalcrate.lyrics import _clean
    seg = lambda t, **k: dict(dict(text=t, no_speech_prob=0.0, avg_logprob=-0.3, compression_ratio=1.2,
                                   words=[dict(word=w, start=i * 0.4, end=i * 0.4 + 0.3, probability=0.9)
                                          for i, w in enumerate(t.split())]), **k)
    assert _clean(dict(segments=[seg(" Thank you.")]))[0] == ""
    assert _clean(dict(segments=[seg(" Ba-a-a-a-a-a-a-a-a")]))[0] == ""
    assert _clean(dict(segments=[seg(" oh love", avg_logprob=-1.4)]))[0] == ""
    text, words, _ = _clean(dict(segments=[seg(" How can I even try")], language="en"))
    assert text == "How can I even try" and words[1][0] == "can"


def test_style_families_and_search_phrases():
    from digitalcrate.styles import family_of
    from digitalcrate.related import phrase, _style_ok
    assert family_of([["Jazz---Hard Bop", 0.4], ["Jazz---Post Bop", 0.3]]) == "Jazz"
    assert family_of([["Electronic---Ambient", 0.5], ["Electronic---Drone", 0.4]]) == "Ambient"
    assert family_of([["Funk / Soul---Neo Soul", 0.05]]) is None  # nothing confident
    assert phrase("Classical---Modern") == "modern classical" and phrase("Funk / Soul---Neo Soul") == "neo soul"
    assert not _style_ok("Hip Hop---Boom Bap") and _style_ok("Electronic---Ambient") and not _style_ok("Rock---Punk")


def test_beat_this_bars_fall_back_without_a_grid(monkeypatch):
    import numpy as np
    from digitalcrate import analyze
    beats = np.arange(0, 60, 0.5)  # a steady 120 bpm, downbeat every 4th beat
    monkeypatch.setattr(analyze, "beat_this", lambda y: (beats, beats[::4]))
    tk = dict(beats=np.array([]), tempo_ok=False, bpm=0)
    bars, how = analyze.bars(tk, None, None)
    assert how == "beat_this" and tk["tempo_ok"] and abs(tk["bpm"] - 120) < 0.01 and len(bars) == 30
    rng = np.random.default_rng(0)  # rubato: no grid, and Essentia didn't trust its tempo either
    loose = np.cumsum(rng.uniform(0.3, 0.9, 80))
    monkeypatch.setattr(analyze, "beat_this", lambda y: (loose, loose[::4]))
    tk = dict(beats=np.array([]), tempo_ok=False, bpm=0)
    assert analyze.bars(tk, None, None)[1] == "none"


def test_setup_saves_folders(tmp_path, monkeypatch):
    """The setup page writes the two folders into the config in use, keeps other settings, and refuses bad choices."""
    from digitalcrate import app, config as C
    cfg = tmp_path / "digitalcrate.toml"
    cfg.write_text('reference_artists = ["X"]\nmusic = "/old"\n')
    monkeypatch.setattr(C, "CONFIG_FILE", cfg)
    music = tmp_path / "Music"; music.mkdir()
    (music / "a.mp3").write_bytes(b""); (music / "._a.mp3").write_bytes(b"")
    assert app.count_audio(music) == {"n": 1, "more": False}
    app.save_config(music, tmp_path / "Lib")
    import tomllib
    d = tomllib.loads(cfg.read_text())
    assert d["music"] == str(music) and d["library"] == str(tmp_path / "Lib") and d["reference_artists"] == ["X"]
    import pytest
    with pytest.raises(ValueError):
        app.save_config(tmp_path / "nope", tmp_path / "Lib")
    with pytest.raises(ValueError):
        app.save_config(music, music / "Lib")


def test_drum_hits_are_trimmed_to_the_impact():
    """Exported drum one-shots start on the hit (most mined hits open with 20-40 ms before it)."""
    import numpy as np
    from digitalcrate.export import trim_to_hit
    sr = 44100
    t = np.arange(int(0.3 * sr)) / sr
    hit = np.sin(2 * np.pi * 80 * t) * np.exp(-t * 20)
    y = np.stack([np.r_[np.zeros(int(0.03 * sr)), hit]] * 2).astype(np.float32)  # 30 ms before the impact
    z = trim_to_hit(y, sr)
    first = int(np.argmax(np.abs(z[0]) >= 0.25 * np.abs(z[0]).max())) / sr
    assert first < 0.004 and z.shape[1] < y.shape[1]
    assert trim_to_hit(z, sr).shape == z.shape  # already on the hit: left alone


def test_suggestions_are_precomputed_and_go_stale_on_a_rating(monkeypatch):
    """The editor's background precompute is used by ✨ (shown only then), the next press is precomputed, and a
    rating makes a precomputed run stale."""
    import time
    from digitalcrate import suggest as sg
    calls = []

    def fake(rel, pk=None, start=None, end=None, n=3, seed=None, log=True, commit=True):
        calls.append(rel)
        time.sleep(0.2)
        return dict(suggestions=[], _shown=dict(ids={len(calls)}, types=set(), families=set()), _rel=rel, _sid="x")
    monkeypatch.setattr(sg, "suggest", fake)
    monkeypatch.setattr(sg, "_PRE", {})
    monkeypatch.setattr(sg, "_SHOWN", {})
    sg.prefetch("a.wav", None, 0, 2)
    assert "a.wav" not in sg._SHOWN  # not shown yet
    r = sg.suggest_now("a.wav", None, 0, 2, log=False)
    assert r["precomputed"] and len(calls) == 2 and sg._SHOWN["a.wav"][-1]["ids"] == {1}  # the next is on its way
    time.sleep(0.3)
    t = time.time()
    assert sg.suggest_now("a.wav", None, 0, 2, log=False)["precomputed"] and time.time() - t < 0.1
    time.sleep(0.3)
    sg.stale("a.wav")
    assert not sg.suggest_now("a.wav", None, 0, 2, log=False)["precomputed"]


def test_fits_my_track_key_and_tempo():
    import numpy as np
    from digitalcrate.mytrack import key_fit, tempo_fit
    # track in C major (pc 0). Samples: C major, A minor (relative), D major (+2 away), F# major, unkeyed
    fit, shift = key_fit(np.array([0, 9, 2, 6, 0]), np.array([False, True, False, False, False]),
                         np.array([True, True, True, True, False]), 0, False)
    assert shift[0] == 0 and shift[1] == 0 and shift[2] == -2 and abs(shift[3]) == 6
    assert fit[0] > fit[1] > fit[2] > fit[3] and fit[4] == 0.75
    tf, pct = tempo_fit(np.array([True, True, True, False]), np.array([90.0, 45.0, 100.0, 0.0]), 90.0)
    assert tf[0] == tf[1] == 1.0 and pct[2] > 10 and tf[2] < 0.2 and tf[3] == 1.0  # half time is on tempo


def _pad(sr=SR, secs=6.0, seed=1):
    """A synthetic pad: a soft attack, a steady chord with slow vibrato and some air, and a fade."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t + 0.3 * np.sin(2 * np.pi * 0.25 * t)) for f in (220.0, 277.18, 329.63)) / 3
    y = y + 0.02 * rng.standard_normal(len(t))
    env = np.minimum(1, t / 0.3) * np.minimum(1, (secs - t) / 0.8)
    return (0.5 * y * env).astype(np.float32)


def test_sustain_loop_is_seamless_and_survives_export(tmp_path):
    import soundfile as sf
    import struct
    from digitalcrate.loopfind import find_loop, seam, bake, write_smpl, MAX_SEAM
    y = _pad()
    lp = find_loop(y, SR)
    assert lp and 0.3 <= lp["start"] < lp["end"] <= 5.3 and lp["end"] - lp["start"] >= 0.5
    assert seam(y, SR, lp) <= MAX_SEAM
    assert find_loop(np.zeros(SR * 4, np.float32), SR) is None  # silence: nothing to loop
    b = bake(y, SR, dict(lp, xf=0.05))
    a, e, n = int(lp["start"] * SR), int(lp["end"] * SR), int(0.05 * SR)
    assert np.allclose(b[:e - n], y[:e - n]) and np.allclose(b[e:], y[e:])  # only the loop's last 50 ms change
    f = tmp_path / "pad.wav"
    sf.write(str(f), y, SR, subtype="PCM_24")
    write_smpl(f, a, e - 1)
    raw = f.read_bytes()
    assert struct.unpack("<I", raw[4:8])[0] == len(raw) - 8
    k = raw.index(b"smpl")
    assert struct.unpack("<6I", raw[k + 8 + 36:k + 8 + 60])[2:4] == (a, e - 1)
    assert sf.read(str(f))[0].shape[0] == len(y)  # still an ordinary WAV


def test_neighborhood_attention_matches_a_direct_reference():
    """The plain-PyTorch NATTEN functions (for All-In-One's song sections), against a slow obvious version."""
    import torch
    from digitalcrate import _natten as N

    def ref_1d(q, k, rpb, K, d):
        n = q.shape[2]
        out = torch.zeros(*q.shape[:3], K)
        for i in range(n):
            g, ig = i % d, i // d
            members = list(range(g, n, d))
            s = min(max(ig - K // 2, 0), len(members) - K)
            for j in range(K):
                nb = members[s + j]
                out[:, :, i, j] = (q[:, :, i] * k[:, :, nb]).sum(-1) + rpb[:, s + j - ig + K - 1]
        return out
    torch.manual_seed(0)
    for n, K, d in [(20, 5, 1), (23, 3, 4), (30, 7, 2)]:
        q, k, v = (torch.randn(1, 2, n, 4) for _ in range(3))
        rpb = torch.randn(2, 2 * K - 1)
        a = N.natten1dqkrpb(q, k, rpb, K, d)
        assert torch.allclose(a, ref_1d(q, k, rpb, K, d), atol=1e-5)
        p = a.softmax(-1)
        nb, _ = N._idx(n, K, d, "cpu")
        direct = torch.stack([(p[:, :, i, :, None] * v[:, :, nb[i]]).sum(2) for i in range(n)], 2)
        assert torch.allclose(N.natten1dav(p, v, K, d), direct, atol=1e-5)
    q, k = torch.randn(1, 2, 4, 9, 4), torch.randn(1, 2, 4, 9, 4)
    rpb = torch.zeros(2, 5, 5)
    a = N.natten2dqkrpb(q, k, rpb, 3, 1)
    assert a.shape == (1, 2, 4, 9, 9)
    # 2D with no bias is the product of the two 1D neighbourhoods: corner (0, 0) sees rows 0-2, columns 0-2
    assert torch.allclose(a[0, 0, 0, 0, 4], (q[0, 0, 0, 0] * k[0, 0, 1, 1]).sum(), atol=1e-5)


def test_song_sections_label_samples_and_steer_mining():
    from digitalcrate.sections import of_sample, adjust
    secs = [(0.0, 20.0, "intro"), (20.0, 50.0, "verse"), (50.0, 70.0, "chorus"), (70.0, 80.0, "outro")]
    assert of_sample(secs, 18.0, 30.0) == "verse" and of_sample(secs, 72.0, 75.0) == "outro"
    assert of_sample([], 1, 2) is None
    c = adjust([dict(start=2.0, end=6.0, quality=0.5, kind="free"),       # in the intro: a little bonus
                dict(start=30.0, end=34.0, quality=0.5, kind="free"),     # in a verse: unchanged
                dict(start=46.0, end=54.0, quality=0.5, kind="loop"),     # a loop across verse -> chorus
                dict(start=52.0, end=60.0, quality=0.5, kind="loop")], secs)
    assert c[0]["quality"] > 0.5 and c[1]["quality"] == 0.5 and c[2]["quality"] < 0.5 and c[3]["quality"] == 0.5
    assert [x["section"] for x in c] == ["intro", "verse", "verse", "chorus"]


def _chords(seq, secs_each, sr=SR):
    """Held triads with a little air, one after another: seq like [(57, 'm'), (53, '')] (root MIDI note, quality)."""
    out = []
    rng = np.random.default_rng(3)
    for root, q in seq:
        t = np.arange(int(secs_each * sr)) / sr
        notes = [root, root + (3 if q == "m" else 4), root + 7, root + 12]
        y = sum(np.sin(2 * np.pi * 440 * 2 ** ((n - 69) / 12) * t) for n in notes) / len(notes)
        out.append(y + 0.01 * rng.standard_normal(len(t)))
    y = np.concatenate(out)
    return (0.4 * y).astype(np.float32)


def test_pads_hold_their_chords_and_moving_passages_dont(tmp_path):
    pytest.importorskip("madmom")
    import pretty_midi
    from digitalcrate import pads
    a = pads.analyze(_chords([(57, "m")], 10.0))  # A minor, held
    assert a["names"] == ["Am"] and pads.is_pad(a)
    b = pads.analyze(_chords([(57, "m"), (53, ""), (48, ""), (55, "")], 3.0))  # Am F C G: a progression
    assert b["n"] >= 3 and not pads.is_pad(b)
    assert pads.where(dict(subtype="Free", instrument="strings"), b) == (pads.STRINGS, "Free")
    assert pads.where(dict(subtype="Free", instrument="pad"), a) == (pads.PADS, "Free")
    # two chords rocking back and forth is still a pad
    c = pads.analyze(_chords([(57, "m"), (53, ""), (57, "m"), (53, "")], 3.0))
    assert set(c["names"]) == {"Am", "F"} and c["n"] == 2
    # mining: a held stretch then a moving one; with bar lines the cut is whole bars from the chord change
    y = np.concatenate([_chords([(57, "m")], 8.0), _chords([(48, ""), (55, ""), (50, "m"), (52, "")], 1.0)])
    found = pads.find(y, SR, bar_times=np.arange(0, 12.1, 2.0))
    assert found and found[0][0] == 0.0 and found[0][2] in (2, 4) and found[0][1] <= 8.2
    assert pads.find(y, SR)[0][2] is None  # no tempo: a free cut along the hold
    # the chords as MIDI, and the note that plays the pad as recorded
    mid = pads.chord_midi([(0, 4, "Am"), (4, 8, "F")], tmp_path / "c.mid", bpm=90)
    pm = pretty_midi.PrettyMIDI(str(mid))
    first = sorted(n.pitch % 12 for n in pm.instruments[0].notes if n.start == 0)
    assert first == [0, 4, 9] and len(pm.instruments[0].notes) == 6
    assert pads.root_note([(0, 6, "Am"), (6, 8, "F")]) == 57 and pads.root_note([(0, 6, "D")]) == 62


MOVE_SCRIPT = r'''
import json, soundfile as sf, numpy as np
from digitalcrate import config as C
from digitalcrate.db import connect
from digitalcrate.recat import move_sample
con = connect()
old = "Pads & Atmospheres/Free/Pad_08A-Am_free_X-Y_0m10s_abc123.wav"
(C.LIB_ROOT / old).parent.mkdir(parents=True, exist_ok=True)
sf.write(str(C.LIB_ROOT / old), np.zeros((4410, 2), np.float32), 44100)
con.execute("INSERT INTO tracks (id, path, status) VALUES (1, 'x.wav', 'done')")
con.execute("INSERT INTO samples (id, track_id, category, subtype, kind, path) VALUES ('abc123', 1, 'Pads & Atmospheres', 'Free', 'free', ?)", (old,))
con.execute("CREATE TABLE IF NOT EXISTS sketches (name TEXT, state TEXT)")
con.execute("INSERT INTO sketches (name, state) VALUES ('s', ?)", (json.dumps({"lanes": [{"path": old}]}),))
con.execute("INSERT INTO events (ts, path, sample_id, type) VALUES (0, ?, 'abc123', 'play')", (old,))
new = move_sample(con, con.execute("SELECT * FROM samples WHERE id='abc123'").fetchone(), "Strings & Orchestral", "Free")
con.commit()
assert new.startswith("Strings & Orchestral/Free/Strings_"), new
assert (C.LIB_ROOT / new).exists() and not (C.LIB_ROOT / old).exists()
assert json.loads(con.execute("SELECT state FROM sketches").fetchone()[0])["lanes"][0]["path"] == new
assert con.execute("SELECT path FROM events").fetchone()[0] == new
assert con.execute("SELECT new FROM moved WHERE old=?", (old,)).fetchone()[0] == new
print("MOVED OK")
'''


def test_moving_a_sample_keeps_every_reference(tmp_path):
    import os, subprocess, sys
    env = dict(os.environ, DIGITALCRATE_LIBRARY=str(tmp_path / "lib"), DIGITALCRATE_MUSIC=str(tmp_path / "m"),
               DIGITALCRATE_CONFIG=str(tmp_path / "cfg.toml"))
    (tmp_path / "cfg.toml").write_text(f'library = "{tmp_path / "lib"}"\nmusic = "{tmp_path / "m"}"\n')
    r = subprocess.run([sys.executable, "-c", MOVE_SCRIPT], env=env, capture_output=True, text=True)
    assert "MOVED OK" in r.stdout, r.stderr[-2000:]


def test_a_struck_key_is_not_a_pad():
    pytest.importorskip("madmom")
    from digitalcrate import pads
    t = np.arange(int(2.5 * SR)) / SR
    notes = (57, 60, 64)
    key = sum(np.sin(2 * np.pi * 440 * 2 ** ((n - 69) / 12) * t) for n in notes) * np.exp(-t * 2.5) / 3  # struck, dies away
    pad = sum(np.sin(2 * np.pi * 440 * 2 ** ((n - 69) / 12) * t) for n in notes) * np.minimum(1, t / 0.2) / 3  # held
    a, b = pads.analyze(key.astype(np.float32)), pads.analyze(pad.astype(np.float32))
    assert pads.where(dict(kind="oneshot", subtype="One-Shots", instrument="strings"), a) == ("Chords & Keys", "One-Shots")
    assert pads.where(dict(kind="oneshot", subtype="One-Shots", instrument="pad"), b) == (pads.PADS, "One-Shots")


def test_heavy_jobs_take_turns(tmp_path):
    """Jobs that load the big models wait for a slot: one for jobs you start, one for library passes."""
    import os, subprocess, sys, time
    env = dict(os.environ, DIGITALCRATE_LIBRARY=str(tmp_path / "lib"), DIGITALCRATE_CONFIG=str(tmp_path / "c.toml"))
    env.pop("DIGITALCRATE_NO_SLOT", None)
    (tmp_path / "c.toml").write_text(f'library = "{tmp_path / "lib"}"\n')
    hold = "from digitalcrate.__main__ import _slot;import time,sys;_slot(sys.argv[1]);print('got',flush=True);time.sleep(float(sys.argv[2]))"
    a = subprocess.Popen([sys.executable, "-c", hold, "ytscout", "3"], env=env, stdout=subprocess.PIPE, text=True)
    assert a.stdout.readline().strip() == "got"
    t = time.time()
    b = subprocess.run([sys.executable, "-c", hold, "ingest", "0"], env=env, capture_output=True, text=True)
    assert "waiting for ytscout" in b.stdout and time.time() - t > 1.5  # another job you started: waits its turn
    a.wait()
    t = time.time()
    a = subprocess.Popen([sys.executable, "-c", hold, "ytscout", "3"], env=env, stdout=subprocess.PIPE, text=True)
    a.stdout.readline()
    c = subprocess.run([sys.executable, "-c", hold, "pads", "0"], env=env, capture_output=True, text=True)
    assert "waiting" not in c.stdout  # a library pass has its own slot
    a.wait()


def test_separation_grain_is_measured():
    """A stem that is the mix has no grain; one whose mask flickers frame to frame (musical noise) does."""
    from digitalcrate import grain
    rng = np.random.default_rng(0)
    t = np.arange(3 * SR) / SR
    music = (np.sin(2 * np.pi * 1500 * t) + 0.5 * np.sin(2 * np.pi * 3000 * t) + 0.1 * rng.standard_normal(len(t))).astype(np.float32)
    assert grain.score(music, music) < 0.02
    # musical noise: a separator's mask flickering per frequency, frame to frame
    import librosa
    X = librosa.stft(music, n_fft=2048, hop_length=512)
    noisy = librosa.istft(X * (rng.random(X.shape) > 0.5), hop_length=512, length=len(music))
    assert grain.score(noisy, music) > 0.1  # (the 0.28 line for "grainy" was set by ear on real music)
    assert grain.penalty(0.03) == 1.0 and abs(grain.penalty(0.1) - 0.8) < 1e-6 and abs(grain.penalty(0.5) - 0.6) < 1e-6


def test_alternate_takes_grouping_rules():
    from digitalcrate.takes import same_take, _toks
    s = lambda cat, sub, start, dur: dict(category=cat, subtype=sub, start=start, dur=dur)
    kick1, kick2, snare = s("Percussion", "Kick", 1.0, 0.3), s("Percussion", "Kick", 9.0, 0.3), s("Percussion", "Snare", 5.0, 0.3)
    assert same_take(kick1, kick2, 0.9, 0, set(), set())            # the same drum again
    assert not same_take(kick1, snare, 0.95, 0, set(), set())       # another drum
    assert not same_take(kick1, kick2, 0.99999, 0, set(), set())    # the very same audio
    v1, v2 = s("Vocals", "Phrases", 10, 2.0), s("Vocals", "Phrases", 60, 2.2)
    assert same_take(v1, v2, 0.8, 0.3, _toks("my love"), _toks("oh my love"))        # the same words, pitch differs
    assert not same_take(v1, v2, 0.8, 0.9, _toks("my love"), _toks("don't go now"))  # other words
    p1, p2 = s("Chords & Keys", "Free", 10, 8.0), s("Chords & Keys", "Free", 40, 8.5)
    assert same_take(p1, p2, 0.95, 0.95, set(), set()) and not same_take(p1, p2, 0.95, 0.6, set(), set())  # same notes
    # the same figure again in a changed arrangement: same notes, similar sound, the same shape over time
    assert same_take(p1, p2, 0.85, 0.98, set(), set(), env_sim=0.7)
    assert not same_take(p1, p2, 0.85, 0.98, set(), set(), env_sim=-0.2)   # same key and instruments, another passage
    assert not same_take(p1, s("Chords & Keys", "Free", 12, 8.0), 0.95, 0.95, set(), set())  # overlapping cuts
    assert not same_take(p1, s("Chords & Keys", "Free", 40, 2.0), 0.95, 0.95, set(), set())  # very different lengths


def _fake_stem_song(tmp, tid, bpm, pc, scale, chroma_pc, monkeypatch=None):
    """A prepared song for the stem mixer without a separator: 24 bars of a held triad on each stem."""
    import json, soundfile as sf
    from digitalcrate import stems
    d = stems.DIR / f"t{tid}"
    d.mkdir(parents=True, exist_ok=True)
    bar = 240.0 / bpm
    nb = 24
    t = np.arange(int(nb * bar * SR)) / SR
    y = (0.3 * sum(np.sin(2 * np.pi * 220 * 2 ** ((chroma_pc + k - 9) / 12) * t) for k in (0, 4, 7))).astype(np.float32)
    for k in stems.STEMS:
        sf.write(str(d / f"{k}.flac"), np.stack([y, y]).T, SR, format="FLAC", subtype="PCM_16")
    ch = np.zeros(12); ch[[chroma_pc, (chroma_pc + 4) % 12, (chroma_pc + 7) % 12]] = 1; ch /= np.linalg.norm(ch)
    e = np.zeros((4, 512), np.float16); e[:, tid % 512] = 1
    np.save(d / "emb.npy", e)
    meta = dict(track=tid, artist=f"A{tid}", title=f"T{tid}", bpm=bpm, pc=pc, scale=scale, camelot="8B",
                bars=[round(b * bar, 4) for b in range(nb + 1)], act={k: [1.0] * nb for k in stems.STEMS},
                chroma=[ch.round(3).tolist()] * nb, stems=list(stems.STEMS), separated=False)
    (d / "meta.json").write_text(json.dumps(meta))


def test_stem_mixer_renders_fits_and_learns(tmp_path, monkeypatch):
    import soundfile as sf
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    import sqlite3
    def _con():  # its own database: never the library's
        c = sqlite3.connect(tmp_path / "t.sqlite"); c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={})
    stems._EMB.clear()
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)    # C major, playing C
    _fake_stem_song(tmp_path, 2, 110, 2, "major", 2)    # D major, playing D
    _fake_stem_song(tmp_path, 3, 100, 0, "major", 6)    # says C major but plays F#: a wrong key on file
    _fake_stem_song(tmp_path, 4, 140, 0, "major", 0)    # too fast for drums at 100, and too slow for half-time
    _fake_stem_song(tmp_path, 5, 200, 0, "major", 0)    # twice the tempo: fits half-time (two of its bars per bar)
    lib = stems.library()
    assert set(lib) == {1, 2, 3, 4, 5}
    # a part is exactly n bars at the mixer's tempo, whatever the song's own tempo
    f = stems.render(2, "other", 4, 2, 100, semis=-2)
    info = sf.info(str(f))
    assert info.frames == round(2 * 240 / 100 * SR)
    # keys: D major comes down two semitones to C; relative minor counts as the same key
    assert stems.key_semis(lib[2], (0, "major")) == -2 and stems.key_semis(lib[1], (9, "minor")) == 0
    assert stems.parse_key("F#m") == (6, "minor") and stems.parse_key("Bb") == (10, "major")
    # harmony fit: the same notes after shifting = 1; a song that plays something else than its key says, low
    a, b, c = (lib[1], 0, 4, 0), (lib[2], 0, 4, -2), (lib[3], 0, 4, 0)
    assert stems.fit(a, b) > 0.98 and stems.fit(a, c) < 0.4
    # picking a bass part under song 1's "other": never the too-fast song, and the one that fits wins
    con = stems._db()
    state = dict(bpm=100, key=None, slots=dict(other=dict(track=1, bar0=0, n=4, off=0)))
    picks = [stems.pick("bass", state, rng=np.random.default_rng(k)) for k in range(12)]
    assert all(p["track"] != 1 for p in picks)             # not the song already playing
    assert sum(p["track"] == 3 for p in picks) <= 1        # the one that clashes loses
    # a slot's own semitones move that slot against the key; they don't move the key (and so every other slot)
    st2 = dict(bpm=100, key=None, slots=dict(other=dict(track=1, bar0=0, n=4, off=0), bass=dict(track=2, bar0=0, n=4, off=0)))
    i0 = stems.info(st2)
    st2["slots"]["other"]["off"] = 3
    i1 = stems.info(st2)
    assert i1["key"] == i0["key"] and i1["slots"]["bass"]["semis"] == i0["slots"]["bass"]["semis"]
    assert i1["slots"]["other"]["semis"] == i0["slots"]["other"]["semis"] + 3
    # the dice moves through the library: songs a slot dealt lately sit out (up to a quarter of what's on offer)
    assert 5 in {stems.pick("bass", state, rng=np.random.default_rng(k))["track"] for k in range(6)}
    assert 5 not in {stems.pick("bass", state, rng=np.random.default_rng(k), avoid=[5])["track"] for k in range(6)}
    # tempo: drums stretch well only within about -20% / +25%, at the song's tempo, half or double
    assert stems.best_k(lib[4], 100, "drums") is None and stems.best_k(lib[5], 100, "drums")[0] == 2
    drums = [stems.pick("drums", state, rng=np.random.default_rng(k)) for k in range(12)]
    assert all(p["track"] != 4 for p in drums) and any(p["track"] == 5 and p["k"] == 2 for p in drums)
    f2 = stems.render(5, "drums", 0, 2, 100, k=2)          # 2 mixer bars = 4 of its bars, still exactly 2 bars long
    assert sf.info(str(f2)).frames == round(2 * 240 / 100 * SR)
    # you chose the song: its best bars, even at a tempo the dice would skip
    assert stems.pick("drums", state, track=4)["track"] == 4
    # one chord throughout is as still as it gets
    assert stems.still(lib[1], 0, 4) > 0.99
    assert stems.info(dict(state, slots=dict(state["slots"], bass=dict(track=2, bar0=0, n=4, off=0))))["fit"] > 0.98
    # any number of slots, several of one stem: slots have ids and carry their stem
    two = dict(bpm=100, key=None, slots=dict(a=dict(stem="other", track=1, bar0=0, n=4, off=0),
                                             b=dict(stem="other", track=2, bar0=0, n=4, off=0)))
    assert set(stems.info(two)["slots"]) == {"a", "b"} and stems.info(two)["fit"] > 0.98
    p = stems.pick("other", two, slot="b", rng=np.random.default_rng(0))
    assert p["stem"] == "other" and p["track"] not in (1, 2)   # not what a plays, not what b had
    assert stems.log("like", two) == 2 and stems.log("kept", two, "b") == 1
    stems._db().execute("DELETE FROM stem_events").connection.commit()
    # other stretches of the same stem in the same song, for stepping through its takes
    al = stems.alts(two, "b")
    assert len(al) >= 2 and all(a["track"] == 2 for a in al) and len({a["bar0"] for a in al}) == len(al)
    # every part comes out equally loud, and a stem that is all but silent in its song isn't offered
    import json as _json
    y, _ = sf.read(str(stems.render(1, "other", 0, 2, 100)))
    assert abs(float(np.sqrt(np.mean(y ** 2))) - stems.TARGET_RMS) < 0.01
    sf.write(str(stems.DIR / "t3" / "drums.flac"), np.zeros((24 * int(2.4 * SR), 2), np.float32), SR, format="FLAC", subtype="PCM_16")
    m3 = _json.loads((stems.DIR / "t3" / "meta.json").read_text()); m3.pop("level", None); m3["stems"] = list(stems.STEMS)
    assert "drums" not in stems._levels(3, m3)["stems"] and "other" in m3["stems"]
    # learning: the guesses until a dozen ratings; then the weights move toward what you rated
    w0, n0 = stems.weights(con)
    assert n0 == 0 and np.allclose(w0, stems.W0)
    good = dict(state, slots=dict(state["slots"], bass=dict(track=2, bar0=0, n=4, off=0)))
    bad = dict(state, slots=dict(state["slots"], bass=dict(track=3, bar0=0, n=4, off=0)))
    for _ in range(8):
        stems.log("like", good, "bass"); stems.log("dislike", bad, "bass")
    w1, n1 = stems.weights(con)
    assert n1 == 16 and w1[stems.FEATURES.index("fit")] > stems.W0[stems.FEATURES.index("fit")]


def test_a_saved_loop_keeps_its_length_and_its_start(monkeypatch):
    """Loop crossfade: the file is exactly the selection, its start untouched, and its end leads back into its start
    (it used to blend the tail into the head: a ghost of the ending at the start, and a file shorter than selected)."""
    from digitalcrate import edit
    t = np.arange(3 * SR) / SR
    src = np.stack([np.sin(2 * np.pi * 220 * t) * (0.4 + 0.3 * t / 3)] * 2).astype(np.float32)  # rising, so head != tail
    monkeypatch.setattr(edit, "_load", lambda rel: src.copy())
    y, _ = edit.render("x.wav", dict(start=1.0, end=2.0, loop_xfade=50, normalize=False))
    a, n = SR, SR
    assert y.shape[1] == n                                              # exactly the selection: one second, not less
    assert np.allclose(y[:, :2000], src[:, a:a + 2000], atol=1e-4)      # the start is the source's, nothing blended in
    assert abs(float(y[0, -1]) - float(src[0, a - 1])) < 0.02           # the end arrives where the start picks up
    jump = abs(float(y[0, 0]) - float(y[0, -1]))
    raw = abs(float(src[0, a]) - float(src[0, a + n - 1]))
    assert jump < 0.03 and jump < raw                                    # seamless at the loop point
    # nothing before the selection to blend from: still the exact length, with a 3 ms fade either side
    z, _ = edit.render("x.wav", dict(start=0.0, end=1.0, loop_xfade=50, normalize=False))
    assert z.shape[1] == SR and abs(float(z[0, 0])) < 1e-3 and abs(float(z[0, -1])) < 1e-3
    # stretched: the length is the stretched selection's, and the start is still clean
    w, _ = edit.render("x.wav", dict(start=1.0, end=2.0, stretch=1.5, loop_xfade=50, normalize=False))
    assert abs(w.shape[1] - 1.5 * SR) < 0.02 * SR


def test_pause_stops_jobs_and_resume_lists_them(tmp_path):
    """⏸ pause: a job stops at its next checkpoint and notes itself; resume gives the list back and clears the pause."""
    import os, subprocess, sys
    env = dict(os.environ, DIGITALCRATE_LIBRARY=str(tmp_path / "lib"), DIGITALCRATE_CONFIG=str(tmp_path / "c.toml"))
    env.pop("DIGITALCRATE_NO_SLOT", None)
    (tmp_path / "c.toml").write_text(f'library = "{tmp_path / "lib"}"\n')
    job = "import sys;sys.argv=['x','pads','--mine'];from digitalcrate.memguard import breathe;breathe();print('RAN')"
    run = lambda code: subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert "RAN" in run(job).stdout                                       # not paused: carries on
    run("from digitalcrate.memguard import pause;pause()")
    r = run(job)
    assert "RAN" not in r.stdout and "PAUSED" in r.stdout and r.returncode == 0   # paused: stops cleanly
    run(job)                                                              # noted once, not twice
    out = run("from digitalcrate.memguard import paused_jobs,resume,paused;print(paused_jobs()['jobs']);print(resume());print(paused())").stdout
    assert out.count("{'kind': 'pads', 'args': ['--mine']}") == 2 and out.strip().endswith("False")
    assert "RAN" in run(job).stdout                                       # resumed: runs again


def test_stem_snapshot_counts_as_a_weak_yes(tmp_path, monkeypatch):
    """📸 a snapshot teaches the stem mixer like locking a part does: a yes of weight 0.6, for the slots it names."""
    import sqlite3
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    def _con():  # its own database: never the library's
        c = sqlite3.connect(tmp_path / "t.sqlite"); c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={})
    stems._EMB.clear()
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)
    _fake_stem_song(tmp_path, 2, 110, 2, "major", 2)
    state = dict(bpm=100, key="C", slots=dict(other=dict(stem="other", track=1, bar0=0, n=4, off=0),
                                              bass=dict(stem="bass", track=2, bar0=0, n=4, off=0)))
    assert stems.log("snap", state, "bass") == 1      # one slot
    assert stems.log("snap", state) == 2              # every slot
    rows = stems._db().execute("SELECT kind, stem, y, w FROM stem_events ORDER BY rowid").fetchall()
    assert [(r["kind"], r["y"], r["w"]) for r in rows] == [("snap", 1, 0.6)] * 3
    assert rows[0]["stem"] == "bass"


def test_stem_picture_is_the_whole_stem(tmp_path, monkeypatch):
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    stems._LIB.update(n=-1, lib={})
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)
    m = stems.library()[1]
    r = stems.peaks(1, "other")
    pk = np.fromfile(r["path"], dtype=np.uint8)
    assert r["rate"] == 400 and r["n"] == len(pk) and abs(len(pk) - r["dur"] * 400) <= 1
    assert abs(r["dur"] - m["bars"][-1]) < 0.5 and r["bars"] == m["bars"] and pk.max() == 255
    made = r["path"].stat().st_mtime_ns
    assert stems.peaks(1, "other")["path"].stat().st_mtime_ns == made          # made once, then kept
    with pytest.raises(KeyError):
        stems.peaks(999, "other")


def test_parts_take_fractions_of_a_semitone_and_drums_take_your_offset(tmp_path, monkeypatch):
    import soundfile as sf
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    stems._LIB.update(n=-1, lib={})
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)    # C major
    _fake_stem_song(tmp_path, 2, 110, 2, "major", 2)    # D major
    a, b, c = (stems.render(1, "other", 0, 2, 100, semis=s) for s in (0, 0.5, 1))
    assert len({a, b, c}) == 3 and sf.info(str(b)).frames == round(2 * 240 / 100 * SR)
    assert stems.render(1, "other", 0, 2, 100, semis=0.5) == b
    d0, d2 = stems.render(1, "drums", 0, 2, 100, semis=0), stems.render(1, "drums", 0, 2, 100, semis=2)
    assert d0 != d2 and not np.allclose(sf.read(str(d0))[0], sf.read(str(d2))[0])
    st = dict(bpm=100, key="C", slots=dict(drums=dict(stem="drums", track=1, bar0=0, n=2, off=2),
                                           bass=dict(stem="bass", track=2, bar0=0, n=2, off=1)))
    i = stems.info(st)["slots"]
    assert i["drums"]["semis"] == 2 and i["bass"]["semis"] == -1


def test_a_cached_legacy_loop_survives_a_missing_stem(tmp_path, monkeypatch):
    import hashlib

    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", stems.DIR / "cache")
    stems._LIB.update(n=-1, lib={})
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)
    made = stems.render(1, "other", 1, 4, 100, semis=-1)
    legacy_key = hashlib.sha1(b"1|other|1|4|1.0|100.00|-1|v3").hexdigest()[:16]
    old = made.rename(stems.CACHE / f"{legacy_key}.wav")
    (stems.DIR / "t1" / "other.flac").unlink()
    with pytest.raises(FileNotFoundError):
        stems.peaks(1, "other")
    assert stems.render(1, "other", 1, 4, 100, semis=-1) == old
    with pytest.raises(RuntimeError):
        stems.render(1, "other", 1, 4, 100, semis=-1.5)


def test_legacy_whole_song_loops_keep_their_original_source_span(tmp_path, monkeypatch):
    import soundfile as sf

    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", stems.DIR / "cache")
    stems._LIB.update(n=-1, lib={})
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)
    bars = len(stems.library()[1]["bars"]) - 1
    source = np.zeros(bars * round(2.4 * SR), dtype=np.float32)
    source[-round(2.4 * SR):] = tone(220, 2.4)[0]
    sf.write(stems.DIR / "t1" / "other.flac", source, SR)
    kept = stems.render(1, "other", 0, bars, 100, legacy=True)
    full = stems.render(1, "other", 0, bars, 100)
    assert kept != full and sf.info(kept).frames == sf.info(full).frames
    assert np.max(np.abs(sf.read(kept)[0])) == 0
    assert np.max(np.abs(sf.read(full)[0])) > 0.1


def test_mashup_exports_a_live_set(tmp_path, monkeypatch):
    """The mashup as a Live set, dry: a track per slot, the sections end to end with a locator each, every part a
    looping clip of exactly its bars; a snapshot's own level is the clip's gain, and a muted slot has no clip."""
    import gzip, sqlite3, xml.etree.ElementTree as ET
    import soundfile as sf
    from digitalcrate import als, stems
    try:
        als.template()
    except FileNotFoundError:
        pytest.skip("needs Ableton Live installed (its empty set is the starting point)")
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    monkeypatch.setattr(stems.C, "ABLETON_SAMPLES", tmp_path / "ableton")
    def _con():
        c = sqlite3.connect(tmp_path / "t.sqlite"); c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={}); stems._EMB.clear()
    split = _fake_kit_song(tmp_path, 1, 100)
    stems.make_tops(1, split=split, embed=lambda _: np.ones(512, np.float32))
    _fake_stem_song(tmp_path, 2, 110, 2, "major", 2)
    part = lambda stem, track, **kw: dict(dict(stem=stem, track=track, bar0=4, n=4, k=1, off=0, db=-2), **kw)
    A = dict(label="A", order=["drums", "other", "tops", "bass"], roles={},
             slots=dict(drums=part("drums", 1), other=part("other", 2, ct=25), tops=part("tops", 1), bass=part("bass", 1, cond=1)))
    B = dict(label="B", order=["drums", "other", "bass"], roles={},
             slots=dict(drums=part("drums", 1, db=-8), other=part("other", 2, mute=True), bass=part("bass", 1)))
    C = dict(label="C", order=["bass"], roles={}, slots=dict(bass=part("bass", 1, n=2, k=2, cond=1)))
    r = stems.export("Unit mash", 100, "C", [A, B, C], bars=8, reveal=False)
    assert (r["tracks"], r["clips"], r["sections"]) == (4, 7, 3)
    dest = tmp_path / "ableton" / "Mashups" / "Unit mash"
    ls = ET.parse(gzip.open(dest / r["als"])).getroot().find("LiveSet")
    assert [(l.find("Time").get("Value"), l.find("Name").get("Value")) for l in ls.iter("Locator")] == [("0", "A"), ("32", "B"), ("64", "C")]
    tr = [t for t in ls.find("Tracks") if t.tag == "AudioTrack"]
    clips = [list(t.iter("AudioClip")) for t in tr]
    assert [len(c) for c in clips] == [2, 1, 1, 3]                              # the muted "other" has no clip in B
    d0, d1 = clips[0]
    assert (d0.get("Time"), d0.find("CurrentEnd").get("Value"), d0.find("Loop/LoopEnd").get("Value"), d0.find("Loop/LoopOn").get("Value")) == ("0", "32", "16", "true")
    assert abs(float(d1.find("SampleVolume").get("Value")) - 10 ** (-6 / 20)) < 1e-3   # 6 dB lower in B: the clip's gain
    assert abs(float(tr[0].find("DeviceChain/Mixer/Volume/Manual").get("Value")) - 10 ** (-2 / 20)) < 1e-3
    for f in (dest / "Parts").glob("*.wav"):                                    # every part is exactly its bars at the tempo
        i = sf.info(str(f))
        assert i.frames == round(4 * 240 / 100 * SR) or (f.name.startswith("Bass") and i.frames == round(2 * 240 / 100 * SR))
    assert "-1.75st" in next(f.name for f in (dest / "Parts").glob("Other*"))  # D major to C plus 25 cents
    assert tr[2].find("Name/EffectiveName").get("Value").startswith("Tops")
    assert next((dest / "Parts").glob("Tops*")).read_bytes() == stems.render(1, "tops", 4, 4, 100).read_bytes()
    bass_files = {f.read_bytes() for f in (dest / "Parts").glob("Bass*")}
    assert bass_files == {stems.render(1, "bass", 4, n, 100, k=k, cond=cond).read_bytes()
                          for n, k, cond in [(4, 1, 0), (4, 1, 1), (2, 2, 1)]}
    assert len(bass_files) == 3


def test_one_shot_export_uses_warp_length_and_fractional_pitch(tmp_path, monkeypatch):
    import soundfile as sf

    from digitalcrate import conform, stems
    sample = tmp_path / "sample.wav"
    sf.write(sample, tone(220, 0.6).T, SR)
    monkeypatch.setattr(conform, "render", lambda path, key=None: (sample, None))
    warped = []

    def warp(path, key, trim, beats, bpm, semis):
        warped.append((beats, semis))
        return sample

    monkeypatch.setattr(stems, "oneshot_warp", warp)
    part = dict(sample=sample.name, fit=[0.9], steps=[0], n=1, off=2, ct=25)
    assert stems.oneshot_loop(part, 100, None, tmp_path / "unwarped.wav") == 4
    assert warped == []
    assert stems.oneshot_loop(dict(part, warp=1), 100, None, tmp_path / "warped.wav") == 4
    assert warped == [(1, 2.25)]


def _fake_kit_song(tmp, tid, bpm, hats=True, kick=True, *, kick_len=0.25, kick_hz=60, kick_amp=0.5):
    """_fake_stem_song, with drums that are a 60 Hz kick on every beat and an 8 kHz hat on every off-beat."""
    import soundfile as sf
    from digitalcrate import stems
    _fake_stem_song(tmp, tid, bpm, 0, "major", 0)
    n = sf.info(str(stems.DIR / f"t{tid}" / "drums.flac")).frames
    t, beat = np.arange(n) / SR, 60.0 / bpm
    k = (kick_amp * (np.modf(t / beat)[0] < kick_len) * np.sin(2 * np.pi * kick_hz * t)).astype(np.float32) * kick
    h = (0.2 * (np.modf(t / beat + 0.5)[0] < 0.1) * np.sin(2 * np.pi * 8000 * t)).astype(np.float32) * hats
    sf.write(str(stems.DIR / f"t{tid}" / "drums.flac"), np.stack([k + h, k + h]).T, SR, format="FLAC", subtype="PCM_16")
    z = np.zeros((2, n), np.float32)
    return lambda drums: dict(kick=np.stack([k, k]), snare=z, toms=z, hh=np.stack([h, h]), ride=z, crash=z)


def test_tame_holds_peaks_and_leaves_the_rest():
    from digitalcrate import stems
    n = stems.C.SR
    t = np.arange(n) / n
    y = 0.1 * np.sin(2 * np.pi * 200 * t)
    y[n // 2:n // 2 + 200] += 0.8 * np.hanning(200)                    # one hit, far over the ceiling
    ref = np.stack([y, 0.5 * y]).astype(np.float32)
    g = stems.tame(ref)
    assert abs(20 * np.log10(stems.PEAK_CEILING) + 8) < 1e-9
    assert g.shape == (n,) and g.dtype == np.float32 and g.max() <= 1.0
    assert np.abs(ref * g).max() <= stems.PEAK_CEILING + 1e-4
    assert np.abs(ref * g).max() > 0.95 * stems.PEAK_CEILING            # held at the ceiling, not pushed under it
    away = np.r_[0:n // 2 - 1000, n // 2 + 1200:n]
    assert g[away].min() > 0.9999                                       # nothing away from the hit is touched
    assert stems.tame(0.9 * stems.PEAK_CEILING * np.sign(ref)).min() > 0.9999   # a part under the ceiling: untouched


def test_drum_peaks_are_tamed_at_render_and_the_kit_still_adds_up(tmp_path, monkeypatch):
    import soundfile as sf
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    stems._LIB.update(n=-1, lib={})
    split = _fake_kit_song(tmp_path, 1, 100, kick_len=0.02, kick_hz=200, kick_amp=0.9)   # a spiky kit: its hits level to about -3 dBFS
    read = lambda f: sf.read(str(f), dtype="float32", always_2d=True)[0]
    c = stems.PEAK_CEILING
    calls, real = [], stems.tame
    monkeypatch.setattr(stems, "tame", lambda ref: calls.append(1) or real(ref))
    stems.render(1, "bass", 4, 4, 100)
    assert not calls                                                    # only Drums and Tops are tamed
    kit = read(stems.render(1, "drums", 4, 4, 100))
    assert calls and 0.95 * c < np.abs(kit).max() <= c + 1e-3
    stems.make_tops(1, split=split, embed=lambda s: np.ones(512, np.float32))
    d, t = stems.render(1, "drums", 4, 4, 100), stems.render(1, "tops", 4, 4, 100)
    assert np.abs(read(d) + read(t) - kit).max() < 2e-4                 # one curve, the kit's: they still add up
    assert np.abs(read(d)).max() <= c + 1e-3


@pytest.mark.parametrize("version", [5, 7])
def test_cached_split_plays_when_the_tops_source_is_missing(tmp_path, monkeypatch, version):
    import hashlib
    from digitalcrate import stems

    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    stems._LIB.update(n=-1, lib={})
    split = _fake_kit_song(tmp_path, 1, 100)
    stems.make_tops(1, split=split, embed=lambda s: np.ones(512, np.float32))
    cached = {}
    for role in ("drums", "tops"):
        path = stems.render(1, role, 4, 4, 100)
        key = hashlib.sha1(f"1|{role}|4|4|1.0|100.00|0.00|v{version}".encode()).hexdigest()[:16]
        cached[role] = path.rename(stems.CACHE / f"{key}.wav") if version == 5 else path

    (stems.DIR / "t1" / "tops.flac").unlink()
    assert not stems.tops_ready(1)
    for role, path in cached.items():
        assert stems.render(1, role, 4, 4, 100, with_tops=True) == path
        assert stems.render(1, role, 4, 4, 100) == path


def test_a_songs_tops_are_made_and_known(tmp_path, monkeypatch):
    import json, soundfile as sf
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    stems._LIB.update(n=-1, lib={})
    stems._EMB.clear()
    one = lambda seg: np.ones(512, np.float32)
    split = _fake_kit_song(tmp_path, 1, 100)
    assert "tops" not in stems.library()[1]["stems"] and not stems.has_tops(1)
    assert not stems._emb(1, "tops").any()                           # no row for it yet: zeros, never an error
    before = stems.library()[1]["level"]["drums"]
    m = stems.make_tops(1, split=split, embed=one)
    tops, _ = sf.read(str(stems.DIR / "t1" / "tops.flac"), dtype="float32", always_2d=True)
    assert stems.has_tops(1) and np.abs(tops.T - split(None)["hh"]).max() < 1e-4
    assert m["stems"][-1] == "tops" and len(m["act"]["tops"]) == 24 and m["level"]["tops"] < m["level"]["drums"] <= before
    assert stems.library()[1]["stems"] == m["stems"]                 # seen without a new song being added
    assert np.load(stems.DIR / "t1" / "emb.npy").shape == (5, 512) and stems._emb(1, "tops").any()
    kit = np.load(stems.DIR / "t1" / "kit.npy")                      # kick, snare, toms, tops: how loud, 86 times a second
    assert kit.shape[0] == 4 and abs(kit.shape[1] - tops.shape[0] / 512) <= 1 and kit[0].max() > kit[3].max() > 0 and not kit[1].any()
    # 2. all hats: Drums go; no hats: Tops are not offered. Neither is boosted.
    assert "drums" not in stems.make_tops(2, split=_fake_kit_song(tmp_path, 2, 100, kick=False), embed=one)["stems"]
    m3 = stems.make_tops(3, split=_fake_kit_song(tmp_path, 3, 100, hats=False), embed=one)
    assert "tops" not in m3["stems"] and stems.has_tops(3)
    # a song that gives only its vocals gives no Tops, and no file
    _fake_kit_song(tmp_path, 4, 100)
    mp = stems.DIR / "t4" / "meta.json"
    mp.write_text(json.dumps({**json.loads(mp.read_text()), "stems": ["vocals"]}))
    stems._LIB.update(n=-1, lib={})
    assert stems.make_tops(4, split=split, embed=one) is None and not stems.has_tops(4)


def test_drums_and_tops_add_back_up_to_the_kit(tmp_path, monkeypatch):
    import soundfile as sf
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    stems._LIB.update(n=-1, lib={})
    split = _fake_kit_song(tmp_path, 1, 100)
    read = lambda f: sf.read(str(f), dtype="float32", always_2d=True)[0]
    db = lambda y: 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9)
    kit, kit110 = stems.render(1, "drums", 4, 4, 100), stems.render(1, "drums", 4, 4, 110)   # the kit as it is today
    whole = stems.peaks(1, "drums")["path"]
    stems.make_tops(1, split=split, embed=lambda s: np.ones(512, np.float32))
    d, t = stems.render(1, "drums", 4, 4, 100), stems.render(1, "tops", 4, 4, 100)
    assert d != kit and np.abs(read(d) + read(t) - read(kit)).max() < 2e-4                  # exactly, at the song's own tempo
    assert db(read(t)) < db(read(d)) - 6                                                    # hats are as quiet as hats are
    d2, t2 = stems.render(1, "drums", 4, 4, 110), stems.render(1, "tops", 4, 4, 110)
    assert abs(db(read(d2) + read(t2)) - db(read(kit110))) < 1.0                            # very nearly, once stretched
    assert stems.render(1, "tops", 4, 4, 100, semis=2) != t                                 # your own pitch
    p = stems.peaks(1, "drums")
    assert p["path"].name == "drums-notops.pk" and p["path"] != whole and stems.peaks(1, "tops")["n"] == p["n"]
    with pytest.raises(Exception):
        stems.render(2, "tops", 0, 4, 100)                                                  # a song that has none


def test_tops_are_picked_like_drums(tmp_path, monkeypatch):
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    import sqlite3
    def _con():  # its own database: never the library's
        c = sqlite3.connect(tmp_path / "t.sqlite"); c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={})
    stems._EMB.clear()
    one = lambda seg: np.ones(512, np.float32)
    for tid in (1, 2):
        stems.make_tops(tid, split=_fake_kit_song(tmp_path, tid, 100), embed=one)
    _fake_kit_song(tmp_path, 3, 100)                               # prepared, but no tops yet
    st = dict(bpm=100, key="D", slots=dict(drums=dict(stem="drums", track=1, bar0=0, n=4)))
    got = {stems.pick("tops", st, rng=np.random.default_rng(k), slot="tops")["track"] for k in range(12)}
    assert got == {2}                                              # not the song already playing, never the one without tops
    p = stems.pick("tops", st, track=1, slot="tops")
    assert p["stem"] == "tops" and p["semis"] == 0 and p["k"] == 1
    st["slots"]["tops"] = dict(p, off=3)
    assert stems.info(st)["slots"]["tops"]["semis"] == 3
    assert stems.pick("tops", dict(st, bpm=140), slot="tops") is None            # out of what drums stretch to
    assert stems.alts(st, "tops")[0]["stem"] == "tops" and stems.log("like", st) == 2


def test_the_tops_pass_tops_up_times_itself_and_survives(tmp_path, monkeypatch, capsys):
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    stems._LIB.update(n=-1, lib={})
    one = lambda seg: np.ones(512, np.float32)
    splits = {tid: _fake_kit_song(tmp_path, tid, 100) for tid in (1, 2, 3, 4)}
    stems.make_tops(1, split=splits[1], embed=one)
    calls = []
    def split(drums):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("model fell over")
        return splits[2](drums)
    assert stems.top_up(split=split, embed=one) == 2                        # three to do, one failed
    out = capsys.readouterr().out
    assert "TASK making Tops for 3 songs" in out and "tops: 1/3 [1 ready]" in out and "about" in out and "model fell over" in out
    assert out.count("s for this song") == 1 and "TASK DONE Tops made for 2 songs" in out
    left = [t for t in (2, 3, 4) if not stems.has_tops(t)]
    assert len(left) == 1 and "tops" not in stems.library()[left[0]]["stems"] and "tops" not in stems.library()[left[0]]["act"]
    def stop(drums):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        stems.top_up(split=stop, embed=one)
    kept = sorted(f.name for f in (stems.DIR / f"t{left[0]}").glob("*.flac"))
    assert kept == ["bass.flac", "drums.flac", "other.flac", "vocals.flac"]                 # nothing half-made
    assert stems.top_up(limit=1, split=splits[left[0]], embed=one) == 1 and stems.top_up(split=split, embed=one) == 0


def test_tops_pass_retries_if_the_song_metadata_was_left_unfinished(tmp_path, monkeypatch):
    from digitalcrate import stems

    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    split = _fake_kit_song(tmp_path, 1, 100)
    embed = lambda _: np.ones(512, np.float32)
    stems.library()
    meta = stems.DIR / "t1" / "meta.json"
    before = meta.read_text()
    stems.make_tops(1, split=split, embed=embed)
    meta.write_text(before)  # the audio was published just before the metadata write was interrupted
    assert stems.has_tops(1)
    assert not stems.tops_ready(1)
    assert stems.top_up(split=split, embed=embed) == 1
    assert "tops" in stems.library()[1]["stems"]


def _bass(kind, secs=4.8, sr=SR):
    """Three basses and a near-silence, each a stereo loop."""
    t = np.arange(int(secs * sr)) / sr
    note = (np.modf(t / 0.6)[0] < 0.8) * np.exp(-3 * np.modf(t / 0.6)[0])            # a note every 0.6 s
    if kind == "sub":      x = 0.3 * np.sin(2 * np.pi * 45 * t) * note
    elif kind == "mid":    x = 0.3 * (np.sin(2 * np.pi * 110 * t) + 0.5 * np.sin(2 * np.pi * 220 * t)) * note
    elif kind == "both":   x = (0.3 * np.sin(2 * np.pi * 45 * t) + 0.04 * np.sin(2 * np.pi * 110 * t)) * note
    elif kind == "spiky":  x = 0.1 * np.sin(2 * np.pi * 80 * t) * note; x[::int(0.6 * sr)] += 0.9
    else:                  x = 1e-5 * np.sin(2 * np.pi * 80 * t)
    return np.stack([x, x]).astype(np.float32)


def test_bass_parts_are_evened_out():
    import time
    from digitalcrate import basscond as BC
    db = lambda v: 20 * np.log10(v + 1e-12)
    rms = lambda y: float(np.sqrt(np.mean(y ** 2)))
    crest = lambda y: db(np.abs(y).max()) - db(rms(y))
    flat = lambda y: y * min(0.08 / (rms(y) + 1e-12), 0.9 / (np.abs(y).max() + 1e-9), 60.0)     # the level every part gets today
    share = lambda y: (lambda X, f: X[(f >= 30) & (f < 60)].sum() / X.sum())(np.abs(np.fft.rfft(y[0])) ** 2, np.fft.rfftfreq(y.shape[1], 1 / SR))
    out = {k: BC.condition(_bass(k), SR) for k in ("sub", "mid", "both", "spiky", "quiet")}
    for k, y in out.items():
        assert y.shape == _bass(k).shape and y.dtype == np.float32 and np.isfinite(y).all() and np.abs(y).max() <= 0.9, k
    heard = lambda y: db(BC.heard(y[0], SR))
    apart0 = heard(flat(_bass("mid"))) - heard(flat(_bass("sub")))
    apart1 = heard(out["mid"]) - heard(out["sub"])
    assert apart0 > 6 and apart1 < apart0 * 0.65                                    # closer by ear: about half the gap is made up
    for k in ("sub", "mid", "both"):
        assert abs(db(rms(out[k])) - db(0.08)) <= 4.1, k                            # and never more than 4 dB from the energy match
    assert db(rms(out["sub"])) > db(0.08) + 2                                       # 1. a pure sub comes up, and is not shelved away
    assert share(out["sub"]) > 0.95 and share(out["both"]) < share(_bass("both")) - 0.02
    assert crest(_bass("spiky")) > 18 and crest(out["spiky"]) < 12.6                # stray peaks held
    assert abs(crest(out["mid"]) - crest(flat(_bass("mid")))) < 3.5                 # a plain bass keeps its shape
    assert rms(out["quiet"]) <= rms(flat(_bass("quiet"))) * 1.6                     # 2. near-silence is not pulled up
    # 3. seamless: a loop twice over comes out as the loop twice over; a one-bar and a sixteen-bar loop both work
    y = _bass("mid"); twice = BC.condition(np.tile(y, 2), SR)
    assert np.abs(twice[:, :y.shape[1]] - twice[:, y.shape[1]:]).max() < 2e-3
    assert np.abs(twice[:, :y.shape[1]] - out["mid"]).max() < 0.02
    for secs in (1.2, 38.4):
        z = _bass("both", secs); assert BC.condition(z, SR).shape == z.shape
    t0 = time.perf_counter(); BC.condition(_bass("spiky", 19.2), SR)
    assert time.perf_counter() - t0 < 1.0                                           # (8 bars at 100 bpm; the aim is 0.25 s)


def test_even_bass_does_not_raise_a_quiet_loop_with_a_click():
    from digitalcrate import basscond

    y = _bass("quiet", 2.4) * 10
    middle = y.shape[1] // 2
    y[:, middle] = -0.65
    out = basscond.condition(y, SR)
    before_click = slice(0, middle // 2)
    legacy_gain = 0.9 / abs(y[0, middle])
    assert np.abs(out[:, before_click]).max() <= np.abs(y[:, before_click]).max() * legacy_gain * 1.001
    y[:, middle] = -0.2
    assert float(np.abs(basscond.condition(y, SR)).max()) <= 0.9
    bed = []
    for amplitude in (0.0019, 0.0020):
        y = _bass("quiet", 2.4) * (amplitude / 1e-5)
        y[:, middle] = -0.65
        bed.append(float(np.abs(basscond.condition(y, SR)[:, before_click]).max()))
    assert bed[1] / bed[0] < 1.2


def test_new_bass_parts_are_rendered_even_and_old_ones_as_before(tmp_path, monkeypatch):
    import soundfile as sf, sqlite3
    from digitalcrate import stems, basscond
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    def _con():
        c = sqlite3.connect(tmp_path / "t.sqlite"); c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={}); stems._EMB.clear()
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)
    _fake_stem_song(tmp_path, 2, 100, 0, "major", 0)
    y = _bass("spiky", 24 * 2.4)                                                     # song 1's bass has stray peaks
    sf.write(str(stems.DIR / "t1" / "bass.flac"), y.T, SR, format="FLAC", subtype="PCM_16")
    raw = stems.render(1, "bass", 0, 4, 100)
    before = raw.read_bytes()
    even = stems.render(1, "bass", 0, 4, 100, cond=1)
    read = lambda f: sf.read(str(f), dtype="float32", always_2d=True)[0]
    crest = lambda a: 20 * np.log10(np.abs(a).max() / np.sqrt(np.mean(a ** 2)))
    assert even != raw and crest(read(even)) < crest(read(raw)) - 4 and len(read(even)) == len(read(raw))
    assert stems.render(1, "bass", 0, 4, 100) == raw and raw.read_bytes() == before  # 4. an old part: the same file
    assert stems.render(1, "other", 0, 4, 100, cond=1) == stems.render(1, "other", 0, 4, 100)
    st = dict(bpm=100, key="C", slots={})
    assert stems.pick("bass", st, slot="bass")["cond"] == basscond.VERSION and "cond" not in stems.pick("other", st, slot="other")
    st["slots"]["bass"] = dict(stems.pick("bass", st, track=1, slot="bass"))
    assert all(a.get("cond") == basscond.VERSION for a in stems.alts(st, "bass"))
    quiet = _bass("quiet", 2.4)
    quiet[:, quiet.shape[1] // 2] = -0.2
    sf.write(str(stems.DIR / "t2" / "bass.flac"), quiet.T, SR, format="FLAC", subtype="PCM_16")
    assert float(np.abs(read(stems.render(2, "bass", 0, 1, 100, cond=1))).max()) <= 0.9


def test_a_songs_keys_follow_its_chords():
    """One chord a bar; the key of each stretch is the one whose chords cover it. The filed key is believed unless
    the chords clearly say otherwise, and a borrowed chord isn't a change of key."""
    from digitalcrate import songkeys as K
    assert K.parse("B♭m") == (10, True) and K.parse("F♯") == (6, False) and K.parse("C") == (0, False) and K.parse("N") is None
    bars = [b * 2.0 for b in range(5)]
    assert K.bar_chords([(0, 2.1, "C"), (2.1, 3.0, "G"), (3.0, 5.9, "Am"), (7.8, 8, "F")], bars) == ["C", "Am", "Am", None]
    # 40 bars of A♭ major / F minor (filed: F minor), then 40 bars of C, G, Am, F: a second key, from bar 41
    first, second = ["Fm", "B♭m", "D♭", "E♭"] * 10, ["C", "G", "Am", "F"] * 10
    keys = K.local_keys(first + second, (5, "minor"))
    assert [(pc, sc) for _, pc, sc in keys] == [(5, "minor"), (0, "major")] and abs(keys[1][0] - 40) <= 2
    m = dict(pc=5, scale="minor", bars=list(range(81)), keys=keys)
    assert K.key_at(m, 8, 4) == (5, "minor") and K.key_at(m, 60, 4) == (0, "major") and K.key_at(m) == (5, "minor")
    assert K.key_at(dict(pc=5, scale="minor", bars=[0, 1]), 0, 1) == (5, "minor")        # not analysed: the filed key
    # two borrowed bars in the middle of a song don't change its key; nor do chords the filed key shares with a neighbor
    assert len(K.local_keys(["C", "F", "G", "Am"] * 6 + ["B♭", "E♭"] + ["C", "F", "G", "Am"] * 6, (0, "major"))) == 1
    assert K.local_keys(["C", "F"] * 20, (0, "major")) == [[0, 0, "major"]]               # (C and F are also in F major)
    assert K.local_keys(["A", "D", "E"] * 12, (6, "minor")) == [[0, 6, "minor"]]          # the relative major's chords: its name stays
    assert K.local_keys([None] * 30 + ["C"], (0, "major")) == []                          # too little to go on
    # a second opinion from the notes: a stretch leaves the filed key only if its notes fit the new key better
    tri = lambda *pcs: [1.0 if k in pcs else 0.0 for k in range(12)]
    in_c, in_ab = tri(0, 2, 4, 5, 7, 9, 11), tri(8, 10, 0, 1, 3, 5, 7)
    assert len(K.local_keys(first + second, (5, "minor"), [in_ab] * 40 + [in_c] * 40)) == 2      # the notes agree: two keys
    assert K.local_keys(first + second, (5, "minor"), [in_ab] * 80) == [[0, 5, "minor"]]         # they don't: the filed key
    assert K.notes_fit(in_c, 0) > K.notes_fit(in_c, 8) + 0.5


def test_parts_are_shifted_by_the_key_of_their_own_bars(tmp_path, monkeypatch):
    """A song that changes key: a part from its second stretch is shifted from that stretch's key, not the filed one."""
    import json, sqlite3
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    def _con():
        c = sqlite3.connect(tmp_path / "t.sqlite"); c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(stems, "connect", _con)
    stems._LIB.update(n=-1, lib={}); stems._EMB.clear()
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)          # C major throughout
    _fake_stem_song(tmp_path, 2, 100, 5, "minor", 5)          # filed F minor ...
    monkeypatch.setattr(stems.songkeys, "SWITCH", 2.0)        # (24 bars: a change of key has little time to show)
    heard = {}
    def chords(y, sr):                                        # ... but its second half is C, G, Am, F
        heard["n"] = len(y)
        bar = 2.4
        return [(b * bar, (b + 1) * bar, (["Fm", "B♭m", "D♭", "E♭"] if b < 12 else ["C", "G", "Am", "F"])[b % 4]) for b in range(24)]
    m = stems.make_chords(2, chords)
    assert heard["n"] > 0 and m["chords"][0] == "Fm" and m["chords"][13] == "G"
    rel = stems.songkeys._major_of                             # (C major and A minor are the same chords)
    assert [rel(pc, sc) for _, pc, sc in m["keys"]] == [8, 0]
    assert json.loads((stems.DIR / "t2" / "meta.json").read_text())["keys"] == m["keys"]
    lib = stems.library()
    assert stems.key_semis(lib[2], (0, "major"), 2, 4) == 4 and stems.key_semis(lib[2], (0, "major"), 16, 4) == 0
    state = dict(bpm=100, key="C", slots=dict(other=dict(track=1, bar0=0, n=4, off=0), bass=dict(track=2, bar0=16, n=4, off=0)))
    i = stems.info(state)
    assert i["slots"]["bass"]["semis"] == 0 and i["slots"]["bass"]["key"] in ("C", "Am")
    state["slots"]["bass"]["bar0"] = 2
    assert stems.info(state)["slots"]["bass"]["semis"] == 4 and stems.info(state)["slots"]["bass"]["key"] == "Fm"
    # a combination saved while the song had only its filed key (the bass there was shifted +4, by hand -1 more: +3)
    # opens sounding the same: the part's own offset takes up the difference, in the mixer and in its snapshots
    old = dict(stem="bass", track=2, bar0=16, n=4, off=-1, semis=3)
    saved = stems.as_saved(dict(bpm=100, key="C", slots=dict(bass=dict(old)), snaps=[dict(slots=dict(bass=dict(old)))]))
    assert saved["slots"]["bass"]["off"] == 3 and saved["snaps"][0]["slots"]["bass"]["off"] == 3
    assert stems.info(dict(bpm=100, key="C", slots=saved["slots"]))["slots"]["bass"]["semis"] == 3
    assert stems.as_saved(dict(bpm=100, key="C", slots=dict(bass=dict(old, bar0=2, semis=3))))["slots"]["bass"]["off"] == -1
    # a stem part turned into a one-shot plays that part, rendered at the tempo
    import soundfile as sf
    src = stems.shot_source("stem:1:other:4:2:1:0:0:0", "C", 120)
    assert src == stems.render(1, "other", 4, 2, 120, 0, 1) and sf.info(str(src)).frames == round(2 * 240 / 120 * SR)
    # the pass: songs without chords yet get them; one already done is left alone
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a))))
    assert stems.chord_up(chords=chords) == 1 and "chords" in stems.library()[1]
    assert stems.chord_up(chords=chords) == 0


def test_one_shot_export_plays_backwards_and_in_part(tmp_path, monkeypatch):
    """In the Live set as in the mixer: a reversed one-shot is written backwards, and a hit set to play half of the
    piece stops there."""
    import soundfile as sf
    from digitalcrate import conform, stems
    n = int(0.4 * SR)
    ramp = np.linspace(0.05, 0.9, n, dtype=np.float32)                 # quiet at its start, loud at its end
    sample = tmp_path / "ramp.wav"
    sf.write(sample, np.stack([ramp, ramp]).T, SR, subtype="FLOAT")
    monkeypatch.setattr(conform, "render", lambda path, key=None: (sample, None))
    part = dict(sample=sample.name, steps=[0], n=1)
    read = lambda f: sf.read(str(f), dtype="float32", always_2d=True)[0][:, 0]
    stems.oneshot_loop(part, 100, None, tmp_path / "a.wav")
    stems.oneshot_loop(dict(part, back=True), 100, None, tmp_path / "b.wav")
    stems.oneshot_loop(dict(part, gate={"0": 0.5}), 100, None, tmp_path / "c.wav")
    a, b, c = read(tmp_path / "a.wav"), read(tmp_path / "b.wav"), read(tmp_path / "c.wav")
    q = n // 4
    assert a[q] < a[3 * q] and b[q] > b[3 * q]                         # the other way round
    assert abs(c[q] - a[q]) < 1e-3 and abs(c[3 * q]) < 1e-4 and abs(a[3 * q]) > 0.5   # the first half only


def test_a_part_can_be_spliced_from_pieces(tmp_path, monkeypatch):
    """A part made of pieces of the song, one after the other (half bars allowed): as long as they add up to."""
    import sqlite3
    import soundfile as sf
    from digitalcrate import stems
    monkeypatch.setattr(stems, "DIR", tmp_path / "stems")
    monkeypatch.setattr(stems, "CACHE", tmp_path / "stems" / "cache")
    stems._LIB.update(n=-1, lib={}); stems._EMB.clear()
    _fake_stem_song(tmp_path, 1, 100, 0, "major", 0)
    f = stems.DIR / "t1" / "vocals.flac"                                   # each bar at its own level: bar b is 0.02 * (b + 1)
    n = sf.info(str(f)).frames
    bar = int(2.4 * SR)
    y = np.concatenate([np.full(bar, 0.02 * (b + 1), np.float32) for b in range(24)])[:n]
    sf.write(str(f), np.stack([y, y]).T, SR, format="FLAC", subtype="PCM_16")
    assert stems.clean_cut([[2.2, 1], [30, 2], [5, 0.2, 1], [23.5, 4], [None, 1], [3, 1, 0, 2, 3]], 24) == (
        (2.0, 1.0, False, 1.0, 1), (23.5, 0.5, False, 1.0, 1), (5.0, 0.5, True, 1.0, 1), (23.5, 0.5, False, 1.0, 1),
        (None, 1.0, False, 1.0, 1), (3.0, 1.0, False, 2.0, 3))
    c = stems.clean_cut([[2, 1], [10, 0.5, 1], [None, 1], [4, 1, 0, 2, 3]], 24)
    assert stems.cut_key(c) == "2+1,10+0.5r,_+1,4+1s2x3" and stems.clean_cut(stems.parse_cut(stems.cut_key(c)), 24) == c
    assert stems.cut_bars(c) == 1 + 0.5 + 1 + 6
    out = stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 1], [10, 0.5], [5, 1.5]])
    a, sr = sf.read(str(out), dtype="float32", always_2d=True)
    assert len(a) == round(3 * 2.4 * SR)                                   # 3 bars in all
    lv = lambda t: float(np.abs(a[int(t * SR), 0]))
    one, two, three = lv(1.2), lv(2.4 + 0.6), lv(3.6 + 1.8)                # the middle of each piece
    assert abs(two / one - 11 / 3) < 0.05 and abs(three / one - 6 / 3) < 0.05   # bar 3, then bar 11, then bar 6
    assert out != stems.render(1, "vocals", 2, 4, 100, 0, 1) and out != stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 1], [10, 1]])
    # crossfaded joins: the same length; across a join the level glides from one piece to the next (no step), and the
    # last piece's tail lands on the start, where the loop comes round
    xo = stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 1], [10, 1]], xf=200)
    hard = sf.read(str(stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 1], [10, 1]])), dtype="float32", always_2d=True)[0][:, 0]
    x = sf.read(str(xo), dtype="float32", always_2d=True)[0][:, 0]
    j = int(2.4 * SR)
    assert len(x) == len(hard) == 2 * j
    assert abs(hard[j + 400]) > 2.5 * abs(hard[j - 400])                    # a clean cut: bar 3's level, then bar 11's at once
    mid = abs(x[j + int(0.1 * SR)])                                         # halfway through the 200 ms: between the two
    assert abs(x[j - 400]) < mid < abs(x[j + int(0.3 * SR)])
    assert abs(x[int(0.1 * SR)]) > 1.3 * abs(x[int(0.6 * SR)])              # bar 11 running on under the start of bar 3
    assert stems.shot_source("stem:1:vocals:2:2:1:0:0:0:2+1,10+1~200", None, 100) == xo
    # a piece played backwards: bars 3-4 forwards get louder at their middle; backwards, quieter
    fw = sf.read(str(stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 2], [10, 1]])), dtype="float32", always_2d=True)[0][:, 0]
    bw_f = stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 2, 1], [10, 1]])
    bw = sf.read(str(bw_f), dtype="float32", always_2d=True)[0][:, 0]
    assert abs(fw[j + 2000]) > 1.2 * abs(fw[j - 2000]) and abs(bw[j - 2000]) > 1.2 * abs(bw[j + 2000])
    assert abs(bw[2 * j + 2000] - fw[2 * j + 2000]) < 1e-4                 # the piece after it is as it was
    assert stems.shot_source("stem:1:vocals:2:3:1:0:0:0:2+2r,10+1", None, 100) == bw_f
    # a rest, a piece twice as long, a piece three times over: bar 3, a bar of nothing, bar 11 over two bars, bar 6 x3
    mix = sf.read(str(stems.render(1, "vocals", 2, 4, 100, 0, 1, cut=[[2, 1], [None, 1], [10, 1, 0, 2], [5, 1, 0, 1, 3]])),
                  dtype="float32", always_2d=True)[0][:, 0]
    assert len(mix) == 7 * j
    m = lambda bar_: float(np.abs(mix[int((bar_ + 0.5) * j)]))
    assert m(1) < 1e-4 and m(0) > 0.001                                     # the rest is silent
    assert abs(m(2) / m(0) - 11 / 3) < 0.15 and abs(m(3) / m(0) - 11 / 3) < 0.15   # bar 11, for two bars
    assert all(abs(m(b) / m(0) - 6 / 3) < 0.1 for b in (4, 5, 6))           # bar 6, three times
    # as a one-shot, and in the Live set, the same splice
    assert stems.shot_source("stem:1:vocals:2:3:1:0:0:0:2+1,10+0.5,5+1.5", None, 100) == out
