"""Opt-in local assets and a genuine clean, silent application entry."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import wave

import pytest

from gui import startup_audio, styles, theme_art, workflow_art
from gui.startup_integration import local_startup_assets
from main import startup_audio_allowed


def test_opt_in_paths_keep_source_checkout_and_private_pack_separate(tmp_path, monkeypatch):
    monkeypatch.delenv("CET_LOCAL_ASSETS_DIR", raising=False)
    monkeypatch.delenv("CET_COMPANIONS_DIR", raising=False)
    checkout = tmp_path / "checkout"
    assert local_startup_assets(checkout) == checkout / "work/preview/startup-assets"
    media = tmp_path / "personal assets"
    monkeypatch.setenv("CET_LOCAL_ASSETS_DIR", str(media))
    assert local_startup_assets(checkout) == media / "startup-assets"
    assert styles._private_font_dir() == media / "fonts"
    assert theme_art.companion_directory() == media / "companions"
    assert workflow_art.ui_meme_directory() == media / "ui-meme-assets"
    assert not media.exists()


def test_audio_gate_is_explicit_interactive_windows_only(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    kwargs = {"reduced": False, "platform": "win32", "qt_platform": "windows"}
    assert startup_audio_allowed(True, **kwargs)
    assert not startup_audio_allowed(False, **kwargs)
    assert not startup_audio_allowed(True, **(kwargs | {"reduced": True}))
    assert not startup_audio_allowed(True, **(kwargs | {"platform": "linux"}))
    assert not startup_audio_allowed(True, **(kwargs | {"qt_platform": "offscreen"}))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen:tests;windows")
    assert not startup_audio_allowed(True, **kwargs)


def test_verified_local_pcm_does_not_initialize_audio(tmp_path, monkeypatch):
    assets = tmp_path / "startup-assets"
    wav = assets / startup_audio._AUDIO
    wav.parent.mkdir(parents=True)
    pcm = bytes(startup_audio._SAMPLES * 2)
    with wave.open(str(wav), "wb") as w:
        w.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        w.writeframes(pcm)
    contract = tmp_path / "startup_audio_contract.json"
    spec = dict(profile=startup_audio._PROFILE, file=startup_audio._AUDIO,
                native_video_frames=[55, 156], duration_ms=3400, sample_rate=48000,
                samples=163200, channels=1, sha256=sha256(wav.read_bytes()).hexdigest())
    contract.write_text(json.dumps(spec), encoding="utf-8")

    def fake_backend():
        pytest.fail("validation or test attempted to initialize an audio device")

    captured = []
    monkeypatch.setattr(startup_audio, "prepare_async", lambda loader, data: captured.append((loader, data)))
    factory = startup_audio.optional_sound_factory(assets, contract, load_backend=fake_backend)
    assert factory is not None and not captured
    factory.prepare()
    assert captured == [(fake_backend, pcm)]
    spec["file"] = "../outside.wav"
    contract.write_text(json.dumps(spec), encoding="utf-8")
    assert startup_audio.optional_sound_factory(assets, contract, load_backend=fake_backend) is None
    spec["file"] = startup_audio._AUDIO
    spec["sha256"] = "0" * 64
    contract.write_text(json.dumps(spec), encoding="utf-8")
    assert startup_audio.optional_sound_factory(assets, contract, load_backend=fake_backend) is None


def test_actual_audio_worker_calls_only_the_injected_device():
    wrote, stopped = Event(), Event()
    observed = []

    class FakeDevice:
        def dispatch_pcm(self, claim, still_current):
            if claim() and still_current():
                observed.append("write")
                wrote.set()
                return True
            return False

        def stop(self):
            observed.append("stop")
            stopped.set()
            return True

    class FakeDriver:
        def prepare_pcm(self, pcm):
            assert pcm == b"test"
            observed.append("prepare")
            return FakeDevice()

    ticket = startup_audio.prepare_async(FakeDriver, b"test")
    try:
        # Wait for the worker's explicit readiness state, with no native API.
        with ticket._cv:
            assert ticket._cv.wait_for(lambda: ticket._ready, timeout=1)
        assert observed == ["prepare"] and not wrote.is_set()
        assert ticket.play() == "pcm-submit-queued"
        assert wrote.wait(1)
    finally:
        ticket.stop()
    assert stopped.wait(1) and observed == ["prepare", "write", "stop"]


@pytest.mark.parametrize("flag", ["--silent", "--with-startup-audio"])
def test_clean_silent_source_entry(tmp_path, flag):
    _assert_fileless_entry(tmp_path, flag)


@pytest.mark.parametrize("malformed_laugh", [None, [], 7, "not a clip", {"frames": [None, 4]}])
def test_malformed_optional_asset_manifest_still_opens_home(tmp_path, malformed_laugh):
    from PIL import Image

    pack = tmp_path / "local assets"
    assets = pack / "startup-assets"
    assets.mkdir(parents=True)
    Image.new("RGB", (30, 44), "yellow").save(assets / "portrait.png")
    (assets / "startup-v4.json").write_text(json.dumps(
        dict(version=4, portrait="portrait.png", laugh=malformed_laugh)), encoding="utf-8")
    _assert_fileless_entry(tmp_path / "fresh runtime", "--silent", assets=pack)


def _assert_fileless_entry(tmp_path, flag, *, assets=None):
    script = """
import sys
from pathlib import Path
import requests
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
import config_manager
import main
from gui.main_window import MainWindow

def deny(*args, **kwargs):
    raise AssertionError('Unexpected live service')

requests.sessions.Session.request = deny
class NoSecretStore:
    def __init__(self, *a, **k): pass
    def get_secret(self, *a, **k): return None
config_manager.SecretStore = NoSecretStore
root = Path(sys.argv[1])
main.project_root = lambda: root
exec_qt = QApplication.exec
def probe():
    app = QApplication.instance()
    win = next(w for w in app.topLevelWidgets() if isinstance(w, MainWindow))
    assert win.isVisible() and win.centralWidget().isEnabled()
    entry = getattr(win, '_startup_attachment', None)
    if entry is not None:
        assert entry._home_released and not entry.splash.isVisible()
        assert not entry.dock_target.isVisible()
    assert win.config.resolve_path('paths.database').is_relative_to(root)
    assert not win.db.list_essays()
    assert 'gui.startup_audio' not in sys.modules
    assert 'gui.startup_audio_worker' not in sys.modules
    QTimer.singleShot(0, app.quit)
    return exec_qt()
QApplication.exec = staticmethod(probe)
raise SystemExit(main.main([sys.argv[2]]))
"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for name in ("CET_LOCAL_ASSETS_DIR", "CET_COMPANIONS_DIR"):
        env.pop(name, None)
    if assets is not None:
        env["CET_LOCAL_ASSETS_DIR"] = str(assets)
    process = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path), flag],
                             cwd=Path(__file__).resolve().parents[1], env=env, text=True,
                             capture_output=True, timeout=30)
    assert process.returncode == 0, process.stdout + process.stderr
