"""Song sections: intro, verse, chorus, bridge, break, solo, outro, from All-In-One (mir-aidj/all-in-one, MIT;
models trained on the Harmonix Set).

Why it matters for sampling: intros, outros and breaks are where a song is most exposed (fewer parts at once), loops
are best cut inside one section, and "from the intro" is useful to know when browsing.

    analyze(y, stems=None)  -> [(start, end, label)]    y: the mix; stems: htdemucs stems if mining already has them
    of_sample(secs, a, b)   -> the label a sample (a..b seconds) mostly falls in
    adjust(cands, secs)     mining: a small bonus for exposed sections, a penalty for loops across a section change
    run(limit=None)         the library pass for songs mined before this existed (separates, then analyses)

All-In-One needs NATTEN, which has no macOS build; _natten.py stands in for the four functions it uses, in plain
PyTorch (identical output; 5 s a song on the CPU with one model instead of 35 s with NATTEN, 4.5 min with the
default 8-model ensemble). It's optional: without it installed, everything here quietly does nothing.
"""
import json
import tempfile
from pathlib import Path

import numpy as np

from . import config as C
from .db import connect

MODEL = "harmonix-fold0"  # one of the 8 cross-validation models: near-identical sections, 8x faster
EXPOSED = {"intro", "outro", "break", "inst", "bridge"}
LABELS = {"intro": "intro", "verse": "verse", "chorus": "chorus", "bridge": "bridge", "inst": "instrumental break",
          "solo": "solo", "break": "break", "outro": "outro"}


def available():
    try:
        from ._natten import install
        install()
        import allin1  # noqa: F401
        return True
    except Exception:
        return False


def analyze(y, stems=None, name="track"):
    """Sections of one song. y: (channels, n) at C.SR. stems: {'bass','drums','other','vocals'} from htdemucs."""
    import soundfile as sf
    from ._natten import install
    install()
    import allin1
    if stems is None:
        from .models import separate
        stems = separate(y)
    with tempfile.TemporaryDirectory(prefix="dc-sections-") as tmp:
        tmp = Path(tmp)
        mix = tmp / f"{name}.wav"
        sf.write(str(mix), y.T, C.SR, subtype="PCM_16")
        d = tmp / "demix" / "htdemucs" / name  # where All-In-One looks for stems it would otherwise separate itself
        d.mkdir(parents=True)
        for k in ("bass", "drums", "other", "vocals"):
            sf.write(str(d / f"{k}.wav"), stems[k].T, C.SR, subtype="PCM_16")
        r = allin1.analyze(str(mix), demix_dir=str(tmp / "demix"), spec_dir=str(tmp / "spec"), device="cpu",
                           model=MODEL, keep_byproducts=True, multiprocess=False)  # its process pool deadlocks inside the app
    out = [(round(float(s.start), 2), round(float(s.end), 2), s.label) for s in r.segments]
    return [s for s in out if s[2] in LABELS]  # 'start' / 'end' are the silence either side


def of_sample(secs, a, b):
    best, lab = 0.0, None
    for s, e, l in secs or []:
        o = min(b, e) - max(a, s)
        if o > best:
            best, lab = o, l
    return lab


def adjust(cands, secs):
    """Mining: prefer candidates from exposed sections, and loops that don't straddle a section change."""
    if not secs:
        return cands
    edges = [s for s, _, _ in secs[1:]]
    for c in cands:
        lab = of_sample(secs, c["start"], c["end"])
        c["section"] = lab
        if lab in EXPOSED:
            c["quality"] = c["quality"] + 0.03
        if c.get("kind") == "loop" and any(c["start"] + 0.25 < e < c["end"] - 0.25 for e in edges):
            c["quality"] = c["quality"] - 0.08
    return cands


def _db():
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS sections (track_id INTEGER PRIMARY KEY, secs TEXT, model TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return con


def save(con, track_id, secs):
    con.execute("INSERT OR REPLACE INTO sections(track_id, secs, model) VALUES (?,?,?)",
                (track_id, json.dumps(secs), MODEL))
    con.commit()  # (it used to be left open: the sections were lost, and the write lock could outlive the call)


def by_track(con=None):
    con = con or _db()
    try:
        return {r["track_id"]: json.loads(r["secs"]) for r in con.execute("SELECT track_id, secs FROM sections")}
    except Exception:
        return {}


def run(limit=None):
    from .audio import decode
    if not available():
        print("All-In-One isn't installed: see models/README.md (song sections)", flush=True)
        return
    con = _db()
    rows = con.execute("""SELECT t.id, t.path FROM tracks t WHERE t.status='done'
                          AND t.id NOT IN (SELECT track_id FROM sections)
                          AND t.id IN (SELECT track_id FROM samples)""").fetchall()
    rows = rows[:limit] if limit else rows
    print(f"TASK finding song sections in {len(rows)} songs", flush=True)
    from .memguard import breathe
    for k, r in enumerate(rows, 1):
        breathe()
        try:
            secs = analyze(decode(r["path"]), name=f"t{r['id']}")
            save(con, r["id"], secs)
            con.commit()
        except Exception as e:
            print(f"    {Path(r['path']).name}: {str(e)[:100]}", flush=True)
        print(f"sections: {k}/{len(rows)}", flush=True)
    print("TASK DONE", flush=True)
