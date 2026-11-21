"""Widget-level startup checks: synthetic frames and no physical audio backend."""
import json
from time import monotonic

import pytest
from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QKeyEvent, QPainter, QRegion
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMainWindow, QWidget

from gui.start_splash import REVEAL_MS, BRIDGE_MS, LAUGH_MS, SLIDE_MS, StartSplash, contain, paint_frame, read_scene
from tests.test_workflow_sessions import APP


@pytest.fixture
def scene(tmp_path):
    side=QImage(1320,1864,QImage.Format.Format_RGB32)
    side.fill(QColor("#d4a966"))
    assert side.save(str(tmp_path / "side.png"))
    frames=[]
    for i in range(12):
        img=QImage(160,200,QImage.Format.Format_RGB32)
        img.fill(QColor(240,120+i*8,50))
        name=f"laugh-{i:02}.png"
        assert img.save(str(tmp_path/name))
        frames.append({"file":name,"ms":90})
    (tmp_path/"startup-v4.json").write_text(json.dumps(
        {"version":4, "portrait":"side.png","laugh":{"frames":frames,"dock":11}}),encoding="utf-8")
    w=QMainWindow(); page=QWidget(); w.setCentralWidget(page)
    target=QWidget(page); target.setGeometry(712,510,72,72)
    w.resize(800,600); w.show(); APP.setActiveWindow(w); APP.processEvents()
    calls=[]
    def make(**kw):
        return StartSplash(w,asset_dir=tmp_path,dock_target=target,
                           on_home=lambda:calls.append(("home",monotonic())),
                           on_docked=lambda:calls.append(("dock",monotonic())),**kw)
    yield make,calls,w,target,tmp_path
    w.close(); APP.processEvents()


def wait_for(check):
    end=monotonic()+2.6
    while not check() and monotonic()<end: QTest.qWait(10)
    assert check()


@pytest.mark.parametrize("reduced",[False,True])
def test_start_once_and_real_timer(scene,reduced):
    make,calls,_,target,_=scene; s=make(reduced_motion=reduced)
    s.start(); s.start()
    assert s.phase=="wait" and s.start_button.hasFocus()
    assert s.blink_wait.isActive() is not reduced
    begin=monotonic()
    QTest.mouseClick(s.start_button,Qt.MouseButton.LeftButton)
    QTest.keyClick(s,Qt.Key.Key_Space); s.start_button.click()
    assert s.phase==("laugh" if reduced else "reveal") and not calls and not s.blink_wait.isActive()
    QTest.qWait(750)
    assert s.phase=="laugh" and not calls
    wait_for(lambda:s.phase=="docked")
    assert [key for key,_ in calls]==["home","dock"] and calls[0][1]-begin>=.985
    if reduced:
        assert s.travel==0 and calls[1][1]-calls[0][1]<.1
    else:
        assert calls[0][1]-begin >= (REVEAL_MS+LAUGH_MS+BRIDGE_MS)/1000-.025
        assert calls[1][1]-calls[0][1] >= SLIDE_MS/1000-.035
    assert s.dock.geometry()==target.rect() and s.dock.isVisible()
    assert s.dock.image.cacheKey()==s.smile.cacheKey()
    target.resize(86,58); assert s.dock.geometry()==target.rect()
    assert s.dock.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    s.skip(); assert len(calls)==2


@pytest.mark.parametrize("phase",["wait","reveal","laugh","slide"])
def test_skip_to_same_state(scene,phase):
    make,calls,_,_,_=scene; s=make(); s.start()
    if phase!="wait": QTest.keyClick(s.start_button,Qt.Key.Key_Return)
    if phase in ("laugh","slide"): wait_for(lambda:s.phase==phase)
    assert s.phase==phase
    QTest.keyClick(s,Qt.Key.Key_Escape)
    assert s.phase=="docked" and s.dock.isVisible()
    assert len(calls)==2 and not s.pulse.isActive() and not s.blink_wait.isActive()
    assert not s._watching


@pytest.mark.parametrize("broken",["side.png","laugh-00.png","startup-v4.json"])
def test_missing_art_never_traps_user(scene,broken):
    make,calls,_,_,path=scene;(path/broken).write_bytes(b"broken")
    s=make();s.start()
    assert s.phase=="docked" and not s.isVisible() and len(calls)==2


def test_blink_keeps_entire_rest_of_portrait_untouched(scene):
    make,_,_,_,_=scene;s=make();s.start()
    def frame(lid):
        image=QImage(660,932,QImage.Format.Format_RGB32)
        painter=QPainter(image);paint_frame(painter,s.side,QRectF(0,0,660,932),lid);painter.end()
        return image
    opened,closed=frame(0),frame(1)
    assert opened.pixel(256,114)!=closed.pixel(256,114)
    assert opened.pixel(190,124)!=closed.pixel(190,124)
    p=QPainter(closed)
    for box in (QRectF(180,100,23,46),QRectF(226,85,64,65)):
        p.drawImage(box,opened,box)
    p.end()
    assert opened==closed
    fitted=contain(QRectF(0,0,320,441),s.side.size())
    assert fitted.width()/fitted.height()==pytest.approx(1320/1864)


def test_shutdown_default_silent_no_audio_path_reads(scene,monkeypatch):
    make,calls,_,_,path=scene;s=make();s.start()
    old=type(path).is_file
    def probe(p):
        assert p.suffix!=".wav"
        return old(p)
    monkeypatch.setattr(type(path),"is_file",probe)
    QTest.keyClick(s.start_button,Qt.Key.Key_Space)
    assert s._effect is None
    s.shutdown(); s.skip(); s._advance()
    assert s.phase=="closed" and not calls and not s.pulse.isActive()


def test_held_activation_never_fires_home_action(scene):
    make,calls,_,_,_=scene;s=make();s.start()
    key=Qt.Key.Key_Space
    QTest.keyPress(s.start_button,key);s._settle()
    assert s._captured==key and s._watching
    again=QKeyEvent(QEvent.Type.KeyPress,key,Qt.KeyboardModifier.NoModifier," ",True,1)
    APP.sendEvent(s.host,again)
    assert len(calls)==2 and s._watching
    QTest.keyRelease(s.host,key)
    assert not s._watching

def test_unshown_dark_main_window_has_white_opening_without_changing_host_palette(scene):
    _,_,_,_,base=scene
    win=QMainWindow()
    win.setStyleSheet("QMainWindow {background:#1c1e19;}")
    win.ensurePolished()
    prior=win.palette().color(win.backgroundRole())
    target=QWidget(win)
    splash=StartSplash(win,on_home=lambda:None,dock_target=target,asset_dir=base)
    try:
        splash.start()
        assert splash.phase=="wait" and splash.paper.name()=="#ffffff"
        assert win.palette().color(win.backgroundRole())==prior and prior.lightness()<64
    finally:
        splash.shutdown(); win.close()


def test_real_gif_native_delays_and_no_single_still_fallback(scene):
    from PIL import Image
    _, _, _, _, directory = scene
    path = directory / "startup-v4.json"
    frames = [Image.new("RGB", (40, 40), (12, i * 35, 160)) for i in range(5)]
    frames[0].save(directory/"original.gif", save_all=True, append_images=frames[1:],
                   duration=[80,100,120,140,160], loop=0, optimize=False)
    spec = {"version":4,"portrait":"side.png","laugh":{"file":"original.gif","dock":3}}
    path.write_text(json.dumps(spec),encoding="utf-8")
    portrait, _, clip = read_scene(directory)
    assert len(clip.frames) == 5 and clip.ends == [80,180,300,440,600]
    assert [clip.index_at(n) for n in (0,90,230,430,590,610)] == [0,1,2,3,4,0]
    assert clip.dock == 3 and not portrait.isNull()
    frames[0].save(directory/"original.gif")
    assert read_scene(directory) is None
    path.unlink()
    (directory/"laugh-frame-6s.jpg").write_bytes(b"V3 static placeholder")
    assert read_scene(directory) is None


def test_animation_progresses_and_slide_uses_one_monotone_clock(scene):
    make, calls, _, _, _ = scene
    s = make(); s.start(); QTest.mouseClick(s.start_button,Qt.MouseButton.LeftButton)
    indices, bridges, points = set(), [], []
    end=monotonic()+3
    while s.phase!="docked" and monotonic()<end:
        QTest.qWait(12)
        if s.phase=="laugh":
            if s.bridge_progress<1:
                bridges.append(s.bridge_progress)
            else:
                indices.add(s.frame_index)
        elif s.phase=="slide":
            box=s.scene_rect()
            points.append((s.travel,box.center().x(),box.center().y(),box.width()))
    assert s.phase=="docked" and len(calls)==2
    assert len(set(bridges))>=3 and list(sorted(bridges))==bridges
    assert len(indices)>=8 and s.frame_index==s.clip.dock
    assert len(points)>=15
    for a,b in zip(points,points[1:]):
        assert all(x<=y+.02 for x,y in zip(a[:3],b[:3]))
        assert a[3]>=b[3]-.02
    assert points[-1][0]>.97 and s.travel==1.
    assert not s.pulse.isActive()
    last=s.frame_index;QTest.qWait(100);assert s.frame_index==last


@pytest.mark.parametrize("size",[(800,600),(1280,820),(360,400),(320,240)])
def test_centered_eye_slot_and_only_requested_copy(scene,size):
    from PyQt6.QtWidgets import QLabel
    from gui.start_splash import EYE_WINDOW, WELCOME_ZH, WELCOME_EN

    make,_,w,_,_=scene;w.resize(*size);s=make();s.start();APP.processEvents()
    slot=s.reveal_aperture();src=s.reveal_source()
    assert src.getRect()==pytest.approx(EYE_WINDOW,abs=1.e-5)
    assert slot.center().x()==pytest.approx(w.width()/2.)
    assert slot.top()>0 and slot.width()/slot.height()==pytest.approx(EYE_WINDOW[2]/EYE_WINDOW[3])
    assert [q.text() for q in s.findChildren(QLabel) if q.isVisible()]==[WELCOME_ZH,WELCOME_EN]
    assert WELCOME_ZH=="欢迎你奶家人" and WELCOME_EN=="Welcome to the CET-4 & CET-6 Writing Grader"
    assert s.start_button.text()=="Start" and s.start_button.hasFocus()
    assert slot.bottom()<s.welcome_title.y()<s.welcome_subtitle.y()<s.start_button.y()
    assert s.start_button.geometry().bottom()<w.height()
    assert "Esc" in s.start_button.accessibleDescription()
    s.skip()


def test_single_white_camera_window_continuously_reveals_complete_source(scene):
    make,_,w,_,_=scene;s=make();s.start()
    wait_src=s.reveal_source();wait_rect=s.reveal_aperture()
    assert s.grab().toImage().pixelColor(1,1).name()=="#ffffff"
    QTest.mouseClick(s.start_button,Qt.MouseButton.LeftButton)
    assert s.phase=="reveal" and s.reveal_progress==0 and s.reveal_source()==wait_src
    assert not any(x.isVisible() for x in [s.welcome_title,s.welcome_subtitle,s.start_button])
    s.pulse.stop();old_a=wait_rect;old_scale=s.camera_image_rect().width()/s.side_crop.width()
    for n in range(1,61):
        s.reveal_progress=n/60
        hole=s.reveal_aperture();cam=s.camera_image_rect();src=s.reveal_source()
        scale=cam.width()/s.side_crop.width()
        assert hole.adjusted(-1.e-6,-1.e-6,1.e-6,1.e-6).contains(old_a)
        assert scale<old_scale and scale>0
        assert cam.width()/cam.height()==pytest.approx(s.side_crop.width()/s.side_crop.height())
        assert src.adjusted(-1.e-5,-1.e-5,1.e-5,1.e-5).contains(wait_src)
        old_a,old_scale=hole,scale
    assert s.reveal_source().getRect()==pytest.approx(s.side_crop.getRect(),abs=1.e-5)
    assert s.reveal_aperture()==QRectF(w.rect())
    assert s.camera_image_rect().contains(s.reveal_aperture().center())
    assert not w.isFullScreen()
    full=s.camera_image_rect();s.phase="laugh";s.bridge_progress=0.
    assert s._bridge_box().getRect()==pytest.approx(full.getRect(),abs=1.e-6)
    s.skip()


def test_real_timer_reveal_precedes_face_motion_with_no_second_pause(scene):
    make,_,w,_,_=scene;s=make();s.start()
    seen=[];labels=[]
    def tick():
        if s.phase in ("reveal","laugh"):
            seen.append((s.clock.elapsed(),s.phase,s.reveal_progress,s.bridge_progress,s.frame_index))
    s.pulse.timeout.connect(tick)
    s.start_button.click()
    wait_for(lambda:s.phase=="laugh" and s.bridge_progress>=1)
    assert s.full_reveal_ms>=REVEAL_MS
    shown=[r for r in seen if r[1]=="reveal"];matched=[r for r in seen if r[1]=="laugh"]
    assert len({r[2] for r in shown})>=5 and all(r[3]==0 for r in shown)
    assert matched[0][0]>=REVEAL_MS and matched[0][0]-s.full_reveal_ms<40
    assert matched[-1][0]<REVEAL_MS+BRIDGE_MS+100
    assert all(r[2]==1. for r in matched)
    s.skip()


def test_reduced_motion_shows_still_pose_and_never_moves_camera(scene):
    make,_,_,_,_=scene;s=make(reduced_motion=True);s.start()
    assert not s.blink_wait.isActive()
    s.start_button.click()
    assert s.phase=="laugh" and s._still_full and s.full_reveal_ms==0
    assert s.reveal_source().getRect()==pytest.approx(s.side_crop.getRect(),abs=1.e-5)
    wait_for(lambda:not s._still_full)
    assert s.frame_index==s.clip.dock and s.bridge_progress==1 and s.travel==0
    s.skip()


def test_paperless_portrait_preserves_enclosed_white_and_source():
    from gui.start_splash import _paperless_portrait
    im=QImage(160,160,QImage.Format.Format_RGBA8888)
    im.fill(QColor("white"))
    painter=QPainter(im)
    painter.fillRect(25,25,110,110,QColor("#edb351"))
    painter.fillRect(62,60,19,12,QColor("white"));painter.end()
    display=_paperless_portrait(im)
    assert im.pixelColor(0,0).alpha()==255 and display.pixelColor(0,0).alpha()==0
    assert display.pixelColor(70,65)==im.pixelColor(70,65)
    assert display.pixelColor(54,36)==im.pixelColor(54,36)


def _rgba_array(q):
    import numpy as np

    img = q.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8)
    return raw.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4].reshape(img.height(), img.width(), 4).copy()


@pytest.fixture(scope="module")
def private_bridge(tmp_path_factory):
    """Optional original-art regression. Never copies private PNG/GIF into Git."""
    from pathlib import Path

    art = Path(__file__).resolve().parents[1] / "work" / "preview" / "startup-assets"
    if not all((art / name).is_file() for name in ("side-eye-clean.png", "classic-laugh.gif", "startup-v4.json")):
        pytest.skip("private reference art is not distributed with the code")
    # Keep the old 0325 regression live even when the private preview switches
    # to an unrelated HD pose. These bounded local test inputs are not tracked.
    spec=json.loads((art/"startup-v4.json").read_text(encoding="utf-8-sig"))
    if str(spec.get("laugh",{}).get("profile","")).startswith("belly-hd-119"):
        import shutil
        fallback=tmp_path_factory.mktemp("reference-0325")
        for name in ("side-eye-clean.png","classic-laugh.gif"):
            shutil.copyfile(art/name,fallback/name)
        (fallback/"startup-v4.json").write_text(json.dumps(
            {"version":4,"portrait":"side-eye-clean.png","laugh":{"file":"classic-laugh.gif","dock":17}}),encoding="utf8")
        art=fallback
    w = QMainWindow()
    target = QWidget(w)
    target.setGeometry(680, 460, 110, 120)
    w.resize(800, 600)
    s = StartSplash(w, asset_dir=art, dock_target=target, on_home=lambda: None, sound_factory=None)
    s.start()
    s._laugh()
    s.pulse.stop()
    def at(ms):
        s.bridge_progress = ms / BRIDGE_MS
        i = round(s._match_progress() * (len(s._bridge_images) + 1)) - 1
        return _rgba_array(s._bridge_images[max(0, min(i, len(s._bridge_images) - 1))])
    try:
        yield at
    finally:
        s.shutdown()
        w.close()


def test_reference_mouth_opens_across_multiple_ticks(private_bridge):
    """The old 105→115ms cut gained 366 dark mouth texels in a single 10ms window."""
    def dark_mouth(ms):
        image = private_bridge(ms)
        h, w = image.shape[:2]
        region = image[int(.10*h):int(.33*h), int(.208*w):int(.49*w)]
        return int(((region[:,:,0]<107) & (region[:,:,1]<94) &
                    (region[:,:,2]<90) & (region[:,:,3]>220)).sum())
    levels = [dark_mouth(ms) for ms in (85, 95, 105, 109, 115, 122, 135)]
    steps = [b-a for a,b in zip(levels, levels[1:])]
    assert min(steps) >= -3 and max(steps) <= 120
    assert 0 < levels[0] < levels[-1] - 160


def test_reference_leg_keeps_one_solid_outline_during_crossing(private_bridge):
    """GUI eye anchors alone do not catch the stacked 109ms heel or enclosed floor."""
    import cv2
    import numpy as np

    for ms in (99, 105, 109, 115, 122):
        image = private_bridge(ms)
        h = image.shape[0]
        alpha = image[:,:,3]
        lower = slice(int(.70*h), None)
        distance = cv2.distanceTransform((alpha<244).astype(np.uint8), cv2.DIST_L2, 5)
        detached_matte = ((alpha>10) & (alpha<236) & (distance>1.6))[lower]
        assert np.count_nonzero(detached_matte) < 320
        rgb = image[lower,:,:3].astype(int)
        paper = (alpha[lower]>220) & (rgb[:,:,0]>187) & (rgb[:,:,1]>181) & ((rgb[:,:,0]-rgb[:,:,2])<56)
        assert np.count_nonzero(paper) < 140


def test_synthetic_anatomical_match_preserves_hole_between_feet():
    """Always runs without private assets; saturated two-leg fixture and pale floor."""
    import numpy as np
    from PIL import Image, ImageDraw
    from gui.start_splash import _morph_frames

    def body(laughing):
        art = Image.new("RGBA", (400,480), (0,0,0,0))
        pen = ImageDraw.Draw(art)
        gold = (191,130,42,255)
        pen.ellipse((35,12,360,360), fill=gold)
        if laughing:
            pen.polygon([(100,310),(205,330),(180,479),(121,479)], fill=gold)
            pen.polygon([(205,330),(312,295),(335,479),(274,479)], fill=gold)
        else:
            pen.polygon([(90,330),(205,330),(225,450),(62,442)],fill=(223,211,184,255))
            pen.polygon([(90,315),(205,332),(180,418),(202,436),(62,443),(55,432),(152,413)],fill=gold)
            pen.polygon([(205,332),(314,316),(301,426),(320,452),(262,470),(200,466),(198,454),(270,427)],fill=gold)
        data = art.tobytes()
        return QImage(data,400,480,400*4,QImage.Format.Format_RGBA8888).copy()
    a,b=body(False),body(True)
    frames=_morph_frames(a,QRectF(a.rect()),b,QRectF(b.rect()),steps=12)
    for frame in frames[3:8]:
        arr=_rgba_array(frame)
        floor=(arr[:,:,0]>208) & (arr[:,:,1]>185) & (arr[:,:,3]>220)
        assert not np.any(floor[int(.77*frame.height()):])


def test_blink_separates_only_enclosed_floor_and_preserves_standing_image():
    from gui.start_splash import _bridge_paper_layers

    im = QImage(100,100,QImage.Format.Format_RGBA8888)
    im.fill(Qt.GlobalColor.transparent)
    p = QPainter(im)
    p.fillRect(15,72,23,24,QColor(140,92,27))
    p.fillRect(38,76,24,18,QColor(224,210,184))
    p.fillRect(62,72,23,24,QColor(140,92,27))
    p.fillRect(28,82,1,1,QColor(23,19,8))
    p.end()
    old = im.copy()
    clean, floor, top = _bridge_paper_layers(im, QRectF(im.rect()))
    assert clean.pixelColor(46,84).alpha() == 0
    assert floor.pixelColor(46,84-top) == old.pixelColor(46,84)
    assert clean.pixelColor(28,82) == old.pixelColor(28,82)
    assert floor.pixelColor(28,82-top).alpha() == 0 and im == old


def test_hd_profile_contract_rejects_incomplete_or_retimed_shot(scene):
    from gui.start_splash import HD_PROFILE
    _,_,_,_,art=scene
    mf=art/"startup-v4.json"
    original=json.loads(mf.read_text(encoding="utf8"))
    original["laugh"]["profile"]=HD_PROFILE
    mf.write_text(json.dumps(original),encoding="utf8")
    assert read_scene(art) is None
    original["laugh"]["frames"]=[
        {"file":f"laugh-{i%12:02}.png","ms":round((i+1)*1000/30)-round(i*1000/30)} for i in range(30)]
    original["laugh"]["dock"]=29
    mf.write_text(json.dumps(original),encoding="utf8")
    result=read_scene(art);assert result is not None
    clip=result[2]
    assert clip.profile==HD_PROFILE and clip.ends[-1]==1000 and clip.index_at(999)==29
    original["laugh"]["dock"]=17;mf.write_text(json.dumps(original),encoding="utf8")
    assert read_scene(art) is None


def test_hd_matte_keeps_teeth_and_both_feet_without_a_floor():
    from gui.start_splash import _clean_hd_backdrop
    im=QImage(220,300,QImage.Format.Format_RGBA8888);im.fill(QColor("#fafaf5"))
    p=QPainter(im);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor("#daa333"))
    p.drawEllipse(42,14,142,205)
    p.fillRect(61,170,36,97,QColor("#ae7835"));p.fillRect(124,169,34,100,QColor("#ae7835"))
    p.fillRect(98,230,25,35,QColor(225,211,184))
    p.fillRect(89,87,47,22,QColor("#352526"));p.fillRect(98,91,28,5,QColor("white"));p.end()
    frozen=im.copy();mat=_clean_hd_backdrop(im)
    assert im==frozen and mat.pixelColor(2,2).alpha()==0
    assert mat.pixelColor(110,248).alpha()<3 and mat.pixelColor(79,240).alpha()>251
    assert mat.pixelColor(135,240).alpha()>251 and mat.pixelColor(112,93)==QColor("white")


def test_hd_hand_lip_maps_stay_finite_at_aperture_endpoints():
    import cv2
    import numpy as np
    from gui.start_splash import _hd_feature_maps
    yy,xx=np.mgrid[:170,:150].astype(np.float32)
    identity=np.dstack((xx,yy))
    for t in (.02,.15,.5,.85,.98):
        a,b=identity.copy(),identity.copy()
        with np.errstate(invalid="raise",over="raise"):
            oral=_hd_feature_maps(cv2,np,a,b,xx,yy,t)
        assert np.isfinite(a).all() and np.isfinite(b).all()
        assert 0<=oral.min()<oral.max()<=1


def test_private_hd_native_order_duration_and_nonstatic_edges():
    from pathlib import Path
    from gui.start_splash import HD_PROFILE
    import numpy as np
    art=Path(__file__).resolve().parents[1]/"work"/"preview"/"startup-assets"
    if not (art/"startup-v4.json").is_file():
        pytest.skip("private HD media is intentionally not distributed with code")
    spec=json.loads((art/"startup-v4.json").read_text(encoding="utf-8-sig"))
    if not spec["laugh"].get("profile","").startswith(HD_PROFILE):
        pytest.skip("candidate is explicitly using the original 200px fallback")
    _,_,clip=read_scene(art)
    assert clip.profile.startswith(HD_PROFILE) and (clip.frames[0].width(),clip.frames[0].height())==(1080,1474)
    n=52 if clip.profile.endswith("-170") else 30
    assert clip.ends==[round((i+1)*1000/30) for i in range(n)] and clip.dock==n-1
    if n==52: assert clip.dock_still is not None and clip.duration_ms==1733
    rendered=[_rgba_array(clip.frames[i])[::12,::12,:3].astype(int) for i in (0,3,12,23,29)]
    assert all(np.mean(np.abs(b-a))>1. for a,b in zip(rendered,rendered[1:]))

# --- V5-audio only. All "play" calls below are inert spies, never device APIs. ---
class _ManualClock:
    def __init__(self):
        self.ms = 0
    def start(self):
        self.ms = 0
    def elapsed(self):
        return self.ms


def _arm_test_shot(scene, factory, *, reduced=False, hd=True, wav=True):
    from gui.start_splash import HD_LONG_PROFILE,LONG_DIR,LONG_DOCK,LONG_WAV
    import shutil
    make,calls,host,_,asset=scene
    frame_dir=asset/LONG_DIR/"frames";frame_dir.mkdir(parents=True)
    if hd:
        spec=json.loads((asset/"startup-v4.json").read_text())
        base=spec["laugh"]["frames"]
        ticks=[round(i*1000/30) for i in range(53)]
        new_frames=[]
        for i in range(52):
            dst=frame_dir/f"{i:03}.png"
            shutil.copyfile(asset/base[i%len(base)]["file"],dst)
            new_frames.append(dict(file=dst.relative_to(asset).as_posix(),ms=ticks[i+1]-ticks[i]))
        shutil.copyfile(asset/base[7]["file"],asset/LONG_DOCK)
        spec["laugh"]=dict(profile=HD_LONG_PROFILE,start_ms=0,dock=51,
                           frames=new_frames,dock_portrait=LONG_DOCK)
        (asset/"startup-v4.json").write_text(json.dumps(spec))
    if wav:
        import wave
        with wave.open(str(asset/LONG_WAV),"wb") as fp:
            fp.setparams((1,2,8000,0,"NONE","not compressed"))
            fp.writeframes(bytes(2*13864))
    s = make(sound_factory=factory, reduced_motion=reduced)
    s.clock = _ManualClock()
    s.start()
    return s, calls, host


def _step(s, ms):
    s.clock.ms = ms
    s._advance()
    APP.processEvents()


def test_audio_only_after_native_first_paint_and_stops_on_flight(scene, monkeypatch):
    import gui.start_splash as gm
    log = []
    class Spy:
        def play(self): log.append(("play", s.clock.elapsed()))
        def stop(self): log.append(("stop", s.clock.elapsed()))
    def make(path):
        assert path.name=="laugh-long-a.wav" and path.parent==s.assets/"hd-laugh-1733"
        log.append(("create", s.clock.elapsed()))
        return Spy()
    s, calls, _ = _arm_test_shot(scene, make)
    real_paint = gm.paint_frame
    def record(p, img, *a, **kw):
        result = real_paint(p, img, *a, **kw)
        if s.phase=="laugh" and img is s.clip.frames[0]:
            log.append(("native-first", s.clock.elapsed()))
        return result
    monkeypatch.setattr(gm, "paint_frame", record)
    assert not log
    QTest.mouseClick(s.start_button, Qt.MouseButton.LeftButton)
    s.pulse.stop()
    s.start_button.click()
    for ms in (0, 350, REVEAL_MS, 770):  # 770 still selects a morph image.
        _step(s, ms)
        assert not log
    at=784  # 100% baseline: the renderer is already drawing #119 at this tick.
    s.clock.ms=at;s._advance()  # requesting an update is not a paint
    assert s.bridge_progress<1 and not log
    s.repaint()
    assert log[:3] == [("native-first",at),("create",at),("play",at)]
    early=s.grab().toImage()
    _step(s,REVEAL_MS+BRIDGE_MS)
    assert s.native_start_ms==at and s.frame_index==0 and early==s.grab().toImage()
    s.repaint();s.grab()
    for ms in (at+10,at+33,at+500,at+1000,at+1732):
        _step(s,ms)
    assert [x[0] for x in log].count("play")==1 and not calls
    assert not any(k=="stop" for k,_ in log)
    _step(s,at+1733);s.repaint();_step(s,at+2533);s.skip();s.shutdown()
    assert [x for x in log if x[0]=="stop"]==[("stop",at+1733)]


class _OpaqueSplashCover(QWidget):
    def __init__(self, splash):
        super().__init__(splash)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setGeometry(0,0,splash.width(),splash.height()//3)
        self.show();self.raise_()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor("white"))
        painter.end()


@pytest.mark.parametrize("kind",["center","hole","obscured"])
def test_only_complete_visible_native_paint_can_start_audio(scene,kind,monkeypatch):
    import gui.start_splash as gm
    calls=[]
    class Spy:
        def play(self): calls.append(("play",s.clock.ms))
        def stop(self): calls.append(("stop",s.clock.ms))
    def factory(path):
        calls.append(("prepare",s.clock.ms))
        return Spy()
    s,_,_=_arm_test_shot(scene,factory)
    paint=gm.paint_frame
    painted=[]
    def observe(painter,img,*args,**kwargs):
        result=paint(painter,img,*args,**kwargs)
        if s.phase=="laugh" and img is s.clip.frames[0]:
            painted.append(s.clock.ms)
        return result
    monkeypatch.setattr(gm,"paint_frame",observe)
    s.start_button.click();s.pulse.stop()
    _step(s,600);_step(s,770)
    assert not calls and not painted
    target=s._laugh_rect().toAlignedRect()
    center=s._laugh_rect().center().toPoint()
    cover=None
    if kind=="obscured":
        cover=_OpaqueSplashCover(s)
        APP.processEvents()
        assert target.intersects(cover.geometry()) and not cover.geometry().contains(center)
    s.clock.ms=784;s._advance()
    if kind=="obscured":
        s.repaint()
    else:
        if kind=="center":
            damage=QRegion(QRect(center.x(),center.y(),1,1))
        else:
            hole=QRegion(QRect(center.x()+13,center.y()-19,11,7))
            damage=QRegion(s.rect()).subtracted(hole)
            assert damage.boundingRect()==s.rect() and damage.contains(center)
        dpr=s.devicePixelRatioF()
        image=QImage(int(s.width()*dpr),int(s.height()*dpr),QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr);image.fill(Qt.GlobalColor.transparent)
        s.render(image,QPoint(),damage)
    assert painted and painted[0]==784, "The partial paint selected the exact source picture."
    assert not calls and s.native_start_ms is None
    if cover is not None: cover.hide()
    s.clock.ms=786;s.repaint()
    assert s.native_start_ms==786 and calls==[("prepare",786),("play",786)]
    s.repaint(); _step(s,790);s.repaint(); _step(s,2519)
    assert calls==[("prepare",786),("play",786),("stop",2519)]


@pytest.mark.parametrize("cancel",[None,"escape","close"])
def test_persistent_paint_obstruction_does_not_stall_or_arm_late(scene,cancel):
    opened=[]
    s,_,host=_arm_test_shot(scene,opened.append)
    s.start_button.click();s.pulse.stop()
    _step(s,600);_step(s,770)
    cover=_OpaqueSplashCover(s);APP.processEvents()
    _step(s,790)
    assert not opened and s.native_start_ms is None
    if cancel=="escape":
        QTest.keyClick(s,Qt.Key.Key_Escape)
    elif cancel=="close":
        host.close()
    else:
        _step(s,895)
        assert s.audio_status=="native-frame-incomplete" and s.frame_index>0
    cover.hide();s.repaint()
    _step(s,3500)
    assert not opened and s.phase==("closed" if cancel=="close" else "docked")


@pytest.mark.parametrize("action",["skip","close"])
@pytest.mark.parametrize("when",[0,599,700,770,784,792])
def test_escape_or_close_cannot_arm_late_audio(scene,action,when):
    events=[]
    class Spy:
        def play(self): events.append("play")
        def stop(self): events.append("stop")
    s, _, host = _arm_test_shot(scene,lambda p: (events.append("open"),Spy())[1])
    if when:
        s.start_button.click();s.pulse.stop();_step(s,when)
    if action=="skip":
        QTest.keyClick(s,Qt.Key.Key_Escape)
    else:
        host.close();APP.processEvents()
    _step(s,800);s.repaint();s._after_native_frame_painted()
    assert events == (["open","play","stop"] if when in (784,792) else [])
    assert s._effect is None and not s.pulse.isActive()


@pytest.mark.parametrize("case",["reduced","fallback","missing","default","hidden"])
def test_opt_in_is_fail_silent_on_unmatched_or_unrendered_shot(scene,case):
    opened=[]
    s, _, host = _arm_test_shot(scene, None if case=="default" else lambda path: opened.append(path),
          reduced=case=="reduced", hd=case!="fallback", wav=case!="missing")
    s.start_button.click();s.pulse.stop()
    if case=="hidden": host.hide()
    at = REVEAL_MS+BRIDGE_MS
    _step(s,at)
    _step(s,at+221);_step(s,at+1733);_step(s,at+2600)
    assert not opened and s.phase=="docked"


@pytest.mark.parametrize("fault",["factory","play","stop","reentrant-close","late-factory"])
def test_bad_optional_backend_cannot_break_visual_clock_or_restart(scene,fault):
    calls=[]
    class Bad:
        def play(self):
            calls.append("play")
            if fault=="play": raise OSError("test-only unsupported device")
        def stop(self):
            calls.append("stop")
            if fault=="stop": raise RuntimeError("test-only stop")
    def build(p):
        calls.append("factory")
        if fault=="factory": raise OSError("test-only unavailable")
        if fault=="reentrant-close": s.shutdown()
        if fault=="late-factory": s.clock.ms+=125
        return Bad()
    s,_,_=_arm_test_shot(scene,build)
    s.start_button.click();s.pulse.stop();_step(s,790);s.repaint();_step(s,3400)
    assert s.phase==("closed" if fault=="reentrant-close" else "docked")
    assert calls.count("factory")==1 and s._effect is None
    assert calls.count("play")==int(fault in ("play","stop"))
    assert calls.count("stop")==int(fault!="factory")


def test_actual_portrait_band_contains_both_native_edges_not_a_vertical_cut():
    from pathlib import Path
    import numpy as np
    from PIL import Image
    from gui.start_splash import EYE_WINDOW
    source=Path(__file__).resolve().parents[1]/"work/preview/startup-assets/side-eye-clean.png"
    if not source.exists(): pytest.skip("private source intentionally not distributed")
    rgb=np.asarray(Image.open(source).convert("RGB"),dtype=int)
    x,y,w,h=map(int,EYE_WINDOW)
    assert (y,h)==(178,114) and w>=480
    band=rgb[y:y+h,x:x+w]; cols=band[:,:,0]-band[:,:,2]>25
    right=np.array([np.flatnonzero(row)[-1] for row in cols])
    left=np.array([np.flatnonzero(row)[0] for row in cols])
    assert min(left)>=40 and min(w-1-right)>=45 and right[-1]-right[0]>=60
    assert band[:,-10:,:].min()>=249  # genuinely white pixels in the source itself


@pytest.mark.parametrize("reduced",[False,True])
def test_copy_fade_pair_tracking_and_start_geometry(scene,reduced):
    from PyQt6.QtCore import QAbstractAnimation
    from PyQt6.QtGui import QFont,QFontMetricsF
    from gui.start_splash import TITLE_TRACKING_PX,COPY_FADE_MS,WELCOME_ZH
    make,_,_,_,_=scene;s=make(reduced_motion=reduced);s.start()
    assert s.copy_fade.duration()==COPY_FADE_MS==300
    assert s.welcome_title.text()==WELCOME_ZH and " " not in s.welcome_title.text()
    font=s.welcome_title.font();assert font.letterSpacingType()==QFont.SpacingType.AbsoluteSpacing
    assert font.letterSpacing()==pytest.approx(TITLE_TRACKING_PX)
    normal=QFont(font);normal.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,0.)
    assert QFontMetricsF(font).horizontalAdvance(WELCOME_ZH)>QFontMetricsF(normal).horizontalAdvance(WELCOME_ZH)+9
    button=s.start_button.geometry()
    if reduced:
        assert s.copy_fade.state()==QAbstractAnimation.State.Stopped
        assert [fx.opacity() for fx in s._copy_effects]==[1.,1.]
    else:
        for t,expected in [(0,0.),(75,.25),(150,.5),(300,1.)]:
            s.copy_fade.setCurrentTime(t)
            assert [fx.opacity() for fx in s._copy_effects]==pytest.approx([expected]*2,abs=.01)
            assert s.start_button.geometry()==button and s.start_button.isEnabled()
    s.shutdown()


@pytest.mark.parametrize("action",["Start","Escape","close"])
def test_immediate_action_cancels_bilingual_fade(scene,action):
    from PyQt6.QtCore import QAbstractAnimation
    make,_,host,_,_=scene;s=make();s.start()
    assert s.copy_fade.state()==QAbstractAnimation.State.Running
    s.copy_fade.setCurrentTime(20)
    if action=="Start": QTest.mouseClick(s.start_button, Qt.MouseButton.LeftButton)
    elif action=="Escape": QTest.keyClick(s,Qt.Key.Key_Escape)
    else: host.close()
    assert s.phase=={"Start":"reveal","Escape":"docked","close":"closed"}[action]
    assert s.copy_fade.state()==QAbstractAnimation.State.Stopped
    assert not any(lbl.isVisible() for lbl in (s.welcome_title,s.welcome_subtitle))


@pytest.mark.parametrize("first_ms,work_ms",[(795,47),(895,45)])
def test_actual_first_frame_sets_clock_slow_backend45_ms_is_not_mute(scene,first_ms,work_ms):
    from gui.start_splash import HD_LONG_PROFILE
    log=[]
    class Spy:
        def play(self): log.append(("play",s.clock.ms))
        def stop(self): log.append(("stop",s.clock.ms))
    def factory(path):
        s.clock.ms+=2
        log.append(("construct",s.clock.ms))
        s.clock.ms+=work_ms-2
        return Spy()
    s,_,_=_arm_test_shot(scene,factory)
    s.start_button.click();s.pulse.stop()
    _step(s,605);_step(s,770)  # a true intermediate, not a coarse request for #119
    assert s.native_start_ms is None and not log
    _step(s,first_ms)
    assert s.clip.profile==HD_LONG_PROFILE and s.native_start_ms==first_ms
    assert log==[("construct",first_ms+2),("play",first_ms+work_ms)]
    assert s.audio_status=="play-request-accepted"
    _step(s,first_ms+1732);assert s.phase=="laugh" and s.frame_index==51
    _step(s,first_ms+1733);assert s.phase=="slide" and log[-1]==("stop",first_ms+1733)
    _step(s,first_ms+2533);assert s.phase=="docked" and s.dock.image is s.smile


def test_undistorted_independent_dock_not_morph_or_last_source_frame(scene,monkeypatch):
    import gui.start_splash as gm
    s,_,_=_arm_test_shot(scene,None)
    assert s.smile!=s.clip.frames[51] and s.dock.image is s.smile
    art=[]
    def capture(p,img,rect,*a,**kw):
        if img is s.smile:
            art.append((rect.width()/rect.height(),kw["crop"].width()/kw["crop"].height()))
        return paint_frame(p,img,rect,*a,**kw)
    monkeypatch.setattr(gm,"paint_frame",capture)
    s.start_button.click();s.pulse.stop()
    for ms in (790,2500,2523,2770): _step(s,ms)
    assert s.phase=="slide" and not art
    for ms in (3180,3323):_step(s,ms);s.repaint()
    s.dock.grab()
    assert s.phase=="docked" and art and all(a==pytest.approx(b,rel=1e-5) for a,b in art)

def test_late_flight_changes_expression_over_many_frames_with_exact_stop_pose(scene,monkeypatch):
    import gui.start_splash as gm
    s,_,_=_arm_test_shot(scene,None);s.start_button.click();s.pulse.stop()
    _step(s,790);end=790+1733;_step(s,end)
    assert s.phase=="slide" and len(s._dock_frames)>=12
    samples=[]; trace=[]
    def capture(p,img,rect,*args,**kw):
        if img is s.smile: tag="native-stop"
        elif img is s.clip.frames[51]: tag="native-last"
        else: tag=next((i for i,f in enumerate(s._dock_frames) if img is f),None)
        trace.append(tag)
        return paint_frame(p,img,rect,*args,**kw)
    monkeypatch.setattr(gm,"paint_frame",capture)
    for t in range(590,798,5):
        _step(s,end+t);trace.clear();s.repaint()
        assert trace
        samples.append((t,trace[-1],s.dock_progress))
    assert samples[0][1]=="native-last" and samples[-1][1]=="native-stop"
    visible=[x for _,x,_ in samples if isinstance(x,int)]
    assert len(set(visible))>=12 and visible==sorted(visible)
    assert all(u[2]<=v[2] for u,v in zip(samples,samples[1:]))
    _step(s,end+800)
    assert s.phase=="docked" and s.dock.image is s.smile and s.dock_progress==1


def test_escape_in_expression_settle_shows_only_natural_native_pose(scene):
    s,_,_=_arm_test_shot(scene,None);s.start_button.click();s.pulse.stop()
    for ms in (790,790+1733,790+1733+722): _step(s,ms)
    assert s.phase=="slide" and .25<s.dock_progress<.85
    s.skip();s._advance()
    assert s.phase=="docked" and s.dock.image is s.smile and not s.pulse.isActive()

def test_high_res_corner_uses_clean_0005_real_alpha_not_a_laugh_frame(scene):
    from gui.start_splash import _clean_hd_backdrop
    s,_,_=_arm_test_shot(scene,None)
    assert s.dock_source=="side-eye-0005"
    assert s.smile.size()==s.side.size()!=s.clip.frames[0].size()
    assert s.smile==_clean_hd_backdrop(s.side)
    s.skip();assert s.dock.image==s.smile and s.phase=="docked"
