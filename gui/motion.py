"""Apple-style motion tokens and helpers for the desktop UI.

Values come from the Animation skill set: ``agent.md`` §3 (shared hard rules)
and ``review-animations/STANDARDS.md`` (exact curves and duration budgets).

* UI entrances/exits use the strong ease-out ``cubic-bezier(0.23, 1, 0.32, 1)``
  and never ``ease-in``.
* Duration budgets: button press 100-160 ms, popovers 125-200 ms, dropdowns
  150-250 ms, modals 200-500 ms; UI motion stays under 300 ms.
* Exits run about 20 % faster than entrances.
* Only opacity and the position of *free-floating* layers are animated. Layout
  properties (margin/padding/width/height) are never animated.
* Reduced motion means fewer and gentler: keep short opacity cross-fades, drop
  positional motion.
* Peer navigation cross-fades only; the standards forbid sliding between peer
  tabs, and the sidebar entries are peers.

Two Qt limitations are worked around rather than hidden:

* QSS has no ``cubic-bezier``; :class:`QEasingCurve.OutQuint` is the closest
  standard curve to ``cubic-bezier(0.23, 1, 0.32, 1)`` (fast start, long
  settle). The spec values stay next to the mapping so the intent survives.
* QWidget has no ``transform``, so press feedback uses an opacity dip instead of
  ``scale(0.97)``, and page layers move with ``move()`` only because they are
  floating snapshots outside any layout.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QPushButton,
    QWidget,
)

EASE_OUT_SPEC = (0.23, 1.0, 0.32, 1.0)
EASE_IN_OUT_SPEC = (0.77, 0.0, 0.175, 1.0)
EASE_DRAWER_SPEC = (0.32, 0.72, 0.0, 1.0)

DURATION_PRESS = 120
DURATION_POPOVER = 150
DURATION_DROPDOWN = 180
DURATION_MODAL = 300
DURATION_PAGE_ENTER = 150
DURATION_PAGE_EXIT = 120
DURATION_REDUCED = 120

STAGGER_STEP = 50
MAX_STAGGERED_ITEMS = 5
MAX_PAGE_LAYERS = 2

_reduce_motion = False
_press_filter: "PressFeedbackFilter | None" = None
_shutting_down = False


def set_reduce_motion(enabled: bool) -> None:
    """Fewer and gentler motion (accessibility), not zero motion."""
    global _reduce_motion
    _reduce_motion = bool(enabled)


def is_reduce_motion() -> bool:
    return _reduce_motion


def ease_out() -> QEasingCurve:
    """Nearest Qt curve to the spec's ``--ease-out`` cubic-bezier."""
    return QEasingCurve(QEasingCurve.Type.OutQuint)


def ease_in_out() -> QEasingCurve:
    """Nearest Qt curve to the spec's ``--ease-in-out`` (screen movement)."""
    return QEasingCurve(QEasingCurve.Type.InOutQuint)


def stagger_delay(index: int) -> int:
    """Stagger inside the 30-80 ms band, capped so it never feels slow."""
    if index >= MAX_STAGGERED_ITEMS:
        return 0
    return index * STAGGER_STEP


def effective_duration(duration: int) -> int:
    """Reduced motion keeps the fade but makes it shorter."""
    if _reduce_motion:
        return min(duration, DURATION_REDUCED)
    return duration


def _animations(widget: QWidget) -> list:
    running = getattr(widget, "_dsh_animations", None)
    if running is None:
        running = []
        widget._dsh_animations = running
    return running


def _detach(animation: object) -> None:
    """Stop an animation and detach it from any target before it is dropped."""
    if hasattr(animation, "stop"):
        animation.stop()
    if isinstance(animation, QPropertyAnimation):
        animation.setTargetObject(None)


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        return effect
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    return effect


def cancel_motion(widget: QWidget) -> None:
    """Stop fades on a widget and restore its normal painting."""
    for animation in _animations(widget):
        _detach(animation)
    widget._dsh_animations = []
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        widget.setGraphicsEffect(None)


def has_active_motion(widget: QWidget) -> bool:
    """True while a fade or transition is still animating this widget."""
    for animation in getattr(widget, "_dsh_animations", None) or []:
        if animation.state() == QAbstractAnimation.State.Running:
            return True
    return False


def fade_in(
    widget: QWidget,
    *,
    duration: int = DURATION_POPOVER,
    delay: int = 0,
    on_finished: Callable[[], None] | None = None,
) -> None:
    """Fade a widget in from its *current* opacity (interruptible, opacity only)."""
    effect = widget.graphicsEffect()
    has_effect = isinstance(effect, QGraphicsOpacityEffect)
    # No effect yet means "this is an entrance": start from hidden. An existing
    # effect means we are interrupting a fade: start from the live value.
    start = effect.opacity() if has_effect else 0.0
    for animation in _animations(widget):
        _detach(animation)
    widget._dsh_animations = []

    if _shutting_down:
        if has_effect:
            widget.setGraphicsEffect(None)
        if on_finished is not None:
            on_finished()
        return

    duration = effective_duration(duration)
    if start >= 0.999 or duration <= 0:
        if has_effect:
            widget.setGraphicsEffect(None)
        if on_finished is not None:
            on_finished()
        return

    effect = _opacity_effect(widget)
    # Hide immediately so a delayed fade never flashes the final state first.
    effect.setOpacity(start)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setEasingCurve(ease_out())
    animation.finished.connect(
        lambda w=widget, extra=on_finished: _finish_fade(w, extra)
    )
    _animations(widget).append(animation)
    if delay > 0:
        QTimer.singleShot(delay, lambda w=widget, a=animation: _start_delayed(w, a))
    else:
        animation.start()


def _start_delayed(widget: QWidget, animation: QPropertyAnimation) -> None:
    """Start a delayed fade only if it is still the widget's current one."""
    if animation in _animations(widget):
        animation.start()


def _finish_fade(widget: QWidget, extra: Callable[[], None] | None) -> None:
    for animation in _animations(widget):
        _detach(animation)
    widget._dsh_animations = []
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        widget.setGraphicsEffect(None)
    if extra is not None:
        extra()


def fade_widgets(
    widgets: list[QWidget],
    *,
    duration: int = DURATION_POPOVER,
) -> None:
    """Fade widgets in reading order with a 50 ms stagger (decorative only)."""
    for index, widget in enumerate(widgets):
        fade_in(widget, duration=duration, delay=stagger_delay(index))


def theme_crossfade(widget: QWidget | None, *, duration: int = DURATION_MODAL) -> None:
    """Ease an abrupt light/dark switch instead of hard-cutting brightness."""
    if widget is None or _shutting_down:
        return
    for animation in _animations(widget):
        _detach(animation)
    widget._dsh_animations = []
    duration = effective_duration(duration)
    if duration <= 0:
        return
    effect = _opacity_effect(widget)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.55)
    animation.setEndValue(1.0)
    animation.setEasingCurve(ease_out())
    animation.finished.connect(lambda w=widget: _finish_fade(w, None))
    _animations(widget).append(animation)
    animation.start()


class _PageTransition(QObject):
    """Cross-fade between stack pages using floating snapshot layers.

    QStackedWidget shows one page at a time, so the outgoing page is rendered
    into a snapshot label that lives outside any layout and can therefore fade
    freely. Interrupted transitions keep their live layer and re-target it, so
    rapid navigation never hard-cuts the outgoing page.
    """

    def __init__(self, stack: QWidget) -> None:
        super().__init__(stack)
        self.stack = stack
        self.layers: list[tuple[QLabel, list]] = []

    def cancel(self) -> None:
        for label, animations in list(self.layers):
            for animation in animations:
                _detach(animation)
            label.hide()
            label.deleteLater()
        self.layers = []

    def _drop_layer(self, label: QLabel, animations: list) -> None:
        for animation in animations:
            _detach(animation)
        for index, (existing, _) in enumerate(self.layers):
            if existing is label:
                del self.layers[index]
                break
        label.hide()
        label.deleteLater()

    def _add_layer(self, pixmap) -> None:
        parent = self.stack.parentWidget()
        if parent is None:
            return
        while len(self.layers) >= MAX_PAGE_LAYERS:
            label, animations = self.layers[0]
            self._drop_layer(label, animations)

        label = QLabel(parent)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setPixmap(pixmap)
        label.setGeometry(self.stack.geometry())
        label.show()
        label.raise_()

        effect = QGraphicsOpacityEffect(label)
        effect.setOpacity(1.0)
        label.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity", label)
        animation.setDuration(effective_duration(DURATION_PAGE_EXIT))
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(ease_out())
        animations = [animation]
        animation.finished.connect(
            lambda lab=label, anims=animations: self._drop_layer(lab, anims)
        )
        self.layers.append((label, animations))
        animation.start()

    def run(self, new_index: int) -> None:
        stack = self.stack
        old_page = stack.currentWidget()
        new_page = stack.widget(new_index)
        if (
            _shutting_down
            or old_page is None
            or new_page is None
            or not stack.isVisible()
            or new_index == stack.currentIndex()
        ):
            if not _shutting_down and new_index != stack.currentIndex():
                stack.setCurrentIndex(new_index)
            return

        self._add_layer(old_page.grab())
        # Start the incoming fade before the switch so the page's own show-time
        # intro can detect a running transition and skip a duplicate reveal.
        fade_in(new_page, duration=DURATION_PAGE_ENTER)
        stack.setCurrentIndex(new_index)


def page_transition(stack: QWidget, new_index: int) -> None:
    """Cross-fade a QStackedWidget page change (no peer-tab sliding)."""
    transition = getattr(stack, "_dsh_transition", None)
    if transition is None:
        transition = _PageTransition(stack)
        stack._dsh_transition = transition
    transition.run(new_index)


class PressFeedbackFilter(QObject):
    """Dip a button's opacity while pressed, then settle back.

    Press feedback is valid motion (purpose: feedback) but it must respect the
    frequency gate: sidebar navigation is used tens of times a day, so it gets
    no press animation at all.
    """

    HANDLED_EVENTS = frozenset(
        (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Leave,
        )
    )

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # noqa: N802
        if event.type() not in self.HANDLED_EVENTS:
            return False
        if not isinstance(obj, QPushButton):
            return False
        if obj.property("nav"):
            return False
        try:
            if not obj.isEnabled():
                return False
        except RuntimeError:
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            _animate_press(obj, 0.86, DURATION_PRESS)
        else:
            _animate_press(obj, 1.0, DURATION_PRESS)
        return False


def _animate_press(button: QPushButton, target: float, duration: int) -> None:
    if _shutting_down or _reduce_motion:
        cancel_motion(button)
        return
    for animation in _animations(button):
        _detach(animation)
    button._dsh_animations = []

    effect = _opacity_effect(button)
    if abs(effect.opacity() - target) < 0.01:
        return
    animation = QPropertyAnimation(effect, b"opacity", button)
    animation.setDuration(effective_duration(duration))
    animation.setStartValue(effect.opacity())
    animation.setEndValue(target)
    animation.setEasingCurve(ease_out())
    if target >= 1.0:
        animation.finished.connect(lambda b=button: _finish_fade(b, None))
    _animations(button).append(animation)
    animation.start()


def install_press_feedback(app: QObject) -> None:
    """Install the press filter once per application instance."""
    global _press_filter
    if _press_filter is not None:
        return
    _press_filter = PressFeedbackFilter(app)
    app.installEventFilter(_press_filter)


def shutdown(app: QObject | None = None) -> None:
    """Drop every motion artifact so window teardown cannot touch them."""
    global _press_filter, _shutting_down
    _shutting_down = True
    if app is not None and _press_filter is not None:
        app.removeEventFilter(_press_filter)
    _press_filter = None
    if app is None:
        return
    for widget in app.allWidgets():  # type: ignore[attr-defined]
        transition = getattr(widget, "_dsh_transition", None)
        if transition is not None:
            transition.cancel()
        if getattr(widget, "_dsh_animations", None):
            cancel_motion(widget)
        elif isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
            widget.setGraphicsEffect(None)


def reset_shutdown_state() -> None:
    """Re-enable motion (used by tests and previews that reuse the process)."""
    global _shutting_down
    _shutting_down = False


def settle(milliseconds: int = 900) -> None:
    """Process events for a while so pending motion completes (preview/tools).

    Uses ``processEvents`` plus a real sleep instead of a nested event loop,
    because a queued ``quit`` from an earlier loop can end a new one instantly.
    """
    from PyQt6.QtCore import QElapsedTimer, QThread
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < max(0, int(milliseconds)):
        app.processEvents()
        QThread.msleep(10)
    app.processEvents()
