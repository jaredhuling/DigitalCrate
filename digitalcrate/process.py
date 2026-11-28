"""Per-track pipeline: decode -> tempo/key -> (separate) -> detect -> score -> CLAP classify -> render."""
import hashlib
import json
import re
import time
import traceback
from pathlib import Path

import numpy as np
from tqdm import tqdm

from . import config as C
from .audio import decode, write_wav, to_mono48, camelot, key_label, PITCHES
from .analyze import track_tempo_key, SourceFeat, bars, segment_stats, sample_key, sec_to_frames
from .extract import find_candidates, measure
from .db import connect
from . import models
from .policy import classify_track, sample_dir

# ---------------------------------------------------------------- CLAP vocab

TYPE_PROMPTS = {
    "vocal_female": "a woman singing, solo female vocals",
    "vocal_male": "a man singing, solo male vocals",
    "vocal_choir": "a choir of voices singing together",
    "vocal_spoken": "a person talking, spoken word speech",
    "pad": "an ambient synthesizer pad, sustained atmospheric chords",
    "strings": "a string section playing sustained notes",
    "drone": "a dark low droning sound",
    "chords_keys": "piano or electric piano chords",
    "organ": "an organ playing chords",
    "guitar": "a guitar playing",
    "melody": "a melodic synthesizer lead line",
    "brass": "brass horns or saxophone",
    "texture": "vinyl crackle, tape hiss and noisy texture",
    "field": "a field recording of rain, street ambience or nature sounds",
    "bass": "a deep bass line",
    "drums": "drums and percussion, a drum beat",
    "silence": "near silence, very quiet",
}
TYPE_KEYS = list(TYPE_PROMPTS)
VOCAL_TYPES = ["vocal_female", "vocal_male", "vocal_choir", "vocal_spoken"]
INST_CATEGORY = {
    "pad": "Pads & Atmospheres", "strings": "Pads & Atmospheres", "drone": "Pads & Atmospheres",
    "chords_keys": "Chords & Keys", "organ": "Chords & Keys", "guitar": "Chords & Keys",
    "melody": "Melodies & Leads", "brass": "Melodies & Leads",
    "texture": "Textures & Field", "field": "Textures & Field",
    "bass": "Bass & Sub",
}

MOOD_PROMPTS = {
    "dark": "dark, ominous music",
    "melancholic": "sad, melancholic, mournful music",
    "ethereal": "ethereal, angelic, heavenly sound",
    "warm": "warm, soft, analog sound",
    "eerie": "eerie, haunting, ghostly sound",
    "dreamy": "dreamy, hazy, blurred sound",
    "euphoric": "euphoric, uplifting, rave music",
    "lofi": "lo-fi, dusty, degraded old recording",
    "cold": "cold, metallic, industrial sound",
    "soulful": "soulful r&b singing",
    "hypnotic": "hypnotic, repetitive, minimal",
    "dubby": "dub techno, echo and reverb chords",
    "nocturnal": "night time city, rain at night",
    "pastoral": "pastoral, organic, acoustic, forest",
    "bright": "bright, shiny, clear sound",
}

SUBTYPE_PREFIX = {
    ("Vocals", "Phrases"): "VoxPhrase", ("Vocals", "Chops"): "VoxChop",
    ("Vocals", "Spoken"): "VoxSpoken", ("Vocals", "Choir & Group"): "VoxChoir",
    "Vocal Atmospheres": "VoxAtmos", "Pads & Atmospheres": "Pad", "Strings & Orchestral": "Strings", "Chords & Keys": "Keys",
    "Melodies & Leads": "Melody", "Textures & Field": "Texture", "Bass & Sub": "Bass",
}
KIND_SUBTYPE = {"loop": "Loops", "free": "Free", "oneshot": "One-Shots", "phrase": "Free"}


def _safe(s, n=40):
    s = re.sub(r"[^\w\-\. ]+", "", str(s or "Unknown")).strip().replace(" ", "")
    return s[:n] or "Unknown"


def classify(c, probs, source_has_stems):
    """Return (category, subtype) or None to reject."""
    p = dict(zip(TYPE_KEYS, probs))
    if p["drums"] > 0.35 or p["silence"] > 0.5:
        return None
    voc = sum(p[k] for k in VOCAL_TYPES)
    allowed = [k for k in INST_CATEGORY
               if not (k == "bass" and (c["source"] == "other" or p["bass"] < 0.6))]
    inst = max(allowed, key=lambda k: p[k])
    c["instrument"] = max(TYPE_KEYS, key=lambda k: p[k] if k not in ("drums", "silence") else -1)
    if c["group"] in ("vocal_phrase", "vocal_chop") or (not source_has_stems and voc > 0.55):
        if c["kind"] == "oneshot" or c["group"] == "vocal_chop":
            return "Vocals", "Chops"
        vt = max(VOCAL_TYPES, key=lambda k: p[k])
        if voc < 0.25:  # vocal stem but sounds like an instrument: likely bleed
            return None
        return "Vocals", {"vocal_spoken": "Spoken", "vocal_choir": "Choir & Group"}.get(vt, "Phrases")
    if c["group"] == "vocal_atmos":
        return "Vocal Atmospheres", KIND_SUBTYPE[c["kind"]]
    if source_has_stems and c["source"] == "other" and voc > 0.5:
        return None  # vocal bleed into 'other'
    return INST_CATEGORY[inst], KIND_SUBTYPE[c["kind"]]


def _dedupe(cands, thresh=0.93):
    keep = []
    for c in sorted(cands, key=lambda c: -c["quality"]):
        if all(float(c["emb"] @ k["emb"]) < thresh for k in keep
               if k["category"] == c["category"] and k["subtype"] == c["subtype"]):
            keep.append(c)
    return keep


def _cap(cands):
    out, counts = [], {}
    for c in sorted(cands, key=lambda c: -c["quality"]):
        g = c["group"]
        spacing = 2.5 if g in ("vocal_chop", "oneshot") else 0.5
        if any(k["group"] == g and abs(k["start"] - c["start"]) < spacing for k in out):
            continue
        if counts.get(g, 0) < C.MAX_PER_TRACK[g]:
            out.append(c)
            counts[g] = counts.get(g, 0) + 1
    return out


def process_track(con, row, separate_mode="auto", verbose=False, vocals="demucs", pads_only=False, mashup=False):
    """Mine one song. pads_only: an already-mined song, looked at again for pads only; its samples stay, new pads
    are added (unless they sound like one it already has)."""
    t0 = time.time()
    _columns()
    policy = row["policy"] or classify_track(row["artist"], row["genre"], row["path"])
    y = decode(row["path"])
    if y.shape[1] < C.SR * 8:
        con.execute("UPDATE tracks SET status='skipped', error='too short' WHERE id=?", (row["id"],))
        return 0
    tk = track_tempo_key(y)
    mix = SourceFeat(y)
    bar_times, _how = bars(tk, y, mix)

    clean_frac = float(((mix.pratio < C.MIX_PRATIO_DRUMS) & mix.active()).sum() / max(1, mix.active().sum()))
    do_sep = separate_mode == "always" or (separate_mode == "auto" and clean_frac < 0.9)
    stems, feats = None, None
    if do_sep:
        stems = models.separate(y)
        if vocals != "demucs":
            stems["vocals"] = models.roformer_vocals(row["path"], y.shape[1], vocals)
        feats = {k: SourceFeat(v, hpss=k in ("vocals", "other")) for k, v in stems.items()}
    if mashup and not pads_only:  # also keep the song's stems for Mashup, from the separation just made
        try:
            from . import stems as SM
            if policy == "reference":
                pass
            elif int(row["id"]) in SM.library():
                print("    Mashup: already prepared")
            elif not tk["tempo_ok"] or len(bar_times) < 17:
                print("    Mashup: not prepared (no steady 4/4 to line up)")
            else:  # mining leaves a song without drums whole; Mashup wants its parts all the same, so separate it here
                m = SM.prepare_track(con, row, have=dict(tk=tk, bars=bar_times,
                                                         stems=stems if stems is not None else models.separate(y)))
                print("    Mashup: " + ("its stems are kept" if m else "not prepared (no steady 4/4 to line up)"))
        except Exception as e:
            print("    Mashup: failed:", str(e)[:120])
    t_sep = time.time()

    cands, masks = find_candidates(tk, mix, feats, bar_times)
    try:  # real pads: stretches holding 1-2 chords for 2+ bars, cut on the chord change so they loop
        from . import pads as PADS
        src = "other" if stems is not None else "mix"
        timed = tk["tempo_ok"] and len(bar_times) > 4
        for a, b, L in PADS.find(stems["other"] if stems is not None else y, C.SR, bar_times if timed else None):
            cands.append(dict(source=src, group="pad", kind="loop" if L else "free", start=a, end=b, bars=L))
    except Exception as e:
        print("    pad finder failed:", str(e)[:100])
    if policy == "vocals_only":  # the beat is someone else's sample: keep the original vocal only
        cands = [c for c in cands if c["group"] in ("vocal_phrase", "vocal_chop")]
    if pads_only:
        cands = [c for c in cands if c["group"] == "pad"]
    cands = [measure(c, mix, feats, masks) for c in cands]
    for c in cands:
        if c["group"] == "pad":
            c["quality"] += 0.05  # asked for: a loop that holds its chords
    if stems is not None and not pads_only:  # song sections (optional: All-In-One), from the stems mining already has: ~5 s
        try:
            from . import sections as SEC
            if SEC.available():
                secs = SEC.analyze(y, stems, name=f"t{row['id']}")
                scon = SEC._db()
                try:
                    SEC.save(scon, row["id"], secs)
                finally:
                    scon.close()
                cands = SEC.adjust(cands, secs)
        except Exception as e:
            print("    sections failed:", str(e)[:100])
    cands = [c for c in cands if c["quality"] >= C.MIN_QUALITY * 0.75]
    # pre-cap generously before the (costly) embedding step
    cands = sorted(cands, key=lambda c: -c["quality"])
    pre, counts = [], {}
    for c in cands:
        if counts.get(c["group"], 0) < 4 * C.MAX_PER_TRACK[c["group"]]:
            pre.append(c)
            counts[c["group"]] = counts.get(c["group"], 0) + 1
    cands = pre

    def audio_of(c, which=None):
        src = which or c["rendered_from"]
        sig = y if src == "mix" else stems[src]
        pad_pre = 0.0 if c["kind"] == "loop" else 0.03
        pad_post = 0.0 if c["kind"] == "loop" else 0.25
        a = max(0, int((c["start"] - pad_pre) * C.SR))
        b = min(sig.shape[1], int((c["end"] + pad_post) * C.SR))
        return sig[:, a:b]

    # CLAP embeddings + zero-shot
    vocab_t = None
    if cands:
        cl = models.clap()
        clips = []
        for c in cands:
            m = audio_of(c).mean(0)
            if len(m) > C.SR * 10:
                mid = len(m) // 2
                m = m[mid - C.SR * 5: mid + C.SR * 5]
            clips.append(to_mono48(m))
        embs = cl.embed_audio(clips)
        T = cl.embed_text(tuple(TYPE_PROMPTS.values()))
        M = cl.embed_text(tuple(MOOD_PROMPTS.values()))
        scale = float(cl.model.logit_scale_a.exp().clamp(max=100))
        logits = scale * embs @ T.T
        probs = np.exp(logits - logits.max(1, keepdims=True))
        probs /= probs.sum(1, keepdims=True)
        moods = embs @ M.T
        kept = []
        from .grain import score as grain_score, penalty as grain_penalty
        for c, e, pr, md in zip(cands, embs, probs, moods):
            cat = classify(c, pr, stems is not None)
            if cat is None:
                continue
            if stems is not None and c["rendered_from"] == "other":  # separation grain: a grainy cut sinks
                try:
                    c["grain"] = grain_score(audio_of(c), audio_of(c, "mix"))
                    c["quality"] *= grain_penalty(c["grain"])
                except Exception:
                    pass
            c["category"], c["subtype"] = cat
            c["emb"], c["probs"], c["moods"] = e, pr, md
            c["quality"] *= 1 - 0.8 * float(pr[TYPE_KEYS.index("drums")])
            if c["quality"] >= C.MIN_QUALITY:
                kept.append(c)
        cands = _cap(_dedupe(kept))
        for c in cands:  # pads hold 1-2 chords and keep still; moving passages are strings & orchestral or chords
            if c["category"] in ("Pads & Atmospheres", "Strings & Orchestral") and (
                    c["kind"] != "oneshot" or c["category"] == "Pads & Atmospheres"):
                try:
                    from . import pads as PADS
                    a = PADS.analyze(audio_of(c))
                    c["chords"], c["pad_still"], c["pad_steady"] = json.dumps(a["chords"]), a["still"], a["steady"]
                    c["category"], c["subtype"] = PADS.where(dict(subtype=c["subtype"], instrument=c.get("instrument"),
                                                                  kind=c["kind"]), a)
                except Exception as e:
                    print("    pad check failed:", str(e)[:100])

    # render + store
    if pads_only:  # keep what the song has; skip new cuts that are already there or sound like a sample it has
        have = con.execute("SELECT id, category, clap FROM samples WHERE track_id=? AND clap IS NOT NULL", (row["id"],)).fetchall()
        ids = {r["id"] for r in have}
        E = {r["id"]: (r["category"], np.frombuffer(r["clap"], np.float16).astype(np.float32)) for r in have}
        def fresh(c):
            sid = hashlib.sha1(f"{row['path']}|{c['source']}|{c['start']:.2f}|{c['kind']}".encode()).hexdigest()[:6]
            if sid in ids:
                return False
            return all(float(c["emb"] @ e) < 0.93 for cat, e in E.values() if cat == c["category"])
        cands = [c for c in cands if fresh(c)]
    else:
        con.execute("DELETE FROM samples WHERE track_id=? AND parent_id IS NULL AND category != 'Percussion'", (row["id"],))
    feat_by = {"mix": mix, **(feats or {})}
    from .recat import overrides
    user_overrides = overrides()
    n = 0
    for c in cands:
        f0, f1 = sec_to_frames(c["start"]), max(sec_to_frames(c["end"]), sec_to_frames(c["start"]) + 2)
        st = segment_stats(feat_by[c["feat_src"]], f0, f1)
        pc, scale, kstr, kfrom = sample_key(st["chroma"], tk["pc"], tk["scale"])
        if c["category"] == "Textures & Field" and kstr < 0.6:
            kfrom = "none"
        note = PITCHES[int(np.argmax(st["chroma"]))] if c["kind"] == "oneshot" else None
        bpm = tk["bpm"] if tk["tempo_ok"] else None
        sid = hashlib.sha1(f"{row['path']}|{c['source']}|{c['start']:.2f}|{c['kind']}".encode()).hexdigest()[:6]
        if sid in user_overrides:  # your manual recategorisation always wins
            c["category"], c["subtype"] = user_overrides[sid]
        cam = camelot(pc, scale)
        keystr = "nokey" if kfrom == "none" else f"{int(cam[:-1]):02d}{cam[-1]}-{key_label(pc, scale)}"
        if c["category"] == "Vocals" and c["subtype"] == "Chops" and note:
            keystr = f"{keystr}-{note}"
        bpmstr = f"{bpm:.0f}bpm" if bpm else "free"
        pref = SUBTYPE_PREFIX.get((c["category"], c["subtype"]), SUBTYPE_PREFIX.get(c["category"], "Smp"))
        if c["kind"] == "loop":
            pref += f"-Loop{c['bars']}"
        mm, ss = divmod(int(c["start"]), 60)
        fname = f"{pref}_{keystr}_{bpmstr}_{_safe(row['artist'], 24)}-{_safe(row['title'], 32)}_{mm}m{ss:02d}s_{sid}.wav"
        path = sample_dir(policy) / c["category"] / c["subtype"] / fname
        fade_out = 0.003 if c["kind"] == "loop" else 0.12
        clip = audio_of(c)
        write_wav(path, clip, fade_in=0.003, fade_out=fade_out)
        a = np.abs(clip).max(0)
        env = [float(x.max()) for x in np.array_split(a, 64)] if len(a) >= 64 else [0.0] * 64
        env = (np.array(env) / (max(env) + 1e-9) * 99).astype(int).tolist()
        con.execute(
            """INSERT OR REPLACE INTO samples(id, track_id, source, rendered_from, category, subtype, kind,
               start, dur, bpm, bars, key, scale, camelot, key_strength, key_from, note, chroma, centroid,
               flatness, pratio, dominance, drum_leak, loudness, quality, clap, type_probs, mood_sims,
               instrument, path, env) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, row["id"], c["source"], c["rendered_from"], c["category"], c["subtype"], c["kind"],
             c["start"], c["end"] - c["start"], bpm, c.get("bars"), PITCHES[pc], scale, cam, kstr, kfrom, note,
             json.dumps(np.round(st["chroma"], 3).tolist()), st["centroid"], st["flatness"], st["pratio"],
             c["dominance"], c["drum_leak"], st["loudness"], round(c["quality"], 3),
             c["emb"].astype(np.float16).tobytes(),
             json.dumps(dict(zip(TYPE_KEYS, np.round(c["probs"], 3).tolist()))),
             json.dumps(dict(zip(MOOD_PROMPTS, np.round(c["moods"], 4).tolist()))),
             c.get("instrument"), str(path.relative_to(C.LIB_ROOT)), json.dumps(env)))
        if c["group"] == "pad":  # found by the pad finder: "new from the pad finder" in the app
            _via(con)
            con.execute("UPDATE samples SET via='pads' WHERE id=?", (sid,))
        if c.get("grain") is not None:
            from .grain import penalty as _gp
            con.execute("UPDATE samples SET grain=?, quality_raw=? WHERE id=?",
                        (c["grain"], round(c["quality"] / _gp(c["grain"]), 3), sid))
        if c.get("chords"):
            con.execute("UPDATE samples SET chords=?, pad_still=?, pad_steady=? WHERE id=?",
                        (c["chords"], c["pad_still"], c["pad_steady"], sid))
        n += 1

    if pads_only:
        con.execute("UPDATE tracks SET pads_done=1 WHERE id=?", (row["id"],))
        con.commit()
        if verbose:
            tqdm.write(f"  {row['artist']} - {row['title']}: {n} new pads ({time.time() - t0:.0f}s)")
        return n
    vocal_frac = float(masks["vocals"].mean()) if "vocals" in masks else None
    con.execute(
        """UPDATE tracks SET status='done', error=NULL, bpm=?, bpm_conf=?, tempo_ok=?, key=?, scale=?, camelot=?,
           key_strength=?, separated=?, clean_frac=?, vocal_frac=?, processed_at=datetime('now') WHERE id=?""",
        (tk["bpm"], tk["bpm_conf"], int(tk["tempo_ok"]), PITCHES[tk["pc"]], tk["scale"], tk["camelot"],
         tk["key_strength"], int(do_sep), clean_frac, vocal_frac, row["id"]))
    con.commit()
    if verbose:
        tqdm.write(f"  {row['artist']} - {row['title']}: {n} samples, {tk['bpm']:.0f}bpm {tk['camelot']} "
                   f"(sep {t_sep - t0:.0f}s, total {time.time() - t0:.0f}s)")
    return n


def remove_track_files(con, track_id):
    for r in con.execute("SELECT path FROM samples WHERE track_id=? AND parent_id IS NULL AND category != 'Percussion'", (track_id,)):
        p = C.LIB_ROOT / r["path"]
        if p.exists():
            p.unlink()
    con.execute("DELETE FROM samples WHERE track_id=? AND parent_id IS NULL AND category != 'Percussion'", (track_id,))
    con.commit()


def _envelope(path, secs=60):
    """Loudness envelope of the first minute: 50 ms frames, 8 kHz mono. Cheap, and robust to encoding."""
    import subprocess
    out = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-t", str(secs), "-i", str(path), "-map", "0:a:0",
                          "-f", "f32le", "-ac", "1", "-ar", "8000", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(out, np.float32)
    n = len(y) // 400
    return np.sqrt((y[:n * 400].reshape(n, 400) ** 2).mean(1) + 1e-9)


def duplicate_of(con, row):
    """An already-mined track that is the same recording (same artist and title ignoring case, length within 1 s,
    and the same loudness envelope; generic titles like "III. Adagio" or "Untitled" need the audio check)."""
    cands = con.execute("""SELECT id, path FROM tracks WHERE status='done' AND id != ?
                           AND lower(trim(artist))=lower(trim(?)) AND lower(trim(title))=lower(trim(?))
                           AND abs(duration - ?) < 1""",
                        (row["id"], row["artist"] or "", row["title"] or "", row["duration"] or 0)).fetchall()
    if not cands:
        return None
    try:
        a = np.log(_envelope(row["path"]))
        for c in cands:
            b = np.log(_envelope(c["path"]))
            n = min(len(a), len(b))
            if n > 100 and np.corrcoef(a[:n], b[:n])[0, 1] > 0.97:
                return c["id"]
    except Exception:
        return None
    return None


def run(where_sql="1=1", params=(), separate_mode="auto", limit=None, reprocess=False, verbose=True,
        vocals="demucs", include_reference=False, order_by="artist, album, path", mashup=False):
    con = connect()
    status_clause = "" if reprocess else "AND status IN ('new','error')"
    if not include_reference:
        status_clause += " AND COALESCE(policy,'source') != 'reference'"
    q = f"SELECT * FROM tracks WHERE ({where_sql}) {status_clause} ORDER BY {order_by}"
    rows = con.execute(q, params).fetchall()
    if "scout" in order_by:  # ranked runs: max 3 tracks per album, 6 per artist, so no source floods the library
        per_album, per_artist, kept = {}, {}, []
        for r in rows:
            a, al = r["artist"] or "?", (r["artist"] or "?") + "|" + (r["album"] or "?")
            if per_album.get(al, 0) < 3 and per_artist.get(a, 0) < 6:
                kept.append(r)
                per_album[al] = per_album.get(al, 0) + 1
                per_artist[a] = per_artist.get(a, 0) + 1
        rows = kept
    if limit:
        rows = rows[:limit]
    print(f"{len(rows)} tracks to process (separation: {separate_mode}, vocals: {vocals})")
    total = 0
    from .memguard import yield_if_paused
    for row in tqdm(rows, desc="process"):
        yield_if_paused()  # ⏸ on the Activity page: stop after the song it's on; the rest are mined on resume
        try:
            dup = duplicate_of(con, row)
            if dup:
                remove_track_files(con, row["id"])
                con.execute("UPDATE tracks SET status='duplicate', error=? WHERE id=?", (f"same recording as track {dup}", row["id"]))
                con.commit()
                tqdm.write(f"  skip {row['artist']} - {row['title']}: same recording as track {dup}")
                continue
            tqdm.write(f"NOW {row['artist']} - {row['title']}")
            remove_track_files(con, row["id"])
            total += process_track(con, row, separate_mode, verbose, vocals, mashup=mashup)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            tqdm.write(f"  ERROR {row['path']}: {e}")
            try:  # one song's failure (a busy database included) must not end the batch
                con.rollback()
                con.execute("UPDATE tracks SET status='error', error=? WHERE id=?",
                            (f"{e}\n{traceback.format_exc()[-800:]}", row["id"]))
                con.commit()
            except Exception as e2:
                tqdm.write(f"    (not recorded: {e2})")
    print(f"done: {total} samples written")


def reclassify():
    """Re-derive category/subtype from stored CLAP probabilities (no audio work); move/rename files."""
    con = connect()
    rows = con.execute("""SELECT s.*, t.separated FROM samples s JOIN tracks t ON t.id=s.track_id""").fetchall()
    moved = dropped = 0
    from .recat import overrides
    ov = overrides()
    for r in rows:
        if r["id"] in ov or r["parent_id"] or r["category"] == "Percussion":
            continue  # manual overrides and your edits are never re-derived
        probs = json.loads(r["type_probs"])
        if r["category"] == "Vocal Atmospheres":
            group = "vocal_atmos"
        elif r["source"] == "vocals":
            group = "vocal_chop" if r["kind"] == "oneshot" else "vocal_phrase"
        else:
            group = "oneshot" if r["kind"] == "oneshot" else "long"
        c = dict(group=group, kind=r["kind"], source=r["source"])
        cat = classify(c, [probs[k] for k in TYPE_KEYS], bool(r["separated"]))
        old = C.LIB_ROOT / r["path"]
        if cat is None:
            old.unlink(missing_ok=True)
            con.execute("DELETE FROM samples WHERE id=?", (r["id"],))
            dropped += 1
            continue
        if cat == (r["category"], r["subtype"]) and c.get("instrument") == r["instrument"]:
            continue
        pref = SUBTYPE_PREFIX.get(cat, SUBTYPE_PREFIX.get(cat[0], "Smp"))
        if r["kind"] == "loop":
            pref += f"-Loop{r['bars']}"
        base = C.LIB_ROOT / "_Reference" if r["path"].startswith("_Reference/") else C.LIB_ROOT
        new = base / cat[0] / cat[1] / (pref + "_" + old.name.split("_", 1)[1])
        if old.exists() and new != old:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
        con.execute("UPDATE samples SET category=?, subtype=?, instrument=?, path=? WHERE id=?",
                    (cat[0], cat[1], c.get("instrument"), str(new.relative_to(C.LIB_ROOT)), r["id"]))
        moved += 1
    con.commit()
    print(f"reclassified {moved}, dropped {dropped}")


_COLUMNS = []


def _columns():
    """The columns a mined sample may fill (grain, chords...), added before the song's writes begin. They used to be
    added on a second connection in the middle of them, which a new library answered with "database is locked"."""
    if _COLUMNS:
        return
    from .grain import _db as gdb
    from .pads import _db as pdb
    for make in (gdb, pdb):
        c = make()
        c.commit()
        c.close()
    c = connect()
    _via(c)
    c.commit()
    c.close()
    _COLUMNS.append(1)


def _via(con):
    """samples.via = 'pads' for what the pad finder added: marked as it mines, and found again here for what it added to
    old songs (samples newer than their song's mining, not drums or edits), so a pass started before this still counts."""
    if "via" not in {r[1] for r in con.execute("PRAGMA table_info(samples)")}:
        con.execute("ALTER TABLE samples ADD COLUMN via TEXT")
    if "pads_done" in {r[1] for r in con.execute("PRAGMA table_info(tracks)")}:
        con.execute("""UPDATE samples SET via='pads' WHERE via IS NULL AND parent_id IS NULL AND category != 'Percussion'
                       AND track_id IN (SELECT id FROM tracks WHERE pads_done=1)
                       AND created_at > (SELECT processed_at FROM tracks t WHERE t.id = samples.track_id)""")
    con.commit()


def repads(limit=None):
    """Look at every already-mined song again for pads only (pads.find): new pads are added, nothing is removed.
    Songs mined with stems are separated again (their pads sit under drums); the rest use the mix. Resumable."""
    con = connect()
    if "pads_done" not in {r[1] for r in con.execute("PRAGMA table_info(tracks)")}:
        con.execute("ALTER TABLE tracks ADD COLUMN pads_done INTEGER")
        con.commit()
    rows = con.execute("""SELECT * FROM tracks WHERE status='done' AND COALESCE(policy,'source')='source'
                          AND pads_done IS NULL AND id IN (SELECT track_id FROM samples)
                          ORDER BY separated, artist, album, path""").fetchall()
    rows = rows[:limit] if limit else rows
    print(f"TASK looking for pads in {len(rows)} mined songs", flush=True)
    total = 0
    from .memguard import breathe
    for k, row in enumerate(rows, 1):
        breathe()
        try:
            total += process_track(con, row, "always" if row["separated"] else "never", verbose=False, pads_only=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"    {row['artist']} - {row['title']}: {str(e)[:100]}", flush=True)
            con.execute("UPDATE tracks SET pads_done=0 WHERE id=?", (row["id"],))
            con.commit()
        print(f"repads: {k}/{len(rows)} [{total} new pads]", flush=True)
        if k % 150 == 0:  # so the new pads show up in the app as they come in, not only at the end
            try:
                from .build import build
                print("BUILDING", flush=True)
                build()
                print("BUILD DONE", flush=True)
            except Exception as e:
                print(f"    build failed: {str(e)[:100]}", flush=True)
    if total:  # so they show up in the app
        try:
            from .build import build
            print("BUILDING", flush=True)
            build()
            print("BUILD DONE", flush=True)
        except Exception as e:
            print(f"    build failed: {str(e)[:100]}", flush=True)
    print(f"TASK DONE {total} new pads from {len(rows)} songs", flush=True)
