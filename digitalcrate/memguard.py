"""Keep heavy jobs from filling memory: each model-loading job loads several GB (CLAP, Demucs, Whisper), and on a
laptop that's already running Live and a browser a few of them at once push macOS into heavy swapping.

    pause() / resume()   you need the machine: every job stops after the song it's on (freeing its memory) and
                  notes itself; resume() gives back the list, to start them again. Jobs started meanwhile wait in it too.
    wait(what)    before loading models: wait while memory is low (up to 10 minutes, then go ahead anyway)
    breathe()     between items of a long library pass: wait while memory is low, and on 16 GB Macs or smaller also
                  while a job you started (mining, ingest, scout) is running, so the two don't compete
"""
import fcntl
import re
import subprocess
import time

LOW = 15     # % of memory free (macOS memory_pressure) below which a heavy job waits
OK = 25      # ... and starts again once it's back above this
SMALL_MAC = 16 * 2 ** 30


def free_pct():
    try:
        out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"free percentage:\s*(\d+)", out)
        return int(m.group(1)) if m else 100
    except Exception:
        return 100


def ram():
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
    except Exception:
        return 0


def wait(what="starting", limit=600):
    if free_pct() >= LOW:
        return
    print(f"memory is low ({free_pct()}% free): waiting before {what}…", flush=True)
    t = time.time()
    while free_pct() < OK and time.time() - t < limit:
        time.sleep(15)
    print(f"going ahead ({free_pct()}% free, waited {time.time() - t:.0f} s)", flush=True)


def _job_running():
    """Is a job you started (it holds the jobs slot) running right now?"""
    from . import config as C
    f = C.DATA_DIR / "slot-jobs.lock"
    if not f.exists():
        return False
    with open(f, "a+") as fh:
        import os
        fh.seek(0)
        m = re.search(r"pid (\d+)", fh.read())
        if m and int(m.group(1)) == os.getpid():
            return False  # this job holds the slot itself (a batch's own lyrics step must not wait for the batch)
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def breathe():
    import os
    if os.environ.get("DIGITALCRATE_NO_SLOT"):
        return
    yield_if_paused()
    small = 0 < ram() <= SMALL_MAC
    said = False
    t = time.time()
    while (small and _job_running()) or free_pct() < LOW:
        if not said:
            why = "a job you started is running" if small and _job_running() else f"memory is low ({free_pct()}% free)"
            print(f"paused: {why}; carrying on when it's done…", flush=True)
            said = True
        time.sleep(20)
        if time.time() - t > 3 * 3600:  # never stall a pass forever
            break
    if said:
        print(f"resumed after {time.time() - t:.0f} s", flush=True)


# ---------------------------------------------------------------- pause: you need the machine now

def _pause_file():
    from . import config as C
    return C.DATA_DIR / "paused.json"


def paused():
    return _pause_file().exists()


def pause():
    """Ask every job to stop after the item it's on. A stopped job frees its memory (a job merely frozen would keep
    its models loaded), and notes itself in the file so resume() can start it again where it left off."""
    import json
    f = _pause_file()
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(dict(since=time.time(), jobs=[])))


def note(kind, args):
    """Add a job to the paused list (once)."""
    import json
    f = _pause_file()
    try:
        d = json.loads(f.read_text())
    except Exception:
        d = dict(since=time.time(), jobs=[])
    job = dict(kind=kind, args=list(args))
    if job not in d["jobs"]:
        d["jobs"].append(job)
        f.write_text(json.dumps(d))


def paused_jobs():
    import json
    try:
        return json.loads(_pause_file().read_text())
    except Exception:
        return None


def resume():
    """-> the jobs that were paused (kind, args), for the caller to start again. Clears the pause."""
    d = paused_jobs() or dict(jobs=[])
    _pause_file().unlink(missing_ok=True)
    return d["jobs"]


def yield_if_paused():
    """Called by a job between items: when paused, note itself and stop cleanly (resumable passes pick up where they
    left off; a mining run carries on with the songs it hadn't reached)."""
    import os
    import sys
    if os.environ.get("DIGITALCRATE_NO_SLOT") or not paused():
        return
    argv = sys.argv[1:]
    if argv:
        note(argv[0], argv[1:])
    print("PAUSED: stopping here; it starts again where it left off when you resume", flush=True)
    print("TASK DONE (paused)", flush=True)
    sys.exit(0)
