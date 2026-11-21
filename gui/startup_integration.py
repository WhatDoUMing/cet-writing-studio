"""Wire the optional startup scene to the existing CET main window."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QShortcut
from PyQt6.QtWidgets import (QAbstractButton,QAbstractItemView,QAbstractSlider,QAbstractSpinBox,
    QComboBox,QLabel,QLineEdit,QMainWindow,QPlainTextEdit,QScrollArea,QStackedWidget,QTextEdit,QWidget)

from gui.local_assets import configured_asset_dir
from gui.start_splash import STARTUP_REQUIRED_MEDIA, StartSplash


def local_startup_assets(project_root: Path) -> Path:
    """Resolve the private local art directory. Do not fetch assets here."""
    return configured_asset_dir("startup-assets") or project_root / "work" / "preview" / "startup-assets"


class StartupAttachment(QObject):
    """Own a click-through island, without reserving any part of the central layout."""

    def __init__(self, window: QMainWindow, asset_dir: Path, *, reduced_motion: bool, sound_factory=None):
        super().__init__(window)
        self.window = window
        self.content = window.centralWidget()
        self._content_enabled = self.content is not None and self.content.isEnabled()
        self._shortcuts = [(item, item.isEnabled()) for item in window.findChildren(QShortcut)]
        self._home_released = False
        self._closed = False
        self._art_available = True
        self._signals = []

        # A QStatusBar is a full-width layout participant. The portrait is not:
        # it lives in an ordinary transparent child at a free point of the viewport.
        self.dock_target=QWidget(window)
        self.dock_target.setObjectName("startupDockTarget")
        self.dock_target.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dock_target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.dock_target.setAutoFillBackground(False)
        self.dock_target.setStyleSheet("QWidget#startupDockTarget { background: transparent; border: 0; }")
        self._placement=QTimer(self);self._placement.setSingleShot(True)
        self._placement.timeout.connect(self._fit_dock)
        self._fit_dock()
        for scroll in window.findChildren(QScrollArea):
            for bar in (scroll.verticalScrollBar(),scroll.horizontalScrollBar()):
                bar.valueChanged.connect(self._queue_fit)
                self._signals.append(bar.valueChanged)
        for stack in window.findChildren(QStackedWidget):
            stack.currentChanged.connect(self._queue_fit)
            self._signals.append(stack.currentChanged)

        self.splash = StartSplash(
            window,
            on_home=self._release_home,
            reduced_motion=reduced_motion,
            asset_dir=asset_dir,
            dock_target=self.dock_target,
            sound_factory=sound_factory,
        )
        if self.content is not None:
            self.content.setEnabled(False)
        for shortcut, _enabled in self._shortcuts:
            shortcut.setEnabled(False)
        window.installEventFilter(self)
        self.splash.start()
        if self.splash.phase != "wait":
            # The assets exist but cannot be decoded: keep the original layout.
            self._art_available=False
            self._placement.stop()
            self._release_home()
            self.dock_target.hide()


    def _queue_fit(self,*unused):
        if self._closed or not self._art_available:return
        if not self._placement.isActive():self._placement.start(0)

    def _protected(self,zone):
        # Protect *actual* visible text and controls, not an entire stretching
        # QLabel row. Clip scrolled descendants to their viewport and page.
        root=self.content
        if not root:return []
        rects=[]
        live=(QAbstractButton,QLineEdit,QComboBox,QAbstractSpinBox,QAbstractItemView,
              QPlainTextEdit,QTextEdit,QAbstractSlider)
        for w in root.findChildren(QWidget):
            if not w.isVisibleTo(root) or not isinstance(w,live+(QLabel,)):continue
            r=w.contentsRect() if isinstance(w,QLabel) else w.rect()
            at=w.mapTo(self.window,r.topLeft())
            if not zone.intersects(QRect(at,r.size())):continue
            if isinstance(w,QLabel):
                if w.text():
                    flags=int(w.alignment())|(int(Qt.TextFlag.TextWordWrap) if w.wordWrap() else 0)
                    r=w.fontMetrics().boundingRect(r,flags,w.text()).intersected(r)
                elif w.pixmap().isNull() and not w.property("role") and not w.objectName():continue
            if r.isEmpty():continue
            r=QRect(w.mapTo(self.window,r.topLeft()),r.size())
            anc=w.parentWidget()
            while anc and anc is not self.window and not r.isEmpty():
                r=r.intersected(QRect(anc.mapTo(self.window,QPoint()),anc.size()))
                anc=anc.parentWidget()
            if not r.isEmpty(): rects.append(r.adjusted(-3,-3,3,3))
        return rects

    def _fit_dock(self):
        if self._closed or not self._art_available:return
        w,h=self.window.width(),self.window.height()
        if not self.content or w<120 or h<100:return
        full=QRect(self.content.mapTo(self.window,QPoint()),self.content.size())
        zone=full.adjusted(round(full.width()*.65),round(full.height()*.55),-8,-8)
        blocks=self._protected(zone)
        preference=max(93,min(151,round(h*.192)))
        best=None
        # Try the true corner first. If a field is there, use the empty part of
        # a neighboring row; never draw over a scrollbar, field, label or action.
        for scale in (1.,.86,.72,.60,.48,.38):
            sh=round(preference*scale);sw=max(24,round(sh*.60))
            xs={zone.right()-sw+1};ys={zone.bottom()-sh+1}
            for b in blocks:
                xs.update((b.left()-sw,b.right()+1))
                ys.update((b.top()-sh,b.bottom()+1))
            for x in xs:
                for y in ys:
                    target=QRect(x,y,sw,sh)
                    if not zone.contains(target) or any(target.intersects(b) for b in blocks):continue
                    distance=(zone.right()-target.right())+1.5*(zone.bottom()-target.bottom())
                    penalty=distance+(preference-sh)*2.2
                    if best is None or penalty<best[0]:best=(penalty,target)
        if best:
            self.dock_target.setGeometry(best[1])
            self.dock_target.show()
            self.dock_target.raise_()
            splash=getattr(self,"splash",None)
            if splash is not None and splash.isVisible():splash.raise_()
        else:
            # An entirely occupied editor takes priority; no art should mask it.
            self.dock_target.hide()

    def _release_home(self) -> None:
        if self._home_released:
            return
        self._home_released = True
        self._fit_dock()
        if self.content is not None:
            self.content.setEnabled(self._content_enabled)
        for shortcut, enabled in self._shortcuts:
            shortcut.setEnabled(enabled)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._placement.stop()
        for sig in self._signals:
            try:sig.disconnect(self._queue_fit)
            except (TypeError,RuntimeError):pass
        self._signals.clear()
        self.dock_target.hide()
        self.splash.shutdown()
        self._release_home()
        self.window.removeEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if self._closed:return False
        if watched is self.window:
            if event.type() == QEvent.Type.Close:
                self.shutdown()
            elif event.type() in (QEvent.Type.Resize,QEvent.Type.Show,QEvent.Type.LayoutRequest):
                self._queue_fit()
        return super().eventFilter(watched, event)


def attach_startup_splash(
    window: QMainWindow,
    *,
    asset_dir: Path,
    reduced_motion: bool = False,
    sound_factory=None,
) -> StartupAttachment | None:
    """Attach once per window. Default silent; no real player is registered."""
    previous = getattr(window, "_startup_attachment", None)
    if previous is not None:
        return previous
    assets = Path(asset_dir)
    if not all((assets / name).is_file() for name in STARTUP_REQUIRED_MEDIA):
        return None
    entry = StartupAttachment(
        window, assets, reduced_motion=reduced_motion, sound_factory=sound_factory,
    )
    window._startup_attachment = entry
    return entry
