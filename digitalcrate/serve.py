"""Local server for Browser.html: serves the library and handles favourites.

    python -m digitalcrate serve        ->  http://localhost:8765

Favourites are stored in SQLite and hardlinked into SampleLibrary/Favorites/<category>/ so they show up
in Ableton's browser straight away. Works for library samples and for variation-family files alike.
"""
import json
import os
import shutil
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path
from urllib.parse import unquote

from . import config as C
from .db import connect

FAV_DIR = C.LIB_ROOT / "Favorites"
JOBS = {}  # id -> dict(target, proc, log)


def _jobs_file():
    return C.DATA_DIR / "jobs.json"


def _saved_jobs():
    try:
        return json.loads(_jobs_file().read_text())
    except Exception:
        return {}


BACKGROUND = {"styles", "lyrics", "credits", "reloop", "loops", "sections", "pads", "grain", "stems", "reco"}
_SLOW = {}


LABELS = dict(pads="pads", grain="separation grain", stems="stems for Mashup", sections="song sections",
              styles="styles", lyrics="words", loops="sustain loops", process="mining", drums="drums",
              ytscout="scout", ingest="adding a source", reco="measuring recommenders")


def start_job(kind, args, target):
    import subprocess, sys, time
    for jid, j in _saved_jobs().items():  # the same job already running (a double click): that one, not a second copy
        if j["kind"] == kind and j.get("args") == list(args) and _alive(j["pid"]):
            return jid
    jid = str(int(time.time() * 1000))
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logf = C.DATA_DIR / f"{kind}_{jid}.log"
    import os
    cmd = [sys.executable, "-u", "-m", "digitalcrate", kind] + args
    env = dict(os.environ)
    nice = 0
    if kind in BACKGROUND:  # library-wide passes: a few cores and low priority, so the app stays quick meanwhile
        env.update({k: "3" for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                                     "OPENBLAS_NUM_THREADS", "DC_THREADS")})
        nice = 15
    elif kind == "process":  # a mining run: most of the machine, but the app comes first
        nice = 5
    proc = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent.parent), stdout=open(logf, "w"),
                            stderr=subprocess.STDOUT, start_new_session=True, env=env,  # survives a server restart
                            preexec_fn=(lambda: os.nice(nice)) if nice else None)
    JOBS[jid] = dict(kind=kind, target=target, proc=proc, log=logf)
    saved = _saved_jobs()
    saved[jid] = dict(kind=kind, target=target, pid=proc.pid, log=str(logf), started=time.time(), args=list(args))
    _jobs_file().write_text(json.dumps(dict(list(saved.items())[-40:])))
    return jid


def _alive(pid):
    import os
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a finished child the server started is a zombie until reaped
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


_STOPPED = set()


def stop_job(jid):
    import os, signal
    j = _saved_jobs().get(jid)
    if j and _alive(j["pid"]):
        # the run stops between songs' work; unfinished songs stay unmined. A second Stop on a job that is still
        # there (it ignores the first: deep in a library call, or waiting) ends it outright.
        os.kill(j["pid"], signal.SIGTERM if jid in _STOPPED else signal.SIGINT)
        _STOPPED.add(jid)
        return True
    return False


_PARSED = {}


def _parse_log(txt):
    import re
    bars = re.findall(r"(\w+):\s+(\d+)%\|[^|]*\|\s*(\d+)/(\d+) \[([\d:]+)<([\d:?]+)", txt)
    now = re.findall(r"^NOW (.+)$", txt, re.M)
    made = re.findall(r"^  (.+?): (\d+) samples", txt, re.M)
    m = re.search(r"done: (\d+) samples written", txt)
    lines = [l for l in re.split(r"[\r\n]+", txt) if l.strip() and not re.search(
        r"Warning|warn|redirects|Loading weights|\d+%\|", l)]
    return dict(progress=[int(bars[-1][2]), int(bars[-1][3])] if bars else None,
                elapsed=bars[-1][4] if bars else None, eta=bars[-1][5] if bars else None,
                _now=now[-1] if now else None, songs=len(made),
                samples=int(m.group(1)) if m else sum(int(x[1]) for x in made),
                errors=txt.count("  ERROR "), building="BUILDING" in txt and "BUILD DONE" not in txt,
                finished=bool(m) or "BUILD DONE" in txt or "INGEST DONE" in txt or "SCOUT DONE" in txt or "TASK DONE" in txt,
                tail=lines[-8:])


def activity():
    """Every processing job the app started (also from before a restart), with progress parsed from its log, plus
    mining runs started from a terminal."""
    import re, subprocess, time
    out = []
    for jid, j in sorted(_saved_jobs().items(), reverse=True):
        f = Path(j["log"])
        running = _alive(j["pid"])
        try:
            st = f.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        got = _PARSED.get(jid)
        if not got or got[0] != sig:  # a log is read and parsed again only when it has changed
            got = _PARSED[jid] = (sig, _parse_log(f.read_text(errors="ignore") if sig else ""))
        d = dict(got[1])
        now = d.pop("_now")
        out.append(dict(id=jid, kind=j["kind"], target=j["target"], running=running, started=j.get("started"),
                        now=now if running else None, **d))
    mine = {j["pid"] for j in _saved_jobs().values()}
    try:
        ps = subprocess.run(["ps", "-axo", "pid=,etime=,command="], capture_output=True, text=True).stdout
        for l in ps.splitlines():
            pid, et, cmd = l.strip().split(None, 2)
            if "python" in cmd.split()[0].rsplit("/", 1)[-1].lower() and "digitalcrate" in cmd and re.search(r"digitalcrate\W+(process|drums|scout|build|ingest|transform|mangle|lyrics|styles|embed|beats|credits|reloop)\b|process import run|\.build import", cmd) \
                    and int(pid) not in mine and "grep" not in cmd:
                out.append(dict(id="pid" + pid, kind="terminal", target=cmd[-160:], running=True, elapsed=et, external=True))
    except Exception:
        pass
    return out


TASKS = {  # library-wide analyses the Processing page can start: (label, SQL for done, SQL for total)
    "sections": ("Find song sections (intro, verse, chorus, break, outro)", "SELECT COUNT(*) FROM sections",
                 "SELECT COUNT(*) FROM tracks WHERE status='done' AND id IN (SELECT track_id FROM samples)"),
    "pads": ("Sort real pads (1-2 chords, still) from strings & orchestral passages",
             "SELECT COUNT(*) FROM samples WHERE chords IS NOT NULL AND kind != 'oneshot' "
             "AND category IN ('Pads & Atmospheres','Strings & Orchestral','Chords & Keys')",
             "SELECT COUNT(*) FROM samples WHERE kind != 'oneshot' AND (category IN ('Pads & Atmospheres',"
             "'Strings & Orchestral') OR chords IS NOT NULL)"),
    "grain": ("Check stem samples for separation grain (grainy ones rank lower)",
              "SELECT COUNT(*) FROM samples WHERE grain IS NOT NULL AND rendered_from = 'other'",
              "SELECT COUNT(*) FROM samples WHERE rendered_from = 'other' AND parent_id IS NULL AND category != 'Percussion'"),
    "loops": ("Find sustain loops (pads, drones, held chords)", "SELECT COUNT(*) FROM samples WHERE loop_q IS NOT NULL "
              "AND category IN ('Pads & Atmospheres','Strings & Orchestral','Textures & Field','Chords & Keys','Vocal Atmospheres') "
              "AND kind != 'loop' AND dur >= 1.5",
              "SELECT COUNT(*) FROM samples WHERE category IN ('Pads & Atmospheres','Strings & Orchestral','Textures & Field','Chords & Keys',"
              "'Vocal Atmospheres') AND kind != 'loop' AND dur >= 1.5"),
    "styles": ("Tag styles (Discogs, from the audio)", "SELECT COUNT(*) FROM styles",
               "SELECT COUNT(*) FROM tracks WHERE status != 'duplicate'"),
    "credits": ("Check sample credits (MusicBrainz; pop, soul, ambient, untagged…)", "SELECT COUNT(*) FROM mb",
                None),
    "lyrics": ("Transcribe words in vocals (Whisper)",
               "SELECT COUNT(*) FROM words w JOIN samples s ON s.id=w.sample_id WHERE s.dur >= 0.8",
               "SELECT COUNT(*) FROM samples WHERE category IN ('Vocals','Vocal Atmospheres') AND dur >= 0.8 "
               "AND path NOT LIKE '_Reference/%'"),
}


def analysis():
    from .db import connect
    con, out = connect(), []
    running = {j["kind"] for j in activity() if j["running"]}
    for k, (label, done_q, total_q) in TASKS.items():
        if k == "pads":
            from .pads import _db as _pads_db
            _pads_db()  # its columns
        if k == "sections":
            from .sections import available
            if not available():  # optional: only offered once All-In-One is installed
                continue
        try:
            done = con.execute(done_q).fetchone()[0]
        except Exception:  # its table doesn't exist until the first run
            done = 0
        if total_q is None:  # credits: the unmined songs in genres where sampling is likely
            from .batches import _pool
            from .mbz import RISKY
            rows, fam, _ = _pool(con)
            seen = {r[0] for r in con.execute("SELECT track_id FROM mb")} if done else set()
            total = done + sum(1 for r, f in zip(rows, fam) if f in RISKY and r["id"] not in seen)
        else:
            total = con.execute(total_q).fetchone()[0]
        out.append(dict(task=k, label=label, done=done, total=total, running=k in running))
    return out


def start_ingest(target, drums):
    return start_job("ingest", [target] + (["--drums"] if drums else []), target)


def job_status(kind=None):
    import re
    out = []
    for jid, j in sorted(JOBS.items()):
        if kind and j.get("kind", "ingest") != kind:
            continue
        txt = j["log"].read_text(errors="ignore") if j["log"].exists() else ""
        lines = [l for l in re.split(r"[\r\n]+", txt) if l.strip() and not re.search(r"Warning|warn|redirects|Loading weights", l)]
        rc = j["proc"].poll()
        m = re.search(r"INGEST TRACKS ([\d,]+)", txt)
        out.append(dict(id=jid, kind=j.get("kind"), target=j["target"], running=rc is None,
                        ok=rc == 0 and ("INGEST DONE" in txt or "SCOUT DONE" in txt),
                        tracks=m.group(1) if m else "", tail=[l for l in lines if not l.startswith("INGEST TRACKS")][-6:]))
    return out


def _db():
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS favorites (path TEXT PRIMARY KEY, sample_id TEXT,
                   label TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    return con


def _fav_target(rel):
    p = Path(rel)
    parts = p.parts
    if parts[0] == "Variations":           # Variations/<cat>/<family>/<NN name>.wav
        cat = parts[1] if len(parts) > 3 else "Variations"
        return FAV_DIR / cat / f"{parts[-2][:60]} — {p.name}"
    return FAV_DIR / (parts[0] if len(parts) > 1 else "Misc") / p.name


def set_fav(rel, on, sample_id=None, label=None):
    rel = rel.lstrip("/")
    src = (C.LIB_ROOT / rel).resolve()
    if C.LIB_ROOT.resolve() not in src.parents or not src.exists():
        raise ValueError("not a library file")
    con = _db()
    dst = _fav_target(rel)
    if on:
        con.execute("INSERT OR REPLACE INTO favorites(path, sample_id, label) VALUES (?,?,?)", (rel, sample_id, label))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    else:
        con.execute("DELETE FROM favorites WHERE path=?", (rel,))
        dst.unlink(missing_ok=True)
        if dst.parent.exists() and not any(dst.parent.iterdir()):
            dst.parent.rmdir()
    con.commit()


def _sketch_db():
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS sketches (name TEXT PRIMARY KEY, state TEXT,
                   updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    return con


def bounce(req):
    """Audio rendered in the browser (chop-pad pattern, sketch mixdown) -> a new sample with provenance."""
    import base64, io
    import numpy as np
    import soundfile as sf
    from .edit import store
    y, sr = sf.read(io.BytesIO(base64.b64decode(req["wav"])), dtype="float32", always_2d=True)
    y = y.T
    if y.shape[0] == 1:
        y = np.repeat(y, 2, 0)
    if sr != C.SR:
        from scipy.signal import resample_poly
        y = resample_poly(y, C.SR, sr, axis=1).astype(np.float32)
    y *= 0.891 / (np.abs(y).max() + 1e-9)
    con = connect()
    parent = con.execute("SELECT s.*, t.artist, t.title FROM samples s JOIN tracks t ON t.id=s.track_id WHERE s.path=?",
                         (unquote(req["parent"]),)).fetchone()
    if parent is None:
        raise ValueError("bounces start from a library sample")
    p = dict(semis=float(req.get("semis") or 0))
    if req.get("key"):
        p["tune_key"] = req["key"]   # sketch/pads conformed to a project key: store that key
    ov = dict(kind=req.get("kind", "loop"), bpm=req.get("bpm"), bars=req.get("bars"), tag=req.get("tag", "bounce"),
              category=req.get("category"),
              ops=dict(bounce=req.get("ops") or {}))
    row = store(parent, parent["path"], y, p, req.get("name") or None, override=ov, prefix=req.get("prefix", "Bounce"))
    from .taste import log_event
    log_event(row["path"], "star", 1, row["id"])
    set_fav(row["path"], True, row["id"], f"{req.get('tag', 'bounce')} from {parent['artist']} — {parent['title']}")
    return row



def _with_partners(row):
    """Attach fresh 'goes well with' picks to a newly saved sample. If scoring fails, the browser
    falls back to the source clip's picks, so the save itself still succeeds."""
    try:
        from .build import partners_for
        row["partners"] = partners_for(row["id"])
    except Exception as e:
        print("partners for new sample failed:", e)
    return row

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        if self.path.endswith(".html") or self.path in ("/", "/Browser.html") or self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _dealt(self, SM, part, rec, surface, deal, req):
        """A deal's impression: written now (its id goes back with the part), or kept for later if prefetched."""
        extra = {k: req[k] for k in ("list", "rank") if req.get(k) is not None}
        if deal == "pre":
            part["pre"] = SM.deal(rec, surface, deal, pre=True, extra=extra)
        else:
            part["imp"] = SM.deal(rec, surface, deal, extra=extra)
            if deal == "best" and req.get("list") is not None and req.get("rank") is not None:
                SM.listed(req["list"], req["rank"])

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, f, ctype, headers=None):
        data = Path(f).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _setup(self, req):
        """First-run setup (static/setup.html) and the quit button."""
        import threading
        from . import app
        if self.path == "/api/setup/choose":
            path = app.choose_folder(req.get("prompt", "Choose a folder"), req.get("start"))
            return self._json(dict(path=path, **(app.count_audio(path) if path and req.get("count") else {})))
        if self.path == "/api/setup/count":
            return self._json(app.count_audio(req["path"]))
        if self.path == "/api/setup/save":
            res = app.save_config(req["music"], req["library"])
            self._json(dict(res, restarting=True))
            threading.Thread(target=_restart, daemon=True).start()  # the folders are read at start-up
            return
        if self.path == "/api/setup/start":
            if any(j["running"] and j["kind"] in ("firstrun", "process", "terminal") for j in activity()):
                return self._json({"error": "already running"}, 409)
            n = max(5, min(200, int(req.get("n", 25))))
            return self._json({"job": start_job("firstrun", ["--mine", str(n)], f"first run: {n} songs")})
        if self.path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), HTTPD.shutdown()), daemon=True).start()
            return
        return self._json({"error": "unknown"}, 404)

    def do_GET(self):
        from . import app
        if self.path == "/api/ping":
            return self._json({"ok": True})
        if self.path == "/api/setup/state":
            st = app.state()
            st["job"] = next((j for j in activity() if j["kind"] == "firstrun"), None)
            if st["job"]:
                import re
                f = Path(_saved_jobs().get(st["job"]["id"], {}).get("log", ""))
                txt = f.read_text(errors="ignore") if f.is_file() else ""
                steps = re.findall(r"^STEP (\d)/4 (.+)$", txt, re.M)
                st["job"]["step"] = [int(steps[-1][0]), steps[-1][1]] if steps else None
            return self._json(st)
        if self.path in ("/", "/setup", "/Browser.html") and (self.path == "/setup" or not app.configured()
                                                             or not (C.LIB_ROOT / "Browser.html").exists()):
            return self._file(Path(__file__).resolve().parent / "static" / "setup.html", "text/html",
                              {"Cache-Control": "no-store"})
        if self.path == "/":
            self.path = "/Browser.html"
        if self.path == "/Browser.html" and not (C.LIB_ROOT / "Browser.html").exists():
            msg = (f"<body style='font:16px system-ui;background:#0e1013;color:#e6e6e6;padding:40px'><h2>No library yet</h2>"
                   f"<p>{C.LIB_ROOT} has no Browser.html. Mine some music first:</p><pre>python -m digitalcrate scan\n"
                   f"python -m digitalcrate process --top 50\npython -m digitalcrate build</pre><p>then reload this page.</p></body>")
            body = msg.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split("?")[0] in ("/pairtest", "/drumlabel"):
            return self._file(Path(__file__).resolve().parent / "static" / (self.path.split("?")[0][1:] + ".html"),
                              "text/html", {"Cache-Control": "no-store"})
        if self.path.split("?")[0] == "/taste":
            return self._file(Path(__file__).resolve().parent / "static" / "taste.html", "text/html",
                              {"Cache-Control": "no-store"})
        if self.path.split("?")[0] == "/api/sets":
            from urllib.parse import parse_qs, urlparse
            from .sets import sets
            q = parse_qs(urlparse(self.path).query)
            return self._json(sets(collection=(q.get("collection") or [None])[0]))
        if self.path.startswith("/api/live/new"):
            from urllib.parse import parse_qs, urlparse
            from .live import new_rows
            q = parse_qs(urlparse(self.path).query)
            return self._json(new_rows(int((q.get("since") or ["0"])[0])))
        if self.path.startswith("/api/slices?"):
            from urllib.parse import parse_qs, urlparse
            from .ableton import segments
            q = parse_qs(urlparse(self.path).query)
            return self._json({"slices": segments(unquote(q["path"][0]), int((q.get("n") or ["16"])[0]), 0.05)})
        if self.path == "/api/libroot":
            return self._json({"root": str(C.LIB_ROOT)})
        if self.path == "/api/collections":
            from .collections_ import listing
            return self._json(listing())
        if self.path.startswith("/api/taste/explain"):
            from .taste_report import explain
            return self._json(explain())
        if self.path.split("?")[0] == "/activity":
            return self._file(Path(__file__).resolve().parent / "static" / "activity.html", "text/html",
                              {"Cache-Control": "no-store"})
        if self.path.split("?")[0] == "/shootout":
            return self._file(Path(__file__).resolve().parent / "static" / "shootout.html", "text/html",
                              {"Cache-Control": "no-store"})
        if self.path.startswith("/studio/"):
            name = Path(unquote(self.path.split("?")[0])).name
            f = Path(__file__).resolve().parent / "static" / name
            if f.exists():
                types = {".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml", ".png": "image/png"}
                return self._file(f, types.get(f.suffix, "application/octet-stream"), {"Cache-Control": "no-store"})
        if self.path.startswith("/api/why?"):
            from urllib.parse import parse_qs, urlparse
            from .taste import why
            return self._json(why(parse_qs(urlparse(self.path).query)["path"][0]))
        if self.path.startswith("/api/taste"):
            from .taste import compact, scores_payload
            recent = 3 if "recent=1" in self.path else None
            p = scores_payload(recent)
            if p and recent is None:  # the "for you" and discover rankings it makes, logged once the page has them
                from .reco import live
                fav = {r[0] for r in _db().execute("SELECT path FROM favorites")}
                p["served"] = live.served(p, fav)
            out = compact(p) if "ids=1" in self.path else p
            if p and "ids=1" in self.path:
                out["served"] = p.get("served")
            return self._json(out)
        if self.path.startswith("/api/onsets?"):
            from urllib.parse import parse_qs, urlparse
            from .edit import onsets
            return self._json(onsets(parse_qs(urlparse(self.path).query)["path"][0]))
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/search":
                from .search import text_search
                return self._json(text_search(q["q"], int(q.get("k", 400))))
            if u.path == "/api/galaxy":
                from .search import galaxy
                return self._json(galaxy())
            if u.path == "/api/conform":
                from .conform import render
                f, info = render(q["path"], q.get("key") or None, float(q["bpm"]) if q.get("bpm") else None,
                                 float(q["src"]) if q.get("src") else None)
                return self._file(f, "audio/wav", {"X-Conform": json.dumps(info)})
            if u.path == "/api/chords":
                from .harmony import suggest
                return self._json(suggest(q["path"], float(q["bpm"]) if q.get("bpm") else None, int(q.get("bpc", 1))))
            if u.path == "/api/pulse":
                from .conform import pulse
                return self._json(pulse(q["path"]))
            if u.path == "/api/conform/info":
                from .conform import lookup, plan
                row, shift = lookup(q["path"])
                se, ti, info = plan(row, shift, q.get("key") or None, float(q["bpm"]) if q.get("bpm") else None)
                return self._json(dict(info, semis=se, time=ti))
            if u.path == "/api/midi":
                from .midi import transcribe
                return self._json(transcribe(q["path"], float(q["bpm"]) if q.get("bpm") else None))
            if u.path == "/api/tune/report":
                from .edit import _load
                from .retune import report
                return self._json(report(_load(q["path"]), q["key"]))
            if u.path == "/api/link":
                from .link import status
                return self._json(status())
            if u.path == "/api/plugins":
                from .plugins import scan
                return self._json(scan())
            if u.path == "/api/plugins/params":
                from .plugins import scan, params
                if q.get("path") not in {x["path"] for x in scan()}:
                    return self._json({"error": "not an installed plugin"}, 400)
                try:
                    return self._json(params(q["path"]))
                except Exception as e:
                    return self._json({"error": f"couldn't load it: {str(e)[:160]}"})
            if u.path == "/api/related-artists":
                from .mbz import related_artists
                try:
                    return self._json(related_artists())
                except Exception as e:
                    return self._json(dict(seeds=[], artists=[], error=str(e)[:200]))
            if u.path == "/api/takes":  # alternate-take groups, by sample id: for samples newer than the page too
                from .takes import groups as take_groups
                con = _db()
                n = con.execute("SELECT COUNT(*), MAX(rowid) FROM samples").fetchone()
                key = (n[0], n[1])
                if _SLOW.get("takes_key") != key:
                    _SLOW.update(takes_key=key, takes=take_groups(con))
                return self._json(dict(groups=_SLOW["takes"]))
            if u.path == "/api/drums/takes":
                from .drumkit import takes
                return self._json(dict(takes=takes(q.get("path", ""))))
            if u.path == "/api/ytscout":
                from .ytscout import results, PRESETS, auto_state, learned
                from .related import guided_queries, profile
                try:
                    prof, gq = profile(), guided_queries()
                except Exception:  # styles not analysed yet
                    prof, gq = dict(styles=[]), []
                return self._json(dict(presets=dict(PRESETS, guided=[g["query"] for g in gq]), guided=gq,
                                       profile=prof, results=results(q.get("q") or None), auto=auto_state(),
                                       learned=learned()))
            if u.path == "/api/shootout":
                from .shootout import manifest, votes, results
                return self._json(dict(manifest(q.get("round")), votes=votes(), results=results()))
            if u.path == "/api/pairtest":
                from .listening import pair_manifest, _db as listen_db
                m = pair_manifest([g for g in q.get("excl", "").split("|") if g], new=q.get("new") == "1")
                v = {r["trial"]: r["rating"] for r in listen_db().execute("SELECT * FROM pair_votes")}
                return self._json(dict(m, votes=v))
            if u.path == "/api/pairtest/results":
                from .listening import pair_results
                return self._json(pair_results())
            if u.path == "/api/drumlabel":
                from .listening import drum_manifest, drum_labels
                return self._json(dict(drum_manifest(new=q.get("new") == "1"), labels=drum_labels()))
            if u.path == "/api/sketches":
                return self._json([dict(r) for r in _sketch_db().execute("SELECT * FROM sketches ORDER BY updated_at DESC")])
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        if u.path == "/api/activity":
            from .batches import coverage
            if q.get("jobs") == "1":  # the main page's badge: just what's running
                return self._json(dict(jobs=[j for j in activity() if j["running"]]))
            from .backup import last_backup
            import time as _t
            if _t.time() - _SLOW.get("at", 0) > 20:  # library stats change slowly; the page polls every 3 s in a run
                _SLOW.update(at=_t.time(), coverage=coverage(), analysis=analysis())
            from .memguard import paused_jobs
            return self._json(dict(jobs=activity(), coverage=_SLOW["coverage"], backup=last_backup(),
                                   analysis=_SLOW["analysis"], paused=paused_jobs()))
        if u.path == "/api/jobs":
            return self._json(job_status(q.get("kind")))
        if self.path == "/api/favs":
            rows = _db().execute("SELECT path, sample_id, label, added_at FROM favorites ORDER BY added_at DESC")
            return self._json([dict(r) for r in rows])
        rel = unquote(u.path.lstrip("/"))
        if rel and not (C.LIB_ROOT / rel).exists():  # a sample that was moved (pads sorted out, recategorised)
            try:
                r = _db().execute("SELECT new FROM moved WHERE old=?", (rel,)).fetchone()
            except Exception:
                r = None
            if r:
                from urllib.parse import quote
                self.send_response(301)
                self.send_header("Location", "/" + quote(r["new"]))
                self.end_headers()
                return
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            from .taste import log_event
            path = unquote(req.get("path") or "")  # (a null path is no path)
            if self.path == "/api/fav":
                on = bool(req.get("on", True))
                set_fav(path, on, req.get("id"), req.get("label"))
                log_event(path, "star" if on else "unstar", 1, req.get("id"))
            elif self.path == "/api/edit/preview":
                from .edit import preview
                return self._json({"url": preview(path, req.get("params", {}))})
            elif self.path == "/api/edit/save":
                from .edit import save
                row = save(path, req.get("params", {}), req.get("name") or None)
                log_event(row["path"], "star", 1, row["id"])  # you made it: counts as a like
                set_fav(row["path"], True, row["id"], f"edit of {req.get('label', path)}")
                return self._json({"row": _with_partners(row)})
            elif self.path.startswith("/api/setup/") or self.path == "/api/quit":
                return self._setup(req)
            elif self.path == "/api/suggest":
                from .suggest import suggest_now
                return self._json(suggest_now(path, req.get("project_key") or None, req.get("start"), req.get("end"),
                                              log=not req.get("nolog")))
            elif self.path == "/api/suggest/prefetch":
                from .suggest import prefetch
                return self._json(prefetch(path, req.get("project_key") or None, req.get("start"), req.get("end")))
            elif self.path == "/api/suggest/rate":
                from .suggest import rate, stale
                stale(path)
                return self._json(rate(path, int(req.get("rating", 0)), req.get("reason") or None, req.get("params"),
                                       req.get("move"), req.get("family"), req.get("material"), req.get("arm"),
                                       req.get("source") or "suggestion"))
            elif self.path == "/api/suggest/feedback":
                from .suggest import feedback, stale
                if req.get("action") != "play":
                    stale(path)
                feedback(path, req.get("id"), req.get("move"), req.get("family"), req.get("arm"), req.get("material"),
                         req.get("action"))
            elif self.path == "/api/reveal":  # show a library file in Finder, selected (to drag it into Live)
                import subprocess
                f = (C.LIB_ROOT / path).resolve()
                if C.LIB_ROOT.resolve() not in f.parents or not f.exists():
                    return self._json({"error": "not a library file"}, 400)
                subprocess.Popen(["open", "-R", str(f)])
                return self._json({"ok": True})
            elif self.path.startswith("/api/stems/"):
                from . import stems as SM
                what, state = self.path.rsplit("/", 1)[1], req.get("state") or {}
                if what == "library":
                    lib = SM.library()
                    return self._json(dict(n=len(lib), rated=SM.rated(), songs=[
                        dict(track=t, artist=m["artist"], title=m["title"], bpm=m["bpm"], bars=len(m["bars"]) - 1,
                             key=SM.NOTES[m["pc"]] + ("m" if m["scale"] == "minor" else ""), stems=m["stems"], tops=SM.tops_ready(t, m))
                        for t, m in lib.items()]))
                deal = req.get("deal")  # sent by the mixer when it deals (a check of fit etc. is not a deal): recorded
                if what == "pick":
                    rec = {} if deal else None
                    part = SM.pick(req["stem"], state, avoid=set(req.get("avoid") or []), n=req.get("n"),
                                   track=req.get("track"), slot=req.get("slot"), rec=rec)
                    if part and rec:
                        surface = "mashup.best" if deal == "best" else "mashup.find" if req.get("track") is not None \
                            else "mashup.dice"
                        self._dealt(SM, part, rec, surface, deal, req)
                    return self._json(dict(part=part, info=SM.info(state)))
                if what == "dealt":  # a prefetched deal was played
                    return self._json(dict(imp=SM.dealt(str(req.get("pre") or ""), req.get("via"))))
                if what == "outcome":
                    return self._json(dict(logged=SM.outcomes(req.get("out") or [])))
                if what == "render":
                    with_tops = req["stem"] in SM.DRUM_ROLES and SM.tops_prepared(req["track"])
                    f = SM.render(req["track"], req["stem"], req["bar0"], req["n"], req["bpm"], req.get("semis") or 0,
                                  req.get("k") or 1, legacy=req.get("legacy") is True, with_tops=with_tops, cond=req.get("cond"),
                                  cut=req.get("cut"), xf=req.get("xf") or 0)
                    return self._json(dict(url=str(f.relative_to(C.LIB_ROOT)), sub=SM.sub_share(f),
                                           whole=req["stem"] == "drums" and not with_tops))
                if what == "peaks":
                    picture = SM.peaks(req["track"], req["stem"])
                    picture["url"] = str(picture.pop("path").relative_to(C.LIB_ROOT))
                    return self._json(picture)
                if what == "oswarp":
                    f = SM.oneshot_warp(req["sample"], req.get("key"), req.get("trim"), float(req["beats"]),
                                        float(req.get("bpm") or 100), float(req.get("semis") or 0))
                    return self._json(dict(url=str(f.relative_to(C.LIB_ROOT))))
                if what == "export":
                    return self._json(SM.export(req.get("name") or "Mashup", float(req.get("bpm") or 100), req.get("key"),
                                                req.get("sections") or [], req.get("bars") or 8, req.get("reveal", True)))
                if what == "best":
                    rec = {} if deal else None
                    parts = SM.top_fits(req["role"], state, req.get("slot"), req.get("n"), req.get("top") or 12, rec=rec,
                                        song=req.get("song"))
                    return self._json(dict(parts=parts, imp=SM.deal(rec, "mashup.best_list", deal) if parts else None))
                if what == "oneshot":
                    pad = req.get("kind") == "pad"
                    rec = {} if deal else None
                    fn = SM.pad if pad else SM.oneshot
                    part = fn(state, req.get("n") or (4 if pad else 1), set(req.get("avoid") or []), path=req.get("path"),
                              rec=rec, slot=req.get("slot"))
                    if part and rec:
                        surface = "mashup.best" if deal == "best" else "mashup.find" if req.get("path") \
                            else "mashup.pad" if pad else "mashup.oneshot"
                        self._dealt(SM, part, rec, surface, deal, req)
                    return self._json(dict(part=part, info=SM.info(state)))
                if what == "info":
                    return self._json(SM.info(state))
                if what == "alts":
                    return self._json(dict(alts=SM.alts(state, req["slot"])))
                if what == "save":
                    SM.save(req["name"], req["mix"], state, req.get("outs"))
                    return self._json(dict(ok=True, rated=SM.rated()))
                if what == "saved":
                    return self._json(dict(mixes=SM.mixes()))
                if what == "delete":
                    SM.delete_mix(req["name"])
                    return self._json(dict(ok=True))
                if what == "event":
                    n = SM.log(req["kind"], state, req.get("stem"))
                    return self._json(dict(logged=n, rated=SM.rated()))
                return self._json({"error": "unknown"}, 404)
            elif self.path == "/api/pad/playable":
                from .pads import playable
                return self._json(playable(path, reveal=req.get("reveal", True)))
            elif self.path == "/api/drums/export":
                from .drumexport import drum_export
                return self._json(drum_export(req.get("name") or "Drums", float(req.get("bpm") or 120), int(req.get("bars") or 1),
                                              float(req.get("swing") or 0), req.get("pads") or [], reveal=req.get("reveal", True)))
            elif self.path == "/api/drumkit":
                from .drumkit import complete
                return self._json(complete(req.get("paths") or [], int(req.get("per", 30)), req.get("kinds"),
                                           req.get("steer"), bool(req.get("everything"))))
            elif self.path.startswith("/api/collections/"):
                from . import collections_ as CO
                op = self.path.rsplit("/", 1)[1]
                if op == "add":
                    return self._json(CO.add(req["name"], path, req.get("id")))
                if op == "remove":
                    return self._json(CO.remove(req["name"], path))
                if op == "create":
                    return self._json(CO.create(req["name"]))
                if op == "delete":
                    return self._json(CO.delete(req["name"]))
                if op == "rename":
                    return self._json(CO.rename(req["name"], req["new"]))
                return self._json({"error": "unknown"}, 404)
            elif self.path in ("/api/trash/delete", "/api/trash/restore"):
                from . import trash
                ids = [str(x) for x in req.get("ids", [])][:2000]
                return self._json(trash.delete(ids) if self.path.endswith("delete") else trash.restore(ids))
            elif self.path == "/api/recat":
                from .recat import recategorise
                res = recategorise(req["id"], req["category"], req["subtype"])
                log_event(res["path"], "recat", None, req["id"], {"category": req["category"], "subtype": req["subtype"]})
                return self._json(res)
            elif self.path == "/api/mytrack":
                from .mytrack import match
                return self._json(match(req.get("file") or None, req.get("name"), req.get("b64")))
            elif self.path == "/api/refsearch":
                from .search import reference_search
                return self._json(reference_search(req["target"]))
            elif self.path == "/api/ytscout":
                mode = req.get("mode") if req.get("mode") in ("pads", "guided") else "voice"
                extra = ["--style", req["style"]] if mode == "guided" and req.get("style") else []
                return self._json({"job": start_job("ytscout", [req["query"], "--n", str(int(req.get("n", 15))), "--mode", mode]
                                                    + extra, req["query"])})
            elif self.path == "/api/styles/hide":
                from .related import hide_style
                return self._json({"hidden": hide_style(req["style"], bool(req.get("hide", True)))})
            elif self.path == "/api/ytscout/mark":
                from .ytscout import mark
                mark(req["id"], req["status"])
            elif self.path == "/api/ytscout/more":
                return self._json({"job": start_job("ytscout", ["--more", req["id"], "--n", str(int(req.get("n", 15)))],
                                                    "more like: " + (req.get("title") or req["id"])[:60])})
            elif self.path == "/api/ytscout/seen":
                from .ytscout import mark_seen
                mark_seen(req.get("ids") or [])
            elif self.path == "/api/ytscout/auto":
                from .ytscout import set_auto
                return self._json(set_auto(enabled=bool(req.get("enabled"))))
            elif self.path == "/api/link/tempo":
                from .link import set_tempo
                set_tempo(req["bpm"])
            elif self.path == "/api/bounce":
                return self._json({"row": _with_partners(bounce(req))})
            elif self.path == "/api/sketch/save":
                con = _sketch_db()
                con.execute("""INSERT INTO sketches(name, state, updated_at) VALUES (?,?,CURRENT_TIMESTAMP)
                               ON CONFLICT(name) DO UPDATE SET state=excluded.state, updated_at=CURRENT_TIMESTAMP""",
                            (req["name"], json.dumps(req["state"])))
                con.commit()
            elif self.path == "/api/chords/midi":
                from .harmony import write_midi
                return self._json(write_midi(req["name"], req["chords"], float(req["step"] or 0), float(req["tempo"]),
                                             times=req.get("times"), bass=req.get("bass")))
            elif self.path == "/api/pair/save":
                from .combos import save_pair
                return self._json(save_pair(unquote(req["src"]), unquote(req["partner"]), req.get("name") or None))
            elif self.path == "/api/stems":
                from .combos import write_stems
                return self._json(write_stems(req["name"], req["stems"], req.get("key"), req.get("bpm"),
                                               als=bool(req.get("als")), bars=req.get("bars")))
            elif self.path == "/api/pairtest/vote":
                from .listening import pair_vote
                return self._json({"ok": pair_vote(req["trial"], req.get("rating"))})
            elif self.path == "/api/drumlabel/vote":
                from .listening import drum_vote
                return self._json({"ok": drum_vote(req["id"], req.get("pieces"))})
            elif self.path == "/api/shootout/vote":
                from .shootout import vote
                return self._json({"ok": vote(req["clip"], req.get("rating"))})
            elif self.path == "/api/sketch/delete":
                con = _sketch_db(); con.execute("DELETE FROM sketches WHERE name=?", (req["name"],)); con.commit()
            elif self.path in ("/api/activity/plan", "/api/activity/start"):
                from .batches import PICKERS, save_batch, DEFAULT_SKIP
                plan = PICKERS[req.get("mode", "breadth")](int(req.get("n", 200)), req.get("skip", DEFAULT_SKIP))
                if self.path.endswith("/plan"):
                    plan.pop("ids")
                    return self._json(plan)
                if any(j["running"] and j["kind"] in ("process", "terminal") for j in activity()):
                    return self._json({"error": "a mining run is already going; stop it first"}, 409)
                f = save_batch(plan)
                args = ["--ids-file", str(f)] + (["--words"] if req.get("words", True) else []) \
                    + (["--build"] if req.get("build", True) else []) + (["--mashup"] if req.get("mashup") else [])
                label = f"{plan['n']} songs · {plan['mode']} · {plan['artists']} artists"
                return self._json({"job": start_job("process", args, label)})
            elif self.path == "/api/activity/pause":
                from .memguard import pause
                pause()
                return self._json(dict(ok=True))
            elif self.path == "/api/activity/resume":
                from .memguard import resume
                jobs = resume()
                first = req.get("first")  # a kind to run before the others (e.g. "stems")
                jobs.sort(key=lambda j: j["kind"] != first)

                def go():  # in the listed order: each gets a few seconds to take its turn before the next starts
                    import time as _t
                    for k, j in enumerate(jobs):
                        if k:
                            _t.sleep(6)
                        start_job(j["kind"], j["args"], LABELS.get(j["kind"], j["kind"]) + " (resumed)")
                import threading
                threading.Thread(target=go, daemon=True).start()
                return self._json(dict(ok=True, started=len(jobs), order=[j["kind"] for j in jobs]))
            elif self.path == "/api/activity/task":
                t = req.get("task")
                if t not in TASKS:
                    return self._json({"error": f"unknown task {t!r}"}, 400)
                if any(j["running"] and j["kind"] == t for j in activity()):
                    return self._json({"error": "already running"}, 409)
                _SLOW.clear()
                return self._json({"job": start_job(t, [], TASKS[t][0])})
            elif self.path == "/api/activity/stop":
                return self._json({"stopped": stop_job(req["id"])})
            elif self.path == "/api/ingest":
                return self._json({"job": start_ingest(req["target"], bool(req.get("drums")))})
            elif self.path == "/api/export":
                from .export import export, favorites_paths, kit_paths
                scope = req.get("scope")
                paths = favorites_paths() if scope == "favorites" else kit_paths(req["kit"]) if scope == "kit" \
                    else [unquote(p) for p in req.get("paths", [])]
                return self._json(export(paths, req.get("name"), reveal=req.get("reveal", True), rack=bool(req.get("rack")),
                                         key=req.get("key") or None, bpm=float(req["bpm"]) if req.get("bpm") else None,
                                         midi=bool(req.get("midi")), chop=bool(req.get("chop")),
                                         pad_edits=req.get("pad_edits") or None))
            elif self.path == "/api/event":
                log_event(path, req["type"], req.get("value"), req.get("id"), req.get("context"))
            elif self.path == "/api/reco/served":  # the page has the rankings it was served: one impression each
                from .reco import live
                return self._json(dict(logged=live.record(req.get("token"))))
            elif self.path == "/api/reco/settings":
                from .reco import live
                return self._json(dict(settings=live.set_setting(req.get("surface"), req.get("value"))))
            elif self.path == "/api/reco/eval":  # every recommender measured again, in the background
                from .taste_report import eval_all
                return self._json(dict(job=eval_all()))
            else:
                return self._json({"error": "not found"}, 404)
            return self._json({"ok": True})
        except Exception as e:
            return self._json({"error": str(e)}, 400)


HTTPD = None


def _restart():
    """Start over in a fresh process (after setup changes the folders, which are read at import)."""
    time.sleep(0.4)
    HTTPD.server_close()
    os.execv(sys.executable, [sys.executable, "-m", "digitalcrate", "serve", "--port", str(HTTPD.server_port),
                              "--no-browser"])


def _warm():
    """Fit the taste model while the page loads, so its first request doesn't wait (about 2 s on a big library)."""
    try:
        from .taste import scores_payload
        scores_payload(None)
        scores_payload(3)
    except Exception as e:
        print("taste warm-up failed:", e)
    try:  # the galaxy map: instant when the last build made it; samples since then are placed in a moment
        from .search import galaxy
        galaxy()
    except Exception as e:
        print("galaxy warm-up failed:", e)


def _scout_daily():
    """The scout's daily inbox: once a day while the app is open, when nothing else is running."""
    while True:
        try:
            from .ytscout import auto_due, set_auto
            from .memguard import paused
            if not paused() and auto_due() and not any(_alive(j["pid"]) for j in _saved_jobs().values()):
                set_auto(last=time.time())
                start_job("ytscout", ["--auto"], "daily finds")
        except Exception as e:
            print("daily scout failed:", e)
        time.sleep(1800)


def serve(port=8765, open_browser=True):
    global HTTPD
    from .app import configured
    if configured():
        _db()
        from .edit import clear_previews
        clear_previews()
        threading.Thread(target=_warm, daemon=True).start()
        if not os.environ.get("DIGITALCRATE_NO_SCOUT"):
            threading.Thread(target=_scout_daily, daemon=True).start()
    httpd = HTTPD = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(C.LIB_ROOT)))
    url = f"http://localhost:{port}/"
    print(f"DigitalCrate at {url}  (Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
