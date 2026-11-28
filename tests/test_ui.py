"""The app in a real browser (Playwright), on a throwaway library built once per run:

  two synthetic songs mined by the real pipeline (pads, keys, melodies), plus a synthetic drum kit (kick, snare, hats,
  clap, tom, shaker one-shots, each with ~25 ms before the hit, as real drum hits have) written into the library with
  real CLAP embeddings, then `build`, then a server on a spare port. Everything the tests do (stars, deletes, sketches,
  collections) happens in that library; nothing touches yours.

    pip install playwright && playwright install chromium
    pytest --ui tests/test_ui.py          (first run downloads the separation and CLAP models)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
import urllib.request

import numpy as np
import pytest
import soundfile as sf

from conftest import SR, tone

pytestmark = pytest.mark.ui

DRUMS = r'''
import json, numpy as np, soundfile as sf
from digitalcrate import config as C
from digitalcrate.db import connect
from digitalcrate import models
SR = 44100
rng = np.random.default_rng(0)
def hit(kind, k):
    n = int(0.6 * SR); t = np.arange(n) / SR; pre = int(0.025 * SR)  # 25 ms before the hit
    if kind == "Kick":
        f = 55 + 70 * np.exp(-t * 30) + 4 * k; y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    elif kind == "Tom":
        f = 110 + 40 * np.exp(-t * 20) + 15 * k; y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)
    else:
        noise = rng.standard_normal(n)
        if kind == "Hat Closed": noise = np.diff(np.r_[0, noise]); y = noise * np.exp(-t * 60)
        elif kind == "Shaker & Tamb": y = np.diff(np.r_[0, noise]) * np.exp(-((t - 0.05) / 0.04) ** 2)
        elif kind == "Rim & Clap": y = noise * (np.exp(-t * 40) + 0.6 * np.exp(-np.abs(t - 0.012) * 300))
        else: y = 0.6 * noise * np.exp(-t * 18) + 0.4 * np.sin(2 * np.pi * (180 + 10 * k) * t) * np.exp(-t * 14)  # snare
    y = np.r_[np.zeros(pre), y][:n] * (0.5 + 0.1 * k)
    return np.stack([y, y]).astype(np.float32)
con = connect()
con.execute("INSERT INTO tracks (path, artist, album, title, genre, duration, status) VALUES (?,?,?,?,?,?,?)",
            ("synthetic/drums.wav", "Drum Machine", "Kits", "Beat", "Jazz", 30.0, "done"))  # not Electronic: hidden by default
tid = con.execute("SELECT id FROM tracks WHERE path='synthetic/drums.wav'").fetchone()[0]
cl = models.clap()
from scipy.signal import resample_poly
from digitalcrate.process import MOOD_PROMPTS
T = cl.embed_text(tuple(MOOD_PROMPTS.values()))  # mood scores as mining computes them: the sound against each mood
for kind in ["Kick", "Snare", "Hat Closed", "Rim & Clap", "Tom", "Shaker & Tamb"]:
    for k in range(3):
        y = hit(kind, k); sid = f"drm{kind[:2].lower()}{k}"
        rel = f"Percussion/{kind.replace(' & ', ' ')}/{kind.replace(' ', '')}_{sid}.wav"
        (C.LIB_ROOT / rel).parent.mkdir(parents=True, exist_ok=True); sf.write(C.LIB_ROOT / rel, y.T, SR)
        e = cl.embed_audio([resample_poly(y.mean(0), 48000, SR).astype(np.float32)])[0]
        moods = json.dumps(dict(zip(MOOD_PROMPTS, np.round((T @ e) / (np.linalg.norm(T, axis=1) * np.linalg.norm(e) + 1e-9), 4).tolist())))
        a = np.abs(y).max(0); env = [float(x.max()) for x in np.array_split(a, 64)]
        env = (np.array(env) / (max(env) + 1e-9) * 99).astype(int).tolist()
        con.execute("""INSERT INTO samples (id, track_id, source, rendered_from, category, subtype, kind, start, dur, bpm,
            key, scale, camelot, key_strength, key_from, chroma, centroid, flatness, pratio, quality, clap, type_probs,
            mood_sims, instrument, path, env) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, tid, "drums", "mix", "Percussion", kind, "oneshot", 1.0 + k, 0.6, 0, "C", "major", "8B", 0, "none",
             json.dumps([0.0] * 12), 3000, 0.3, 0.8, 0.8, e.astype(np.float16).tobytes(), "{}", moods, "drums", rel,
             json.dumps(env)))
# a one-bar drum loop at 120 bpm: kick 0/8, snare 4/12, hats on the off-8ths (for slicing into pads)
st = int(SR * 60 / 120 / 4); loop = np.zeros((2, 16 * st), np.float32)
for s, kind in [(0, "Kick"), (4, "Snare"), (8, "Kick"), (12, "Snare"), (2, "Hat Closed"), (6, "Hat Closed"), (10, "Hat Closed"), (14, "Hat Closed")]:
    h = hit(kind, 0)[:, int(0.025 * SR):][:, :st * 2]; loop[:, s * st:s * st + h.shape[1]] += h[:, :16 * st - s * st]
rel = "Percussion/Full Kit/FullKit_drmloop.wav"; (C.LIB_ROOT / rel).parent.mkdir(parents=True, exist_ok=True); sf.write(C.LIB_ROOT / rel, loop.T, SR)
e = cl.embed_audio([resample_poly(loop.mean(0), 48000, SR).astype(np.float32)])[0]
moods = json.dumps(dict(zip(MOOD_PROMPTS, np.round((T @ e) / (np.linalg.norm(T, axis=1) * np.linalg.norm(e) + 1e-9), 4).tolist())))
con.execute("""INSERT INTO samples (id, track_id, source, rendered_from, category, subtype, kind, start, dur, bpm, bars,
    key, scale, camelot, key_strength, key_from, chroma, centroid, flatness, pratio, quality, clap, type_probs,
    mood_sims, instrument, path, env) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    ("drmloop", tid, "drums", "mix", "Percussion", "Full Kit", "loop", 10.0, 2.0, 120, 1, "C", "major", "8B", 0, "none",
     json.dumps([0.0] * 12), 3000, 0.3, 0.8, 0.8, e.astype(np.float16).tobytes(), "{}", moods, "drums", rel, json.dumps([50] * 64)))
con.commit()
print("DRUMS OK")
'''


def _has_live():
    try:
        from digitalcrate.ableton import _template
        _template()
        return True
    except Exception:
        return False


# Drum Racks are built from an installed Live's own factory rack: without Live (as on CI) there's nothing to build from
needs_live = pytest.mark.skipif(not _has_live(), reason="needs Ableton Live installed (its Drum Rack is the template)")


def _song(chords, mel_hz, secs=5.0):
    pad = np.concatenate([tone(c, secs) for c in chords], axis=1)
    t = np.arange(pad.shape[1]) / SR
    f = mel_hz * 2 ** (np.round(4 * np.sin(2 * np.pi * t / 7)) / 12)
    mel = 0.15 * np.sin(2 * np.pi * np.cumsum(f) / SR) * (0.5 + 0.5 * np.sin(2 * np.pi * t / 2.5) ** 2)
    return (pad + mel[None]).astype(np.float32)


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pytest.importorskip("playwright")
    root = tmp_path_factory.mktemp("uilib")
    music, lib = root / "music", root / "lib"
    for artist, title, chords, mel in (
            ("Test Artist", "Night", [(220, 261.6, 329.6), (174.6, 220, 261.6), (196, 246.9, 293.7), (164.8, 207.7, 246.9)] * 2, 440),
            ("Other Artist", "Morning", [(261.6, 329.6, 392), (220, 261.6, 329.6), (174.6, 220, 261.6), (196, 246.9, 293.7)] * 2, 523)):
        d = music / artist / "Album"
        d.mkdir(parents=True)
        sf.write(d / f"01 {title}.wav", _song(chords, mel).T, SR)
    env = dict(os.environ, DIGITALCRATE_MUSIC=str(music), DIGITALCRATE_LIBRARY=str(lib),
               DIGITALCRATE_FOUND=str(root / "found"), DIGITALCRATE_ABLETON_SAMPLES=str(root / "ableton"),
               DIGITALCRATE_CONFIG=str(root / "cfg.toml"), DIGITALCRATE_NO_SCOUT="1",
               DIGITALCRATE_NO_SLOT="1")  # the test library has its own jobs: no waiting on the real ones
    (root / "cfg.toml").write_text(f'music = "{music}"\nlibrary = "{lib}"\n')
    def run(*a):
        r = subprocess.run([sys.executable, *a], env=env, capture_output=True, text=True)
        assert r.returncode == 0, f"{a}: {r.stderr[-3000:]}"
        return r.stdout
    run("-m", "digitalcrate", "scan")
    run("-m", "digitalcrate", "policy")
    run("-m", "digitalcrate", "process", "--all", "--separate", "never")
    assert "DRUMS OK" in run("-c", DRUMS)
    run("-m", "digitalcrate", "build")
    port = _port()
    srv = subprocess.Popen([sys.executable, "-m", "digitalcrate", "serve", "--port", str(port), "--no-browser"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://localhost:{port}/"
    for _ in range(90):
        try:
            urllib.request.urlopen(base + "api/ping", timeout=1)
            break
        except OSError:
            time.sleep(1)
    else:
        srv.terminate()
        pytest.fail("server did not start")
    yield dict(base=base, lib=lib, env=env, root=root)
    srv.terminate()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        yield b
        b.close()


@pytest.fixture
def page(site, browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(site["base"])
    pg.wait_for_function("typeof S!=='undefined'&&document.querySelectorAll('#list .row').length>=3", timeout=120000)
    pg.evaluate("localStorage.removeItem('atlasSketchDraft')")
    yield pg
    ctx.close()
    # These songs are specific to the Tops tests. The other mixer tests use 901–903.
    for path in site.pop("tops_cleanup", []):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    assert not errors, errors  # every test also fails on a page error


def idx(pg, cond):
    return pg.evaluate(f"S.findIndex(s=>{cond})")


# ---------------------------------------------------------------------------------------------------- browsing

def test_library_loads_with_every_kind(page):
    cats = set(page.evaluate("S.map(s=>s[F.cat])"))
    assert "Percussion" in cats and len(cats) >= 2


def test_the_served_rankings_are_logged_once(page, site):
    """The "for you" and discover rankings the page was served: one impression each, not one per reload."""
    import sqlite3
    page.wait_for_function("TASTE.loaded", timeout=120000)
    db = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    q = "SELECT COUNT(*) FROM reco_impressions WHERE surface='samples.for_you'"
    for _ in range(40):
        try:
            if db.execute(q).fetchone()[0]:
                break
        except sqlite3.OperationalError:  # no table yet
            pass
        page.wait_for_timeout(500)
    n = db.execute(q).fetchone()[0]
    assert n >= 1
    page.evaluate("loadTaste()")                      # the same rankings again: nothing new
    page.wait_for_timeout(3000)
    assert db.execute(q).fetchone()[0] == n
    pol = json.loads(db.execute("SELECT policy FROM reco_impressions WHERE surface='samples.for_you' ORDER BY id DESC")
                     .fetchone()[0])
    assert pol["model"] in ("reco.taste", "taste", "taste (new model not fitted yet)")
    db.close()


def test_play_shows_and_stop_hides_the_now_playing_bar(page):
    page.locator("#list .row [data-play]").first.click()
    page.wait_for_timeout(300)
    assert page.is_visible("#np")
    page.click("#npstop")
    page.wait_for_timeout(200)
    assert not page.is_visible("#np")


def test_select_and_unselect(page):
    row = page.locator("#list .row .meta").first
    row.click()
    assert page.evaluate("st.sel") is not None
    row.click()
    assert page.evaluate("st.sel") is None
    row.click()
    page.keyboard.press("Escape")
    assert page.evaluate("st.sel") is None
    row.click()
    page.click("#dclose")
    assert page.evaluate("st.sel") is None


def test_favourite_appears_in_the_favorites_tab(page):
    b = page.locator("#list .row [data-fav]").first
    b.click()
    page.wait_for_timeout(300)
    page.click("#tabF")
    page.click("[data-favview='list']")
    assert page.locator("#list .row").count() >= 1
    page.locator("#list .row [data-fav]").first.click()  # unstar again


def test_delete_and_undo(page):
    n0 = page.evaluate("filtered().length")
    page.locator("#list .row .meta").first.click()
    page.click("#detail [data-del]")
    page.wait_for_timeout(500)
    assert page.evaluate("filtered().length") == n0 - 1
    page.click("#undel")
    page.wait_for_timeout(800)
    assert page.evaluate("filtered().length") == n0


def test_collections(page):
    page.locator("#list .row [data-col]").first.click()
    page.fill("#colnew", "UI test set")
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    page.mouse.click(5, 5)
    page.click("#tabF")
    page.click("[data-favview='cols']")
    page.wait_for_selector("[data-colplay]")
    assert page.locator(".kit .row").count() == 1
    page.click("[data-coldel]")
    page.click("[data-coldel]")
    page.wait_for_timeout(500)
    assert page.locator("[data-colplay]").count() == 0


# ---------------------------------------------------------------------------------------------------- sketchpad

def _drums(page, kinds=("Kick", "Snare")):
    for k in kinds:
        i = idx(page, "s[F.cat]==='Percussion'&&s[F.sub]===" + json.dumps(k))
        page.evaluate(f"CRATE.drumAdd({i})")
    page.wait_for_function(f"SK.lanes[0]&&SK.lanes[0].state==='ok'&&SK.lanes[0].pads.length==={len(kinds)}", timeout=30000)


def test_drum_hits_go_to_the_drum_lane_with_a_starter_and_start_on_the_hit(page):
    _drums(page)
    lane = page.evaluate("SK.lanes.map(l=>l.type||'sample')")
    assert lane == ["drums"]
    assert page.evaluate("SK.lanes[0].pads.every(p=>p.steps.some(Boolean))")
    starts = page.evaluate("SK.lanes[0].pads.map(p=>p.start)")
    assert all(0.015 < s < 0.035 for s in starts), starts  # the synthetic hits have 25 ms before them


def test_step_edits_are_scheduled_at_once(page):
    _drums(page)
    page.evaluate("CRATE.PROJ.bpm=90;SK.lanes[0].pads[0].steps.fill(0);CRATE.drawSK()")
    page.evaluate("document.getElementById('skplay').click()")
    page.wait_for_timeout(1000)
    res = page.evaluate("""(async()=>{const l=SK.lanes[0],st=CRATE.barLen()/16,ac=l.g.context,j=(Math.floor((ac.currentTime-SK.start)/st)+4)%16;
        document.querySelector(`[data-dstep="0:0:${j}"]`).click();const t0=ac.currentTime;await new Promise(r=>setTimeout(r,(5*st)*1000));
        const q=l.live.get('0:'+j);return q?q.t-t0:null})()""")
    page.evaluate("document.getElementById('skplay').click()")
    assert res is not None and res < 1.0, res  # within the same pass, not after the bar


def test_pad_editor_and_volume(page):
    _drums(page)
    page.click("[data-dedit='0:0']")
    assert "▾" in page.inner_text("[data-dedit='0:0']") and page.locator(".dped").count() == 1
    page.fill("[data-dpv='0:0']", "-6")
    page.dispatch_event("[data-dpv='0:0']", "input")
    assert page.evaluate("SK.lanes[0].pads[0].db") == -6
    page.click("[data-dedit='0:0']")
    assert page.locator(".dped").count() == 0


def test_complete_the_kit(page):
    _drums(page, ("Kick",))
    page.click("[data-dfind='0']")
    page.wait_for_selector(".dfrow", timeout=120000)
    kinds = [x.split("\n")[0] for x in page.locator(".dfrow .dlab").all_inner_texts()]
    assert "Snare" in kinds and "Kick" not in kinds
    page.locator(".dfrow").first.locator("[data-dfadd]").first.click()
    page.wait_for_function("SK.lanes[0].pads.length===2", timeout=30000)


def test_unsaved_save_undo_and_the_kept_draft(page):
    _drums(page)
    page.wait_for_timeout(800)
    assert "dirty" in page.get_attribute("#sksave", "class")
    page.fill("#skname", "UI test beat")
    page.keyboard.press("Meta+s")
    page.wait_for_timeout(800)
    assert "dirty" not in (page.get_attribute("#sksave", "class") or "")
    s0 = page.evaluate("SK.lanes[0].pads[0].steps.join('')")
    page.click("[data-dstep='0:0:2']")
    page.wait_for_timeout(800)
    assert "dirty" in page.get_attribute("#sksave", "class")
    page.keyboard.press("Meta+z")
    page.wait_for_timeout(800)
    assert page.evaluate("SK.lanes[0].pads[0].steps.join('')") == s0
    page.click("#skclear")
    page.wait_for_timeout(800)
    page.click("#skundo")
    page.wait_for_function("SK.lanes.length===1", timeout=10000)
    page.wait_for_timeout(800)
    page.reload()
    page.wait_for_function("typeof S!=='undefined'&&SK.lanes.length===1", timeout=30000)


def test_hidden_sketch_shows_its_bar(page):
    _drums(page)
    page.evaluate("document.getElementById('skplay').click()")
    page.click("#skhide")
    assert page.is_visible(".skminibar")
    page.click(".skminibar #skplay")
    assert not page.evaluate("SK.playing")


# ---------------------------------------------------------------------------------------------------- editor, pages

def test_editor_reset(page):
    page.locator("#list .row .meta").first.click()
    page.click("#edopen")
    page.wait_for_selector("#edreset", timeout=30000)
    page.wait_for_function("ED&&ED.buf&&ED.sel", timeout=30000)  # the editor has loaded the audio
    page.fill("#edst", "2")
    page.dispatch_event("#edst", "input")
    page.click("#edreset")
    assert page.evaluate("edParams().stretch") == 1


def test_drum_editor_has_the_drum_panel(page):
    i = idx(page, "s[F.cat]==='Percussion'")
    page.evaluate(f"select({i},'list')")
    page.click("#edopen")
    page.wait_for_selector("#eddrum", timeout=30000)
    assert page.is_checked("#edtape")


def test_taste_and_activity_pages_render(site, browser):
    pg = browser.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    for path in ("taste", "activity", "setup"):
        pg.goto(site["base"] + path)
        pg.wait_for_timeout(1500)
        if path == "taste":  # every recommender's measurement, and the switch between models
            pg.wait_for_selector("text=How well each recommender predicts you", timeout=60000)
            assert pg.locator("[data-reco]").count() == 5
            pg.click("[data-reco=mashup][data-val=w0]")
            pg.wait_for_selector("[data-reco=mashup][data-val=w0].on", timeout=60000)
            got = json.load(urllib.request.urlopen(site["base"] + "api/taste/explain", timeout=120))
            assert got["settings"]["current"] == dict(samples="new", mashup="w0")
            pg.click("[data-reco=mashup][data-val=new]")
            pg.wait_for_selector("[data-reco=mashup][data-val=new].on", timeout=60000)
    pg.close()
    assert not errors, errors


def test_api_answers(site):
    get = lambda p: json.load(urllib.request.urlopen(site["base"] + p, timeout=120))
    assert "sets" in get("api/sets")
    assert isinstance(get("api/collections"), list)
    assert get("api/ping")["ok"]


def test_new_samples_appear_without_a_rebuild(site, page):
    """A sample mined after the page was built shows up in the open page (live.py), with its goes-with picks."""
    import shutil
    import sqlite3
    db = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    db.row_factory = sqlite3.Row
    r = dict(db.execute("SELECT * FROM samples WHERE category != 'Percussion' LIMIT 1").fetchone())
    new = r["path"].replace(".wav", "_live.wav")
    shutil.copy(site["lib"] / r["path"], site["lib"] / new)
    r.update(id="live01", path=new)
    r.pop("created_at", None)
    cols = ",".join(r)
    db.execute(f"INSERT INTO samples ({cols}) VALUES ({','.join('?' * len(r))})", list(r.values()))
    db.commit()
    n0 = page.evaluate("S.length")
    added = page.evaluate("window.liveCheck(true)")
    assert added == 1 and page.evaluate("S.length") == n0 + 1
    assert page.evaluate("BYID.has('live01')")


def test_rows_drag_out_as_files(page):
    """A dragged row carries a file promise (Finder, the desktop) and the file's own path (apps that take a path)."""
    page.wait_for_function("document.querySelector('#list .row[data-i][draggable]')", timeout=10000)
    got = page.evaluate("""(()=>{const row=document.querySelector('#list .row[data-i]'),dt=new DataTransfer();
        row.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));
        return {promise:dt.getData('DownloadURL'),uri:dt.getData('text/uri-list')}})()""")
    assert got["promise"].startswith("audio/wav:") and "/" in got["promise"]
    assert got["uri"].startswith("file://") and got["uri"].endswith(".wav")


@needs_live
def test_drum_rack_export_starts_on_the_hit(site):
    """⇩ Ableton / Drum Rack: drum one-shots are written starting on the hit, edited pads as edited."""
    import sqlite3
    db = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    paths = [r[0] for r in db.execute("SELECT path FROM samples WHERE category='Percussion' LIMIT 3")]
    body = dict(scope="paths", paths=paths, name="UI rack", rack=True, reveal=False,
                pad_edits={paths[0]: dict(start=0.0, end=0.2, tune=-2, decay=0.1)})
    req = urllib.request.Request(site["base"] + "api/export", method="POST", data=json.dumps(body).encode())
    r = json.load(urllib.request.urlopen(req, timeout=120))
    dest = site["root"] / "ableton" / "UI rack"
    assert r["count"] == 3 and (dest / "UI rack.adg").exists()
    wavs = {p.name: sf.read(str(p), always_2d=True)[0] for p in dest.rglob("*.wav")}
    for name, y in wavs.items():
        m = np.abs(y).max(1)
        first = int(np.argmax(m >= 0.25 * m.max())) / SR
        if paths[0].endswith(name):  # the edited pad keeps its start at 0 (as the drum lane played it) and is short
            assert len(y) / SR < 0.25
        else:
            assert first < 0.005, (name, first)  # the 25 ms before the hit is gone


def test_recent_actions_undo(page):
    """★, ✕ and collection changes land in 🕘 recent actions; ⌘Z (sketchpad closed) and the list undo them."""
    path = page.evaluate("S[+document.querySelector('#list .row[data-i]').dataset.i][F.path]")
    page.locator("#list .row [data-fav]").first.click()
    page.wait_for_timeout(300)
    assert page.evaluate(f"FAV.has({json.dumps(path)})")
    page.keyboard.press("Meta+z")
    page.wait_for_timeout(500)
    assert not page.evaluate(f"FAV.has({json.dumps(path)})")
    page.locator("#list .row [data-nope]").first.click()
    assert page.evaluate(f"TASTE.disliked.has({json.dumps(path)})")
    page.click("#actbtn")
    page.locator("#actpop [data-actu]").first.click()
    page.wait_for_timeout(300)
    assert not page.evaluate(f"TASTE.disliked.has({json.dumps(path)})")


def test_recategorize_and_undo_moves_the_file_back(site, page):
    i = page.evaluate("+document.querySelector('#list .row[data-i]').dataset.i")
    cat0, path0 = page.evaluate(f"[S[{i}][F.cat],S[{i}][F.path]]")
    page.evaluate(f"select({i},'list')")
    target = "Textures & Field" if cat0 != "Textures & Field" else "Pads & Atmospheres"
    page.select_option("#rcat", target)
    page.dispatch_event("#rcat", "change")
    page.click("#rsave")
    page.wait_for_function(f"S[{i}][F.cat]==={json.dumps(target)}", timeout=20000)
    moved = page.evaluate(f"S[{i}][F.path]")
    assert moved != path0 and (site["lib"] / moved).exists() and not (site["lib"] / path0).exists()
    page.keyboard.press("Escape")
    page.keyboard.press("Meta+z")
    page.wait_for_function(f"S[{i}][F.cat]==={json.dumps(cat0)}", timeout=20000)
    back = page.evaluate(f"S[{i}][F.path]")
    assert (site["lib"] / back).exists() and not (site["lib"] / moved).exists()


def test_keyboard_browsing(page):
    page.mouse.click(700, 5)  # focus the page, not a field
    page.keyboard.press("ArrowDown")
    first = page.evaluate("st.sel")
    assert first is not None and page.evaluate(f"players.has({first})")  # moving previews
    page.keyboard.press("j")
    second = page.evaluate("st.sel")
    assert second != first
    page.keyboard.press("k")
    assert page.evaluate("st.sel") == first
    path = page.evaluate(f"S[{first}][F.path]")
    page.keyboard.press("f")
    page.wait_for_timeout(300)
    assert page.evaluate(f"FAV.has({json.dumps(path)})")
    page.keyboard.press("f")  # and off again
    page.keyboard.press("x")
    assert page.evaluate(f"TASTE.disliked.has({json.dumps(path)})")
    page.keyboard.press("x")
    page.keyboard.press("Shift+?")
    assert page.is_visible("#khelp")
    page.keyboard.press("Shift+?")
    page.keyboard.press("Enter")
    page.wait_for_selector("#edprev", timeout=20000)


def test_velocity_flam_and_choke(page):
    _drums(page, ("Tom", "Hat Closed"))
    page.evaluate("SK.lanes[0].pads.forEach(p=>p.steps.fill(0));SK.lanes[0].pads[0].steps[0]=1;CRATE.drawSK()")
    step = "[data-dstep='0:0:0']"
    page.dispatch_event(step, "wheel", {"deltaY": 120})
    assert abs(page.evaluate("SK.lanes[0].pads[0].steps[0]") - 0.9) < 1e-6  # scroll down: 10% softer
    page.click("[data-dstep='0:1:2']", modifiers=["Alt"])
    assert page.evaluate("SK.lanes[0].pads[1].flams[2]") == 1 and page.evaluate("SK.lanes[0].pads[1].steps[2]") > 0
    # choke: the tom rings from step 0; the hat on step 2 in the same group cuts it off
    level = """(async(choke)=>{const l=SK.lanes[0];l.pads.forEach(p=>{p.choke=choke;p.flams=[]});l.pads[1].steps.fill(0);l.pads[1].steps[2]=1;l._choke=null;
        const L=CRATE.barLen(),ctx=new OfflineAudioContext(1,Math.ceil(L*44100),44100);CRATE.skBar(ctx,ctx.destination,l,0,0,L,null);
        const d=(await ctx.startRendering()).getChannelData(0),a=Math.floor(L/16*4*44100),b=Math.floor(L/16*8*44100);let s=0;for(let k=a;k<b;k++)s+=d[k]*d[k];return s})"""
    ringing = page.evaluate(level + "(0)")
    choked = page.evaluate(level + "(1)")
    assert choked < 0.2 * ringing, (choked, ringing)


@needs_live
def test_drum_midi_and_rack_export(site):
    import gzip
    import sqlite3
    import pretty_midi
    db = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    paths = [r[0] for r in db.execute("SELECT path FROM samples WHERE category='Percussion' AND subtype IN ('Kick','Snare','Hat Closed') LIMIT 3")]
    steps = lambda *on: [1 if j in on else 0 for j in range(16)]
    pads = [dict(path=paths[0], steps=steps(0, 8), choke=0), dict(path=paths[1], steps=steps(4, 12), flams=steps(12)),
            dict(path=paths[2], steps=steps(*range(0, 16, 2)), choke=1)]
    body = dict(name="UI drums", bpm=100, bars=1, swing=0.2, pads=pads, reveal=False)
    req = urllib.request.Request(site["base"] + "api/drums/export", method="POST", data=json.dumps(body).encode())
    r = json.load(urllib.request.urlopen(req, timeout=120))
    dest = site["root"] / "ableton" / "UI drums"
    pm = pretty_midi.PrettyMIDI(str(dest / r["midi"]))
    notes = pm.instruments[0].notes
    assert len(notes) == 2 + 3 + 8  # kick 2, snare 2 + a flam, hats 8
    assert {n.pitch for n in notes} == {36, 37, 38}
    adg = gzip.open(dest / "UI drums.adg").read().decode()
    assert '<ChokeGroup Value="1"' in adg


def test_slice_a_drum_loop_into_pads(page):
    i = idx(page, "s[F.id]==='drmloop'")
    page.evaluate(f"select({i},'list')")
    page.click("#sliceit")
    page.wait_for_function("SK.lanes[0]&&SK.lanes[0].type==='drums'&&SK.lanes[0].pads.length>=6&&SK.lanes[0].pads.every(p=>p.buf)", timeout=30000)
    on = page.evaluate("SK.lanes[0].pads.map(p=>p.steps.findIndex(v=>v>0))")
    assert set(on) <= set(range(16)) and {0, 2, 4, 6, 8, 10, 12, 14} <= set(on), on  # each hit on its own step
    assert page.evaluate("SK.lanes[0].pads.every(p=>p.label&&p.end>p.start)")


def test_arrangement_sections(page):
    """AB × 1 bar: a lane ticked only for B is silent in bar 1 and plays in bar 2; the bounce offers the whole song."""
    _drums(page, ("Kick",))
    page.evaluate("SK.lanes[0].pads[0].steps.fill(0);SK.lanes[0].pads[0].steps[0]=1;CRATE.drawSK()")
    page.fill("#skarr", "ab")
    page.dispatch_event("#skarr", "change")
    page.select_option("#sksec", "1")
    assert page.evaluate("SK.arr") == "AB"
    page.click("[data-sksec='0:A']")  # untick A: the drums play in B only
    assert page.evaluate("SK.lanes[0].secs") == "B"
    assert page.input_value("#skbars") == "2"
    energy = """(async()=>{const l=SK.lanes[0],L=CRATE.barLen(),ctx=new OfflineAudioContext(1,Math.ceil(2*L*44100),44100);
        for(let b=0;b<2;b++)CRATE.skBar(ctx,ctx.destination,l,b,b*L,L,null);const d=(await ctx.startRendering()).getChannelData(0),h=Math.floor(L*44100);
        let a=0,b=0;for(let k=0;k<h;k++){a+=d[k]*d[k];b+=d[h+k]*d[h+k]}return [a,b]})()"""
    a, b = page.evaluate(energy)
    assert a < 1e-6 and b > 0.01, (a, b)
    snap = json.loads(page.evaluate("JSON.stringify(JSON.parse(CRATE.skSnap()))"))
    assert snap["arr"] == "AB" and snap["sec"] == 1 and snap["lanes"][0]["secs"] == "B"


def test_fits_my_track(site, page, tmp_path):
    """🎚 fits my track: a bounce's key and tempo are detected, results carry their reasons, and the track's key and
    tempo can become the project's. The file is only analysed (nothing is added to the library)."""
    import sqlite3
    A, D, E, Fs, Cs = 220.0, 293.66, 329.63, 369.99, 277.18
    bounce = _song([[A, Cs, E], [D, Fs, A], [E, A * 2 ** (8 / 12), 493.88 / 2], [A, Cs, E]], 440.0)
    f = tmp_path / "my bounce.wav"
    sf.write(f, bounce.T, SR)
    n0 = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite").execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    page.click("#mybtn")
    page.fill("#myIn", str(f))
    page.click("#myGo")
    page.wait_for_selector("#sbanner #myproj", timeout=120000)
    label = page.inner_text("#sbanner")
    assert "fits my bounce.wav" in label and "bpm" in label
    assert page.locator("#list .row[data-i] .meta span").first.inner_text().count("sounds like") == 1
    page.click("#myproj")
    key = page.evaluate("CRATE.PROJ.key")
    assert key and key in label
    n1 = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite").execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    assert n1 == n0


def test_why_this(site, page):
    """💡 why this? explains a sample's rank: where it stands, and the liked samples it sounds closest to."""
    paths = page.evaluate("[...document.querySelectorAll('#list .row[data-i]')].slice(0,4).map(r=>S[+r.dataset.i][F.path])")
    for p in paths[:3]:
        req = urllib.request.Request(site["base"] + "api/fav", method="POST", data=json.dumps(dict(path=p, on=True)).encode())
        urllib.request.urlopen(req, timeout=30)
    page.reload()
    page.wait_for_function("TASTE.loaded", timeout=120000)
    i = page.evaluate(f"byPath.get({json.dumps(paths[3])})")
    page.evaluate(f"select({i},'list')")
    page.click("#whybtn")
    page.wait_for_function("document.querySelector('#whybox b')", timeout=120000)
    txt = page.inner_text("#whybox")
    assert "In your" in txt and "sounds closest to what you liked" in txt
    page.locator("#whybox [data-go2]").first.click()  # a liked sample opens; the explanation follows it
    page.wait_for_function(f"st.sel!=={i}")
    page.wait_for_function("document.querySelector('#whybox b')", timeout=120000)


def test_build_a_kit_around_a_hit(page):
    """🥁 build a kit around this: the hit goes into the drum lane and the finder offers the rest of a kit."""
    i = idx(page, "s[F.cat]==='Percussion'&&s[F.sub]==='Kick'")
    page.evaluate(f"select({i},'list')")
    page.click("#kitaround")
    page.wait_for_function("SK.lanes[0]&&SK.lanes[0].type==='drums'&&SK.lanes[0].pads.length===1", timeout=30000)
    page.wait_for_selector(".dfrow [data-dfadd]", timeout=120000)
    page.locator(".dfrow").filter(has_text="Snare").first.locator("[data-dfadd]").first.click()
    page.wait_for_function("SK.lanes[0].pads.length===2", timeout=30000)


def test_scout_groups_inbox_and_filters(site, page):
    """🔭 Scout: full width, finds grouped by search, the daily inbox on top, playlists filtered, ✕ remembered."""
    import sqlite3
    urllib.request.urlopen(site["base"] + "api/ytscout", timeout=60).read()  # creates the table
    db = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    e = lambda k: (np.eye(512)[k] + 0.1).astype(np.float16).tobytes()
    rows = [("v1", "acapella test", "Singer - Song (Acapella)", 1.5, 1, 0, e(1)),
            ("v2", "acapella test", "Another (A Cappella)", 1.2, 0, 1, e(2)),
            ("v3", "acapella test", "2000s hits [playlist]", 1.9, 0, 1, e(3)),
            ("v4", "acapella test", "Third (Acapella)", 1.0, 0, 1, e(4))]
    for vid, q, t, sc, auto, seen, emb in rows:
        db.execute("""INSERT OR REPLACE INTO yt_scout(id, query, queries, url, title, channel, duration, views, score,
                      vocal, neg, taste, best_at, snippet, status, mode, emb, moments, auto, seen)
                      VALUES (?,?,?,?,?,'ch',200,10,?,0.5,0.1,0.2,30,'x.wav','scored','voice',?,?,?,?)""",
                   (vid, q, q, f"https://www.youtube.com/watch?v={vid}", t, sc, emb,
                    json.dumps([[30, "x.wav"], [50, "y.wav"]]), auto, seen))
    db.commit()
    page.evaluate("CRATE.setTab('Y')")
    page.wait_for_selector(".ygrp .yghead", timeout=30000)
    assert not page.locator("aside").is_visible()
    assert page.locator(".ygrp.inbox .yt").count() == 1
    page.locator(".ygrp.inbox .ymoms .play").nth(1).click()  # listening doesn't move a find out of the inbox
    page.wait_for_timeout(600)
    page.evaluate("CRATE.setTab('Y')")
    page.wait_for_selector(".ygrp.inbox .yt", timeout=30000)
    assert page.locator(".ygrp.inbox .yt").count() == 1
    grp = page.locator(".ygrp:not(.inbox)").filter(has_text="acapella test")
    assert grp.locator(".yt").count() == 2  # the playlist is filtered out
    assert grp.locator(".yt").first.locator(".ymoms .play").count() == 2
    assert "dismissed or filtered" in page.inner_text("#ytcount")
    grp.locator(".yt").filter(has_text="Another").locator("[data-ytskip]").click()
    page.wait_for_function("document.querySelectorAll('.ygrp:not(.inbox) .yt').length===1")
    assert db.execute("SELECT status FROM yt_scout WHERE id='v2'").fetchone()[0] == "skipped"
    assert db.execute("SELECT status FROM yt_scout WHERE id='v3'").fetchone()[0] == "filtered"
    page.click("[data-ytseen]")
    page.wait_for_function("!document.querySelector('.ygrp.inbox')")
    page.evaluate("CRATE.setTab('S')")
    assert page.locator("aside").is_visible()


def test_hold_a_pad_on_its_sustain_loop(page):
    """∞ hold: a sustained sample with a seamless loop plays and holds until stopped; a sketchpad lane can hold too."""
    i = page.evaluate("+Object.keys(CRATE.LOOPS).find(k=>S[k]&&S[k][F.kind]!=='loop')")
    assert i == i, "the test library should have at least one loopable pad"  # not NaN
    page.evaluate(f"select({i},'list')")
    page.click("#holdit")
    page.wait_for_function("players.has('hold')")
    page.click("#holdit")
    page.wait_for_function("!players.has('hold')")
    page.evaluate(f"CRATE.skAdd({i})")
    page.wait_for_function("SK.lanes.length&&SK.lanes[SK.lanes.length-1].state==='ok'", timeout=120000)
    page.evaluate("(()=>{const l=SK.lanes[SK.lanes.length-1];l.more=true;CRATE.drawSK()})()")
    page.locator("[data-skhold]").last.click()
    assert page.evaluate("(()=>{const l=SK.lanes[SK.lanes.length-1];const h=CRATE.laneHold(l);return l.hold&&l.every>=2&&!!h&&h.b>h.a})()")


def test_drum_takes_alternate(site, page):
    """🔁 takes: other hits of the same drum from the same song; hits cycle main, take 2, take 3… deterministically."""
    found = None
    for i in page.evaluate("S.map((s,i)=>i).filter(i=>S[i][F.cat]==='Percussion'&&S[i][F.kind]==='oneshot')"):
        p = page.evaluate(f"S[{i}][F.path]")
        t = json.loads(urllib.request.urlopen(site["base"] + "api/drums/takes?path=" + urllib.parse.quote(p), timeout=30).read())
        if t["takes"]:
            found = i
            break
    assert found is not None, "the test library should have a drum hit with another take in its song"
    page.evaluate(f"CRATE.drumAdd({found},{{quiet:true}})")
    page.wait_for_function("SK.lanes.some(l=>l.type==='drums'&&l.state==='ok')", timeout=120000)
    page.locator("[data-dtakes]").first.click()
    page.wait_for_function("(()=>{const l=SK.lanes.find(l=>l.type==='drums');return l.pads[0].tk&&l.pads[0].tk.length>0})()", timeout=30000)
    seq = page.evaluate("""(()=>{const l=SK.lanes.find(l=>l.type==='drums'),p=l.pads[0];p.steps=new Array(32).fill(0);[0,4,8,12].forEach(k=>p.steps[k]=1);
      const out=[];for(let bar=0;bar<2;bar++)for(const k of [0,4,8,12]){const t=CRATE.drumTake(l,p,k,bar);out.push(t?t.path:'main')}return out})()""")
    n = page.evaluate("SK.lanes.find(l=>l.type==='drums').pads[0].tk.length") + 1
    assert seq[0] == "main" and len(set(seq)) == n and seq[n] == "main"  # cycles through every take, then repeats


def test_drum_takes_pin_shuffle_and_make_main(site, page):
    """Takes: ⇧-click pins a step to one take, "shuffled" is a seeded shuffle bag the export reproduces exactly, and ★
    makes a take the main hit."""
    from digitalcrate.drumexport import take_idx
    for n in (2, 3, 4):  # the page and the exporter pick the same take for every hit
        js = page.evaluate(f"[...Array(60).keys()].map(h=>CRATE.takeIdx({{order:'shuffle',seed:777}},h,0,{n}))")
        assert js == [take_idx(dict(order="shuffle", seed=777), h, 0, n) for h in range(60)]
        if n > 2:
            assert all(a != b for a, b in zip(js, js[1:])) and set(js) == set(range(n))
    found = None
    for i in page.evaluate("S.map((s,i)=>i).filter(i=>S[i][F.cat]==='Percussion'&&S[i][F.kind]==='oneshot')"):
        p = page.evaluate(f"S[{i}][F.path]")
        t = json.loads(urllib.request.urlopen(site["base"] + "api/drums/takes?path=" + urllib.parse.quote(p), timeout=30).read())
        if t["takes"]:
            found = i
            break
    assert found is not None
    page.evaluate(f"CRATE.drumAdd({found},{{quiet:true}})")
    page.wait_for_function("SK.lanes.some(l=>l.type==='drums'&&l.state==='ok')", timeout=120000)
    page.locator("[data-dtakes]").first.click()
    page.wait_for_function("(()=>{const l=SK.lanes.find(l=>l.type==='drums');return l.pads[0].tk&&l.pads[0].tk.length>0})()", timeout=30000)
    page.evaluate("(()=>{const p=SK.lanes.find(l=>l.type==='drums').pads[0];p.steps=new Array(32).fill(0);[0,4,8,12].forEach(k=>p.steps[k]=1);CRATE.drawSK()})()")
    st = page.locator('[data-dstep$=":0:4"]').first
    st.click(modifiers=["Shift"])
    st.click(modifiers=["Shift"])  # auto -> main -> take 2
    assert page.locator('[data-dstep$=":0:4"]').first.get_attribute("data-pin") == "2"
    seq = page.evaluate("""(()=>{const l=SK.lanes.find(l=>l.type==='drums'),p=l.pads[0];const out=[];for(let bar=0;bar<3;bar++){const t=CRATE.drumTake(l,p,4,bar);out.push(t?t.path:'main')}return out})()""")
    t2 = page.evaluate("SK.lanes.find(l=>l.type==='drums').pads[0].takes[0]")
    assert seq == [t2] * 3  # pinned: every pass
    # ★ make take 2 the main hit
    old = page.evaluate("SK.lanes.find(l=>l.type==='drums').pads[0].path")
    page.locator("[data-dtkmain]").first.click()  # the takes row shows under the pad once takes are on
    page.wait_for_function(f"(()=>{{const p=SK.lanes.find(l=>l.type==='drums').pads[0];return p.path==={json.dumps(t2)}&&p.buf}})()", timeout=30000)
    p = page.evaluate("(()=>{const p=SK.lanes.find(l=>l.type==='drums').pads[0];return {takes:p.takes,pin:p.pins[4]}})()")
    assert p["takes"][0] == old and p["pin"] == 1  # the pin follows its recording, now the main one
    # shuffled is in the saved state
    page.select_option("[data-dtkord]", "shuffle")
    assert page.evaluate("JSON.parse(CRATE.skSnap()).lanes.find(l=>l.type==='drums').pads[0].order") == "shuffle"
    # each pad row stays on one line (✕ doesn't wrap)
    tops = page.evaluate("[...document.querySelector('.drow').children].map(e=>Math.round(e.getBoundingClientRect().top+e.getBoundingClientRect().height/2))")
    assert max(tops) - min(tops) <= 4, tops


def test_pad_solo_hears_only_that_pad(page):
    """S on a drum pad: only that pad plays, and the other lanes go quiet too."""
    i = page.evaluate("S.findIndex(s=>s[F.cat]==='Percussion'&&s[F.kind]==='oneshot')")
    page.evaluate(f"CRATE.drumAdd({i},{{quiet:true}})")
    page.wait_for_function("SK.lanes.some(l=>l.type==='drums'&&l.state==='ok')", timeout=120000)
    page.locator("[data-dsolo]").first.click()
    assert page.evaluate("SK.lanes.find(l=>l.type==='drums').pads[0].solo") is True
    assert page.evaluate("CRATE.laneSolo(SK.lanes.find(l=>l.type==='drums'))") is True
    assert page.locator("[data-dsolo]").first.get_attribute("class").split().count("on") == 1
    page.locator("[data-dsolo]").first.click()
    assert page.evaluate("CRATE.laneSolo(SK.lanes.find(l=>l.type==='drums'))") is False


def test_playable_pad_for_live(site, page):
    """🎹 playable: a Simpler preset tuned to the sample's chord, its loop in the WAV, and its chords as MIDI."""
    import gzip, re
    i = page.evaluate("S.findIndex(s=>['Pads & Atmospheres','Strings & Orchestral','Chords & Keys'].includes(s[F.cat])&&s[F.kind]!=='oneshot')")
    assert i >= 0
    page.evaluate(f"select({i},'list')")
    page.wait_for_selector("#playit")
    page.evaluate("window._t=[];const o=toast;toast=(m,...a)=>{_t.push(String(m));return o(m,...a)}")
    page.route("**/api/pad/playable", lambda route: route.continue_(post_data=json.dumps({**json.loads(route.request.post_data), "reveal": False})))
    page.click("#playit")
    page.wait_for_function("_t.some(m=>m.includes('Playable pads')||m.includes('failed'))", timeout=120000)
    msg = page.evaluate("_t.find(m=>m.includes('Playable pads')||m.includes('failed'))")
    assert "Playable pads" in msg, msg
    d = site["root"] / "ableton" / "Playable pads"
    mids, advs = list(d.glob("*chords.mid")), list(d.glob("*.adv"))
    assert list(d.glob("*.wav"))
    try:
        import madmom  # noqa: F401  (the chords clip needs the chord recognizer; without it the instrument still works)
        assert mids
    except ImportError:
        pass
    if advs:  # Live installed: the preset's root key is the chord's root
        x = gzip.open(advs[0]).read().decode()
        assert re.search(r'<RootKey Value="(\d+)"', x)


def test_tab_survives_refresh(page):
    page.click("#tabC")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='C'", timeout=30000)
    assert "on" in page.locator("#tabC").get_attribute("class").split()
    page.click("#tabS")  # leave it where the other tests expect it


def test_playback_progress_shows(page):
    """While a sample plays: a thin bar on the now-playing strip and a playhead on its waveform."""
    page.evaluate("CRATE.setTab('S')")
    page.locator(".row [data-play]").first.click()
    page.wait_for_function("document.querySelector('#npbar')&&parseFloat(document.querySelector('#npbar').style.width)>0", timeout=20000)
    page.wait_for_function("document.querySelector('.row svg.wave .phl')", timeout=10000)
    page.evaluate("stopAll()")
    page.wait_for_function("!document.querySelector('svg.wave .phl')", timeout=10000)


def test_search_from_crate_and_by_id(page):
    """Typing in search on another tab shows the samples; an id finds its sample even if filters would hide it."""
    sid, cat = page.evaluate("[S[3][F.id],S[3][F.cat]]")
    other = page.evaluate(f"CATS.find(c=>c!=={json.dumps(cat)})")
    page.click("#tabC")
    page.fill("#search", sid)
    page.wait_for_function("st.tab==='S'", timeout=5000)
    page.evaluate(f"st.cats=new Set([{json.dumps(other)}]);render()")  # a category filter that would hide it
    page.wait_for_function(f"document.querySelectorAll('#list .row').length===1&&document.querySelector('#list .row').dataset.i==='3'", timeout=5000)
    page.fill("#search", "")
    page.evaluate("st.cats=new Set();render()")


def test_now_playing_does_not_move_the_page(page):
    """Starting and stopping playback never shifts the list (the now-playing strip floats over it)."""
    page.evaluate("CRATE.setTab('S')")
    row = page.locator("#list .row").nth(1)
    # let the list settle first (takes tags and fresh scores arrive just after the page loads and redraw it)
    y0, same = row.bounding_box()["y"], 0
    for _ in range(40):
        page.wait_for_timeout(250)
        y = row.bounding_box()["y"]
        same = same + 1 if abs(y - y0) < 0.5 else 0
        y0 = y
        if same >= 6:
            break
    page.locator("#list .row [data-play]").first.click()
    page.wait_for_function("!document.querySelector('#np').hidden", timeout=10000)
    y1 = row.bounding_box()["y"]
    page.evaluate("stopAll()")
    page.wait_for_function("document.querySelector('#np').hidden", timeout=10000)
    y2 = row.bounding_box()["y"]
    assert abs(y1 - y0) < 1 and abs(y2 - y0) < 1, (y0, y1, y2)


def test_recommendations_updated_only_when_the_list_changes(page):
    """Fresh taste scores that don't change the top of the list don't show "recommendations updated"."""
    page.evaluate("CRATE.setTab('S')")
    page.wait_for_function("TASTE.loaded", timeout=30000)
    page.evaluate("$('refresh').hidden=true")
    page.evaluate("loadTaste()")
    page.wait_for_timeout(1500)
    assert page.evaluate("$('refresh').hidden") is True


def test_plays_record_where_they_came_from(site, page):
    """A play from the crate's wildcards is logged with that source (for "where your stars come from")."""
    import sqlite3
    page.click("#tabC")
    page.wait_for_selector("#list .kit")
    b = page.locator("#list .kit").nth(1).locator("[data-play]").first
    if not b.count():
        b = page.locator("#list .kit").first.locator("[data-play]").first
    want = "crate · wildcards" if page.locator("#list .kit").nth(1).locator("[data-play]").count() else "crate · for you"
    b.click()
    page.wait_for_timeout(600)
    page.evaluate("stopAll()")
    db = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    for _ in range(20):  # the event is sent in the background
        ctx = [r[0] for r in db.execute("SELECT context FROM events WHERE type='listen' AND context IS NOT NULL")]
        if any(json.loads(c).get("src") == want for c in ctx):
            break
        page.wait_for_timeout(250)
    page.click("#tabS")
    assert any(json.loads(c).get("src") == want for c in ctx), ctx


def test_alternate_takes_play_through(page):
    """🔁 takes: a tag on the row, the list in the sample panel, play all, and T for the next take."""
    page.evaluate("CRATE.setTab('S')")
    i = page.evaluate("S.findIndex((s,i)=>CRATE.takesOf(i).length>1)")
    assert i >= 0, "the test library's drum hits (three of each kind in one song) should group as takes"
    g = page.evaluate(f"CRATE.takesOf({i})")
    page.fill("#search", page.evaluate(f"S[{i}][F.id]"))
    page.wait_for_selector(f'#list .row[data-i="{i}"] [data-takes]')
    page.click(f'#list .row[data-i="{i}"] [data-takes]')   # plays through the takes, the first one first
    page.wait_for_function(f"players.has({g[0]})", timeout=10000)
    page.wait_for_function(f"players.has({g[1]})", timeout=20000)   # ... then the next, on its own
    page.evaluate("stopAll()")
    page.evaluate(f"select({i},'list')")
    page.wait_for_selector("#tkbox")
    assert page.locator("#tkbox .prow").count() == len(g)
    page.keyboard.press("t")
    nxt = g[(g.index(i) + 1) % len(g)]
    page.wait_for_function(f"st.sel==={nxt}", timeout=5000)
    page.evaluate("stopAll()")
    page.fill("#search", "")


def test_editor_selection_sticks_to_bars_and_knobs_need_a_real_grab(page):
    """Dragging a selection in the editor: its length sticks at whole bars; a click near (not on) a fade knob selects."""
    page.evaluate("CRATE.setTab('S')")
    i = page.evaluate("S.findIndex(s=>s[F.kind]==='loop'&&s[F.bpm]>0&&s[F.dur]>240/s[F.bpm]*1.6)")
    if i < 0:  # no loop long enough: a free sample against the project tempo
        i = page.evaluate("S.findIndex(s=>s[F.dur]>5)")
        page.evaluate("PROJ.bpm=120")
    page.evaluate(f"select({i},'list')")
    page.evaluate(f"openEditor({i})")
    page.wait_for_function("ED&&ED.buf&&document.querySelector('#edc')", timeout=30000)
    box = page.locator("#edc").bounding_box()
    bar, dur = page.evaluate("edBar()"), page.evaluate("ED.buf.duration")
    assert bar > 0 and dur > bar * 1.5
    x = lambda t: box["x"] + t / dur * box["width"]
    fi0 = page.evaluate("+$('edfi').value")
    # near the left edge, below the knob: starts a selection, the fade stays as it was
    page.evaluate("$('edsnap').checked=false")
    t0 = 0.15 * dur   # well clear of the edges (within 7 px of one, a drag moves that edge instead)
    page.mouse.move(x(t0), box["y"] + 60)
    page.mouse.down()
    page.mouse.move(x(t0 + bar) + 5, box["y"] + 60, steps=8)   # 5 px past one bar: sticks to exactly one
    page.mouse.up()
    a, b = page.evaluate("ED.sel")
    assert abs((b - a) - bar) < 0.002, (a, b, bar)
    assert "1 bar" in page.inner_text("#edsel")
    assert page.evaluate("+$('edfi').value") == fi0
    # a click 20 px down, right by the fade-in knob, is not a knob grab
    page.mouse.move(x(a) + 6, box["y"] + 22)
    page.mouse.down()
    page.mouse.move(x(a) + 80, box["y"] + 22, steps=4)
    page.mouse.up()
    assert page.evaluate("+$('edfi').value") <= max(fi0, 10)
    page.keyboard.press("Escape")


def test_lane_trim_sticks_to_bars(page):
    """Dragging a part of a sketchpad lane: its length sticks at whole bars of the project."""
    i = page.evaluate("S.findIndex(s=>s[F.cat]!=='Percussion'&&s[F.dur]>6)")
    assert i >= 0
    n0 = page.evaluate("SK.lanes.length")
    page.evaluate(f"CRATE.skAdd({i})")
    page.wait_for_function(f"SK.lanes.length>{n0}&&SK.lanes[SK.lanes.length-1].state==='ok'", timeout=120000)
    k = page.evaluate("SK.lanes.length-1")
    c = page.locator(f'[data-skw="{k}"]')
    c.scroll_into_view_if_needed()
    box = c.bounding_box()
    dur, bar = page.evaluate(f"SK.lanes[{k}].buf.duration"), page.evaluate("CRATE.barLen()")
    assert dur > bar * 1.2
    x = lambda t: box["x"] + t / dur * box["width"]
    t0 = 0.15 * dur   # well clear of the edges
    page.mouse.move(x(t0), box["y"] + 15)
    page.mouse.down()
    page.mouse.move(x(t0 + bar) + 4, box["y"] + 15, steps=8)   # 4 px past one bar
    page.mouse.up()
    a, b = page.evaluate(f"SK.lanes[{k}].trim")
    assert abs((b - a) * dur - bar) < 0.003, ((b - a) * dur, bar)
    assert "1 bar" in page.locator(".lane .meta").last.inner_text()


STEM_SONGS = r'''
import json, numpy as np, soundfile as sf
from digitalcrate import stems, config as C
SR = C.SR
for tid, bpm, pc in ((901, 100, 0), (902, 110, 2), (903, 92, 7)):
    d = stems.DIR / f"t{tid}"; d.mkdir(parents=True, exist_ok=True)
    bar, nb = 240.0 / bpm, 16
    t = np.arange(int(nb * bar * SR)) / SR
    tone = lambda f: (0.25 * np.sin(2 * np.pi * f * t)).astype(np.float32)
    click = (0.5 * (np.modf(t / (bar / 4))[0] < 0.02) * np.sin(2 * np.pi * 90 * t)).astype(np.float32)
    root = 220 * 2 ** ((pc - 9) / 12)
    parts = dict(drums=click, bass=tone(root / 2), vocals=tone(root * 2), other=tone(root) + tone(root * 1.26) + tone(root * 1.5))
    for k, y in parts.items():
        sf.write(str(d / f"{k}.flac"), np.stack([y, y]).T, SR, format="FLAC", subtype="PCM_16")
    ch = np.zeros(12); ch[[pc, (pc + 4) % 12, (pc + 7) % 12]] = 1; ch /= np.linalg.norm(ch)
    e = np.zeros((4, 512), np.float16); e[:, tid % 512] = 1; np.save(d / "emb.npy", e)
    (d / "meta.json").write_text(json.dumps(dict(track=tid, artist=f"Stem Artist {tid}", title="Song", bpm=bpm, pc=pc,
        scale="major", camelot="8B", bars=[round(b * bar, 4) for b in range(nb + 1)], act={k: [1.0] * nb for k in stems.STEMS},
        chroma=[ch.round(3).tolist()] * nb, stems=list(stems.STEMS), separated=False)))
print("STEMS OK")
'''


def test_stem_mixer_deals_plays_and_learns(site, page):
    """🎛 Mashup: prepared songs, 🎲 all fills the slots with parts rendered to the tempo, they loop in sync, and a
    rating is logged."""
    # three prepared songs written straight into the test library (the beat tracker doesn't take the synthetic songs)
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout, r.stderr[-2000:]
    n = json.load(urllib.request.urlopen(urllib.request.Request(site["base"] + "api/stems/library", data=b"{}", method="POST")))["n"]
    assert n == 3
    page.click("#tabM")
    page.wait_for_selector("#mxall")
    page.fill("#mxbpm", "100")
    page.dispatch_event("#mxbpm", "change")
    page.click("#mxall")
    page.wait_for_function("CRATE.MX.on&&Object.values(CRATE.MX.slots).some(p=>p&&p.buf)", timeout=90000)
    slots = page.evaluate("Object.fromEntries(Object.entries(CRATE.MX.slots).map(([k,p])=>[k,{n:p.n,dur:p.buf?p.buf.duration:0,track:p.track}]))")
    for k, p in slots.items():
        if p["dur"]:
            assert abs(p["dur"] - p["n"] * 2.4) < 0.01, (k, p)   # n bars at 100 bpm, whatever the song's tempo
    stem = next(k for k, p in slots.items() if p["dur"])
    page.evaluate(f"CRATE.TR.setLoop('{stem}',CRATE.MX.slots['{stem}'].bar0,2)")
    page.wait_for_function(f"CRATE.MX.slots['{stem}'].buf&&Math.abs(CRATE.MX.slots['{stem}'].buf.duration-4.8)<0.01", timeout=120000)
    page.click("#mxup")
    page.wait_for_function("CRATE.MX.rated>0", timeout=10000)
    # the waveform and its play line
    page.wait_for_function(f"(()=>{{const b=document.querySelector('[data-mxwave=\"{stem}\"]');return b&&b.querySelector('canvas').width>50&&getComputedStyle(b.querySelector('i')).display==='block'}})()", timeout=10000)
    # ↶ goes back to the part a slot held before a 🎲, ↷ forward again
    before = page.evaluate(f"[CRATE.MX.slots['{stem}'].track,CRATE.MX.slots['{stem}'].bar0]")
    page.click(f'[data-mxroll="{stem}"]')
    page.wait_for_function(f"(()=>{{const p=CRATE.MX.slots['{stem}'];return p&&p.buf&&!p._loading&&(p.track!=={before[0]}||p.bar0!=={before[1]})}})()", timeout=120000)
    after = page.evaluate(f"[CRATE.MX.slots['{stem}'].track,CRATE.MX.slots['{stem}'].bar0]")
    page.click(f'[data-mxhist="{stem}:-1"]')
    page.wait_for_function(f"(()=>{{const p=CRATE.MX.slots['{stem}'];return p.track==={before[0]}&&p.bar0==={before[1]}&&p.buf&&!p._loading}})()", timeout=120000)
    page.click(f'[data-mxhist="{stem}:1"]')
    page.wait_for_function(f"(()=>{{const p=CRATE.MX.slots['{stem}'];return p.track==={after[0]}&&p.bar0==={after[1]}&&p.buf&&!p._loading}})()", timeout=120000)
    # Use the C bass at its original pitch. A key-shifted deal can move a bass above the sub-bass cutoff.
    page.select_option("#mxkey", "C")
    _roll(page, "bass", 901)
    page.wait_for_function("CRATE.MX.slots.bass.sub>=0.85&&CRATE.MX.slots.bass.harm===1")
    assert "sub-bass" in page.locator('[data-mxrow="bass"] .mxsrc').inner_text()
    # the list of prepared songs, and a stem button that puts a song straight into a slot of that kind
    page.click("#mxsongs summary")
    page.wait_for_function("document.querySelectorAll('#mxsongs .mxsong').length===3", timeout=10000)
    page.evaluate("window._since=Object.fromEntries(Object.entries(CRATE.MX.slots).map(([id,p])=>[id,p&&p.since]))")
    page.click('[data-mxput="drums:903"]')
    # (the slot may already hold that song from the dice: wait for the part that was just put in, not just for the song)
    page.wait_for_function("Object.entries(CRATE.MX.slots).some(([id,p])=>CRATE.MX.roles[id]==='drums'&&p&&p.track===903&&p.buf&&!p._loading&&p.since!==window._since[id])", timeout=120000)
    page.wait_for_timeout(400)
    # ⇄ steps to another stretch of the same stem in the same song
    b0, tr = page.evaluate(f"[CRATE.MX.slots['{stem}'].bar0,CRATE.MX.slots['{stem}'].track]")
    _more(page, stem)
    page.click(f'[data-mxalt="{stem}"]')
    page.wait_for_function(f"CRATE.MX.slots['{stem}'].bar0!=={b0}&&CRATE.MX.slots['{stem}'].buf&&!CRATE.MX.slots['{stem}']._loading", timeout=120000)
    assert page.evaluate(f"CRATE.MX.slots['{stem}'].track") == tr and page.evaluate(f"CRATE.MX.slots['{stem}'].alt[1]") >= 2
    # ✕ takes a part out; 🔍 puts a chosen song in
    _more(page, stem)
    page.click(f'[data-mxdel="{stem}"]')
    page.wait_for_function(f"!CRATE.MX.slots['{stem}']", timeout=10000)
    _more(page, stem)
    page.click(f'[data-mxfind="{stem}"]')
    page.fill("#mxq", "Stem Artist 902")
    page.wait_for_selector(f'[data-mxsong="{stem}:902"]')
    page.keyboard.press("Enter")
    page.wait_for_function(f"CRATE.MX.slots['{stem}']&&CRATE.MX.slots['{stem}'].track===902&&CRATE.MX.slots['{stem}'].buf", timeout=120000)
    # save, clear all, open it again
    assert "dirty" in page.locator("#mxsave").get_attribute("class")      # unsaved changes: the button says so
    page.fill("#mxname", "ui mix")
    page.click("#mxsave")
    page.wait_for_selector("#mxload")
    page.wait_for_function("!document.querySelector('#mxsave').classList.contains('dirty')", timeout=10000)
    page.evaluate(f"(()=>{{const e=document.querySelector('[data-mxdb=\"{stem}\"]');e.value=-9;e.dispatchEvent(new Event('input',{{bubbles:true}}))}})()")
    assert "dirty" in page.locator("#mxsave").get_attribute("class")      # a volume change is a change
    page.click("#mxsave")
    page.wait_for_function("!document.querySelector('#mxsave').classList.contains('dirty')", timeout=10000)
    page.click("#mxclear")
    assert page.evaluate("Object.keys(CRATE.MX.slots).length") == 0
    page.select_option("#mxload", "ui mix")
    page.wait_for_function(f"CRATE.MX.slots['{stem}']&&CRATE.MX.slots['{stem}'].track===902&&CRATE.MX.slots['{stem}'].buf", timeout=120000)
    page.evaluate(f"CRATE.TR.setLoop('{stem}',CRATE.MX.slots['{stem}'].bar0,2)")
    page.wait_for_function(f"CRATE.MX.slots['{stem}'].buf&&Math.abs(CRATE.MX.slots['{stem}'].buf.duration-4.8)<0.01", timeout=120000)
    # ↺ revert: changes made to an open saved combination are dropped, and it's back as saved
    saved_track = page.evaluate(f"CRATE.MX.slots['{stem}'].track")
    _more(page, stem)
    page.click(f'[data-mxdel="{stem}"]')
    page.wait_for_function(f"!CRATE.MX.slots['{stem}']", timeout=10000)
    page.click("#mxrevert")
    page.wait_for_function(f"CRATE.MX.slots['{stem}']&&CRATE.MX.slots['{stem}'].track==={saved_track}&&CRATE.MX.slots['{stem}'].buf", timeout=120000)
    page.wait_for_function("!document.querySelector('#mxsave').classList.contains('dirty')", timeout=10000)
    page.evaluate(f"CRATE.TR.setLoop('{stem}',CRATE.MX.slots['{stem}'].bar0,2)")   # (the saved one had 4 bars: 2 again, for the reload check below)
    page.wait_for_function(f"CRATE.MX.slots['{stem}'].buf&&Math.abs(CRATE.MX.slots['{stem}'].buf.duration-4.8)<0.01", timeout=120000)
    # space starts and stops the mashup, also with a button focused (but not while typing a name)
    was = page.evaluate("CRATE.MX.on")
    page.locator("#mxsave").focus()
    page.keyboard.press("Space")
    page.wait_for_function(f"CRATE.MX.on==={'false' if was else 'true'}", timeout=10000)
    page.locator("#mxname").focus()
    page.keyboard.press("Space")
    assert page.evaluate("CRATE.MX.on") == (not was)
    page.locator("#mxsave").focus()
    page.keyboard.press("Space")
    page.wait_for_function(f"CRATE.MX.on==={'true' if was else 'false'}", timeout=10000)
    page.evaluate("(()=>{const e=document.querySelector('#mxname');e.value=e.value.trim();e.dispatchEvent(new Event('input',{bubbles:true}))})()")
    # ⌘Z undoes the last change in the mashup and ⌘⇧Z brings it back; the part keeps playing
    v0 = page.evaluate(f"CRATE.MX.slots['{stem}'].db||0")
    page.wait_for_timeout(700)
    page.evaluate(f"(()=>{{const e=document.querySelector('[data-mxdb=\"{stem}\"]');e.value=-11;e.dispatchEvent(new Event('input',{{bubbles:true}}));e.dispatchEvent(new Event('change',{{bubbles:true}}))}})()")
    page.locator("#mxsave").focus()
    page.keyboard.press("Meta+z")
    page.wait_for_function(f"(CRATE.MX.slots['{stem}'].db||0)==={v0}&&!!CRATE.MX.slots['{stem}'].buf", timeout=20000)
    page.keyboard.press("Meta+Shift+z")
    page.wait_for_function(f"CRATE.MX.slots['{stem}'].db===-11", timeout=20000)
    page.keyboard.press("Meta+z")
    page.wait_for_function(f"(CRATE.MX.slots['{stem}'].db||0)==={v0}", timeout=20000)
    # ⌘S on this tab saves the mashup (it used to save the sketch)
    page.evaluate(f"(()=>{{const e=document.querySelector('[data-mxdb=\"{stem}\"]');e.value=-5;e.dispatchEvent(new Event('input',{{bubbles:true}}))}})()")
    assert "dirty" in page.locator("#mxsave").get_attribute("class")
    page.keyboard.press("Meta+s")
    page.wait_for_function("!document.querySelector('#mxsave').classList.contains('dirty')", timeout=10000)
    # ⇩ Ableton sends the mixer as one section (or its snapshots, in order), with every slot's part and level
    sent = []
    def _grab(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(status=200, body=json.dumps(dict(als="x.als", tracks=4, clips=4, sections=1, bars=8)))
    page.route("**/api/stems/export", _grab)
    page.click("#mxexport")
    page.wait_for_function("document.querySelector('#toast').textContent.includes('Live set')", timeout=10000)
    page.unroute("**/api/stems/export")
    ex = sent[0]
    assert ex["bpm"] == 100 and len(ex["sections"]) == 1 and ex["bars"] == 8
    assert ex["sections"][0]["slots"][stem]["track"] == saved_track and ex["sections"][0]["slots"][stem]["db"] == -5
    # another slot (a second "other"), then its role changed to vocals: a part of the new kind comes in
    page.select_option("#mxaddrole", "other")
    page.click("#mxadd")
    page.wait_for_function("CRATE.MX.order.length===6&&CRATE.MX.slots[CRATE.MX.order[5]]&&CRATE.MX.slots[CRATE.MX.order[5]].buf", timeout=120000)
    new = page.evaluate("CRATE.MX.order[5]")
    assert page.evaluate(f"CRATE.MX.slots['{new}'].stem") == "other"
    _more(page, new)
    page.select_option(f'[data-mxrole="{new}"]', "vocals")
    page.wait_for_function(f"CRATE.MX.roles['{new}']==='vocals'&&CRATE.MX.slots['{new}']&&CRATE.MX.slots['{new}'].stem==='vocals'&&CRATE.MX.slots['{new}'].buf", timeout=120000)
    page.click("#mxplay")
    assert page.evaluate("CRATE.MX.on") is False
    page.reload()                                   # the tab and the combination come back
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'", timeout=30000)
    page.wait_for_function(f"CRATE.MX.slots['{stem}']&&CRATE.MX.slots['{stem}'].n===2", timeout=10000)
    assert page.evaluate("CRATE.MX.order.length") == 6 and page.evaluate(f"CRATE.MX.roles['{new}']") == "vocals"
    page.evaluate("localStorage.removeItem('dcStems')")   # the next tests start with the default four slots
    page.click("#tabS")


def test_sliders_look_off_at_their_minimum(page):
    """Every slider's fill starts at its minimum (or at zero for ranges that span it): nothing shows when it's off."""
    page.evaluate("""(()=>{const d=document.createElement('div');d.id='sltest';d.innerHTML='<input type="range" id="sl1" min="0" max="10" value="0"><input type="range" id="sl2" min="-12" max="12" value="0"><input type="range" id="sl3" min="0" max="10" value="5">';document.body.appendChild(d)})()""")
    page.wait_for_function("getComputedStyle(document.querySelector('#sl3')).getPropertyValue('--b').trim()!==''", timeout=5000)
    v = lambda i, k: float(page.evaluate(f"getComputedStyle(document.querySelector('#{i}')).getPropertyValue('--{k}')"))
    assert v("sl1", "a") == 0 and v("sl1", "b") == 0            # at the minimum: no fill
    assert v("sl2", "a") == 0.5 and v("sl2", "b") == 0.5        # at zero in a ± range: no fill
    assert v("sl3", "a") == 0 and v("sl3", "b") == 0.5
    page.evaluate("(()=>{const e=document.querySelector('#sl2');e.value=-6;e.dispatchEvent(new Event('input',{bubbles:true}))})()")
    assert v("sl2", "a") == 0.25 and v("sl2", "b") == 0.5       # below zero: the fill runs from the value up to zero
    page.evaluate("document.querySelector('#sltest').remove()")


# ---------------------------------------------------------------------------------------------------- stem blends
def _mixer(site, page, bpm=100):
    """🎛 Mashup on the three prepared test songs, with a part dealt into each of the four slots and playing."""
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout, r.stderr[-2000:]
    page.click("#tabM")
    page.wait_for_selector("#mxall")
    page.fill("#mxbpm", str(bpm))
    page.dispatch_event("#mxbpm", "change")
    page.click("#mxall")
    page.wait_for_function("CRATE.MX.on&&['drums','bass','vocals','other'].every(s=>CRATE.MX.slots[s]&&CRATE.MX.slots[s].buf)", timeout=90000)


def _set(page, sel, value, events=("input",)):
    """Set a slider or a number field the way a hand does: the value, then the events the app listens for."""
    page.evaluate("([sel,v,evs])=>{const e=document.querySelector(sel);e.value=v;evs.forEach(n=>e.dispatchEvent(new Event(n,{bubbles:true})))}",
                  [sel, str(value), list(events)])


BLEND_AUDIO = r"""async () => {
  const BL = window.BLEND, SR = 44100, N = 4 * SR, out = {};
  const db = x => 20 * Math.log10(Math.max(x, 1e-12));
  const rms = (d, a, b) => { let s = 0; for (let i = a; i < b; i++) s += d[i] * d[i]; return Math.sqrt(s / (b - a)); };
  const play = (ctx, buf) => { const s = ctx.createBufferSource(); s.buffer = buf; s.start(0); return s; };
  const noise = (ctx, secs, seed) => { const b = ctx.createBuffer(1, secs * SR, SR), d = b.getChannelData(0); let s = seed;
    for (let i = 0; i < d.length; i++) { s = (s * 16807) % 2147483647; d[i] = (s / 2147483647) * 2 - 1; } return b; };
  // the level of one band of a signal: three bandpasses in a row, rendered offline
  const band = async (data, f0, q) => { const c = new OfflineAudioContext(1, data.length, SR), b = c.createBuffer(1, data.length, SR);
    b.copyToChannel(data, 0); let n = play(c, b);
    for (let i = 0; i < 3; i++) { const f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = f0; f.Q.value = q; n.connect(f); n = f; }
    n.connect(c.destination); return (await c.startRendering()).getChannelData(0); };

  // 1. a parked blend filter passes everything, to the sample
  { const c = new OfflineAudioContext(1, SR, SR), nb = noise(c, 1, 7), x = BL.mkXf(c); play(c, nb).connect(x.in); x.out.connect(c.destination);
    const y = (await c.startRendering()).getChannelData(0), d = nb.getChannelData(0); let mx = 0;
    for (let i = 0; i < d.length; i++) mx = Math.max(mx, Math.abs(y[i] - d[i])); out.parked_max_diff = mx; }

  // 2. halfway through a filter handoff (cutoff 632 Hz): what is left of each side two octaves the wrong way, in dB
  out.handoff = {};
  for (const side of ['a', 'b']) { const c = new OfflineAudioContext(1, 2 * SR, SR), nb = noise(c, 2, side === 'a' ? 11 : 13), x = BL.mkXf(c), o = BL.blendAt('filter', 0.5, SR / 2);
    BL.setXf(x, side === 'a' ? { gain: o.ga, hp: o.hp, lp: SR / 2 } : { gain: o.gb, hp: 0, lp: o.lp }, 0);
    play(c, nb).connect(x.in); x.out.connect(c.destination); const y = (await c.startRendering()).getChannelData(0), d = nb.getChannelData(0);
    for (const f of [158, 2528]) out.handoff[side + '_' + f] = db(rms(await band(y, f, 4), SR, 2 * SR)) - db(rms(await band(d, f, 4), SR, 2 * SR)); }

  // 3. the duck: a kick on every beat at 120 bpm, at the loudness the server gives every part (RMS 0.08), over a bass of 55 Hz + 440 Hz
  const kick = ctx => { const b = ctx.createBuffer(1, N, SR), d = b.getChannelData(0);
    for (let beat = 0; beat < 8; beat++) { let ph = 0; const i0 = Math.round(beat * 0.5 * SR);
      for (let i = 0; i < 0.4 * SR; i++) { const t = i / SR; ph += 2 * Math.PI * (50 + 100 * Math.exp(-t / 0.03)) / SR; d[i0 + i] += Math.sin(ph) * Math.exp(-t / 0.12); } }
    const g = Math.min(0.08 / rms(d, 0, N), 0.9 / d.reduce((m, v) => Math.max(m, Math.abs(v)), 0)); for (let i = 0; i < N; i++) d[i] *= g; return b; };
  const bass = ctx => { const b = ctx.createBuffer(1, N, SR), d = b.getChannelData(0);
    for (let i = 0; i < N; i++) d[i] = 0.2 * Math.sin(2 * Math.PI * 55 * i / SR) + 0.1 * Math.sin(2 * Math.PI * 440 * i / SR); return b; };
  const O = { fx: true, bar: 2, DT: { '1/8': 1 / 8 } };
  const run = async (duck, drumsOn) => { const c = new OfflineAudioContext(2, N, SR), merge = c.createChannelMerger(2); merge.connect(c.destination);
    const MX = {}; BL.out(MX, c); MX.master.disconnect();                       // the bus without the speakers: each chain to its own channel
    const outB = c.createGain(), outK = c.createGain(); outB.connect(merge, 0, 0); outK.connect(merge, 0, 1);
    const cb = BL.mkChain(c, outB, MX.bus), ck = BL.mkChain(c, outK, MX.bus);
    BL.applyChain(cb, BL.mixOf({ db: 0 }, 'bass', { ...O, on: true, duck }), 0);
    BL.applyChain(ck, BL.mixOf({ db: 0 }, 'drums', { ...O, on: drumsOn }), 0);
    play(c, bass(c)).connect(cb.in); play(c, kick(c)).connect(ck.in); return (await c.startRendering()).getChannelData(0); };
  const ref = await run({ on: false }, true), lo0 = await band(ref, 55, 3), hi0 = await band(ref, 440, 6);
  const dip = async (duck, drumsOn) => { const y = await run(duck, drumsOn), lo = await band(y, 55, 3), hi = await band(y, 440, 6), w = Math.round(0.02 * SR), dips = [];
    for (let k = 0; k < 25; k++) { const a = 2 * SR + k * w; dips.push(db(rms(lo, a, a + w)) - db(rms(lo0, a, a + w))); }   // one beat, in 20 ms steps
    return { deepest: Math.min(...dips), shallowest: Math.max(...dips), high: db(rms(hi, 2 * SR, 3 * SR)) - db(rms(hi0, 2 * SR, 3 * SR)) }; };
  out.duck3 = await dip(undefined, true);            // no setting yet: on, 3 dB
  out.duck12 = await dip({ on: true, db: 12 }, true);
  out.muted = await dip({ on: true, db: 12 }, false); // muted drums duck nothing
  out.off = await dip({ on: false, db: 12 }, true);
  return out;
}"""


def test_blend_audio_core(page):
    """The stem blends audio graph, measured offline: a parked blend filter changes nothing, a filter handoff splits the
    spectrum between the two parts, and the duck takes a few dB off the bass's low end only, only under the kick."""
    o = page.evaluate(BLEND_AUDIO)
    assert o["parked_max_diff"] < 1e-6
    h = o["handoff"]
    assert h["a_158"] < -40 and h["b_2528"] < -40            # the outgoing part has no lows left, the incoming one no highs yet
    assert abs(h["a_2528"]) < 0.5 and abs(h["b_158"]) < 0.5  # and each keeps its own side whole
    assert -3.5 < o["duck3"]["deepest"] < -2.0 and o["duck3"]["shallowest"] > -0.5   # down under the kick, back between kicks
    assert abs(o["duck3"]["high"]) < 0.2                     # 440 Hz is left alone
    assert -13.0 < o["duck12"]["deepest"] < -9.0
    assert o["muted"]["deepest"] > -0.1 and o["off"]["deepest"] > -0.1


def test_duck_is_on_for_bass_and_remembered(site, page):
    """Bass Duck starts on at 3 dB, and keeps its switch and amount across a reload."""
    _mixer(site, page)
    assert page.locator('[data-mxduckon="bass"]').count() == 1
    assert page.locator('[data-mxduckon="drums"], [data-mxduckon="vocals"]').count() == 0
    assert page.evaluate("CRATE.MX.duck.bass?.db ?? BLEND.DUCK.db") == 3
    page.wait_for_function("CRATE.MX.slots.bass._c&&CRATE.MX.slots.bass._c.ducked===true&&CRATE.MX.slots.drums._c.ducked===false")
    page.evaluate("CRATE.TR.set('bass','duck',6)")
    assert page.evaluate("CRATE.MX.duck.bass.db") == 6
    page.click('[data-mxduckon="bass"]')
    page.wait_for_function("CRATE.MX.slots.bass._c.ducked===false&&CRATE.MX.duck.bass.on===false")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).duck.bass") == {"on": False, "db": 6}
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.duck.bass&&CRATE.MX.duck.bass.on===false", timeout=30000)


def test_state_saved_before_blends_still_opens(site, page):
    """A mixer saved before snapshots and the duck existed (no duck, snaps or trans keys) opens with their defaults."""
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout, r.stderr[-2000:]
    page.evaluate("""localStorage.setItem('dcStems',JSON.stringify({bpm:100,key:'',name:'',fx:true,order:['drums','bass','vocals','other'],
      roles:{drums:'drums',bass:'bass',vocals:'vocals',other:'other'},slots:{bass:{stem:'bass',track:901,bar0:0,n:4,k:1,off:0,bars:16,
      artist:'Stem Artist 901',title:'Song',db:-2,mute:false,lock:false,eq:[0,0,0],dly:0,dt:'1/8',eqOn:true,dlyOn:true}}}));localStorage.setItem('dcTab','M')""")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.slots.bass&&CRATE.MX.slots.bass.buf", timeout=120000)
    assert page.evaluate("[CRATE.MX.snaps.length,CRATE.MX.trans.length]") == [0, 0]
    assert page.evaluate("CRATE.MX.duck") == {}
    assert page.evaluate("CRATE.MX.duck.bass?.db ?? BLEND.DUCK.db") == 3


def _roll(page, slot, track):
    """Put this prepared song's best-fitting bars into a slot, and wait until they are loaded."""
    page.evaluate(f"CRATE.mxRoll('{slot}', true, {track})")
    page.wait_for_function(f"CRATE.MX.slots['{slot}']&&CRATE.MX.slots['{slot}'].track==={track}&&CRATE.MX.slots['{slot}'].buf&&!CRATE.MX.slots['{slot}']._loading", timeout=120000)


def test_snapshots_capture_recall_replace_delete(site, page):
    """📸 keeps the mixer as it is; a snapshot comes back with a click, can be replaced and deleted, survives a reload,
    freezes an auto key, and teaches the recommendations."""
    _mixer(site, page)
    assert page.evaluate("CRATE.MX.snaps.length") == 0 and page.is_disabled("#snplay")
    _roll(page, "drums", 901)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===1&&CRATE.MX.snapSel===0")
    assert page.evaluate("CRATE.MX.key") != ""                                   # an auto key is frozen by the first snapshot
    page.wait_for_function("CRATE.MX.rated>=4", timeout=10000)                   # four slots, four weak yeses
    _roll(page, "drums", 902)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===2&&CRATE.MX.snapSel===1")
    label = page.inner_text('[data-sn="1"]')
    assert "B" in label and "drums" in label and "bass" not in label             # what changed since A
    assert "start" in page.inner_text('[data-sn="0"]')
    assert page.evaluate("CRATE.MX.trans.length") == 1 and page.is_enabled("#snplay")
    page.click('[data-sn="0"]')                                                  # A comes back
    page.wait_for_function("CRATE.MX.snapSel===0&&CRATE.MX.slots.drums.track===901&&CRATE.MX.slots.drums.buf", timeout=120000)
    bass = page.evaluate("CRATE.MX.slots.bass.track")
    _roll(page, "bass", 903 if bass != 903 else 901)
    page.click("#snrep")                                                         # ... and is replaced by what is playing now
    page.wait_for_function(f"CRATE.MX.snaps[0].slots.bass.track!=={bass}")
    assert page.evaluate("CRATE.MX.snaps.length") == 2
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.snaps.length===2", timeout=30000)
    assert page.evaluate("[CRATE.MX.snaps[0].slots.drums.track,CRATE.MX.snaps[1].slots.drums.track,CRATE.MX.trans.length]") == [901, 902, 1]
    page.click('[data-sn="1"]')
    page.wait_for_function("CRATE.MX.snapSel===1")
    page.click("#sndel")
    page.wait_for_function("CRATE.MX.snaps.length===1&&CRATE.MX.trans.length===0&&CRATE.MX.snapSel===null")
    assert page.is_disabled("#snplay")


def test_blend_model(page):
    """The pure half of the stem blends block: which layers differ between two snapshots, each transition's settings (kept from
    the transition before), where a layer is for a master position, and the mix of a layer that stays."""
    r = page.evaluate("""() => { const B = BLEND, P = (stem, track, o) => Object.assign({stem, track, bar0: 0, n: 4, k: 1, off: 0, db: 0, eq: [0, 0, 0], dly: 0, dt: '1/8'}, o);
      const A = {order: ['drums', 'bass', 'vocals', 'other'], roles: {drums: 'drums', bass: 'bass', vocals: 'vocals', other: 'other'}, duck: {},
                 slots: {drums: P('drums', 1), bass: P('bass', 2, {db: -2}), vocals: P('vocals', 3, {mute: true})}};
      const Z = {order: ['drums', 'bass', 'vocals', 'other', 's1'], roles: {drums: 'drums', bass: 'bass', vocals: 'vocals', other: 'vocals', s1: 'other'}, duck: {},
                 slots: {drums: P('drums', 1, {bar0: 4}), bass: P('bass', 2, {db: -4}), other: P('vocals', 5), s1: P('other', 6)}};
      const rows = B.diffSnaps(A, Z), MX = {snaps: [A, Z, A], trans: [{bars: 4, layers: {drums: {style: 'xfade', win: 'second'}}}, {bars: 16, layers: {}}]};
      const T = B.transFor(MX, 0);
      return {rows: rows.map(x => [x.id, x.stem, x.kind]), back: B.diffSnaps(Z, A).map(x => [x.id, x.kind]), t0: T, t1: B.transFor(MX, 1),
        pos: [B.rowPos(rows[0], 0.75, T, {}), B.rowPos(rows[1], 0.75, T, {}), B.rowPos(rows[0], 0.75, T, {drums: 0.1})],
        mix: B.lerpMix(P('bass', 2, {db: -2, eq: [2, 0, 0], dly: 0.4, dt: '1/4'}), P('bass', 2, {db: -4, eq: [6, 0, 0], eqOn: false, dly: 0, dt: '1/16'}), 0.25),
        lp: [B.layerPos(0.25, 'all'), B.layerPos(0.25, 'first'), B.layerPos(0.25, 'second'), B.layerPos(0.75, 'second'), B.layerPos(0.49, 'cut'), B.layerPos(0.5, 'cut')],
        b: [B.blendAt('filter', 0, 22050), B.blendAt('filter', 0.5, 22050), B.blendAt('xfade', 0.5, 22050), B.blendAt('filter', 1, 22050), B.blendAt('filter', 0.025, 22050)]}; }""")
    # a moved loop is a changed layer; a volume change alone is not; a muted part counts as absent; a slot's stem is the side that sounds
    assert r["rows"] == [["drums", "drums", "change"], ["bass", "bass", "same"], ["vocals", "vocals", "empty"], ["other", "vocals", "enter"], ["s1", "other", "enter"]]
    assert r["back"] == [["drums", "change"], ["bass", "same"], ["vocals", "empty"], ["other", "exit"], ["s1", "exit"]]
    new = {"style": "filter", "win": "all"}
    assert r["t0"] == {"bars": 4, "layers": {"drums": {"style": "xfade", "win": "second"}, "other": new, "s1": new}}
    assert r["t1"] == {"bars": 16, "layers": {"drums": {"style": "xfade", "win": "second"}, "other": new, "s1": new}}   # drums: from the transition before
    assert r["pos"] == [0.5, 0.75, 0.1]
    m = r["mix"]
    assert m["db"] == -2.5 and m["eq"] == [1.5, 0, 0] and abs(m["dly"] - 0.3) < 1e-9 and m["dt"] == "1/4" and m["eqOn"] is True and m["dlyOn"] is True
    assert r["lp"] == [0.25, 0.5, 0, 0.5, 0, 1]
    b = r["b"]
    assert b[0] == {"ga": 1, "gb": 0, "hp": 0, "lp": 22050} and b[3] == {"ga": 0, "gb": 1, "hp": 0, "lp": 22050}
    assert b[1]["ga"] == 1 and b[1]["gb"] == 1 and abs(b[1]["hp"] - 632.4555) < 0.001 and b[1]["lp"] == b[1]["hp"]
    assert abs(b[2]["ga"] - 0.70711) < 1e-4 and abs(b[2]["gb"] - 0.70711) < 1e-4 and b[2]["hp"] == 0 and b[2]["lp"] == 22050
    assert b[4]["ga"] == 1 and abs(b[4]["gb"] - 0.5) < 1e-9


def _strip(site, page, bpm=100, three=False):
    """A strip on the test songs: A (drums from song 901), B (drums from 902, "other" taken out) and, with three=True,
    C (bass from another song)."""
    _mixer(site, page, bpm)
    _roll(page, "drums", 901)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===1")
    _roll(page, "drums", 902)
    _more(page, 'other')
    page.click('[data-mxdel="other"]')
    page.wait_for_function("!CRATE.MX.slots.other")
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===2")
    if three:
        bass = page.evaluate("CRATE.MX.slots.bass.track")
        _roll(page, "bass", 903 if bass != 903 else 901)
        page.click("#sncap")
        page.wait_for_function("CRATE.MX.snaps.length===3")


def _voice(page, slot, side):
    """What a playback voice was last told: its gain, highpass and lowpass, and how long its loop is. None if there is none."""
    return page.evaluate(f"(()=>{{const v=CRATE.PB.voice('{slot}','{side}');return v?{{...v.set,dur:v.buf.duration}}:null}})()")


def test_playback_shows_both_sets_and_blends_by_hand(site, page):
    """▶ play strip: both snapshots' four slots side by side, the transition controls between them, and a master and a
    slider per layer that move the sound from the left snapshot to the right one."""
    _strip(site, page)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    assert page.evaluate("CRATE.MX.on") is False and page.is_visible("#pb")
    assert page.locator('#pb [data-pbside="a"]').count() == 5 and page.locator('#pb [data-pbside="b"]').count() == 5
    assert page.evaluate("CRATE.PB.rows.map(r=>[r.id,r.kind])") == [["drums", "change"], ["tops", "empty"], ["bass", "same"], ["vocals", "same"], ["other", "exit"]]
    a, b = _voice(page, "drums", "a"), _voice(page, "drums", "b")
    assert a["gain"] == 1 and b["gain"] == 0 and abs(b["dur"] - 9.6) < 0.01                 # 4 bars at 100 bpm, loaded but silent
    assert page.evaluate("CRATE.PB.voice('bass','a')===CRATE.PB.voice('bass','b')")          # a layer that stays is one voice
    assert "same in both" in page.inner_text('[data-pbrow="bass"]')
    # every slot shows its waveform with a play line, as the mixer's rows do
    page.wait_for_function("(()=>{const b=document.querySelector('[data-pbwave=\"b:drums\"]');return b&&b.querySelector('canvas').width>50&&getComputedStyle(b.querySelector('i')).display==='block'})()", timeout=10000)
    _set(page, "#pbm", 50)                                                                   # the master, halfway
    assert page.evaluate("CRATE.PB.m") == 0.5 and page.input_value('[data-pbpos="drums"]') == "50"
    a, b = _voice(page, "drums", "a"), _voice(page, "drums", "b")
    assert a["gain"] == 1 and b["gain"] == 1 and abs(a["hp"] - 632.46) < 0.1 and abs(b["lp"] - 632.46) < 0.1 and b["hp"] == 0
    assert abs(_voice(page, "other", "a")["hp"] - 632.46) < 0.1 and _voice(page, "other", "b") is None   # leaves alone
    page.select_option('[data-pbstyle="drums"]', "xfade")
    a, b = _voice(page, "drums", "a"), _voice(page, "drums", "b")
    assert abs(a["gain"] - 0.7071) < 0.001 and abs(b["gain"] - 0.7071) < 0.001 and a["hp"] == 0
    page.select_option('[data-pbwin="drums"]', "second")                                     # changes over the second half only
    assert page.evaluate("CRATE.PB.pos('drums')") == 0 and _voice(page, "drums", "b")["gain"] == 0
    _set(page, "#pbm", 75)
    assert page.evaluate("CRATE.PB.pos('drums')") == 0.5
    _set(page, '[data-pbpos="other"]', 100, ("input", "change"))                            # one layer by hand
    assert page.evaluate("[CRATE.PB.pos('other'),CRATE.PB.m]") == [1, 0.75]
    assert page.locator('[data-pbrow="other"] .tag.hot').count() == 1 and page.locator('[data-pbwin="other"]').count() == 0
    _set(page, "#pbm", 100)
    assert page.evaluate("CRATE.PB.atEnd(1)") is True and page.is_disabled("#pbnext")        # B is the last snapshot
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).trans[0].layers.drums") == {"style": "xfade", "win": "second"}
    page.click("#pbback")
    page.wait_for_selector("#mxall")
    assert page.evaluate("CRATE.PB.on") is False
    _set(page, "#mxbpm", 120, ("change",))                                                   # the strip plays at the mixer's tempo
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    assert abs(_voice(page, "drums", "a")["dur"] - 8.0) < 0.01


def test_playback_arrows_walk_the_strip(site, page):
    """Fully on the right snapshot, ▶ moves the view on: B to the left without a gap in its sound, C on the right.
    ◀ goes back. A part whose song is no longer prepared shows as missing and the rest plays on."""
    _strip(site, page, three=True)
    page.evaluate("CRATE.MX.snapSel=null;CRATE.MX.snaps[2].slots.vocals.track=999999")   # (not on a snapshot: nothing of the mixer is written into one)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing&&CRATE.PB.nextReady", timeout=90000)
    assert page.is_disabled("#pbnext") and page.is_disabled("#pbprev")
    _set(page, "#pbm", 100)
    page.wait_for_function("!document.querySelector('#pbnext').disabled")
    key, t = page.evaluate("[CRATE.PB.voice('drums','b').key,CRATE.PB.voice('drums','b').t]")
    page.click("#pbnext")
    page.wait_for_function("CRATE.PB.i===1&&CRATE.PB.ready", timeout=120000)
    assert page.evaluate("[CRATE.PB.m,[...document.querySelectorAll('#pb .pbletter')].map(e=>e.textContent)]") == [0, ["B", "C"]]
    assert page.evaluate("[CRATE.PB.voice('drums','a').key,CRATE.PB.voice('drums','a').t]") == [key, t]     # B's drums never stopped
    assert "missing" in page.inner_text('[data-pbrow="vocals"] [data-pbside="b"]')
    assert page.evaluate("CRATE.PB.rows.find(r=>r.id==='vocals').kind") == "exit"
    assert page.is_disabled("#pbnext")                                                                    # C is the last one
    page.click("#pbprev")
    page.wait_for_function("CRATE.PB.i===0&&CRATE.PB.ready", timeout=120000)
    assert page.evaluate("CRATE.PB.m") == 1


def test_playback_waits_for_the_next_snapshot(site, page):
    """The arrow stays off until the next snapshot's parts are loaded, however long that takes."""
    _strip(site, page, three=True)
    page.evaluate("""(()=>{const api=CRATE.api,slow=CRATE.MX.snaps[2].slots.bass.track;
      CRATE.api=(p,b)=>p==='api/stems/render'&&b.stem==='bass'&&b.track===slow?new Promise(r=>setTimeout(r,4000)).then(()=>api(p,b)):api(p,b)})()""")
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    _set(page, "#pbm", 100)
    assert page.evaluate("CRATE.PB.nextReady") is False and page.is_disabled("#pbnext")
    page.wait_for_function("CRATE.PB.nextReady&&!document.querySelector('#pbnext').disabled", timeout=20000)


def test_auto_walks_the_strip_and_hands_back_control(site, page):
    """auto: hold a snapshot, move the master across over the transition's bars, move the view on, and stop on the last
    snapshot. A hand on a slider switches it off where it stands."""
    _strip(site, page, bpm=200, three=True)                  # 200 bpm: a bar lasts 1.2 s
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing&&CRATE.PB.nextReady", timeout=90000)
    page.select_option("#pbbars", "2")
    page.evaluate("CRATE.PB.setHold(1)")                     # the menu offers 4, 8 and 16 bars: one keeps the test short
    page.click("#pbauto")
    assert page.evaluate("CRATE.PB.auto") is True
    page.wait_for_function("CRATE.PB.i===0&&CRATE.PB.m>0.2&&CRATE.PB.m<1", timeout=15000)   # moving, after the hold
    assert "bar" in page.inner_text("#pbstat")
    page.wait_for_function("CRATE.PB.i===1", timeout=15000)                                # on B: the view moved on by itself
    _set(page, "#pbm", 30)                                                                  # a hand on the master
    assert page.evaluate("[CRATE.PB.auto,CRATE.PB.m]") == [False, 0.3]
    page.click("#pbauto")                                                                   # on again from where it stands
    page.wait_for_function("CRATE.PB.i===1&&CRATE.PB.m===1&&CRATE.PB.auto===false", timeout=30000)   # the last snapshot: it stays


def test_auto_holds_after_a_slow_next_snapshot(site, page):
    """auto waits on a snapshot that loads slowly, and once it is in, holds it before moving on: it never skips the
    hold or cuts through the transition because the wait was long."""
    _strip(site, page, bpm=200, three=True)                  # a bar lasts 1.2 s
    page.evaluate("""(()=>{const api=CRATE.api,slow=CRATE.MX.snaps[2].slots.bass.track;
      CRATE.api=(p,b)=>p==='api/stems/render'&&b.stem==='bass'&&b.track===slow?new Promise(r=>setTimeout(r,12000)).then(()=>api(p,b)):api(p,b)})()""")
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    page.select_option("#pbbars", "2")
    page.evaluate("CRATE.PB.setHold(1)")
    page.click("#pbauto")
    page.wait_for_function("CRATE.PB.i===1&&CRATE.PB.ready", timeout=40000)
    page.wait_for_timeout(300)
    assert page.evaluate("[CRATE.PB.auto,CRATE.PB.m,CRATE.PB.ph&&CRATE.PB.ph.kind]") == [True, 0, "hold"]


def test_a_failed_info_call_keeps_the_pair_playing(site, page):
    """When the server cannot answer for the next pair, ▶ leaves the view where it is and the sound playing; nothing
    is marked missing."""
    _strip(site, page, three=True)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing&&CRATE.PB.nextReady", timeout=90000)
    _set(page, "#pbm", 100)
    page.wait_for_function("!document.querySelector('#pbnext').disabled")
    page.evaluate("""(()=>{const api=CRATE.api;CRATE.api=(p,b)=>p==='api/stems/info'?Promise.reject(new Error('down')):api(p,b)})()""")
    page.click("#pbnext")
    page.wait_for_timeout(1500)
    assert page.evaluate("[CRATE.PB.i,CRATE.PB.ready,!!(CRATE.PB.voice('drums','b')&&CRATE.PB.voice('drums','b').src)]") == [0, True, True]
    assert "missing" not in page.inner_text("#pb")


def test_changing_the_length_during_auto_does_not_jump(site, page):
    """A new transition length while auto is moving changes its speed from where the master is, not its position."""
    _strip(site, page, bpm=200, three=True)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing&&CRATE.PB.nextReady", timeout=90000)
    page.evaluate("CRATE.PB.setHold(1)")
    page.click("#pbauto")                                    # over 8 bars: 9.6 s
    page.wait_for_function("CRATE.PB.m>0.3", timeout=20000)
    page.select_option("#pbbars", "2")
    page.wait_for_timeout(150)
    assert page.evaluate("CRATE.PB.m") < 0.6 and page.evaluate("CRATE.PB.i") == 0


def test_snapshot_says_when_the_mixer_has_moved_on(site, page):
    """Edits change the mixer, not the snapshot it came from: the strip says so and points at ↻ replace."""
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout, r.stderr[-2000:]
    page.evaluate("localStorage.removeItem('dcStems')")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&window.CRATE&&CRATE.MX", timeout=30000)
    page.click("#tabM")
    page.wait_for_selector("#mxall")
    page.click("#mxall")
    page.wait_for_function("Object.values(CRATE.MX.slots).some(p=>p&&p.buf)", timeout=90000)
    page.click("#sncap")
    page.wait_for_selector("#snrep")
    assert "dirty" not in (page.locator("#snrep").get_attribute("class") or "")
    sid = page.evaluate("CRATE.MX.order.find(id=>CRATE.MX.slots[id]&&CRATE.MX.slots[id].buf)")
    page.click(f'[data-mxmute="{sid}"]')
    page.wait_for_function("document.querySelector('#snrep').classList.contains('dirty')", timeout=5000)
    assert "changed since A: kept in A when you move on" in page.inner_text("#snnote")
    assert page.evaluate(f"CRATE.MX.snaps[0].slots['{sid}'].mute") is False      # the snapshot itself is untouched
    page.click("#snrep")
    page.wait_for_function("!document.querySelector('#snrep').classList.contains('dirty')", timeout=5000)
    assert page.evaluate(f"CRATE.MX.snaps[0].slots['{sid}'].mute") is True       # ↻ wrote the change into it
    # a snapshot click replaces the mixer: when what was there isn't in any snapshot, it can be undone
    _more(page, sid)
    page.click(f'[data-mxdel="{sid}"]')
    page.wait_for_function(f"!CRATE.MX.slots['{sid}']", timeout=10000)
    page.click('[data-sn="0"]')
    page.wait_for_function(f"CRATE.MX.snapSel===0&&CRATE.MX.slots['{sid}']&&CRATE.MX.slots['{sid}'].buf", timeout=120000)
    page.wait_for_selector("#snundo")
    page.click("#snundo")
    page.wait_for_function(f"!CRATE.MX.slots['{sid}']&&CRATE.MX.snapSel===null", timeout=30000)
    # clear all is a clean slate: the strip goes too (asked once more first), so it can't tag along into the next one
    place = page.evaluate("JSON.stringify([...document.querySelectorAll('#mxclear,#mxexport')].map(b=>{const r=b.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top),Math.round(r.width)]}))")
    page.click("#mxclear")
    # asking first: the button says so in place (nothing in the bar moves)
    assert page.evaluate("CRATE.MX.snaps.length") == 1 and page.inner_text("#mxclear") == "sure?"
    assert place == page.evaluate("JSON.stringify([...document.querySelectorAll('#mxclear,#mxexport')].map(b=>{const r=b.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top),Math.round(r.width)]}))")
    page.click("#mxclear")
    assert page.evaluate("CRATE.MX.snaps.length") == 0 and page.evaluate("Object.keys(CRATE.MX.slots).length") == 0
    page.evaluate("CRATE.mxPlay(false)")
    page.evaluate("localStorage.removeItem('dcStems')")
    page.click("#tabS")


def test_reverb_has_a_tail_that_decays_and_is_stereo(page):
    """The mixer's reverb, measured offline: a short burst rings on, dies away at about the decay time, and left and
    right differ (it is wide). A longer decay rings longer."""
    r = page.evaluate("""async()=>{
      const run=async(type,decay)=>{const sr=44100,c=new OfflineAudioContext(2,sr*4,sr),out=c.createGain();out.connect(c.destination);
        const rv=BLEND.reverb(c,out,{type,decay}),b=c.createBuffer(1,Math.floor(0.03*sr),sr),d=b.getChannelData(0);
        for(let i=0;i<d.length;i++)d[i]=Math.sin(i*0.9)*Math.sin(i*0.31)*0.8;            // a 30 ms burst with highs and mids
        const s=c.createBufferSource();s.buffer=b;s.connect(rv.in);s.start(0);
        const o=await c.startRendering(),L=o.getChannelData(0),R=o.getChannelData(1);
        const rms=(x,a,z)=>{let e=0;const i0=Math.floor(a*sr),i1=Math.floor(z*sr);for(let i=i0;i<i1;i++)e+=x[i]*x[i];return Math.sqrt(e/(i1-i0))};
        let num=0,dl=0,dr=0;for(let i=Math.floor(0.1*sr);i<sr;i++){num+=L[i]*R[i];dl+=L[i]*L[i];dr+=R[i]*R[i]}
        return {early:rms(L,0.1,0.3),late:rms(L,decay-0.1,decay+0.1),end:rms(L,3.5,3.9),corr:num/Math.sqrt(dl*dr+1e-20)}};
      return {plate:await run('plate',1.5),hall:await run('hall',3.0)}}""")
    import math
    p, h = r["plate"], r["hall"]
    assert p["early"] > 1e-4                                            # it rings on after the 30 ms burst
    drop = 20 * math.log10(p["late"] / p["early"])                      # by the decay time it is far down
    assert -70 < drop < -30, drop
    assert abs(p["corr"]) < 0.4                                         # left and right are different: wide, not mono
    assert h["end"] > 5 * p["end"]                                      # the hall is still ringing when the plate is gone


def test_mashup_reverb_send_and_bar_axis(site, page):
    """A slot's REVERB send reaches the shared reverb; its type is set at the top; the waveform stays visible."""
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout, r.stderr[-2000:]
    page.evaluate("localStorage.removeItem('dcStems')")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&window.CRATE&&CRATE.MX", timeout=30000)
    page.click("#tabM")
    page.wait_for_selector("#mxall")
    page.click("#mxall")
    page.wait_for_function("Object.values(CRATE.MX.slots).some(p=>p&&p.buf)", timeout=90000)
    page.wait_for_function("CRATE.MX.on&&CRATE.MX.order.some(id=>CRATE.MX.slots[id]&&CRATE.MX.slots[id]._c)", timeout=90000)
    sid = page.evaluate("CRATE.MX.order.find(id=>CRATE.MX.slots[id]&&CRATE.MX.slots[id]._c)")   # (a slot's chain exists once it plays)
    page.evaluate("id=>CRATE.TR.set(id,'rev',50)", sid)
    page.wait_for_function(f"Math.abs(CRATE.MX.slots['{sid}']._c.rsend.gain.value-0.5)<0.02", timeout=5000)
    page.click(f'[data-mxrevon="{sid}"]')                                # off: nothing is sent, the setting is kept
    page.wait_for_function(f"CRATE.MX.slots['{sid}']._c.rsend.gain.value<0.02", timeout=5000)
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].rev") == 0.5
    page.select_option("#mxrvtype", "hall")
    page.wait_for_function("CRATE.MX.reverb.type==='hall'&&CRATE.MX.bus.rev.type==='hall'", timeout=5000)
    assert page.evaluate(f"document.querySelector('[data-mxwave=\"{sid}\"] canvas').height") > 40
    page.evaluate("CRATE.mxPlay(false)")
    page.evaluate("localStorage.removeItem('dcStems')")
    page.click("#tabS")


def test_mashup_one_shot_slot(site, page):
    """✦ one-shot: a library sample in a slot, placed on steps of a cycle of bars, played on the mixer's clock."""
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout, r.stderr[-2000:]
    page.evaluate("localStorage.removeItem('dcStems')")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&!!(window.CRATE&&CRATE.MX&&CRATE.mxAddOneShot)", timeout=30000)
    i = page.evaluate("S.findIndex(s=>s[F.kind]==='oneshot'&&s[F.dur]<2)")
    assert i >= 0
    page.evaluate(f"CRATE.mxAddOneShot({i})")                       # as ✦ Mashup in the sample panel does
    page.wait_for_function("CRATE.MX.order.some(id=>CRATE.MX.roles[id]==='oneshot'&&CRATE.MX.slots[id]&&CRATE.MX.slots[id].buf)", timeout=120000)
    sid = page.evaluate("CRATE.MX.order.find(id=>CRATE.MX.roles[id]==='oneshot')")
    page.click("#tabM")
    page.wait_for_selector(f'[data-mxstep="{sid}:0"]')
    assert page.locator(f'[data-mxrow="{sid}"] .mxst').count() == 16 and page.evaluate(f"CRATE.MX.slots['{sid}'].steps") == [0]
    page.evaluate("""id=>{
      const create = AC.createBufferSource.bind(AC);
      AC.createBufferSource = () => {
        const source = create(), start = source.start.bind(source);
        source.start = (...args) => { window.auditionRate = source.playbackRate.value; return start(...args); };
        return source;
      };
      CRATE.TR.set(id, 'st', 5);
      CRATE.TR.set(id, 'ct', 25);
    }""", sid)
    page.click(f'[data-mxaud="{sid}"]')
    assert page.evaluate("auditionRate") == pytest.approx(2 ** (5.25 / 12))
    page.click(f'[data-mxstep="{sid}:10"]')                          # a hit in the middle of the bar
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].steps") == [0, 10]
    page.select_option(f'[data-mxlen="{sid}"]', "2")                 # a two-bar cycle: 32 steps, the hits stay
    assert page.locator(f'[data-mxrow="{sid}"] .mxst').count() == 32
    page.click(f'[data-mxstep="{sid}:30"]')                          # ... and one at the end of bar 2
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].steps") == [0, 10, 30]
    # trim: drag across the small waveform to choose the piece that plays; double-click for the whole sample
    tb = page.locator(f'canvas[data-mxtrim="{sid}"]').bounding_box()
    page.mouse.move(tb["x"] + tb["width"] * 0.25, tb["y"] + 10)
    page.mouse.down()
    page.mouse.move(tb["x"] + tb["width"] * 0.75, tb["y"] + 10, steps=5)
    page.mouse.up()
    tr = page.evaluate(f"CRATE.MX.slots['{sid}'].trim")
    assert abs(tr[0] - 0.25) < 0.03 and abs(tr[1] - 0.75) < 0.03
    page.dblclick(f'canvas[data-mxtrim="{sid}"]')
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].trim") is None
    page.click(f'[data-mxhk="{sid}"]')
    page.wait_for_function("id=>!CRATE.MX.slots[id].hk", arg=sid)
    harmonics = page.locator(f'[data-mxharm="{sid}"]')
    harmonics.click()
    assert harmonics.get_attribute("aria-pressed") == "true"
    # Audition after each change so the browser is pulling audio through the harmonics path.
    page.click(f'[data-mxaud="{sid}"]')
    page.wait_for_function("id=>Math.abs(CRATE.MX.slots[id]._c.hg.gain.value-0.35)<0.01", arg=sid)
    assert page.evaluate("id=>JSON.parse(localStorage.getItem('dcStems')).slots[id].harm", sid) == 1
    harmonics.click()
    assert harmonics.get_attribute("aria-pressed") == "false"
    page.click(f'[data-mxaud="{sid}"]')
    page.wait_for_function("id=>CRATE.MX.slots[id]._c.hg.gain.value<0.01", arg=sid)
    # ⤢ the large trim view: the same drag on a much wider waveform, shift for fine, nudges of 5 ms
    page.click(f'[data-mxtrimopen="{sid}"]')
    big = page.locator(f'canvas.mxtrim.big[data-mxtrim="{sid}"]')
    bb = big.bounding_box()
    assert bb["width"] > 4 * tb["width"]
    page.mouse.move(bb["x"] + bb["width"] * 0.2, bb["y"] + 40)
    page.mouse.down()
    page.mouse.move(bb["x"] + bb["width"] * 0.6, bb["y"] + 40, steps=5)
    page.mouse.up()
    tr = page.evaluate(f"CRATE.MX.slots['{sid}'].trim")
    assert abs(tr[0] - 0.2) < 0.01 and abs(tr[1] - 0.6) < 0.01
    # on an edge the pointer shows ↔ and a drag moves that edge only; elsewhere it is a cross (a drag draws a new piece)
    cur = lambda: page.locator(f'canvas.mxtrim.big[data-mxtrim="{sid}"]').evaluate("e=>getComputedStyle(e).cursor")
    page.mouse.move(bb["x"] + bb["width"] * 0.45, bb["y"] + 40)
    assert cur() == "crosshair"
    page.mouse.move(bb["x"] + bb["width"] * 0.2 + 5, bb["y"] + 40)
    assert cur() == "ew-resize"
    page.mouse.down()
    page.mouse.move(bb["x"] + bb["width"] * 0.3 + 5, bb["y"] + 40, steps=5)
    page.mouse.up()
    tr = page.evaluate(f"CRATE.MX.slots['{sid}'].trim")
    assert abs(tr[0] - 0.3) < 0.01 and abs(tr[1] - 0.6) < 0.01                       # the right edge stayed
    dur = page.evaluate(f"CRATE.MX.slots['{sid}'].buf.duration")
    page.click(f'[data-mxnudge="{sid}:0:1"]')                        # the start, 5 ms later
    assert abs(page.evaluate(f"CRATE.MX.slots['{sid}'].trim[0]") - (tr[0] + 0.005 / dur)) < 1e-6
    assert "start" in page.inner_text(f'[data-mxtrimtxt="{sid}"]')
    page.click(f'[data-mxtrimall="{sid}"]')
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].trim") is None
    # fades, and warping the piece to an exact length at the tempo (its pitch kept)
    page.evaluate(f"(()=>{{const e=document.querySelector('[data-mxfade=\"{sid}:fout\"]');e.value=120;e.dispatchEvent(new Event('input',{{bubbles:true}}));e.dispatchEvent(new Event('change',{{bubbles:true}}))}})()")
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].fout") == 120
    beat = 60 / page.evaluate("CRATE.MX.bpm")
    fit = next(b for b in (1, 2, 4, 8) if 0.45 < b * beat / dur < 2.4)
    _calls(page)
    page.select_option(f'[data-mxwarp="{sid}"]', str(fit))
    page.wait_for_function(f"(p=>p.warp==={fit}&&p.wbuf&&Math.abs(p.wbuf.duration-{fit * beat})<0.01)(CRATE.MX.slots['{sid}'])", timeout=120000)
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/oswarp').at(-1)[1].semis") == 5.25
    page.evaluate("id=>CRATE.TR.set(id,'ct',-20)", sid)
    page.wait_for_function("id=>CRATE.MX.slots[id]._wkey?.endsWith('|4.8')", arg=sid)
    page.select_option(f'[data-mxwarp="{sid}"]', "0")
    page.wait_for_function(f"!CRATE.MX.slots['{sid}'].wbuf", timeout=20000)
    # ... or to any length in beats (a 16th is 0.25; anything finer can be typed)
    odd = round(fit * 1.1, 2)
    page.fill(f'[data-mxwarpn="{sid}"]', str(odd)); page.dispatch_event(f'[data-mxwarpn="{sid}"]', "change")
    page.wait_for_function(f"(p=>p.warp==={odd}&&p.wbuf&&Math.abs(p.wbuf.duration-{odd * beat})<0.01)(CRATE.MX.slots['{sid}'])", timeout=120000)
    assert f"fit {odd:g} beats" in page.inner_text(f'[data-mxwarp="{sid}"]')
    page.fill(f'[data-mxwarpn="{sid}"]', ""); page.dispatch_event(f'[data-mxwarpn="{sid}"]', "change")
    page.wait_for_function(f"!CRATE.MX.slots['{sid}'].wbuf", timeout=20000)
    page.click(f'.mxtrimbar [data-mxtrimopen="{sid}"]')              # done
    assert page.locator(".mxtrimbox").count() == 0
    # ⧉ duplicate: the same sample, placement and settings in a new slot right below
    _more(page, sid)
    page.click(f'[data-mxdup="{sid}"]')
    dup = page.evaluate(f"CRATE.MX.order[CRATE.MX.order.indexOf('{sid}')+1]")
    assert page.evaluate(f"CRATE.MX.roles['{dup}']") == "oneshot" and page.evaluate(f"CRATE.MX.slots['{dup}'].steps") == [0, 10, 30]
    assert page.evaluate(f"CRATE.MX.slots['{dup}'].sample===CRATE.MX.slots['{sid}'].sample&&!!CRATE.MX.slots['{dup}'].buf")
    page.click(f'[data-mxstep="{dup}:4"]')                           # the copy is its own: changing it leaves the original
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].steps") == [0, 10, 30]
    _more(page, dup)
    page.click(f'[data-mxdel="{dup}"]')
    _more(page, dup)
    page.click(f'[data-mxrm="{dup}"]')
    page.wait_for_function(f"!CRATE.MX.order.includes('{dup}')", timeout=10000)
    page.click("#mxplay")                                            # it plays on the bar clock, through its own chain
    page.wait_for_function(f"CRATE.MX.on&&CRATE.MX.slots['{sid}']._c&&CRATE.MX.slots['{sid}']._next>0", timeout=20000)
    page.click(f'[data-mxstep="{sid}:10"]')
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].steps") == [0, 30]
    page.click("#mxplay")
    # 🎲 on a one-shot slot asks the server for one (no sample named): it answers, even when the library has none to offer
    r = json.load(urllib.request.urlopen(urllib.request.Request(site["base"] + "api/stems/oneshot", data=json.dumps(
        {"state": {"bpm": 100, "key": None, "slots": {}}, "n": 1, "path": None}).encode(), method="POST")))
    assert "part" in r and "error" not in r
    page.reload()                                                    # it comes back with its placement
    page.wait_for_function(f"window.CRATE&&CRATE.MX&&CRATE.MX.slots['{sid}']&&CRATE.MX.slots['{sid}'].n===2", timeout=30000)
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].steps") == [0, 30]
    page.evaluate("localStorage.removeItem('dcStems')")
    page.click("#tabS")


def test_saving_under_a_new_name_asks_about_another_ones_snapshots(site, page):
    """A strip that came with one saved combination doesn't silently become part of another."""
    _mixer(site, page)
    page.click("#sncap")
    page.wait_for_selector("#snrep")
    page.fill("#mxname", "first one")
    page.evaluate("""() => {
        const api = CRATE.api;
        CRATE.api = (path, body) => path === 'api/stems/save'
            ? new Promise(resolve => { window.releaseSave = () => { CRATE.api = api; resolve(api(path, body)); }; })
            : api(path, body);
    }""")
    page.click("#mxsave")
    assert page.locator("#mxsave").is_disabled() and "saving" in page.inner_text("#mxsave")
    page.evaluate("CRATE.mxSync()")
    assert page.locator("#mxsave").is_disabled() and "saving" in page.inner_text("#mxsave")
    page.evaluate("releaseSave()")
    page.wait_for_function("!document.querySelector('#mxsave').disabled && !document.querySelector('#mxsave').classList.contains('dirty')", timeout=10000)
    page.fill("#mxname", "second one")
    page.click("#mxsave")
    page.wait_for_selector(".mxask")                                 # asked, not saved yet
    page.click("#mxdropsn")
    page.wait_for_function("CRATE.MX.name==='second one'&&CRATE.MX.snaps.length===0", timeout=10000)
    page.wait_for_function("!document.querySelector('#mxsave').classList.contains('dirty')", timeout=10000)   # saved
    saved = json.load(urllib.request.urlopen(urllib.request.Request(site["base"] + "api/stems/saved", data=b"{}", method="POST")))["mixes"]
    by = {m["name"]: m["state"] for m in saved}
    assert len(by["first one"]["snaps"]) == 1 and len(by["second one"].get("snaps") or []) == 0
    page.evaluate("CRATE.mxPlay(false)")
    page.evaluate("localStorage.removeItem('dcStems')")
    page.click("#tabS")


TRACKS_MATHS = [
    ("TR.resizeEnd({bar0:104,n:8,k:1},114,177)", {"bar0": 104, "n": 10}),
    ("TR.resizeEnd({bar0:104,n:8,k:1},100,177)", {"bar0": 104, "n": 1}),
    ("TR.resizeEnd({bar0:104,n:8,k:1},130,177)", {"bar0": 104, "n": 16}),
    ("TR.resizeEnd({bar0:170,n:4,k:1},190,177)", {"bar0": 170, "n": 7}),      # stops at the song's last bar line
    ("TR.resizeEnd({bar0:10,n:4,k:2},21,100)", {"bar0": 10, "n": 6}),         # half-time: every second line
    ("TR.resizeEnd({bar0:10,n:4,k:0.5},13,100)", {"bar0": 10, "n": 6}),       # double-time: two mixer bars a line
    ("TR.resizeEnd({bar0:10,n:4,k:0.5},30,100)", {"bar0": 10, "n": 16}),
    ("TR.resizeStart({bar0:104,n:8,k:1},108,177)", {"bar0": 108, "n": 4}),
    ("TR.resizeStart({bar0:104,n:8,k:1},120,177)", {"bar0": 111, "n": 1}),
    ("TR.resizeStart({bar0:4,n:8,k:1},-3,177)", {"bar0": 0, "n": 12}),
    ("TR.moveTo({bar0:104,n:8,k:1},175,177)", {"bar0": 169, "n": 8}),
    ("TR.moveTo({bar0:104,n:8,k:1},-5,177)", {"bar0": 0, "n": 8}),
    ("TR.nudge({bar0:104,n:8,k:1},1,177)", {"bar0": 105, "n": 8}),
    ("TR.grow({bar0:104,n:8,k:1},-1,177)", {"bar0": 104, "n": 7}),
    ("TR.grow({bar0:104,n:1,k:1},-1,177)", {"bar0": 104, "n": 1}),
    ("[3.9,-1,99].map(t=>TR.floorBar([0,2,4,6,8],t))", [1, 0, 3]),
    ("[2.9,3.1,99,-1].map(t=>TR.nearLine([0,2,4,6,8],t))", [1, 2, 4, 0]),
    ("[[100,160,158],[100,160,104],[100,160,130],[100,160,50],[100,106,104],[100,106,101]].map(a=>TR.hit(...a))",
     ["end", "start", "move", "out", "end", "start"]),
    ("TR.zoom(0,300,0.5,0.5,300,4)", [75, 225]), ("TR.zoom(0,300,0.5,4,300,4)", [0, 300]), ("TR.zoom(100,104,0,0.1,300,4)", [100, 104]),
    ("TR.pan(100,200,150,300)", [200, 300]), ("TR.pan(100,200,-500,300)", [0, 100]),
    ("TR.loopView(100,116,2,300)", [84, 132]), ("TR.loopView(2,6,2,300)", [0, 10]),
    ("[{bar0:104,n:8,k:1},{bar0:43,n:1,k:1},{bar0:10,n:4,k:2}].map(TR.barsText)",
     ["bars 105–112 · 8 bars", "bar 44 · 1 bar", "bars 11–18 · 4 bars"]),
    ("[TR.semis(4,{ct:25}),TR.semis(0,{}),TR.srcBars(4,2),TR.srcBars(1,0.5),TR.MAXN]", [4.25, 0, 8, 1, 16]),
]

def test_tracks_maths(page):
    for js, want in TRACKS_MATHS:
        assert page.evaluate(f"(()=>{{const TR=CRATE.TR;return {js}}})()") == want, js


def _calls(page, *, block_prefetch=False):
    """Record every api call the page makes from now on, as [path, body]."""
    page.evaluate("""blockPrefetch => {
        if (window.__calls) return;
        window.__calls = [];
        // An in-flight recommendation must not add a background render to a drag test.
        if (blockPrefetch) CRATE.MX.pre = {};
        const api = CRATE.api;
        CRATE.api = (path, body) => {
            if (blockPrefetch && path === 'api/stems/pick' && !Object.hasOwn(body, 'track')) {
                return Promise.resolve({part: null});
            }
            __calls.push([path, body]);
            return api(path, body);
        };
    }""", block_prefetch)

def test_pitch_is_two_numbers_you_drag(site, page):
    _mixer(site, page)
    for slot in ("drums", "bass", "vocals", "other"):
        assert page.locator(f'[data-v="{slot}:st"]').count() == 1 and page.locator(f'[data-v="{slot}:ct"]').count() == 1
    _calls(page, block_prefetch=True)
    box = page.locator('[data-v="bass:ct"]').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x, y - 20); page.mouse.move(x, y - 75)   # 3 px a cent
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/render').length") == 0     # nothing is asked while dragging
    page.mouse.up()
    page.wait_for_function("""() => {
        const p = CRATE.MX.slots.bass, key = CRATE.MX.info?.slots.bass?.semis;
        const bassRender = __calls.filter(([path, body]) => path === 'api/stems/render' && body.stem === 'bass').at(-1);
        return p.ct === 25 && p.buf && !p._loading && bassRender?.[1].semis === key + 0.25;
    }""")
    page.evaluate("CRATE.TR.set('drums','st',2)")
    page.wait_for_function("__calls.some(c=>c[0]==='api/stems/render'&&c[1].stem==='drums'&&c[1].semis===2)")
    page.focus('[data-v="bass:st"]'); page.keyboard.press("ArrowUp")
    page.wait_for_function("CRATE.MX.slots.bass.off===1")
    page.dblclick('[data-v="bass:ct"]')
    page.wait_for_function("(CRATE.MX.slots.bass.ct||0)===0")
    assert "+1 st" in page.inner_text('[data-v="bass:st"]')
    page.evaluate("CRATE.TR.set('vocals','ct',-30)")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.vocals.ct") == -30
    # the strip: the same part at other cents is a change, not the same audio
    assert page.evaluate("(()=>{const a=CRATE.MX.slots.vocals;return BLEND.sameAudio(a,{...a,ct:0})})()") is False


def _box(page, sel):
    return page.evaluate("s=>{const r=document.querySelector(s).getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}}", sel)

def _one_shot(page):
    """Put a short library one-shot in a new slot, as ✦ Mashup in the sample panel does. -> its slot id"""
    i = page.evaluate("S.findIndex(s=>s[F.kind]==='oneshot'&&s[F.dur]<2)")
    assert i >= 0
    page.evaluate(f"CRATE.mxAddOneShot({i})")
    page.wait_for_function("CRATE.MX.order.some(id=>CRATE.MX.roles[id]==='oneshot'&&CRATE.MX.slots[id]&&CRATE.MX.slots[id].buf)", timeout=120000)
    page.click("#tabM")
    return page.evaluate("CRATE.MX.order.find(id=>CRATE.MX.roles[id]==='oneshot')")

def test_effects_are_numbers_under_every_track(site, page):
    _mixer(site, page)
    devs = lambda s: page.evaluate(f"[...document.querySelectorAll('[data-mxrow=\"{s}\"] .trfx .trdev')].map(d=>d.dataset.dev)")
    for s in ("drums", "vocals"):
        assert devs(s) == ["eq", "dly", "rev", "harm"], s
    assert devs("bass") == ["eq", "dly", "rev", "harm", "even", "duck"]
    assert devs("other") == ["eq", "dly", "rev", "harm", "duck"]
    page.evaluate("CRATE.TR.set('bass','fb',60)")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.bass.fb") == 0.6
    page.evaluate("CRATE.TR.set('bass','dly',50)")
    page.wait_for_function("Math.abs(CRATE.MX.slots.bass._c.fb.gain.value-0.6)<0.02")
    assert page.evaluate("CRATE.MX.slots.drums._c.fb.gain.value") == pytest.approx(0.35, abs=0.01)   # untouched: as it was fixed
    box = page.locator('[data-v="vocals:g0"]').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x, y - 30); page.mouse.move(x + 25, y - 30)   # up, then right: both mean more
    page.wait_for_function("CRATE.MX.slots.vocals._c.lo.gain.value>2")                 # heard while dragging
    page.mouse.up()
    assert page.evaluate("CRATE.MX.slots.vocals.eq[0]") == 6                            # 55 px of 220 for 24 dB
    # a line under the number shows where it sits (from the middle for a ± value)
    assert page.evaluate("(()=>{const e=document.querySelector('[data-v=\"vocals:g0\"]');return [e.style.getPropertyValue('--a'),e.style.getPropertyValue('--w')]})()") == ["50.0%", "25.0%"]
    # ⇧ makes a drag five times finer
    box = page.locator('[data-v="other:rev"]').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.keyboard.down("Shift"); page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 20, y); page.mouse.move(x + 60, y); page.mouse.up(); page.keyboard.up("Shift")
    assert page.evaluate("Math.round(CRATE.MX.slots.other.rev*100)") == 4              # 60 px of 1500 for 100 %
    # a click lets you type the value; Enter sets it (inside its range), Esc leaves it
    page.click('[data-v="other:rev"]')
    page.wait_for_selector('[data-v="other:rev"] input.trtype')
    page.keyboard.type("37"); page.keyboard.press("Enter")
    page.wait_for_function("Math.round(CRATE.MX.slots.other.rev*100)===37")
    page.click('[data-v="other:rev"]')
    page.wait_for_selector('[data-v="other:rev"] input.trtype')
    page.keyboard.type("90"); page.keyboard.press("Escape")
    assert page.evaluate("Math.round(CRATE.MX.slots.other.rev*100)") == 37 and page.locator("input.trtype").count() == 0
    page.dblclick('[data-v="other:rev"]')                                              # a double-click still resets
    page.wait_for_function("(CRATE.MX.slots.other.rev||0)===0")
    page.wait_for_timeout(400)
    assert page.locator("input.trtype").count() == 0
    page.click('[data-mxrow="vocals"] [data-mxeqon]')
    page.wait_for_function("Math.abs(CRATE.MX.slots.vocals._c.lo.gain.value)<0.1")
    assert page.evaluate("CRATE.MX.slots.vocals.eq[0]") == 6 and page.locator('[data-mxrow="vocals"] .trdev[data-dev="eq"].mxoff').count() == 1
    assert page.evaluate("CRATE.MX.slots.bass.dly") == pytest.approx(0.4)
    assert page.locator('[data-mxrow] input[data-mxeq], [data-mxrow] input[data-mxdly], [data-mxrow] select[data-mxdt], [data-mxrow] input[data-mxrev], [data-mxrow] input[data-mxduck]').count() == 0
    page.set_viewport_size({"width": 1280, "height": 800})
    for s in ("drums", "bass", "vocals", "other"):                  # every row's effects are inside it, without clicking them
        r = _box(page, f'[data-mxrow="{s}"]')
        assert page.evaluate(f"[...document.querySelectorAll('[data-mxrow=\"{s}\"] .trfx .trdev')].every(d=>d.getBoundingClientRect().right<={r['r']}+1)")
    os = _one_shot(page)
    assert devs(os) == ["eq", "dly", "rev", "harm", "trim"] and page.locator(f'[data-mxrow="{os}"] .trfx canvas[data-mxtrim="{os}"]').count() == 1


EMOJI = "[\\u{1F300}-\\u{1FAFF}\\u{2600}-\\u{27BF}]"

def _more(page, slot):
    """Open a track's ⋯ menu (the moved controls are in it)."""
    if not page.locator(f'[data-mxrow="{slot}"].open').count():
        page.click(f'[data-trmore="{slot}"]')

def test_track_header_holds_every_control(site, page):
    _mixer(site, page)
    page.set_viewport_size({"width": 1280, "height": 800})
    for slot, word in (("drums", "Drums"), ("bass", "Bass"), ("vocals", "Vocals"), ("other", "Other")):
        row = f'[data-mxrow="{slot}"]'
        assert page.inner_text(f"{row} .trname").strip() == word
        h = _box(page, f"{row} .trh")
        for sel in (".trname", ".mxsrc", ".trbars", f'[data-v="{slot}:st"]', f'[data-v="{slot}:ct"]', "[data-mxroll]", f'[data-mxhist="{slot}:-1"]', f'[data-mxhist="{slot}:1"]', "[data-mxsolo]",
                    "[data-mxmute]", "input[data-mxdb]", "[data-trmore]"):
            b = _box(page, f"{row} .trh {sel}")
            assert b["l"] >= h["l"] - 1 and b["r"] <= h["r"] + 1 and b["r"] <= 1280 and b["r"] > b["l"], (slot, sel, b)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert page.evaluate(f"[...document.querySelectorAll('.trk')].every(e=>!/{EMOJI}/u.test(e.textContent))")
    assert page.locator('[data-mxrow="bass"] .trmenu').is_hidden()
    _more(page, "bass")
    menu = page.locator('[data-mxrow="bass"] .trmenu')
    assert menu.locator('[data-mxfind], [data-mxalt], [data-mxlock], [data-mxdup], '
                        '[data-mxdel], [data-mxrole], [data-mxrm]').count() == 7
    page.keyboard.press("Escape")
    assert page.locator('[data-mxrow="bass"].open').count() == 0
    _more(page, "bass"); page.click('[data-mxrow="bass"] [data-mxdup]')
    page.wait_for_function("CRATE.MX.order.length===6")
    # a one-shot: the same header, its own part under it
    os = _one_shot(page)
    assert page.inner_text(f'[data-mxrow="{os}"] .trname').strip() == "One-shot"
    assert page.locator(f'[data-mxrow="{os}"] [data-mxstep]').count() == 16 and page.locator(f'[data-mxrow="{os}"] [data-mxaud]').count() == 1


PIXEL = """([slot,x,y])=>{const c=document.querySelector(`[data-mxwave="${slot}"] canvas`),k=c.width/c.clientWidth,
  d=c.getContext('2d').getImageData(Math.round(x*k),Math.round(y*k),1,1).data;return [d[0],d[1],d[2]]}"""

def test_track_shows_the_whole_song(site, page):
    _mixer(site, page)
    page.click('#trview [data-trview="song"]')
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.TR.has(s))", timeout=20000)
    g = page.evaluate("""(()=>{const p=CRATE.MX.slots.other,s=CRATE.TR.song(p.track,'other'),c=document.querySelector('[data-mxwave="other"] canvas');
      return {w:c.clientWidth,h:c.clientHeight,dur:s.dur,a:s.bars[p.bar0],b:s.bars[p.bar0+CRATE.TR.srcBars(p.n,p.k||1)],n:s.pk.length,rate:s.rate}})()""")
    assert g["rate"] == 400 and abs(g["n"] - g["dur"] * 400) <= 1 and g["b"] > g["a"]
    xa, xb = g["a"] / g["dur"] * g["w"], g["b"] / g["dur"] * g["w"]
    col = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--KEYS').trim()")
    rgb = [int(col[i:i + 2], 16) for i in (1, 3, 5)]                                    # ("other" sounds all the way through the test song)
    assert page.evaluate(PIXEL, ["other", (xa + xb) / 2, 1]) == rgb                     # the bar joining the loop's edges
    outside = xb + 20 if xb + 20 < g["w"] else xa - 20
    assert page.evaluate(PIXEL, ["other", outside, 1]) != rgb
    assert page.evaluate(PIXEL, ["other", (xa + xb) / 2, g["h"] / 2]) == rgb            # lit inside the loop
    assert page.evaluate(PIXEL, ["other", outside, g["h"] / 2]) == [0x39, 0x40, 0x4b]   # gray outside it
    page.wait_for_function("([lo,hi])=>{const l=parseFloat(document.querySelector('[data-mxwave=\"other\"] i').style.left)/100;return l>=lo&&l<=hi}",
                           arg=[xa / g["w"] - 0.01, xb / g["w"] + 0.01], timeout=10000)   # the play line is inside the loop (a frame after the view changed)
    assert page.inner_text('[data-mxrow="other"] .trbars') == page.evaluate("CRATE.TR.barsText(CRATE.MX.slots.other)")

def test_track_plays_without_its_picture(site, page):
    """The picture can't be had: the track still shows its loop and plays."""
    r = subprocess.run([sys.executable, "-c", STEM_SONGS], env=site["env"], capture_output=True, text=True)
    assert "STEMS OK" in r.stdout
    page.evaluate("""() => {
        const api = CRATE.api;
        window.pictureUnavailable = true;
        CRATE.api = (path, body) => path === 'api/stems/peaks' && pictureUnavailable
            ? Promise.reject(new Error('no picture')) : api(path, body);
    }""")
    page.click("#tabM"); page.wait_for_selector("#mxall"); page.click("#mxall")
    page.wait_for_function("CRATE.MX.on&&['drums','bass','vocals','other'].every(s=>CRATE.MX.slots[s]&&CRATE.MX.slots[s].buf)", timeout=90000)
    assert page.evaluate("CRATE.TR.has('drums')") is False
    page.wait_for_function("(()=>{const b=document.querySelector('[data-mxwave=\"drums\"]');return b.querySelector('canvas').width>50&&getComputedStyle(b.querySelector('i')).display==='block'})()")
    wave = page.locator('[data-mxwave="drums"]')
    wave.hover()
    assert wave.locator(".trzoom").is_hidden()
    page.evaluate("() => { window.pictureUnavailable = false; return CRATE.mxSync(); }")
    page.wait_for_function("CRATE.TR.has('drums')", timeout=5000)
    wave.hover()
    assert wave.locator(".trzoom").is_visible()


def _edge(page, slot):
    """Where a stem track's loop is on the page: its two edges and the row's middle height, and px per bar."""
    return page.evaluate("""slot=>{const p=CRATE.MX.slots[slot],s=CRATE.TR.song(p.track,CRATE.MX.roles[slot]),r=document.querySelector(`[data-mxwave="${slot}"]`).getBoundingClientRect(),
      [v0,v1]=p._v,X=t=>r.left+(t-v0)/(v1-v0)*r.width,e=p.bar0+CRATE.TR.srcBars(p.n,p.k||1);
      return {xa:X(s.bars[p.bar0]),xb:X(s.bars[e]),y:r.top+r.height/2,bar:X(s.bars[1])-X(s.bars[0]),left:r.left,bar0:p.bar0,n:p.n,nb:s.bars.length-1}}""", slot)

def _drag(page, x0, x1, y):
    page.mouse.move(x0, y); page.mouse.down()
    for k in range(1, 6):
        page.mouse.move(x0 + (x1 - x0) * k / 5, y)
    page.mouse.up()

def test_loop_drags_and_snaps(site, page):
    _mixer(site, page)
    page.click('#trview [data-trview="song"]')
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.TR.has(s))", timeout=20000)
    page.evaluate("CRATE.TR.setLoop('drums',4,4)")
    page.wait_for_function("CRATE.MX.slots.drums.bar0===4&&CRATE.MX.slots.drums.n===4&&CRATE.MX.slots.drums.buf&&!CRATE.MX.slots.drums._loading")
    _calls(page, block_prefetch=True)
    e = _edge(page, "drums")
    page.mouse.move(e["xb"], e["y"]); page.mouse.down(); page.mouse.move(e["xb"] + e["bar"], e["y"]); page.mouse.move(e["xb"] + 2.2 * e["bar"], e["y"])
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/render').length") == 0 and "6 bars" in page.inner_text('[data-mxwave="drums"] .trtip')
    page.mouse.up()
    page.wait_for_function("CRATE.MX.slots.drums.n===6&&CRATE.MX.slots.drums.bar0===4&&!CRATE.MX.slots.drums._loading")
    assert abs(page.evaluate("CRATE.MX.slots.drums.buf.duration") - 6 * 2.4) < 0.01          # six bars at 100 bpm
    e = _edge(page, "drums"); _drag(page, e["xa"], e["xa"] + 2 * e["bar"], e["y"])              # the start: the end stays
    page.wait_for_function("CRATE.MX.slots.drums.bar0===6&&CRATE.MX.slots.drums.n===4")
    e = _edge(page, "drums"); _drag(page, e["xa"] + 1.5 * e["bar"], e["xa"] - 1.5 * e["bar"], e["y"])   # the whole loop, three bars back
    page.wait_for_function("CRATE.MX.slots.drums.bar0===3&&CRATE.MX.slots.drums.n===4")
    e = _edge(page, "drums"); _drag(page, e["xb"], e["xb"] + 40 * e["bar"], e["y"])             # past the song's end: it stops there
    page.wait_for_function("CRATE.MX.slots.drums.bar0===3&&CRATE.MX.slots.drums.n===13")
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/render').every(c=>c[1].bar0+c[1].n<=16)")
    e = _edge(page, "drums"); page.mouse.click(e["left"] + 0.4 * e["bar"], e["y"])              # the gray: the loop goes there
    page.wait_for_function("CRATE.MX.slots.drums.bar0===0&&CRATE.MX.slots.drums.n===13")
    page.evaluate("CRATE.TR.setLoop('bass',2,2)"); page.wait_for_function("CRATE.MX.slots.bass.bar0===2&&!CRATE.MX.slots.bass._loading")
    page.focus('[data-mxwave="bass"]'); page.keyboard.press("ArrowRight"); page.keyboard.press("Shift+ArrowRight")
    page.wait_for_function("CRATE.MX.slots.bass.bar0===3&&CRATE.MX.slots.bass.n===3")
    assert page.locator("[data-mxpos]").count() == 0 and page.locator('select[data-mxlen="drums"]').count() == 0
    # Keep the first render's reply until the next edit is already playing.
    page.evaluate("""() => {
      const api = CRATE.api;
      CRATE.api = (path, b) => {
        const reply = api(path, b);
        if (path === 'api/stems/render' && b.stem === 'other' && b.bar0 === 1 && b.n === 2) {
          return reply.then(r => new Promise(resolve => { window.releaseOldLoop = () => resolve(r); }));
        }
        return reply;
      };
      window.oldLoop = CRATE.TR.setLoop('other', 1, 2);
    }""")
    page.wait_for_function("typeof releaseOldLoop==='function'")
    page.wait_for_selector('[data-mxwave="other"].busy')
    page.evaluate("CRATE.TR.setLoop('other',5,4)")
    page.wait_for_function("CRATE.MX.slots.other.bar0===5&&CRATE.MX.slots.other.n===4&&!CRATE.MX.slots.other._loading")
    page.evaluate("() => { releaseOldLoop(); return oldLoop; }")
    assert page.locator('[data-mxwave="other"].busy').count() == 0
    assert abs(page.evaluate("CRATE.MX.slots.other.buf.duration") - 4 * 2.4) < 0.01


def test_a_half_time_loop_snaps_to_every_second_bar(site, page):
    _mixer(site, page, bpm=50)                                    # the songs are at 92 to 110: two of their bars to one
    page.wait_for_function("CRATE.TR.has('drums')&&CRATE.MX.slots.drums.k===2", timeout=20000)
    page.evaluate("CRATE.TR.setLoop('drums',2,2)"); page.wait_for_function("CRATE.MX.slots.drums.bar0===2&&!CRATE.MX.slots.drums._loading")
    e = _edge(page, "drums"); _drag(page, e["xb"], e["xb"] + 0.8 * e["bar"], e["y"])
    page.wait_for_timeout(300); assert page.evaluate("CRATE.MX.slots.drums.n") == 2          # one of the song's bars: not a step
    e = _edge(page, "drums"); _drag(page, e["xb"], e["xb"] + 2 * e["bar"], e["y"])
    page.wait_for_function("CRATE.MX.slots.drums.n===3")


def test_tracks_fit_the_window(site, page):
    _kits(site)
    _mixer(site, page)
    page.wait_for_function("CRATE.MX.order.length===5&&CRATE.MX.order.every(id=>CRATE.MX.slots[id]&&CRATE.MX.slots[id].buf)", timeout=60000)
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===1")
    for w, h in ((1512, 857), (1280, 800)):
        page.set_viewport_size({"width": w, "height": h}); page.wait_for_timeout(200)
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('.mx,.mx *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"), w
        assert page.evaluate("[...document.querySelectorAll('.trwave')].map(e=>Math.round(e.getBoundingClientRect().height))") == [58] * 5, w
        tk = page.evaluate("[...document.querySelectorAll('.trk')].map(e=>Math.round(e.getBoundingClientRect().height))")
        assert all(x <= 122 for x in tk), (w, tk)                     # no taller than a slot is on main
    page.set_viewport_size({"width": 1512, "height": 857}); page.wait_for_timeout(200)
    last = f'[data-mxrow="{page.evaluate("CRATE.MX.order[4]")}"] .trfx'
    for sel in (".mxtop", "#snbar", last):                         # the top bar, the strip and all five tracks, without scrolling
        b = _box(page, sel); assert b["t"] >= 0 and b["b"] <= 858, (sel, b)

def test_zoom_and_the_view_switch(site, page):
    _mixer(site, page)
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.TR.has(s))", timeout=20000)
    bar = page.evaluate("(()=>{const p=CRATE.MX.slots.drums,g=CRATE.TR.song(p.track,'drums');return g.bars[1]-g.bars[0]})()")
    r = page.evaluate("(()=>{const b=document.querySelector('[data-mxwave=\"drums\"]').getBoundingClientRect();return [b.left,b.top,b.width,b.height]})()")
    x, y = r[0] + r[2] * 0.25, r[1] + r[3] / 2
    t0 = page.evaluate("(()=>{const v=CRATE.MX.slots.drums._v;return v[0]+0.25*(v[1]-v[0])})()")
    page.evaluate("([x,y])=>document.querySelector('[data-mxwave=\"drums\"] canvas').dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:-120,clientX:x,clientY:y}))", [x, y])
    v = page.evaluate("CRATE.MX.slots.drums._v")
    assert v[1] - v[0] < 16 * bar * 0.5 and abs(v[0] + 0.25 * (v[1] - v[0]) - t0) < 0.2          # tighter, and the same moment under the pointer
    for _ in range(20):
        page.evaluate("([x,y])=>document.querySelector('[data-mxwave=\"drums\"] canvas').dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:-300,clientX:x,clientY:y}))", [x, y])
    v = page.evaluate("CRATE.MX.slots.drums._v"); assert abs((v[1] - v[0]) - 2 * bar) < 0.01    # never tighter than two bars
    page.click('[data-trview="loop"]'); page.wait_for_timeout(400)
    assert page.evaluate("""['drums','bass','vocals','other'].every(s=>{const p=CRATE.MX.slots[s],g=CRATE.TR.song(p.track,s),e=p.bar0+CRATE.TR.srcBars(p.n,p.k||1),
      w=CRATE.TR.loopView(g.bars[p.bar0],g.bars[e],g.bars[1]-g.bars[0],g.dur);return Math.abs(p._v[0]-w[0])<0.01&&Math.abs(p._v[1]-w[1])<0.01})""")
    page.click('[data-trview="song"]'); page.wait_for_timeout(400)
    assert page.evaluate("CRATE.MX.slots.bass._v[0]===0&&Math.abs(CRATE.MX.slots.bass._v[1]-CRATE.TR.song(CRATE.MX.slots.bass.track,'bass').dur)<0.01")
    wave = page.locator('[data-mxwave="drums"]')
    wave.hover()
    assert wave.locator(".trzoom").is_visible()
    wave.locator('[data-trz="loop"]').click()
    assert page.evaluate("CRATE.MX.slots.drums._viewMode") == "loop"
    wave.locator('[data-trz="song"]').click()
    assert page.evaluate("CRATE.MX.slots.drums._viewMode") == "song"
    page.click("#tabS"); page.click("#tabM"); page.wait_for_selector(".trfx")                 # away and back: still there, nothing stuck
    assert page.locator(".trfx").count() == 4   # the four tracks with parts


HARM = r"""async () => {
  const BL = window.BLEND, SR = 44100, N = 2 * SR, out = {};
  const sub = c => { const b = c.createBuffer(1, N, SR), d = b.getChannelData(0); for (let i = 0; i < N; i++) d[i] = 0.3 * Math.sin(2 * Math.PI * 55 * i / SR); return b; };
  const rms = d => { let s = 0; for (let i = SR / 2; i < N; i++) s += d[i] * d[i]; return Math.sqrt(s / (N - SR / 2)); };
  const probe = new OfflineAudioContext(1, N, SR), hc = await BL.harmMeasure(sub(probe));
  const run = async (p, withComp) => { const c = new OfflineAudioContext(1, N, SR), ch = BL.mkChain(c, c.destination, BL.duckBus(c)), s = c.createBufferSource();
    const m = BL.mixOf(p, 'bass', { on: true, fx: true, bar: 2.4, DT: { '1/8': 1 / 8 }, hc: withComp ? hc : null, duck: { on: false } });
    BL.applyChain(ch, m, 0); s.buffer = sub(c); s.connect(ch.in); s.start(0); return rms((await c.startRendering()).getChannelData(0)); };
  const base = await run({ db: 0, harm: 0 }, true);
  out.level = [];
  for (const a of [0.25, 0.5, 1]) out.level.push(20 * Math.log10((await run({ db: 0, harm: a }, true)) / base));
  out.raw = 20 * Math.log10((await run({ db: 0, harm: 1 }, false)) / base);        // the switch as it was: louder
  out.old = 20 * Math.log10((await run({ db: 0, harm: true, hup: true }, true)) / (await run({ db: 0, harm: 1 }, false)));
  out.amt = [BL.harmAmt({ harm: true }), BL.harmAmt({ harm: false }), BL.harmAmt({ harm: null }), BL.harmAmt({ harm: 0.4 })];
  return out; }"""

def test_harmonics_amount_keeps_the_level(page):
    r = page.evaluate(HARM)
    assert all(abs(x) < 0.3 for x in r["level"]), r          # the level stays where it was at 0 (the spec allows a decibel)
    assert r["raw"] > 0.8 and abs(r["old"]) < 0.05, r        # the old switch was louder; a part from before plays as it did
    assert r["amt"] == [1, 0, 0, 0.4]


OCTAVE_AUDIO = """async () => {
  const BL = BLEND, SR = 44100, N = 4 * SR, out = {};
  const tone = (ctx, f, amp) => { const b = ctx.createBuffer(1, N, SR), d = b.getChannelData(0);
    for (let i = 0; i < N; i++) d[i] = amp * Math.sin(2 * Math.PI * f * i / SR); return b; };
  // Measure the level of one frequency over the last two seconds.
  const at = (d, f) => { let re = 0, im = 0; for (let i = 2 * SR; i < N; i++) { const w = 2 * Math.PI * f * i / SR; re += d[i] * Math.cos(w); im += d[i] * Math.sin(w); }
    return 20 * Math.log10(2 * Math.hypot(re, im) / (2 * SR) + 1e-12); };
  const rms = d => { let s = 0; for (let i = 2 * SR; i < N; i++) s += d[i] * d[i]; return 10 * Math.log10(s / (2 * SR) + 1e-24); };
  const O = { on: true, fx: true, bar: 2, DT: { '1/8': 1 / 8 } };
  const run = async (f, amp, part, fx = true) => {
    const c = new OfflineAudioContext(1, N, SR), ch = BL.mkChain(c, c.destination, BL.duckBus(c)), s = c.createBufferSource();
    s.buffer = tone(c, f, amp);
    const hc = fx ? await BL.harmMeasure(s.buffer, part.hk === 'oct' ? 'oct' : 'drive') : null;
    s.connect(ch.in); s.start(0);
    BL.applyChain(ch, BL.mixOf({ db: 0, ...part }, 'bass', { ...O, fx, hc }), 0); return (await c.startRendering()).getChannelData(0); };
  const A = 0.113; // Rendered parts have RMS 0.08.
  const dry = await run(50, A, { harm: 0 }), oct = await run(50, A, { harm: 1, hk: 'oct' }), drv = await run(50, A, { harm: 1 });
  const rel = (y, f) => at(y, f) - at(y, 50);
  out.oct = { h2: rel(oct, 100), h3: rel(oct, 150), h4: rel(oct, 200), level: rms(oct) - rms(dry) };
  out.drive = { h2: rel(drv, 100), h3: rel(drv, 150), level: rms(drv) - rms(dry) };
  const quiet = await run(50, A / 2, { harm: 1, hk: 'oct' });
  out.tracks = rel(quiet, 100) - out.oct.h2;
  const half = await run(50, A, { harm: 0.5, hk: 'oct' }); out.half = rel(half, 100) - out.oct.h2;
  const mid = await run(220, A, { harm: 1, hk: 'oct' }), mid0 = await run(220, A, { harm: 0 });
  out.notSub = { added: at(mid, 440) - at(mid, 220), level: rms(mid) - rms(mid0) };
  out.fxOff = rel(await run(50, A, { harm: 1, hk: 'oct' }, false), 100);
  return out;
}"""


def test_octave_harmonics_audio(page):
    """The octave follows the bass level, and both generators keep the track's loudness."""
    o = page.evaluate(OCTAVE_AUDIO)
    assert -8 < o["oct"]["h2"] < -4, o
    assert o["oct"]["h3"] < o["oct"]["h2"] - 30 and o["oct"]["h4"] < o["oct"]["h2"] - 12, o
    assert abs(o["oct"]["level"]) < 1.0 and abs(o["drive"]["level"]) < 1.0, o
    assert abs(o["tracks"]) < 0.5, o
    assert -7.0 < o["half"] < -5.0, o
    assert o["drive"]["h3"] > -12 and o["drive"]["h2"] < -40, o
    assert o["notSub"]["added"] < -30 and abs(o["notSub"]["level"]) < 0.3, o
    assert o["fxOff"] < -50, o


@pytest.mark.parametrize("bass_harm", [True, None])
def test_state_saved_before_tracks_still_opens(site, page, bass_harm):
    _mixer(site, page)
    page.select_option("#mxkey", "C")
    _roll(page, "bass", 901)
    assert page.evaluate("CRATE.MX.slots.bass.sub") >= 0.85
    page.evaluate("""bassHarm=>{CRATE.mxPlay(false);const s=JSON.parse(localStorage.getItem('dcStems'));delete s.v;
      for(const id of Object.keys(s.slots)){const p=s.slots[id];delete p.ct;delete p.fb;delete p.hk;p.harm=id==='bass'?bassHarm:id==='drums'?false:null;p.db=-2}
      s.snaps=[{order:s.order,roles:s.roles,slots:JSON.parse(JSON.stringify(s.slots)),duck:{}}];localStorage.setItem('dcStems',JSON.stringify(s))}""", bass_harm)
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX&&CRATE.MX.slots.bass", timeout=30000)
    if bass_harm:
        assert page.evaluate("CRATE.MX.snaps[0].slots.bass.hup===true&&!CRATE.MX.slots.drums.hup")
    else:
        assert page.evaluate("CRATE.MX.snaps[0].slots.bass.harm") is None
    page.click("#mxplay")
    page.wait_for_function("CRATE.MX.slots.bass._hc&&!CRATE.MX.slots.bass.hup", timeout=60000)
    want = page.evaluate("-2-20*Math.log10(BLEND.harmComp({harm:1},CRATE.MX.slots.bass._hc))")
    assert page.evaluate("CRATE.MX.slots.bass.db") == pytest.approx(min(6, want), abs=0.0001)
    assert page.evaluate("CRATE.MX.slots.bass.harm") == 1 and page.evaluate("CRATE.MX.slots.drums.db") == -2
    c = page.evaluate("(()=>{const c=CRATE.MX.slots.vocals._c;return [c.lo.frequency.value,c.mid.frequency.value,c.hi.frequency.value,+c.fb.gain.value.toFixed(2)]})()")
    assert c == [200, 1000, 5000, 0.35] and page.evaluate("(CRATE.MX.slots.vocals.ct||0)") == 0
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).v") == 5
    page.evaluate("CRATE.TR.set('bass','harm',50)")
    page.wait_for_function("Math.abs(CRATE.MX.slots.bass._c.hg.gain.value-0.175)<0.01")
    assert page.locator("[data-mxharm]").count() == 0 and page.locator('[data-mxrow="bass"] .trfx [data-v="bass:harm"]').count() == 1


def test_duplicating_a_track_while_its_loop_renders(site, page):
    _mixer(site, page)
    page.wait_for_function("CRATE.TR.has('other')")
    page.evaluate("""() => {
      const api = CRATE.api;
      let release;
      const held = new Promise(resolve => { release = resolve; });
      window.releaseDuplicateRender = release;
      CRATE.api = (path, part) => {
        const reply = api(path, part);
        return path === 'api/stems/render' && part.stem === 'other' && part.bar0 === 1 && part.n === 2
          ? reply.then(async r => { await held; return r; })
          : reply;
      };
      window.pendingDuplicateRender = CRATE.TR.setLoop('other', 1, 2);
    }""")
    page.wait_for_selector('[data-mxwave="other"].busy')
    _more(page, "other")
    page.click('[data-mxdup="other"]')
    copy = page.evaluate("""() => {
      const order = CRATE.MX.order;
      return order[order.indexOf('other') + 1];
    }""")
    assert page.evaluate("id=>CRATE.MX.slots[id].n", copy) == 2
    page.evaluate("() => { releaseDuplicateRender(); return pendingDuplicateRender; }")
    assert page.evaluate("id=>CRATE.MX.slots[id].buf.duration", copy) == pytest.approx(4.8, abs=0.01)


def test_pitch_after_snapshot_recall_keeps_the_other_parts_pitch(site, page):
    _mixer(site, page)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===1")
    original = page.evaluate("CRATE.MX.slots.drums.bar0")
    alternate = (original + 1) % 12
    page.evaluate("bar=>CRATE.TR.setLoop('drums',bar,4)", alternate)
    page.evaluate("CRATE.TR.set('drums','ct',7)")
    page.click('[data-sn="0"]')
    page.wait_for_function("bar=>CRATE.MX.slots.drums.bar0===bar&&!CRATE.MX.slots.drums._loading", arg=original)
    page.evaluate("CRATE.TR.set('drums','ct',-20)")
    assert page.evaluate("bar=>CRATE.MX.hist.drums.find(p=>p.bar0===bar).ct", alternate) == 7


TOPS_SONGS = r'''
import json, numpy as np, soundfile as sf
from digitalcrate import stems, config as C
SR = C.SR
for tid, bpm in ((904, 100), (905, 104)):
    d = stems.DIR / f"t{tid}"; d.mkdir(parents=True, exist_ok=True)
    bar, nb = 240.0 / bpm, 16
    t = np.arange(int(nb * bar * SR)) / SR
    kick = (0.5 * (np.modf(t / (bar / 4))[0] < 0.25) * np.sin(2 * np.pi * 60 * t)).astype(np.float32)
    hat = (0.2 * (np.modf(t / (bar / 4) + 0.5)[0] < 0.1) * np.sin(2 * np.pi * 8000 * t)).astype(np.float32)
    tone = lambda f: (0.25 * np.sin(2 * np.pi * f * t)).astype(np.float32)
    parts = dict(drums=kick + hat, tops=hat, bass=tone(110), vocals=tone(440), other=tone(220) + tone(277) + tone(330))
    for k, y in parts.items():
        sf.write(str(d / f"{k}.flac"), np.stack([y, y]).T, SR, format="FLAC", subtype="PCM_16")
    ch = np.zeros(12); ch[[9, 1, 4]] = 1; ch /= np.linalg.norm(ch)
    e = np.zeros((5, 512), np.float16); e[:, tid % 512] = 1; np.save(d / "emb.npy", e)
    (d / "meta.json").write_text(json.dumps(dict(track=tid, artist=f"Kit Artist {tid}", title="Song", bpm=bpm, pc=9,
        scale="major", camelot="11B", bars=[round(b * bar, 4) for b in range(nb + 1)], act={k: [1.0] * nb for k in stems.ROLES},
        chroma=[ch.round(3).tolist()] * nb, stems=list(stems.ROLES), separated=False)))
print("TOPS OK", stems.DIR)
'''


def _kits(site):
    r = subprocess.run([sys.executable, "-c", TOPS_SONGS], env=site["env"], capture_output=True, text=True)
    assert "TOPS OK" in r.stdout, r.stderr[-2000:]
    directory = site["tops_dir"] = Path(r.stdout.split("TOPS OK ", 1)[1].strip())
    site["tops_cleanup"] = [directory / f"t{tid}" for tid in (904, 905)]


def test_tops_is_a_track(site, page):
    _kits(site)
    _mixer(site, page)
    assert page.evaluate("CRATE.MX.order") == ["drums", "tops", "bass", "vocals", "other"]
    _calls(page)
    _roll(page, "drums", 904); _roll(page, "tops", 905)
    assert page.inner_text('[data-mxrow="tops"] .trname') == "Tops" and "🥢" not in page.inner_text('[data-mxrow="tops"]')
    assert page.evaluate("document.querySelector('[data-mxrow=\"tops\"]').style.getPropertyValue('--trcol').trim()") == "var(--MEL)"
    stems_asked = page.evaluate("__calls.filter(c=>c[0]==='api/stems/render').map(c=>c[1].stem)")
    assert "tops" in stems_asked and "drums" in stems_asked
    assert page.evaluate("CRATE.MX.slots.tops.db") == -2 and page.locator('[data-mxduckon="tops"]').count() == 1
    page.select_option("#mxkey", "E")
    page.wait_for_function("!CRATE.MX.slots.tops._loading&&CRATE.MX.info&&CRATE.MX.info.slots.tops")
    assert page.evaluate("CRATE.MX.info.slots.tops.semis") == 0                       # never shifted to the key
    page.evaluate("CRATE.TR.set('tops','st',2)")
    page.wait_for_function("__calls.some(c=>c[0]==='api/stems/render'&&c[1].stem==='tops'&&c[1].semis===2)")
    page.evaluate("document.getElementById('mxsongs').open=true")
    page.wait_for_selector('[data-mxput="tops:904"]')
    assert page.is_disabled('.mxsong:has-text("Stem Artist 901") button >> nth=1')    # that song has no tops
    # the deal: Tops straight after Drums (the parts fetched ahead are dropped first, so both are asked for)
    order = page.evaluate("(async()=>{CRATE.MX.pre={};const seen=[],a=CRATE.api;CRATE.api=(p,b)=>{if(p==='api/stems/pick'){if(!Object.hasOwn(b,'track'))return Promise.resolve({part:null});seen.push(b.stem)}return a(p,b)};await CRATE.mxRollAll();return seen})()")
    assert order[:2] == ["drums", "tops"]


GIVE_TOPS = r"""
import json, soundfile as sf
from digitalcrate import stems
p = stems.DIR / "tTID" / "meta.json"
drums, sr = sf.read(str(p.with_name("drums.flac")), always_2d=True)
tops = stems._rough_tops(drums.T)["hh"].T
sf.write(str(p.with_name("tops.flac")), tops, sr, subtype="PCM_16")
m = json.loads(p.read_text())
m["act"]["tops"] = m["act"]["drums"]
m["stems"].append("tops")
m.pop("level", None)
p.write_text(json.dumps(m))
print("GIVEN")
"""


def _give_tops(site, track):
    site["tops_cleanup"].append(site["tops_dir"] / f"t{track}" / "tops.flac")
    r = subprocess.run([sys.executable, "-c", GIVE_TOPS.replace("TID", str(track))], env=site["env"],
                       capture_output=True, text=True)
    assert "GIVEN" in r.stdout, r.stderr[-2000:]


def _old_state(site, page, track, snap_only=False):
    """A mixer as it was saved before Tops: four tracks, a Drums part with settings of its own, one snapshot, v 2, clean."""
    _kits(site); _mixer(site, page); _roll(page, "drums", track)
    page.evaluate("""(async()=>{const M=CRATE.MX;M.order=M.order.filter(id=>id!=='tops');delete M.roles.tops;delete M.slots.tops;
      Object.assign(M.slots.drums,{db:-5,lock:true,eq:[1,0,2],dly:0.2,rev:0.3});await CRATE.mxSync()})()""")
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===1")
    page.fill("#mxname", "before tops"); page.click("#mxsave")
    page.wait_for_function("!CRATE.MX._saving&&CRATE.MX.savedSig&&CRATE.MX.savedSig===CRATE.mxSig()")
    saved = page.evaluate("""snapOnly=>{CRATE.mxPlay(false);const s=JSON.parse(localStorage.getItem('dcStems'));s.v=2;
      [s,...s.snaps].forEach(x=>Object.values(x.slots).forEach(p=>{delete p.kit}));
      const mark=JSON.parse(CRATE.mxSig(2));mark.snaps=s.snaps;s.savedSig=JSON.stringify(mark);
      if(snapOnly)delete s.slots.drums;
      return s}""", snap_only)
    # Install the legacy save in the new document, after the old mixer can no longer autosave over it.
    encoded = json.dumps(json.dumps(saved))
    page.add_init_script(f"""if (!sessionStorage.getItem('topsMigrationFixture')) {{
        sessionStorage.setItem('topsMigrationFixture', '1');
        localStorage.setItem('dcStems', {encoded});
    }}""")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX&&CRATE.MX.songs", timeout=30000)


def test_drums_saved_before_tops_keep_them_on_their_own_track(site, page):
    _old_state(site, page, 904)
    page.wait_for_function("CRATE.MX.slots['drums~tops']&&CRATE.MX.slots['drums~tops'].buf&&CRATE.MX.slots.drums.buf", timeout=60000)
    assert page.evaluate("CRATE.MX.order.slice(0,2)") == ["drums", "drums~tops"] and page.evaluate("CRATE.MX.roles['drums~tops']") == "tops"
    same = "['track','bar0','n','k','off','db','mute','lock','dly','rev'].every(f=>(d[f]||0)===(t[f]||0))&&''+d.eq===''+t.eq"
    assert page.evaluate(f"(()=>{{const d=CRATE.MX.slots.drums,t=CRATE.MX.slots['drums~tops'];return {same}&&!d.kit}})()")
    assert page.evaluate(f"(()=>{{const s=CRATE.MX.snaps[0],d=s.slots.drums,t=s.slots['drums~tops'];return s.order[1]==='drums~tops'&&{same}}})()")
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")                 # opening and splitting is not a change
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).v") == 5
    page.evaluate("CRATE.MX.snapSel=0"); assert page.evaluate("BLEND.changed()") is False
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===2")            # the play-strip view: the rows line up
    page.click("#snplay"); page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready", timeout=90000)
    assert page.evaluate("CRATE.PB.rows.slice(0,2).map(r=>[r.id,r.stem,r.kind])") == [["drums", "drums", "same"], ["drums~tops", "tops", "same"]]
    assert page.evaluate("!!CRATE.PB.voice('drums~tops','a')")
    page.reload()                                                                        # and it is split once, not again
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.slots['drums~tops']", timeout=30000)
    assert page.evaluate("CRATE.MX.order.filter(id=>CRATE.MX.roles[id]==='tops').length") == 1


def test_an_old_drums_part_only_in_a_snapshot(site, page):                              # Review Focus 4
    _old_state(site, page, 904, snap_only=True)
    page.wait_for_function("CRATE.MX.order.includes('drums~tops')", timeout=30000)
    assert page.evaluate("!CRATE.MX.slots['drums~tops']&&!!CRATE.MX.snaps[0].slots['drums~tops']")
    assert page.evaluate("''+CRATE.MX.order===''+CRATE.MX.snaps[0].order")


def test_a_part_split_once_its_song_has_tops(site, page):                               # Review Focus 1 and 5
    _old_state(site, page, 901)                                                          # 901 has no tops yet
    page.wait_for_function("CRATE.MX.slots.drums.buf&&!CRATE.MX.slots.drums._loading", timeout=60000)
    assert page.evaluate("CRATE.MX.slots.drums.kit===true&&!CRATE.MX.order.includes('drums~tops')")
    _roll(page, "drums", 902)                                                            # a new part of a song without tops
    assert page.evaluate("CRATE.MX.slots.drums.kit") is True
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.drums.kit") is True
    assert page.evaluate("CRATE.MX.hist.drums[CRATE.MX.hpos.drums].kit") is True
    _give_tops(site, 902)
    page.evaluate("CRATE.TR.set('drums','st',1)")                                        # any new render: the list of songs is still stale
    page.wait_for_function("CRATE.MX.slots['drums~tops']&&CRATE.MX.slots['drums~tops'].track===902&&CRATE.MX.slots['drums~tops'].buf&&!CRATE.MX.slots.drums.kit", timeout=60000)
    assert page.evaluate("CRATE.MX.slots['drums~tops'].off") == 1
    _roll(page, "drums", 904)
    assert page.evaluate("!CRATE.MX.slots.drums.kit")                                    # a song with tops: nothing to keep


def test_old_drums_parts_in_a_full_mixer(site, page):
    _old_state(site, page, 904)
    page.wait_for_function("JSON.parse(localStorage.getItem('dcStems')).slots['drums~tops']", timeout=60000)
    page.evaluate("""(()=>{const s=JSON.parse(localStorage.getItem('dcStems'));s.v=2;s.order=s.order.filter(id=>id!=='drums~tops');delete s.slots['drums~tops'];
      for(let k=0;k<4;k++){const id='x'+k;s.order.push(id);s.roles[id]='drums';s.slots[id]={...s.slots.drums,stem:'drums'}}
      s.snaps=[];delete s.sel;localStorage.setItem('dcStems',JSON.stringify(s));
      Storage.prototype.setItem=()=>{}})()""")   # (the page being left mustn't autosave over it: a render may still be finishing)
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.order.length===13", timeout=60000)   # 8 tracks, 5 of them old Drums
    assert page.locator("#mxadd").count() == 1                                       # (16 tracks at most now: room for more)


VDUCK_AUDIO = """async () => {
  const BL = BLEND, SR = 44100, N = 4 * SR, out = {};
  const rms = (d, a, b) => { let s = 0; for (let i = Math.round(a); i < Math.round(b); i++) s += d[i] * d[i]; return Math.sqrt(s / (b - a)); };
  const db = x => 20 * Math.log10(x + 1e-12);
  // a "vocal": 220 Hz and two overtones, sung for a second, silent for a second, at the loudness the server gives every part
  const vocal = ctx => { const b = ctx.createBuffer(1, N, SR), d = b.getChannelData(0);
    for (let i = 0; i < N; i++) { const t = i / SR;
      d[i] = Math.floor(t) % 2 ? 0 : Math.sin(2 * Math.PI * 220 * t) + 0.5 * Math.sin(2 * Math.PI * 440 * t) + 0.25 * Math.sin(2 * Math.PI * 660 * t); }
    const g = 0.08 / rms(d, 0, SR); for (let i = 0; i < N; i++) d[i] *= g; return b; };
  // what is ducked: steady noise, so its level is easy to read
  const hiss = ctx => { const b = ctx.createBuffer(1, N, SR), d = b.getChannelData(0); let a = 12345;
    for (let i = 0; i < N; i++) { a = (a * 1664525 + 1013904223) >>> 0; d[i] = a / 2147483648 - 1; }
    const g = 0.08 / rms(d, 0, N); for (let i = 0; i < N; i++) d[i] *= g; return b; };
  const play = (ctx, buf) => { const s = ctx.createBufferSource(); s.buffer = buf; s.start(0); return s; };
  const O = { fx: true, bar: 2, DT: { '1/8': 1 / 8 } };
  // one track of this role under the vocals; -> that track alone
  const run = async (role, duck, voices = [{ db: 0, on: true }]) => {
    const c = new OfflineAudioContext(2, N, SR), merge = c.createChannelMerger(2); merge.connect(c.destination);
    const MX = {}; BL.out(MX, c); MX.master.disconnect();
    const outT = c.createGain(), outV = c.createGain(); outT.connect(merge, 0, 0); outV.connect(merge, 0, 1);
    const ct = BL.mkChain(c, outT, MX.bus);
    BL.applyChain(ct, BL.mixOf({ db: 0 }, role, { ...O, on: true, duck }), 0); play(c, hiss(c)).connect(ct.in);
    for (const v of voices) { const cv = BL.mkChain(c, outV, MX.bus);
      BL.applyChain(cv, BL.mixOf({ db: v.db }, 'vocals', { ...O, on: v.on }), 0); play(c, vocal(c)).connect(cv.in); }
    return (await c.startRendering()).getChannelData(0); };
  const ref = await run('tops', { on: false });
  const against = (y, a, b) => db(rms(y, a * SR, b * SR)) - db(rms(ref, a * SR, b * SR));
  const drop = async (...a) => { const y = await run(...a); return { sung: against(y, 2.4, 2.9), rest: against(y, 1.4, 1.9) }; };
  out.tops3 = await drop('tops', undefined);                       // no setting yet: on, 3 dB
  out.tops12 = await drop('tops', { on: true, db: 12 });
  out.off = await drop('tops', { on: false, db: 12 });
  out.muted = await drop('tops', { on: true, db: 12 }, [{ db: 0, on: false }]);
  out.quiet = await drop('tops', { on: true, db: 12 }, [{ db: -12, on: true }]);
  out.two = await drop('tops', { on: true, db: 12 }, [{ db: 0, on: true }, { db: 0, on: true }]);
  for (const r of ['drums', 'bass', 'vocals', 'oneshot']) out[r] = await drop(r, { on: true, db: 12 });
  // the whole range: as much off at 100 Hz as at 8 kHz
  const band = async (data, f0) => { const c = new OfflineAudioContext(1, data.length, SR), b = c.createBuffer(1, data.length, SR); b.getChannelData(0).set(data);
    const f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = f0; f.Q.value = 2; play(c, b).connect(f); f.connect(c.destination);
    return (await c.startRendering()).getChannelData(0); };
  const y12 = await run('tops', { on: true, db: 12 });
  const at = async f => db(rms(await band(y12, f), 2.4 * SR, 2.9 * SR)) - db(rms(await band(ref, f), 2.4 * SR, 2.9 * SR));
  out.low = await at(100); out.high = await at(8000);
  // Other: by frequency. The vocal is at 220, 440 and 660 Hz: Other gives way there, and keeps its lows and its top
  const o12 = await run('other', { on: true, db: 12 }), o3 = await run('other', undefined), oOff = await run('other', { on: false, db: 12 });
  const o2 = await run('other', { on: true, db: 12 }, [{ db: 0, on: true }, { db: 0, on: true }]);
  const dip = async (y, f, a = 2.4, b = 2.9) => db(rms(await band(y, f), a * SR, b * SR)) - db(rms(await band(ref, f), a * SR, b * SR));
  out.other = { at250: await dip(o12, 250), at500: await dip(o12, 500), at4k: await dip(o12, 4000), at8k: await dip(o12, 8000), at60: await dip(o12, 60),
    d250: await dip(o3, 250), d4k: await dip(o3, 4000), rest250: await dip(o12, 250, 1.4, 1.9), off250: await dip(oOff, 250), two250: await dip(o2, 250) };
  // one chain, its track's role changed from Bass to Other to Tops
  { const c = new OfflineAudioContext(1, SR, SR), MX = {}; BL.out(MX, c); const ch = BL.mkChain(c, c.destination, MX.bus), seen = [];
    for (const role of ['bass', 'other', 'tops']) { BL.applyChain(ch, BL.mixOf({ db: 0 }, role, { ...O, on: true }), 0); seen.push([ch.ducked, ch.vducked, ch.vbanded]); }
    out.switched = seen; }
  // a chain on a bus that has no vocal bus
  { const c = new OfflineAudioContext(1, SR, SR), ch = BL.mkChain(c, c.destination, BL.duckBus(c));
    for (const role of ['other', 'tops']) BL.applyChain(ch, BL.mixOf({ db: 0 }, role, { ...O, on: true }), 0);
    ch.drop(); out.bare = [ch.vducked, ch.vbanded]; }
  return out;
}"""


def test_vocal_duck_audio(page):
    """The vocal duck, measured offline. Tops drop by close to the amount while the vocal sings, across the whole range,
    and are back between phrases. Other gives way where the voice is and keeps its lows and its top. Nothing else is touched."""
    o = page.evaluate(VDUCK_AUDIO)
    assert -3.6 < o["tops3"]["sung"] < -2.2 and o["tops3"]["rest"] > -0.5
    assert -13.0 < o["tops12"]["sung"] < -9.5 and o["tops12"]["rest"] > -1.0
    assert o["off"]["sung"] > -0.1 and o["muted"]["sung"] > -0.1
    assert o["quiet"]["sung"] > o["tops12"]["sung"] + 3            # a quieter vocal ducks less
    assert o["two"]["sung"] > -13.0                                # two vocals: no deeper than the amount
    assert all(o[r]["sung"] > -0.1 for r in ("drums", "bass", "vocals", "oneshot"))
    assert abs(o["low"] - o["high"]) < 0.5                         # Tops: the whole range, not a shelf
    b = o["other"]
    assert -13.5 < b["at250"] < -8 and b["at500"] < -4             # Other at 12 dB: down where the voice is
    assert b["at4k"] > -1.5 and b["at8k"] > -1.0 and b["at60"] > -1.0   # and its top and its lows left alone
    assert -4.2 < b["d250"] < -2.0 and b["d4k"] > -0.6             # at 3 dB, the amount it starts with
    assert b["rest250"] > -1.0 and b["off250"] > -0.1 and b["two250"] > -14.0   # back between phrases; off is off; two vocals go no deeper
    assert o["switched"] == [[True, False, False], [False, False, True], [False, True, False]] and o["bare"] == [False, False]


def test_vocals_duck_tops_and_other(site, page):
    _kits(site); _mixer(site, page); _roll(page, "drums", 904); _roll(page, "tops", 905)
    assert page.locator("[data-mxduckon]").count() == 3 and all(page.locator(f'[data-mxduckon="{s}"]').count() == 1 for s in ("bass", "tops", "other"))
    assert "vocals" in page.inner_text('[data-mxrow="other"] [data-dev="duck"]') and "lows" in page.inner_text('[data-mxrow="bass"] [data-dev="duck"]')
    page.wait_for_function("(()=>{const c=id=>CRATE.MX.slots[id]._c;return c('other').vbanded&&!c('other').vducked&&c('tops').vducked&&!c('tops').vbanded&&!c('bass').vducked&&c('bass').ducked&&!c('vocals').vducked})()")
    assert page.evaluate("BLEND.duckDb(CRATE.MX.duck.other)") == 3
    page.click("#mxfx")                                                              # the ducks are not effects
    page.wait_for_function("CRATE.MX.fx===false&&CRATE.MX.slots.other._c.vbanded===true")
    page.click("#mxfx")
    page.click('[data-mxsolo="drums"]')                                              # a vocal that is soloed out ducks nothing
    page.wait_for_function("CRATE.MX.slots.vocals._c.vol.gain.value<0.001")
    page.click('[data-mxsolo="drums"]')
    page.fill("#mxname", "ducked"); page.click("#mxsave")
    page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===1")
    page.click("#mxsave"); page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.evaluate("CRATE.TR.set('other','duck',6)")
    assert "dirty" in page.get_attribute("#mxsave", "class") and page.evaluate("BLEND.changed()") is True
    page.click('[data-mxduckon="tops"]')
    page.wait_for_function("CRATE.MX.slots.tops._c.vducked===false&&CRATE.MX.duck.tops.on===false")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.duck.other", timeout=30000)
    assert page.evaluate("[CRATE.MX.duck.other,CRATE.MX.duck.tops]") == [{"on": True, "db": 6}, {"on": False, "db": 3}]
    for w in (1512, 1280):                                                           # the longer rows still fit
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(200)
        assert page.evaluate("[...document.querySelectorAll('.trfx,.trfx *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"), w


def test_state_saved_before_the_vocal_duck_uses_its_default(site, page):
    _old_state(site, page, 904)                                                      # v 2, clean, one snapshot, old Drums
    page.wait_for_function("CRATE.MX.slots['drums~tops']&&CRATE.MX.slots['drums~tops'].buf&&CRATE.MX.slots.other.buf", timeout=60000)
    enabled = "(d=>['other','drums~tops','bass'].every(id=>d[id]?.on!==false))"
    assert page.evaluate(f"{enabled}(CRATE.MX.duck)") and page.evaluate(f"{enabled}(CRATE.MX.snaps[0].duck)")
    page.click("#mxplay")
    page.wait_for_function("['other','drums~tops','bass'].every(id=>CRATE.MX.slots[id]._c)")
    assert page.evaluate("CRATE.MX.slots.other._c.vbanded&&CRATE.MX.slots['drums~tops']._c.vducked&&CRATE.MX.slots.bass._c.ducked")
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")
    page.evaluate("CRATE.MX.snapSel=0"); assert page.evaluate("BLEND.changed()") is False
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).v") == 5
    page.click("#mxclear"); page.click("#mxclear")                                   # a clean slate ducks as a new mixer does
    _roll(page, "other", 902); _roll(page, "vocals", 901)
    page.wait_for_function("CRATE.MX.slots.other._c&&CRATE.MX.slots.other._c.vbanded===true")


def test_playback_ducks_under_the_vocals(site, page):
    _strip(site, page)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    assert page.evaluate("CRATE.PB.voice('other','a').chain.vbanded") is True        # A's Other, under the vocal
    assert page.evaluate("(()=>{const c=CRATE.PB.voice('vocals','a').chain;return c.vducked||c.vbanded})()") is False
    assert page.evaluate("CRATE.PB.voice('bass','a').chain.ducked") is True          # and the bass's own duck is as it was


def test_playback_ducks_each_side_by_its_own_role(site, page):
    _kits(site)
    _mixer(site, page)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===1")
    _more(page, "other")
    page.select_option('[data-mxrole="other"]', "tops")
    page.wait_for_function("CRATE.MX.slots.other?.stem==='tops'&&CRATE.MX.slots.other.buf&&!CRATE.MX.slots.other._loading")
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===2")
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    assert page.evaluate("""() => ['a','b'].map(side => {
        const {vbanded, vducked} = CRATE.PB.voice('other', side).chain;
        return [vbanded, vducked];
    })""") == [[True, False], [False, True]]


def test_vocal_duck_migration_ignores_a_previous_bass_setting(site, page):
    _mixer(site, page)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===1")
    # Earlier builds kept a slot's Bass setting when Plays changed its role to Other.
    page.evaluate("""() => {
        const s = JSON.parse(localStorage.getItem('dcStems'));
        s.v = 3;
        for (const mix of [s, ...s.snaps]) mix.duck.other = {on: true, db: 12};
        const mark = JSON.parse(CRATE.mxSig(3));
        mark.snaps = s.snaps;
        s.savedSig = JSON.stringify(mark);
        localStorage.setItem('dcStems', JSON.stringify(s));
    }""")
    page.reload()
    page.wait_for_function("CRATE.MX?.slots.other?.buf", timeout=60000)
    assert page.evaluate("""[CRATE.MX, CRATE.MX.snaps[0]].map(mix => {
        const duck = mix.duck?.other;
        return [duck?.on !== false, BLEND.duckDb(duck), BLEND.gduckDb(duck)];
    })""") == [[True, 3, 2]] * 2
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")


def test_tops_split_keeps_an_edited_companion_track(site, page):
    _old_state(site, page, 904)
    page.wait_for_function("CRATE.MX.slots['drums~tops']?.buf", timeout=60000)
    _roll(page, "drums~tops", 905)
    _roll(page, "drums", 902)
    _give_tops(site, 902)
    page.evaluate("async () => { await CRATE.mxRefreshSongs(); await CRATE.mxSync(); }")
    assert page.evaluate("CRATE.MX.slots['drums~tops'].track") == 905
    assert page.evaluate("""() => {
        const m = CRATE.MX;
        const id = m.order.find(id => m.roles[id] === 'tops' && m.slots[id]?.track === 902);
        return !!id && m.snaps[0].order.includes(id) && m.snaps[0].slots['drums~tops'].track === 904;
    }""")


def test_playback_reloads_drums_after_a_kit_split(site, page):
    _old_state(site, page, 901)
    page.wait_for_function("CRATE.MX.slots.drums?.buf", timeout=60000)
    for count in (2, 3):
        page.click("#sncap")
        page.wait_for_function("n => CRATE.MX.snaps.length === n", arg=count)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.ready&&CRATE.PB.playing&&CRATE.PB.nextReady", timeout=60000)
    page.evaluate("window.wholeDrums = CRATE.PB.voice('drums','a').buf")
    _give_tops(site, 901)
    _set(page, "#pbm", 100)
    page.click("#pbnext")
    page.wait_for_function("CRATE.PB.i===1&&CRATE.PB.ready", timeout=60000)
    assert page.evaluate("CRATE.PB.voice('drums','a').buf !== wholeDrums && !!CRATE.PB.voice('drums~tops','a')")
    page.click("#pbback")
    assert page.evaluate("!!CRATE.MX.slots['drums~tops'].buf")


def test_vocal_duck_releases_a_discarded_mixer_chain(site, page):
    _mixer(site, page)
    page.click("#sncap")
    page.wait_for_function("CRATE.MX.snaps.length===1")
    page.evaluate("window.previousOther = CRATE.MX.slots.other._c")
    assert page.evaluate("previousOther.vbanded")
    page.click('[data-sn="0"]')
    page.wait_for_function("CRATE.MX.slots.other._c?.vbanded && CRATE.MX.slots.other._c !== previousOther")
    page.wait_for_function("!previousOther.vbanded", timeout=1500)


def test_bass_is_even_by_default_and_parts_from_before_are_not(site, page):
    _mixer(site, page)
    _calls(page)
    bass = page.evaluate("CRATE.MX.slots.bass.track")
    _roll(page, "bass", 902 if bass != 902 else 903)
    asked = lambda: page.evaluate("""() => {
        const p = CRATE.MX.slots.bass;
        return __calls.filter(([path, args]) => path === 'api/stems/render' &&
            args.stem === 'bass' && args.track === p.track && args.bar0 === p.bar0).pop()[1].cond || 0;
    }""")
    assert page.evaluate("CRATE.MX.slots.bass.cond") == 1 and asked() == 1
    assert page.locator("[data-mxeven]").count() == 1 and page.get_attribute('[data-mxeven="bass"]', "aria-pressed") == "true"
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.bass.cond") == 1
    page.click("#mxfx")
    assert page.evaluate("CRATE.MX.fx===false&&CRATE.MX.slots.bass.cond===1")
    assert page.get_attribute('[data-mxeven="bass"]', "aria-pressed") == "true"
    page.click("#mxfx")
    assert page.evaluate("(()=>{const a=CRATE.MX.slots.bass;return BLEND.sameAudio({...a,stem:'bass'},{...a,stem:'bass',cond:undefined})})()") is False
    for w in (1512, 1280):                                                           # the bass row still fits
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(200)
        assert page.evaluate("[...document.querySelectorAll('[data-mxrow=\"bass\"] .trfx,[data-mxrow=\"bass\"] .trfx *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"), w
    # what counts as a change: a part with Even has one thing more in its signature; a part without has none (4)
    longer = "(()=>{const s=JSON.parse(CRATE.mxSig()).slots,len=r=>s.find(x=>x[0]===r)[1].length;return len('bass')-len('drums')})()"
    assert page.evaluate(longer) == 1
    page.fill("#mxname", "even"); page.click("#mxsave"); page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.evaluate("window.evenBuffer = CRATE.MX.slots.bass.buf")
    page.click('[data-mxeven="bass"]')                                               # off: a new render, and a change
    page.wait_for_function("""() => {
        const p = CRATE.MX.slots.bass;
        return !p.cond && p.buf && p.buf !== evenBuffer && !p._loading;
    }""")
    assert asked() == 0 and "dirty" in page.get_attribute("#mxsave", "class") and page.evaluate(longer) == 0
    assert "cond" not in page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.bass")
    assert page.evaluate("CRATE.MX.hist.bass[CRATE.MX.hpos.bass].cond ?? null") is None
    page.click("#mxsave")
    page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.reload()                                                                    # a part without it stays without it
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.slots.bass&&CRATE.MX.slots.bass.buf", timeout=60000)
    assert page.get_attribute('[data-mxeven="bass"]', "aria-pressed") == "false"
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")
    # 5. the play-strip view asks for the same render as the mixer
    page.evaluate("window.plainBuffer = CRATE.MX.slots.bass.buf")
    page.click('[data-mxeven="bass"]')
    page.wait_for_function("""() => {
        const p = CRATE.MX.slots.bass;
        return p.cond === 1 && p.buf && p.buf !== plainBuffer && !p._loading;
    }""")
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===1")
    _roll(page, "drums", 902 if page.evaluate("CRATE.MX.slots.drums.track") != 902 else 903)
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===2")
    _calls(page); page.evaluate("__calls.length=0"); page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready", timeout=90000)
    strip = page.evaluate("__calls.filter(c=>c[0]==='api/stems/render'&&c[1].stem==='bass').map(c=>c[1].cond||0)")
    assert strip and all(c == 1 for c in strip)


def test_even_bass_prefetch_follows_the_new_role(site, page):
    _mixer(site, page)
    page.wait_for_function("CRATE.MX.pre.bass?.ready")
    assert page.evaluate("CRATE.MX.pre.bass.part.cond") == 1
    _more(page, "bass")
    page.select_option('[data-mxrole="bass"]', "other")
    page.wait_for_function("CRATE.MX.roles.bass === 'other' && !!CRATE.MX.slots.bass?.buf && !CRATE.MX.slots.bass._loading")
    assert page.evaluate("CRATE.MX.slots.bass.stem") == "other"
    assert page.evaluate("CRATE.MX.slots.bass.cond ?? null") is None


def test_even_bass_history_keeps_both_renders_of_one_part(site, page):
    _mixer(site, page)
    _roll(page, "bass", 901)
    page.click('[data-mxeven="bass"]')
    page.wait_for_function("document.querySelector('[data-mxeven=bass]')?.getAttribute('aria-pressed') === 'false'")
    before = page.evaluate("""() => {
        const {track, bar0, n, k} = CRATE.MX.slots.bass;
        return [track, bar0, n, k];
    }""")
    _roll(page, "bass", 901)
    assert page.evaluate("""() => {
        const {track, bar0, n, k} = CRATE.MX.slots.bass;
        return [track, bar0, n, k];
    }""") == before
    assert page.evaluate("""() => {
        const {hist, hpos} = CRATE.MX;
        return hist.bass.slice(hpos.bass - 1, hpos.bass + 1).map(p => p.cond || 0);
    }""") == [0, 1]
    page.click('[data-mxhist="bass:-1"]')
    page.wait_for_function("document.querySelector('[data-mxeven=bass]')?.getAttribute('aria-pressed') === 'false'")


def test_new_parts_use_the_octave_and_parts_from_before_the_clipper(site, page):
    _mixer(site, page)
    bass = page.evaluate("CRATE.MX.slots.bass.track")
    _roll(page, "bass", 902 if bass != 902 else 903)
    switch = page.locator('[data-mxhk="bass"]')
    assert page.evaluate("CRATE.MX.slots.bass.hk") == "oct"
    assert switch.get_attribute("aria-pressed") == "true"
    page.evaluate("CRATE.TR.set('bass','harm',100)")
    live = "CRATE.MX.slots.bass._c"
    def gains(chain, kind):
        wet = {"drive": ("0.35", "0"), "oct": ("0", "BLEND.HARM.oct.gain"), "off": ("0", "0")}[kind]
        page.wait_for_function(f"Math.abs({chain}.hg.gain.value-{wet[0]})<0.001&&Math.abs({chain}.hgo.gain.value-{wet[1]})<0.001")
    gains(live, "oct")
    page.click("#mxfx")
    gains(live, "off")
    page.click("#mxfx")
    gains(live, "oct")
    page.fill("#mxname", "octave")
    page.click("#mxsave")
    page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    vol = live + ".vol.gain.value"
    page.wait_for_timeout(200)
    v_oct = page.evaluate(vol)
    page.evaluate(f"window.__vols=[];window.__w=setInterval(()=>__vols.push({vol}),5)")
    switch.click()
    gains(live, "drive")
    page.wait_for_timeout(200)
    page.evaluate("clearInterval(__w)")
    lo, hi = sorted((v_oct, page.evaluate(vol)))
    assert page.evaluate("Math.min(...__vols)") > lo * 0.97
    assert page.evaluate("Math.max(...__vols)") < hi * 1.03
    assert "dirty" in page.get_attribute("#mxsave", "class")
    assert "hk" not in page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.bass")
    page.click("#mxsave")
    page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.reload()
    page.wait_for_selector("#mxplay")
    page.click("#mxplay")
    page.wait_for_function(f"!!{live}", timeout=60000)
    gains(live, "drive")
    assert switch.get_attribute("aria-pressed") == "false"
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")
    for w in (1512, 1280):
        page.set_viewport_size({"width": w, "height": 800})
        assert page.evaluate("[...document.querySelectorAll('.trfx,.trfx *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"), w
    page.click("#sncap")
    page.evaluate("CRATE.TR.set('other','harm',50)")
    page.click("#sncap")
    switch.click()
    gains(live, "oct")
    page.click("#sncap")
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.ready&&CRATE.PB.playing&&CRATE.PB.nextReady")
    voice = "CRATE.PB.voice('bass','a')"
    page.evaluate(f"window.__bassVoice={voice}")
    gains(voice + ".chain", "drive")
    page.evaluate("CRATE.PB.setMaster(1)")
    page.click("#pbnext")
    page.wait_for_function("CRATE.PB.i===1&&CRATE.PB.ready")
    assert page.evaluate(f"{voice}===__bassVoice&&{voice}===CRATE.PB.voice('bass','b')")
    for m, kind in ((0.2, "drive"), (0.5, "oct"), (0.8, "oct")):
        page.evaluate(f"CRATE.PB.setMaster({m})")
        gains(voice + ".chain", kind)
        want = page.evaluate(f"""async()=>{{const v={voice},hc=await BLEND.harmMeasure(v.buf,'{kind}'),
          p=CRATE.MX.snaps[1].slots.bass;return 10**(p.db/20)*BLEND.harmComp(p,hc)}}""")
        page.wait_for_function(f"Math.abs({voice}.chain.vol.gain.value-{want})<0.001")


def test_one_shot_uses_octave_harmonics(site, page):
    _mixer(site, page)
    slot = _one_shot(page)
    p = f"CRATE.MX.slots['{slot}']"
    assert page.evaluate(p + ".hk") == "oct"
    assert page.get_attribute(f'[data-mxhk="{slot}"]', "aria-pressed") == "true"
    page.evaluate(f"CRATE.TR.set('{slot}','harm',100)")
    page.wait_for_function(f"{p}._hc&&{p}._c.hg.gain.value<0.001&&Math.abs({p}._c.hgo.gain.value-BLEND.HARM.oct.gain)<0.001")
    page.click(f'[data-mxtrimopen="{slot}"]')
    beat = 60 / page.evaluate("CRATE.MX.bpm")
    dur = page.evaluate(p + ".buf.duration")
    fit = next(b for b in (1, 2, 4, 8) if 0.45 < b * beat / dur < 2.4)
    page.select_option(f'[data-mxwarp="{slot}"]', str(fit))
    page.wait_for_function(f"{p}.wbuf&&!{p}._loading", timeout=60000)
    assert page.evaluate(f"async()=>{p}._hc===await BLEND.harmMeasure({p}.wbuf,'oct')")
    page.click(f'[data-mxhk="{slot}"]')
    page.wait_for_function(f"!{p}.hk&&{p}._hc===null&&Math.abs({p}._c.hg.gain.value-0.35)<0.001")
    # The scheduler must see a freshly dealt one-shot and its compensation together.
    page.evaluate("""id=>{
      const original=BLEND.harmMeasure, sample=CRATE.MX.slots[id].sample;
      BLEND.harmMeasure=async(buf,kind)=>{
        if(kind==='oct' && buf.duration<2){
          BLEND.harmMeasure=original;
          await new Promise(resolve=>window.releaseShot=resolve);
        }
        return original(buf,kind);
      };
      void CRATE.mxRoll(id,true,sample);
    }""", slot)
    page.wait_for_function("!!window.releaseShot")
    assert page.evaluate(p + ".buf") is None
    page.evaluate("releaseShot()")
    page.wait_for_function(f"{p}.buf&&{p}._hc&&!{p}._loading")



def test_octave_measurement_follows_the_current_part(site, page):
    _mixer(site, page)
    slot = "CRATE.MX.slots.bass"
    switch = page.locator('[data-mxhk="bass"]')
    # Hold the first measurement on the old buffer while the mixer handles other input.
    def hold_drive():
        page.evaluate("""() => {
          const original=BLEND.harmMeasure, old=CRATE.MX.slots.bass.buf;
          window.releaseDrive=null;
          BLEND.harmMeasure=async(buf,kind)=>{
            if(buf===old&&kind==='drive'){
              BLEND.harmMeasure=original;
              await new Promise(resolve=>window.releaseDrive=resolve);
            }
            return original(buf,kind);
          };
        }""")
        switch.click()
        page.wait_for_function("!!window.releaseDrive")
    hold_drive()
    switch.click()
    page.evaluate("releaseDrive()")
    page.wait_for_function(f"!{slot}._hkRequest&&{slot}.hk==='oct'")

    hold_drive()
    page.evaluate(f"window.__oldBuf={slot}.buf")
    page.click('[data-mxeven="bass"]')
    page.wait_for_function(f"{slot}.buf!==__oldBuf&&!{slot}._loading")
    page.evaluate("releaseDrive()")
    page.wait_for_function(f"!{slot}.hk")
    assert page.evaluate(f"async()=>{slot}._hc===await BLEND.harmMeasure({slot}.buf,'drive')")

    switch.click()
    page.wait_for_function(f"{slot}.hk==='oct'")
    hold_drive()
    track = page.evaluate(slot + ".track")
    _roll(page, "bass", 902 if track != 902 else 903)
    page.evaluate("releaseDrive()")
    assert page.evaluate(slot + ".hk") == "oct"
    switch.click()
    page.wait_for_function(f"!{slot}.hk")
    page.click('[data-mxhist="bass:-1"]')
    page.wait_for_function(f"{slot}.track==={track}&&{slot}.buf")
    assert page.evaluate(slot + ".hk") == "oct"
    page.click('[data-mxhist="bass:1"]')
    page.wait_for_function(f"{slot}.track!=={track}&&{slot}.buf")
    assert page.evaluate(slot + ".hk") is None


def test_octave_toggle_after_snapshot_recall_keeps_other_bars_history(site, page):
    _mixer(site, page)
    p = "CRATE.MX.slots.bass"
    a = page.evaluate(p + ".bar0")
    b = 0 if a != 0 else 4
    page.click("#sncap")
    page.evaluate(f"CRATE.TR.setLoop('bass',{b},2)")
    page.click('[data-sn="0"]')
    page.wait_for_function(f"{p}.bar0==={a}&&{p}.buf")
    page.click('[data-mxhk="bass"]')
    page.wait_for_function(f"!{p}.hk")
    page.click('[data-mxhist="bass:-1"]')
    page.wait_for_function(f"{p}.bar0==={a}&&{p}.buf")
    page.click('[data-mxhist="bass:1"]')
    page.wait_for_function(f"{p}.bar0==={b}&&{p}.buf")
    assert page.evaluate(p + ".hk") == "oct"


def test_trimmed_octave_one_shot_keeps_level_at_playback_pitch(site, page):
    _mixer(site, page)
    slot = _one_shot(page)
    page.evaluate("""async id=>{
      const p=CRATE.MX.slots[id], sr=44100;
      const buf=new AudioBuffer({numberOfChannels:1,length:sr,sampleRate:sr}), data=buf.getChannelData(0);
      for(let i=0;i<sr;i++){
        const t=i/sr*2*Math.PI;
        data[i]=i<sr/5 ? 0.2*Math.sin(55*t)+0.1*Math.sin(110*t+3*Math.PI/4) : 0.2*Math.sin(440*t);
      }
      p.buf=buf;p.trim=null;p.off=p.ct=0;p._hc=await BLEND.harmMeasure(buf,'oct');
      CRATE.TR.set(id,'harm',100);
    }""", slot)
    canvas = page.locator(f'canvas[data-mxtrim="{slot}"]').first
    box = canvas.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + 1, y)
    page.mouse.down()
    page.mouse.move(box["x"] + 0.2 * box["width"], y, steps=6)
    page.mouse.up()
    for pitch in (0, 12):
        page.evaluate("([id,pitch])=>CRATE.TR.set(id,'st',pitch)", [slot, pitch])
        target = page.evaluate("""async id=>{
          const p=CRATE.MX.slots[id], [a,b]=p.trim, rate=2**(p.off/12);
          const ctx=new OfflineAudioContext(1,Math.ceil((b-a)*p.buf.length/rate),p.buf.sampleRate);
          const source=ctx.createBufferSource();source.buffer=p.buf;source.playbackRate.value=rate;
          source.connect(ctx.destination);source.start(0,a*p.buf.duration,(b-a)*p.buf.duration);
          const played=await ctx.startRendering(), hc=await BLEND.harmMeasure(played,'oct');
          return 10**(p.db/20)*BLEND.harmComp(p,hc);
        }""", slot)
        page.wait_for_function(f"Math.abs(20*Math.log10(CRATE.MX.slots['{slot}']._c.vol.gain.value/{target}))<0.05", timeout=3000)


def test_other_take_keeps_driven_harmonics_if_render_fails(site, page):
    _mixer(site, page)
    p = "CRATE.MX.slots.other"
    page.click('[data-mxhk="other"]')
    page.wait_for_function(f"!{p}.hk")
    page.evaluate("""()=>{
      const p=CRATE.MX.slots.other;
      window.oldOther={buf:p.buf,hc:p._hc};
      const api=CRATE.api;
      CRATE.api=(path,body)=>{
        if(path==='api/stems/alts')return Promise.resolve({alts:[{bar0:p.bar0},{bar0:(p.bar0+1)%12}]});
        if(path==='api/stems/render'&&body.stem==='other')return Promise.reject(Error('take unavailable'));
        return api(path,body);
      };
    }""")
    _more(page, "other")
    page.click('[data-mxalt="other"]')
    page.wait_for_function(f"{p}.err==='take unavailable'")
    page.evaluate("CRATE.TR.set('other','harm',100)")
    assert page.evaluate(f"!{p}.hk&&{p}.buf===oldOther.buf&&{p}._hc===oldOther.hc")
    page.wait_for_function(f"Math.abs({p}._c.hg.gain.value-0.35)<0.001&&{p}._c.hgo.gain.value<0.001")


def test_octave_duplicate_gets_the_pending_one_shot_measurement(site, page):
    _mixer(site, page)
    slot = _one_shot(page)
    page.evaluate("""id => {
        const part = CRATE.MX.slots[id], original = BLEND.harmMeasure;
        const target = part.buf.duration / 2;
        BLEND.harmMeasure = async (buf, kind) => {
            if (kind === 'oct' && Math.abs(buf.duration - target) < 0.001) {
                BLEND.harmMeasure = original;
                await new Promise(resolve => { window.releaseDuplicateMeasure = resolve; });
            }
            return original(buf, kind);
        };
        window.beforeDuplicateMeasure = part._hc;
        void CRATE.TR.set(id, 'st', 12);
    }""", slot)
    page.wait_for_function("typeof window.releaseDuplicateMeasure === 'function'")
    _more(page, slot)
    page.click(f'[data-mxdup="{slot}"]')
    copy = page.evaluate("id => CRATE.MX.order[CRATE.MX.order.indexOf(id) + 1]", slot)
    page.evaluate("releaseDuplicateMeasure()")
    page.wait_for_function("""([id, copy]) => {
        const original = CRATE.MX.slots[id], duplicate = CRATE.MX.slots[copy];
        return original._hc !== beforeDuplicateMeasure && duplicate._hc === original._hc;
    }""", arg=[slot, copy], timeout=2000)


def test_master_chain_is_unity_when_quiet_trims_the_ends_and_holds_loud_peaks(page):
    r = page.evaluate("""(async()=>{const SR=48000;
      const run=async(make)=>{const ctx=new OfflineAudioContext(2,SR*2,SR),c=await CRATE.masterChain(ctx);make(ctx).connect(c.in);c.out.connect(ctx.destination);
        const d=(await ctx.startRendering()).getChannelData(0);let s=0,pk=0;for(let k=0;k<d.length;k++){pk=Math.max(pk,Math.abs(d[k]));if(k>=SR)s+=d[k]*d[k]}return {rms:Math.sqrt(s/SR),pk}};
      const tone=(f,a)=>ctx=>{const o=ctx.createOscillator(),g=ctx.createGain();o.frequency.value=f;g.gain.value=a;o.connect(g);o.start();return g};
      const noise=ctx=>{const b=ctx.createBuffer(2,SR*2,SR);for(let c=0;c<2;c++){const d=b.getChannelData(c);let x=7+c;for(let k=0;k<d.length;k++){x=(x*1664525+1013904223)>>>0;d[k]=(x/4294967296*2-1)*1.4}}
        const s=ctx.createBufferSource();s.buffer=b;s.start();return s};
      const A=0.03,ref=A/Math.SQRT2,db=x=>20*Math.log10(x/ref);
      return {mid:db((await run(tone(1000,A))).rms),low:db((await run(tone(20,A))).rms),high:db((await run(tone(15000,A))).rms),peak:(await run(noise)).pk,
              makeup:await CRATE.masterProbe({threshold:-18,knee:12,ratio:2,attack:0.03,release:0.25})}})()""")
    assert r["makeup"] > 1.2, r        # the browser's compressor adds make-up gain by itself
    assert abs(r["mid"]) < 0.5, r      # below the threshold: out at the level it went in
    assert -10 < r["low"] < -6, r      # 20 Hz, under the 30 Hz highpass
    assert -1.6 < r["high"] < -0.6, r  # 15 kHz, on the -1.5 dB shelf
    assert r["peak"] < 0.9, r          # noise peaking at 1.4 going in


def test_master_switch_is_on_by_default_bypasses_and_is_kept(site, page):
    page.evaluate("localStorage.setItem('dcStems', JSON.stringify({bpm:100,key:'',slots:{}}))")
    page.reload()
    page.evaluate("""() => {
        const start = OfflineAudioContext.prototype.startRendering;
        const gate = new Promise(resolve => { window.releaseMasterProbe = resolve; });
        // Hold back the master chain's calibration only (one second of mono at 48 kHz). Loading a part renders
        // offline too, to measure its harmonics, and must go through.
        OfflineAudioContext.prototype.startRendering = function () {
            const probe = this.length === 48000 && this.sampleRate === 48000 && this.destination.channelCount === 1;
            return probe ? gate.then(() => start.call(this)) : start.call(this);
        };
        const targets = new Set();
        const connect = AudioNode.prototype.connect, disconnect = AudioNode.prototype.disconnect;
        AudioNode.prototype.connect = function (target) {
            const output = connect.apply(this, arguments);
            if (this === CRATE.MX.master) targets.add(target);
            return output;
        };
        AudioNode.prototype.disconnect = function (target) {
            disconnect.apply(this, arguments);
            if (this === CRATE.MX.master) {
                if (arguments.length) targets.delete(target);
                else targets.clear();
            }
        };
        window.masterRoutedTo = target => {
            const {master, mast} = CRATE.MX;
            const node = target === 'direct' ? master.context.destination : mast.chain?.in;
            return targets.size === 1 && targets.has(node);
        };
    }""")
    _mixer(site, page)
    assert page.evaluate("CRATE.MX.mast.on") is True and page.is_checked("#mxmaster")   # no saved 'master' key: on
    page.evaluate("for(let k=0;k<6;k++)document.getElementById('mxmaster').click()")
    assert page.evaluate("CRATE.MX.mast.built===0 && masterRoutedTo('direct')")
    page.evaluate("releaseMasterProbe()")
    page.wait_for_function("CRATE.MX.mast.chain", timeout=10000)
    page.wait_for_function("masterRoutedTo('chain')")
    page.wait_for_function("/^-?\\d+\\.\\d dB$/.test(document.getElementById('mxgr').textContent)", timeout=5000)
    page.evaluate("for(let k=0;k<6;k++)document.getElementById('mxmaster').click()")          # six quick flips: back on
    assert page.evaluate("CRATE.MX.mast.on") is True and page.evaluate("CRATE.MX.mast.built") == 1  # built once
    page.click("#mxmaster")
    assert page.evaluate("CRATE.MX.mast.on") is False
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).master.on") is False
    page.wait_for_function("document.getElementById('mxgr').textContent===''", timeout=2000)   # off: no readout
    page.wait_for_function("masterRoutedTo('direct')")
    page.reload()
    page.wait_for_function("typeof CRATE!=='undefined'&&CRATE.MX&&document.getElementById('mxmaster')", timeout=60000)
    assert not page.is_checked("#mxmaster")                                                    # kept across a refresh


def test_mixer_undo_preserves_new_mix_settings_and_playback(site, page):
    _mixer(site, page)
    page.evaluate("CRATE.mxSync()")
    state = """() => {
        const {v, master, glue, slots} = JSON.parse(localStorage.getItem('dcStems'));
        return [v, master.on, glue.on, slots.bass.cond, slots.bass.hk];
    }"""
    initial = page.evaluate(state)
    assert initial[:3] == [5, True, True] and initial[3] and initial[4] == "oct"
    page.evaluate("window.sourceBeforeUndo = CRATE.MX.slots.bass._s")
    for control, index in (("#mxmaster", 1), ("#mxglue", 2)):
        before = page.evaluate(state)
        after = before.copy()
        after[index] = False
        page.wait_for_timeout(700)
        page.click(control)
        assert page.evaluate(state) == after
        page.evaluate("CRATE.mxUndo(-1)")
        assert page.evaluate(state) == before
        page.evaluate("CRATE.mxUndo(1)")
        assert page.evaluate(state) == after
    assert page.evaluate("CRATE.MX.on && CRATE.MX.slots.bass._s === sourceBeforeUndo")


def test_delay_loops_are_connected_only_while_in_use(site, page):
    _mixer(site, page)
    setd = "(v)=>CRATE.TR.set('drums','dly',v/0.008)"
    on = "CRATE.MX.slots.drums._c.dlyOn"
    assert page.evaluate(on) is False                 # delay at zero: the loop is not in the graph
    page.evaluate(f"({setd})(0.3)"); assert page.evaluate(on) is True
    page.evaluate(f"({setd})(0)");   assert page.evaluate(on) is True    # echoes die away first
    page.wait_for_timeout(2000); page.evaluate(f"({setd})(0.2)")          # raised again inside the 4 s
    page.wait_for_timeout(3000); assert page.evaluate(on) is True
    page.evaluate(f"({setd})(0)"); page.wait_for_timeout(4400)
    assert page.evaluate(on) is False


def test_a_busy_page_does_not_make_drums_late(page):
    _drums(page, ("Kick",))
    page.evaluate("CRATE.PROJ.bpm=220;SK.lanes[0].pads[0].steps.fill(1);CRATE.drawSK()")
    page.evaluate("document.getElementById('skplay').click()")
    page.wait_for_timeout(700)
    page.evaluate("(()=>{const e=performance.now()+190;while(performance.now()<e);})()")  # the page blocks for 190 ms
    page.wait_for_timeout(500)
    late = page.evaluate("Math.max(...[...SK.lanes[0].live.values()].map(q=>q.src._t-q.t))")
    page.evaluate("document.getElementById('skplay').click()")
    assert late < 0.002, late  # every hit was scheduled before its time


def test_a_step_switched_on_just_ahead_still_sounds_this_pass(page):
    _drums(page, ("Kick",))
    page.evaluate("CRATE.PROJ.bpm=200;SK.lanes[0].pads[0].steps.fill(0);CRATE.drawSK()")
    page.evaluate("document.getElementById('skplay').click()")
    page.wait_for_timeout(1000)
    res = page.evaluate("""(async()=>{const l=SK.lanes[0],st=CRATE.barLen()/16,ac=l.g.context,j=Math.ceil((ac.currentTime+0.05-SK.start)/st)%16;
        document.querySelector(`[data-dstep="0:0:${j}"]`).click();const t0=ac.currentTime;await new Promise(r=>setTimeout(r,400));
        const q=l.live.get('0:'+j);return q?q.t-t0:null})()""")
    page.evaluate("document.getElementById('skplay').click()")
    assert res is not None and 0.03 < res < 0.25, res  # 50 to 125 ms ahead when clicked: inside the scheduled window


def test_restarting_playback_keeps_one_animation_loop(page):
    _drums(page, ("Kick",))
    page.evaluate("document.getElementById('skplay').click()")
    page.wait_for_timeout(300)
    page.evaluate("for(let k=0;k<3;k++){CRATE.skStop();CRATE.skPlay()}")  # stop and play inside one frame, three times
    n = page.evaluate("""(async()=>{const a=CRATE.perf.anim;for(let k=0;k<30;k++)await new Promise(r=>requestAnimationFrame(r));return CRATE.perf.anim-a})()""")
    page.evaluate("CRATE.skStop()")
    assert 28 <= n <= 33, n  # one loop: one call a frame


def test_waveforms_are_computed_once_and_drags_draw_once_a_frame(page):
    i = idx(page, "s[F.cat]!=='Percussion'")
    page.evaluate(f"CRATE.skAdd({i})")
    page.wait_for_function("SK.lanes[0]&&SK.lanes[0].state==='ok'&&document.querySelector('[data-skw=\"0\"]')", timeout=60000)
    a = page.evaluate("CRATE.perf.peaks")
    assert a >= 1
    page.evaluate("""() => {
        window.waveCanvas = document.querySelector('[data-skw="0"]');
        window.waveBase = waveCanvas._base;
        window.waveWidth = waveCanvas.width;
    }""")
    page.evaluate("for(let k=0;k<5;k++)CRATE.drawSK()")
    assert page.evaluate("CRATE.perf.peaks") == a  # redrawing reuses the peaks
    n = page.evaluate("""(async()=>{const c=document.querySelector('[data-skw="0"]'),r=c.getBoundingClientRect(),y=r.top+r.height/2,
        ev=(t,x)=>new MouseEvent(t,{bubbles:true,clientX:r.left+x,clientY:y,buttons:1});
        c.dispatchEvent(ev('mousedown',40));const a=CRATE.perf.skWave;for(let k=0;k<20;k++)window.dispatchEvent(ev('mousemove',60+k*4));
        for(let k=0;k<2;k++)await new Promise(r=>requestAnimationFrame(r));const n=CRATE.perf.skWave-a;window.dispatchEvent(ev('mouseup',140));return n})()""")
    assert 1 <= n <= 2, n  # twenty mouse moves, one repaint
    page.set_viewport_size({"width": 1100, "height": 1000})
    page.wait_for_function("""() => {
        const c = document.querySelector('[data-skw="0"]');
        return c.width !== waveWidth && c.width === Math.floor(c.clientWidth * devicePixelRatio);
    }""", timeout=3000)
    b = page.evaluate("CRATE.perf.peaks")
    page.evaluate("CRATE.drawSK()")
    assert page.evaluate("CRATE.perf.peaks") == b and b - a == 1  # a new width is computed once
    assert page.evaluate("document.querySelector('[data-skw=\"0\"]')===waveCanvas&&waveCanvas._base===waveBase")


def test_wav_export_bytes(page):
    r = page.evaluate("""(async()=>{const b=new AudioBuffer({numberOfChannels:1,length:5,sampleRate:44100});b.getChannelData(0).set([0,1,-1,0.5,2]);
        const u=CRATE.wavBytes(b),v=new DataView(u.buffer,u.byteOffset),s=[];for(let k=0;k<5;k++)s.push(v.getInt16(44+k*4,true),v.getInt16(46+k*4,true));
        let bin='';u.forEach(x=>bin+=String.fromCharCode(x));
        return {len:u.length,riff:String.fromCharCode(...u.subarray(0,4)),ch:v.getUint16(22,true),sr:v.getUint32(24,true),bits:v.getUint16(34,true),
                data:v.getUint32(40,true),s,same:(await CRATE.wavB64(b))===btoa(bin)}})()""")
    assert r == {"len": 64, "riff": "RIFF", "ch": 2, "sr": 44100, "bits": 16, "data": 20,
                 "s": [0, 0, 32767, 32767, -32767, -32767, 16383, 16383, 32767, 32767], "same": True}


def _lane(page):
    i = idx(page, "s[F.cat]!=='Percussion'")
    page.evaluate(f"CRATE.skAdd({i})")
    page.wait_for_function("SK.lanes[0]&&SK.lanes[0].state==='ok'", timeout=60000)


def test_quick_tempo_changes_reload_each_lane_once(page):
    _lane(page)
    page.evaluate("document.getElementById('skplay').click()")
    page.wait_for_timeout(300)
    urls = []
    page.on("request", lambda r: urls.append(r.url) if "api/conform?" in r.url else None)
    page.evaluate("(()=>{const b=CRATE.PROJ.bpm;CRATE.setProj({bpm:b+1});CRATE.setProj({bpm:b+2});CRATE.setProj({bpm:b+3})})()")
    assert page.evaluate("SK.lanes[0].state") == "loading" and not page.evaluate("SK.playing")
    page.wait_for_function("SK.lanes[0].state==='ok'&&SK.playing", timeout=60000)
    page.wait_for_timeout(500)
    bpm = page.evaluate("String(CRATE.PROJ.bpm)")
    page.evaluate("CRATE.skStop()")
    assert len(urls) == 1 and urls[0].endswith("bpm=" + bpm), urls  # one render, at the last tempo; playing again


def test_a_superseded_load_does_not_fail_the_lane(page):
    _lane(page)
    state = page.evaluate("(async()=>{const l=SK.lanes[0];await Promise.all([CRATE.skLoad(l),CRATE.skLoad(l)]);return l.state})()")
    assert state == "ok"


def test_galaxy_repaints_once_a_frame(page):
    page.evaluate("document.getElementById('tabG').click()")
    page.wait_for_function("document.getElementById('gll')&&!/loading/.test(document.getElementById('gll').textContent)", timeout=60000)
    if "unavailable" in page.evaluate("document.getElementById('gll').textContent"):
        pytest.skip("no galaxy map in this library")
    n = page.evaluate("""(async()=>{const c=document.getElementById('galc'),r=c.getBoundingClientRect();
        await new Promise(q=>requestAnimationFrame(q));const a=CRATE.perf.gal;
        for(let k=0;k<30;k++)c.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:r.left+50+k*5,clientY:r.top+80}));
        for(let k=0;k<2;k++)await new Promise(q=>requestAnimationFrame(q));return CRATE.perf.gal-a})()""")
    assert 1 <= n <= 2, n


def test_reverb_impulse_is_built_once_and_caches_are_bounded(page):
    r = page.evaluate("""(()=>{const ac=new AudioContext(),a=CRATE.perf.ir,n=[1,2,3].map(()=>CRATE.padReverb(ac));
        const m=CRATE.lruMap(2);m.set('a',1);m.set('b',2);m.get('a');m.set('c',3);
        return {built:CRATE.perf.ir-a,nodes:n.every(x=>x instanceof ConvolverNode&&Math.abs(x.buffer.duration-3)<0.01),shared:n[0].buffer===n[1].buffer,
                keys:['a','b','c'].map(k=>m.has(k)),size:m.size}})()""")
    assert r == {"built": 1, "nodes": True, "shared": True, "keys": [True, False, True], "size": 2}


def test_a_swung_step_enabled_by_wheel_sounds_once_before_the_next_pass(page):
    _drums(page, ("Kick",))
    page.evaluate("CRATE.PROJ.bpm=120;SK.lanes[0].swing=0.6;SK.lanes[0].pads[0].steps.fill(0);CRATE.drawSK();CRATE.skPlay()")
    result = page.evaluate("""(async()=>{
        const l=SK.lanes[0],ac=l.g.context,st=CRATE.barLen()/16;
        const abs=Math.ceil((ac.currentTime+0.18-SK.start)/st)|1,j=abs%16,grid=SK.start+abs*st;
        while(ac.currentTime<grid+0.015)await new Promise(r=>setTimeout(r,4));
        const step=document.querySelector(`[data-dstep="0:0:${j}"]`);
        const wheel=dy=>step.dispatchEvent(new WheelEvent('wheel',{deltaY:dy,bubbles:true,cancelable:true}));
        wheel(-1);
        const hit=l.live.get('0:'+j);
        if(!hit)return null;
        const lead=hit.t-ac.currentTime,stop=hit.src.stop.bind(hit.src);
        let cancelled=false;
        hit.src.stop=()=>{cancelled=true;stop()};
        wheel(1);wheel(-1);
        return {lead,cancelled,replaced:l.live.get('0:'+j).src!==hit.src}
    })()""")
    page.evaluate("CRATE.skStop()")
    assert result is not None and 0.01 < result["lead"] < 0.075, result
    assert result["cancelled"] and result["replaced"], result


def test_a_tempo_reload_waits_for_a_lanes_replacement_request(page):
    _lane(page)
    page.evaluate("CRATE.skPlay()")
    pattern = "**/api/conform?*"
    pending = []
    page.route(pattern, lambda route: pending.append(route))
    with page.expect_request(pattern):
        page.evaluate("CRATE.setProj({bpm:CRATE.PROJ.bpm+1})")
    with page.expect_request(pattern):
        page.evaluate("void CRATE.skLoad(SK.lanes[0])")
    page.wait_for_timeout(100)
    resumed_early = page.evaluate("SK.playing")
    pending[0].abort()
    pending[1].continue_()
    page.wait_for_function("SK.lanes[0].state==='ok'&&SK.playing", timeout=60000)
    page.evaluate("CRATE.skStop()")
    assert not resumed_early


def test_space_starts_and_stops_the_mashup(site, page):
    """Space is play / stop on the Mashup tab, whatever control was used last. In a text box it types a space."""
    _mixer(site, page)
    on = "CRATE.MX.on"
    assert page.evaluate(on) is True
    page.keyboard.press("Space"); assert page.evaluate(on) is False
    assert page.inner_text("#mxplay") == "▶ play"
    page.keyboard.press("Space"); assert page.evaluate(on) is True
    page.focus("#mxplay"); page.keyboard.press("Space")                  # on the button itself: once, not twice
    assert page.evaluate(on) is False
    part = "[CRATE.MX.slots.drums.track,CRATE.MX.slots.drums.bar0]"
    before = page.evaluate(part)
    page.focus('[data-mxroll="drums"]'); page.keyboard.press("Space")    # on a die: plays, deals nothing
    page.wait_for_timeout(300)
    assert page.evaluate(on) is True and page.evaluate(part) == before
    page.focus("#mxmaster"); page.keyboard.press("Space")                # on a switch: the switch stays as it was
    assert page.evaluate(on) is False and page.is_checked("#mxmaster")
    page.focus("#mxkey"); page.keyboard.press("Space")
    assert page.evaluate(on) is True
    page.focus("#mxbpm"); page.keyboard.press("Space")                   # typing: not a transport key
    assert page.evaluate(on) is True
    page.click("#tabS"); page.keyboard.press("Space")                    # another tab: the mashup is left alone
    assert page.evaluate(on) is True


def test_space_starts_and_stops_the_strip(site, page):
    _strip(site, page)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    page.keyboard.press("Space"); assert page.evaluate("CRATE.PB.playing") is False
    page.keyboard.press("Space"); assert page.evaluate("CRATE.PB.playing") is True


def test_the_die_sits_before_the_song_and_stands_out(site, page):
    _mixer(site, page)
    page.set_viewport_size({"width": 1440, "height": 900})
    for slot in ("drums", "bass", "vocals", "other"):
        row = f'[data-mxrow="{slot}"] .trh'
        src, die, back = _box(page, f"{row} .mxsrc"), _box(page, f"{row} [data-mxroll]"), _box(page, f'{row} [data-mxhist="{slot}:-1"]')
        bars = _box(page, f"{row} .trbars")
        fwd = _box(page, f'{row} [data-mxhist="{slot}:1"]')
        assert 0 <= src["l"] - fwd["r"] <= 14, (slot, src, fwd)             # straight before the song's text (a name can't move it)
        assert die["r"] <= back["l"] and src["r"] <= bars["l"], (slot, die, back, bars)
        assert die["r"] - die["l"] > back["r"] - back["l"] and die["b"] - die["t"] <= 24, (slot, die, back)   # a little larger, not tall
        icon = _box(page, f"{row} [data-mxroll] svg")
        assert abs(icon["r"] - icon["l"] - 16) < 0.5 and abs(icon["b"] - icon["t"] - 16) < 0.5, (slot, icon)       # and upright
    assert page.evaluate("getComputedStyle(document.querySelector('[data-mxroll=\"drums\"]')).color"
                         "===getComputedStyle(document.querySelector('#mxplay.on')).backgroundColor")   # in the accent colour


GLUE_AUDIO = """async () => {
  const BL = BLEND, out = {}, db = x => 20 * Math.log10(x + 1e-12);
  const rms = (d, a, b) => { let s = 0; for (let i = Math.round(a); i < Math.round(b); i++) s += d[i] * d[i]; return Math.sqrt(s / (b - a)); };
  const O = { fx: false, on: true, bar: 2, DT: { '1/8': 1 / 8 }, duck: { on: false, ddb: 0 } };   // no effects, no ducks: the group alone
  const buffer = (c, fill) => { const b = c.createBuffer(1, c.length, c.sampleRate); fill(b.getChannelData(0), c.sampleRate); return b; };
  const click = at => (d, sr) => { d[Math.round(at * sr)] = 0.05; };
  const tone = (f, a) => (d, sr) => { for (let i = 0; i < d.length; i++) d[i] = a * Math.sin(2 * Math.PI * f * i / sr); };
  // a kit as the server gives it: a decaying 100 Hz hit every half second, at 0.08 RMS, its peaks held at -8 dBFS
  const kit = (d, sr) => { for (let i = 0; i < d.length; i++) { const t = (i / sr) % 0.5; d[i] = Math.sin(2 * Math.PI * 100 * t) * Math.exp(-t / 0.05); }
    const g = 0.08 / rms(d, 0, d.length); for (let i = 0; i < d.length; i++) d[i] = Math.max(-0.398, Math.min(0.398, d[i] * g)); };
  // the mixer's own output on an offline context. parts: [role, fill]; -> the mix
  const mix = async (parts, glue, SR = 44100, secs = 4) => {
    const c = new OfflineAudioContext(1, secs * SR, SR), MX = { glue: { on: glue } }; BL.out(MX, c);
    await MX.bus.g.ready;
    for (const [role, fill] of parts) { const ch = BL.mkChain(c, MX.master, MX.bus);
      BL.applyChain(ch, BL.mixOf({ db: 0 }, role, O), 0);
      const s = c.createBufferSource(); s.buffer = buffer(c, fill); s.connect(ch.in); s.start(0); }
    return (await c.startRendering()).getChannelData(0); };
  // 1. timing: a drum click and a bass click a tenth of a second apart stay a tenth of a second apart
  const peakAt = (y, a, b) => { let k = Math.round(a); for (let i = k; i < Math.round(b); i++) if (Math.abs(y[i]) > Math.abs(y[k])) k = i; return k; };
  for (const SR of [44100, 48000]) for (const glue of [true, false]) {
    const y = await mix([['drums', click(0.1)], ['bass', click(0.2)]], glue, SR, 1);
    const d = peakAt(y, 0, 0.15 * SR), b = peakAt(y, 0.15 * SR, SR), k = SR + (glue ? 'on' : 'off');
    out['gap' + k] = (b - d) - 0.1 * SR; out['late' + k] = d - 0.1 * SR; }
  // 2. how much it takes off, in 10 ms steps over the last two seconds
  const taken = async parts => { const on = await mix(parts, true), off = await mix(parts, false), w = 441; let most = -99, least = 99;
    for (let i = 2 * 44100; i + w < on.length; i += w) { const a = rms(off, i, i + w); if (db(a) < -40) continue;
      const r = db(a) - db(rms(on, i, i + w)); most = Math.max(most, r); least = Math.min(least, r); }
    return { most, least }; };
  out.kit = await taken([['drums', kit]]);
  out.pair = await taken([['drums', kit], ['tops', kit]]);              // Tops go through the same compressor
  // 3. levels: a quiet drum is not raised, a loud one is held, nothing else is touched
  const lv = async (role, fill, glue) => db(rms(await mix([[role, fill]], glue), 2 * 44100, 4 * 44100));
  const change = async (role, fill) => await lv(role, fill, true) - await lv(role, fill, false);
  out.quiet = await change('drums', tone(1000, 0.01)); out.loud = await change('drums', tone(200, 0.5));
  for (const r of ['bass', 'vocals', 'other', 'oneshot']) out[r] = await change(r, tone(200, 0.5));
  // 4. before the make-up is measured, a failed measurement, a role that changes, and chains that are not on the group
  { const c = new OfflineAudioContext(1, 44100, 44100), MX = {}; BL.out(MX, c); const g = MX.bus.g;
    out.early = [g.wet.gain.value, g.dry.gain.value];
    const ch = BL.mkChain(c, MX.master, MX.bus), seen = [];
    for (const role of ['drums', 'other', 'tops', 'bass']) { BL.applyChain(ch, BL.mixOf({ db: 0, dly: 0.3 }, role, { ...O, fx: true }), 0); seen.push(ch.grouped); }
    out.moved = seen; ch.drop();
    const own = BL.mkChain(c, c.createGain(), MX.bus); BL.applyChain(own, BL.mixOf({ db: 0 }, 'drums', O), 0); out.own = own.grouped;
    const bare = BL.mkChain(c, c.destination, BL.duckBus(c)); BL.applyChain(bare, BL.mixOf({ db: 0 }, 'drums', O), 0); bare.drop(); out.bare = bare.grouped;
    const failed = BL.drumGroup(c, c.destination, () => Promise.reject(new Error('no probe')));
    await failed.ready; out.failed = [failed.wet.gain.value, failed.dry.gain.value]; }
  // 5. A switch during a fade carries on from that fade's current gain.
  { const sr = 48000, c = new OfflineAudioContext(1, sr, sr);
    const g = BL.drumGroup(c, c.destination); g.set(false); await g.ready;
    const signal = new ConstantSourceNode(c); signal.connect(g.dry); signal.start();
    g.set(true, 0.020); g.set(false, 0.025);
    const dry = (await c.startRendering()).getChannelData(0);
    out.interrupted = [0.022, 0.024, 0.025, 0.027].map(t => dry[Math.round(t * sr)]); }
  return out;
}"""


def test_glue_audio(page):
    """The drum group, measured offline. Drums and Tops are held a little and never raised; nothing else is touched;
    nothing moves in time, with the glue on or off; and the drums play before the make-up gain is known."""
    o = page.evaluate(GLUE_AUDIO)
    for sr, late in ((44100, 264), (48000, 288)):
        for sw in ("on", "off"):
            assert abs(o[f"gap{sr}{sw}"]) <= 1 and abs(o[f"late{sr}{sw}"] - late) <= 1, (sr, sw, o)
    assert 0.3 < o["kit"]["most"] < 2.5 and o["kit"]["least"] > -0.2, o["kit"]   # light, and never louder
    assert o["pair"]["most"] > o["kit"]["most"] + 0.5
    assert abs(o["quiet"]) < 0.3 and o["loud"] < -1.5                             # no make-up gain; a loud tone is held
    assert all(abs(o[r]) < 0.05 for r in ("bass", "vocals", "other", "oneshot"))
    assert o["early"] == [0, 1] and o["failed"] == [0, 1]
    assert o["moved"] == [True, False, True, False] and o["own"] is False and o["bare"] is False
    assert o["interrupted"] == pytest.approx([0.8, 0.6, 0.5, 0.6], abs=0.002)


def test_glue_is_on_by_default_switches_off_and_is_kept(site, page):
    page.evaluate("""() => {
        const render = OfflineAudioContext.prototype.startRendering;
        const probe = new Promise(resolve => { window.releaseGlueProbe = resolve; });
        OfflineAudioContext.prototype.startRendering = function () {
            if (this.length === 48000 && this.sampleRate === 48000) return probe.then(() => render.call(this));
            return render.call(this);
        };
    }""")
    _kits(site); _mixer(site, page); _roll(page, "drums", 904); _roll(page, "tops", 905)
    assert page.locator(".mxmaster:has(#mxmaster) + .mxmaster #mxglue").count() == 1
    assert page.is_checked("#mxglue")
    page.wait_for_function("(()=>{const g=CRATE.MX.bus&&CRATE.MX.bus.g,c=id=>CRATE.MX.slots[id]._c;return g&&g.on&&['drums','tops'].every(id=>c(id)&&c(id).grouped)&&['bass','vocals','other'].every(id=>c(id)&&!c(id).grouped)})()")
    assert page.inner_text("#mxglgr") == ""
    page.evaluate("releaseGlueProbe()")
    page.wait_for_function("CRATE.MX.bus.g.wet.gain.value>0.5&&CRATE.MX.bus.g.dry.gain.value<0.01")   # the make-up is measured and taken out (about 0.67)
    page.wait_for_function(r"/^-?\d+\.\d dB$/.test(document.getElementById('mxglgr').textContent)")
    with_glue = page.evaluate("CRATE.mxSig()")
    assert '"glue"' not in with_glue                                                 # on is not a change: older saves still match
    page.click("#mxfx")                                                              # the glue is not an effect
    page.wait_for_function("CRATE.MX.fx===false&&CRATE.MX.bus.g.on===true&&CRATE.MX.bus.g.wet.gain.value>0.5")
    page.click("#mxfx")
    page.uncheck("#mxglue")
    page.wait_for_function("CRATE.MX.glue.on===false&&CRATE.MX.bus.g.wet.gain.value<0.01&&CRATE.MX.bus.g.dry.gain.value>0.99")
    assert page.inner_text("#mxglgr") == "" and page.evaluate("CRATE.mxSig()") != with_glue
    page.check("#mxglue")
    for s in ("drums", "tops"):                                                      # no drums: nothing to read
        _more(page, s); page.click(f'[data-mxdel="{s}"]'); page.wait_for_function(f"!CRATE.MX.slots['{s}']")
        if s == "drums":
            assert page.inner_text("#mxglgr").endswith(" dB")                        # Tops alone still use the group
    page.wait_for_function("document.getElementById('mxglgr').textContent===''")
    page.uncheck("#mxglue")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&document.getElementById('mxglue')", timeout=30000)
    assert not page.is_checked("#mxglue") and page.evaluate("JSON.parse(localStorage.getItem('dcStems')).glue.on") is False
    for w in (1512, 1280):                                                           # the longer top row still fits
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(200)
        assert page.evaluate("[...document.querySelectorAll('.mxmaster,.mxmaster *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"), w


GDUCK_AUDIO = """async () => {
  const BL = BLEND, SR = 44100, N = 4 * SR, out = {}, db = x => 20 * Math.log10(x + 1e-12);
  const rms = (d, a, b) => { let s = 0; for (let i = Math.round(a); i < Math.round(b); i++) s += d[i] * d[i]; return Math.sqrt(s / (b - a)); };
  const buffer = (c, fill) => { const b = c.createBuffer(1, N, SR); fill(b.getChannelData(0)); return b; };
  // a "drum": a burst of one frequency, len seconds long, every `every` seconds, at the loudness the server gives every part
  const hit = (f, len, every) => d => { for (let i = 0; i < N; i++) { const t = i / SR; d[i] = (t % every) < len ? Math.sin(2 * Math.PI * f * t) : 0; }
    const g = 0.08 / rms(d, 0, N); for (let i = 0; i < N; i++) d[i] *= g; };
  const kick = hit(125, 0.1, 0.5), snare = hit(500, 0.1, 0.5), hat = hit(8000, 0.05, 0.25);
  const sung = d => { for (let i = 0; i < N; i++) d[i] = 0.113 * Math.sin(2 * Math.PI * 500 * i / SR); };   // a held 500 Hz note at 0.08 RMS
  // what is ducked: four steady tones, so each band's level is easy to read
  const TONES = [125, 500, 4000, 8000];
  const bed = d => { for (let i = 0; i < N; i++) { let v = 0; for (const f of TONES) v += 0.03 * Math.sin(2 * Math.PI * f * i / SR); d[i] = v; } };
  const O = { fx: true, bar: 2, DT: { '1/8': 1 / 8 } };
  // one track of this role under these keys ([role, fill, dB, on]); -> that track alone
  const run = async (role, duck, keys) => {
    const c = new OfflineAudioContext(2, N, SR), merge = c.createChannelMerger(2); merge.connect(c.destination);
    const MX = {}; BL.out(MX, c); MX.master.disconnect();
    const outT = c.createGain(), outK = c.createGain(); outT.connect(merge, 0, 0); outK.connect(merge, 0, 1);
    const play = (fill, ch) => { const s = c.createBufferSource(); s.buffer = buffer(c, fill); s.connect(ch.in); s.start(0); };
    const ct = BL.mkChain(c, outT, MX.bus);
    BL.applyChain(ct, BL.mixOf({ db: 0 }, role, { ...O, on: true, duck }), 0); play(bed, ct);
    for (const [r, fill, level = 0, on = true] of keys) { const ck = BL.mkChain(c, outK, MX.bus);
      BL.applyChain(ck, BL.mixOf({ db: level }, r, { ...O, on }), 0); play(fill, ck); }
    return (await c.startRendering()).getChannelData(0); };
  const band = async (data, f0) => { const c = new OfflineAudioContext(1, data.length, SR), b = c.createBuffer(1, data.length, SR); b.getChannelData(0).set(data);
    const f = c.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = f0; f.Q.value = 4;
    const s = c.createBufferSource(); s.buffer = b; s.connect(f); f.connect(c.destination); s.start(0);
    return (await c.startRendering()).getChannelData(0); };
  const ref = {}, flat = await run('other', { on: false }, []);
  for (const f of TONES) ref[f] = await band(flat, f);
  // the dip at f over a window counted from the hit that starts at 2 s (every window is whole cycles of 125 Hz)
  const dip = async (y, f, a, b) => db(rms(await band(y, f), (2 + a) * SR, (2 + b) * SR)) - db(rms(ref[f], (2 + a) * SR, (2 + b) * SR));
  const EARLY = [0.016, 0.04], HELD = [0.052, 0.1], SOON = [0.16, 0.2], REST = [0.3, 0.46], HAT = [0.02, 0.048];
  const D12 = { on: true, db: 0, ddb: 12 }, K = [['drums', kick]];
  const held = async (role, duck, keys, f = 125) => dip(await run(role, duck, keys), f, ...HELD);
  { const y = await run('other', D12, K);
    out.kick = { early: await dip(y, 125, ...EARLY), held: await dip(y, 125, ...HELD), soon: await dip(y, 125, ...SOON), rest: await dip(y, 125, ...REST),
      top: await dip(y, 4000, ...HELD) }; }
  out.first = await held('other', undefined, K);                        // no setting yet: on, 2 dB
  out.off = await held('other', { on: false, db: 0, ddb: 12 }, K);
  out.zero = await held('other', { on: true, db: 0, ddb: 0 }, K);
  out.muted = await held('other', D12, [['drums', kick, 0, false]]);
  out.quiet = await held('other', D12, [['drums', kick, -18]]);
  out.two = await held('other', D12, [['drums', kick], ['drums', kick]]);
  { const y = await run('other', D12, [['tops', hat]]);                // hats on a Tops track: Other's top gives way, its lows do not
    out.hat = { top: await dip(y, 8000, ...HAT), low: await dip(y, 125, ...HAT) }; }
  { const y = await run('other', { on: true, db: 6, ddb: 6 }, [['vocals', sung], ['drums', snare]]);   // a snare on a sung note: the dips add
    out.both = { hit: await dip(y, 500, ...HELD), between: await dip(y, 500, ...REST) }; }
  for (const r of ['drums', 'tops', 'bass', 'vocals', 'oneshot']) out[r] = await held(r, D12, K);
  // one chain, its track's role and its Duck changed
  { const c = new OfflineAudioContext(1, SR, SR), MX = {}; BL.out(MX, c); const ch = BL.mkChain(c, c.destination, MX.bus), seen = [];
    const set = (role, duck) => { BL.applyChain(ch, BL.mixOf({ db: 0 }, role, { ...O, on: true, duck }), 0); seen.push([ch.ducked, ch.vducked, ch.vbanded, ch.gbanded]); };
    set('bass'); set('other'); set('tops'); set('other', { on: true, db: 0, ddb: 2 }); set('other', { on: true, db: 3, ddb: 0 }); set('other', { on: false, db: 3, ddb: 2 });
    out.switched = seen; ch.drop(); }
  // a chain on a bus that has no drum bus
  { const c = new OfflineAudioContext(1, SR, SR), ch = BL.mkChain(c, c.destination, BL.duckBus(c));
    BL.applyChain(ch, BL.mixOf({ db: 0 }, 'other', { ...O, on: true }), 0); ch.drop(); out.bare = ch.gbanded; }
  return out;
}"""


def test_drum_duck_audio(page):
    """Other under the drums, measured offline. It gives way where the drums are, by close to its amount, quickly,
    and is back quickly; the dips add to the vocals'; nothing else is ducked by the drums."""
    o = page.evaluate(GDUCK_AUDIO)
    k = o["kick"]
    assert -15.0 < k["held"] < -8.0 and k["top"] > -1.0                # at 12 dB: down at 125 Hz, 4 kHz left alone
    assert k["early"] < -4.0                                           # quick attack: well on its way within 40 ms
    assert k["soon"] > -1.5 and k["rest"] > -0.5                       # quick release: back within 100 ms of the hit's end
    assert -3.0 < o["first"] < -1.2                                    # at 2 dB, the amount it starts with
    assert o["off"] > -0.1 and o["zero"] > -0.1 and o["muted"] > -0.1
    assert o["quiet"] > k["held"] + 3                                  # a quieter kit ducks less
    assert o["two"] > k["held"] - 2.0                                  # two kits: hardly deeper than one
    assert o["hat"]["top"] < -6.0 and o["hat"]["low"] > -1.0           # Tops feed it too, and it is by frequency
    b = o["both"]                                                      # 6 dB each: the vocal alone between hits, both on a hit
    assert -9.0 < b["between"] < -3.0 and -19.0 < b["hit"] < b["between"] - 3.0
    assert all(o[r] > -0.1 for r in ("drums", "tops", "bass", "vocals", "oneshot"))
    F, T = False, True
    assert o["switched"] == [[T, F, F, F], [F, F, T, T], [F, T, F, F], [F, F, F, T], [F, F, T, F], [F, F, F, F]] and o["bare"] is False


def test_drums_duck_other(site, page):
    _kits(site); _mixer(site, page); _roll(page, "drums", 904); _roll(page, "tops", 905)
    assert page.locator('[data-mxduckon="other"]').count() == 1                      # still one switch
    text = page.inner_text('[data-mxrow="other"] [data-dev="duck"]')
    assert "vocals" in text and "drums" in text
    assert all("drums" not in page.inner_text(f'[data-mxrow="{s}"] [data-dev="duck"]') for s in ("tops", "bass"))
    page.wait_for_function("(()=>{const c=id=>CRATE.MX.slots[id]._c;return c('other').gbanded&&c('other').vbanded&&!c('tops').gbanded&&!c('bass').gbanded})()")
    assert page.evaluate("BLEND.gduckDb(CRATE.MX.duck.other)") == 2
    page.click("#mxfx")                                                              # the ducks are not effects
    page.wait_for_function("CRATE.MX.fx===false&&CRATE.MX.slots.other._c.gbanded===true")
    page.click("#mxfx")
    page.fill("#mxname", "room"); page.click("#mxsave")
    page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===1")
    page.click("#mxsave"); page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.evaluate("CRATE.TR.set('other','gduck',5)")
    assert "dirty" in page.get_attribute("#mxsave", "class") and page.evaluate("BLEND.changed()") is True
    assert page.evaluate("BLEND.gduckDb(CRATE.MX.snaps[0].duck.other)") == 2         # the snapshot keeps its own amount
    page.evaluate("CRATE.TR.set('other','gduck',0)")                                 # 0 is off, for the drums alone
    page.wait_for_function("(c=>!c.gbanded&&c.vbanded)(CRATE.MX.slots.other._c)")
    page.evaluate("CRATE.TR.set('other','gduck',5)")
    page.click('[data-mxduckon="other"]')                                            # the one switch turns both off
    page.wait_for_function("(c=>!c.gbanded&&!c.vbanded)(CRATE.MX.slots.other._c)")
    page.click('[data-mxduckon="other"]')
    page.wait_for_function("(c=>c.gbanded&&c.vbanded)(CRATE.MX.slots.other._c)")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.duck.other", timeout=30000)
    assert page.evaluate("CRATE.MX.duck.other") == {"on": True, "db": 3, "ddb": 5}
    for w in (1512, 1280):                                                           # the longer row still fits
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(200)
        assert page.evaluate("[...document.querySelectorAll('.trfx,.trfx *')].every(e=>e.getBoundingClientRect().right<=innerWidth+1)"), w


def test_old_mixes_default_to_drum_duck_and_keep_explicit_settings(site, page):
    _old_state(site, page, 904)                                                      # v 2, clean, one snapshot
    page.wait_for_function("CRATE.MX.slots.other&&CRATE.MX.slots.other.buf", timeout=60000)
    drum_amount = "(m=>BLEND.gduckDb(m.duck?.other))"
    assert page.evaluate(f"{drum_amount}(CRATE.MX)") == page.evaluate(f"{drum_amount}(CRATE.MX.snaps[0])") == 2
    page.click("#mxplay")
    page.wait_for_function("CRATE.MX.slots.other._c")
    assert page.evaluate("CRATE.MX.slots.other._c.gbanded") is True
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).v") == 5
    # An earlier vocal duck keeps its amount. A snapshot with the Duck switch off stays off.
    page.click("#mxclear"); page.click("#mxclear")
    _roll(page, "other", 902); _roll(page, "vocals", 901); _roll(page, "drums", 904)
    page.click("#sncap"); page.wait_for_function("CRATE.MX.snaps.length===1")
    page.fill("#mxname", "four"); page.click("#mxsave")
    page.wait_for_function("CRATE.MX.savedSig===CRATE.mxSig()")
    page.evaluate("""() => { const s = JSON.parse(localStorage.getItem('dcStems')); s.v = 4;
      for (const mix of [s, ...s.snaps]) for (const d of Object.values(mix.duck || {})) delete d.ddb;
      s.snaps[0].duck.other = {on:false, db:6};
      const signature = JSON.parse(CRATE.mxSig(4)); signature.snaps = s.snaps;
      s.savedSig = JSON.stringify(signature); localStorage.setItem('dcStems', JSON.stringify(s)); }""")
    page.reload()
    page.wait_for_function("typeof st!=='undefined'&&st.tab==='M'&&CRATE.MX.slots.other&&CRATE.MX.slots.other.buf", timeout=60000)
    mix = page.evaluate("(m=>[m.vband,m.gband])(BLEND.mixOf(CRATE.MX.slots.other,'other',{on:true,fx:true,bar:2,DT:{},duck:CRATE.MX.duck.other}))")
    assert mix == [3, 2]
    assert page.evaluate("CRATE.MX.snaps[0].duck.other") == {"on": False, "db": 6}
    assert "dirty" not in (page.get_attribute("#mxsave", "class") or "")
    page.click("#mxplay")
    page.wait_for_function("CRATE.MX.slots.other._c?.gbanded")
    page.click('[data-sn="0"]')
    page.wait_for_function("""() => {
        const chain = CRATE.MX.slots.other._c;
        return CRATE.MX.duck.other?.on === false && chain && !chain.vbanded && !chain.gbanded;
    }""")


def test_playback_groups_the_drums_and_ducks_other_under_them(site, page):
    _strip(site, page)
    page.click("#snplay")
    page.wait_for_function("CRATE.PB.on&&CRATE.PB.ready&&CRATE.PB.playing", timeout=90000)
    assert page.evaluate("CRATE.PB.voice('drums','a').chain.grouped") is True        # A's drums, in the group
    assert page.evaluate("CRATE.PB.voice('bass','a').chain.grouped") is False
    assert page.evaluate("CRATE.PB.voice('other','a').chain.gbanded") is True        # A's Other, under the drums
    assert page.evaluate("CRATE.PB.voice('bass','a').chain.ducked") is True          # and the bass's own duck is as it was


def test_the_die_stays_put_when_the_part_changes(site, page):
    """The die comes before the song's name, at the same place on every track, so a new part's longer or shorter
    name can't move it (you can click it again and again without looking)."""
    _mixer(site, page)
    at = lambda: page.evaluate("JSON.stringify(Object.fromEntries([...document.querySelectorAll('[data-mxrow]')].map(r=>[r.dataset.mxrow,Math.round(r.querySelector('[data-mxroll]').getBoundingClientRect().left)])))")
    before = json.loads(at())
    assert len(set(before.values())) == 1, before                # one column of dice down the mixer
    page.evaluate("(()=>{const p=CRATE.MX.slots.vocals;p.artist='An artist with a very long name indeed';p.title='and a title that goes on and on and on';CRATE.MX.slots.bass.artist='X';CRATE.MX.slots.bass.title='Y'})()")
    cur = page.evaluate("CRATE.MX.slots.other.track")
    _roll(page, "other", next(t for t in (901, 902, 903) if t != cur))
    assert json.loads(at()) == before
    assert page.evaluate("document.querySelector('[data-mxrow=\"vocals\"] .trsrc').getBoundingClientRect().left > document.querySelector('[data-mxrow=\"vocals\"] [data-mxroll]').getBoundingClientRect().right")


def test_the_song_search_closes(site, page):
    """Choose the song (under ⋯) opens a search; ✕, Esc from anywhere, or a click elsewhere puts it away again."""
    _mixer(site, page)
    def open_():
        page.click('[data-mxrow="bass"] [data-trmore]'); page.click('[data-mxrow="bass"] .trmenu [data-mxfind]')
        page.wait_for_selector(".mxfind #mxq")
    open_(); page.click(".mxfind [data-mxfindx]")
    assert page.locator(".mxfind").count() == 0
    open_(); page.locator("#mxsave").focus(); page.keyboard.press("Escape")
    assert page.locator(".mxfind").count() == 0
    open_(); page.click('[data-mxrow="drums"] .trname')
    page.wait_for_function("!document.querySelector('.mxfind')")
    open_(); page.fill("#mxq", "a")                                 # typing in it and clicking a result still work
    assert page.locator(".mxfind").count() == 1
    track = page.evaluate("+document.querySelector('.mxfind [data-mxsong]').dataset.mxsong.split(':')[1]")
    page.click(".mxfind [data-mxsong]")
    page.wait_for_function(f"CRATE.MX.slots.bass.track==={track}&&!document.querySelector('.mxfind')", timeout=120000)


def test_tracks_open_on_their_loops_and_remember_the_view(site, page):
    """Loops is the view tracks open in; Whole song, once chosen, is kept: to the play strip and back, and after a
    reload."""
    _mixer(site, page)
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.TR.has(s)&&CRATE.MX.slots[s]._viewMode)", timeout=20000)
    modes = lambda: page.evaluate("['drums','bass','vocals','other'].map(s=>CRATE.MX.slots[s]._viewMode)")
    pressed = lambda: page.evaluate("[...document.querySelectorAll('#trview button')].filter(b=>b.getAttribute('aria-pressed')==='true').map(b=>b.dataset.trview)")
    assert modes() == ["loop"] * 4 and pressed() == ["loop"]
    page.click('#trview [data-trview="song"]')
    page.wait_for_function("CRATE.MX.slots.drums._viewMode==='song'")
    assert page.evaluate("localStorage.getItem('dcStemsView')") == "song"
    page.reload(); page.click("#tabM"); page.wait_for_selector("#trview")
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.TR.has(s)&&CRATE.MX.slots[s]._viewMode==='song')", timeout=120000)
    assert pressed() == ["song"]


def test_new_starts_a_fresh_mashup(site, page):
    """＋ new: an empty slate, nothing dealt; it asks first when there is unsaved work, in place."""
    _mixer(site, page)
    page.fill("#mxname", "keeper"); page.dispatch_event("#mxname", "input")
    page.click("#mxnew")
    assert page.inner_text("#mxnew") == "sure?" and page.evaluate("CRATE.MX.name") == "keeper"
    page.click("#mxnew")
    page.wait_for_function("CRATE.MX.name===''")
    page.wait_for_timeout(1500)
    assert page.evaluate("Object.keys(CRATE.MX.slots).length") == 0                 # nothing is dealt
    assert page.evaluate("CRATE.MX.snaps.length") == 0 and page.inner_text("#mxnew").strip() == "＋ new"


def test_a_stem_part_becomes_a_one_shot(site, page):
    """⋯ → Play it as a one-shot: the same audio, now placed on steps of a cycle (once, then a rest), with the track's
    mix settings; ↶ brings the loop back."""
    _mixer(site, page)
    was = page.evaluate("(p=>({track:p.track,bar0:p.bar0,n:p.n,dur:p.buf.duration,db:p.db,artist:p.artist}))(CRATE.MX.slots.vocals)")
    page.click('[data-mxrow="vocals"] [data-trmore]'); page.click('[data-mxrow="vocals"] .trmenu [data-mxshot]')
    page.wait_for_function("CRATE.MX.roles.vocals==='oneshot'&&CRATE.MX.slots.vocals.buf&&!CRATE.MX.slots.vocals._loading", timeout=120000)
    p = page.evaluate("(p=>({sample:p.sample,n:p.n,steps:p.steps,dur:p.buf.duration,db:p.db,artist:p.artist}))(CRATE.MX.slots.vocals)")
    assert p["sample"].startswith(f"stem:{was['track']}:vocals:{was['bar0']}:{was['n']}:")
    assert abs(p["dur"] - was["dur"]) < 0.01 and p["steps"] == [0] and p["n"] == min(8, 2 * was["n"])
    assert p["db"] == was["db"] and p["artist"] == was["artist"]
    assert page.locator('[data-mxrow="vocals"] .mxsteps .mxst.on').count() == 1          # its step grid, one hit
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.vocals.sample") == p["sample"]
    # the tempo changes: it is rendered again at the new tempo (it is a part, not a fixed sample)
    page.fill("#mxbpm", "110"); page.dispatch_event("#mxbpm", "change")
    page.wait_for_function(f"Math.abs(CRATE.MX.slots.vocals.buf.duration-{was['dur'] * 100 / 110})<0.02", timeout=120000)
    page.click('[data-mxhist="vocals:-1"]')
    page.wait_for_function(f"CRATE.MX.roles.vocals==='vocals'&&CRATE.MX.slots.vocals.track==={was['track']}&&CRATE.MX.slots.vocals.buf", timeout=120000)


def test_one_shot_plays_backwards_and_in_part(site, page):
    """◀ reverse plays the piece backwards; ⇧-click on a hit makes it play the first half, a quarter, then all again."""
    _mixer(site, page)
    sid = _one_shot(page)
    page.wait_for_function(f"!!CRATE.MX.slots['{sid}'].buf")
    step = page.evaluate(f"CRATE.MX.slots['{sid}'].steps[0]")
    sel = f'[data-mxstep="{sid}:{step}"]'
    page.click(sel, modifiers=["Shift"])
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].gate[{step}]") == 0.5 and "g2" in page.get_attribute(sel, "class")
    page.click(sel, modifiers=["Shift"])
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].gate[{step}]") == 0.25 and "g4" in page.get_attribute(sel, "class")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots['%s'].gate['%s']" % (sid, step)) == 0.25
    page.click(sel, modifiers=["Shift"])
    assert page.evaluate(f"Object.keys(CRATE.MX.slots['{sid}'].gate).length") == 0 and page.evaluate(f"CRATE.MX.slots['{sid}'].steps.length") >= 1
    page.click(f'[data-mxrow="{sid}"] [data-mxtrimopen]')
    page.click(f'[data-mxback="{sid}"]')
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].back") is True and "dirty" in page.get_attribute("#mxsave", "class")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots['%s'].back" % sid) is True


def test_a_part_is_spliced_from_pieces(site, page):
    """⋯ → Splice pieces…: the part as pieces of its song, one after the other. Pieces are whole bars unless you ask
    for halves; ⌥-click on the waveform adds the bar under the pointer; moving the loop makes it one stretch again."""
    _mixer(site, page)
    page.click('#trview [data-trview="song"]')
    _calls(page)
    bar = 240 / 100
    page.click('[data-mxrow="vocals"] [data-trmore]'); page.click('[data-mxrow="vocals"] .trmenu [data-mxsplice]')
    page.wait_for_selector('[data-mxsplicebox="vocals"]')
    p0 = page.evaluate("(p=>({bar0:p.bar0,n:p.n}))(CRATE.MX.slots.vocals)")
    assert page.locator('[data-mxsplicebox="vocals"] .mxpc').count() == 1          # it starts as the stretch it was
    page.select_option('[data-mxpcl="vocals:0"]', "1")
    page.wait_for_function(f"(p=>p.cut&&p.cut.length===1&&p.buf&&!p._loading&&Math.abs(p.buf.duration-{bar})<0.02)(CRATE.MX.slots.vocals)", timeout=120000)
    page.click('[data-mxpcadd="vocals"]')
    page.wait_for_function("CRATE.MX.slots.vocals.cut.length===2")
    page.fill('[data-mxpcb="vocals:1"]', "12.5"); page.dispatch_event('[data-mxpcb="vocals:1"]', "change")   # the middle of bar 12
    page.select_option('[data-mxpcl="vocals:1"]', "0.5")
    page.wait_for_function(f"(p=>p.cut.length===2&&p.cut[1][0]===11.5&&p.cut[1][1]===0.5&&p.buf&&!p._loading&&Math.abs(p.buf.duration-{1.5 * bar})<0.02)(CRATE.MX.slots.vocals)", timeout=120000)
    sent = page.evaluate("__calls.filter(c=>c[0]==='api/stems/render'&&c[1].stem==='vocals'&&c[1].cut).pop()[1].cut")
    assert sent == [[p0["bar0"], 1], [11.5, 0.5]]
    assert "2 pieces" in page.inner_text('[data-mxrow="vocals"] .trbars') and "drift" in page.inner_text('[data-mxsplicebox="vocals"]')
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.vocals.cut") == sent
    # what plays, left to right: a block per piece, as wide as its share, named by its bar; the play line runs along it
    blocks = page.evaluate("[...document.querySelectorAll('.mxpcstrip>span')].map(e=>[e.innerText.trim(),Math.round(parseFloat(e.style.width))])")
    assert blocks == [[f"1 bar {p0['bar0'] + 1}", 67], ["2 bar 12.5 · ½ bar", 33]]
    assert page.evaluate("(()=>{const c=document.querySelector('.mxpcstrip canvas');return c.width>100&&c.getContext('2d').getImageData(0,0,c.width,c.height).data.some((v,i)=>i%4===0&&v>150)})()")
    # in the song above, the play line goes through the pieces in turn: it is inside one of them, never between
    inside = page.evaluate("""()=>{const p=CRATE.MX.slots.vocals,s=CRATE.TR.song(p.track,'vocals'),l=parseFloat(document.querySelector('[data-mxwave="vocals"] i').style.left)/100,
      t=p._v[0]+l*(p._v[1]-p._v[0]),bt=x=>{const i=Math.floor(x);return s.bars[i]+(x-i)*(s.bars[i+1]-s.bars[i])};
      return p.cut.some(c=>t>=bt(c[0])-0.05&&t<=bt(c[0]+c[1])+0.05)}""")
    assert inside
    # a crossfade at the joins: asked of the server, kept with the part; the length stays
    page.evaluate("(()=>{const e=document.querySelector('[data-mxpcxf=\"vocals\"]');e.value=60;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))})()")
    page.wait_for_function(f"(p=>p.xf===60&&p.buf&&!p._loading&&p._key.endsWith('~60')&&Math.abs(p.buf.duration-{1.5 * bar})<0.02)(CRATE.MX.slots.vocals)", timeout=120000)
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/render'&&c[1].stem==='vocals'&&c[1].cut).pop()[1].xf") == 60
    assert page.get_attribute('[data-mxpcb="vocals:0"]', "step") == "0.5"          # the arrows step by half a bar
    # ⌥-click on the waveform: the bar under the pointer becomes the next piece
    box = page.locator('[data-mxwave="vocals"]').bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] / 2)
    page.keyboard.down("Alt"); page.mouse.down(); page.mouse.up(); page.keyboard.up("Alt")
    page.wait_for_function(f"(p=>p.cut.length===3&&p.cut[2][1]===1&&Number.isInteger(p.cut[2][0])&&p.buf&&!p._loading&&Math.abs(p.buf.duration-{2.5 * bar})<0.02)(CRATE.MX.slots.vocals)", timeout=120000)
    # a piece played backwards
    page.click('[data-mxpcrev="vocals:2"]')
    page.wait_for_function("(p=>p.cut[2][2]===1&&p.buf&&!p._loading&&p._key.includes('r~60'))(CRATE.MX.slots.vocals)", timeout=120000)
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/render'&&c[1].stem==='vocals'&&c[1].cut).pop()[1].cut[2][2]") == 1
    assert "backwards" in page.inner_text(".mxpcstrip")
    # a piece earlier, a piece out
    third = page.evaluate("CRATE.MX.slots.vocals.cut[2][0]")
    page.click('[data-mxpcup="vocals:2"]')
    page.wait_for_function(f"CRATE.MX.slots.vocals.cut[1][0]==={third}")
    page.click('[data-mxpcx="vocals:2"]')
    page.wait_for_function(f"(p=>p.cut.length===2&&p.buf&&!p._loading&&Math.abs(p.buf.duration-{2 * bar})<0.02)(CRATE.MX.slots.vocals)", timeout=120000)
    # ↶ steps back through it; "one stretch again" drops the splice
    page.click('[data-mxpcoff="vocals"]')
    page.wait_for_function(f"(p=>!p.cut&&p.buf&&!p._loading&&Math.abs(p.buf.duration-{2 * bar})<0.02)(CRATE.MX.slots.vocals)", timeout=120000)
    assert "piece" not in page.inner_text('[data-mxrow="vocals"] .trbars')


def test_pieces_stretch_repeat_rest_and_are_dragged(site, page):
    """A piece can take twice (or half) as long, play several times over, or be a rest; pieces are dragged into another
    order, and so are the tracks."""
    _mixer(site, page)
    _calls(page)
    bar = 240 / 100
    ready = lambda cond: page.wait_for_function(f"(p=>{cond}&&p.buf&&!p._loading)(CRATE.MX.slots.vocals)", timeout=120000)
    page.click('[data-mxrow="vocals"] [data-trmore]'); page.click('[data-mxrow="vocals"] .trmenu [data-mxsplice]')
    b0 = page.evaluate("CRATE.MX.slots.vocals.bar0")
    page.select_option('[data-mxpcl="vocals:0"]', "1"); ready("p.cut&&p.cut.length===1")
    page.select_option('[data-mxpcs="vocals:0"]', "2")                                   # twice as long
    ready(f"p.cut[0][3]===2&&Math.abs(p.buf.duration-{2 * bar})<0.03")
    page.select_option('[data-mxpcn="vocals:0"]', "3")                                   # three times over
    ready(f"p.cut[0][4]===3&&Math.abs(p.buf.duration-{6 * bar})<0.05")
    page.click('[data-mxpcrest="vocals"]')                                               # then a bar of nothing
    ready(f"p.cut.length===2&&p.cut[1][0]===null&&Math.abs(p.buf.duration-{7 * bar})<0.05")
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/render'&&c[1].stem==='vocals'&&c[1].cut).pop()[1].cut") == [[b0, 1, 0, 2, 3], [None, 1]]
    labels = page.evaluate("[...document.querySelectorAll('.mxpcstrip>span')].map(e=>e.innerText.trim())")
    assert labels == [f"1 bar {b0 + 1} · 2× long ×3", "2 rest · 1 bar"]
    # how long it is in all, said against the other tracks (4-bar loops here: 7 bars doesn't line up), with a bar ruler
    said = page.inner_text('[data-mxpclen="vocals"]')
    assert said.startswith("7 bars") and "does not line up" in said and "(4 bars)" in said
    assert page.locator(".mxpcruler>span").count() == 7
    assert "7 bars" in page.inner_text('[data-mxrow="vocals"] .trbars')
    assert page.evaluate("CRATE.MX.slots.vocals.buf.getChannelData(0).slice(-20000,-2000).every(v=>Math.abs(v)<1e-4)")   # the rest is silent
    # drag the rest in front of the piece
    page.drag_and_drop('.mxpcstrip>span:nth-of-type(2)', '.mxpcstrip>span:nth-of-type(1)')
    ready("p.cut[0][0]===null&&p.cut.length===2")
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots.vocals.cut") == [[None, 1], [b0, 1, 0, 2, 3]]
    # tracks: drag one by its name onto another, and it takes that place
    order = page.evaluate("CRATE.MX.order")
    page.drag_and_drop('[data-mxrow="bass"] .trname', '[data-mxrow="drums"]', target_position={"x": 300, "y": 4})
    new = page.evaluate("CRATE.MX.order")
    assert new.index("bass") < new.index("drums") and sorted(new) == sorted(order)
    assert page.evaluate("[...document.querySelectorAll('[data-mxrow]')].map(r=>r.dataset.mxrow)")[:len(new)] == new
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).order") == new


def test_a_snapshot_keeps_the_work_done_on_it(site, page):
    """Work on B, go to A, come back: B has what you did (it used to be dropped unless ↻ was clicked first). Clicking
    the snapshot you are on drops the changes instead; a save keeps them too; and the place survives a reload."""
    _strip(site, page)
    assert page.evaluate("CRATE.MX.snapSel") == 1                                    # on B
    setdb = lambda v: page.evaluate(f"(()=>{{const e=document.querySelector('[data-mxdb=\"bass\"]');e.value={v};e.dispatchEvent(new Event('input',{{bubbles:true}}));e.dispatchEvent(new Event('change',{{bubbles:true}}))}})()")
    setdb(-9)
    _roll(page, "vocals", 903)
    assert page.evaluate("CRATE.MX.snaps[1].slots.bass.db") != -9                    # not yet: only when you move on
    page.click('[data-sn="0"]')
    page.wait_for_function("CRATE.MX.snapSel===0&&CRATE.MX.slots.drums.track===901&&CRATE.MX.slots.drums.buf", timeout=120000)
    assert page.evaluate("[CRATE.MX.snaps[1].slots.bass.db,CRATE.MX.snaps[1].slots.vocals.track]") == [-9, 903]
    assert "kept in snapshot B" in page.inner_text("#toast") and page.locator("#snundo").count() == 0
    page.click('[data-sn="1"]')
    page.wait_for_function("CRATE.MX.snapSel===1&&CRATE.MX.slots.vocals.track===903&&CRATE.MX.slots.vocals.buf&&CRATE.MX.slots.bass.db===-9", timeout=120000)
    # a save keeps the work in the snapshot you are on as well
    setdb(-4)
    page.fill("#mxname", "kept"); page.click("#mxsave")
    page.wait_for_function("!CRATE.MX._saving&&CRATE.MX.savedSig===CRATE.mxSig()", timeout=20000)
    assert page.evaluate("CRATE.MX.snaps[1].slots.bass.db") == -4
    # after a reload you are still on B, so what you do next is kept in it too
    setdb(-6)
    page.reload(); page.click("#tabM"); page.wait_for_selector("#snbar")
    assert page.evaluate("[CRATE.MX.snapSel,CRATE.MX.slots.bass.db,CRATE.MX.snaps[1].slots.bass.db]") == [1, -6, -4]
    # clicking the snapshot you are on drops the changes
    page.click('[data-sn="1"]')
    page.wait_for_function("CRATE.MX.slots.bass.db===-4&&CRATE.MX.slots.bass.buf", timeout=120000)
    assert page.evaluate("CRATE.MX.snaps[1].slots.bass.db") == -4
    # ⌘Z keeps you on the snapshot (it used to leave you on none, so later work was kept nowhere)
    setdb(-7); page.wait_for_timeout(700); setdb(-8)
    page.locator("#mxsave").focus(); page.keyboard.press("Meta+z")
    page.wait_for_function("CRATE.MX.slots.bass.db===-7&&CRATE.MX.snapSel===1", timeout=30000)
    # work that is on no snapshot isn't lost by going to one: it waits under "not in a snapshot"
    page.evaluate("CRATE.MX.snapSel=null")
    setdb(-11)
    page.click('[data-sn="0"]')
    page.wait_for_function("CRATE.MX.snapSel===0&&CRATE.MX.slots.drums.track===901&&CRATE.MX.slots.drums.buf", timeout=120000)
    page.wait_for_selector("#snloose")
    page.reload(); page.click("#tabM"); page.wait_for_selector("#snloose")            # it survives a reload
    page.click("#snloose")
    page.wait_for_function("CRATE.MX.snapSel===null&&CRATE.MX.slots.bass.db===-11&&CRATE.MX.slots.bass.buf&&!document.querySelector('#snloose')", timeout=120000)
    # a saved mashup opens on the snapshot its mixer is: work done next is kept there
    page.click('[data-sn="1"]')
    page.wait_for_function("CRATE.MX.snapSel===1&&CRATE.MX.slots.bass.buf&&!CRATE.MX.slots.bass._loading", timeout=120000)
    page.fill("#mxname", "kept"); page.click("#mxsave")
    page.wait_for_function("!CRATE.MX._saving&&CRATE.MX.savedSig===CRATE.mxSig()", timeout=20000)
    page.evaluate("CRATE.MX.snapSel=null")
    page.select_option("#mxload", "kept")
    page.wait_for_function("CRATE.MX.snapSel===1&&CRATE.MX.slots.bass.buf", timeout=120000)
    page.evaluate("CRATE.mxPlay(false);localStorage.removeItem('dcStems')")


def test_tracks_are_rated_where_they_play(site, page):
    """A one-shot track has ★ and ✕ (the library's favorite and not-for-me); a stem track has 👍 and 👎, which teach
    Mashup's recommendations for that part."""
    _mixer(site, page)
    sent = []
    # (watched, not intercepted: the page reloads your ratings from the server now and then, and must find them there)
    page.on("request", lambda r: sent.append(json.loads(r.post_data)) if r.url.endswith("/api/stems/event") else None)
    page.click('[data-mxpart="bass:1"]')
    page.wait_for_function("CRATE.MX.slots.bass.rated===1")
    assert any(e.get("kind") == "like" and e.get("stem") == "bass" for e in sent)
    page.click('[data-mxpart="bass:-1"]')
    page.wait_for_function("CRATE.MX.slots.bass.rated===-1")
    assert any(e.get("kind") == "dislike" and e.get("stem") == "bass" for e in sent)
    sid = _one_shot(page)
    path = page.evaluate(f"CRATE.MX.slots['{sid}'].sample")
    pj = json.dumps(path)
    for btn, has in (("mxfav", f"FAV.has({pj})"), ("mxnope", f"TASTE.disliked.has({pj})")):   # (another test may have rated it already)
        was = page.evaluate(has)
        page.click(f'[data-{btn}="{sid}"]')
        page.wait_for_function(f"{has}==={'false' if was else 'true'}&&document.querySelector('[data-{btn}=\"{sid}\"]').classList.contains('on')==={'false' if was else 'true'}", timeout=10000)
        page.click(f'[data-{btn}="{sid}"]')
        page.wait_for_function(f"{has}==={'true' if was else 'false'}", timeout=10000)
    assert page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth")   # nothing pushed off the side


def _reco_db(site):
    import sqlite3
    con = sqlite3.connect(site["lib"] / "_data" / "samples.sqlite")
    con.row_factory = sqlite3.Row
    return con


def test_a_deal_is_recorded_and_so_is_what_became_of_it(site, page):
    """Every part dealt has its impression (what else was on offer, each one's chance, the context), and the browser
    reports what became of it with the seconds it was heard: here a re-roll, after a few seconds of listening; a muted
    track hears nothing."""
    from digitalcrate.reco import log as L
    _mixer(site, page)
    outs = []
    page.on("request", lambda r: outs.extend(json.loads(r.post_data)["out"]) if r.url.endswith("/api/stems/outcome") else None)
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.MX.slots[s].imp)", timeout=20000)
    page.click('[data-mxmute="vocals"]')
    old = page.evaluate("({imp:CRATE.MX.slots.bass.imp,track:CRATE.MX.slots.bass.track,bar0:CRATE.MX.slots.bass.bar0,n:CRATE.MX.slots.bass.n})")
    con = _reco_db(site)
    imp = next(i for i in L.impressions(con) if i["id"] == old["imp"])
    con.close()
    assert imp["surface"] == "mashup.dice" and imp["context"]["via"] == "all" and imp["context"]["slot"] == "bass"
    assert imp["chosen"] == ("part", old["track"], "bass", old["bar0"], old["n"])
    assert imp["context"]["bpm"] == 100 and imp["shown"] and imp["policy"]["model"] == "stems.pick"
    assert sum(s["p"] for s in imp["shown"]) + imp["context"]["rest"]["p"] == pytest.approx(1.0)
    t0 = time.time()
    page.wait_for_timeout(3000)
    page.click('[data-mxroll="bass"]')
    page.wait_for_function(f"CRATE.MX.slots.bass.imp&&CRATE.MX.slots.bass.imp!=={old['imp']}", timeout=60000)
    wall = time.time() - t0
    page.wait_for_function("!CRATE.MX.slots.bass._loading", timeout=60000)
    page.wait_for_timeout(700)                                       # (outcomes go out in batches)
    rep = [o for o in outs if o["action"] == "replaced" and o["slot"] == "bass"]
    assert len(rep) == 1 and rep[0]["imp"] == old["imp"] and rep[0]["by"] == "dice"
    assert 2.0 <= rep[0]["secs"] <= wall + 0.5                       # heard, on the audio clock
    assert page.evaluate("Object.entries(CRATE.MX.dw).filter(([k])=>k.startsWith('vocals|')).every(([k,d])=>d.s<0.5)")
    con = _reco_db(site)
    got = L.outcomes(con, imp=old["imp"])
    new = next(i for i in L.impressions(con) if i["id"] == page.evaluate("CRATE.MX.slots.bass.imp"))
    con.close()
    assert [o["action"] for o in got] == ["replaced"] and got[0]["context"]["secs"] == rep[0]["secs"]
    assert new["surface"] == "mashup.dice" and new["context"]["via"] == "dice"
    # an undo brings the part back: neither part is judged (undone / restored, not replaced)
    outs.clear()
    page.evaluate("CRATE.mxUndo(-1)")
    page.wait_for_function(f"CRATE.MX.slots.bass.imp==={old['imp']}", timeout=60000)
    page.wait_for_timeout(700)
    acts = {(o["action"], o["imp"]) for o in outs if o["slot"] == "bass"}
    assert ("undone", new["id"]) in acts and ("restored", old["imp"]) in acts and not any(a == "replaced" for a, _ in acts)
    page.evaluate("CRATE.mxPlay(false);localStorage.removeItem('dcStems')")


def test_saving_twice_records_one_save_per_part(site, page):
    """A re-save of the same combination is no new yes: one save per part per mix, in the old log and the new."""
    _mixer(site, page)
    page.wait_for_function("['drums','bass','vocals','other'].every(s=>CRATE.MX.slots[s].imp)", timeout=20000)
    con = _reco_db(site)
    count = lambda: con.execute("SELECT COUNT(*) FROM stem_events WHERE kind='save'").fetchone()[0]
    n0 = count()
    name = f"twice {time.time():.0f}"
    page.fill("#mxname", name)
    for _ in range(2):
        page.evaluate("CRATE.MX.savedSig=null")
        page.click("#mxsave")
        page.wait_for_function("!CRATE.MX._saving&&CRATE.MX.savedSig===CRATE.mxSig()", timeout=20000)
        assert count() - n0 == 4
    from digitalcrate.stems import _mix_tag
    rows = con.execute("SELECT imp, item FROM reco_outcomes WHERE action='saved' AND json_extract(context,'$.mix')=?",
                       (_mix_tag(name),)).fetchall()
    con.close()
    imps = page.evaluate("['drums','bass','vocals','other'].map(s=>CRATE.MX.slots[s].imp)")
    assert len(rows) == 4 and sorted(r["imp"] for r in rows) == sorted(imps)
    page.evaluate("CRATE.mxPlay(false);localStorage.removeItem('dcStems')")


def test_a_pad_track_holds_a_library_pad(site, page):
    """A Pad track: the dice deals a library pad that fits, held under the whole cycle (one hit, hold on, long fades);
    its search looks through pads; hold can be switched per track."""
    _mixer(site, page)
    n_pads = page.evaluate("S.filter(s=>['Pads & Atmospheres','Strings & Orchestral','Vocal Atmospheres'].includes(s[F.cat])&&s[F.dur]>=1.5&&!s[F.parent]).length")
    if not n_pads:
        pytest.skip("the test library has no pads")
    _calls(page)
    page.select_option("#mxaddrole", "pad"); page.click("#mxadd")
    page.wait_for_function("CRATE.MX.order.some(id=>CRATE.MX.roles[id]==='pad'&&CRATE.MX.slots[id]&&CRATE.MX.slots[id].buf)", timeout=120000)
    sid = page.evaluate("CRATE.MX.order.find(id=>CRATE.MX.roles[id]==='pad')")
    p = page.evaluate(f"(p=>({{hold:p.hold,steps:p.steps,n:p.n,cat:p.cat,fout:p.fout}}))(CRATE.MX.slots['{sid}'])")
    assert p["hold"] is True and p["steps"] == [0] and p["n"] == 4 and p["fout"] >= 100
    assert p["cat"] in ("Pads & Atmospheres", "Strings & Orchestral", "Vocal Atmospheres")
    assert page.evaluate("__calls.filter(c=>c[0]==='api/stems/oneshot').pop()[1].kind") == "pad"
    assert "Pad" in page.inner_text(f'[data-mxrow="{sid}"] .trname')
    assert page.evaluate("JSON.parse(localStorage.getItem('dcStems')).slots['%s'].hold" % sid) is True
    # held: a hit is asked to last the whole cycle (4 bars at 100 bpm), not just the sample's length
    got = page.evaluate(f"""(()=>{{const p=CRATE.MX.slots['{sid}'];let stopAt=null;const mk=AC.createBufferSource.bind(AC);
      AC.createBufferSource=()=>{{const s=mk(),st=s.stop.bind(s),sa=s.start.bind(s);let t0=0;s.start=(w,...a)=>{{t0=w;return sa(w,...a)}};s.stop=w=>{{if(w!=null)stopAt=w-t0;return st(w)}};return s}};
      CRATE.mxPlay(false);CRATE.mxPlay(true);return new Promise(r=>setTimeout(()=>{{AC.createBufferSource=mk;r(stopAt)}},600))}})()""")
    assert got is not None and abs(got - 4 * 2.4) < 0.1
    page.click(f'[data-mxrow="{sid}"] [data-mxtrimopen]')
    page.click(f'[data-mxhold="{sid}"]')
    assert page.evaluate(f"CRATE.MX.slots['{sid}'].hold") is False


def test_best_fits_lists_what_fits_in_order(site, page):
    """⋯ → Best fits…: the parts that fit the harmony best, in order (the dice draws; this lists). A click puts one in,
    and the list stays open to try the next."""
    _mixer(site, page)
    page.click('[data-mxrow="bass"] [data-trmore]'); page.click('[data-mxrow="bass"] .trmenu [data-mxbest]')
    page.wait_for_function("CRATE.MX.best&&!CRATE.MX.best.loading&&CRATE.MX.best.parts.length>0", timeout=60000)
    parts = page.evaluate("CRATE.MX.best.parts.map(p=>[p.track,p.fitp])")
    fits = [f for _, f in parts]
    assert all(f is not None for f in fits) and fits == sorted(fits, reverse=True)      # most harmonious first
    assert len({t for t, _ in parts}) == len(parts)                                      # one entry a song
    playing = page.evaluate("['vocals','other'].map(s=>CRATE.MX.slots[s].track)")
    assert not set(playing) & {t for t, _ in parts}                                      # not a song already in another track
    assert "%" in page.inner_text(".mxbest")
    page.click('[data-mxbestpick="bass:0"]')
    page.wait_for_function(f"CRATE.MX.slots.bass.track==={parts[0][0]}&&CRATE.MX.slots.bass.buf&&!CRATE.MX.slots.bass._loading", timeout=120000)
    assert page.locator(".mxbest").count() == 1
    page.click(".mxbest [data-mxbestx]")
    assert page.locator(".mxbest").count() == 0
    # drums have no harmony: the list says so and is still in order of the overall score
    page.click('[data-mxrow="drums"] [data-trmore]'); page.click('[data-mxrow="drums"] .trmenu [data-mxbest]')
    page.wait_for_function("CRATE.MX.best&&CRATE.MX.best.id==='drums'&&!CRATE.MX.best.loading", timeout=60000)
    assert "no harmony" in page.inner_text(".mxbest")


def test_the_piece_list_keeps_its_place_when_a_piece_changes(site, page):
    """With more pieces than fit, changing the last one doesn't jump the list back to the top."""
    _mixer(site, page)
    page.click('[data-mxrow="vocals"] [data-trmore]'); page.click('[data-mxrow="vocals"] .trmenu [data-mxsplice]')
    page.wait_for_selector('[data-mxsplicebox="vocals"]')
    page.select_option('[data-mxpcl="vocals:0"]', "1")
    for i in range(1, 12):
        page.click('[data-mxpcadd="vocals"]')
        page.wait_for_function(f"CRATE.MX.slots.vocals.cut&&CRATE.MX.slots.vocals.cut.length==={i + 1}")
    box = '[data-mxsplicebox="vocals"] .mxpcs'
    assert page.evaluate(f"(e=>e.scrollHeight>e.clientHeight+40)(document.querySelector('{box}'))")
    page.evaluate(f"(e=>e.scrollTop=e.scrollHeight)(document.querySelector('{box}'))")
    top = page.evaluate(f"document.querySelector('{box}').scrollTop")
    page.select_option('[data-mxpcs="vocals:11"]', "2")
    page.wait_for_function("(CRATE.MX.slots.vocals.cut[11]||[])[3]===2")
    page.wait_for_timeout(300)
    assert abs(page.evaluate(f"document.querySelector('{box}').scrollTop") - top) < 4
