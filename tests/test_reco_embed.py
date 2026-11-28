"""The embedding trial (reco/embed_trial.py), on synthetic audio and a stub embedder (never the real library or a model)."""
import numpy as np
import pytest
import soundfile as sf

from digitalcrate import stems
from digitalcrate.reco import embed_trial as ET
from digitalcrate.reco import eval as E
from digitalcrate.reco.models import taste as T
from test_reco_taste import _library


class Stub:
    """Stands in for a model: a few spectral numbers of the clip, so different audio gives different vectors."""
    name, dim = "stub", 4

    def __init__(self):
        self.calls = 0

    def embed(self, path):
        self.calls += 1
        y = ET.load_clip(path, 16000, min_s=1.0)
        assert len(y) >= 16000 and y.ndim == 1
        S = np.abs(np.fft.rfft(y[:16000]))
        return np.array([S[:200].sum(), S[200:800].sum(), S[800:].sum(), y.std()], np.float32)


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(ET, "STORE", tmp_path / "store")
    for c in (ET._EMB, ET._SPACE, T._LIB):
        c.clear()
    yield tmp_path
    for c in (ET._EMB, ET._SPACE, T._LIB):
        c.clear()


def test_clips_and_a_resumable_pass(clean):
    root = clean / "lib"
    (root / "a").mkdir(parents=True)
    t = np.arange(44100 * 14) / 44100
    names = []
    for k, f in enumerate((110, 440, 1760, 220, 880)):
        y = 0.3 * np.sin(2 * np.pi * f * t[: 44100 * (14 if k == 0 else 1) // (1 if k == 0 else 4)])
        sf.write(root / "a" / f"{k}.wav", np.stack([y, y], 1), 44100)
        names.append(f"a/{k}.wav")
    (root / "a" / "bad.wav").write_bytes(b"not audio")
    long = ET.load_clip(root / "a" / "0.wav", 24000)
    assert len(long) == 24000 * 10  # the middle 10 s
    short = ET.load_clip(root / "a" / "1.wav", 16000, min_s=2.0)
    assert len(short) == 32000 and np.abs(short[-100:]).max() == 0  # padded with silence

    st = Stub()
    r = ET.run("stub", names[:2], root=root, embedder=st, chunk=1, breathe=False, verbose=False)
    assert r["done"] == 2 and st.calls == 2
    r = ET.run("stub", names + ["a/bad.wav"], root=root, embedder=st, chunk=2, breathe=False, verbose=False)
    assert r["done"] == 5 and r["new"] == 3 and r["failed"] == 1 and st.calls == 2 + 4  # resumed; bad one recorded
    r = ET.run("stub", names + ["a/bad.wav"], root=root, embedder=st, chunk=2, breathe=False, verbose=False)
    assert r["new"] == 0 and st.calls == 6  # nothing left, the failure not retried
    paths, X = ET.load("stub")
    assert paths == names and X.shape == (5, 4) and np.isfinite(X).all()
    assert len({tuple(np.round(x, 2)) for x in X}) == 5


def _store_from_clap(con, name, noise=0.0, seed=0):
    """A stored 'embedding' made from the samples' CLAP vectors (plus noise), as a pass would leave it."""
    lib = T.library(con)
    rng = np.random.default_rng(seed)
    X = lib["E"] + noise * rng.normal(size=lib["E"].shape)
    ET._save(name, lib["paths"], X, set())


def test_variants_and_probe_rank_favorites(clean, monkeypatch):
    monkeypatch.setattr(stems, "_emb", lambda track, stem: np.zeros(512, np.float32))
    con, heard, far = _library(clean / "t.sqlite")
    con.close()
    src = E.Source(clean / "t.sqlite")
    try:
        _store_from_clap(src.con, "effnet", noise=0.002)  # a near copy of CLAP: as informative
        _store_from_clap(src.con, "junk", noise=10.0, seed=1)  # noise: carries nothing
        assert set(ET.targets(src.con)) >= set(heard)
        fav = {r[0] for r in src.con.execute("SELECT path FROM favorites")}
        m = src.masked()
        train = E.Train(m, [], E.Fold("song", "all", [], []), "sample_taste")
        items = [("sample", p) for p in heard]
        y = [p in fav for p in heard]
        aucs = {}
        for name, mdl in [("clap", ET.variant_model("clap")), ("swap", ET.variant_model("swap", "effnet")),
                          ("add", ET.variant_model("add", "effnet", k_add=8)),
                          ("add_kernel", ET.variant_model("add", "effnet", k_add=8, kernel_add=True)),
                          ("probe", ET.probe_model("effnet", k=16)), ("probe_junk", ET.probe_model("junk", k=16))]:
            s = mdl.fit(train)(items + [("sample", "gone.wav")], None)
            assert np.isfinite(s[:-1]).all() and np.isnan(s[-1])  # no embedding: NaN, not an error
            aucs[name] = E.auc(y, s[:-1])
        for k in ("clap", "swap", "add", "add_kernel", "probe"):
            assert aucs[k] > 0.8, aucs
        assert aucs["probe_junk"] < aucs["probe"]
        m.close()
        # a fold that hides samples still scores them: the spaces are fixed, whatever the fold's database holds
        hidden = heard[:10]
        ET._SPACE.clear()  # built afresh on the masked database
        m = src.masked({("sample", p) for p in hidden})
        train = E.Train(m, [], E.Fold("song", "hide", [], []), "sample_taste")
        for mdl in (ET.variant_model("swap", "effnet"), ET.probe_model("effnet", k=16)):
            assert np.isfinite(mdl.fit(train)([("sample", p) for p in hidden], None)).all()
        m.close()
    finally:
        src.close()


def test_trial_folds_keep_development_and_confirmation_apart(clean):
    con, heard, far = _library(clean / "t.sqlite")
    con.close()
    src = E.Source(clean / "t.sqlite")
    try:
        dev, conf = ET.TrialTask("dev"), ET.TrialTask("confirm")
        ex = dev.examples(src.con)
        assert {f.seed for f in dev.folds(ex, "song")} == {0}
        assert {f.seed for f in conf.folds(ex, "song")} == {2, 3, 4} and len(conf.folds(ex, "sample")) == 15
        dev.min_pos = conf.min_pos = 2
        fd, fc = [f.name for f in dev.folds(ex, "forward")], [f.name for f in conf.folds(ex, "forward")]
        assert fd and fc and not set(fd) & set(fc)
        assert all(int(n[1:]) % 2 == 1 for n in fd) and all(int(n[1:]) % 2 == 0 for n in fc)
    finally:
        src.close()
