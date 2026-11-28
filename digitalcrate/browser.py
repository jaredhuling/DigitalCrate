"""Writes Browser.html: a self-contained, offline sample browser at the library root."""
import json
from . import config as C

ABBR = {"Vocals": "VOX", "Vocal Atmospheres": "VATM", "Pads & Atmospheres": "PAD", "Chords & Keys": "KEYS",
        "Melodies & Leads": "MEL", "Textures & Field": "TEX", "Bass & Sub": "BASS", "Percussion": "PERC", "Strings & Orchestral": "STR"}


def _ops_label(ops):
    if not ops:
        return ""
    from .edit import clean_params, _ops_tag
    o = json.loads(ops)
    if o.get("tag"):
        return o["tag"] + (f" · {o['name']}" if o.get("name") else "")
    return _ops_tag(clean_params(o)) + (f" · {o['name']}" if o.get("name") else "")


def _q(x):
    return int(round(max(0.0, min(1.0, float(x))) * 255))


def pack_partners(parts, n):
    """Goes-well-with lists as one base64 blob: per pick the sample index (2 or 4 bytes) + score, harmony, vibe
    (1 byte each, 0-1 in 1/255 steps), with offsets per sample. About a third the size of plain JSON."""
    import base64
    import struct
    w = 2 if n < 65535 else 4
    fmt = "<H3B" if w == 2 else "<I3B"
    buf, off = bytearray(), [0]
    for picks in parts:
        for j, sc, h, v in picks:
            buf += struct.pack(fmt, int(j), _q(sc), _q(h), _q(v))
        off.append(off[-1] + len(picks))
    return dict(b64=base64.b64encode(bytes(buf)).decode(), off=off, w=w)


def _pack_env(env):
    import base64
    return base64.b64encode(bytes(max(0, min(255, int(x))) for x in env)).decode()


def write_browser(d, tags, parts, kits):
    S = []
    for i, r in enumerate(d["rows"]):
        keyed = r["key_from"] != "none"
        S.append([r["id"], r["path"], r["category"], r["subtype"], r["kind"],
                  r["camelot"] if keyed else "", (r["key"] + ("m" if r["scale"] == "minor" else "")) if keyed else "",
                  round(r["bpm"]) if r["bpm"] else 0, round(r["dur"], 1), r["artist"] or "", r["title"] or "",
                  round(r["quality"], 2), tags[i], _pack_env(json.loads(r["env"] or "[]")), r["note"] or "",
                  r["instrument"] or "", r["bars"] or 0, round(r["start"]),
                  round(float(d["ref_sim"][i]), 3), d["ref_match"][i], d["genre"][i], r["track_id"],
                  r["parent_id"] or "", r["root_id"] or "", _ops_label(r["ops"])])
    from .db import connect
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS variants (sample_id TEXT, idx INTEGER, technique TEXT,
                   chain TEXT, seed INTEGER, path TEXT, PRIMARY KEY(sample_id, idx))""")
    pos = {r["id"]: i for i, r in enumerate(d["rows"])}
    V = {}
    for r in con.execute("SELECT * FROM variants ORDER BY sample_id, idx"):
        if r["sample_id"] in pos and (C.LIB_ROOT / r["path"]).exists():
            V.setdefault(pos[r["sample_id"]], []).append([r["idx"], r["technique"], r["chain"], r["path"]])
    from .recat import SUBTYPES, overrides
    ov = set(overrides())
    import time as _t
    from datetime import datetime, timezone
    tracks = {}
    for r in d["rows"]:
        if r["track_id"] not in tracks:
            ts = r["processed_at"]  # SQLite's datetime('now') is UTC
            ep = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()) if ts else 0
            added = not str(r["tpath"]).startswith(str(C.MUSIC_ROOT))
            kind = "YouTube" if "/YouTube/" in str(r["tpath"]) else ("added file" if added else "")
            tracks[r["track_id"]] = [ep, r["artist"] or "", r["title"] or "", kind, r["album"] or ""]
    # when each sample was made (minutes since the epoch, UTC): for the "added" filter
    from datetime import timezone
    born = [int(datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() // 60)
            if r["created_at"] else 0 for r in d["rows"]]
    from .lyrics import for_browser
    wl = for_browser(con, [r["id"] for r in d["rows"]])
    words = {i: t for i, t in enumerate(wl) if t}  # sung words; and which were transcribed and found wordless
    wordless = [i for i, t in enumerate(wl) if t == ""]
    loops = {}
    try:  # sustain loops: index -> [start, end, crossfade] (seconds)
        for r in connect().execute("SELECT id, loop_start, loop_end, loop_xf FROM samples WHERE loop_q > 0"):
            if r["id"] in pos:
                loops[pos[r["id"]]] = [r["loop_start"], r["loop_end"], r["loop_xf"] or 0]
    except Exception:
        pass
    chs = {}
    try:  # a sample's own chords (pads, strings): index -> chord names in order, e.g. ["Fm", "D♭"]
        for r in connect().execute("SELECT id, chords FROM samples WHERE chords IS NOT NULL"):
            if r["id"] in pos:
                names = [n for _, _, n in json.loads(r["chords"])]
                names = [n for k, n in enumerate(names) if k == 0 or n != names[k - 1]]
                if names:
                    chs[pos[r["id"]]] = names[:8]
    except Exception:
        pass
    takes = []
    try:  # alternate takes: groups of samples that are the same thing again in their song (takes.py)
        from .takes import groups as take_groups
        for g in take_groups(connect()):
            g = [pos[i] for i in g if i in pos]
            if len(g) > 1:
                takes.append(g)
    except Exception as e:
        print("takes:", str(e)[:100])
    padfound = []
    try:  # what the pad finder added ("new from the pad finder")
        from .process import _via
        cv = connect()
        _via(cv)
        padfound = [pos[r["id"]] for r in cv.execute("SELECT id FROM samples WHERE via='pads'") if r["id"] in pos]
    except Exception:
        pass
    grainy = []
    try:  # samples with audible separation grain (grain.py)
        from .grain import line
        grainy = [pos[r["id"]] for r in connect().execute("SELECT id, grain, recut FROM samples WHERE grain IS NOT NULL")
                  if r["id"] in pos and r["grain"] >= line(r["recut"])]
    except Exception:
        pass
    secs = {}
    try:  # song sections: index -> the section a sample mostly comes from (only once sections have been found)
        from .sections import by_track, of_sample
        bt = by_track()
        for i, r in enumerate(d["rows"]):
            if r["track_id"] in bt and r["start"] is not None:
                lab = of_sample(bt[r["track_id"]], r["start"], r["start"] + (r["dur"] or 0))
                if lab:
                    secs[i] = lab
    except Exception:
        pass
    data = dict(tracks=tracks, samples=S, born=born, loops=loops, chords=chs, grainy=grainy, padfound=padfound,
                takes=takes, sections=secs, words=words, wordless=wordless, partners=pack_partners(parts, len(S)), variants=V, subtypes=SUBTYPES, overridden=[i for i, r in enumerate(d["rows"]) if r["id"] in ov], kits=[dict(name=k["name"], m=k["members"]) for k in kits],
                abbr=ABBR)
    write_page(data)


def write_page(data):
    """Browser.html, plus Browser-partners.js: the goes-with picks (almost half the data) load after the list is
    showing, as a plain script so the page still works when opened straight from disk."""
    import hashlib
    data = dict(data)
    # smaller page: artist and title come from the track (the page fills them back in), reference names from a table
    S, tracks = data["samples"], data["tracks"]
    refs = data.get("refs") or sorted({s[19] for s in S if isinstance(s[19], str)})
    ri = {r: k for k, r in enumerate(refs)}
    for s in S:
        t = tracks.get(s[21]) or tracks.get(str(s[21]))
        if t and s[9] == t[1] and s[10] == t[2]:
            s[9] = s[10] = 0
        if isinstance(s[19], str):
            s[19] = ri[s[19]]
    data["refs"] = refs
    parts = data.pop("partners", None)
    if parts is not None:
        js = "window.__PARTNERS=" + json.dumps(parts, separators=(",", ":")) + ";"
        (C.LIB_ROOT / "Browser-partners.js").write_text(js, encoding="utf-8")
        data["partners_v"] = hashlib.md5(js.encode()).hexdigest()[:10]
    html = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    (C.LIB_ROOT / "Browser.html").write_text(html, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DigitalCrate</title><link rel="icon" href="studio/icon.svg">
<style>
:root{--bg:#0e1013;--panel:#15181d;--line:#242932;--ink:#d9dde3;--mute:#7d8592;--acc:#e0a458;--acc2:#7fb0c9;
--VOX:#e0a458;--VATM:#d1857a;--PAD:#7fb0c9;--KEYS:#9fc29a;--MEL:#c4a7e0;--TEX:#8f8f86;--BASS:#6c7fd1;--PERC:#d96c6c;--STR:#c9a27f}
*{box-sizing:border-box}[hidden]{display:none!important}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
font:13px/1.4 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
button{font:inherit;color:inherit;background:none;border:1px solid var(--line);border-radius:6px;padding:4px 9px;cursor:pointer}
button:hover{border-color:var(--mute)}button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}#tabP.busy{border-color:var(--acc);color:var(--acc)}
input,select{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
.app{display:grid;grid-template-columns:260px 1fr var(--dw,480px);height:100vh;position:relative}
#dsplit{position:absolute;top:0;bottom:0;right:calc(var(--dw,480px) - 3px);width:7px;cursor:col-resize;z-index:5}
#dsplit:hover,#dsplit.on{background:linear-gradient(90deg,transparent 2px,var(--acc) 2px,var(--acc) 4px,transparent 4px)}
aside,.detail{overflow:auto;padding:16px;border-right:1px solid var(--line)}.detail{border-right:0;border-left:1px solid var(--line)}
main{overflow:auto;display:flex;flex-direction:column}
h1{font-size:15px;letter-spacing:.08em;text-transform:uppercase;margin:0 0 2px}h2{font-size:11px;letter-spacing:.1em;
text-transform:uppercase;color:var(--mute);margin:18px 0 8px;font-weight:600}
.sub{color:var(--mute);font-size:12px}.chips{display:flex;flex-wrap:wrap;gap:5px}.chips button{font-size:12px;padding:3px 8px}
.top{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;gap:8px;align-items:center;z-index:2;flex-wrap:wrap}
.top input[type=search]{flex:1;min-width:200px}
.row{display:grid;grid-template-columns:30px 120px 1fr auto;gap:12px;align-items:center;padding:7px 16px;border-bottom:1px solid #1a1d23;cursor:pointer}
#list .row{content-visibility:auto;contain-intrinsic-size:auto 56px}
.row:hover{background:#13161b}.row.sel{background:#1a1f27}
.play{width:28px;height:28px;border-radius:50%;padding:0;display:grid;place-items:center;font-size:10px}
.play.playing{background:var(--acc);color:#000;border-color:var(--acc)}
svg.wave{display:block}.name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;padding:1px 5px;border-radius:4px;color:#000;margin-right:6px}
.meta{color:var(--mute);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lyr{color:var(--ink);font-style:italic}
.right{display:flex;gap:10px;align-items:center;color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums}
.key{color:var(--ink);font-weight:600;min-width:62px;text-align:right}.qbar{width:36px;height:4px;background:var(--line);border-radius:2px;overflow:hidden}
.qbar i{display:block;height:100%;background:var(--acc2)}
.id{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--mute);cursor:copy}.id:hover{color:var(--acc)}
.tag{font-size:11px;color:var(--mute);border:1px solid var(--line);border-radius:10px;padding:0 6px;margin-right:3px}
.more{margin:14px auto}.empty{padding:40px;color:var(--mute);text-align:center}
.prow{display:grid;grid-template-columns:28px 1fr auto;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid #1a1d23}
.score{font-variant-numeric:tabular-nums;font-size:12px;color:var(--acc)}
.big{font-size:16px;font-weight:600;margin:6px 0 2px}.kv{display:grid;grid-template-columns:90px 1fr;gap:3px 10px;font-size:12px;margin:10px 0}
.kv span:nth-child(odd){color:var(--mute)}.path{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--mute);word-break:break-all}
.wheel path{cursor:pointer;stroke:var(--bg);stroke-width:1.5}.wheel text{pointer-events:none;font-size:9px;fill:var(--ink)}
.tabs{display:flex;gap:6px}.kit{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 16px}
.kit h3{margin:0 0 6px;font-size:13px;display:flex;justify-content:space-between;align-items:center}
.star{border:0;padding:2px 4px;font-size:15px;color:#4a515c;line-height:1}.star.on{color:var(--acc)}.star:hover{color:var(--acc)}
.np{position:sticky;bottom:0;margin-top:auto;background:#12151a;border-top:1px solid var(--line);padding:8px 16px calc(8px + env(safe-area-inset-bottom,0px));display:flex;gap:10px;align-items:center;z-index:3}
.np .lbl{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pill{background:var(--acc);color:#000;border-color:var(--acc);font-size:12px}
.ed{border:1px solid var(--line);border-radius:8px;padding:10px;margin:10px 0;display:grid;gap:8px}
.edrow{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.edgrid{display:grid;grid-template-columns:auto 1fr auto;gap:6px 10px;align-items:center;font-size:12px}
.prov{border-left:2px solid var(--acc);padding:4px 10px;margin:8px 0;font-size:12px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10;display:grid;place-items:center}
.toast{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:7px 14px;border-radius:8px;font-size:12px;z-index:20}
.xp{border:0;padding:2px 4px;font-size:13px;color:#4a515c}.xp:hover{color:var(--acc)}.xp.done{color:var(--acc)}
.hint{font-size:11px;color:var(--mute);margin-top:6px}
.hq{display:inline-grid;place-items:center;width:17px;height:17px;padding:0;border-radius:50%;font-size:11px;font-weight:700;color:var(--mute);border:1px solid var(--line);margin-left:4px;vertical-align:middle;line-height:1}
.hq:hover{color:var(--acc);border-color:var(--acc)}
#helppop{position:fixed;z-index:60;background:#1b1f26;border:1px solid #3a414c;border-radius:10px;padding:12px 14px;font-size:12.5px;line-height:1.5;color:var(--ink);box-shadow:0 8px 30px rgba(0,0,0,.5)}
#helppop b:first-child{display:block;margin-bottom:4px;color:var(--acc)}
.artbar{background:var(--bg);display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--line);z-index:1}
.artbar input{flex:1;min-width:180px}.letters{display:flex;flex-wrap:wrap;gap:2px}.letters a{color:var(--mute);text-decoration:none;font-size:12px;padding:1px 4px;border-radius:3px}.letters a:hover{color:var(--ink);background:var(--panel)}
.art{border-bottom:1px solid #1a1d23;padding:6px 16px;scroll-margin-top:56px}.arow{display:flex;gap:8px;align-items:baseline}.tw{border:0;padding:0 4px;color:var(--mute)}
.aname{color:var(--ink);text-decoration:none;font-weight:600}.aname:hover,.alb a:hover,.song a:hover{color:var(--acc)}
.rackb{font-size:11px;padding:1px 6px;margin-left:6px}
.rackgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.rpad{border:1px solid var(--line);border-radius:8px;background:#161a20;padding:6px 8px;cursor:pointer;user-select:none;display:grid;gap:4px;min-height:84px}
.rpad:hover{border-color:var(--mute)}.rpad.hit{background:#d96c6c;border-color:#d96c6c;color:#000}.rpad.empty{opacity:.25;cursor:default}
.rtop{display:flex;justify-content:space-between;align-items:center}.rtop b{color:var(--acc);font-size:13px}.rpad.hit .rtop b{color:#000}
.rx{border:0;padding:0 3px;font-size:11px;color:#4a515c}.rx:hover{color:var(--ink)}.rpad span{font-size:12px}.rpad span i{color:var(--mute);font-style:normal;font-size:10px;margin-left:4px}
.rpad svg{width:100%;height:22px}.alb{margin:4px 0 6px 28px}.alb>a{color:var(--ink);text-decoration:none;font-size:12px;font-weight:600}.song{margin-left:14px;font-size:12px}.song a{color:var(--ink);text-decoration:none}
.cattabs{display:flex;flex-wrap:wrap;gap:0;flex-basis:100%;border-bottom:1px solid var(--line);margin:4px -16px -12px;padding:0 16px}
.cattabs button{border:0;border-bottom:2px solid transparent;border-radius:0;padding:8px 6px 7px;font-size:12.5px;white-space:nowrap;color:var(--mute)}
.cattabs button:hover{color:var(--ink)}.cattabs button.on{background:none;color:var(--ink);border-bottom-color:var(--c,var(--ink))}
.cattabs button .n{font-size:11px;opacity:.6;margin-left:4px;font-variant-numeric:tabular-nums}
.cattabs button i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--c);margin-right:5px;vertical-align:1px}
.subrow{flex-basis:100%;margin-top:12px}
</style></head><body>
<div class="app">
<aside>
  <h1 style="display:flex;align-items:center;gap:6px">DigitalCrate<span style="flex:1"></span><button id="actbtn" title="recent actions: undo any of them (⌘Z undoes the last)" hidden style="font-size:12px;padding:1px 6px">🕘</button><a id="setbtn" href="setup" title="your music and library folders" hidden style="font-size:13px;text-decoration:none">⚙</a><button id="quitbtn" title="turn DigitalCrate off (mining runs keep going)" hidden style="font-size:12px;padding:1px 6px">⏻</button></h1><div class="sub" id="count"></div>
  <h2>Key <span class="sub" id="keylbl"></span></h2>
  <svg class="wheel" id="wheel" viewBox="-110 -110 220 220" width="220" height="220"></svg>
  <div class="chips" style="margin-top:6px"><button id="nbr" class="on" title="include Camelot neighbours">+ neighbours</button><button id="clrkey">clear</button></div>
  <h2>Tempo (loops)</h2>
  <div style="display:flex;gap:6px;align-items:center"><input id="bmin" type="number" placeholder="min" style="width:70px"> – <input id="bmax" type="number" placeholder="max" style="width:70px"> <label class="sub"><input type="checkbox" id="half"> ×½ ×2</label></div>
  <h2>Genre</h2><div class="chips" id="genres"></div>
  <h2>Exclude genres</h2><div id="excl" style="display:grid;grid-template-columns:1fr 1fr;gap:2px 8px;font-size:12px"></div>
  <h2>Kind</h2><div class="chips" id="kinds"></div>
  <h2>Mood</h2><div class="chips" id="moods"></div>
  <h2>Min quality <span class="sub" id="qv"></span></h2><input id="q" type="range" min="0" max="1" step="0.05" value="0.4" style="width:100%">
</aside>
<main>
  <div class="top"><div class="tabs"><button id="tabS" class="on">Samples</button><button id="tabA" title="browse by artist, album and song">👤 Artists</button><button id="tabK" title="recommended kits and your saved sketches">Kits &amp; sketches</button><button id="tabF">★ Favorites</button><button id="tabR">🆕 Recent</button><button id="tabP" title="mining runs: what's processing, start a new run, how much of your library is mined" hidden>⚙ Processing</button><button id="tabT" title="your taste model: how accurate it is, what it has learned, what to rate next" hidden>🧠 Taste</button></div>
    <input type="search" id="search" placeholder="search artist, title, mood, instrument, id…">
    <select id="sort"><option value="div">diverse (best of each artist)</option><option value="you">for you</option><option value="vibe">today's vibe</option><option value="disc">discover</option><option value="q">best quality</option><option value="key">key</option><option value="bpm">tempo</option><option value="dur">length</option><option value="ref">closest to reference</option><option value="var">has variations</option><option value="new">newest first</option><option value="rnd">shuffle</option></select><span id="sorthq"></span><select id="since" title="only samples added recently — combine with any sort, e.g. for you"><option value="">added any time</option><option value="batch">latest run</option><option value="pads">new from the pad finder</option><option value="0.25">last 6 hours</option><option value="1">last day</option><option value="3">last 3 days</option><option value="7">last week</option><option value="30">last month</option></select><select id="secsel" hidden title="the part of the song a sample comes from (All-In-One): intros, outros and breaks are where songs are most exposed"><option value="">any section</option><option value="exposed">intro · break · outro</option><option value="intro">intro</option><option value="verse">verse</option><option value="chorus">chorus</option><option value="bridge">bridge</option><option value="inst">instrumental break</option><option value="solo">solo</option><option value="outro">outro</option></select><select id="wsel" title="vocals: with sung words, or wordless (oohs, hums, vowels) — words are transcribed by Whisper; search finds lyrics too"><option value="">words or not</option><option value="w">with words</option><option value="n">wordless</option></select>
    <button id="addsrc">＋ add source</button><button id="expbtn" title="copy what's listed into Ableton's User Library">⇩ export to Ableton</button><button id="refresh" class="pill" hidden>↻ recommendations updated</button><select id="grp" title="group by"><option value="">no grouping</option><option value="track">group by track</option><option value="type">group by type</option><option value="genre">group by genre</option></select><button id="stop">■ stop all</button>
    <div class="cattabs" id="cats" title="⌘/ctrl-click to pick several"></div><div id="subsBox" class="chips subrow" hidden></div></div>
  <div id="tbanner" class="prov" style="margin:8px 16px" hidden></div>
  <div id="list"></div>
  <div class="np" id="np" hidden></div>
  <div class="toast" id="toast" hidden></div><div id="helppop" hidden></div>
  <div id="modal" class="modal" hidden>
   <div style="background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;width:min(560px,92vw);display:grid;gap:10px" id="modalBody"></div></div>
</main>
<div id="dsplit" title="drag to resize the sample panel · double-click to reset"></div><section class="detail" id="detail"><div class="empty">Select a sample to see what it goes with.<br><br>Click an <span class="id">ID</span> to copy it — paste into Ableton's browser search to find the file instantly.</div></section>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
// partners and waveform envelopes arrive packed (see pack_partners in browser.py); unpack once here
function unpackP(p){if(Array.isArray(p))return p;const b=atob(p.b64),w=p.w,stp=w+3,out=new Array(p.off.length-1);
 for(let i=0;i<out.length;i++){const a=[];for(let k=p.off[i];k<p.off[i+1];k++){const o=k*stp;
  const j=w===2?(b.charCodeAt(o)|b.charCodeAt(o+1)<<8):(b.charCodeAt(o)|b.charCodeAt(o+1)<<8|b.charCodeAt(o+2)<<16|b.charCodeAt(o+3)<<24)>>>0;
  a.push([j,Math.round(b.charCodeAt(o+w)/255*1000)/1000,Math.round(b.charCodeAt(o+w+1)/255*100)/100,Math.round(b.charCodeAt(o+w+2)/255*100)/100])}out[i]=a}return out}
const S=D.samples, AB=D.abbr;
// fill in what the build left out to keep the page small (artist 9, title 10 from the track 21; reference name 19)
S.forEach(s=>{if(s[9]===0){const t=D.tracks[s[21]]||[];s[9]=t[1]||'';s[10]=t[2]||''}if(D.refs&&typeof s[19]==='number')s[19]=D.refs[s[19]]});
// goes-with picks: in Browser-partners.js, loaded once the list is up (older pages carry them inline)
const P=D.partners?unpackP(D.partners):new Array(S.length);let P_READY=!!D.partners,P_FAIL=false;
function loadPartners(){if(P_READY)return;const sc=document.createElement('script');sc.src='Browser-partners.js?v='+(D.partners_v||'');
 sc.onload=()=>{const all=unpackP(window.__PARTNERS);delete window.__PARTNERS;for(let k=0;k<all.length;k++)if(P[k]===undefined)P[k]=all[k];P_READY=true;
  if(st.sel!=null&&$('goload'))select(st.sel)};
 sc.onerror=()=>{P_READY=true;P_FAIL=true;if(st.sel!=null&&$('goload'))select(st.sel)};document.body.appendChild(sc)}
// ---------- "?" explainers for the less obvious features: hq('key') renders the button, HELP holds the text
const HELP={
 goes:['Goes well with','Samples that sit well with this one. Each is scored on <b>key</b> (Camelot wheel plus the notes the two actually use), <b>tempo</b> (for loops), whether their <b>roles</b> fit in an arrangement (a pad under a vocal), and how alike they <b>sound</b>. You get the best 24 overall plus the best few of every other category; the chips show one category at a time. <b>⧉</b> plays the pair together, <b>💾</b> saves the pair as a sketch.'],
 sort:['Sort orders','<b>diverse</b>: the best of each artist in turn. <b>for you</b>: what the taste model (trained on your ★, ✕ and listening) rates highest. <b>today\'s vibe</b>: the same, weighted to your last few hours. <b>discover</b>: what the model is least sure about, to widen what it knows. The <b>added</b> menu next to it narrows any sort to recent samples, so <i>for you</i> + <i>latest run</i> shows the best of what the last mining run found.'],
 sound:['Search by sound','<b>≈ by sound</b>: describe a sound in words and press Enter. Commas mean AND (“female voice, distant, rainy”); <b>-word</b> pushes away from something (“-drums”). <b>🎧 feels like…</b>: give a YouTube link, a file or “artist – title” and get the samples that feel most like it. Searches match timbre and mood, not key or tempo.'],
 project:['Project key & tempo','Set the key and tempo of the track you\'re making. Previews (with the box ticked), the sketchpad and exports are retuned by the smallest shift that fits, and loops (and phrases with a reliable tempo) are stretched to the tempo. <b>🔗 Live</b> follows Ableton Live\'s tempo over Link.'],
 sketch:['Sketchpad','Layer up to 8 samples in time. Loops lock to the bar; other clips repeat every N bars (⋯ to change).<br><b>Amber lines</b>: the project\'s bars and beats as that lane plays. <b>White ticks</b>: the clip\'s own attacks (tall = strong). <b>▼</b>: the attack placed on the beat.<br><b>no pulse</b>: a pad or texture with nothing to line up; it plays from its start. <b>pulse ≈ N bpm</b>: a steady rhythm; <b>⟷ match tempo</b> stretches it so every attack stays on the grid.<br>Drag a waveform to use part of it, <b>⌥-drag</b> to slide it in time, <b>↺ re-align</b> to fit the selection to the grid. Faders are relative: every lane starts equally loud at 0 dB.<br><b>⇩ stems</b>: each lane as its own WAV, same length from bar 1, so they line up in Live.'],
 pads:['Pads','Your sample cut at its syllables (or notes), one slice per pad, in order, like an MPC. Tap keys <b>1–4 · Q–R · A–F · Z–V</b> to play the pieces back in a new order and rhythm.<br><b>● record</b> loops 1–4 bars with a click: play pads to lay down a pattern (it overdubs, and quantises if you like). <b>▶ pattern</b> plays it; <b>save pattern</b> keeps it as a new sample. <b>chops → Drum Rack</b> sends every slice to Ableton as a playable rack.'],
 chords:['Chord suggestions','Progressions picked to suit this sample: every chord is scored on how much of what the sample plays falls on its notes (and penalized for clashing a semitone away), then whole sequences are chosen for good movement and smooth voice leading. The sample\'s mood picks the flavour (soulful = 7ths/9ths, dark = minor 9ths, ethereal = sus/add9).<br>If the sample has chords of its own, suggestions change where it does: <b>follows</b> enriches its chords in another register, <b>reharmonized</b> swaps in chords that still contain what it plays.<br>On the keyboard, <span style="color:#7fb0c9">blue</span> = bass, <span style="color:#e0a458">amber</span> = the chord. <b>bass</b> adds a bassline under the chords: held roots, root &amp; fifth, an 8th-note pulse, syncopated R&amp;B or a walking line (✓ marks the one suited to this sample). ⇩ MIDI for your own instruments (chords and bass on separate tracks); ＋ sketch renders the pad, and the bass as its own lane.'],
 rack:['Drum Rack','Every drum hit cut from this song (or album/artist), kicks first, then snares, hats, toms, cymbals and combinations. Keys <b>1–4 · Q–R · A–F · Z–V</b> play the current page. ✕ drops a pad before export. The type names come from automatic drum labelling, which is often wrong; trust your ears.'],
 suggest:['Suggested edits','DigitalCrate tries a dozen edits that suit this kind of sound (gentle lifts, natural tuning and a little space for voices; an octave down, darker, washed out or slower for pads and textures) and renders each one. Your taste model then judges how each <i>result</i> sounds: whether it sounds more like what you star than the original does, with a cost for losing what the sample is. You get its three best, from three different kinds of edit, plus one <b>wildcard</b> picked at random. <b>use</b> sets the editor to it (then adjust anything). <b>👍 / 👎</b> rate it, with an optional reason: <i>too much</i> or <i>too subtle</i> tune how strong that kind of edit is made, <i>sounds processed</i> steers away from that move (only your ears can hear artifacts), <i>wrong mood</i> just counts against it. You can rate your own edits too (<i>rate this edit</i> under the preview button). After about 8 ratings a small edit model learns from how each rated edit changed the sound. The Taste page shows whether its picks beat the wildcard, so you can tell if it really helps. It judges how a result sounds, not processing artifacts, so every move uses the engines you rated best in blind tests.'],
 tune:['Tune to','Pulls a vocal toward a key by gently changing its speed, tape-style (nothing is resynthesised). <b>Strength</b>: how far each note moves. <b>Glide</b>: how slowly it moves (low = the hard Auto-Tune effect). <b>Detune</b> and <b>drift</b> add back human looseness.'],
 galaxy:['Galaxy','Every sample on a map by sound: neighbours sound alike, and clusters are families of sounds (distances between far-apart clusters mean little). Hover to hear, click to open, wheel to zoom. <b>Show taste</b> colours by how much the taste model thinks you\'ll like each one.'],
 crate:['Crate','A daily dig: samples the taste model rates highest that you haven\'t heard yet, plus wildcards. ★ and ✕ teach it; a fresh crate appears each day and never repeats.'],
 scout:['Scout','Searches YouTube and listens to a minute of each result (from the middle of long videos), scored for <b>🎤 raw singing</b>, <b>🌫 pads & textures</b>, or <b>🧭 your styles</b> (the Discogs styles of songs you like). Playlists, DJ mixes and music videos are skipped.<br><br><b>▶</b> plays its three best moments; the title opens YouTube at the best one. <b>🔭 more</b> listens through that video\'s channel and a search built from its title: a channel with one great acapella usually has more. <b>✕</b> and <b>add source</b> teach the ranking (scores are within each kind of search). <b>dig deeper</b> repeats a search further down YouTube\'s results. With <b>daily finds</b> on, it runs a few searches by itself once a day and shows them at the top. Nothing enters the library until you press add source.'],
 kits:['Kits & sketches','<b>Kits</b> are built automatically: a few samples in compatible keys whose sounds and roles fit together. Open one in the sketchpad (🎛), play it together, export it, or make a Drum Rack. <b>Your sketches</b> are the ones you saved, including pairs saved with 💾.'],
};
const hq=k=>`<button class="hq" data-help="${k}" title="what is this?">?</button>`;
document.addEventListener('DOMContentLoaded',()=>{const x=document.getElementById('sorthq');if(x)x.outerHTML=hq('sort')});
document.addEventListener('click',e=>{const b=e.target.closest('[data-help]'),pop=$('helppop');
 if(!b){if(pop&&!e.target.closest('#helppop'))pop.hidden=true;return}e.preventDefault();e.stopPropagation();
 const [t,txt]=HELP[b.dataset.help]||['',''];pop.innerHTML=`<b>${t}</b><div>${txt}</div>`;pop.hidden=false;
 const r=b.getBoundingClientRect(),w=Math.min(360,window.innerWidth-24);pop.style.width=w+'px';
 pop.style.left=Math.max(12,Math.min(window.innerWidth-w-12,r.left-w/2))+'px';const below=r.bottom+8+pop.offsetHeight<window.innerHeight;
 pop.style.top=(below?r.bottom+8:Math.max(12,r.top-8-pop.offsetHeight))+'px'},true);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('helppop'))$('helppop').hidden=true});

S.forEach(s=>{if(typeof s[13]==='string'){const b=atob(s[13]);const e=new Array(b.length);for(let k=0;k<b.length;k++)e[k]=b.charCodeAt(k);s[13]=e}});
const F={id:0,path:1,cat:2,sub:3,kind:4,cam:5,key:6,bpm:7,dur:8,artist:9,title:10,q:11,tags:12,env:13,note:14,inst:15,bars:16,start:17,ref:18,refm:19,genre:20,tid:21,parent:22,root:23,ops:24};
const st={tracks:null,subs:new Set(),rel:'go',genres:new Set(),open:new Set(),cats:new Set(),kinds:new Set(),moods:new Set(),key:null,nbr:true,tab:'S',sel:null,shown:200};
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const url=p=>p.split('/').map(encodeURIComponent).join('/');
const col=c=>`var(--${AB[c]})`;
// one <path> per waveform (not a <rect> per bar: 200 rows made ~8,000 elements), cached per envelope and size
const WAVES=new WeakMap();
function wave(env,w=120,h=26,c='#7d8592'){if(!env||!env.length)return'';let m=WAVES.get(env);if(!m){m=new Map();WAVES.set(env,m)}const k=w+'|'+h;
 let d=m.get(k);if(d==null){const bw=w/env.length,bwd=(bw*.7).toFixed(1);d=env.map((v,i)=>{const hh=Math.max(1,v/99*h);return`M${(i*bw).toFixed(1)} ${((h-hh)/2).toFixed(1)}h${bwd}v${hh.toFixed(1)}h-${bwd}z`}).join('');m.set(k,d)}
 return `<svg class="wave" width="${w}" height="${h}"><path d="${d}" fill="${c}"/></svg>`}
// ---------- favourites
const FAV=new Map(); let SERVED=location.protocol.startsWith('http');
function lsGet(){try{return JSON.parse(localStorage.getItem('atlasFavs')||'[]')}catch(e){return[]}}
function lsSet(){try{localStorage.setItem('atlasFavs',JSON.stringify([...FAV.values()]))}catch(e){}}
async function loadFavs(){let list=[];if(SERVED){try{list=await (await fetch('api/favs')).json()}catch(e){SERVED=false}}
 if(!SERVED)list=lsGet();list.forEach(f=>FAV.set(f.path,f));render()}
async function toggleFav(path,id,label){const on=!FAV.has(path);
 if(on)FAV.set(path,{path,sample_id:id,label,added_at:new Date().toISOString()});else FAV.delete(path);
 if(SERVED){try{const r=await fetch('api/fav',{method:'POST',body:JSON.stringify({path,id,label,on})});if(!r.ok)throw 0}catch(e){SERVED=false}}
 if(!SERVED)lsSet();document.querySelectorAll(`[data-fav="${CSS.escape(path)}"]`).forEach(b=>b.classList.toggle('on',on));if(st.tab==='F')render()}
const star=(path,id,label)=>`<button class="star${FAV.has(path)?' on':''}" data-fav="${esc(path)}" data-fid="${esc(id||'')}" data-flabel="${esc(label||'')}" title="favourite">★</button>`;
document.addEventListener('click',e=>{const b=e.target.closest('[data-fav]');if(!b)return;e.stopPropagation();toggleFav(b.dataset.fav,b.dataset.fid,b.dataset.flabel)},true);
// ---------- taste
let TASTE={score:{},discover:{},vibe:{},disliked:new Set(),n:0};
// scores come keyed by sample id (?ids=1, a quarter of the size); the page keeps them keyed by path
const byIds=(r,k)=>{const o={};if(!r.ids)return r[k]||{};r.ids.forEach((id,j)=>{const i=BYID.get(id);if(i!=null)o[S[i][F.path]]=r[k][j]});return o};
async function loadTaste(){if(!SERVED)return;try{const [a,b]=await Promise.all([fetch('api/taste?ids=1').then(r=>r.json()),fetch('api/taste?recent=1&ids=1').then(r=>r.json())]);
 const first=!TASTE.loaded;
 if(a.served)fetch('api/reco/served',{method:'POST',body:JSON.stringify({token:a.served})}).catch(()=>{});  // logged once: what "for you" and discover were served
 // what you're looking at, ranked before and after: "updated" only when the top of the list would really change
 const top=()=>{try{return st.tab==='S'?filtered().slice(0,30).join(','):''}catch(e){return''}},before=first?'':top();
 TASTE={loaded:true,score:byIds(a,'score'),discover:byIds(a,'discover'),vibe:byIds(b,'score'),disliked:new Set([...(a.disliked||[]),...TASTE.disliked]),n:a.n_labels||0};
 if(first)render();else if(before&&top()!==before){$('refresh').hidden=false;const c=$('count');if(c&&!c.textContent.includes('taste'))render.countOnly&&render.countOnly()}}catch(e){}}
// ---------- deleting samples (served only): files go to _data/trash, undo brings them back
let GONE=new Set();
const trashBtn=i=>SERVED?`<button class="xp" data-del="${i}" title="delete this sample (you can undo)">🗑</button>`:'';
async function delSamples(idx,what){idx=idx.filter(i=>!GONE.has(i));if(!idx.length){toast('nothing to delete');return}
 let r;try{r=await (await fetch('api/trash/delete',{method:'POST',body:JSON.stringify({ids:idx.map(i=>S[i][F.id])})})).json()}catch(e){r={error:'server not reachable'}}
 if(r.error){toast('delete failed: '+r.error);return}
 const ok=new Set(r.deleted),gone=idx.filter(i=>ok.has(S[i][F.id]));
 gone.forEach(i=>{GONE.add(i);FAV.delete(S[i][F.path]);const a=players.get(i);if(a){a.pause();players.delete(i)}});
 const y=document.querySelector('main').scrollTop;render();document.querySelector('main').scrollTop=y;
 if(st.sel!=null){if(GONE.has(st.sel)){st.sel=null;$('detail').innerHTML='<div class="empty">Deleted.</div>'}else select(st.sel)}
 const t=$('toast');t.innerHTML=`🗑 deleted ${esc(what)} <button id="undel">undo</button>`;t.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>t.hidden=true,10000);
 let undone=false;const restore=async()=>{if(undone)return;undone=true;t.textContent='restoring…';try{await fetch('api/trash/restore',{method:'POST',body:JSON.stringify({ids:gone.map(i=>S[i][F.id])})});
  gone.forEach(i=>GONE.delete(i));await loadFavs();toast(`restored ${gone.length}`)}catch(e){toast('undo failed')}};
 $('undel').onclick=restore;if(window.actPush)actPush(`deleted ${what}`,restore)}
document.addEventListener('click',e=>{const b=e.target.closest('[data-del],[data-delsong]');if(!b)return;e.stopPropagation();e.preventDefault();
 if(b.dataset.del!=null){const i=+b.dataset.del;delSamples([i],`${S[i][F.sub]} from ${S[i][F.title]}`);return}
 const all=trk(+b.dataset.delsong),keep=all.filter(i=>FAV.has(S[i][F.path])||S[i][F.parent]||(D.variants[i]||[]).some(v=>FAV.has(v[3]))),go=all.filter(i=>!keep.includes(i));
 const s=S[all[0]];if(!go.length){toast('only favourites and edits left in this song');return}
 if(b.dataset.armed!=='1'){b.dataset.armed='1';b.textContent=`🗑 delete ${go.length} sample${go.length>1?'s':''}${keep.length?` (keeping ${keep.length} ★/edits)`:''}? click again`;setTimeout(()=>{if(b.isConnected){b.dataset.armed='';b.textContent='🗑'+(b.closest('h2')?" delete this song's samples":'')}},4000);return}
 delSamples(go,`${go.length} samples from ${s[F.artist]} — ${s[F.title]}`)},true);
// ⏻ turns the local server off (served only); the app turns it back on
if(SERVED){$('setbtn').hidden=$('quitbtn').hidden=false;
 $('quitbtn').onclick=async e=>{const b=e.currentTarget;if(b.dataset.armed!=='1'){b.dataset.armed='1';b.textContent='⏻ turn off?';setTimeout(()=>{b.dataset.armed='';b.textContent='⏻'},3000);return}
  players.forEach(a=>a.pause());try{await fetch('api/quit',{method:'POST',body:'{}'})}catch(err){}
  document.body.innerHTML='<div style="font:16px system-ui;color:#d9dde3;background:#0e1013;position:fixed;inset:0;display:grid;place-items:center;text-align:center"><div><h2>DigitalCrate is off</h2><p style="color:#7d8592">Mining runs you started keep going in the background.<br>Open the DigitalCrate app to turn it back on. You can close this window.</p></div></div>'}}
let refitT=null;function scheduleRefit(){clearTimeout(refitT);refitT=setTimeout(loadTaste,4000)}
function sendEvent(path,type,value,id){if(!SERVED)return;fetch('api/event',{method:'POST',body:JSON.stringify({path,type,value,id})}).catch(()=>{});scheduleRefit()}
const listenStart=new Map();
function beginListen(key,path){listenStart.set(key,{t:performance.now(),path})}
function endListen(key,audio){const s=listenStart.get(key);if(!s)return;listenStart.delete(key);
 const secs=(performance.now()-s.t)/1000,dur=(audio&&isFinite(audio.duration))?audio.duration:8,frac=Math.min(1,secs/dur);sendEvent(s.path,'listen',+frac.toFixed(2))}
function toggleDislike(path,id){const on=!TASTE.disliked.has(path);on?TASTE.disliked.add(path):TASTE.disliked.delete(path);sendEvent(path,'dislike',on?1:0,id);
 document.querySelectorAll(`[data-nope="${CSS.escape(path)}"]`).forEach(b=>{b.classList.toggle('on',on);const r=b.closest('.row');if(r&&on)r.style.opacity=.35;else if(r)r.style.opacity=''});
 if(on&&NP&&NP.path===path)stopAll();drawNP()}
const nope=(path,id)=>`<button class="star${TASTE.disliked.has(path)?' on':''}" data-nope="${esc(path)}" data-nid="${esc(id||'')}" title="not for me" style="font-size:12px">✕</button>`;
document.addEventListener('click',e=>{const b=e.target.closest('[data-nope]');if(!b)return;e.stopPropagation();toggleDislike(b.dataset.nope,b.dataset.nid)},true);
// ---------- now playing
let NP=null;
function setNP(path,id,label,i){NP={path,id,label,i};drawNP()}
function drawNP(){const el=$('np');if(!NP||!(players.size||(ED&&ED.P))){el.hidden=true;return}el.hidden=false;
 el.innerHTML=`<button class="play playing" id="npstop">■</button><div class="lbl"><span class="sub">now playing</span> · ${esc(NP.label)}${window.SK&&SK.playing?' <span class="sub" style="color:var(--acc)">· with the sketch</span>':''}</div>
 ${NP.edit?'<span class="sub">a preview: use it or save it to keep it</span>':`${star(NP.path,NP.id,NP.label)}${nope(NP.path,NP.id)}${xp(NP.path)}`}${NP.i!=null?`<button id="npshow">show</button>`:''}${NP.edit?'':'<span class="sub">F ★ · X ✕</span>'}`;
 $('npstop').onclick=()=>{stopAll()};if($('npshow'))$('npshow').onclick=()=>select(NP.i,'go')}
// F / X / C (and the rest of the keyboard) live in studio.js: they act on the selected sample, else the playing one
const lbl=i=>`${S[i][F.artist]} — ${S[i][F.title]} · ${S[i][F.sub]}${S[i][F.cam]?' · '+S[i][F.cam]:''}`;
// ---------- provenance
function provHTML(i){const s=S[i];let h='';
 if(s[F.parent]){const p=BYID.get(s[F.parent]),r=BYID.get(s[F.root]);
  h+=`<div class="prov">✎ edit · <b>${esc(s[F.ops])}</b><br>derived from ${p!=null?`<a href="#" data-go2="${p}">${esc(S[p][F.sub])} · ${esc(S[p][F.artist])} — ${esc(S[p][F.title])} (${S[p][F.id]})</a>`:s[F.parent]}
  ${r!=null&&s[F.root]!==s[F.parent]?`<br>original: <a href="#" data-go2="${r}">${esc(S[r][F.sub])} (${S[r][F.id]})</a>`:''}</div>`}
 const kids=S.map((t,j)=>t[F.parent]===s[F.id]?j:-1).filter(j=>j>=0);
 if(kids.length)h+=`<div class="prov">your edits of this sample (${kids.length}):${kids.map(j=>`<div class="prow"><button class="play" data-play="${j}">▶</button><div class="name">${esc(S[j][F.ops])} · ${S[j][F.dur]}s ${S[j][F.cam]||''}</div><div style="display:flex;gap:6px">${star(S[j][F.path],S[j][F.id],lbl(j))}<button data-go="${j}">→</button></div></div>`).join('')}</div>`;
 return h}
// ---------- editor
let ED=null;const AC=new (window.AudioContext||window.webkitAudioContext)();
function edStop(){const P=ED&&ED.P;if(!P)return;clearTimeout(P.timer);const now=AC.currentTime;
 P.voices.forEach(v=>{try{v.g.gain.cancelScheduledValues(now);v.g.gain.setValueAtTime(v.g.gain.value,now);v.g.gain.linearRampToValueAtTime(0,now+0.02);v.src.stop(now+0.03)}catch(e){}});
 ED.P=null;setTimeout(()=>{typeof drawNP==='function'&&drawNP();typeof edButtons==='function'&&edButtons();edPaint()},0)}
async function openEditor(i){const box=$('editor');if(!box)return;if(!box.hidden){box.hidden=true;edStop();return}box.hidden=false;
 if(!SERVED){box.innerHTML='<div class="sub">Editing needs the local server: run <code>python -m digitalcrate serve</code> and open http://localhost:8765</div>';return}
 const isDrum=S[i][F.cat]==='Percussion';  // drums get a drum panel, and tape pitch by default (like a sampler)
 box.innerHTML=`<canvas id="edc" style="width:100%;height:120px;background:#101317;border-radius:6px;cursor:crosshair"></canvas>
 <div class="sub" id="edsel">drag to select · double-click selects one syllable/note · loading…</div>
 <div class="edrow"><button id="edplay">▶ selection</button><label class="sub"><input type="checkbox" id="edloop" checked> loop</label>
 <label class="sub"><input type="checkbox" id="edsnap" checked> snap to syllables</label><label class="sub" id="edbarsl" title="bar lines counted from where the selection starts (the line marked 2 is two bars on), and while you drag, the selection's length sticks at 1, 2, 3… bars (the sample's tempo, or the project's). Hold ⌥ to move freely"><input type="checkbox" id="edbars" checked> bars</label><button id="edall">select all</button><button id="edzoom">🔍 zoom to selection</button><span class="sub">wheel = zoom</span></div>
 <div class="edgrid"><span>Stretch</span><input type="range" id="edst" min="0.5" max="4" step="0.05" value="1"><span id="edstv">1×</span>
 <span>Pitch</span><input type="range" id="edpi" min="-12" max="12" step="1" value="0"><span id="edpiv">0 st</span>
 <span>Loop crossfade</span><input type="range" id="edxf" min="0" max="1000" step="10" value="20"><span id="edxfv">20 ms</span>
 <span title="a gentle low-pass: lower is darker">Tone</span><input type="range" id="edtone" min="0" max="100" step="1" value="100"><span id="edtonev">open</span></div>
 ${isDrum?`<div class="edgrid" id="eddrum" style="margin-top:-2px"><span title="sharper attack: a transient shaper">Punch</span><input type="range" id="edpunch" min="0" max="100" step="1" value="0"><span id="edpunchv">off</span>
 <span title="shortens the tail with a natural fade after the hit">Decay</span><input type="range" id="eddecay" min="0" max="100" step="1" value="0"><span id="eddecayv">natural</span>
 <span title="saturation: rounder and louder, then crunchy">Drive</span><input type="range" id="eddrive" min="0" max="100" step="1" value="0"><span id="eddrivev">off</span>
 <span title="removes rumble and boom below this">Low cut</span><input type="range" id="edlow" min="0" max="400" step="5" value="0"><span id="edlowv">off</span></div>`:''}
 <div class="edgrid" style="margin-top:-2px"><span>Fade in</span><input type="range" id="edfi" min="0" max="2000" step="5" value="10"><span id="edfiv">10 ms</span>
 <span id="edfol">Fade out</span><input type="range" id="edfo" min="0" max="2000" step="5" value="40"><span id="edfov">40 ms</span></div>
 <div class="edrow sub"><label title="Rubber Band's formant mode: keeps a voice's character on big shifts, but scored lowest in your blind shootout"><input type="checkbox" id="edfm"> keep formants</label><label title="pitch and speed change together, like a turntable or tape (Re-Pitch: the best-rated engine for pitch in your blind test)"><input type="checkbox" id="edtape"${isDrum?' checked':''}> tape</label><label><input type="checkbox" id="edrev"> reverse</label>
 <span title="Fade in: start of playback. Fade out: end of a one-shot, or when you stop. Loop crossfade: between loop passes.">ⓘ which fade applies when</span></div>
 <div class="edrow"><button id="edprev">▶ preview edit</button><button id="edreset" title="put every setting and the selection back to how they started">↺ reset</button><input id="edname" placeholder="name (optional)" style="flex:1;min-width:120px"><button id="edsave" class="pill">save as new</button></div>
 <div class="sub" id="edmsg">original is never modified · the new sample remembers where it came from</div>`;
 ED={i,sel:null,onsets:[],buf:null,P:null,peaks:null,base:null,view:null};
 const path=S[i][F.path];
 const [ab,on]=await Promise.all([fetch(url(path)).then(r=>r.arrayBuffer()),fetch('api/onsets?path='+encodeURIComponent(path)).then(r=>r.json()).catch(()=>({onsets:[]}))]);
 ED.buf=await AC.decodeAudioData(ab);ED.onsets=on.onsets||[];ED.sel=[0,ED.buf.duration];edDraw();
 const c=$('edc'),tx=e=>edT(e.offsetX,c.clientWidth);
 c.addEventListener('wheel',e=>{e.preventDefault();const [v0,v1]=edView(),t=tx(e),f=e.deltaY>0?1.25:0.8,d=ED.buf.duration;
  let n0=t-(t-v0)*f,n1=t+(v1-t)*f;if(n1-n0>=d){n0=0;n1=d}if(n1-n0<0.02)return;edZoom([Math.max(0,n0),Math.min(d,n1)])},{passive:false});
 const snap=t=>{if(!$('edsnap').checked||!ED.onsets.length)return t;const n=ED.onsets.reduce((a,b)=>Math.abs(b-t)<Math.abs(a-t)?b:a);return Math.abs(n-t)<0.2?n:t};
 let down=null,drag=null;c.onmousedown=e=>{drag=edHandleAt(e);if(drag)return;
  // grabbing an edge moves just that edge: anchor on the opposite one and let the normal drag logic extend from it
  const edge=edEdgeAt(e);if(edge){down=edge==='a'?ED.sel[1]:ED.sel[0];ED.anchor=down;return}
  down=snap(tx(e));ED.anchor=down;ED.sel=[down,down];edDraw()};
 c.onmousemove=e=>{if(drag){const t=tx(e),[a,b]=ED.sel;edSetEnv(drag,Math.max(0,(drag==='in'?t-a:drag==='xin'?a-t:b-t))*1000);return}
  c.style.cursor=down!=null||edHandleAt(e)||edEdgeAt(e)?'ew-resize':'crosshair';if(down==null)return;let t=tx(e);
  // the length sticks at whole bars (1, 2, 3…) when the edge comes within 8 px of one; ⌥ lets it move freely
  ED.stuck=0;const bar=edBar();if(bar&&!e.altKey&&$('edbars').checked){const [v0,v1]=edView(),tol=Math.min(0.2*bar,8*(v1-v0)/c.clientWidth),n=Math.round(Math.abs(t-down)/bar);
   if(n>=1&&Math.abs(Math.abs(t-down)-n*bar)<=tol){const tt=down+Math.sign(t-down)*n*bar;if(tt>=0&&tt<=ED.buf.duration+1e-6){t=Math.min(ED.buf.duration,tt);ED.stuck=n}}}
  ED.sel=[Math.min(down,t),Math.max(down,t)];edDraw()};
 window.addEventListener('mouseup',()=>{if(drag){drag=null;['edxf','edfi','edfo'].forEach(id=>$(id).dispatchEvent(new Event('change')));return}
  if(down==null)return;down=null;ED.anchor=null;if(!ED.stuck)ED.sel=[snap(ED.sel[0]),snap(ED.sel[1])];  // a whole-bar length stays exactly that
  if(ED.sel[1]-ED.sel[0]<0.03)ED.sel=[0,ED.buf.duration];
  // fades set for a longer selection would swallow a short one (it'd be all fade): back to the defaults
  const len=ED.sel[1]-ED.sel[0];[['edfi',10],['edfo',40],['edxf',20]].forEach(([id,def])=>{const el=$(id);if(+el.value/1000>len*0.25){el.value=Math.min(def,Math.floor(len*250/5)*5);el.dispatchEvent(new Event('input'))}});
  edDraw();edChanged()},{once:false});
 c.ondblclick=e=>{const t=tx(e),b=[0,...ED.onsets,ED.buf.duration];let k=b.findIndex(x=>x>t);if(k<1)k=1;ED.sel=[b[k-1],b[k]];edDraw();
 if(ED.P&&ED.P.loop)edChanged();else edPlaySel()};
 $('edbars').onchange=()=>edDraw();
 $('edplay').onclick=edToggleSel;$('edzoom').onclick=()=>{const d=ED.buf.duration;ED.view&&(ED.view[1]-ED.view[0])<d-1e-3?edZoom(null):edZoom('sel')};$('edall').onclick=()=>{ED.sel=[0,ED.buf.duration];edDraw();edChanged()};
 ['edst','edpi','edfm','edrev','edfi','edfo','edxf','edtape','edtone','edpunch','eddecay','eddrive','edlow'].forEach(id=>$(id)&&$(id).addEventListener('change',edChanged));
 if($('eddrum')){const lab={edpunch:v=>v?v+'%':'off',eddecay:v=>v?decayS(v).toFixed(2)+' s':'natural',eddrive:v=>v?v+'%':'off',edlow:v=>v?v+' Hz':'off'};
  Object.entries(lab).forEach(([id,f])=>$(id).addEventListener('input',()=>$(id+'v').textContent=f(+$(id).value)))}
 $('edtone').addEventListener('input',()=>{const v=+$('edtone').value;$('edtonev').textContent=v>=100?'open':(toneHz(v)/1000).toFixed(1)+' kHz'});
 $('edtape').addEventListener('change',()=>{if($('edtape').checked)$('edfm').checked=false});$('edfm').addEventListener('change',()=>{if($('edfm').checked)$('edtape').checked=false});
 $('edloop').addEventListener('change',()=>{if(ED.P){ED.P.loop=$('edloop').checked;if(!ED.P.loop){const last=ED.P.segs[ED.P.segs.length-1];ED.P.end=last?last.t0+last.len:AC.currentTime}}});
 $('edxf').oninput=()=>{$('edxfv').textContent=$('edxf').value+' ms';if(ED&&ED.P&&ED.P.mode==='sel'&&ED.P.cur)ED.P.cur.xf=+$('edxf').value/1000};
 $('edfi').addEventListener('input',()=>$('edfiv').textContent=$('edfi').value+' ms');$('edfo').addEventListener('input',()=>$('edfov').textContent=$('edfo').value+' ms');
 window.addEventListener('resize',()=>{if(ED&&ED.buf)edDraw()});
 ['edxf','edfi','edfo'].forEach(id=>$(id).addEventListener('input',()=>{edDraw();const P=ED.P;if(P&&P.mode==='sel'&&P.cur){P.cur.fin=+$('edfi').value/1000;P.cur.fout=+$('edfo').value/1000}}));
 const foMode=()=>{const L=$('edloop').checked;$('edfol').textContent=L?'Fade out (on stop)':'Fade out';
  [$('edfol'),$('edfo'),$('edfov')].forEach(x=>x.style.opacity=L?.55:1);$('edfo').title=L?'While looping, passes use the loop crossfade; this fade applies when you stop or turn loop off.':''};
 foMode();$('edloop').addEventListener('change',()=>{foMode();edDraw()});
 $('edst').oninput=()=>$('edstv').textContent=(+$('edst').value).toFixed(2)+'×';
 $('edpi').oninput=()=>$('edpiv').textContent=(+$('edpi').value>0?'+':'')+$('edpi').value+' st';
 $('edprev').onclick=edPreview;$('edsave').onclick=edSave;$('edreset').onclick=edReset}
// start over: every control back to its starting value (including ones studio.js adds), whole sample selected, zoom out.
// loop / snap / the name are preferences, not edits, so they stay
function edReset(){if(!ED||!ED.buf)return;$('editor').querySelectorAll('input,select').forEach(el=>{if(['edloop','edsnap','edbars','edname'].includes(el.id))return;
 if(el.type==='checkbox')el.checked=el.defaultChecked;else if(el.tagName==='SELECT')el.selectedIndex=Math.max(0,[...el.options].findIndex(o=>o.defaultSelected));else el.value=el.defaultValue;
 el.dispatchEvent(new Event('input'));if(el.tagName==='SELECT')el.dispatchEvent(new Event('change'))});if($('tnrep'))$('tnrep').textContent='';  // menus redraw their panels (plugin controls, tuning report)
 ED.sugg=null;document.querySelectorAll('[data-sgk]').forEach(r=>r.style.background='');
 ED.sel=[0,ED.buf.duration];edZoom(null);edDraw();edChanged();$('edmsg').textContent='reset: back to the untouched sample'}
function edButtons(){if(!$('edprev'))return;const m=ED&&ED.P&&ED.P.mode;
 $('edprev').textContent=m==='prev'?'■ stop preview':'▶ preview edit';$('edprev').classList.toggle('playing',m==='prev');
 $('edplay').textContent=m==='sel'?'■ stop':'▶ selection';$('edplay').classList.toggle('playing',m==='sel')}
// Tone slider 0..100 -> low-pass cutoff, log scale 300 Hz..20 kHz (100 = off)
// Decay slider 0..100 -> 0 (natural) or 0.03..2 s on a log scale
const decayS=v=>v?0.03*Math.pow(2/0.03,(v-1)/99):0,decayVal=s=>s?Math.max(1,Math.round(1+99*Math.log(s/0.03)/Math.log(2/0.03))):0;
const toneHz=v=>Math.round(300*Math.pow(20000/300,v/100)),toneVal=hz=>hz>=19000?100:Math.round(100*Math.log(hz/300)/Math.log(20000/300));
function edParams(){return{start:+ED.sel[0].toFixed(3),end:+ED.sel[1].toFixed(3),stretch:+$('edst').value,semis:+$('edpi').value,
 formant:$('edfm').checked,tape:$('edtape').checked,tone:+$('edtone').value>=100?20000:toneHz(+$('edtone').value),reverse:$('edrev').checked,
 ...($('eddrum')?{punch:+$('edpunch').value/100,decay:+decayS(+$('eddecay').value).toFixed(3),drive:+$('eddrive').value/100,lowcut:+$('edlow').value}:{}),fade_in:+$('edfi').value,fade_out:+$('edfo').value,normalize:true,loop_xfade:$('edloop').checked?+$('edxf').value:0}}
// ---------- resizable sample panel (remembered per browser)
(function(){const app=document.querySelector('.app'),sp=$('dsplit'),KEY='atlasDetailW',set=w=>{w=Math.max(340,Math.min(window.innerWidth-560,w));app.style.setProperty('--dw',w+'px');return w};
 try{const v=+localStorage.getItem(KEY);if(v)set(v)}catch(e){}
 let drag=false;sp.onmousedown=e=>{drag=true;sp.classList.add('on');e.preventDefault()};
 window.addEventListener('mousemove',e=>{if(drag)set(window.innerWidth-e.clientX)});
 window.addEventListener('mouseup',()=>{if(!drag)return;drag=false;sp.classList.remove('on');try{localStorage.setItem(KEY,parseInt(getComputedStyle(app).getPropertyValue('--dw')))}catch(e){}
  window.dispatchEvent(new Event('resize'))});
 sp.ondblclick=()=>{app.style.removeProperty('--dw');try{localStorage.removeItem(KEY)}catch(e){}window.dispatchEvent(new Event('resize'))}})();
function edDraw(){const c=$('edc');if(!c||!ED||!ED.buf)return;const dpr=window.devicePixelRatio||1,W=Math.round(c.clientWidth*dpr),H=Math.round(120*dpr);
 if(c.width!==W||c.height!==H){c.width=W;c.height=H;ED.peaks=null}
 const base=ED.base||(ED.base=document.createElement('canvas'));base.width=W;base.height=H;const g=base.getContext('2d');
 const d0=ED.buf.getChannelData(0),d1=ED.buf.numberOfChannels>1?ED.buf.getChannelData(1):d0,sr=ED.buf.sampleRate,[v0,v1]=edView();
 if(!ED.peaks){ED.peaks=[];const s0=v0*sr,step=(v1-v0)*sr/W;for(let x=0;x<W;x++){let mn=0,mx=0;const k0=Math.floor(s0+x*step),k1=Math.max(k0+1,Math.floor(s0+(x+1)*step));
  for(let k=k0;k<Math.min(d0.length,k1);k++){const v=(d0[k]+d1[k])/2;if(v<mn)mn=v;if(v>mx)mx=v}ED.peaks.push([mn,mx])}}
 const [a,b]=ED.sel,X=t=>edX(t,W),e=edEnv(),top=6*dpr,bot=H-14*dpr,mid=(top+bot)/2,amp=(bot-top)/2;
 const gain=t=>{if(t<a||t>b)return 1;const gi=!e.loop&&e.fin>0?Math.min(1,(t-a)/e.fin):1,tail=e.loop?e.xf:e.fout,go=tail>0?Math.min(1,(b-t)/tail):1;return Math.min(gi,go)};  // a loop's start is left as it is
 g.clearRect(0,0,W,H);g.fillStyle='rgba(224,164,88,.10)';g.fillRect(X(a),0,X(b)-X(a),H);
 ED.peaks.forEach(([mn,mx],x)=>{const t=edT(x/dpr,W/dpr),inS=t>=a&&t<=b,k=inS?gain(t):1;
  if(inS&&k<0.98){g.fillStyle='rgba(140,192,218,.28)';g.fillRect(x,mid-mx*amp,1,Math.max(1,(mx-mn)*amp))}  // what's there before the fade
  g.fillStyle=inS?'#8cc0da':'#3f4e58';g.fillRect(x,mid-mx*amp*k,1,Math.max(1,(mx-mn)*amp*k))});
 const bar0=edBar();if(bar0&&(!$('edbars')||$('edbars').checked)){const o=ED.anchor!=null?ED.anchor:a,[v0,v1]=edView(),pxBar=bar0/(v1-v0)*W;
  if(pxBar>=5*dpr){const every=Math.max(1,Math.ceil(26*dpr/pxBar));g.font=`${10*dpr}px ui-monospace,Menlo,monospace`;g.textBaseline='top';
   if(pxBar>=90*dpr){g.fillStyle='rgba(224,164,88,.12)';for(let n=Math.ceil((v0-o)/bar0*4);o+n*bar0/4<=v1;n++)if(n%4)g.fillRect(X(o+n*bar0/4),top,1*dpr,bot-top)}  // beats, when there's room
   for(let n=Math.ceil((v0-o)/bar0);o+n*bar0<=v1+1e-6;n++){if(!n)continue;const x=X(o+n*bar0),m=Math.abs(n),lab=m%every===0;
    g.fillStyle=lab?'rgba(224,164,88,.45)':'rgba(224,164,88,.2)';g.fillRect(x,0,1*dpr,lab?H:bot);
    if(lab){const txt=m===1?'1 bar':String(m);g.fillStyle='#12151a';g.fillRect(x+2*dpr,bot+1*dpr,g.measureText(txt).width+4*dpr,12*dpr);g.fillStyle='#e0a458';g.fillText(txt,x+4*dpr,bot+2*dpr)}}}}
 g.fillStyle='rgba(255,255,255,.28)';ED.onsets.forEach(t=>g.fillRect(X(t),H-7*dpr,1*dpr,7*dpr));
 g.fillStyle='#e0a458';[a,b].forEach(t=>{g.fillRect(X(t)-1*dpr,0,2*dpr,H);g.fillRect(X(t)-3*dpr,mid-10*dpr,6*dpr,20*dpr)});
 const line=(x0,y0,x1,y1,col,dash)=>{g.save();g.strokeStyle=col;g.lineWidth=1.5*dpr;g.setLineDash(dash?[4*dpr,3*dpr]:[]);g.beginPath();g.moveTo(x0,y0);g.lineTo(x1,y1);g.stroke();g.restore()};
 if(e.fin>0&&!e.loop)line(X(a),bot,X(a+e.fin),top,'#ffffff');
 if(e.loop){if(e.fout>0)line(X(b-e.fout),top,X(b),bot,'rgba(255,255,255,.45)',true);
  if(e.xf>0){line(X(b-e.xf),top,X(b),bot,'#e0a458');line(X(a-e.xf),bot,X(a),top,'#e0a458',true);g.fillStyle='rgba(224,164,88,.07)';g.fillRect(X(a-e.xf),0,X(a)-X(a-e.xf),H)}}  // the lead-in the end blends into
 else if(e.fout>0)line(X(b-e.fout),top,X(b),bot,'#ffffff');
 edKnobs().forEach(k=>{g.beginPath();g.arc(X(k.t),top,(k.small?4:6)*dpr,0,Math.PI*2);g.fillStyle=k.col;g.fill();g.lineWidth=2*dpr;g.strokeStyle='#101317';g.stroke()});
 const bar=edBar(),nb=bar?(b-a)/bar:0,bars=bar&&Math.abs(nb-Math.round(nb))<0.004&&Math.round(nb)>=1?` · ${Math.round(nb)} bar${Math.round(nb)>1?'s':''}`:'';
 if($('edbarsl'))$('edbarsl').hidden=!bar;
 $('edsel').textContent=`selection ${a.toFixed(2)}–${b.toFixed(2)} s (${(b-a).toFixed(2)} s${bars}) · fade in ${Math.round(e.fin*1000)} ms · `+
  (e.loop?`loop crossfade ${Math.round(e.xf*1000)} ms${e.xf<0.001&&a<0.003?' (nothing before the selection to blend from: start it a little later for a crossfade)':' into the lead-in'}`:`fade out ${Math.round(e.fout*1000)} ms`)+(e.loop?` · fade out on stop ${Math.round(e.fout*1000)} ms`:'')+` · drag knobs to adjust`;
 edPaint()}
// one bar in this sample's own time: its tempo if it has one (loops), else the project's
function edBar(){if(!ED)return 0;const own=S[ED.i]&&S[ED.i][F.bpm],pj=(typeof PROJ!=='undefined'&&PROJ&&PROJ.bpm)||0,bpm=own||pj;return bpm?240/bpm:0}
function edView(){const d=ED.buf.duration,v=ED.view||[0,d];return [Math.max(0,v[0]),Math.min(d,v[1])]}
function edX(t,W){const [v0,v1]=edView();return (t-v0)/(v1-v0)*W}
function edT(px,W){const [v0,v1]=edView();return Math.max(0,Math.min(ED.buf.duration,v0+px/W*(v1-v0)))}
function edZoom(to){const d=ED.buf.duration;if(to==='sel'){const [a,b]=ED.sel,m=Math.max(0.05,(b-a)*0.12);ED.view=[a-m,b+m]}else ED.view=to;
 ED.peaks=null;edDraw();if($('edzoom'))$('edzoom').textContent=ED.view&&(ED.view[1]-ED.view[0])<d-1e-3?'🔍 zoom out':'🔍 zoom to selection'}
function edEnv(){const [a,b]=ED.sel,len=b-a,loop=$('edloop').checked,cap=v=>Math.max(0,Math.min(v,len/2-0.002));
 // a loop's crossfade blends its end into the audio that leads into its start: it can't be longer than that lead-in
 return{loop,fin:cap(+$('edfi').value/1000),fout:cap(+$('edfo').value/1000),xf:Math.max(0,Math.min(+$('edxf').value/1000,len/3,a))}}
function edKnobs(){const e=edEnv(),[a,b]=ED.sel;const k=e.loop?[]:[{id:'in',t:a+e.fin,col:'#ffffff'}];  // a loop's start is left as it is
 if(e.loop){k.push({id:'xout',t:b-e.xf,col:'#e0a458'},{id:'xin',t:a-e.xf,col:'#e0a458',small:true})}else k.push({id:'out',t:b-e.fout,col:'#ffffff'});return k}
function edEdgeAt(ev){const c=$('edc');if(!ED||!ED.buf)return null;const [a,b]=ED.sel,W=c.clientWidth;
 const da=Math.abs(ev.offsetX-edX(a,W)),db=Math.abs(ev.offsetX-edX(b,W));if(Math.min(da,db)>7)return null;return da<db?'a':'b'}
function edHandleAt(ev){const c=$('edc');if(ev.offsetY>15)return null;let best=null,bd=8;  // on the knob itself (6 px from the top), not just near it
 edKnobs().forEach(k=>{const d=Math.abs(ev.offsetX-edX(k.t,c.clientWidth));if(d<bd){bd=d;best=k.id}});return best}
function edSetEnv(which,ms){const el={in:$('edfi'),out:$('edfo'),xin:$('edxf'),xout:$('edxf')}[which],st=+el.step||1;
 el.value=Math.round(ms/st)*st;el.dispatchEvent(new Event('input'))}
function edPaint(pos){const c=$('edc');if(!c||!ED||!ED.base)return;const g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);g.drawImage(ED.base,0,0);
 if(pos==null)return;const dpr=window.devicePixelRatio||1,x=edX(pos,c.width);if(x<0||x>c.width)return;g.fillStyle='#fff';g.fillRect(x-dpr,0,2*dpr,c.height);g.fillStyle='rgba(255,255,255,.12)';g.fillRect(x-6*dpr,0,5*dpr,c.height)}
// one sample-accurate loop player for both the selection and the rendered preview
const eqIn=n=>Float32Array.from({length:n},(_,k)=>Math.sin(k/(n-1)*Math.PI/2)),eqOut=n=>Float32Array.from({length:n},(_,k)=>Math.cos(k/(n-1)*Math.PI/2));
// one pass of the selection. Looping is seamless the way the saved file will be: every pass is the whole selection
// at its exact length, and each later pass comes in over the previous one's end from the audio that leads into the
// selection's start (the "lead-in"), so the start itself is never blended with anything.
function lpLead(P,pass){const len=pass.b-pass.a;return P.loop?Math.max(0,Math.min(pass.xf||0,len/3,pass.a||0)):0}
function lpGrain(P,when,pass,first,last){const len=pass.b-pass.a,loop=P.loop&&!last,pre=lpLead(P,pass),lead=first?0:pre,
 fin=first?Math.max(0.004,P.loop?0.004:pass.fin):(lead>0.001?lead:0.003),fout=last?Math.max(0.004,pass.fout):(pre>0.001?pre:0.003);
 const g=AC.createGain(),src=AC.createBufferSource();src.buffer=pass.buf;src.connect(g);g.connect(AC.destination);
 const fi=Math.min(fin,len/2-0.002),fo=Math.min(fout,len/2-0.002),t0=Math.max(AC.currentTime,when-lead);
 if(fi>0.001)g.gain.setValueCurveAtTime(eqIn(64),t0,fi);else g.gain.setValueAtTime(1,t0);
 if(fo>0.001)g.gain.setValueCurveAtTime(eqOut(64),when+len-fo,fo);
 src.start(t0,Math.max(0,pass.a-(when-t0)),len+(when-t0));const v={src,g};P.voices.push(v);src.onended=()=>{P.voices=P.voices.filter(x=>x!==v)};
 P.segs.push({t0:when,len,map:pass.map});if(P.segs.length>8)P.segs.shift();return len}
function lpSchedule(){const P=ED&&ED.P;if(!P)return;
 if(P.pending&&(!P.loop||P.next<=AC.currentTime+0.35+lpLead(P,P.cur))){P.cur=P.pending;P.pending=null;if(P.onSwitch)P.onSwitch()}
 if(!P.loop){if(!P.segs.length){const len=lpGrain(P,P.next,P.cur,true,true);P.end=P.next+len}
  if(AC.currentTime>P.end+0.05){ED.P=null;edButtons();drawNP();edPaint();return}P.timer=setTimeout(lpSchedule,60);return}
 while(P.next<AC.currentTime+0.35+lpLead(P,P.cur)){if(P.pending){P.cur=P.pending;P.pending=null;if(P.onSwitch)P.onSwitch()}
  P.next+=Math.max(0.03,lpGrain(P,P.next,P.cur,!P.segs.length,false))}
 P.timer=setTimeout(lpSchedule,60)}
function lpStart(mode,pass,label){stopAll();AC.resume();
 ED.P={mode,loop:$('edloop').checked,next:AC.currentTime+0.03,cur:pass,pending:null,segs:[],voices:[],timer:null};
 lpSchedule();setNP(S[ED.i][F.path],S[ED.i][F.id],label,ED.i);edButtons();requestAnimationFrame(edTick)}
function selPass(){const [a,b]=ED.sel;return{buf:ED.buf,a,b,map:t=>a+t,fin:+$('edfi').value/1000,fout:+$('edfo').value/1000,xf:+$('edxf').value/1000}}
function prevPass(buf,p){return{buf,a:0,b:buf.duration,fin:0.004,fout:0.004,xf:0,
 map:t=>{const src=Math.min(t/p.stretch,p.end-p.start);return p.reverse?p.end-src:p.start+src}}}
function edPos(){const P=ED&&ED.P;if(!P)return null;const now=AC.currentTime,seg=[...P.segs].reverse().find(x=>x.t0<=now);
 if(!seg)return null;const t=now-seg.t0;return t<=seg.len?seg.map(t):null}
function edTick(){if(!ED||!ED.P){edPaint();return}const p=edPos();edPaint(p);requestAnimationFrame(edTick)}
function edToggleSel(){if(ED&&ED.P&&ED.P.mode==='sel'){edStop();return}edPlaySel()}
function edPlaySel(){const [a,b]=ED.sel;lpStart('sel',selPass(),`selection ${a.toFixed(2)}–${b.toFixed(2)} s of `+lbl(ED.i))}
function pvPlaying(){return !!(ED&&ED.P&&ED.P.mode==='prev')}
async function edRender(params){const r=await (await fetch('api/edit/preview',{method:'POST',body:JSON.stringify({path:S[ED.i][F.path],params})})).json();
 if(r.error)throw new Error(r.error);const ab=await (await fetch(url(r.url)+'?t='+Date.now())).arrayBuffer();return AC.decodeAudioData(ab)}
async function edPreview(){if(pvPlaying()){edStop();$('edmsg').textContent='stopped';return}
 $('edmsg').textContent='rendering…';const params=edParams();
 try{const buf=await edRender(params);lpStart('prev',prevPass(buf,params),'preview: edit of '+lbl(ED.i));
  $('edmsg').textContent='previewing — change anything and it updates after this pass'}
 catch(e){$('edmsg').textContent='error: '+e.message}}
let pvTimer=null,pvSeq=0;
function edChanged(){if(!ED||!ED.P)return;
 if(ED.P.mode==='sel'){ED.P.pending=selPass();return}
 clearTimeout(pvTimer);pvTimer=setTimeout(edQueuePreview,250)}
async function edQueuePreview(){const seq=++pvSeq,params=edParams();$('edmsg').textContent='rendering the change…';
 try{const buf=await edRender(params);if(seq!==pvSeq||!pvPlaying())return;
  ED.P.pending=prevPass(buf,params);ED.P.onSwitch=()=>{$('edmsg').textContent='now playing the updated preview'};
  $('edmsg').textContent=ED.P.loop?'updated preview queued — plays after this pass':'updated — press preview again to hear it'}
 catch(e){$('edmsg').textContent='error: '+e.message}}
function edQueueSel(){if(ED&&ED.P&&ED.P.mode==='sel')ED.P.pending=selPass()}
async function edSave(){$('edmsg').textContent='saving (analysing for related-sample matches)…';
 const i=ED.i,p=S[i];const r=await (await fetch('api/edit/save',{method:'POST',body:JSON.stringify({path:p[F.path],params:edParams(),name:$('edname').value,label:lbl(i)})})).json();
 if(r.error){$('edmsg').textContent='error: '+r.error;return}const n=r.row,row=p.slice();
 Object.assign(row,{[F.id]:n.id,[F.path]:n.path,[F.sub]:n.subtype,[F.kind]:n.kind,[F.cam]:n.cam,[F.key]:n.key,[F.bpm]:n.bpm,[F.dur]:n.dur,
  [F.env]:n.env,[F.note]:n.note,[F.bars]:n.bars,[F.start]:n.start,[F.parent]:n.parent,[F.root]:n.root,[F.ops]:n.ops});
 const j=S.push(row)-1;P.push(n.partners?n.partners.map(([id,sc,h,v])=>[BYID.get(id),sc,h,v]).filter(x=>x[0]!=null):P[i]);BYID.set(n.id,j);byPath.set(n.path,j);(BYTRACK.get(row[F.tid])||[]).push(j);
 FAV.set(n.path,{path:n.path,sample_id:n.id,label:'edit of '+lbl(i),added_at:new Date().toISOString()});
 edStop();select(j,'go')}
// ---------- source focus (show only some tracks' samples)
function showTracks(ids,{group='type',label=''}={}){st.tracks=new Set(ids.map(String));st.tlabel=label;st.tab='S';Object.values(tabs).forEach(t=>$(t).classList.toggle('on',t==='tabS'));
 st.excl=new Set();if(group)$('grp').value=group;st.shown=500;history.replaceState(null,'','#tracks='+ids.join(','));render()}
function clearTracks(){st.tracks=null;st.tlabel='';history.replaceState(null,'',location.pathname);
 st.excl=new Set((()=>{try{const v=localStorage.getItem('atlasExcl');return v?JSON.parse(v):['Electronic']}catch(e){return['Electronic']}})());$('grp').value='';render()}
function drawBanner(){const b=$('tbanner');if(!st.tracks||st.tab!=='S'){b.hidden=true;return}const ids=[...st.tracks],n=S.filter(s=>st.tracks.has(String(s[F.tid]))).length;
 const names=ids.map(t=>D.tracks[t]?`${D.tracks[t][1]} – ${D.tracks[t][2]}`:t);
 b.hidden=false;b.innerHTML=`Showing <b>${n}</b> samples from ${st.tlabel?`<b>${esc(st.tlabel)}</b> (${ids.length} song${ids.length>1?'s':''})`:esc(names.slice(0,3).join(' · '))+(names.length>3?` +${names.length-3} more`:'')} &nbsp;${st.tlabel?'<button id="tback">← artists</button> ':''}${rackBtn(ids,st.tlabel||'Selection').replace('🥁 ','🥁 Drum Rack · ')} <button id="tclear">✕ clear</button>`;$('tclear').onclick=clearTracks;
 if($('tback'))$('tback').onclick=()=>{$('tabA').click()}}
// ---------- artists: every artist → albums → songs; click any level to list its samples
const ARTISTS=(()=>{const cnt={};S.forEach(s=>{cnt[s[F.tid]]=(cnt[s[F.tid]]||0)+1});const A=new Map();
 Object.entries(D.tracks).forEach(([t,[ep,ar,ti,kind,al]])=>{if(!cnt[t])return;const name=(ar||'Unknown artist').trim(),k=name.toLowerCase();
  if(!A.has(k))A.set(k,{name,n:0,tracks:[],albums:new Map()});const a=A.get(k);a.n+=cnt[t];a.tracks.push(t);const alb=al||'(no album)';
  if(!a.albums.has(alb))a.albums.set(alb,[]);a.albums.get(alb).push([t,ti,cnt[t]])});return [...A.values()]})();
st.aq='';st.asort='az';st.aopen=new Set();
function artistKey(a){return a.name.replace(/^the\s+/i,'')}
function renderArtists(){const L=$('list');const q=st.aq.toLowerCase();
 let list=ARTISTS.filter(a=>!q||a.name.toLowerCase().includes(q)||[...a.albums.values()].some(ts=>ts.some(([,ti])=>(ti||'').toLowerCase().includes(q))));
 list.sort(st.asort==='n'?(a,b)=>b.n-a.n:(a,b)=>artistKey(a).localeCompare(artistKey(b),undefined,{sensitivity:'base'}));
 $('count').textContent=`${ARTISTS.length.toLocaleString()} artists · ${Object.keys(D.tracks).length.toLocaleString()} songs`;
 const letters=[...new Set(list.map(a=>{const c=artistKey(a)[0]||'#';return /[a-z]/i.test(c)?c.toUpperCase():'#'}))];
 let h=`<div class="artbar"><input id="aq" type="search" placeholder="find an artist or song…" value="${esc(st.aq)}"><select id="asort"><option value="az" ${st.asort==='az'?'selected':''}>A–Z</option><option value="n" ${st.asort==='n'?'selected':''}>most samples</option></select>
  ${st.asort==='az'?`<span class="letters">${letters.map(l=>`<a href="#" data-jump="${l}">${l}</a>`).join('')}</span>`:''}</div>`;
 let last='';h+=list.map(a=>{const c=artistKey(a)[0]||'#',l=/[a-z]/i.test(c)?c.toUpperCase():'#';const anchor=st.asort==='az'&&l!==last?` id="art-${l}"`:'';last=l;
  const open=st.aopen.has(a.name)||(q&&list.length<=5);const songs=a.tracks.length;
  return `<div class="art"${anchor}><div class="arow"><button class="tw" data-aopen="${esc(a.name)}">${open?'▾':'▸'}</button><a href="#" class="aname" data-aall="${esc(a.name)}">${esc(a.name)}</a><span class="sub">${a.n} samples · ${songs} song${songs>1?'s':''}</span>${open?rackBtn(a.tracks,a.name):''}</div>
  ${open?[...a.albums.entries()].map(([al,ts])=>`<div class="alb"><a href="#" data-aalb="${esc(a.name)}|${esc(al)}">${esc(al)}</a> <span class="sub">${ts.reduce((x,t)=>x+t[2],0)}</span> ${rackBtn(ts.map(t=>t[0]),a.name+' - '+al)}
   ${ts.map(([t,ti,n])=>`<div class="song"><a href="#" data-showt="${t}" data-tlabel="${esc(a.name+' — '+ti)}">${esc(ti||'untitled')}</a> <span class="sub">${n}</span> ${rackBtn([t],a.name+' - '+(ti||'untitled'))}</div>`).join('')}</div>`).join(''):''}</div>`}).join('');
 L.innerHTML=h||'<div class="empty">No artists match.</div>';
 const aq=$('aq');aq.oninput=()=>{st.aq=aq.value;const pos=aq.selectionStart;renderArtists();const n=$('aq');n.focus();n.setSelectionRange(pos,pos)};
 $('asort').onchange=e=>{st.asort=e.target.value;renderArtists()}}
const artistBy=name=>ARTISTS.find(a=>a.name===name);
// ---------- Drum Racks from a song / album / artist: its drum one-shots, kicks first, then snares, hats…
const RACK_ORDER=['Kick','Snare','Rim & Clap','Hat Closed','Hat Open','Shaker & Tamb','Tom','Hand Drum','Wood & Metal','Orchestral','Ride','Crash',
 'Kick + Snare','Kick + Hat','Snare + Hat','Perc + Hat','Kick + Cymbal','Snare + Cymbal','Other Combos'];
function drumHits(tids){const T=new Set(tids.map(String)),ro=s=>{const k=RACK_ORDER.indexOf(s);return k<0?99:k};
 return S.map((s,i)=>i).filter(i=>T.has(String(S[i][F.tid]))&&S[i][F.cat]==='Percussion'&&S[i][F.kind]==='oneshot')
  .sort((a,b)=>ro(S[a][F.sub])-ro(S[b][F.sub])||S[b][F.q]-S[a][F.q]).slice(0,128)}
async function makeRack(ids,name,btn){if(!SERVED){btn.textContent='needs "digitalcrate serve"';return}
 if(!ids.length){btn.textContent='no pads left';return}btn.textContent='building…';
 try{const r=await (await fetch('api/export',{method:'POST',body:JSON.stringify({scope:'paths',paths:ids.map(i=>S[i][F.path]),name:name+' drums',rack:true,reveal:true})})).json();
  btn.textContent=r.error?'error':`✓ exported ${r.count} pads (Finder is open)`}catch(e){btn.textContent='error'}}
// ---------- Drum Rack viewer: the rack as 4x4 pad pages; click or keys 1234/QWER/ASDF/ZXCV to play
const RKEYS='1234qwerasdfzxcv'.split(''),RACK={open:false,ids:[],page:0,name:'',buf:{}};
const RSHORT={'Kick':'Kick','Snare':'Snare','Rim & Clap':'Rim/Clap','Hat Closed':'Hat','Hat Open':'Open hat','Shaker & Tamb':'Shaker','Tom':'Tom','Hand Drum':'Hand drum',
 'Wood & Metal':'Wood/Metal','Orchestral':'Timpani','Ride':'Ride','Crash':'Crash','Kick + Snare':'Kick+Snare','Kick + Hat':'Kick+Hat','Snare + Hat':'Snare+Hat',
 'Perc + Hat':'Perc+Hat','Kick + Cymbal':'Kick+Cym','Snare + Cymbal':'Snare+Cym','Other Combos':'Combo'};
function openRack(tids,name){RACK.ids=drumHits(tids);RACK.name=name;RACK.page=0;RACK.open=true;$('modalBody').style.width='min(760px,94vw)';drawRack();
 RACK.ids.slice(0,16).forEach(rackLoad)}
async function rackLoad(i){const p=S[i][F.path];if(!RACK.buf[p])RACK.buf[p]=fetch(url(p)).then(r=>r.arrayBuffer()).then(a=>AC.decodeAudioData(a));return RACK.buf[p]}
async function rackHit(k){const i=RACK.ids[RACK.page*16+k];if(i==null)return;AC.resume();const b=await rackLoad(i);const s=AC.createBufferSource();s.buffer=b;s.connect(AC.destination);s.start();
 const el=document.querySelector(`#rackgrid [data-rp="${k}"]`);if(el){el.classList.add('hit');setTimeout(()=>el.classList.remove('hit'),Math.min(400,b.duration*1000))}}
function drawRack(){const n=RACK.ids.length,pages=Math.max(1,Math.ceil(n/16)),p0=RACK.page*16;
 modal(`<h2 style="margin:0;display:flex;gap:10px;align-items:center;flex-wrap:wrap">🥁 ${esc(RACK.name)}${hq('rack')}<span class="sub">${n} pad${n===1?'':'s'} · kicks first</span></h2>
 <div class="sub">Click a pad or press its key to play it. ✕ drops a pad from the rack; shift-click opens its sample.</div>
 ${pages>1?`<div class="chips">${Array.from({length:pages},(_,k)=>`<button data-rpage="${k}" class="${k===RACK.page?'on':''}">pads ${k*16+1}–${Math.min(n,k*16+16)}</button>`).join('')}</div>`:''}
 <div id="rackgrid" class="rackgrid">${Array.from({length:16},(_,k)=>{const i=RACK.ids[p0+k];if(i==null)return`<div class="rpad empty"></div>`;const s=S[i];
  return `<div class="rpad" data-rp="${k}" title="${esc(s[F.sub])} · ${esc(s[F.artist])} — ${esc(s[F.title])} (${s[F.id]})"><div class="rtop"><b>${RKEYS[k].toUpperCase()}</b><button class="rx" data-rx="${p0+k}" title="drop this pad">✕</button></div>
   ${wave(s[F.env],120,22,'#7d8592')}<span>${esc(RSHORT[s[F.sub]]||s[F.sub])} <i>${p0+k+1}</i></span></div>`}).join('')}</div>
 <div class="edrow"><button id="rackexp" class="pill">⇩ Drum Rack to Ableton</button>${SERVED?'<button id="racksk" title="a playable kit from this rack (up to two of each kind: kick, snare, hats…) as a drum lane in the sketchpad, with a starter pattern">🎛 to the sketchpad</button>':''}<button data-close>close</button></div>`)}
$('modalBody').addEventListener('mousedown',e=>{if(!RACK.open)return;const x=e.target.closest('[data-rx]');if(x){e.stopPropagation();RACK.ids.splice(+x.dataset.rx,1);
  if(RACK.page*16>=RACK.ids.length&&RACK.page>0)RACK.page--;drawRack();return}
 const pg=e.target.closest('[data-rpage]');if(pg){RACK.page=+pg.dataset.rpage;drawRack();RACK.ids.slice(RACK.page*16,RACK.page*16+16).forEach(rackLoad);return}
 const pd=e.target.closest('[data-rp]');if(pd){e.preventDefault();const k=+pd.dataset.rp;if(e.shiftKey){const i=RACK.ids[RACK.page*16+k];closeRack();select(i,'list');return}rackHit(k);return}
 if(e.target.id==='rackexp'){makeRack(RACK.ids,RACK.name,e.target)}});
function closeRack(){RACK.open=false;$('modal').hidden=true;$('modalBody').style.width=''}
$('modal').addEventListener('click',e=>{if(RACK.open&&(e.target.id==='modal'||e.target.closest('[data-close]')))closeRack()});
window.addEventListener('keydown',e=>{if(!RACK.open||$('modal').hidden){RACK.open=false;return}if(e.key==='Escape'){closeRack();return}
 if(e.metaKey||e.ctrlKey||e.target.tagName==='INPUT')return;const k=RKEYS.indexOf(e.key.toLowerCase());if(k<0)return;e.preventDefault();e.stopImmediatePropagation();if(!e.repeat)rackHit(k)},true);
const rackBtn=(tids,name)=>{const n=drumHits(tids).length;return n?`<button class="rackb" data-rack="${esc(tids.join(','))}" data-rname="${esc(name)}" title="see and play a Drum Rack of ${n} drum hits (kicks first), then export it to Ableton">🥁 ${n}</button>`:''};
document.addEventListener('click',e=>{const b=e.target.closest('[data-rack]');if(!b)return;e.preventDefault();e.stopPropagation();openRack(b.dataset.rack.split(','),b.dataset.rname)},true);
$('list').addEventListener('click',e=>{if(st.tab!=='A')return;const t=e.target.closest('[data-aopen],[data-aall],[data-aalb],[data-jump]');if(!t)return;e.preventDefault();e.stopPropagation();
 if(t.dataset.jump){const el=$('art-'+t.dataset.jump),m=document.querySelector('main'),hd=document.querySelector('.top');
  if(el)m.scrollTop+=el.getBoundingClientRect().top-hd.getBoundingClientRect().bottom-4;return}
 if(t.dataset.aopen){const n=t.dataset.aopen;st.aopen.has(n)?st.aopen.delete(n):st.aopen.add(n);const y=document.querySelector('main').scrollTop;renderArtists();document.querySelector('main').scrollTop=y;return}
 if(t.dataset.aall){const a=artistBy(t.dataset.aall);showTracks(a.tracks,{label:a.name});return}
 if(t.dataset.aalb){const [n,al]=t.dataset.aalb.split('|');const a=artistBy(n);showTracks(a.albums.get(al).map(x=>x[0]),{label:`${a.name} — ${al}`})}},true);
// ---------- per-clip export
const XPKEY='atlasExportName';
function xpName(){try{return localStorage.getItem(XPKEY)||'Clips'}catch(e){return 'Clips'}}
function setXpName(v){try{localStorage.setItem(XPKEY,v||'Clips')}catch(e){}}
function toast(msg){const t=$('toast');t.textContent=msg;t.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>t.hidden=true,2200)}
const xp=path=>`<button class="xp" data-xp="${esc(path)}" title="export this clip to Ableton (${esc(xpName())})">⇩</button>`;
async function exportOne(path,btn){if(!SERVED){toast('export needs the local server');return}
 const r=await (await fetch('api/export',{method:'POST',body:JSON.stringify({scope:'paths',paths:[path],name:xpName(),reveal:false})})).json();
 if(r.error||!r.count){toast('export failed'+(r.error?': '+r.error:''));return}
 document.querySelectorAll(`[data-xp="${CSS.escape(path)}"]`).forEach(b=>{b.classList.add('done');b.textContent='✓'});toast(`exported to ${xpName()} ✓`)}
document.addEventListener('click',e=>{const b=e.target.closest('[data-xp]');if(!b)return;e.stopPropagation();exportOne(b.dataset.xp,b)},true);
// ---------- add source / export
function modal(html){$('modalBody').innerHTML=html;$('modal').hidden=false}
$('modal').addEventListener('click',e=>{if(e.target.id==='modal'||e.target.dataset.close!=null)$('modal').hidden=true});
let jobTimer=null;
async function pollJobs(){const js=await (await fetch('api/jobs')).json();const el=$('jobs');if(!el){clearInterval(jobTimer);return}
 el.innerHTML=js.slice(-3).reverse().map(j=>`<div class="prov"><b>${esc(j.target)}</b> — ${j.running?'running…':j.ok?'<span style="color:var(--acc)">done</span>':'stopped'}
  <div class="meta" style="white-space:pre-wrap">${j.tail.map(esc).join('\n')}</div>${!j.running&&j.ok&&j.tracks?`<button class="pill" onclick="location.hash='tracks=${j.tracks}';location.reload()">show the new samples →</button>`:''}</div>`).join('')}
$('addsrc').onclick=()=>{if(!SERVED){alert('needs the local server');return}
 modal(`<h2 style="margin:0">Add a source</h2><div class="sub">A YouTube (or other) URL, an audio file path, or a folder path. It is downloaded / catalogued, mined for vocals, pads and textures (and optionally percussion), then the library is rebuilt.</div>
 <input id="srcIn" placeholder="https://www.youtube.com/watch?v=…   or   /path/to/song.mp3   or   /path/to/folder" style="width:100%">
 <label class="sub"><input type="checkbox" id="srcDrums"> also mine percussion (slower)</label>
 <div class="edrow"><button id="srcGo" class="pill">start</button><button data-close>close</button></div><div id="jobs"></div>`);
 $('srcGo').onclick=async()=>{const t=$('srcIn').value.trim();if(!t)return;await fetch('api/ingest',{method:'POST',body:JSON.stringify({target:t,drums:$('srcDrums').checked})});$('srcIn').value='';pollJobs()};
 pollJobs();clearInterval(jobTimer);jobTimer=setInterval(pollJobs,2500)};
$('expbtn').onclick=()=>{if(!SERVED){alert('needs the local server');return}
 const scope=st.tab==='F'?'favorites':'list',ids=st.tab==='F'?[...FAV.keys()]:filtered().slice(0,500).map(i=>S[i][F.path]);
 modal(`<h2 style="margin:0">Export to Ableton</h2><div class="sub">${ids.length} ${scope==='favorites'?'favourites':'samples from the current list'}${scope!=='favorites'&&filtered().length>500?' (first 500)':''} → <code>User Library/Samples/DigitalCrate/&lt;name&gt;/&lt;category&gt;/&lt;subtype&gt;/</code>, with an _info.csv of keys, tempos and sources. Live's browser shows it under User Library.</div>
 <input id="expName" placeholder="export name (e.g. Night session)" style="width:100%"><div class="edrow"><button id="expGo" class="pill">export</button><button data-close>close</button></div><div id="expMsg" class="sub"></div>`);
 $('expGo').onclick=async()=>{$('expMsg').textContent='copying…';const r=await (await fetch('api/export',{method:'POST',body:JSON.stringify(scope==='favorites'?{scope,name:$('expName').value}:{scope:'paths',paths:ids,name:$('expName').value})})).json();
  $('expMsg').textContent=r.error?'error: '+r.error:`exported ${r.count} files to ${r.dest} (opened in Finder)`}};
// ---------- audio
const players=new Map();
function stopAll(){setTimeout(()=>typeof drawNP==='function'&&drawNP(),0);if(typeof edStop==='function')edStop();setTimeout(()=>{if(typeof edButtons==='function')edButtons()},0);players.forEach((a,k)=>{a.pause();endListen(k,a)});players.clear();document.querySelectorAll('.play.playing').forEach(b=>b.classList.remove('playing'))}
function toggle(i,btn,{loop=true,exclusive=true}={}){
 if(players.has(i)){const a=players.get(i);a.pause();endListen(i,a);players.delete(i);mark();return}
 if(exclusive)stopAll();
 const a=new Audio(url(S[i][F.path]));a.loop=loop&&S[i][F.kind]!=='oneshot';a.onended=()=>{endListen(i,a);players.delete(i);mark()};
 a.play();players.set(i,a);beginListen(i,S[i][F.path]);setNP(S[i][F.path],S[i][F.id],lbl(i),i);mark()}
function playTogether(ids){stopAll();const as=ids.map(i=>{const a=new Audio(url(S[i][F.path]));a.loop=S[i][F.kind]!=='oneshot';a.volume=.8;players.set(i,a);return a});
 setNP(S[ids[ids.length-1]][F.path],S[ids[ids.length-1]][F.id],'together: '+ids.map(i=>S[i][F.artist]).join(' + '),ids[ids.length-1]);
 Promise.all(as.map(a=>new Promise(r=>{a.oncanplaythrough=r;a.load()}))).then(()=>{as.forEach(a=>a.play());mark()})}
function mark(){drawNP();document.querySelectorAll('[data-play]').forEach(b=>b.classList.toggle('playing',players.has(+b.dataset.play)))}
// ---------- filters
const CATS=[...new Set(S.map(s=>s[F.cat]))], KINDS=['loop','phrase','free','oneshot'];
const MOODS=[...new Set(S.flatMap(s=>s[F.tags]))].sort();
function chips(el,items,set,label=x=>x){el.innerHTML=items.map(x=>`<button data-v="${esc(x)}">${esc(label(x))}</button>`).join('');
 el.onclick=e=>{const v=e.target.dataset.v;if(v==null)return;set.has(v)?set.delete(v):set.add(v);e.target.classList.toggle('on');st.shown=200;render()}}
const CATORD=Object.keys(AB);CATS.sort((a,b)=>(CATORD.indexOf(a)+99*(CATORD.indexOf(a)<0))-(CATORD.indexOf(b)+99*(CATORD.indexOf(b)<0)));
const SHORT={'Vocal Atmospheres':'Vocal Atmos','Pads & Atmospheres':'Pads','Chords & Keys':'Keys','Melodies & Leads':'Leads','Textures & Field':'Textures','Bass & Sub':'Bass','Percussion':'Drums','Strings & Orchestral':'Strings'};
function drawCats(){const el=$('cats');const show=st.tab==='S'||st.tab==='G';el.hidden=!show;$('subsBox').hidden=!show||!st.cats.size;if(!show)return;
 // counts follow every other filter, so each tab says how many you'd get by switching to it
 const sc=st.cats,ss=st.subs;st.cats=new Set();st.subs=new Set();let base;try{base=filtered()}finally{st.cats=sc;st.subs=ss}
 const cnt={};base.forEach(i=>{const c=S[i][F.cat];cnt[c]=(cnt[c]||0)+1});
 const tab=(v,lbl,n,on,c)=>`<button data-v="${esc(v)}" title="${esc(v||'every category')}" class="${on?'on':''}" style="${c?`--c:var(--${c})`:''}">${c?'<i></i>':''}${esc(lbl)}<span class="n">${n.toLocaleString()}</span></button>`;
 el.innerHTML=tab('','All',base.length,!st.cats.size)+CATS.filter(c=>cnt[c]||st.cats.has(c)).map(c=>tab(c,SHORT[c]||c,cnt[c]||0,st.cats.has(c),AB[c])).join('');drawSubs()}
$('cats').onclick=e=>{const b=e.target.closest('button');if(!b)return;const v=b.dataset.v;
 if(!v)st.cats.clear();else if(e.metaKey||e.ctrlKey){st.cats.has(v)?st.cats.delete(v):st.cats.add(v)}else{const only=st.cats.size===1&&st.cats.has(v);st.cats.clear();if(!only)st.cats.add(v)}
 st.subs.clear();st.shown=200;render();$('list').scrollTop=0;document.querySelector('main').scrollTop=0};
chips($('kinds'),KINDS,st.kinds);
function drawSubs(){const box=$('subsBox');if(!st.cats.size){box.hidden=true;st.subs.clear();return}
 const cnt={};S.forEach(s=>{if(st.cats.has(s[F.cat]))cnt[s[F.sub]]=(cnt[s[F.sub]]||0)+1});
 [...st.subs].forEach(x=>{if(!cnt[x])st.subs.delete(x)});
 box.innerHTML=Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a]).map(x=>`<button data-v="${esc(x)}" class="${st.subs.has(x)?'on':''}">${esc(x)} (${cnt[x]})</button>`).join('')}
$('subsBox').onclick=e=>{const v=e.target.dataset.v;if(v==null)return;st.subs.has(v)?st.subs.delete(v):st.subs.add(v);e.target.classList.toggle('on');st.shown=200;render()};
const GENRES=[...new Set(S.map(s=>s[F.genre]))].sort((a,b)=>S.filter(s=>s[F.genre]===b).length-S.filter(s=>s[F.genre]===a).length);
chips($('genres'),GENRES,st.genres,g=>`${g} (${S.filter(s=>s[F.genre]===g).length})`);
st.excl=new Set((()=>{try{const v=localStorage.getItem('atlasExcl');return v?JSON.parse(v):['Electronic']}catch(e){return['Electronic']}})());
$('excl').innerHTML=GENRES.map(g=>`<label class="sub" style="white-space:nowrap"><input type="checkbox" data-ex="${esc(g)}" ${st.excl.has(g)?'checked':''}> ${esc(g)}</label>`).join('');
$('excl').onchange=e=>{const g=e.target.dataset.ex;if(!g)return;e.target.checked?st.excl.add(g):st.excl.delete(g);
 try{localStorage.setItem('atlasExcl',JSON.stringify([...st.excl]))}catch(err){}st.shown=200;render();if(st.sel!=null)select(st.sel,'back')};chips($('moods'),MOODS,st.moods);
function camNbrs(c){const n=+c.slice(0,-1),l=c.slice(-1),o=l==='A'?'B':'A',w=k=>((k+11)%12)+1;return new Set([c,`${w(n-1)}${l}`,`${w(n+1)}${l}`,`${n}${o}`])}
// Camelot wheel
(function(){const names={B:['B','F#','Db','Ab','Eb','Bb','F','C','G','D','A','E'],A:['Abm','Ebm','Bbm','Fm','Cm','Gm','Dm','Am','Em','Bm','F#m','Dbm']};
 let h='';for(const [ring,r0,r1] of [['B',70,105],['A',38,70]])for(let k=0;k<12;k++){const a0=(k-0.5)/12*2*Math.PI-Math.PI/2,a1=(k+0.5)/12*2*Math.PI-Math.PI/2;
 const p=(r,a)=>`${(r*Math.cos(a)).toFixed(1)},${(r*Math.sin(a)).toFixed(1)}`;const code=`${k+1}${ring}`;
 h+=`<path data-c="${code}" d="M${p(r0,a0)}A${r0},${r0} 0 0 1 ${p(r0,a1)}L${p(r1,a1)}A${r1},${r1} 0 0 0 ${p(r1,a0)}Z"/>`;
 const am=k/12*2*Math.PI-Math.PI/2,rm=(r0+r1)/2;h+=`<text x="${(rm*Math.cos(am)).toFixed(1)}" y="${(rm*Math.sin(am)+3).toFixed(1)}" text-anchor="middle">${code}</text>`;
 h+=`<title>${names[ring][k]}</title>`}
 $('wheel').innerHTML=h;$('wheel').onclick=e=>{const c=e.target.dataset.c;if(!c)return;st.key=st.key===c?null:c;st.shown=200;render()}})();
function paintWheel(){const cnt={};S.forEach(s=>{if(s[F.cam])cnt[s[F.cam]]=(cnt[s[F.cam]]||0)+1});const mx=Math.max(1,...Object.values(cnt));
 const nb=st.key?(st.nbr?camNbrs(st.key):new Set([st.key])):null;
 document.querySelectorAll('#wheel path').forEach(p=>{const c=p.dataset.c,v=(cnt[c]||0)/mx;
 p.style.fill=nb&&nb.has(c)?(c===st.key?'#e0a458':'#8a6a3e'):`rgba(127,176,201,${0.08+v*0.6})`});
 $('keylbl').textContent=st.key?st.key:''}
$('nbr').onclick=e=>{st.nbr=!st.nbr;e.target.classList.toggle('on');render()};$('clrkey').onclick=()=>{st.key=null;render()};
['bmin','bmax','half','q','sort','grp','since','wsel','secsel'].forEach(id=>$(id).addEventListener('input',()=>{st.shown=200;render()}));
let searchT=null;$('search').addEventListener('input',()=>{clearTimeout(searchT);searchT=setTimeout(()=>{st.shown=200;render()},160)});
$('stop').onclick=stopAll;
// the Processing page (served only), with a badge while a mining run is going
if(SERVED){const tt=$('tabT');tt.hidden=false;tt.onclick=()=>location.href='taste';}
if(SERVED){const tp=$('tabP');tp.hidden=false;tp.onclick=()=>location.href='activity';
 const badge=async()=>{try{const r=await (await fetch('api/activity?jobs=1')).json();const j=(r.jobs||[]).find(j=>j.kind==='process'||j.kind==='terminal');
  tp.textContent=j?(j.progress?`⚙ Processing · ${Math.round(100*j.progress[0]/j.progress[1])}%`:'⚙ Processing…'):'⚙ Processing';tp.classList.toggle('busy',!!j)}catch(e){}};
 badge();setInterval(badge,30000)}
$('refresh').onclick=()=>{$('refresh').hidden=true;render()};

// the latest run: walk back from the newest sample until a gap of more than 6 hours
const WORDS=D.words||{},WORDLESS=new Set(D.wordless||[]);
const BORN=D.born||[],BATCH0=(()=>{const e=BORN.filter(x=>x).sort((a,b)=>b-a);let k=0;while(k+1<e.length&&e[k]-e[k+1]<360)k++;return e[k]||0})();
const tabs={S:'tabS',A:'tabA',K:'tabK',F:'tabF',R:'tabR'};
Object.entries(tabs).forEach(([k,id])=>$(id).onclick=()=>{st.tab=k;Object.values(tabs).forEach(t=>$(t).classList.toggle('on',t===id));render()});
function filtered(){const q=$('search').value.toLowerCase().trim(),mq=+$('q').value,bmin=+$('bmin').value||0,bmax=+$('bmax').value||0,half=$('half').checked;
 const nb=st.key?(st.nbr?camNbrs(st.key):new Set([st.key])):null;$('qv').textContent=mq.toFixed(2);
 const okB=b=>{if(!bmin&&!bmax)return true;if(!b)return false;const t=[b];if(half)t.push(b*2,b/2);return t.some(x=>(!bmin||x>=bmin)&&(!bmax||x<=bmax))};
 let out=[];S.forEach((s,i)=>{if(s[F.q]<mq)return;if(st.tracks&&!st.tracks.has(String(s[F.tid])))return;if(st.cats.size&&!st.cats.has(s[F.cat]))return;if(st.subs.size&&!st.subs.has(s[F.sub]))return;if(st.kinds.size&&!st.kinds.has(s[F.kind]))return;if(st.genres.size&&!st.genres.has(s[F.genre]))return;if(st.excl.has(s[F.genre]))return;
 if(nb&&!(s[F.cam]&&nb.has(s[F.cam])))return;if(!okB(s[F.kind]==='loop'?s[F.bpm]:0)&&(bmin||bmax))return;
 if(st.moods.size&&![...st.moods].every(m=>s[F.tags].includes(m)))return;
 if(q&&!(`${s[F.artist]} ${s[F.title]} ${s[F.tags].join(' ')} ${s[F.inst]} ${s[F.id]} ${s[F.cat]} ${s[F.sub]} ${s[F.genre]} ${WORDS[i]||''}`.toLowerCase().includes(q)))return;out.push(i)});
 const wv=$('wsel').value;if(wv)out=out.filter(i=>wv==='w'?WORDS[i]:WORDLESS.has(i));
 const secv=$('secsel').value,SECS=D.sections||{};if(secv)out=out.filter(i=>secv==='exposed'?['intro','outro','break','inst','bridge'].includes(SECS[i]):SECS[i]===secv);
 out=out.filter(i=>!TASTE.disliked.has(S[i][F.path])&&!GONE.has(i));
 const sv=$('since').value;if(sv==='pads'){const P=new Set(D.padfound||[]);out=out.filter(i=>P.has(i))}else if(sv){const lim=sv==='batch'?BATCH0:Date.now()/60000-sv*1440;out=out.filter(i=>(BORN[i]||0)>=lim)}
 const k=$('sort').value;
 const byKey=(arr,f)=>{const v=new Float64Array(S.length);arr.forEach(i=>v[i]=f(i));return arr.sort((a,b)=>v[b]-v[a])};
 if(k==='div'){const by=new Map();byKey(out,i=>S[i][F.q]*1000+(TASTE.score[S[i][F.path]]??0));
  out.forEach(i=>{const a=S[i][F.artist];if(!by.has(a))by.set(a,[]);by.get(a).push(i)});
  const lists=[...by.values()].sort((x,y)=>(TASTE.score[S[y[0]][F.path]]??S[y[0]][F.q])-(TASTE.score[S[x[0]][F.path]]??S[x[0]][F.q]));
  const rr=[];for(let r=0;rr.length<out.length;r++)lists.forEach(l=>{if(l[r]!=null)rr.push(l[r])});return rr}
 if(k==='you'||k==='vibe'||k==='disc'){if(st.tab!=='F')out=out.filter(i=>!FAV.has(S[i][F.path]));  // recommendations: not what you've already starred
  const m=TASTE[{you:'score',vibe:'vibe',disc:'discover'}[k]];return byKey(out,i=>m[S[i][F.path]]??-9)}
 const cmp={q:(a,b)=>S[b][F.q]-S[a][F.q],key:(a,b)=>(S[a][F.cam]||'zz').localeCompare(S[b][F.cam]||'zz',undefined,{numeric:true}),
 bpm:(a,b)=>S[a][F.bpm]-S[b][F.bpm],dur:(a,b)=>S[b][F.dur]-S[a][F.dur],ref:(a,b)=>S[b][F.ref]-S[a][F.ref],new:(a,b)=>((D.tracks[S[b][F.tid]]||[0])[0]-(D.tracks[S[a][F.tid]]||[0])[0])||S[b][F.q]-S[a][F.q],var:(a,b)=>((D.variants[b]||[]).length-(D.variants[a]||[]).length)||S[b][F.q]-S[a][F.q],rnd:()=>Math.random()-.5}[k];return out.sort(cmp)}
function rowHTML(i){const s=S[i],c=col(s[F.cat]);const bpm=s[F.bpm]?`${s[F.bpm]} bpm`:'free';
 const kind=s[F.kind]==='loop'?`${s[F.bars]}-bar loop`:s[F.kind];
 return `<div class="row${st.sel===i?' sel':''}" data-i="${i}"><button class="play" data-play="${i}">▶</button>${wave(s[F.env],120,26,'#5b6370')}
 <div style="min-width:0"><div class="name"><span class="badge" style="background:${c}">${AB[s[F.cat]]}</span>${esc(s[F.sub])} · ${esc(kind)}${D.variants[i]?` · <span style="color:var(--acc)">${D.variants[i].length} variations</span>`:''}${s[F.parent]?` · <span style="color:var(--acc)">✎ edit</span>`:''}${s[F.note]?` · ${s[F.note]}`:''} · ${s[F.dur]}s
 ${s[F.tags].map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
 <div class="meta">${esc(s[F.artist])} — ${esc(s[F.title])} @ ${Math.floor(s[F.start]/60)}:${String(s[F.start]%60).padStart(2,'0')}${WORDS[i]?` · <i class="lyr">“${esc(WORDS[i].length>70?WORDS[i].slice(0,70)+'…':WORDS[i])}”</i>`:''}</div></div>
 <div class="right">${star(s[F.path],s[F.id],`${s[F.artist]} — ${s[F.title]} · ${s[F.sub]}`)}${nope(s[F.path],s[F.id])}${xp(s[F.path])}<span class="id" data-id="${s[F.id]}" title="copy ID">${s[F.id]}</span><span>${bpm}</span><span class="key">${s[F.cam]?`${s[F.cam]} ${s[F.key]}`:'—'}</span><span class="qbar" title="quality ${s[F.q]}"><i style="width:${s[F.q]*100}%"></i></span></div></div>`}
const OVR=new Set((D.overridden||[]).map(i=>S[i][F.id]));
const BYID=new Map(S.map((s,i)=>[s[F.id],i]));
const BYTRACK=new Map();S.forEach((s,i)=>{if(!BYTRACK.has(s[F.tid]))BYTRACK.set(s[F.tid],[]);BYTRACK.get(s[F.tid]).push(i)});
const trk=t=>(BYTRACK.get(t)||[]).filter(j=>!GONE.has(j));
BYTRACK.forEach(l=>l.sort((a,b)=>S[a][F.start]-S[b][F.start]||S[b][F.dur]-S[a][F.dur]));
const byPath=new Map(S.map((s,i)=>[s[F.path],i]));
function render(){paintWheel();drawCats();const L=$('list');$('refresh').hidden=true;drawBanner();
 if(st.tab==='R'){const cnt={};S.forEach(s=>cnt[s[F.tid]]=(cnt[s[F.tid]]||0)+1);
  const tr=Object.entries(D.tracks).filter(([t])=>cnt[t]).sort((a,b)=>b[1][0]-a[1][0]).slice(0,60);
  $('count').textContent='recently processed sources';
  L.innerHTML=tr.map(([t,[ep,ar,ti,kind]])=>`<div class="row" style="grid-template-columns:1fr auto;cursor:default"><div style="min-width:0"><div class="name">${kind?`<span class="badge" style="background:var(--acc)">${esc(kind)}</span>`:''}${esc(ar)} — ${esc(ti)}</div>
   <div class="meta">${ep?new Date(ep*1000).toLocaleString():''} · ${cnt[t]} samples</div></div><button data-showt="${t}">show samples →</button></div>`).join('');return}
 if(st.tab==='F'){const favs=[...FAV.values()].sort((a,b)=>(b.added_at||'').localeCompare(a.added_at||''));
  $('count').textContent=`${favs.length} favourites`+(SERVED?' · also in SampleLibrary/Favorites':' · run "python -m digitalcrate serve" to sync them to Ableton');
  L.innerHTML=favs.length?favs.map(f=>{const i=byPath.get(f.path);if(i!=null)return rowHTML(i);
   return `<div class="row" style="cursor:default"><button class="play" data-vp2="${esc(f.path)}">▶</button><span class="sub">variation</span>
   <div style="min-width:0"><div class="name">${esc(f.label||f.path)}</div><div class="meta">${esc(f.path)}</div></div><div class="right">${star(f.path,f.sample_id,f.label)}</div></div>`}).join('')
   :'<div class="empty">No favourites yet — click ★ on any sample or variation.</div>';mark();return}
 if(st.tab==='A'){renderArtists();return}
 if(st.tab==='K'){if(SERVED&&TASTE.loaded&&P_READY&&!P_FAIL&&(KITS_FOR!==String(TASTE.n)||$('kitnew')?.dataset.go==='1'))dealKits();
  const shown=D.kits.map((k,ki)=>[k,ki]).filter(([k])=>kitMembers(k).length>=3),hid=D.kits.length-shown.length;
  $('count').textContent=`${shown.length} kits`+(hid?` · ${hid} hidden: mostly ${[...st.excl].join(', ')}`:'')+(st.excl.size?` · ${[...st.excl].join(', ')} samples left out`:'');
  const kitHead=SERVED?`<div class="hint" style="margin:4px 0 10px">${D.kits[0]?.yours?`Dealt for you: each kit starts from a vocal your taste model rates highly and adds samples from other songs that fit it. ★ and ✕ samples (here or anywhere) to steer what it picks; listening counts too.`:(TASTE.loaded&&P_READY?'':'Loading your taste model… kits will be dealt for you in a moment.')} <button id="kitnew" title="deal a new set of kits">↻ new kits</button></div>`:'';
  L.innerHTML=kitHead+(shown.length?shown.map(([k,ki])=>`<div class="kit"><h3><span>${esc(k.name)}</span><button data-kit="${ki}">▶ play together</button> <button data-kitexp="${esc(k.name)}" data-kiti="${ki}">⇩ export</button></h3>${kitMembers(k).map(rowHTML).join('')}</div>`).join(''):'<div class="empty">No kits yet.</div>');const kn=$('kitnew');if(kn)kn.onclick=()=>{kn.dataset.go='1';render();document.querySelector('main').scrollTop=0};return}
 const ids=filtered();$('count').textContent=`${ids.length.toLocaleString()} of ${S.length.toLocaleString()} samples`+(st.excl.size?` · excluding ${[...st.excl].join(', ')}`:'')+(SERVED?` · taste model: ${TASTE.n} ratings`:'');
 const gm=$('grp').value;
 if(gm&&ids.length){const keyOf={track:i=>S[i][F.artist]+' — '+S[i][F.title],type:i=>S[i][F.cat]+' / '+S[i][F.sub],genre:i=>S[i][F.genre]}[gm];
  const per=gm==='track'?3:6,g=new Map();ids.forEach(i=>{const k=keyOf(i);if(!g.has(k))g.set(k,[]);g.get(k).push(i)});
  let groups=[...g.entries()];if(gm!=='track')groups.sort((a,b)=>b[1].length-a[1].length);
  const shownGroups=gm==='track'?groups.slice(0,Math.ceil(st.shown/3)):groups;
  L.innerHTML=shownGroups.map(([k,l])=>{const open=st.open.has(gm+k),lim=open?Math.min(l.length,60):per;
   return `<div class="kit"><h3><span>${esc(k)}</span><span class="sub">${l.length} samples ${gm==='track'&&SERVED?`<button data-delsong="${S[l[0]][F.tid]}" title="delete every sample cut from this song, except your favourites and edits">🗑</button> `:''}${l.length>per?`<button data-grp="${esc(gm+k)}">${open?'collapse':'show more'}</button>`:''}</span></h3>${l.slice(0,lim).map(rowHTML).join('')}</div>`}).join('')
   +(gm==='track'&&g.size>shownGroups.length?`<button class="more" id="more">show more tracks</button>`:'');mark();return}
 L.innerHTML=ids.length?ids.slice(0,st.shown).map(rowHTML).join('')+(ids.length>st.shown?`<button class="more" id="more">show more (${ids.length-st.shown})</button>`:''):'<div class="empty">Nothing matches these filters.</div>';mark()}
$('list').addEventListener('click',async e=>{const stb=e.target.closest('[data-showt]');if(stb){e.preventDefault();showTracks([stb.dataset.showt],{label:stb.dataset.tlabel||''});return}const ke=e.target.closest('[data-kitexp]');if(ke){const r=await (await fetch('api/export',{method:'POST',body:JSON.stringify({scope:'paths',paths:kitMembers(D.kits[+ke.dataset.kiti]).map(i=>S[i][F.path]),name:ke.dataset.kitexp})})).json();ke.textContent=r.error?'error':`exported ${r.count} ✓`;return}
 const gb=e.target.closest('[data-grp]');if(gb){const k=gb.dataset.grp;st.open.has(k)?st.open.delete(k):st.open.add(k);render();return}
 const vp=e.target.closest('[data-vp2]');if(vp){stopAll();const a=new Audio(url(vp.dataset.vp2));a.play();players.set('f',a);const f=FAV.get(vp.dataset.vp2);setNP(vp.dataset.vp2,f&&f.sample_id,(f&&f.label)||vp.dataset.vp2,null);return}
 const t=e.target.closest('[data-play],[data-id],[data-kit],#more,.row');if(!t)return;
 if(t.id==='more'){st.shown+=300;render();return}
 if(t.dataset.kit!=null){playTogether(kitMembers(D.kits[+t.dataset.kit]));return}
 if(t.dataset.id){navigator.clipboard&&navigator.clipboard.writeText(t.dataset.id);t.textContent='copied';setTimeout(()=>t.textContent=t.dataset.id,800);return}
 if(t.dataset.play!=null){toggle(+t.dataset.play,t);return}
 if(st.sel===+t.dataset.i){deselect();return}  // clicking the selected sample again unselects it
 select(+t.dataset.i,'list')});
let HIST=[];
// unselect: the sample panel goes back to how it starts (Esc, the panel's ✕, or clicking the selected row again)
const DETAIL_EMPTY=$('detail').innerHTML;
document.addEventListener('click',e=>{if(e.target.closest('#dclose')){e.stopPropagation();deselect()}},true);
function deselect(){if(st.sel==null)return;if(typeof edStop==='function')edStop();st.sel=null;HIST=[];
 document.querySelectorAll('.row.sel').forEach(r=>r.classList.remove('sel'));$('detail').innerHTML=DETAIL_EMPTY}
document.addEventListener('keydown',e=>{if(e.key!=='Escape'||['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;
 if(($('helppop')&&!$('helppop').hidden)||($('modal')&&!$('modal').hidden))return;deselect()});
// Goes-well-with: the best partners overall plus the best few of each category. "All" spreads categories out
// (each repeat of a category is discounted 15% for ordering only); a chip shows one category, best first.
function goPool(i){return (P[i]||[]).filter(([j])=>!st.excl.has(S[j][F.genre])&&!GONE.has(j))}
function goList(i){const pool=goPool(i);if(st.gcat){const f=pool.filter(([j])=>S[j][F.cat]===st.gcat);if(f.length)return f}
 const left=pool.slice(),out=[],n={};while(left.length&&out.length<30){let bk=0,bv=-1;
  left.forEach((p,k)=>{const v=p[1]*Math.pow(0.85,n[S[p[0]][F.cat]]||0);if(v>bv){bv=v;bk=k}});const p=left.splice(bk,1)[0];n[S[p[0]][F.cat]]=(n[S[p[0]][F.cat]]||0)+1;out.push(p)}
 return out}
function goChips(i){if(!P_READY)return '<div class="sub" id="goload">loading goes-with picks…</div>';if(P_FAIL&&!(P[i]||[]).length)return '<div class="sub">Goes-with picks didn\'t load (Browser-partners.js is missing). Rebuild with <code>digitalcrate build</code>.</div>';const cnt={};goPool(i).forEach(([j])=>{const c=S[j][F.cat];cnt[c]=(cnt[c]||0)+1});const cs=CATS.filter(c=>cnt[c]);if(cs.length<2)return'';
 const cur=st.gcat&&cnt[st.gcat]?st.gcat:'';
 return `<div class="chips" style="margin:6px 0 8px"><button data-gcat="" class="${cur?'':'on'}">All</button>${cs.map(c=>`<button data-gcat="${esc(c)}" class="${cur===c?'on':''}" title="${esc(c)}"><span class="badge" style="background:${col(c)};margin-right:4px">${AB[c]}</span>${cnt[c]}</button>`).join('')}</div>`}
// kits are built for everyone; the members in genres you've excluded are left out when shown, played or exported
const kitMembers=k=>k.m.filter(i=>!st.excl.has(S[i][F.genre])&&!GONE.has(i)&&!TASTE.disliked.has(S[i][F.path]));
// Kits for you (served): each starts from a vocal the taste model rates highly, chosen with some chance so ↻ deals new
// ones, then adds a pad, chords or melody, a texture, a vocal chop and a bass from that sample's goes-with picks, each
// from a different song, ranked by fit and your taste. They're re-dealt when your ratings change (★ ✕ and listening).
const KIT_ROLES=[['Pads & Atmospheres'],['Chords & Keys','Melodies & Leads'],['Textures & Field'],['Vocals'],['Pads & Atmospheres','Melodies & Leads','Bass & Sub','Strings & Orchestral']];
let KITS_FOR=null;
function dealKits(n=24){const sc=TASTE.score,ok=i=>!GONE.has(i)&&!TASTE.disliked.has(S[i][F.path])&&!st.excl.has(S[i][F.genre]);
 const ranked=S.map((_,i)=>i).filter(i=>sc[S[i][F.path]]!=null&&ok(i)).sort((a,b)=>sc[S[b][F.path]]-sc[S[a][F.path]]);
 const pct=new Map(ranked.map((i,r)=>[i,1-r/ranked.length]));
 const seeds=ranked.filter(i=>/^Vocal/.test(S[i][F.cat])&&S[i][F.sub]!=='Chops'&&(P[i]||[]).length).slice(0,400);
 // weighted draw without replacement: higher-rated seeds are likelier, but never certain
 const w=seeds.map((i,r)=>Math.exp(-r/90)*Math.random()),order=seeds.map((i,r)=>[i,w[r]]).sort((a,b)=>b[1]-a[1]).map(x=>x[0]);
 const kits=[],usedT=new Set(),perA={};
 for(const s of order){if(kits.length>=n)break;const a=S[s][F.artist];if(usedT.has(S[s][F.tid])||(perA[a]||0)>=2)continue;
  const ch=[s],tr=new Set([S[s][F.tid]]);
  for(const roles of KIT_ROLES){const fit=new Map();
   ch.forEach((c,ci)=>(P[c]||[]).forEach(([j,v])=>{if(j==null||!roles.includes(S[j][F.cat])||tr.has(S[j][F.tid])||ch.includes(j)||!ok(j))return;
    if(roles[0]==='Vocals'&&S[j][F.sub]!=='Chops')return;fit.set(j,(fit.get(j)||0)+v*(ci===0?0.6:0.4/(ch.length-1||1)))}));
   let best=null,bs=-1;fit.forEach((v,j)=>{const x=v*(0.6+0.4*(pct.get(j)??0.5));if(x>bs){bs=x;best=j}});
   if(best!=null&&bs>0.2){ch.push(best);tr.add(S[best][F.tid])}}
  if(ch.length<4)continue;usedT.add(S[s][F.tid]);perA[a]=(perA[a]||0)+1;
  const r=S[s],bpm=(ch.map(c=>S[c]).find(x=>x[F.kind]==='loop'&&x[F.bpm])||r)[F.bpm],cam=r[F.cam]||'';
  kits.push({name:`ForYou${String(kits.length+1).padStart(2,'0')}_${cam?cam.padStart(3,'0'):'xx'}-${(r[F.key]||'').replace(/[\s_]/g,'')}_${bpm?Math.round(bpm)+'bpm':'free'}_${(r[F.tags][0]||'mixed').replace(/[\s_]/g,'-')}`,m:ch,yours:true})}
 if(kits.length){D.kits.length=0;D.kits.push(...kits)}KITS_FOR=String(TASTE.n);return kits.length}
function select(i,from){edStop&&edStop();if(from==='go'&&st.sel!=null&&st.sel!==i)HIST.push({i:st.sel,scroll:$('detail').scrollTop});else if(from==='list')HIST=[];
 st.sel=i;vcur=0;document.querySelectorAll('.row').forEach(r=>r.classList.toggle('sel',+r.dataset.i===i));const s=S[i];
 const back=HIST.length?`<div style="margin-bottom:10px"><button id="back">← back to ${esc(S[HIST[HIST.length-1].i][F.artist])} — ${esc(S[HIST[HIST.length-1].i][F.title])}</button> <span class="sub">${HIST.length>1?HIST.length+' steps · ':''}Backspace</span></div>`:'';
 $('detail').innerHTML=back+`<button id="dclose" title="unselect (Esc)" style="float:right;padding:1px 7px">✕</button><span class="badge" style="background:${col(s[F.cat])}">${AB[s[F.cat]]}</span><span class="sub">${esc(s[F.cat])} / ${esc(s[F.sub])}</span>
 <div class="big">${esc(s[F.artist])} — ${esc(s[F.title])}</div>${wave(s[F.env],368,48,col(s[F.cat]))}
 <div style="margin:10px 0;display:flex;gap:6px;align-items:center">${star(s[F.path],s[F.id],`${s[F.artist]} — ${s[F.title]} · ${s[F.sub]}`)}<button data-play="${i}" class="play" style="width:auto;border-radius:6px;padding:4px 12px">▶ play</button><button id="edopen">✎ edit</button><button data-xp="${esc(s[F.path])}" title="export this clip to Ableton">⇩ export</button>${SERVED?`<button data-del="${i}" title="delete this sample (you can undo)">🗑 delete</button>`:''}
 <span class="sub">to <input id="xpname" value="${esc(xpName())}" style="width:110px;padding:2px 6px" title="export folder name under User Library/Samples/DigitalCrate"></span></div>
 <div class="ed" id="editor" hidden></div>
 ${provHTML(i)}
 <div class="kv"><span>Key</span><span>${s[F.cam]?`${s[F.cam]} · ${s[F.key]}`:'atonal'}${s[F.note]?` · root note ${s[F.note]}`:''}</span>
 <span>Tempo</span><span>${s[F.bpm]?s[F.bpm]+' bpm':'free'}${s[F.kind]==='loop'?` · ${s[F.bars]} bars`:''}</span><span>Length</span><span>${s[F.dur]} s · ${s[F.kind]}</span>
 <span>Sounds like</span><span>${esc(s[F.inst].replace('_',' '))}${s[F.tags].length?' · '+s[F.tags].map(esc).join(', '):''}</span><span>Category</span><span><select id="rcat">${Object.keys(D.subtypes).map(c=>`<option ${c===s[F.cat]?'selected':''}>${esc(c)}</option>`).join('')}</select>
 <select id="rsub">${D.subtypes[s[F.cat]].map(c=>`<option ${c===s[F.sub]?'selected':''}>${esc(c)}</option>`).join('')}</select>
 <button id="rsave" class="pill" hidden>save</button>${OVR.has(s[F.id])?' <span class="sub">(your correction)</span>':''}</span>
 <span>Source</span><span><a href="#" data-showt2="${s[F.tid]}">this track (${trk(s[F.tid]).length})</a>${rackBtn([s[F.tid]],`${s[F.artist]} - ${s[F.title]}`)}${(()=>{const a=ARTISTS.find(x=>x.name.toLowerCase()===((s[F.artist]||'Unknown artist').trim().toLowerCase()));if(!a)return'';
  const al=(D.tracks[s[F.tid]]||[])[4]||'(no album)',ts=a.albums.get(al)||[];return `${ts.length>1?` · <a href="#" data-aalb2="${esc(a.name)}|${esc(al)}">this album (${ts.reduce((x,t)=>x+t[2],0)})</a>`:''}${a.tracks.length>1?` · <a href="#" data-aall2="${esc(a.name)}">everything by ${esc(a.name)} (${a.n})</a>`:''}`})()}</span>
 <span>Genre</span><span>${esc(s[F.genre])}</span><span>Quality</span><span>${s[F.q]}</span>
 ${s[F.refm]?`<span>Echoes</span><span>${esc(s[F.refm])} <span class="sub">(${Math.round(s[F.ref]*100)}% similar)</span></span>`:''}
 <span>ID</span><span class="id" data-id="${s[F.id]}">${s[F.id]}</span></div><div class="path">${esc(s[F.path])}</div>
 ${(D.variants[i]||[]).length?`<h2>Variations (${D.variants[i].length}) <span class="sub">← → to scroll · 0 = original</span></h2>
 <div id="vars">${[[0,'original','',s[F.path]],...D.variants[i]].map(([k,t,c,p])=>`<div class="prow vrow" data-v="${k}">
 <button class="play" data-vp="${esc(p)}" data-vk="${k}">▶</button><div style="min-width:0"><div class="name">${String(k).padStart(2,'0')} · ${esc(t.replace('_',' '))}</div>
 <div class="meta">${esc(c)}</div></div>${star(p,s[F.id],`${s[F.artist]} — ${s[F.title]} · ${String(k).padStart(2,'0')} ${t}`)}${nope(p,s[F.id])}${xp(p)}</div>`).join('')}</div>`:''}
 <h2 style="display:flex;gap:6px;align-items:center"><button data-rel="go" class="${st.rel==='go'?'on':''}">Goes well with</button><button data-rel="song" class="${st.rel==='song'?'on':''}">Same song (${trk(s[F.tid]).length-1})</button>${SERVED&&st.rel==='song'?`<button data-delsong="${s[F.tid]}" title="delete every sample cut from this song, except your favourites and edits">🗑 delete this song's samples</button>`:''}${hq('goes')}</h2>
 <div class="hint">${st.rel==='go'?'▶ auditions alone · ⧉ plays it together with the selected sample':'every sample cut from this track, in song order · ⧉ plays it with the selected one'}</div>
 ${st.rel==='song'?trk(s[F.tid]).filter(j=>j!==i).map(j=>{const t=S[j];return`<div class="prow"><button class="play" data-play="${j}">▶</button>
 <div style="min-width:0"><div class="name"><span class="badge" style="background:${col(t[F.cat])}">${AB[t[F.cat]]}</span>${Math.floor(t[F.start]/60)}:${String(t[F.start]%60).padStart(2,'0')} · ${esc(t[F.sub])} · ${t[F.dur]}s${t[F.note]?' · '+t[F.note]:''}</div>
 <div class="meta">${t[F.cam]||'—'} ${esc(t[F.key])}${t[F.tags].length?' · '+t[F.tags].map(esc).join(', '):''}</div></div>
 <div style="display:flex;gap:6px;align-items:center">${star(t[F.path],t[F.id],lbl(j))}${nope(t[F.path],t[F.id])}${xp(t[F.path])}${trashBtn(j)}<button data-pair="${j}" title="play together">⧉</button><button data-go="${j}" title="open">→</button></div></div>`}).join('')
 :goChips(i)+goList(i).map(([j,sc,h,v])=>{const t=S[j];return`<div class="prow"><button class="play" data-play="${j}">▶</button>
 <div style="min-width:0"><div class="name"><span class="badge" style="background:${col(t[F.cat])}">${AB[t[F.cat]]}</span>${t[F.cam]||'—'} ${esc(t[F.key])} · ${t[F.bpm]?t[F.bpm]:'free'} · ${t[F.dur]}s</div>
 <div class="meta">${esc(t[F.artist])} — ${esc(t[F.title])}</div></div>
 <div style="display:flex;gap:6px;align-items:center"><span class="score" title="harmony ${h} · vibe ${v}">${Math.round(sc*100)}</span>${star(t[F.path],t[F.id],lbl(j))}${nope(t[F.path],t[F.id])}${xp(t[F.path])}<button data-pair="${j}" title="play together">⧉</button><button data-go="${j}" title="open">→</button></div></div>`}).join('')}`;mark()}
let vcur=0;
function playVar(k){const rows=[...document.querySelectorAll('#vars .vrow')];if(!rows.length)return;k=Math.max(0,Math.min(rows.length-1,k));vcur=k;
 const b=rows[k].querySelector('[data-vp]');stopAll();const a=new Audio(url(b.dataset.vp));a.loop=true;a.play();players.set('v'+k,a);beginListen('v'+k,b.dataset.vp);
 if(st.sel!=null)setNP(b.dataset.vp,S[st.sel][F.id],`${S[st.sel][F.artist]} — ${S[st.sel][F.title]} · variation ${String(k).padStart(2,'0')} ${rows[k].querySelector('.name').textContent.split('·').slice(1).join('·')}`,st.sel);
 rows.forEach((r,j)=>{r.style.background=j===k?'#1f2630':'';r.querySelector('.play').classList.toggle('playing',j===k)});rows[k].scrollIntoView({block:'nearest'})}
document.addEventListener('keydown',e=>{if(e.target.tagName!=='INPUT'&&e.key==='Backspace'&&HIST.length){e.preventDefault();goBack()}});
document.addEventListener('keydown',e=>{if(e.key!==' '||['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target.tagName))return;
 if(players.size||(ED&&ED.P)){e.preventDefault();e.stopImmediatePropagation();stopAll();if(ED)edPaint()}
 else if(window.SK&&SK.playing&&window.CRATE){e.preventDefault();e.stopImmediatePropagation();CRATE.skStop()}},true);
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(!document.querySelector('#vars'))return;
 if(e.key==='ArrowRight'){e.preventDefault();playVar(vcur+1)}else if(e.key==='ArrowLeft'){e.preventDefault();playVar(vcur-1)}
 else if(e.key==='0'){playVar(0)}else if(e.key===' '){e.preventDefault();stopAll();document.querySelectorAll('.vrow .play').forEach(b=>b.classList.remove('playing'))}});
function goBack(){if(!HIST.length)return;const h=HIST.pop();select(h.i,'back');$('detail').scrollTop=h.scroll}
$('detail').addEventListener('change',e=>{if(e.target.id==='xpname'){setXpName(e.target.value.trim());toast(`clips will export to ${xpName()}`);return}
 if(e.target.id==='rcat'){const c=e.target.value;
  $('rsub').innerHTML=D.subtypes[c].map(x=>`<option ${x===S[st.sel][F.sub]?'selected':''}>${esc(x)}</option>`).join('');$('rsave').hidden=false}
 else if(e.target.id==='rsub')$('rsave').hidden=false});
async function recat(i,cat,sub){cat=cat||$('rcat').value;sub=sub||$('rsub').value;if(!SERVED){alert('needs the local server');return}
 const was=[S[i][F.cat],S[i][F.sub]];if($('rsave'))$('rsave').textContent='saving…';
 const r=await (await fetch('api/recat',{method:'POST',body:JSON.stringify({id:S[i][F.id],category:cat,subtype:sub})})).json();
 if(r.error){if($('rsave'))$('rsave').textContent='error';return}const old=S[i][F.path];
 if(window.actPush&&!window.ACT_QUIET)actPush(`moved ${S[i][F.artist]} — ${was[1]} to ${cat} / ${sub}`,()=>recat(i,was[0],was[1]),true);
 S[i][F.cat]=r.category;S[i][F.sub]=r.subtype;S[i][F.path]=r.path;byPath.delete(old);byPath.set(r.path,i);OVR.add(S[i][F.id]);
 if(FAV.has(old)){const f=FAV.get(old);FAV.delete(old);f.path=r.path;FAV.set(r.path,f)}
 const row=document.querySelector(`.row[data-i="${i}"]`);if(row)row.outerHTML=rowHTML(i);if(st.sel===i){const sc=$('detail').scrollTop;select(i,'back');$('detail').scrollTop=sc}}
$('detail').addEventListener('click',e=>{if(e.target.id==='back'){goBack();return}
 const s2=e.target.closest('[data-showt2]');if(s2){e.preventDefault();showTracks([s2.dataset.showt2],{label:`${S[st.sel][F.artist]} — ${S[st.sel][F.title]}`});return}
 const aa=e.target.closest('[data-aall2]');if(aa){e.preventDefault();const a=artistBy(aa.dataset.aall2);showTracks(a.tracks,{label:a.name});return}
 const ab=e.target.closest('[data-aalb2]');if(ab){e.preventDefault();const [n,al]=ab.dataset.aalb2.split('|');const a=artistBy(n);showTracks(a.albums.get(al).map(x=>x[0]),{label:`${a.name} — ${al}`});return}
 if(e.target.id==='rsave'){recat(st.sel);return}
 if(e.target.id==='edopen'){openEditor(st.sel);return}
 const g2=e.target.closest('[data-go2]');if(g2){e.preventDefault();select(+g2.dataset.go2,'go');return}
 const gc=e.target.closest('[data-gcat]');if(gc){st.gcat=gc.dataset.gcat;const sc=$('detail').scrollTop;select(st.sel,'back');$('detail').scrollTop=sc;return}
 const rb=e.target.closest('[data-rel]');if(rb){st.rel=rb.dataset.rel;const sc=$('detail').scrollTop;select(st.sel,'back');$('detail').scrollTop=sc;return}
 const vb=e.target.closest('[data-vk]');if(vb){const k=+vb.dataset.vk;
 if(players.has('v'+k)){stopAll();vb.classList.remove('playing')}else playVar(k);return}
 const t=e.target.closest('[data-play],[data-pair],[data-go],[data-id]');if(!t)return;
 if(t.dataset.play!=null)toggle(+t.dataset.play,t);else if(t.dataset.pair!=null)playTogether([st.sel,+t.dataset.pair]);
 else if(t.dataset.go!=null){select(+t.dataset.go,'go');$('detail').scrollTop=0}else if(t.dataset.id){navigator.clipboard&&navigator.clipboard.writeText(t.dataset.id)}});
render();requestAnimationFrame(()=>setTimeout(loadPartners,0));loadFavs();loadTaste();
// deep link: #edit=<id>[&sel=a,b][&fi=ms][&fo=ms][&xf=ms][&loop=0|1][&zoom=1]
(async()=>{const h=new URLSearchParams(location.hash.slice(1));if(h.get('tracks')){showTracks(h.get('tracks').split(','));return}const id=h.get('edit')||h.get('s');if(!id||!BYID.has(id))return;
 const i=BYID.get(id);select(i,'list');if(!h.get('edit'))return;await openEditor(i);
 if(h.get('loop'))$('edloop').checked=h.get('loop')==='1';[['fi','edfi'],['fo','edfo'],['xf','edxf']].forEach(([k,el])=>{if(h.get(k)){$(el).value=h.get(k);$(el).dispatchEvent(new Event('input'))}});
 if(h.get('sel')){ED.sel=h.get('sel').split(',').map(Number)}if(h.get('zoom'))edZoom('sel');edDraw()})();
</script>
<link rel="stylesheet" href="studio/studio.css"><script src="studio/studio.js"></script></body></html>"""
