import numpy as np
import pytest

SR = 44100


def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", help="also run the end-to-end pipeline test (loads models)")
    parser.addoption("--ui", action="store_true", help="also run the browser tests (Playwright; builds a throwaway library)")


def pytest_collection_modifyitems(config, items):
    for opt, mark in (("--slow", "slow"), ("--ui", "ui")):
        if config.getoption(opt):
            continue
        skip = pytest.mark.skip(reason=f"run with {opt}")
        for it in items:
            if mark in it.keywords:
                it.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: end-to-end test that loads the separation and CLAP models")
    config.addinivalue_line("markers", "ui: browser test (Playwright) on a throwaway library")


def tone(freqs, secs=4.0, sr=SR):
    """A soft stereo chord: sum of sines with a gentle attack and release."""
    t = np.arange(int(secs * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in np.atleast_1d(freqs)) / len(np.atleast_1d(freqs))
    env = np.minimum(1, t / 0.05) * np.minimum(1, (secs - t) / 0.2)
    y = (0.3 * y * env).astype(np.float32)
    return np.stack([y, y])


@pytest.fixture(autouse=True)
def _reco_live_isolated(tmp_path, monkeypatch):
    """The served models (reco/live.py) never reach a real library from a test: settings in a temporary file, no
    background fits (a test that wants a fit makes one with live.refit on its own database)."""
    from digitalcrate.reco import live
    live.reset()
    monkeypatch.setattr(live, "SETTINGS", tmp_path / "reco_settings.json")
    monkeypatch.setattr(live, "CHECK_EVERY", 1e12)
    monkeypatch.setattr(live, "_con", lambda: (_ for _ in ()).throw(RuntimeError("tests: no library")))
    live._S["checked"] = 1e12
    yield
    live.reset()
