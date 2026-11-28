"""Which notes a sample plays and how far off the tuning grid it sits, for Mashup's harmony fit.

The 12-note chroma kept with every sample smears: a voice a third of a semitone flat lands on two notes at once, and
a sample with no clear notes looks like a little of everything, which matches any harmony "well". Here the notes are
measured three times finer (36 positions an octave), which gives both things the fit needs:

    cents, clarity   how far the sample sits from the grid (-50..50 cents) and how sure that is (0 = notes all over
                     the place or sliding, about 0.2 and up = a steady pitch)
    profile          the share of its energy on each of the 12 notes, read on its own grid (so a flat sample's notes
                     are named right) and with the floor taken off (so only notes that stand out count)

    fine(y, sr) -> (36,)             tuning(f) -> (cents, clarity)            profile(f) -> (12,) summing to 1 (or 0)
    notes(con) -> {sample path: (profile, cents, clarity)}                    song_tuning(con) -> {track: (cents, clarity)}
    run()                            the pass: every one-shot and pad sample, every song prepared for Mashup

Kept in two tables of their own (sample_notes, track_tuning). Nothing else is changed.
"""
import threading
import time

import numpy as np

from . import config as C

SR = 22050
STEADY = 0.12   # clarity from which a tuning is believed (a piano note measures about 0.25, a sliding voice under 0.1)


def fine(y, sr=SR):
    """Energy at 36 positions an octave (three a semitone), summed over time. Position 3k is note k exactly in tune,
    3k+1 a third of a semitone sharp, 3k+2 a third flat of the next note."""
    import librosa
    y = np.asarray(y, np.float32)
    if len(y) < 2048 or not np.any(y):
        return np.zeros(36)
    c = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36, n_chroma=36, tuning=0.0, hop_length=512, n_octaves=6)
    return (c ** 2).sum(1).astype(float)


def tuning(f):
    """(cents off the grid, clarity): where within a semitone the energy sits, as a circular mean."""
    e = np.asarray(f, float).reshape(12, 3).sum(0)
    if e.sum() <= 0:
        return 0.0, 0.0
    z = (e * np.exp(2j * np.pi * np.arange(3) / 3)).sum() / e.sum()
    return float(np.angle(z) / (2 * np.pi) * 100), float(abs(z))


def profile(f, cents=None):
    """The share of energy on each of the 12 notes, on the sample's own grid, floor removed. Sums to 1 (0 if silent)."""
    f = np.asarray(f, float)
    if cents is None:
        cents = tuning(f)[0]
    g = np.roll(f, -int(round(cents / (100 / 3)))).reshape(12, 3)
    pc = g[:, 0] + 0.5 * (g[:, 1] + g[:, 2])
    pc = np.maximum(pc - np.median(pc), 0)
    return pc / pc.sum() if pc.sum() > 0 else np.zeros(12)


def _tables(con):
    con.execute("CREATE TABLE IF NOT EXISTS sample_notes (path TEXT PRIMARY KEY, fine BLOB, cents REAL, clarity REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS track_tuning (track INTEGER PRIMARY KEY, cents REAL, clarity REAL)")


_N = dict(n=-1, got={})
_T = dict(n=-1, got={})


def notes(con):
    """{sample path: (profile, cents, clarity)} of every sample measured so far."""
    _tables(con)
    n = con.execute("SELECT COUNT(*) FROM sample_notes").fetchone()[0]
    if _N["n"] != n:
        got = {}
        for path, blob, cents, clarity in con.execute("SELECT path, fine, cents, clarity FROM sample_notes"):
            got[path] = (profile(np.frombuffer(blob, np.float32), cents), cents, clarity)
        _N.update(n=n, got=got)
    return _N["got"]


def song_tuning(con):
    """{track: (cents, clarity)} of the songs prepared for Mashup."""
    _tables(con)
    n = con.execute("SELECT COUNT(*) FROM track_tuning").fetchone()[0]
    if _T["n"] != n:
        _T.update(n=n, got={int(t): (c, q) for t, c, q in con.execute("SELECT track, cents, clarity FROM track_tuning")})
    return _T["got"]


def apart(a, b):
    """How far tuning a is from tuning b, in cents, the short way round (-50..50): a semitone apart is in tune again."""
    return (a - b + 50) % 100 - 50


def measure(path):
    """-> (fine as float32 bytes, cents, clarity) of a library sample, or None if it can't be read."""
    import librosa
    try:
        y, _ = librosa.load(str(C.LIB_ROOT / path), sr=SR, mono=True, duration=30)
    except Exception:
        return None
    f = fine(y)
    cents, clarity = tuning(f)
    return f.astype(np.float32).tobytes(), cents, clarity


def _song(track):
    """A song's tuning from a minute of the middle of its Other stem (its Bass where it has no Other)."""
    import soundfile as sf
    import librosa
    d = C.DATA_DIR / "stems" / f"t{track}"
    for stem in ("other", "bass", "vocals"):
        f = d / f"{stem}.flac"
        if not f.exists():
            continue
        try:
            with sf.SoundFile(str(f)) as s:
                n = min(len(s), 60 * s.samplerate)
                s.seek(max(0, (len(s) - n) // 2))
                y = s.read(n, dtype="float32", always_2d=True).mean(1)
                y = librosa.resample(y, orig_sr=s.samplerate, target_sr=SR)
        except Exception:
            continue
        if np.sqrt(np.mean(y ** 2)) > 1e-3:
            return tuning(fine(y))
    return None


def missing(con):
    """(sample paths, tracks) not measured yet: the one-shot and pad pools, and the songs prepared for Mashup."""
    from . import stems as SM
    _tables(con)
    have = {r[0] for r in con.execute("SELECT path FROM sample_notes")}
    pool = {r["path"] for r in SM._oneshots(con)["rows"]} | {r["path"] for r in SM._pads(con)["rows"]}
    tuned = {r[0] for r in con.execute("SELECT track FROM track_tuning")}
    return sorted(pool - have), sorted(set(SM.library()) - tuned)


def run(limit=None, quiet=False, pause=0.0):
    """Measure what is missing. Light work (about 20 samples a second, half a second a song); safe to stop any time."""
    from .db import connect
    con = connect()
    paths, tracks = missing(con)
    paths = paths[:limit] if limit else paths
    if not quiet:
        print(f"TASK notes and tuning of {len(paths)} samples, {len(tracks)} songs", flush=True)
    done = 0
    for k, p in enumerate(paths, 1):
        m = measure(p)
        if m is not None:
            con.execute("INSERT OR REPLACE INTO sample_notes (path, fine, cents, clarity) VALUES (?, ?, ?, ?)", (p, *m))
            done += 1
        if k % 200 == 0:
            con.commit()
            if not quiet:
                print(f"  {k}/{len(paths)} samples", flush=True)
        if pause:
            time.sleep(pause)
    con.commit()
    for t in tracks:
        m = _song(t)
        if m is not None:
            con.execute("INSERT OR REPLACE INTO track_tuning (track, cents, clarity) VALUES (?, ?, ?)", (int(t), *m))
    con.commit()
    con.close()
    if not quiet:
        print(f"TASK DONE notes: {done} samples, {len(tracks)} songs", flush=True)
    return done


_BUSY = threading.Lock()
WANTED = False  # set by the fit when it meets samples not measured yet


def catch_up():
    """Measure newly mined samples in the background (the server calls this when the fit meets some it doesn't know).
    Never waits; one at a time; gently, so playback isn't disturbed."""
    global WANTED
    if not WANTED or not _BUSY.acquire(blocking=False):
        return False
    WANTED = False

    def go():
        try:
            run(quiet=True, pause=0.02)
        except Exception as e:
            print("notes: catching up failed:", str(e)[:120], flush=True)
        finally:
            _BUSY.release()
    threading.Thread(target=go, daemon=True).start()
    return True
