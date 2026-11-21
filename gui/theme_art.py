"""Optional, user-local Nai family artwork. No bundled images or network access."""
from pathlib import Path
import os

from PyQt6.QtCore import QEasingCurve, QRect, QRectF, QSize, QStandardPaths, Qt, QVariantAnimation
from PyQt6.QtGui import QBitmap, QImage, QImageReader, QPainter, QPainterPath, QPixmap, QRegion
from PyQt6.QtWidgets import QLabel

from gui.local_assets import configured_asset_dir


ASSETS = {"naiwa": "奶蛙", "naidan": "奶蛋", "naigou": "奶狗"}


def companion_directory() -> Path:
    override = os.environ.get("CET_COMPANIONS_DIR")
    if override:
        return Path(override)
    configured = configured_asset_dir("companions")
    if configured is not None:
        return configured
    preview = Path(__file__).resolve().parents[1] / "work" / "preview" / "companions"
    if preview.is_dir():
        return preview
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    return Path(base) / "CETWritingStudio" / "companions"


class ThemeArt(QLabel):
    """Collapse when a user has not supplied their own licensed PNG."""

    def __init__(self, side: int, parent=None, *, directory: Path | None = None):
        super().__init__(parent)
        self.directory = directory if directory is not None else companion_directory()
        self.side = side
        self._tilt = 0.0
        self._animation = None
        self.role = None
        self.setFixedSize(side, side)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()

    def show_role(self, role: str | None) -> bool:
        self.stop_feedback()
        self.clear()
        self.setAccessibleName('')
        self.role = None
        self.hide()
        if role not in ASSETS:
            return False
        source = self.directory / f"{role}.png"
        if not source.is_file():
            return False
        reader = QImageReader(str(source), b"png")
        shape = reader.size()
        if not shape.isValid() or shape.width() * shape.height() > 16_000_000:
            return False
        shape.scale(QSize(self.side * 2, self.side * 2), Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(shape)
        image = reader.read()
        if image.isNull():
            return False
        # Trim transparent atlas margins in memory, keeping the original asset intact.
        if image.hasAlphaChannel():
            bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
            if not bounds.isEmpty():
                image = image.copy(bounds)
        image = image.scaled(self.side * 2, self.side * 2, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        # Non-transparent posters are small rounded stickers, not white square tiles.
        # Clip the in-memory view only; retain the source artwork as supplied.
        if role in ("naidan", "naigou"):
            rounded = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
            rounded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            shape = QPainterPath()
            radius = min(image.width(), image.height()) * .24
            shape.addRoundedRect(QRectF(image.rect()), radius, radius)
            painter.setClipPath(shape)
            painter.drawImage(0, 0, image)
            painter.end()
            image = rounded
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(2.0)
        self.setPixmap(pixmap)
        self.role = role
        self.setAccessibleName(ASSETS[role])
        self.show()
        return True
    def stop_feedback(self):
        if self._animation is not None:
            self._animation.stop()
        if self._tilt:
            self._set_tilt(0.0)

    def play_feedback(self, *, reduced: bool) -> bool:
        """One nod after a confirmed action. Merely showing a role is static."""
        self.stop_feedback()
        if reduced or self.isHidden() or self.role is None:
            return False
        if self._animation is None:
            self._animation = QVariantAnimation(self)
            self._animation.setDuration(320)
            self._animation.setStartValue(0.0)
            self._animation.setKeyValueAt(.36, -5.0)
            self._animation.setKeyValueAt(.72, 2.0)
            self._animation.setEndValue(0.0)
            self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._animation.valueChanged.connect(self._set_tilt)
        self._animation.start()
        return True

    def _set_tilt(self, angle):
        self._tilt = float(angle)
        self.update()

    def hideEvent(self, event):
        self.stop_feedback()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self._tilt or self.pixmap().isNull():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.width()/2, self.height()/2)
        painter.rotate(self._tilt)
        pix = self.pixmap()
        size = pix.deviceIndependentSize().toSize()
        dst = QRect(-size.width()//2, -size.height()//2, size.width(), size.height())
        painter.drawPixmap(dst, pix, pix.rect())
        painter.end()


def role_stamp(role: str, side: int) -> ThemeArt:
    art = ThemeArt(side)
    art.show_role(role)
    return art
