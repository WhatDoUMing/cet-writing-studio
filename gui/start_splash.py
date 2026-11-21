"""The local CET startup portrait. No network access, audio modules or device setup."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from random import randint

from PyQt6.QtCore import QElapsedTimer, QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QRegion
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QPushButton, QWidget

from gui.styles import ui_font_stack


STARTUP_REQUIRED_MEDIA = ("startup-v4.json",)
START_KEYS = (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Space)
REVEAL_MS, BRIDGE_MS, LAUGH_MS, SLIDE_MS = 600, 190, 1000, 800
WELCOME_ZH = "欢迎你奶家人"
WELCOME_EN = "Welcome to the CET-4 & CET-6 Writing Grader"
COPY_FADE_MS, TITLE_TRACKING_PX = 300, 2.5
# In the unflipped 1320x1864 portrait: both pupils, neither mouth nor body.
# Across this real eye band the visible right head contour runs from x=689 to 755.
# Show the shoulder of that curve and >50px of its own white background, without zoom distortion.
EYE_WINDOW = (319., 178., 490., 114.)
# Midpoint of visible eyes plus their horizontal span, measured on the exact originals.
SIDE_FACE = (448/1320, 242/1864, 129/1320)
LAUGH_FACE = (68/200, 30/200, 30/200)  # 0325 frame zero: both eyes and the full head are visible.
SAFE_STILLS = {".png", ".jpg", ".jpeg", ".webp"}
ANIMATION_BYTES = 192 * 1024**2


@dataclass
class LaughClip:
    frames: list
    ends: list
    dock: int
    start_ms: int = 0
    profile: str = "classic-0325"
    duration_ms: int = LAUGH_MS
    dock_still: QImage | None = None
    anticipation: tuple[QImage, ...] = ()

    def index_at(self, elapsed):
        # Retain the original GIF cadence and the approved starting pose.
        if elapsed >= self.duration_ms:
            return self.dock
        t = (self.start_ms + elapsed) % self.ends[-1]
        return bisect_right(self.ends, t)


def _file(root, name, extensions):
    if not isinstance(name, str) or not name or Path(name).name != name or ":" in name:
        raise ValueError("Expected a local asset basename")
    path = root / name
    if path.suffix.lower() not in extensions or path.resolve().parent != root.resolve():
        raise ValueError("Unexpected local asset type or path")
    if not path.is_file() or path.stat().st_size > 48 * 1024**2:
        raise ValueError("Missing or oversized local asset")
    return path


def _long_asset(root, expected):
    # Only fixed names explicitly computed from the f119..170 shot are accepted;
    # old manifests retain their stricter basename-only contract.
    parent=root/Path(expected).parent
    if parent.resolve() != root.resolve()/Path(expected).parent:
        raise ValueError("Unexpected long-clip asset directory")
    return _file(parent, Path(expected).name, {Path(expected).suffix})


def _reader(path):
    r = QImageReader(str(path))
    size = r.size()
    if size.isEmpty() or size.width() * size.height() > 12_000_000:
        raise ValueError("Unexpected image dimensions")
    return r


def _frame(reader):
    frame = reader.read()
    if frame.isNull():
        raise ValueError("Undecodable local image")
    return frame


def read_scene(root):
    try:
        manifest = _file(root, STARTUP_REQUIRED_MEDIA[0], {".json"})
        if manifest.stat().st_size > 65536:
            raise ValueError("Manifest too large")
        spec = json.loads(manifest.read_text("utf-8-sig"))
        if not isinstance(spec, dict) or spec.get("version") != 4:
            raise ValueError("Expected the V4 manifest")
        portrait = _frame(_reader(_file(root, spec["portrait"], SAFE_STILLS)))
        if portrait.width() >= portrait.height():
            raise ValueError("Expected upright side-eye portrait")
        # Optional crop registration describes the full original normalized eye coordinates.
        # Default is the unchanged 0005 composition in either its native or proportional size.
        registration = spec.get("eye_reference", [0, 0, 1320, 1864])
        if (not isinstance(registration, list) or len(registration) != 4
                or not all(isinstance(n, (float, int)) and -20000 <= n <= 20000 for n in registration)
                or min(registration[2:]) <= 0):
            raise ValueError("Invalid portrait registration")
        laugh = spec.get("laugh")
        if not isinstance(laugh, dict):
            raise ValueError("Expected a laugh manifest object")
        profile=laugh.get("profile","classic-0325")
        if profile not in ("classic-0325", HD_PROFILE, *HD_NATIVE_PROFILES):
            raise ValueError("Unknown portrait/sequence registration")
        is_long=profile in HD_NATIVE_PROFILES
        is_fade=profile==HD_FADE_PROFILE
        native_count,native_duration,asset_dir=(102,3400,FADE_DIR) if is_fade else (52,1733,LONG_DIR)
        if is_long and (not isinstance(laugh.get("frames"),list) or len(laugh["frames"])!=native_count
                        or laugh.get("dock_portrait") not in (LONG_DOCK,spec["portrait"])):
            raise ValueError("Expected an exact native shot and separate natural dock still")
        budget = (640 if is_fade else 336)*1024**2 if is_long else ANIMATION_BYTES
        images, ends = [], []
        used = total = 0

        def add(img, ms):
            nonlocal used, total
            if type(ms) is not int or not 10 <= ms <= 1000:
                raise ValueError("Invalid animation frame duration")
            used += img.sizeInBytes()
            if used > budget or (images and img.size() != images[0].size()):
                raise ValueError("Animation budget or canvas mismatch")
            total += ms
            images.append(img)
            ends.append(total)

        if "frames" in laugh and "file" not in laugh:
            raw = laugh["frames"]
            if not isinstance(raw, list) or not 2 <= len(raw) <= 150:
                raise ValueError("Expected a bounded multi-frame clip")
            for n,item in enumerate(raw):
                if not isinstance(item, dict):
                    raise ValueError("Expected an animation frame object")
                if is_long:
                    expected=f"{asset_dir}/frames/{n:03}.png"
                    if item["file"]!=expected:
                        raise ValueError("The long shot must retain native frame order")
                    expected_ms=round((n+1)*1000/30)-round(n*1000/30)
                    if item["ms"]!=expected_ms:
                        raise ValueError("The long shot must retain native cadence")
                    path=_long_asset(root,expected)
                else:
                    path=_file(root,item["file"],SAFE_STILLS)
                add(_frame(_reader(path)),item["ms"])
        elif "file" in laugh and "frames" not in laugh:
            reader = _reader(_file(root, laugh["file"], {".gif", ".webp"}))
            count = reader.imageCount()
            if not reader.supportsAnimation() or not 2 <= count <= 150:
                raise ValueError("Expected a real GIF or animated WebP")
            for _ in range(count):
                img = _frame(reader)
                add(img, reader.nextImageDelay())
        else:
            raise ValueError("Expected exactly one clip representation")
        offset = laugh.get("start_ms", 0)
        if type(offset) is not int or not 0 <= offset < total:
            raise ValueError("Invalid native start time")
        dock = laugh.get("dock", bisect_right(ends, (offset + LAUGH_MS - 1) % total))
        if type(dock) is not int or not 0 <= dock < len(images):
            raise ValueError("Invalid frozen expression")
        if is_long and (total!=native_duration or offset!=0 or dock!=native_count-1):
            raise ValueError("Invalid duration or stop frame for the registered native shot")
        dock_still=None
        if is_long:
            # Use the complete clean side-eye portrait, not a laugh frame. Older
            # private contracts may still name f375; never load or display it here.
            dock_still=portrait
        if profile==HD_PROFILE and (len(images)!=30 or total!=1000 or offset!=0 or dock!=29):
            raise ValueError("The native f119-to-f148 shot must be exactly one second")
        anticipation=[]
        if is_fade:
            refs=[f"{FADE_DIR}/anticipation/{n:03}.png" for n in range(6)]
            if laugh.get("anticipation")!=refs:
                raise ValueError("Expected the exact ordered closed-mouth anticipation")
            for name in refs:
                reader=_reader(_long_asset(root,name))
                if reader.size()!=images[0].size():
                    raise ValueError("Unexpected anticipation canvas")
                anticipation.append(_frame(reader))
        clip=LaughClip(images,ends,dock,offset,profile,total if is_long else LAUGH_MS,dock_still,tuple(anticipation))
        sample_ids = {clip.index_at(ms) for ms in range(0, clip.duration_ms, 10)}
        first = images[clip.index_at(0)]
        if not any(images[i] != first for i in sample_ids):
            raise ValueError("A static image is not a laugh animation")
        return portrait, registration, clip
    except (OSError, ValueError, KeyError, TypeError, RecursionError, RuntimeError):
        return None

def _paperless_portrait(image):
    """Display-only: remove a uniform white exterior, never an enclosed highlight.

    The verified clean 0005 has opaque white corners; the original 0325 GIF is
    transparent. Both figures should sit on our same sheet, including in dark mode.
    Keep the source bytes, every original GIF pixel and the actor's own colours.
    """
    from PIL import Image, ImageDraw, ImageOps
    import numpy as np
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = rgba.width(), rgba.height()
    raw = np.frombuffer(rgba.constBits().asstring(rgba.sizeInBytes()), np.uint8)
    pixels = raw.reshape(h, rgba.bytesPerLine())[:, :4*w].reshape(h, w, 4)
    corners = pixels[[0,0,h-1,h-1],[0,w-1,0,w-1]]
    if np.any(corners[:,:3] < 243) or np.any(corners[:,3] < 250):
        return image
    preview = Image.fromarray(pixels[:,:,:3])
    preview.thumbnail((512,640), Image.Resampling.LANCZOS)
    low = np.asarray(preview).astype(np.int16)
    base = low.min(axis=2)
    outside = (base >= 214) & ((low.max(axis=2)-base) <= 28)
    mask = Image.fromarray(np.where(outside,255,0).astype(np.uint8))
    bordered = ImageOps.expand(mask, border=1, fill=255)
    ImageDraw.floodfill(bordered,(0,0),128)
    border = np.asarray(bordered)[1:-1,1:-1]
    alpha = Image.fromarray(np.where(border==128,0,255).astype(np.uint8))
    alpha = alpha.resize((w,h), Image.Resampling.BILINEAR)
    result = pixels.copy()
    result[:,:,3] = np.minimum(result[:,:,3], np.asarray(alpha))
    return QImage(result.data,w,h,result.strides[0],QImage.Format.Format_RGBA8888).copy()


def _bridge_paper_layers(image, crop):
    """Separate only 0005's pale floor from its lower legs for the blink.

    The standing image remains byte-for-byte visually unchanged outside the
    bridge. Its enclosed cream triangle is not uniformly transparent. Fading
    this backdrop separately during the blink avoids a dark-mode pop without
    ever fading a second foot, hand or face over the moving one.
    """
    import numpy as np
    q=image.convertToFormat(QImage.Format.Format_RGBA8888)
    w,h=q.width(),q.height()
    raw=np.frombuffer(q.constBits().asstring(q.sizeInBytes()),np.uint8)
    data=raw.reshape(h,q.bytesPerLine())[:,:w*4].reshape(h,w,4)
    top=max(0,min(h-1,int(crop.top()+.70*crop.height())))
    region=data[top:];rgb=region[:,:,:3].astype(np.int16)
    warm=(rgb[:,:,0]-rgb[:,:,2]>30)&(rgb[:,:,1]-rgb[:,:,2]>12)
    warm&=(rgb[:,:,0]<206)|(rgb[:,:,2]<120)
    floor=(~warm)&(rgb.min(axis=2)>105)&(region[:,:,3]>0)
    if not floor.any():
        return image,None,top
    one=data.copy()
    one[top:,:,3][floor]=0
    tile=region.copy();tile[:,:,3][~floor]=0
    clean=QImage(one.data,w,h,one.strides[0],QImage.Format.Format_RGBA8888).copy()
    layer=QImage(tile.data,w,h-top,tile.strides[0],QImage.Format.Format_RGBA8888).copy()
    return clean,layer,top


# Each pair is the same anatomical landmark in the two fitted crops. Units are
# a 400 x 480 registration grid, not screen pixels. The GIF cuts its ankles:
# both old toes therefore converge to the two *separate* cut ankle edges.
# Source order must stay stable (the mouth indices below refer to this table).
_BRIDGE_MARKS = (
    # top/back of head; brows; far and near corners of the eyes
    (165,10,147,14),(99,48,80,72),(249,22,191,32),
    (104,39,83,74),(110,39,91,80),(144,36,139,69),(182,36,156,65),
    # left corner, upper middle, right corner, lower middle of the mouth
    (101,59,99,106),(119,58,133,109),(139,58,168,92),(121,61,134,143),
    (111,79,111,132),(133,95,138,156),(162,80,187,117),
    # far and near armpits / elbows / wrists / finger masses; belly
    (84,178,96,166),(20,202,45,214),(12,225,42,242),
    (40,205,126,281),(36,247,130,339),(68,228,146,308),
    (91,208,162,282),(121,246,191,328),(206,215,255,285),
    (221,170,253,211),(317,176,336,225),(286,235,284,307),
    (85,272,119,335),(167,289,176,365),(254,255,251,333),
    (35,215,120,294),(40,225,145,311),(39,237,144,325),
    (68,239,143,324),(84,250,165,339),(100,222,168,307),
    # hips, groin, two knees and ankle/heel contours
    (94,320,109,361),(203,342,205,405),(314,325,327,370),
    (100,365,115,410),(185,377,197,418),(244,372,260,420),(313,375,328,420),
    (152,413,124,455),(180,411,185,455),(270,427,276,454),(301,426,330,457),
    # independently pin each toe, sole and heel; do not fade two poses on top.
    (55,432,118,472),(63,444,125,479),(131,441,154,479),(202,436,181,466),
    (198,454,267,477),(208,467,280,479),(262,470,304,479),(320,452,335,479),
)

# Registered on the complete native 1080x1474 f119 canvas, after the stable
# f119..148 union crop (400x480 measurement grid). Unlike the 0325 GIF, both
# complete feet survive and both hands move *up* to the initial belly-laugh pose.
HD_PROFILE = "belly-hd-119"
HD_LONG_PROFILE = "belly-hd-119-170"
LONG_DIR = "hd-laugh-1733"
LONG_DOCK = LONG_DIR + "/dock-natural-f375.png"
LONG_WAV = LONG_DIR + "/laugh-long-a.wav"
HD_FADE_PROFILE = "belly-hd-first-055-156-3400"
FADE_DIR = "hd-laugh-first-055-3400"
FADE_WAV = FADE_DIR + "/laugh-fade-a.wav"
HD_NATIVE_PROFILES = (HD_LONG_PROFILE, HD_FADE_PROFILE)
FADE_SLIDE_START_MS = 2900
NATIVE_PREROLL_MS = 200
AUDIO_START_GRACE_MS = 100
NATIVE_PAINT_GRACE_MS = 100
_AUDIO_LOG = logging.getLogger("cet.startup.audio")
_HD_MARKS = (
    (183,10),(116,38),(226,23),(119,34),(132,35),(184,27),(219,29),
    (128,55),(162,46),(205,52),(165,97),(128,85),(152,109),(203,88),
    (91,163),(22,179),(11,201),(91,182),(84,227),(153,176),
    (191,160),(218,211),(270,207),(271,172),(339,164),(343,218),
    (85,265),(170,294),(264,263),(86,196),(90,205),(89,216),
    (154,187),(159,198),(179,183),
    (100,326),(211,356),(324,329),(98,370),(160,371),(247,385),(313,377),
    (140,412),(166,411),(292,432),(323,429),(67,429),(75,440),
    (130,436),(185,432),(246,451),(256,465),(298,471),(333,449),
)
_HD_BOUNDARY = (
    (183,10),(226,23),(366,176),(359,273),(324,329),(323,429),
    (333,449),(298,471),(256,465),(246,451),(292,432),(211,356),
    (166,411),(185,432),(130,436),(75,440),(67,429),(140,412),
    (100,326),(69,245),(11,201),(22,179),(92,151),(119,112),
    (120,67),(116,38),
)


def _clean_hd_backdrop(image):
    """Display matte for the HD white soundstage; preserve enclosed teeth and eyes.

    Alpha comes from the photographed material's real edge, not generated
    detail. Treat the pale floor between the two feet as backdrop, never as a
    third foot. Source PNGs remain untouched, including all stored RGB values.
    """
    import cv2
    import numpy as np
    img=image.convertToFormat(QImage.Format.Format_RGBA8888)
    h,w=img.height(),img.width()
    raw=np.frombuffer(img.constBits().asstring(img.sizeInBytes()),np.uint8)
    src=raw.reshape(h,img.bytesPerLine())[:,:w*4].reshape(h,w,4)
    sw=min(w,560);sh=max(1,round(h*sw/w))
    small=cv2.resize(src,(sw,sh),interpolation=cv2.INTER_AREA)
    rgb=small[:,:,:3].astype(np.int16)
    gold=(rgb[:,:,0]-rgb[:,:,2]>27)&(rgb[:,:,1]-rgb[:,:,2]>11)
    gold|=(rgb.min(2)<118)&(rgb.max(2)<188)
    low=round(sh*.70)
    gold[low:]&=(rgb[low:,:,0]<203)|(rgb[low:,:,2]<120)|((rgb[low:,:,0]-rgb[low:,:,2])>78)
    mask=(gold&(small[:,:,3]>20)).astype(np.uint8)
    cnts,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:return image
    body=np.zeros_like(mask)
    cv2.drawContours(body,[max(cnts,key=cv2.contourArea)],-1,255,cv2.FILLED)
    body[low:]&=mask[low:]*255
    alpha=cv2.resize(body,(w,h),interpolation=cv2.INTER_LINEAR)
    rgba=src.copy();rgba[:,:,3]=np.minimum(src[:,:,3],alpha)
    return QImage(rgba.data,w,h,rgba.strides[0],QImage.Format.Format_RGBA8888).copy()


def _hd_feature_maps(cv2, np, map_a, map_b, xx, yy, t):
    """Continuous local maps of the lip opening and the two turning hands.

    A triangulation can fold between an almost closed lip and a wide mouth,
    distorting teeth into little spikes. Map upper and lower lip curves in the
    same coordinate system, and move each hand as one rotating local surface.
    Geometry belongs to one subject throughout, not two crossfaded characters.
    """
    h,w=xx.shape
    fx,fy=(w-1)/400,(h-1)/480
    X,Y=xx/fx,yy/fy
    # Rigid-ish registrations anchored at the wrist, first finger and thumb.
    for a,b in (
        ([(134,231),(67,228),(92,208)],[(213,198),(164,164),(195,158)]),
        ([(16,219),(40,205),(39,237)],[(65,199),(90,182),(87,211)]),
    ):
        pa=np.float32(a);pb=np.float32(b);pd=pa+(pb-pa)*t
        center=pd.mean(0)
        dx=X-center[0];dy=Y-center[1]
        rx=45 if a[0][0]>50 else 30
        ry=33 if a[0][0]>50 else 34
        radial=np.sqrt((dx/rx)**2+(dy/ry)**2)
        u=np.clip((1.55-radial)/.68,0,1);weight=(u*u*(3-2*u))[:,:,None]
        for mp,end in ((map_a,pa),(map_b,pb)):
            mt=cv2.getAffineTransform(pd,end)
            ux=(X*mt[0][0]+Y*mt[0][1]+mt[0][2])*fx
            uy=(X*mt[1][0]+Y*mt[1][1]+mt[1][2])*fy
            mp[:]=mp*(1-weight)+np.dstack([ux,uy])*weight
    # left x/y, right x/y, aperture center top/bottom y in the two real poses.
    a=np.array([99.5,60.,140.,59.,58.6,61.],np.float32)
    b=np.array([126.5,61.,207.,55.5,46.5,98.],np.float32)
    d=a+(b-a)*t
    u=(X-d[0])/(d[2]-d[0]);uc=np.clip(u,0,1)
    bulge=np.maximum(0.,np.sin(np.pi*uc))**.64
    def bounds(k):
        base=k[1]+uc*(k[3]-k[1]);middle=(k[1]+k[3])*.5
        return base+(k[4]-middle)*bulge,base+(k[5]-middle)*bulge
    du,dl=bounds(d);dz=np.maximum(dl-du,1.)
    # Core includes the lip and chin rim; the neighbouring skin blends to
    # the feature mesh smoothly. No triangles cross the teeth.
    edge_x=np.maximum(-u,u-1.)*(d[2]-d[0])
    edge_y=np.maximum(du-Y,Y-dl)
    region=np.clip(1.-np.maximum(edge_x/9.,edge_y/13.),0.,1.)
    region=(region*region*(3.-2.*region)).astype(np.float32)
    for mp,endpoint in ((map_a,a),(map_b,b)):
        up,low=bounds(endpoint); ratio=np.clip((Y-du)/dz,0.,1.)
        new_y=up+ratio*np.maximum(low-up,.65)+np.minimum(Y-du,0)+np.maximum(Y-dl,0)
        new_x=endpoint[0]+u*(endpoint[2]-endpoint[0])
        new=np.dstack([new_x*fx,new_y*fy])
        mp[:]=mp*(1-region[:,:,None])+new*region[:,:,None]
    return region


def _morph_frames(side, side_crop, first, laugh_crop, steps=30, *, profile="classic-0325"):
    """A registered surface moves once, within one interpolated boundary.

    In particular, the original mouth is a line which opens into a real GIF
    interior, and the two feet terminate at the GIF's two cropped ankle edges.
    These in-memory transition images never change the native GIF or its clock.
    """
    import cv2
    import numpy as np
    from PIL import Image

    w,h=(384,460) if profile==HD_PROFILE else (292,350)
    def raster(img,crop):
        q=img.convertToFormat(QImage.Format.Format_RGBA8888)
        raw=np.frombuffer(q.constBits().asstring(q.sizeInBytes()), np.uint8)
        raw=raw.reshape(q.height(),q.bytesPerLine())[:,:q.width()*4].reshape(q.height(),q.width(),4)
        return np.array(Image.fromarray(raw).resize((w,h),Image.Resampling.LANCZOS,
                 box=(crop.left(),crop.top(),crop.right(),crop.bottom())),copy=True)
    def field(pic, side=False):
        a=pic[:,:,3:4].astype(np.float32)/255
        mask=(a[:,:,0]>.48).astype(np.uint8)
        # The 0005 source has a very faint cream floor reflection below its feet.
        # It is paper, not an extra foot. Use a connected colour outline only for
        # this transient matte; all enclosed highlights, eyes and teeth survive.
        rgb=pic[:,:,:3].astype(np.int16)
        warm=(rgb[:,:,0]-rgb[:,:,2]>30)&(rgb[:,:,1]-rgb[:,:,2]>12)
        if side:
            # 0005's legs enclose an opaque *white* triangular patch and
            # a beige floor shadow (RGB 224/210/184 vs the dark warm toes).
            # Their source alpha alone cannot identify either as floor.
            low=int(.70*h)
            warm[low:] &= (rgb[low:,:,0]<206)|(rgb[low:,:,2]<120)
        support=(mask*warm).astype(np.uint8)
        if .04<support.mean()<.96:
            contours,_=cv2.findContours(support,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                body=np.zeros_like(mask)
                cv2.drawContours(body,[max(contours,key=cv2.contourArea)],-1,1,cv2.FILLED)
                # Feet can touch at a single pixel, enclosing backdrop
                # between the legs. It must stay outside the silhouette.
                lower=int(.69*h)
                body[lower:]=support[lower:]
                mask=body
        if not mask.any() or mask.all(): # unregistered solid synthetic fixtures.
            return np.full((h,w),float(2*int(mask.any())-1)*32,np.float32)
        return cv2.distanceTransform(mask,cv2.DIST_L2,5)-cv2.distanceTransform(1-mask,cv2.DIST_L2,5)
    A=raster(side,side_crop);B=raster(first,laugh_crop)
    sdA,sdB=field(A,True),field(B)
    def tex(pic,sd):
        # Nearest subject texel colour even just outside its old edge, so the
        # signed-distance contour has no dark/white/see-through rim after a warp.
        fg=((pic[:,:,3]>210)&(sd>1.3)).astype(np.uint8)
        if not fg.any() or fg.all(): return pic[:,:,:3].copy()
        _,labels=cv2.distanceTransformWithLabels(1-fg,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
        opaque=fg.astype(bool);lookup=np.zeros((int(labels.max())+1,3),np.uint8)
        lookup[labels[opaque]]=pic[:,:,:3][opaque]
        return np.where(fg[:,:,None].astype(bool),pic[:,:,:3],lookup[labels])
    ta,tb=tex(A,sdA),tex(B,sdB)
    marks=np.array(_BRIDGE_MARKS,np.float32).reshape(-1,2,2)
    if profile==HD_PROFILE:
        marks[:,1,:]=np.asarray(_HD_MARKS,np.float32)
    # Perimeter points remain fixed, outside all anatomical correspondence.
    edges=((0,0),(200,0),(400,0),(400,240),(400,480),(225,480),(0,480),(0,240))
    marks=np.concatenate([marks,np.repeat(np.array(edges,np.float32)[:,None,:],2,axis=1)])
    marks*=np.array([(w-1)/400,(h-1)/480],np.float32)
    ma,mb=marks[:,0].copy(),marks[:,1].copy()
    mid=.5*(ma+mb);sub=cv2.Subdiv2D((0,0,w,h))
    for point in mid:sub.insert(tuple(map(float,point)))
    triangles=[]
    for xy in sub.getTriangleList().reshape(-1,3,2):
        dist=((mid[None,:,:]-xy[:,None,:])**2).sum(2)
        ids=dist.argmin(1)
        if dist.min(1).max()<.01:triangles.append(ids)
    def outline(sd):
        mask=(sd>0).astype(np.uint8)
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        if not contours:return None
        poly=max(contours,key=cv2.contourArea)[:,0,:].astype(np.float32)
        # In image coordinates increasing angle around the outline is clockwise.
        if cv2.contourArea(poly,oriented=True)<0:poly=poly[::-1]
        return poly
    # Clockwise anatomical marks, including BOTH edges of both feet and the
    # crotch. Corresponding arcs (not just the outer left/right row limits)
    # produce exactly one continuous contour between the two original bodies.
    boundary_ref=np.array([
        (165,10,147,14),(249,22,191,32),(350,180,338,200),(380,260,370,306),
        (314,325,327,370),(301,426,330,457),(320,452,335,479),(262,470,304,479),
        (208,467,280,479),(198,454,270,474),(270,427,276,454),(203,342,205,405),
        (180,411,185,455),(202,436,183,479),(131,441,154,479),(63,444,125,479),
        (55,432,120,470),(152,413,119,455),(94,320,109,361),(30,250,74,306),
        (12,225,42,242),(20,202,45,214),(94,149,97,135),(122,98,97,123),
        (101,59,80,78),(99,48,80,72)],np.float32).reshape(-1,2,2)
    if profile==HD_PROFILE:
        boundary_ref[:,1,:]=np.asarray(_HD_BOUNDARY,np.float32)
    boundary_ref*=np.array([(w-1)/400,(h-1)/480],np.float32)
    def register_outline(sd,marks):
        poly=outline(sd)
        if poly is None or len(poly)<100:return None
        # Nearest sequential contour point. A calf and the far toe can project
        # close together; allow coincident guide points, never reverse direction.
        start=int(np.argmin(((poly-marks[0])**2).sum(1)))
        poly=np.roll(poly,-start,axis=0);n=len(poly)
        poly=np.vstack((poly,poly[:1]));at=[0];last=0
        for mark in marks[1:]:
            end=min(n,last+int(.24*n))
            idx=last+int(np.argmin(((poly[last:end+1]-mark)**2).sum(1)))
            at.append(idx);last=idx
        at.append(n)
        pts=[]
        for lo,hi in zip(at,at[1:]):
            seg=poly[lo:hi+1]
            if len(seg)==1:pts.extend([seg[0]]*12);continue
            dist=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(seg,axis=0),axis=1))]
            q=dist[-1]*np.arange(12)/12
            pts.extend(np.column_stack([np.interp(q,dist,seg[:,k]) for k in (0,1)]))
        return np.array(pts,np.float32)
    registered=register_outline(sdA,boundary_ref[:,0]),register_outline(sdB,boundary_ref[:,1])
    use_contour=all(k is not None for k in registered) and not (np.all(sdA>0) or np.all(sdB>0))
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    base_map=np.dstack([xx,yy])
    # The GIF's oral cavity is introduced as soon as there is space for
    # it, not via a sudden dark texture swap halfway through the bridge.
    mouth_source=np.zeros((h,w),np.uint8)
    mouth_poly=mb[[7,8,9,10]]
    cv2.fillConvexPoly(mouth_source,np.int32(np.rint(mouth_poly*16)),255,lineType=cv2.LINE_AA,shift=4)
    mouth_source=cv2.GaussianBlur(mouth_source,(7,7),1.15)
    result=[]
    for i in range(1,steps):
        t=i/steps; dst=ma+(mb-ma)*t
        mapA=base_map.copy();mapB=base_map.copy()
        for ids in triangles:
            dd=dst[ids]; aa=ma[ids];bb=mb[ids]
            x0,y0=np.maximum(0,np.floor(dd.min(0))).astype(int)
            x1,y1=np.minimum([w,h],np.ceil(dd.max(0))+1).astype(int)
            if x1<=x0 or y1<=y0: continue
            v1,v2=(dd[1:]-dd[0])
            det=float(v1[0]*v2[1]-v1[1]*v2[0])
            if abs(det)<.005: continue
            xxr=xx[y0:y1,x0:x1]-dd[0,0];yyr=yy[y0:y1,x0:x1]-dd[0,1]
            k1=(xxr*v2[1]-yyr*v2[0])/det; k2=(yyr*v1[0]-xxr*v1[1])/det
            inside=(k1>=-.0001)&(k2>=-.0001)&((k1+k2)<=1.0001)
            j,k=np.nonzero(inside)
            u=k1[j,k,None];v=k2[j,k,None];j+=y0;k+=x0
            mapA[j,k]=aa[0]+u*(aa[1]-aa[0])+v*(aa[2]-aa[0])
            mapB[j,k]=bb[0]+u*(bb[1]-bb[0])+v*(bb[2]-bb[0])
        def warp(arr,fieldmap):
            return cv2.remap(arr,fieldmap,None,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        for mp in (mapA,mapB):
            delta=mp-base_map
            mp[:]=base_map+cv2.GaussianBlur(delta,(0,0),1.35,
                        borderType=cv2.BORDER_REPLICATE)
        hd_mouth=_hd_feature_maps(cv2,np,mapA,mapB,xx,yy,t) if profile==HD_PROFILE else None
        if use_contour:
            path=registered[0]*(1.-t)+registered[1]*t
            painted=np.zeros((h,w),np.uint8)
            cv2.fillPoly(painted,[np.int32(np.rint(path*16))],255,lineType=cv2.LINE_AA,shift=4)
            alpha=painted.astype(np.float32)/255.
        else:
            # Flat/non-anatomical synthetic fixtures can lack an outer contour.
            da,db=warp(sdA,mapA),warp(sdB,mapB)
            alpha=np.clip(.5+((1.-t)*da+t*db)/1.5,0.,1.)
        oa,ob=warp(ta,mapA),warp(tb,mapB)
        # Native 0325 has a 1–2 px pale antialiased rim on the bottom
        # of its cropped legs. Hand that original edge back before frame 0;
        # the role itself is already the registered GIF pose here.
        if profile!="belly-hd-119" and use_contour and t>.82:
            z=(t-.82)/.18; z=z*z*(3.-2.*z)
            ba=warp(B[:,:,3],mapB).astype(np.float32)/255.
            rim=np.clip(1.-np.abs(warp(sdB,mapB))/5.,0.,1.)
            alpha=alpha+(ba-alpha)*z*rim
            b_native=warp(B[:,:,:3],mapB)
            ow=(z*rim*ba)[:,:,None]
            ob=ob*(1.-ow)+b_native*ow
        oral=warp(mouth_source,mapB).astype(np.float32)/255.
        # Gradual material transfer everywhere else. The *shape* is controlled
        # by registered points, including top/bottom lips and both hands.
        if hd_mouth is not None:
            oral=np.maximum(oral,hd_mouth)
        mouth_mix=np.clip(t/(.18 if profile==HD_PROFILE else .28),0.,1.)
        mix=t+(1.-t)*(mouth_mix*mouth_mix*(3.-2.*mouth_mix))*oral
        rgba=np.empty((h,w,4),np.uint8)
        rgba[:,:,:3]=np.rint(oa*(1.-mix[:,:,None])+ob*mix[:,:,None]).clip(0,255).astype(np.uint8)
        rgba[:,:,3]=np.rint(alpha*255).astype(np.uint8)
        result.append(QImage(rgba.data,w,h,rgba.strides[0],QImage.Format.Format_RGBA8888).copy())
    return result


# f170 to the original clean 0005 portrait; positions normalized to 270 x 368.5.
# In particular: matching upper/lower lips, near/far eyelids, individual thumb
# tips and palms are not interchangeable with the nearby belly texture.
_DOCK_MARKS = (
    (149, 53, 116, 26),(170, 58, 137, 33),(181, 75, 147, 52),(191, 98, 157, 76),
    (115, 76, 77, 49),(119, 73, 79, 44),(124, 76, 81, 47.7),(119, 77, 78, 53),
    (146, 72, 94.5, 46.8),(154, 67.7, 104, 38.1),(164, 70, 114.1, 46.8),(154, 69.5, 104, 53.2),
    (122, 88.5, 77.4, 62.5),(141, 84, 84, 61.8),(157.5, 85, 94, 62.1),(139, 113, 84, 63.0),
    (129, 99, 80, 62.8),(151, 98, 91, 62.5),(138, 116, 86, 69),(125, 108, 86, 86),
    (105, 119, 76, 110),(77, 152, 44, 161),(71, 172, 35, 178),(82, 184, 36, 185),
    (82, 194, 38, 193),(99, 206, 47, 199),(94, 205, 44, 198),(105, 196, 49, 191),
    (102, 189, 49, 185),(101, 180, 50, 170),(104, 176, 50, 166),(86, 180, 38, 180),
    (85, 192, 40, 191),(161, 174, 98, 174),(149, 170, 77, 170),(143, 169, 72, 169),
    (142, 181, 77, 179),(130, 182, 61, 183),(128, 188, 60, 189),(129, 194, 62, 196),
    (137, 200, 68, 201),(150, 194, 85, 195),(160, 192, 98, 191),(173, 168, 105, 162),
    (190, 157, 130, 148),(192, 139, 135, 130),(227, 184, 196, 182),(233, 163, 192, 159),
    (211, 120, 176, 112),(86, 215, 46, 213),(99, 246, 56, 246),(127, 268, 84, 267),
    (182, 272, 152, 281),(211, 248, 190, 255),(221, 216, 205, 224),(99, 270, 73, 271),
    (110, 304, 95, 324),(81, 316, 56, 344),(81, 326, 57, 354),(130, 323, 118, 351),
    (128, 311, 115, 339),(141, 272, 121, 278),(160, 272, 127, 282),(187, 315, 154, 334),
    (166, 338, 125, 349),(174, 347, 128, 360),(200, 346, 171, 357),(206, 330, 178, 347),
    (201, 287, 176, 282),
)


DOCK_SETTLE_FROM, DOCK_SETTLE_TO = 610, 792
# Source #156 has the same belly-held posture as the verified #170,
# but different eyelids/lip opening. Register facial features on this exact
# original frame; the body stays as a single solid, recognizable actor.
_FADE_DOCK_SOURCE = tuple(
    {0:(143,52),1:(166,55),2:(175,68),3:(188,90),
     4:(112,74),5:(115,68),6:(122,73),7:(116,80),
     8:(141,69),9:(150,62),10:(157,68),11:(149,74),
     12:(116,88),13:(133,82),14:(154,85),15:(132,113),
     16:(120,99),17:(147,98),18:(132,117),19:(119,107)}.get(i,row[:2])
    for i,row in enumerate(_DOCK_MARKS)
)
_FADE_DOCK_MARKS=tuple((*p,*m[2:]) for p,m in zip(_FADE_DOCK_SOURCE,_DOCK_MARKS,strict=True))
_DOCK_MOUTH=(122,89,157.8,85.5,84,112.4)
_DOCK_EYE=(145.5,72,164.3,70.75,67.7,70.)


def _dock_inbetweens(last, last_crop, still, still_crop, steps=14, *, fade_shot=False):
    """One evolving registered surface; the PNG sources and final pose stay untouched."""
    import cv2
    import numpy as np
    from PIL import Image

    w=212; h=round(w*last_crop.height()/last_crop.width())
    def data(q,crop):
        img=q.convertToFormat(QImage.Format.Format_RGBA8888)
        arr=np.frombuffer(img.constBits().asstring(img.sizeInBytes()),np.uint8)
        arr=arr.reshape(img.height(),img.bytesPerLine())[:,:img.width()*4].reshape(img.height(),img.width(),4)
        b=(crop.left(),crop.top(),crop.right(),crop.bottom())
        pil=Image.fromarray(arr)
        if b[0]<0 or b[1]<0 or b[2]>pil.width or b[3]>pil.height:
            lo=np.floor(b[:2]).astype(int);hi=np.ceil(b[2:]).astype(int)
            pil=pil.crop((*lo,*hi));b=tuple(np.array(b)-np.tile(lo,2))
        rgb=np.array(pil.resize((w,h),Image.Resampling.LANCZOS,box=b),copy=True)
        fg=(rgb[:,:,3]>=128).astype(np.uint8)
        if fg.all() or not fg.any():
            return rgb[:,:,:3],np.full((h,w),255. if fg.any() else -255.,np.float32)
        # Extend edge colour for subpixel sampling. Alpha below comes from one
        # interpolated signed-distance field, never two stacked silhouettes.
        _,ids=cv2.distanceTransformWithLabels(1-fg,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
        ok=fg.astype(bool); palette=np.zeros((int(ids.max())+1,3),np.uint8)
        palette[ids[ok]]=rgb[:,:,:3][ok]
        sdf=cv2.distanceTransform(fg,cv2.DIST_L2,5)-cv2.distanceTransform(1-fg,cv2.DIST_L2,5)
        return np.where(ok[:,:,None],rgb[:,:,:3],palette[ids]),sdf
    a,sa=data(last,last_crop); b,sb=data(still,still_crop)
    def control(q,crop,offset):
        pt=np.asarray(_FADE_DOCK_MARKS if fade_shot else _DOCK_MARKS,np.float32)[:,offset:offset+2].copy()
        pt[:,0]=(pt[:,0]*q.width()/270-crop.left())*(w-1)/crop.width()
        pt[:,1]=(pt[:,1]*q.height()/368.5-crop.top())*(h-1)/crop.height()
        return np.vstack([np.clip(pt,[1.,1.],[w-2.,h-2.]),[[0,0],[w//2,0],[w-1,0],
                         [w-1,h//2],[w-1,h-1],[w//2,h-1],[0,h-1],[0,h//2]]]).astype(np.float32)
    pa,pb=control(last,last_crop,0),control(still,still_crop,2)
    mid=(pa+pb)*.5
    sub=cv2.Subdiv2D((0,0,w,h))
    for xy in mid:sub.insert(tuple(map(float,xy)))
    tris=[]
    for face in sub.getTriangleList().reshape(-1,3,2):
        dist=((face[:,None,:]-mid[None,:,:])**2).sum(2)
        if dist.min(1).max()<.001:tris.append(dist.argmin(1))
    yy,xx=np.mgrid[:h,:w].astype(np.float32); base=np.dstack([xx,yy])
    result=[]
    for n in range(1,steps):
        t=n/steps; dst=pa+(pb-pa)*t
        ma=base.copy();mb=base.copy()
        for ids in tris:
            v=dst[ids];x0,y0=np.floor(v.min(0)).astype(int);x1,y1=np.ceil(v.max(0)).astype(int)+1
            a1,a2=v[1:]-v[0];det=float(a1[0]*a2[1]-a2[0]*a1[1])
            if abs(det)<.02:continue
            x=xx[y0:y1,x0:x1]-v[0,0];y=yy[y0:y1,x0:x1]-v[0,1]
            u=(x*a2[1]-y*a2[0])/det;z=(a1[0]*y-a1[1]*x)/det
            j,k=np.nonzero((u>=-.0001)&(z>=-.0001)&(u+z<=1.0001))
            c=u[j,k,None];d=z[j,k,None]
            for field,end in ((ma,pa[ids]),(mb,pb[ids])):
                field[j+y0,k+x0]=end[0]+c*(end[1]-end[0])+d*(end[2]-end[0])
        def warp(image,field):
            return cv2.remap(image,field,None,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        # Transfer lip/eye textures through the actual aperture, not through a
        # dissolve between two mouth lines. Both local maps share one opening.
        def aperture(coords,q,c):
            h4=np.array(coords,np.float32)
            sx=q.width()/270; sy=q.height()/368.5
            h4[[0,2]]=(h4[[0,2]]*sx-c.left())*(w-1)/c.width()
            h4[[1,3,4,5]]=(h4[[1,3,4,5]]*sy-c.top())*(h-1)/c.height()
            return h4
        mix=np.full((h,w),t,np.float32)
        for feature,va,vb in (
            ('mouth',(116,88,154,85,82,113) if fade_shot else _DOCK_MOUTH,(77.4,62.5,94.,62.1,61.8,63.0)),
            ('eye',(141,69,157,68,62,74) if fade_shot else _DOCK_EYE,(94.5,46.8,114.1,46.8,38.1,53.2)),
        ):
            aa=aperture(va,last,last_crop);bb=aperture(vb,still,still_crop);dd=aa+(bb-aa)*t
            rel=(xx-dd[0])/(dd[2]-dd[0]); cl=np.clip(rel,0.,1.)
            arc=np.maximum(0.,np.sin(np.pi*cl))**.62
            def bounds(k):
                line=k[1]+cl*(k[3]-k[1]);m=(k[1]+k[3])*.5
                return line+(k[4]-m)*arc,line+(k[5]-m)*arc
            hi,lo=bounds(dd);v=np.clip((yy-hi)/np.maximum(.9,lo-hi),0.,1.)
            outside=np.maximum(np.maximum(-rel,rel-1)*(dd[2]-dd[0]),np.maximum(hi-yy,yy-lo))
            weight=np.clip(1.-outside/5.5,0.,1.);weight=weight*weight*(3.-2.*weight)
            for mp,ep in ((ma,aa),(mb,bb)):
                top,bottom=bounds(ep)
                uy=top+v*np.maximum(.6,bottom-top)+np.minimum(yy-hi,0.)+np.maximum(yy-lo,0.)
                ux=ep[0]+rel*(ep[2]-ep[0]); nu=np.dstack([ux,uy])
                mp[:]=mp+(nu-mp)*weight[:,:,None]
            # Prefer a single clean donor at any point: the mouth closes with
            # f170's teeth; 0005's iris texture opens early from the genuine lid.
            if fade_shot and feature=='mouth':
                # Stop donating the open mouth earlier in this more skewed pose.
                u=np.clip((t-.24)/.48,0.,1.)
            else:
                u=np.clip((t-.64)/.30,0.,1.) if feature=='mouth' else np.clip(t/.32,0.,1.)
            blend=u*u*(3.-2.*u)
            mix+=weight*(blend-mix)
            if fade_shot and feature=='mouth':
                # As the smile closes, let the matched cheek replace inverse
                # warped open-mouth texels below the single lip boundary.
                surround=np.maximum(np.maximum(-rel,rel-1)*(dd[2]-dd[0]),
                                    np.maximum(hi-yy,yy-lo))
                cheek=np.clip(1.-surround/24.,0.,1.)
                # Constrain dark teeth/mouth texels to the shrinking
                # aperture. Once outside, replace them with the matched
                # cheek sooner than the interior's natural lip closure.
                below=np.clip((yy-lo+1.)/3.,0.,1.)
                x_weight=np.clip(1.-np.maximum(-rel,rel-1)*(dd[2]-dd[0])/7.,0.,1.)
                y_weight=np.clip(1.-np.maximum(0.,yy-lo-5.)/18.,0.,1.)
                advance=np.clip((t-.13)/.26,0.,1.)
                floor=x_weight*y_weight*below*advance*advance*(3.-2.*advance)
                # Keep both donor textures below the lip anchored below their
                # actual apertures; a folded lower triangle may otherwise
                # sample the same dark inner-mouth texture twice.
                for mp,endpoint in ((ma,aa),(mb,bb)):
                    _,edge=bounds(endpoint)
                    cheek_y=edge+1.5+np.maximum(0.,yy-lo)
                    mp[:,:,1]+=floor*np.maximum(0.,cheek_y-mp[:,:,1])
                mix=np.maximum(mix,floor)
                mix+=cheek*blend*(1.-mix)
        # The palms change orientation as they meet. Keep the photographed
        # fingers intact rather than superimposing all their shadows for 140ms.
        hand_ids=[23,39]
        for hp in hand_ids:
            cx,cy=dst[hp]; rx,ry=w*.16,h*.073
            zone=np.clip((1.4-np.sqrt(((xx-cx)/rx)**2+((yy-cy)/ry)**2))/.4,0.,1.)
            u=np.clip((t-.30-.21*np.clip((xx-cx+rx)/(2*rx),0,1))/.24,0,1)
            mix+=zone*(u*u*(3-2*u)-mix)
        alpha=np.clip(.5+((1-t)*warp(sa,ma)+t*warp(sb,mb))/1.45,0.,1.)
        oa,ob=warp(a,ma),warp(b,mb)
        tex=np.rint(oa*(1-mix[:,:,None])+ob*mix[:,:,None]).clip(0,255).astype(np.uint8)
        rgba=np.dstack([tex,np.rint(255*alpha).astype(np.uint8)])
        result.append(QImage(rgba.data,w,h,rgba.strides[0],QImage.Format.Format_RGBA8888).copy())
    return result


def _subject(image):
    """Estimate a subject only against a known transparent or near-white backdrop."""
    thumb = image.scaled(QSize(120, 140), Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.FastTransformation)
    thumb = thumb.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = thumb.width(), thumb.height()
    raw = thumb.constBits().asstring(thumb.sizeInBytes())
    stride = thumb.bytesPerLine()
    def rgba(x, y):
        j = y * stride + x * 4
        return raw[j], raw[j + 1], raw[j + 2], raw[j + 3]
    # Do not crop a photograph, a colored scene, or uncertain framing.
    corners = [rgba(x, y) for x in (0, w - 1) for y in (0, h - 1)]
    alpha = all(a < 16 for _, _, _, a in corners)
    neutral = all(a >= 245 and min(r, g, b) >= 232 and max(r, g, b)-min(r, g, b) < 15
                  for r, g, b, a in corners)
    full = QRectF(image.rect())
    if not (alpha or neutral):
        return full
    left, top, right, bottom = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = rgba(x, y)
            visible = a > 20 if alpha else a > 20 and (min(r, g, b) < 225 or max(r, g, b)-min(r, g, b) > 22)
            if visible:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < left or bottom < top:
        return full
    sx, sy = image.width()/w, image.height()/h
    return QRectF(left*sx, top*sy, (right+1-left)*sx, (bottom+1-top)*sy)


def _framing(images):
    # One stable crop across the complete sequence, including the final dock frame.
    # Only empty pixels of clean private media are trimmed; never remove attribution.
    full = QRectF(images[0].rect())
    body = _subject(images[0])
    for image in images[1:]:
        body = body.united(_subject(image))
    pad = max(2., max(body.width(), body.height()) * .018)
    frame = full.intersected(body.adjusted(-pad, -pad, pad, pad))
    return body, frame


def contain(bounds, size):
    if bounds.isEmpty() or size.isEmpty():
        return QRectF()
    k = min(bounds.width() / size.width(), bounds.height() / size.height())
    w, h = size.width() * k, size.height() * k
    return QRectF(bounds.center().x() - w / 2, bounds.center().y() - h / 2, w, h)


def paint_frame(painter, image, bounds, eyelid=0., *, crop=None, eye_reference=None):
    if image.isNull() or bounds.isEmpty():
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    crop = QRectF(image.rect()) if crop is None else crop
    painter.translate(bounds.topLeft())
    painter.scale(bounds.width()/crop.width(), bounds.height()/crop.height())
    painter.translate(-crop.left(), -crop.top())
    painter.setClipRect(crop, Qt.ClipOperation.IntersectClip)
    painter.drawImage(QPointF(0,0), image)
    if eyelid:
        rx, ry, rw, rh = eye_reference or (0, 0, 1320, 1864)
        painter.scale(image.width()/rw, image.height()/rh)
        painter.translate(-rx, -ry)
        # Coordinates were measured on the full, unflipped 0005 portrait, not its thumbnail.
        near = QPainterPath(); near.moveTo(462,234)
        near.cubicTo(463,182,539,163,561,210)
        near.cubicTo(584,272,488,304,463,252); near.closeSubpath()
        far = QPainterPath(); far.moveTo(396,209)
        far.cubicTo(378,217,369,235,372,259)
        far.quadTo(373,273,380,282); far.quadTo(393,240,396,209)
        for mask, lighter, darker in ((near,"#f0d35a","#e0ac56"),(far,"#baa358","#d7a65b")):
            painter.save(); painter.setClipPath(mask, Qt.ClipOperation.IntersectClip)
            r = mask.boundingRect()
            y = r.top() + (r.height()+6)*eyelid
            shape = QPainterPath(); shape.moveTo(r.topLeft()); shape.lineTo(r.topRight())
            shape.lineTo(r.right(),y-3); shape.quadTo(r.center().x(),y+4,r.left(),y); shape.closeSubpath()
            grad = QLinearGradient(r.topLeft(),r.bottomRight())
            grad.setColorAt(0,QColor(lighter)); grad.setColorAt(1,QColor(darker))
            painter.fillPath(shape,grad)
            rim = min(y - 2, r.top() + r.height()*.82)
            line = QPainterPath(); line.moveTo(r.left(),rim)
            line.quadTo(r.center().x(),rim+4,r.right(),rim-2)
            painter.setPen(QPen(QColor(109,81,44,round(175*eyelid)),2.7)); painter.drawPath(line)
            painter.restore()
    painter.restore()


class DockPortrait(QWidget):
    def __init__(self, parent, image, crop):
        super().__init__(parent)
        self.image, self.crop = image, crop
        self.setObjectName("splashDockArt"); self.setAccessibleName("大笑的奶蛙")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("QWidget#splashDockArt {background:transparent;border:0;}")
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        paint_frame(p, self.image, contain(QRectF(self.rect()), self.crop.size()), crop=self.crop)
        p.end()


class StartSplash(QWidget):
    """Parent to the main window. dock_target is a reserved, non-interactive home slot."""
    def __init__(self, host, *, on_home, on_docked=None, reduced_motion=False,
                 asset_dir, dock_target, sound_factory=None):
        super().__init__(host)
        self.host, self.target = host, dock_target
        self.on_home, self.on_docked = on_home, on_docked
        self.reduced, self.assets = reduced_motion, Path(asset_dir)
        self._factory, self._effect = sound_factory, None
        self._prepared_effect = None
        self._audio_consumed = False
        self.audio_status = "opt-in-pending" if sound_factory is not None else "disabled"
        self.native_start_ms = None
        self._native_wait_since_ms = None
        self._native_requested = False
        self._fade_framing=0.
        self.phase, self._released = "idle", False
        self.lid = self.travel = self.dock_progress = 0.
        self._dock_frames = []
        self.dock = None
        self._captured = None
        self._watching = False
        self.setObjectName("startupPaper")
        self.setStyleSheet("QWidget#startupPaper {background:transparent;border:0;}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.start_button = QPushButton("Start",self)
        self.start_button.setAutoDefault(False)
        self.start_button.setAccessibleName("Start，开始写作")
        self.start_button.setAccessibleDescription("Enter 或空格开始，Esc 跳过开屏")
        self.start_button.clicked.connect(self._laugh)
        self.welcome_title = QLabel(WELCOME_ZH, self)
        self.welcome_subtitle = QLabel(WELCOME_EN, self)
        self.welcome_subtitle.setWordWrap(True)
        for label in (self.welcome_title, self.welcome_subtitle):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setAccessibleName(label.text())
        self.setAccessibleName("写作批改欢迎页")
        self.setAccessibleDescription("回车或空格开始，Esc 跳过")
        # Two real text labels, one timeline. The button and its focus remain live.
        self._copy_effects = []
        for label in (self.welcome_title, self.welcome_subtitle):
            fx = QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(fx)
            self._copy_effects.append(fx)
        self.copy_opacity = 1. if self.reduced else 0.
        self._set_copy_opacity(self.copy_opacity)
        self.copy_fade = self._anim(COPY_FADE_MS, self._set_copy_opacity,
                                    lambda: self._set_copy_opacity(1.))
        self.reveal_progress = 0.
        self._reveal_lid = 0.
        self._still_full = False
        self.full_reveal_ms = None
        self.blink_wait = self._timer(self._blink_now)
        self.blink = self._anim(168, self._move_lid, self._plan_blink)
        self.clock = QElapsedTimer()
        self.pulse = QTimer(self)
        self.pulse.setInterval(12)
        self.pulse.setTimerType(Qt.TimerType.PreciseTimer)
        self.pulse.timeout.connect(self._advance)
        self.bridge_progress = 0.
        self.frame_index = 0
        self._route = None
        self._retarget = False
        self.hide()

    def _timer(self, callback):
        timer = QTimer(self); timer.setSingleShot(True); timer.timeout.connect(callback)
        return timer

    def _anim(self, ms, update, finish):
        anim = QVariantAnimation(self); anim.setStartValue(0.); anim.setEndValue(1.)
        anim.setDuration(ms); anim.valueChanged.connect(update); anim.finished.connect(finish)
        return anim

    def _set_copy_opacity(self, value):
        self.copy_opacity = float(value)
        for effect in self._copy_effects:
            effect.setOpacity(self.copy_opacity)

    def start(self):
        if self.phase != "idle":
            return
        self.phase = "wait"
        scene = read_scene(self.assets)
        if scene is None:
            if self._factory is not None:self._audio_note("visual-media-missing-or-rejected")
            self._settle()
            return
        self.side, self.eye_reference, self.clip = scene
        self.side_body, self.side_crop = _framing([self.side])
        self.side = _paperless_portrait(self.side)
        # The calibrated f119 bridge is identical to the accepted inward shot.
        # Use its exact reference framing to avoid perturbing the face/hand map.
        reference=self.clip.frames[:30] if self.clip.profile in HD_NATIVE_PROFILES else self.clip.frames
        self.laugh_body, self.laugh_crop = _framing(reference)
        self._fade_crop=QRectF(self.laugh_crop)
        if self.clip.profile==HD_FADE_PROFILE and not self.reduced:
            # Keep the first shot framing unchanged; then gradually make room
            # for the extended original hand motion, at the same aspect ratio.
            _,full=_framing(self.clip.frames)
            union=self.laugh_crop.united(full)
            ratio=self.laugh_crop.width()/self.laugh_crop.height()
            width=max(union.width(),union.height()*ratio)
            self._fade_crop=QRectF(0,0,width,width/ratio)
            self._fade_crop.moveCenter(union.center())
        del reference
        self.laugh_face=LAUGH_FACE
        if self.clip.profile in (HD_PROFILE,*HD_NATIVE_PROFILES):
            for i,frame in enumerate(self.clip.frames):
                self.clip.frames[i]=_clean_hd_backdrop(frame)
            first=self.clip.frames[0];c=self.laugh_crop
            self.laugh_face=((c.x()+165/400*c.width())/first.width(),
                             (c.y()+30/480*c.height())/first.height(),
                             (75/400*c.width())/first.width())
        self.dock_source="side-eye-0005" if self.clip.dock_still is not None else "native-last"
        self.smile=(_clean_hd_backdrop(self.side) if self.clip.dock_still is not None
                    else self.clip.frames[self.clip.dock])
        self.dock_crop=QRectF(self.laugh_crop)
        if self.clip.dock_still is not None:
            # The original portrait is a different optical canvas than the movie.
            # Match the flight aspect with transparent space, NEVER by stretching.
            _,padded=_framing([self.smile]);ratio=self.laugh_crop.width()/self.laugh_crop.height()
            width=max(padded.width(),padded.height()*ratio)
            self.dock_crop=QRectF(0,0,width,width/ratio);self.dock_crop.moveCenter(padded.center())
        if self.clip.dock_still is not None and not self.reduced:
            self._dock_frames=_dock_inbetweens(self.clip.frames[self.clip.dock],self._fade_crop,
                                                self.smile,self.dock_crop,
                                                fade_shot=self.clip.profile==HD_FADE_PROFILE)
        self.clip.dock_still=None  # one local static image is sufficient
        if self._factory is not None and self.reduced: self._audio_note("reduced-motion")
        elif self._factory is not None and self.clip.profile not in HD_NATIVE_PROFILES: self._audio_note("not-matching-native-shot")
        self._bridge_images = []
        self._bridge_side,self._bridge_floor,self._floor_y=self.side,None,0
        if self.clip.anticipation and not self.reduced:
            self.clip.anticipation=tuple(_clean_hd_backdrop(im) for im in self.clip.anticipation)
        elif not self.reduced:
            self._bridge_side,self._bridge_floor,self._floor_y=_bridge_paper_layers(self.side,self.side_crop)
            # Match a real eyelid close to the original laughing GIF's closed eyes.
            closed = QImage(self.side.size(), QImage.Format.Format_RGBA8888)
            closed.fill(Qt.GlobalColor.transparent)
            pen = QPainter(closed)
            paint_frame(pen, self.side, QRectF(closed.rect()), 1., eye_reference=self.eye_reference)
            pen.end()
            self._bridge_images = _morph_frames(closed, self.side_crop,
                         self.clip.frames[self.clip.index_at(0)],self.laugh_crop,
                         profile=HD_PROFILE if self.clip.profile in HD_NATIVE_PROFILES else self.clip.profile)
        self.dock = DockPortrait(self.target, self.smile, self.dock_crop)
        self.target.installEventFilter(self)
        self.host.installEventFilter(self)
        self.setGeometry(self.host.rect())
        # The opening is an intentional white page, even above a dark home.
        # Dark application chrome is not flashed/changed; it fades in on the flight.
        self.paper = QColor("#ffffff")
        title_stack=ui_font_stack("'Microsoft YaHei UI','Microsoft YaHei'")
        english_stack=ui_font_stack("'Segoe UI'")
        headline_weight="700" if QApplication.instance().property("cetPrivateUiFont") else "600"
        self.welcome_title.setStyleSheet(
            "QLabel {background:transparent;color:#252820;border:0;"
            "font-family:"+title_stack+";font-size:31px;font-weight:"+headline_weight+";}")
        self.welcome_subtitle.setStyleSheet(
            "QLabel {background:transparent;color:#51554f;border:0;"
            "font-family:"+english_stack+";font-size:15px;font-weight:400;}")
        self.start_button.setStyleSheet(
            "QPushButton {background:#38482c;color:white;border:2px solid transparent;"
            "border-radius:7px;font-family:"+english_stack+";font-weight:"+headline_weight+
            ";font-size:16px;text-decoration:none;}"
            "QPushButton:hover {background:#2b3822;}"
            "QPushButton:focus {border-color:#829b67;}")
        self.start_button.setToolTip("Enter 或空格开始；Esc 跳过")
        self.welcome_title.ensurePolished()
        title_font = self.welcome_title.font()
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, TITLE_TRACKING_PX)
        self.welcome_title.setFont(title_font)
        self._layout()
        QApplication.instance().installEventFilter(self); self._watching = True
        self.show(); self.raise_()
        self.start_button.setFocus(Qt.FocusReason.OtherFocusReason)
        if not self.reduced:
            self.copy_fade.start()
        self._plan_blink()

    def _bounds(self, *, waiting=None):
        pad = min(12., max(4., self.height() * .013))
        return QRectF(pad, pad, max(1.,self.width()-2*pad), max(1.,self.height()-2*pad))

    def _eye_crop(self):
        # Same source-space registration used by the blink, including image variants.
        rx,ry,rw,rh=self.eye_reference
        ex,ey,ew,eh=EYE_WINDOW
        sx,sy=self.side.width()/rw,self.side.height()/rh
        return QRectF((ex-rx)*sx,(ey-ry)*sy,ew*sx,eh*sy).intersected(QRectF(self.side.rect()))

    def _eye_window(self):
        w,h=max(1,self.width()),max(1,self.height())
        # A close crop is the poster; it does not sit inside a decorative card.
        sw,sh=EYE_WINDOW[2:]
        # Keep the former vertical eye magnification on desktops; small windows
        # pull back optically rather than cutting either contour or stretching it.
        scale=min(max(136.,min(530.,w*.485,h*.94))/300.,max(1.,w-32.)/sw)
        width,height=sw*scale,sh*scale
        # Keep the whole eye / headline / English / Start stack centered as a unit.
        goods=self._copy_sizes()
        total=height+sum(goods)
        y=max(3.,(h-total)/2.)
        return QRectF((w-width)/2.,y,width,height)

    def _copy_sizes(self):
        h=self.height()
        compact=h<450 or self.width()<470
        # Gaps and line heights, in the same order as the three real controls.
        return (12 if compact else 24, 40 if compact else 47, 1 if compact else 3,
                38 if self.width()<370 else 23, 10 if compact else 23, 33 if compact else 40)

    def _layout(self):
        if not hasattr(self,"welcome_subtitle"):
            return
        r=self._eye_window()
        gap,title,gap2,sub,gap3,bh=self._copy_sizes()
        w=self.width()
        y=round(r.bottom()+gap)
        self.welcome_title.setGeometry(5,y,max(1,w-10),title)
        y+=title+gap2
        self.welcome_subtitle.setGeometry(8,y,max(1,w-16),sub)
        y+=sub+gap3
        bw=max(48,min(116,w-24))
        self.start_button.setGeometry((w-bw)//2,y,bw,bh)

    def _reveal_u(self):
        if self.phase=="wait":
            return 0.
        if self.phase!="reveal":
            return 1.
        return self._ease(self.reveal_progress)

    def reveal_aperture(self):
        # Local logical pixels only. Resizing never touches OS fullscreen/window state.
        start=self._eye_window(); end=QRectF(self.rect()); t=self._reveal_u()
        return QRectF(*(a+(b-a)*t for a,b in zip(start.getRect(),end.getRect())))

    def camera_image_rect(self):
        # One isotropic optical zoom. Clip and subject use the same eased clock.
        # Geometric rather than linear interpolation of scale avoids a tiny
        # face suspended for most of the move, then a rush of body at the end.
        window=self._eye_window(); eyes=self._eye_crop(); t=self._reveal_u()
        full=contain(self._bounds(),self.side_crop.size())
        if t>=1. or eyes.isEmpty():
            return full
        src=self.side_crop; at=eyes.center()
        z0=window.width()/eyes.width(); z1=full.width()/src.width()
        zoom=z0*(z1/z0)**t
        p0=window.center()
        p1=QPointF(full.x()+(at.x()-src.x())*z1,full.y()+(at.y()-src.y())*z1)
        point=p0+(p1-p0)*t
        return QRectF(point.x()-(at.x()-src.x())*zoom,point.y()-(at.y()-src.y())*zoom,
                      src.width()*zoom,src.height()*zoom)

    def reveal_source(self):
        # Actual visible source pixels, not an intended zoom percentage.
        camera=self.camera_image_rect();clipped=self.reveal_aperture().intersected(camera)
        if clipped.isEmpty() or camera.isEmpty():
            return QRectF()
        k=self.side_crop.width()/camera.width()
        return QRectF(self.side_crop.x()+(clipped.x()-camera.x())*k,
                      self.side_crop.y()+(clipped.y()-camera.y())*k,
                      clipped.width()*k,clipped.height()*k).intersected(self.side_crop)

    def _paint_camera(self, painter):
        painter.save()
        painter.setClipRect(self.reveal_aperture(),Qt.ClipOperation.IntersectClip)
        lid=self.lid if self.phase=="wait" else (
            self._reveal_lid*(1.-self._ease(min(1.,self.reveal_progress*REVEAL_MS/100.))))
        paint_frame(painter,self.side,self.camera_image_rect(),lid,
                    crop=self.side_crop,eye_reference=self.eye_reference)
        painter.restore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "welcome_subtitle"):
            self._layout()
        if self.phase == "slide":
            self._retarget = True

    def _plan_blink(self):
        self.lid = 0.
        if self.phase == "wait" and not self.reduced:
            self.blink_wait.start(randint(4300,7400))
        self.update()

    def _blink_now(self):
        if self.phase == "wait" and not self.reduced:
            self.blink.start()

    def _move_lid(self, t):
        if self.phase == "wait":
            self.lid = max(0.,min(1.,t/.42,(1.-t)/.5)); self.update()

    def _laugh(self):
        if self.phase != "wait":
            return
        self.copy_fade.stop()
        self.phase = "laugh" if self.reduced else "reveal"
        self.blink_wait.stop(); self.blink.stop()
        self._reveal_lid=self.lid
        self._start_lid=0.
        self.lid=self.travel=0.
        self.reveal_progress=1. if self.reduced else 0.
        self.bridge_progress=1. if self.reduced else 0.
        self.frame_index=self.clip.dock if self.reduced else self.clip.index_at(0)
        self._still_full=self.reduced
        self.start_button.hide();self.welcome_title.hide();self.welcome_subtitle.hide()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.clock.start();self.repaint()
        if self.clip.profile==HD_FADE_PROFILE and not self.reduced:
            # Explicit Start can pre-open a prepared PCM stream, but it must
            # submit no samples until the complete native frame is painted.
            self._prepare_sound()
            if self.phase in ("docked","closed"):
                return
        if self.reduced:
            # Full portrait explicitly drawn once; no moving aperture or pan.
            self.full_reveal_ms=0
        self.pulse.start()

    def _prepare_sound(self):
        prepare=getattr(self._factory,"prepare",None)
        if not callable(prepare):
            if self._factory is not None:
                self._audio_consumed=True
                self._audio_note("pcm-worker-unavailable")
            return
        try:
            pending=prepare()
            if self.phase not in ("reveal","laugh"):
                pending.stop()
                return
            self._prepared_effect=pending
            self._audio_note("pcm-preparation-queued")
        except Exception as error:
            self._audio_consumed=True
            reason=getattr(error,"reason",None)
            self._audio_note(reason if reason in {"audio-driver-quarantined","audio-worker-busy",
                             "audio-worker-unavailable","pcm-media-rejected"} else "pcm-prepare-failed")

    def _audio_note(self, reason):
        self.audio_status=reason
        if self._factory is not None:
            _AUDIO_LOG.info("startup-audio status=%s",reason)

    def _audio_active(self):
        return (self.phase=="laugh" and self.clip.profile in HD_NATIVE_PROFILES and not self.reduced
                and not self._still_full and self.isVisible()
                and not self.host.isMinimized() and self.native_start_ms is not None)

    def _native_paint_wait_expired(self, now):
        return (self._native_wait_since_ms is not None and
                now-self._native_wait_since_ms>=NATIVE_PAINT_GRACE_MS)

    def _after_native_frame_painted(self):
        if (self.clip.profile not in HD_NATIVE_PROFILES or self.reduced or not self._native_requested or
                self.frame_index!=0 or self.phase!="laugh" or not self.isVisible() or self.host.isMinimized()):
            return
        if self.native_start_ms is None:
            now=self.clock.elapsed()
            if self._native_paint_wait_expired(now):
                return
            self.native_start_ms=now
        if self._factory is None or self._audio_consumed or not self._audio_active():
            return
        self._audio_consumed=True  # reserve before IO / possible reentry
        try:
            effect=self._prepared_effect
            self._prepared_effect=None
            if effect is None:
                if self.clip.profile==HD_FADE_PROFILE:
                    self._audio_note("pcm-worker-unavailable")
                    return
                try:
                    path=_long_asset(self.assets,LONG_WAV)
                except (ValueError,OSError):
                    self._audio_note("media-missing-or-rejected")
                    return
                effect=self._factory(path)
            self._effect=effect
            if not self._audio_active():
                self._stop_effect();self._audio_note("cancelled-before-play")
            elif self.clock.elapsed()-self.native_start_ms>AUDIO_START_GRACE_MS:
                self._stop_effect();self._audio_note("audio-ready-too-late")
            else:
                result=effect.play()
                if self._audio_active() and self._effect is effect:
                    self._audio_note("pcm-submit-queued" if result=="pcm-submit-queued" else "play-request-accepted")
        except Exception as exc:
            self._stop_effect()
            # Known adapter failures may report named reasons; never print paths or credentials.
            code=getattr(exc,"reason",None)
            self._audio_note(code if code in {"media-missing-or-rejected","backend-unavailable",
                             "backend-declined","pcm-not-ready-at-first-frame","pcm-generation-cancelled",
                             "pcm-already-queued"} else "play-request-failed")

    def _stop_effect(self):
        old,self._effect=self._effect,None
        pending,self._prepared_effect=self._prepared_effect,None
        for device in (old,pending):
            if device is not None:
                try:
                    device.stop()
                except Exception:
                    pass

    def _home(self):
        if not self._released:
            self._released = True
            self.on_home()

    def _advance(self):
        if self.phase not in ("reveal", "laugh", "slide"):
            return
        elapsed=self.clock.elapsed()
        reveal=0 if self.reduced else REVEAL_MS
        if self.phase=="reveal":
            self.reveal_progress=min(1.,elapsed/REVEAL_MS)
            if elapsed<reveal:
                self.update()
                return
            # Include the complete head-to-feet pose even if the last timer sample
            # fell 15ms early. Do not wait for a paint callback or add a hold.
            self.repaint()
            self.full_reveal_ms=elapsed
            self.phase="laugh"
        elif self._still_full:
            self._still_full=False
        elapsed-=reveal
        bridge = 0 if self.reduced else NATIVE_PREROLL_MS if self.clip.anticipation else BRIDGE_MS
        if elapsed < bridge:
            self.bridge_progress = elapsed / bridge
            self.update()
            return
        self.bridge_progress = 1.
        laugh_elapsed = elapsed - bridge
        if self.clip.profile in HD_NATIVE_PROFILES and not self.reduced:
            if self.native_start_ms is None:
                self.frame_index=0
                # On a late event-loop tick, still paint f119 before advancing the shot.
                # Hidden/minimized widgets must not stall navigation or start audio on restore.
                if not self.isVisible() or self.host.isMinimized():
                    self.native_start_ms=self.clock.elapsed()
                    self._audio_consumed=True
                    if self._factory is not None:self._audio_note("not-visible")
                else:
                    if self._native_wait_since_ms is None:
                        self._native_wait_since_ms=self.clock.elapsed()
                    if not self._native_paint_wait_expired(self.clock.elapsed()):
                        self.repaint()
                    if self.phase!="laugh":
                        return
                    if self.native_start_ms is None:
                        if not self._native_paint_wait_expired(self.clock.elapsed()):
                            return
                        # Persistent clipping cannot stall navigation or cause a
                        # late sound; continue the original visual schedule silently.
                        self.native_start_ms=self._native_wait_since_ms
                        self._audio_consumed=True
                        if self._factory is not None:self._audio_note("native-frame-incomplete")
            laugh_elapsed=self.clock.elapsed()-self.native_start_ms
        fade_shot=self.clip.profile==HD_FADE_PROFILE and not self.reduced
        if fade_shot:
            self._fade_framing=self._ease((laugh_elapsed-1200)/420)
        slide_at=(FADE_SLIDE_START_MS if fade_shot else
                  min(self.clip.duration_ms,1733) if self.reduced else self.clip.duration_ms)
        self.frame_index=self.clip.dock if self.reduced else self.clip.index_at(laugh_elapsed)
        if laugh_elapsed < slide_at:
            self.update()
            return
        if laugh_elapsed >= self.clip.duration_ms:
            self._stop_effect()
        if self.phase == "laugh":
            if self.reduced:
                self._settle()
                return
            self.phase = "slide"
            self._home()
            if self.phase != "slide":
                return
            self.raise_()
            self._route = (self._laugh_rect(),
                           self._destination(), 0.)
        if self._retarget:
            # A real host resize may move the slot. Rebase once from the current pose,
            # never let a changing layout independently tween the character.
            self._route = (self.scene_rect(), self._destination(), self.travel)
            self._retarget = False
        slide_elapsed = laugh_elapsed-slide_at
        # Let the native finish stay untouched until the approaching figure is
        # already small enough for the registered single-surface rest pose.
        settle_from=max(630,self.clip.duration_ms-slide_at) if fade_shot else DOCK_SETTLE_FROM
        self.dock_progress=self._ease((slide_elapsed-settle_from)/(DOCK_SETTLE_TO-settle_from))
        if slide_elapsed >= SLIDE_MS:
            self.travel = 1.
            self._settle()
        else:
            self.travel = self._ease(slide_elapsed / SLIDE_MS)
            self.update()

    @staticmethod
    def _ease(t):
        t = min(1., max(0., t))
        return t*t*(3.-2.*t)

    def _destination(self):
        point = self.mapFromGlobal(self.target.mapToGlobal(QPoint()))
        area = QRectF(QPointF(point), QRectF(self.target.rect()).size())
        return contain(area, self.laugh_crop.size())

    def scene_rect(self):
        if self.phase == "docked":
            return self._destination()
        if self.phase in ("wait","reveal"):
            return self.reveal_aperture()
        if self.phase == "laugh" and self.bridge_progress < 1:
            return self._bridge_box()
        start = self._laugh_rect()
        if self.phase != "slide":
            return start
        start, end, began = self._route or (start, self._destination(), 0.)
        local = min(1., max(0., (self.travel - began) / max(1.e-8, 1. - began)))
        return QRectF(*(a+(b-a)*local for a,b in zip(start.getRect(),end.getRect())))

    def _laugh_rect(self):
        # The GIF character leans left. Center the *face* horizontally on the waiting
        # face if there is spare room; the whole original laughing subject must fit.
        area = self._bounds(waiting=False)
        rect = contain(area, self.laugh_crop.size())
        side = contain(self._bounds(waiting=True), self.side_crop.size())
        x0 = side.x() + (SIDE_FACE[0]*self.side.width()-self.side_crop.x())*side.width()/self.side_crop.width()
        x1 = rect.x() + (self.laugh_face[0]*self.clip.frames[0].width()-self.laugh_crop.x())*rect.width()/self.laugh_crop.width()
        rect.translate(min(area.right()-rect.right(), max(area.left()-rect.left(), x0-x1)), 0)
        return rect

    def _match_progress(self):
        # First 30 ms close the measured original eyelids. Geometry is stable.
        return self._ease((self.bridge_progress-.16)/.84)

    def _bridge_sample(self):
        steps=30 if self.clip.anticipation else len(self._bridge_images)+1
        index=round(self._match_progress()*steps)
        if self.clip.anticipation and self.bridge_progress<1.:
            # Exactly six sequential pre-roll frames at source cadence.
            # Do not advance the native audio epoch by morph quantization.
            index=min(index,steps-1)
        return index,steps

    def _bridge_box(self):
        dst=self._laugh_rect()
        index,steps=self._bridge_sample()
        if self.clip.profile in HD_NATIVE_PROFILES and index==steps:
            # This sample is native #119, not another interpolated surface.
            # Use exactly the same crop, fit and pixel grid as the next paint.
            return dst
        src=contain(self._bounds(waiting=True), self.side_crop.size())
        t=self._match_progress()
        return QRectF(*(a+(b-a)*t for a,b in zip(src.getRect(),dst.getRect())))

    def bridge_landmark(self):
        # One eye landmark in the single morphed portrait (logical window pixels).
        def relative(face, image, crop):
            return ((face[0]*image.width()-crop.x())/crop.width(),
                    (face[1]*image.height()-crop.y())/crop.height(),
                    face[2]*image.width()/crop.width())
        a=relative(SIDE_FACE,self.side,self.side_crop)
        b=relative(self.laugh_face,self.clip.frames[0],self.laugh_crop)
        index,steps=self._bridge_sample()
        t=index/steps
        u,v,span=(x+(y-x)*t for x,y in zip(a,b))
        rect=self._bridge_box()
        return [rect.x()+u*rect.width(),rect.y()+v*rect.height(),span*rect.width()]

    def _paint_clip_frame(self, painter, rect, damage):
        frame=self.clip.frames[self.frame_index]
        crop=self.laugh_crop
        if self._fade_framing:
            f=self._fade_framing
            crop=QRectF(*(a+(b-a)*f for a,b in zip(crop.getRect(),self._fade_crop.getRect())))
        paint_frame(painter,frame,rect,crop=crop)
        if (self.native_start_ms is not None or self.phase!="laugh" or
                self.clip.profile not in HD_NATIVE_PROFILES or self.frame_index!=0 or
                self.reduced or frame.isNull() or rect.isEmpty()):
            return False
        # Paint-event/visible regions and the fitted destination all use widget
        # logical coordinates. Round the latter outward so fractional edges at
        # any device-pixel ratio are covered. Keep holes in the real clip region.
        goal=QRegion(rect.toAlignedRect())
        return goal.subtracted(damage.intersected(self.visibleRegion())).isEmpty()

    def paintEvent(self, event):
        if self.phase not in ("wait","reveal","laugh","slide") or not hasattr(self,"paper"):
            return
        p = QPainter(self)
        native_painted=False
        color = QColor(self.paper)
        if self.phase == "slide":
            color.setAlphaF(1.-self.travel)
        p.fillRect(self.rect(), color)
        if self.phase in ("wait","reveal") or self._still_full:
            self._paint_camera(p)
        elif self.phase == "laugh" and self.bridge_progress < 1.:
            index,steps=self._bridge_sample()
            r = self._bridge_box()
            # This is original background only, never a second character.
            if self._bridge_floor is not None and self.bridge_progress*BRIDGE_MS<68.:
                src=self.side_crop
                visible=src.intersected(QRectF(0,self._floor_y,self.side.width(),self._bridge_floor.height()))
                if not visible.isEmpty():
                    kx,ky=r.width()/src.width(),r.height()/src.height()
                    dst=QRectF(r.x()+(visible.x()-src.x())*kx,r.y()+(visible.y()-src.y())*ky,
                               visible.width()*kx,visible.height()*ky)
                    p.save();p.setOpacity(1.-self._ease(self.bridge_progress*BRIDGE_MS/68.))
                    p.drawImage(dst,self._bridge_floor,visible.translated(0,-self._floor_y));p.restore()
            if index>=steps:
                native_painted=self._paint_clip_frame(p,r,event.region())
            elif self.clip.anticipation:
                # Real closed-mouth poses; do not show synthetic teeth early.
                frame=min(len(self.clip.anticipation)-1,int(self.bridge_progress*NATIVE_PREROLL_MS*30/1000))
                bounds=contain(r,self.laugh_crop.size())
                paint_frame(p,self.clip.anticipation[frame],bounds,crop=self.laugh_crop)
            elif index<=0:
                lid = self._start_lid+(1.-self._start_lid)*self._ease(self.bridge_progress/.16)
                paint_frame(p,self._bridge_side,r,lid,crop=self.side_crop,eye_reference=self.eye_reference)
            else:
                paint_frame(p,self._bridge_images[index-1],r)
        else:
            # Face, hands and contour share a single fitted surface late in flight.
            # Esc / reduced motion / the final dock always use the native side-eye 0005 portrait.
            rect=self.scene_rect()
            interval=len(self._dock_frames)+1
            index=round(self.dock_progress*interval) if self.phase=="slide" else 0
            if self.reduced or self.phase=="slide" and index==interval:
                paint_frame(p,self.smile,rect,crop=self.dock_crop)
            elif self.phase=="slide" and self._dock_frames and index:
                paint_frame(p,self._dock_frames[index-1],rect)
            else:
                native_painted=self._paint_clip_frame(p,rect,event.region())
        if p.end() and native_painted and self.native_start_ms is None:
            # Start the shared shot clock after the actual native paint, even
            # when the terminal bridge sample occurs one refresh before 100%.
            self._native_requested=True
            self._after_native_frame_painted()

    def skip(self):
        if self.phase in ("wait","reveal","laugh","slide"):
            if self._factory is not None:
                self._audio_note("skipped-after-request" if self._effect is not None else "skipped")
            self._settle()

    def _halt(self):
        self.copy_fade.stop()
        self.blink_wait.stop()
        self.blink.stop()
        self.pulse.stop()
        self._stop_effect()

    def _remove_watch(self):
        if self._watching:
            QApplication.instance().removeEventFilter(self); self._watching=False

    def _settle(self):
        if self.phase in ("docked","closed"):
            return
        self.phase="docked"; self.dock_progress=1.; self._halt(); self._home()
        if self.phase=="closed": return
        if self.dock is not None:
            self.dock.setGeometry(self.target.rect()); self.dock.show()
        self.hide()
        if self._captured is None: self._remove_watch()
        if self.on_docked: self.on_docked()

    def shutdown(self):
        if self.phase=="closed": return
        if self._factory is not None and self.phase not in ("idle","docked"):
            self._audio_note("closed-after-request" if self._effect is not None else "closed")
        self.phase="closed"; self._halt(); self._remove_watch()
        if self.dock is not None:
            self.dock.hide(); self.target.removeEventFilter(self); self.host.removeEventFilter(self)
        self.hide()

    def eventFilter(self,obj,event):
        kind=event.type()
        if obj is self.target and kind in (QEvent.Type.Resize,QEvent.Type.Move) and self.dock is not None:
            self.dock.setGeometry(self.target.rect())
            if self.phase=="slide":self._retarget=True
        if obj is self.host:
            if kind==QEvent.Type.Close: self.shutdown()
            elif kind==QEvent.Type.Resize: self.setGeometry(self.host.rect())
        # During Qt object teardown, unrelated events can arrive after the host's
        # native window is gone. Never inspect a window for non-input events.
        if kind not in (QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress,QEvent.Type.KeyRelease,
                        QEvent.Type.WindowDeactivate):
            return False
        if not isinstance(obj,QWidget) or obj.window() is not self.host.window():
            return False
        if kind==QEvent.Type.WindowDeactivate:
            if self.phase=="docked":
                self._captured=None; self._remove_watch()
            return False
        key=event.key()
        if self.phase=="docked":
            if self._captured!=key: return False
            if kind==QEvent.Type.KeyRelease and not event.isAutoRepeat():
                self._captured=None; self._remove_watch()
            event.accept(); return True
        if self.phase not in ("wait","reveal","laugh","slide"): return False
        if key==Qt.Key.Key_F4 and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            return False
        event.accept()
        if kind==QEvent.Type.KeyRelease and not event.isAutoRepeat() and self._captured==key:
            self._captured=None
        elif kind==QEvent.Type.KeyPress and not event.isAutoRepeat():
            if key==Qt.Key.Key_Escape:
                self._captured=key; self.skip()
            elif key in START_KEYS and self.phase=="wait":
                self._captured=key; self._laugh()
        return True
