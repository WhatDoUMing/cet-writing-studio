"""Window-level startup integration. Audio fixtures never talk to a device."""

import json
import os
from time import monotonic
from wave import open as open_wave

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PIL import Image, ImageDraw
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QMainWindow, QPushButton, QScrollArea, QStatusBar, QVBoxLayout, QWidget

from gui.start_splash import AUDIO_START_GRACE_MS, BRIDGE_MS, HD_LONG_PROFILE, LAUGH_MS, LONG_WAV, REVEAL_MS, SLIDE_MS
from gui.startup_integration import attach_startup_splash
from gui.styles import get_app_style
from tests.test_workflow_sessions import APP, make_window


class SilentDevice:
    """Record operations only; no multimedia imports or system I/O."""

    def __init__(self):
        self.calls = []
        self.active = False

    def play(self):
        self.calls.append("play")
        self.active = True

    def stop(self):
        self.calls.append("stop")
        self.active = False


def _write_silent_fixture(path):
    # Minimal all-zero samples for a synthetic WAV container in pytest tmp_path.
    # Only the fake factory receives the path: no reader or playback is used.
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_wave(str(path), "wb") as fixture:
        fixture.setnchannels(1)
        fixture.setsampwidth(2)
        fixture.setframerate(8000)
        fixture.writeframes(b"\x00\x00" * 80)


def _wait_until(predicate, timeout_ms=3600):
    deadline = monotonic() + timeout_ms / 1000
    while not predicate():
        assert monotonic() < deadline, "Timed out waiting for startup transition"
        QTest.qWait(12)


def _press_esc(window):
    QTest.keyClick(APP.focusWidget() or window, Qt.Key.Key_Escape)
    APP.processEvents()


@pytest.fixture
def host():
    window = QMainWindow()
    central = QWidget()
    layout = QVBoxLayout(central)
    button = QPushButton("主页操作")
    layout.addWidget(button)
    window.setCentralWidget(central)
    window.resize(800, 600)
    shortcut = QShortcut(QKeySequence("Ctrl+1"), window)
    yield window, central, button, shortcut
    window.close()
    APP.processEvents()


@pytest.fixture
def image_dir(tmp_path):
    assets = tmp_path / "synthetic-frames"
    assets.mkdir()
    portrait = Image.new("RGBA", (1320, 1864), (255, 255, 255, 0))
    ImageDraw.Draw(portrait).ellipse((300, 180, 1080, 1720), fill="#E1BA35")
    portrait.save(assets / "synthetic-portrait.png")
    frames = []
    for index in range(12):
        image = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
        brush = ImageDraw.Draw(image)
        brush.ellipse((28 + index, 18, 175, 186 - index), fill="#E3BF3E")
        brush.ellipse((74, 74, 91 + index, 111), fill="#45310D")
        name = f"synthetic-laugh-{index:02d}.png"
        image.save(assets / name)
        frames.append({"file": name, "ms": 100})
    manifest = {"version": 4, "portrait": "synthetic-portrait.png",
                "laugh": {"frames": frames, "dock": 6}}
    (assets / "startup-v4.json").write_text(json.dumps(manifest), encoding="utf-8")
    return assets


@pytest.fixture
def hd_dir(image_dir):
    source = image_dir / "startup-v4.json"
    manifest = json.loads(source.read_bytes())
    frames = []
    native_dir=image_dir/"hd-laugh-1733"
    (native_dir/"frames").mkdir(parents=True)
    for i in range(52):
        ms=round((i+1)*1000/30)-round(i*1000/30)
        image = Image.new("RGBA", (180, 246), (255, 255, 255, 0))
        brush = ImageDraw.Draw(image)
        brush.ellipse((22, 12, 164, 235), fill="#E3BF3E")
        brush.ellipse((48 + i // 2, 50, min(126, 81 + 2 * i), 108), fill="#45310D")
        name = f"hd-laugh-1733/frames/{i:03d}.png"
        image.save(image_dir / name)
        frames.append({"file": name, "ms": ms})
    dock = Image.new("RGBA", (180,246), (255,255,255,0))
    brush = ImageDraw.Draw(dock)
    brush.ellipse((32,14,158,237), fill="#E3BF3E")
    brush.ellipse((65,67,81,86), fill="#352D15")
    brush.ellipse((108,67,124,86), fill="#352D15")
    portrait = "hd-laugh-1733/dock-natural-f375.png"
    dock.save(image_dir/portrait)
    manifest["laugh"] = {"profile": HD_LONG_PROFILE, "start_ms": 0, "dock": 51,
                         "frames": frames, "dock_portrait":portrait}
    source.write_text(json.dumps(manifest), encoding="utf-8")
    return image_dir


def _show_startup(host, image_dir, *, reduced_motion=False, sound_factory=None):
    window, central, _button, shortcut = host
    attachment = attach_startup_splash(
        window, asset_dir=image_dir, reduced_motion=reduced_motion, sound_factory=sound_factory,
    )
    assert attachment is not None
    assert attach_startup_splash(window, asset_dir=image_dir) is attachment
    window.show()
    APP.setActiveWindow(window)
    APP.processEvents()
    assert attachment.splash.phase == "wait"
    assert attachment.splash.start_button.isVisible()
    assert not central.isEnabled() and not shortcut.isEnabled()
    return attachment


def _verify_dock(attachment, host):
    window, central, button, shortcut = host
    _wait_until(lambda: attachment.splash.phase == "docked", SLIDE_MS + 750)
    APP.processEvents()
    assert central.isEnabled() and shortcut.isEnabled()
    assert attachment.dock_target.isVisible()
    dock = QRect(attachment.dock_target.mapTo(window, QPoint()), attachment.dock_target.size())
    content = QRect(central.mapTo(window, QPoint()), central.size())
    assert content==window.rect() and content.contains(dock)
    assert window.findChild(QStatusBar) is None
    assert not any(dock.intersects(r) for r in attachment._protected(dock))
    assert window.childAt(dock.center()) is not attachment.dock_target
    assert dock.center().x() > window.width() * 0.8 and dock.center().y() > window.height() * 0.8
    assert attachment.dock_target.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    clicks = QSignalSpy(button.clicked)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(clicks) == 1


@pytest.mark.parametrize("stage", ["wait", "reveal", "bridge", "laugh", "slide"])
def test_escape_in_every_live_stage_docks_once_and_leaves_home_interactive(host, hd_dir, stage):
    wav = hd_dir / LONG_WAV
    _write_silent_fixture(wav)
    device = SilentDevice()
    opened = []

    def fake_factory(path):
        opened.append(path)
        return device

    attachment = _show_startup(host, hd_dir, sound_factory=fake_factory)
    splash = attachment.splash
    if stage != "wait":
        splash.start_button.click()
        assert splash.phase == "reveal" and not device.calls
    if stage == "reveal":
        assert 0 <= splash.reveal_progress < 1
    elif stage == "bridge":
        _wait_until(lambda: splash.phase == "laugh" and splash.bridge_progress < 1)
        assert 0 <= splash.bridge_progress < 1
    elif stage == "laugh":
        _wait_until(lambda: splash.bridge_progress >= 1 and device.active and splash.phase == "laugh")
        assert device.calls == ["play"]
    elif stage == "slide":
        _wait_until(lambda: splash.phase == "slide")
        assert host[1].isEnabled(), "The main page must reveal while the image docks"
    else:
        assert splash.phase == "wait"
    _press_esc(host[0])
    _verify_dock(attachment, host)
    _press_esc(host[0])
    assert splash.phase == "docked" and not device.active
    if stage in {"wait", "reveal", "bridge"}:
        assert not opened and not device.calls
    else:
        assert opened == [wav]
        assert device.calls == ["play", "stop"]


def test_start_only_once_with_normal_motion_and_explicit_fake_channel(host, hd_dir):
    wav = hd_dir / LONG_WAV
    _write_silent_fixture(wav)
    device = SilentDevice()
    opened = []

    def factory(path):
        opened.append((path, splash.phase, splash.bridge_progress, splash.frame_index, splash.clock.elapsed()))
        return device

    attachment = _show_startup(host, hd_dir, sound_factory=factory)
    splash = attachment.splash

    splash.start_button.click()
    started = monotonic()
    for _ in range(4):
        splash.start_button.click()
        QTest.keyClick(splash.start_button, Qt.Key.Key_Return)
    assert splash.phase == "reveal" and not host[1].isEnabled()
    assert not opened and not device.calls
    _wait_until(lambda: splash.bridge_progress >= 1 and splash.phase == "laugh")
    assert REVEAL_MS <= splash.full_reveal_ms <= REVEAL_MS + 160
    first = splash.frame_index
    _wait_until(lambda: splash.phase == "laugh" and splash.frame_index != first)
    _wait_until(lambda: splash.phase == "slide")
    sliding = monotonic()
    expected = REVEAL_MS + BRIDGE_MS + splash.clip.duration_ms
    assert sliding - started >= (expected - 125) / 1000 and host[1].isEnabled()
    _verify_dock(attachment, host)
    assert monotonic() - sliding >= (SLIDE_MS - 125) / 1000
    assert len(opened) == 1
    path, phase, bridge, index, at_ms = opened[0]
    assert (path, phase, index) == (wav, "laugh", 0)
    # A terminal bridge sample can already select the native source. No sound
    # on an intermediate sample, nor a second request at the nominal boundary.
    steps=len(splash._bridge_images)+1
    assert round(splash._ease((bridge-.16)/.84)*steps)==steps
    assert splash.full_reveal_ms <= splash.native_start_ms <= at_ms <= splash.native_start_ms + AUDIO_START_GRACE_MS
    assert device.calls == ["play", "stop"] and not device.active


def test_missing_audio_does_not_instantiate_even_an_available_factory(host, hd_dir):
    opened = []
    attachment = _show_startup(host, hd_dir, sound_factory=opened.append)
    attachment.splash.start_button.click()
    _wait_until(lambda: attachment.splash.phase == "laugh" and attachment.splash.frame_index >= 2)
    assert not opened
    _press_esc(host[0])
    _verify_dock(attachment, host)


def test_old_profile_stays_silent_even_with_the_private_wav_filename(host, image_dir):
    _write_silent_fixture(image_dir / LONG_WAV)
    opened = []
    attachment = _show_startup(host, image_dir, sound_factory=opened.append)
    attachment.splash.start_button.click()
    _wait_until(lambda: attachment.splash.phase == "laugh" and attachment.splash.frame_index >= 2)
    assert not opened
    _press_esc(host[0])
    _verify_dock(attachment, host)


def test_reduced_motion_skips_optional_audio_even_if_present(host, hd_dir):
    _write_silent_fixture(hd_dir / LONG_WAV)
    opened = []
    attachment = _show_startup(host, hd_dir, reduced_motion=True, sound_factory=opened.append)
    attachment.splash.start_button.click()
    _wait_until(lambda: attachment.splash.phase == "docked", 2400)
    _verify_dock(attachment, host)
    assert not opened


def test_reduced_motion_reaches_same_dock_without_long_transition(host, image_dir):
    attachment = _show_startup(host, image_dir, reduced_motion=True)
    splash = attachment.splash
    splash.start_button.click()
    assert splash.phase == "laugh" and splash.full_reveal_ms == 0
    _wait_until(lambda: splash.phase != "laugh", 1750)
    assert splash.phase == "docked", "Reduced motion should skip the sliding animation"
    _verify_dock(attachment, host)


def test_close_during_laugh_stops_the_fake_channel_without_docking(host, hd_dir):
    _write_silent_fixture(hd_dir / LONG_WAV)
    device = SilentDevice()
    attachment = _show_startup(host, hd_dir, sound_factory=lambda _path: device)
    attachment.splash.start_button.click()
    _wait_until(lambda: attachment.splash.phase == "laugh" and device.active)
    host[0].close()
    APP.processEvents()
    assert attachment.splash.phase == "closed"
    assert device.calls.count("play") == 1 and not device.active


def test_no_private_assets_leaves_startup_as_the_normal_v2_window(host, tmp_path):
    window, central, _button, shortcut = host
    assert attach_startup_splash(window, asset_dir=tmp_path) is None
    window.show()
    APP.processEvents()
    assert central.isEnabled() and shortcut.isEnabled() and window.findChild(QStatusBar) is None

@pytest.mark.parametrize("width,height,theme", [(800, 600, "light"), (1040, 710, "dark")])
def test_large_dock_keeps_actual_v2_pages_operable(tmp_path, image_dir, width, height, theme):
    # Exercise the existing MainWindow and its real navigation, not a layout mock.
    app_data = tmp_path / "isolated-v2"
    app_data.mkdir()
    window, db = make_window(app_data)
    old_style = APP.styleSheet()
    APP.setStyleSheet(get_app_style(theme))
    window.resize(width, height)
    try:
        entry = attach_startup_splash(window, asset_dir=image_dir)
        assert entry is not None and entry.splash.phase == "wait"
        window.show()
        APP.setActiveWindow(window)
        APP.processEvents()
        _press_esc(window)
        assert entry.splash.phase == "docked"
        dpr = window.devicePixelRatioF()
        if os.environ.get("QT_SCALE_FACTOR") == "1.5":
            assert dpr >= 1.45

        def no_overlap():
            dock = QRect(entry.dock_target.mapTo(window, QPoint()), entry.dock_target.size())
            body = window.centralWidget()
            body_rect = QRect(body.mapTo(window, QPoint()), body.size())
            assert window.size().width() == width and window.size().height() == height
            assert dock.height()>=36  # If the page is crowded, controls keep priority.
            assert body_rect.height() >= body.minimumSizeHint().height() - 1
            assert body_rect==window.rect() and body_rect.contains(dock)
            assert window.findChild(QStatusBar) is None
            if entry.dock_target.isVisible():
                assert not any(dock.intersects(r) for r in entry._protected(dock))
            assert body.isEnabled()

        no_overlap()
        QTest.mouseClick(window.home_page.exam_buttons["CET-6"], Qt.MouseButton.LeftButton)
        APP.processEvents()
        assert window.stack.currentWidget() is window.setup_page and window.exam_level == "CET-6"
        no_overlap()
        window._open_history()
        APP.processEvents()
        assert window.stack.currentWidget() is window.history_page
        assert window.history_page.group_combo.isEnabled()
        no_overlap()
        window._open_settings()
        APP.processEvents()
        assert window.stack.currentWidget() is window.settings_page
        assert window.settings_page.provider_combo.isEnabled()
        no_overlap()
    finally:
        window.close()
        db.close()
        APP.setStyleSheet(old_style)
        APP.processEvents()


def test_dock_uses_available_height_and_scales_on_resize(host, image_dir):
    entry = _show_startup(host, image_dir)
    _press_esc(host[0])
    _verify_dock(entry, host)
    narrow = entry.dock_target.size()
    assert narrow.height() >= 110
    host[0].resize(1280, 820)
    APP.processEvents()
    assert entry.dock_target.height() > narrow.height()
    _verify_dock(entry, host)

@pytest.mark.parametrize("size,theme", [((1266,835),"light"),((800,600),"dark")])
def test_settings_real_view_fills_bottom_and_role_is_click_through(tmp_path,image_dir,size,theme):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent
    data=tmp_path/"isolated-settings";data.mkdir()
    w,db=make_window(data);old=APP.styleSheet();APP.setStyleSheet(get_app_style(theme))
    try:
        w.resize(*size);w.show();APP.processEvents()
        a=attach_startup_splash(w,asset_dir=image_dir,reduced_motion=True)
        a.splash.skip();w._open_settings()
        for _ in range(3):APP.processEvents()
        sc=w.settings_page.findChild(QScrollArea);bar=sc.verticalScrollBar()
        wrect=w.rect(); assert w.centralWidget().geometry()==wrect and not w.findChild(QStatusBar)
        for value in (0,bar.maximum()//2,bar.maximum()):
            bar.setValue(value)
            for _ in range(3):APP.processEvents()
            assert a.dock_target.isVisible()
            rect=a.dock_target.geometry()
            assert wrect.contains(rect) and not any(rect.intersects(x) for x in a._protected(rect))
            hit=w.childAt(rect.center())
            assert hit is not None and hit is not a.dock_target and not a.dock_target.isAncestorOf(hit)
            assert sc.isAncestorOf(hit) or hit is sc
            bottom=sc.viewport().mapTo(w,QPoint(0,sc.viewport().height()-1)).y()
            assert bottom>=w.height()-3
        # A bottom-row button is physically reachable. Clicking 'back' only
        # navigates; do not save config, use API credentials, or fetch a provider.
        back=next(b for b in w.settings_page.findChildren(QPushButton) if b.text()=="返回首页")
        at=back.mapTo(w,back.rect().center());assert w.childAt(at) is back
        QTest.mouseClick(w.childAt(at),Qt.MouseButton.LeftButton);APP.processEvents()
        assert w.stack.currentWidget() is w.home_page
        w._open_settings();bar.setValue(0);APP.processEvents()
        q=w.settings_page.api_key_edit;q.setFocus();QTest.keyClicks(q,"test");assert q.text().endswith("test")
        corner=a.dock_target.geometry().center()
        local=sc.viewport().mapFrom(w,corner);glob=sc.viewport().mapToGlobal(local)
        ev=QWheelEvent(QPointF(local),QPointF(glob),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
        APP.sendEvent(sc.viewport(),ev);APP.processEvents()
        assert bar.value()>0 and not a.dock_target.hasFocus()
        for ww,hh in ((1000,700),(800,600),size):
            w.resize(ww,hh)
            for _ in range(3):APP.processEvents()
            assert w.centralWidget().geometry()==w.rect() and not w.findChild(QStatusBar)
    finally:
        w.close();db.close();APP.setStyleSheet(old);APP.processEvents()
