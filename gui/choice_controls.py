"""Native choices with independent focus preview and committed values."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

Choice = str | tuple[str, Any]
_UNSET = object()
_CONFIRM = {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}
_PREVIOUS = {Qt.Key.Key_Left, Qt.Key.Key_Up}
_NEXT = {Qt.Key.Key_Right, Qt.Key.Key_Down}


def _item(value: Choice) -> tuple[str, Any]:
    return value if isinstance(value, tuple) else (value, None)


class _Choice(QWidget):
    currentIndexChanged = pyqtSignal(int)
    currentTextChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None, accessible_name: str) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, Any]] = []
        self._index = -1
        self.setAccessibleName(accessible_name)

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:
        return self._items[index][0] if 0 <= index < self.count() else ""

    def itemData(self, index: int) -> Any:
        return self._items[index][1] if 0 <= index < self.count() else None

    def findText(self, text: str) -> int:
        return next((i for i, item in enumerate(self._items) if item[0] == text), -1)

    def findData(self, data: Any) -> int:
        return next((i for i, item in enumerate(self._items) if item[1] == data), -1)

    def currentIndex(self) -> int:
        return self._index

    def currentData(self) -> Any:
        return self.itemData(self._index)

    def currentText(self) -> str:
        return self.itemText(self._index)

    def setCurrentIndex(self, index: int) -> None:
        if not -1 <= index < self.count():
            return
        old = self._state()
        self._index = index
        self._set_text_from_index()
        self._render_selection()
        self._notify(old)

    def setCurrentText(self, text: str) -> None:
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)

    def addItem(self, text: str, userData: Any = None) -> None:
        self.addItems([(text, userData)])

    def addItems(self, items: Iterable[Choice]) -> None:
        additions = [_item(item) for item in items]
        if not additions:
            return
        old = self._state()
        was_empty = not self._items
        self._items.extend(additions)
        if was_empty and self._index < 0 and not self.currentText():
            self._index = 0
            self._set_text_from_index()
        self._render_items()
        self._notify(old)

    def clear(self) -> None:
        old = self._state()
        self._items.clear()
        self._index = -1
        self._set_text_from_index()
        self._render_items()
        self._notify(old)

    def _state(self) -> tuple[int, str]:
        return self._index, self.currentText()

    def _notify(self, previous: tuple[int, str]) -> None:
        index, text = self._state()
        if index != previous[0]:
            self.currentIndexChanged.emit(index)
        if text != previous[1] and self._state() == (index, text):
            self.currentTextChanged.emit(text)

    def _set_text_from_index(self) -> None:
        pass

    def _render_items(self) -> None:
        self._render_selection()

    def _render_selection(self) -> None:
        pass


class FixedChoice(_Choice):
    """Show every choice; arrow keys move focus without changing its value."""

    def __init__(
        self,
        items: Iterable[Choice] | None = None,
        parent: QWidget | None = None,
        *,
        accessible_name: str = "",
    ) -> None:
        super().__init__(parent, accessible_name)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._buttons: list[QPushButton] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        if items is not None:
            self.addItems(items)

    @property
    def option_buttons(self) -> tuple[QPushButton, ...]:
        return tuple(self._buttons)

    def _render_items(self) -> None:
        while len(self._buttons) > self.count():
            button = self._buttons.pop()
            self._grid.removeWidget(button)
            button.hide()
            button.deleteLater()
        for index in range(len(self._buttons), self.count()):
            button = QPushButton(self.itemText(index), self)
            button.setProperty("choiceOption", True)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.installEventFilter(self)
            button.clicked.connect(lambda _checked=False, i=index: self._activate(i))
            self._buttons.append(button)
        self._columns = 0
        self._reflow()
        self._render_selection()

    def _render_selection(self) -> None:
        focused = QApplication.focusWidget()
        active = self._buttons.index(focused) if focused in self._buttons else self._index
        self._set_tab_stop(max(0, active))
        for index, button in enumerate(self._buttons):
            button.setChecked(index == self._index)
            button.setAccessibleDescription("已选" if index == self._index else "")

    def _set_tab_stop(self, index: int) -> None:
        if not self._buttons:
            self.setFocusProxy(None)
            return
        for position, button in enumerate(self._buttons):
            policy = Qt.FocusPolicy.StrongFocus if position == index else Qt.FocusPolicy.ClickFocus
            button.setFocusPolicy(policy)
        self.setFocusProxy(self._buttons[index])

    def _reset_tab_stop(self) -> None:
        if QApplication.focusWidget() not in self._buttons:
            self._set_tab_stop(max(0, self._index))

    def _activate(self, index: int) -> None:
        self.setCurrentIndex(index)

    def _move_focus(self, index: int) -> None:
        self._set_tab_stop(index)
        self._buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._buttons:
            if event.type() == QEvent.Type.FocusIn:
                self._set_tab_stop(self._buttons.index(watched))
            elif event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self._reset_tab_stop)
            elif event.type() in {QEvent.Type.KeyPress, QEvent.Type.KeyRelease}:
                key = Qt.Key(event.key())
                if key in _CONFIRM:
                    if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                        self._activate(self._buttons.index(watched))
                    return True
                if event.type() == QEvent.Type.KeyPress:
                    index = self._buttons.index(watched)
                    if key in _PREVIOUS or key in _NEXT:
                        self._move_focus((index + (-1 if key in _PREVIOUS else 1)) % self.count())
                        return True
                    if key in {Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Escape}:
                        target = {Qt.Key.Key_Home: 0, Qt.Key.Key_End: self.count() - 1,
                                  Qt.Key.Key_Escape: max(0, self._index)}[key]
                        self._move_focus(target)
                        return True
        return super().eventFilter(watched, event)

    def minimumSizeHint(self) -> QSize:
        width = max((button.minimumSizeHint().width() for button in self._buttons), default=0)
        return QSize(width, self._grid.minimumSize().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        if not self._buttons:
            return
        widest = max(button.sizeHint().width() for button in self._buttons)
        gap = self._grid.spacing()
        columns = max(1, min(self.count(), (self.width() + gap) // (max(widest, 1) + gap)))
        if columns == self._columns:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, button in enumerate(self._buttons):
            self._grid.addWidget(button, index // columns, index % columns)
        self.updateGeometry()


class SearchChoice(_Choice):
    """Search the options without editing the current value until confirmation."""

    def __init__(
        self,
        items: Iterable[Choice] | None = None,
        parent: QWidget | None = None,
        *,
        editable: bool = False,
        accessible_name: str = "",
        search_placeholder: str = "搜索选项",
        open_label: str = "选择",
    ) -> None:
        super().__init__(parent, accessible_name)
        self._editable = False
        self._text_value = ""
        self._preview_cancelled = False
        self._open_label = open_label
        self._opener: QWidget | None = None
        self._popup_owner: QWidget | None = None
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("手动输入模型名称")
        self._edit.setAccessibleName(accessible_name or "手动输入")
        self._edit.textChanged.connect(self._on_edit_text)
        self._edit.installEventFilter(self)
        self.open_button = QPushButton(self)
        self.open_button.setProperty("choiceTrigger", True)
        self.open_button.setAutoDefault(False)
        self.open_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.open_button.setIcon(self.open_button.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.open_button.setIconSize(QSize(12, 12))
        self.open_button.setAccessibleName(f"查看{accessible_name or '全部选项'}")
        self.open_button.clicked.connect(self.showPopup)
        self.open_button.installEventFilter(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self._edit, 1)
        row.addWidget(self.open_button)

        self._popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup.setObjectName("choicePopup")
        self._popup.setAccessibleName(accessible_name or "选项列表")
        self._popup.installEventFilter(self)
        panel = QVBoxLayout(self._popup)
        panel.setContentsMargins(10, 10, 10, 10)
        panel.setSpacing(6)
        self.search_edit = QLineEdit(self._popup)
        self.search_edit.setObjectName("choiceSearch")
        self.search_edit.setPlaceholderText(search_placeholder)
        self.search_edit.setAccessibleName(search_placeholder)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.installEventFilter(self)
        panel.addWidget(self.search_edit)
        self.results = QListWidget(self._popup)
        self.results.setObjectName("choiceResults")
        self.results.setAccessibleName("匹配选项，方向键预览，回车确认")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.results.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.results.setMinimumSize(0, 0)
        self.results.itemClicked.connect(self._confirm_row)
        self.results.installEventFilter(self)
        panel.addWidget(self.results, 1)
        self._no_matches = QLabel(self._popup)
        self._no_matches.setObjectName("choiceEmpty")
        self._no_matches.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel.addWidget(self._no_matches, 1)
        self.setEditable(editable)
        if items is not None:
            self.addItems(items)

    def setEditable(self, enabled: bool) -> None:
        value = self.currentText()
        self._editable = enabled
        self._edit.setVisible(enabled)
        policy = QSizePolicy.Policy.Fixed if enabled else QSizePolicy.Policy.Ignored
        self.open_button.setSizePolicy(policy, QSizePolicy.Policy.Fixed)
        self.setFocusProxy(self._edit if enabled else self.open_button)
        if enabled:
            self._set_edit_text(value)
        self._render_selection()

    def isEditable(self) -> bool:
        return self._editable

    def lineEdit(self) -> QLineEdit | None:
        return self._edit if self._editable else None

    def setEditText(self, text: str) -> None:
        if self._editable:
            self._edit.setText(text)

    def currentText(self) -> str:
        return self._text_value if self._editable else super().currentText()

    def setCurrentText(self, text: str) -> None:
        if self._editable:
            self.setEditText(text)
        else:
            super().setCurrentText(text)

    def replaceItems(
        self,
        items: Iterable[Choice],
        *,
        current_text: str | None = None,
        current_data: Any = _UNSET,
    ) -> None:
        """Replace options once without interrupting the open search or its preview."""
        old = self._state()
        old_data = self.currentData()
        self._items = [_item(item) for item in items]
        if self._editable:
            text = old[1] if current_text is None else current_text
            self._index = self.findText(text)
            self._set_edit_text(text)
        else:
            data = old_data if current_data is _UNSET else current_data
            self._index = self.findData(data)
            if self._index < 0 and self._items:
                self._index = 0
        self._render_selection(data_refresh=True)
        self._notify(old)

    def _set_text_from_index(self) -> None:
        if self._editable:
            self._set_edit_text(self.itemText(self._index))

    def _set_edit_text(self, text: str) -> None:
        self._text_value = text
        if text != self._edit.text():
            old = self._edit.blockSignals(True)
            try:
                self._edit.setText(text)
            finally:
                self._edit.blockSignals(old)

    def _on_edit_text(self, text: str) -> None:
        old = self._state()
        self._text_value = text
        self._index = self.findText(text)
        self._render_selection()
        self._notify(old)

    def _render_selection(self, *, data_refresh: bool = False) -> None:
        if self._editable:
            self.open_button.setText(self._open_label)
        else:
            available = max(36, self.width() - 34)
            label = self.currentText() or self._open_label
            short = self.open_button.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, available)
            self.open_button.setText(short)
            self.open_button.setToolTip(label)
        if self.isPopupVisible():
            self._filter_results(data_refresh=data_refresh)

    def isPopupVisible(self) -> bool:
        return self._popup.isVisible()

    def showPopup(self) -> None:
        if not self.isVisible() or not self.isEnabled():
            return
        if self.isPopupVisible():
            self.hidePopup()
            return
        focused = QApplication.focusWidget()
        self._opener = focused if focused in (self._edit, self.open_button) else self.open_button
        self._popup_owner = self.window()
        self._popup_owner.installEventFilter(self)
        self._preview_cancelled = False
        self.search_edit.clear()
        self._filter_results(prefer_committed=True)
        self._place_popup()
        self._popup.show()
        self.search_edit.setFocus(Qt.FocusReason.PopupFocusReason)

    def hidePopup(self, *, restore_focus: bool = True) -> None:
        if not self.isPopupVisible():
            return
        opener = self._opener
        self._popup.hide()
        if restore_focus and opener is not None and opener.isVisible() and opener.isEnabled():
            opener.setFocus(Qt.FocusReason.PopupFocusReason)

    def _on_search_changed(self, _value: str) -> None:
        self._preview_cancelled = False
        self._filter_results()

    def _filter_results(self, *, prefer_committed: bool = False, data_refresh: bool = False) -> None:
        current = self.results.currentItem()
        data_role = Qt.ItemDataRole.UserRole + 1
        preview_data = None if current is None else current.data(data_role)
        preview_index = -1 if current is None else current.data(Qt.ItemDataRole.UserRole)
        preview_text = None if current is None else current.data(Qt.ItemDataRole.AccessibleTextRole)
        query = self.search_edit.text().strip().casefold()
        self.results.clear()
        preferred_row = -1
        for index, (text, data) in enumerate(self._items):
            if query and query not in text.casefold():
                continue
            selected = index == self._index
            entry = QListWidgetItem(("✓  " if selected else "    ") + text)
            entry.setData(Qt.ItemDataRole.UserRole, index)
            entry.setData(data_role, data)
            entry.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            entry.setData(Qt.ItemDataRole.AccessibleDescriptionRole, "已选" if selected else "回车确认")
            entry.setToolTip(text)
            same_preview = (
                data == preview_data if preview_data is not None
                else text == preview_text and (preferred_row < 0 or index == preview_index)
            )
            if (prefer_committed and selected) or (not prefer_committed and same_preview):
                preferred_row = self.results.count()
            self.results.addItem(entry)
        any_matches = bool(self.results.count())
        self._no_matches.setText("没有匹配选项" if query else "暂无可选项")
        self._no_matches.setVisible(not any_matches)
        self.results.setVisible(any_matches)
        if data_refresh and current is not None and preferred_row < 0:
            self._preview_cancelled = True
        if any_matches and preferred_row >= 0:
            self._preview_cancelled = False
            self.results.setCurrentRow(preferred_row)
        elif any_matches and not self._preview_cancelled:
            self.results.setCurrentRow(0)
        else:
            # If a result vanished, Enter must not silently confirm another result.
            if self.results.hasFocus():
                self.search_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self.results.setCurrentRow(-1)
        if self.isPopupVisible():
            self._place_popup()

    def _confirm_row(self, item: QListWidgetItem | None) -> None:
        if item is not None:
            index = int(item.data(Qt.ItemDataRole.UserRole))
            self.hidePopup()
            self.setCurrentIndex(index)

    def _place_popup(self) -> None:
        owner = self._popup_owner or self.window()
        window_bounds = QRect(owner.mapToGlobal(QPoint()), owner.size())
        screen = self.screen()
        if screen is not None:
            window_bounds = window_bounds.intersected(screen.availableGeometry())
        bounds = window_bounds.adjusted(6, 6, -6, -6)
        if not bounds.isValid():
            bounds = window_bounds
        if not bounds.isValid():
            return
        anchor = QRect(self.mapToGlobal(QPoint()), self.size())
        width = min(max(anchor.width(), 250), bounds.width())
        row_height = max(26, self.results.sizeHintForRow(0))
        chrome = self.search_edit.sizeHint().height() + 28
        desired = max(chrome + 50, chrome + row_height * min(8, self.results.count()))
        below = max(0, bounds.bottom() - anchor.bottom() - 5)
        above = max(0, anchor.top() - bounds.top() - 5)
        use_below = below >= desired or below >= above
        side = below if use_below else above
        height = min(desired, side if side >= chrome + 24 else bounds.height())
        x = max(bounds.left(), min(anchor.left(), bounds.right() - width + 1))
        proposed_y = anchor.bottom() + 5 if use_below else anchor.top() - height - 5
        y = max(bounds.top(), min(proposed_y, bounds.bottom() - height + 1))
        self._popup.setGeometry(x, y, width, height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._editable:
            self._render_selection()
        elif self.isPopupVisible():
            self._place_popup()

    def hideEvent(self, event) -> None:
        self.hidePopup(restore_focus=False)
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.hidePopup(restore_focus=False)
        super().changeEvent(event)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if watched is getattr(self, "_popup", None) and kind == QEvent.Type.Hide:
            if self._popup_owner is not None:
                self._popup_owner.removeEventFilter(self)
            self._popup_owner = None
            self._opener = None
        if watched is self._popup_owner:
            if kind in {QEvent.Type.Resize, QEvent.Type.Move}:
                QTimer.singleShot(0, self._place_if_open)
            elif kind in {QEvent.Type.Hide, QEvent.Type.Close}:
                self.hidePopup(restore_focus=False)
        if kind != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        key = Qt.Key(event.key())
        if watched in (self._edit, getattr(self, "open_button", None)):
            shortcut = key == Qt.Key.Key_F4 or (key == Qt.Key.Key_Down and
                        (watched is self.open_button or event.modifiers() & Qt.KeyboardModifier.AltModifier))
            if shortcut or (watched is self.open_button and key in _CONFIRM):
                if not event.isAutoRepeat():
                    self.showPopup()
                return True
        if watched in (getattr(self, "search_edit", None), getattr(self, "results", None)):
            if key == Qt.Key.Key_Escape:
                self.hidePopup()
                return True
            if key in {Qt.Key.Key_Enter, Qt.Key.Key_Return} or (
                watched is self.results and key == Qt.Key.Key_Space
            ):
                if not event.isAutoRepeat():
                    self._confirm_row(self.results.currentItem())
                return True
            if key in {Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown}:
                delta = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1,
                         Qt.Key.Key_PageUp: -6, Qt.Key.Key_PageDown: 6}[key]
                row = self.results.currentRow()
                if self.results.count():
                    self._preview_cancelled = False
                    self.results.setCurrentRow(max(0, min(row + delta, self.results.count() - 1)))
                return True
        return super().eventFilter(watched, event)

    def _place_if_open(self) -> None:
        if self.isPopupVisible():
            self._place_popup()
