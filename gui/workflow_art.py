"""Small, optional workflow illustrations loaded only from private local files."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QEasingCurve, QIODevice, QRectF, QSize, Qt, QVariantAnimation
from PyQt6.QtGui import QBitmap, QImage, QImageReader, QPainter, QPainterPath, QPixmap, QRegion
from PyQt6.QtWidgets import QLabel


from gui.local_assets import configured_asset_dir


ROLE_ASSET_IDS = {
    "reviewing": "gh-nailong-memes-49feeda3e4a2",
    "upload_empty": "dot-naiwa-1118",
    "review_completed": "dot-naiwa-1005",
    "guide": "ghn-naiwa-wallpaper-6a040e71f9b2",
    "history_empty": "dot-naiwa-1165",
    "export_success": "dot-naiwa-1166",
}
REVIEW_FEEDBACK_MS = 240
_IMAGE_FORMATS = {b"png", b"jpeg", b"gif", b"webp"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024


def ui_meme_directory() -> Path:
    return configured_asset_dir("ui-meme-assets") or Path(__file__).resolve().parents[1] / "work" / "preview" / "ui-meme-assets"


def _subfile(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name or any(c in name for c in ":/\\"):
        raise ValueError("Expected a local image basename")
    path = directory / name
    if path.resolve().parent != directory.resolve() or not path.is_file():
        raise ValueError("Expected a local, private file")
    return path


def _read_bounded(path: Path, budget: int) -> bytes:
    with path.open("rb") as stream:
        result = stream.read(budget + 1)
    if not result or len(result) > budget:
        raise ValueError("Private workflow art exceeds its local size limit")
    return result


def _preview_pixmap(directory: Path, asset_id: str, view: QSize) -> QPixmap:
    """Read a verified still; videos, audio and external paths are never loaded."""
    try:
        manifest = _subfile(directory, "ui-meme-assets.json")
        spec = json.loads(_read_bounded(manifest, 65536).decode("utf-8-sig"))
        if spec["version"] != 1:
            return QPixmap()
        assets = spec["assets"]
        item = assets[asset_id]
        path = _subfile(directory, item["file"])
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            return QPixmap()
        body = _read_bounded(path, _MAX_IMAGE_BYTES)
        expected = item["sha256"]
        if not isinstance(expected, str) or sha256(body).hexdigest() != expected.casefold():
            return QPixmap()
        buffer = QBuffer()
        buffer.setData(QByteArray(body))
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            return QPixmap()
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        size = reader.size()
        if (bytes(reader.format()) not in _IMAGE_FORMATS or not size.isValid()
                or size.isEmpty() or size.width() * size.height() > 16_000_000):
            return QPixmap()
        target = (view - QSize(8, 8)) * 2
        size.scale(target, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
        image = reader.read()
        if image.isNull():
            return QPixmap()
    except (OSError, ValueError, KeyError, TypeError, RecursionError, RuntimeError):
        return QPixmap()

    # Leave source pixels untouched; display tight transparent art or calm framed stills.
    bounds = image.rect()
    if image.hasAlphaChannel():
        bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
        if bounds.isEmpty():
            return QPixmap()
    if bounds != image.rect():
        image = image.copy(bounds)
    image = image.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    if not image.hasAlphaChannel():
        image = _rounded_preview(image)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(2.0)
    return pixmap


def _rounded_preview(image: QImage) -> QImage:
    rounded = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    rounded.fill(Qt.GlobalColor.transparent)
    shape = QPainterPath()
    radius = min(16, min(image.width(), image.height()) / 4)
    shape.addRoundedRect(QRectF(image.rect()), radius, radius)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setClipPath(shape)
    painter.drawImage(0, 0, image)
    painter.end()
    return rounded


class WorkflowArt(QLabel):
    """A decorative slot that collapses when inactive or when private art is absent."""

    def __init__(self, role: str, width: int, height: int, parent=None, *, directory: Path | None = None):
        super().__init__(parent)
        self.role = role
        self.asset_id = ROLE_ASSET_IDS[role]
        self.directory = directory if directory is not None else ui_meme_directory()
        self._loaded = False
        self._angle = 0.0
        self._animation = None
        self.setObjectName(f"workflow-{role.replace('_', '-')}")
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    @property
    def active(self) -> bool:
        return not self.isHidden() and self._has_pixmap()

    def _has_pixmap(self) -> bool:
        pixmap = self.pixmap()
        return pixmap is not None and not pixmap.isNull()

    def set_active(self, active: bool) -> bool:
        if active and not self._loaded:
            self._loaded = True
            self.setPixmap(_preview_pixmap(self.directory, self.asset_id, self.size()))
        self.setVisible(active and self._has_pixmap())
        if self.isHidden():
            self.stop_feedback()
        return self.active

    def play_review_once(self, *, reduced: bool) -> bool:
        """A single nod of the static thumbs-up, never a GIF loop or a replay."""
        self.stop_feedback()
        if reduced or not self.active or not self.isVisible() or self.role != "review_completed":
            return False
        if self._animation is None:
            animation = QVariantAnimation(self)
            animation.setDuration(REVIEW_FEEDBACK_MS)
            animation.setLoopCount(1)
            animation.setStartValue(0.0)
            animation.setKeyValueAt(0.44, -5.0)
            animation.setEndValue(0.0)
            animation.setEasingCurve(QEasingCurve.Type.InOutSine)
            animation.valueChanged.connect(self._set_angle)
            self._animation = animation
        self._animation.start()
        return True

    def stop_feedback(self) -> None:
        if self._animation is not None:
            self._animation.stop()
        if self._angle:
            self._set_angle(0.0)

    def _set_angle(self, angle: float) -> None:
        self._angle = float(angle)
        self.update()

    def hideEvent(self, event):
        self.stop_feedback()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self._angle or not self._has_pixmap():
            super().paintEvent(event)
            return
        pixmap = self.pixmap()
        size = pixmap.deviceIndependentSize()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)
        dst = QRectF(-size.width() / 2, -size.height() / 2, size.width(), size.height())
        painter.drawPixmap(dst, pixmap, QRectF(pixmap.rect()))
        painter.end()
