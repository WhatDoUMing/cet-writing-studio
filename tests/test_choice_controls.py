"""Native choice interaction and Settings model catalog regression tests."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from ai.model_catalog import ModelCatalog
from gui.choice_controls import FixedChoice, SearchChoice
from tests.test_workflow_sessions import APP, CapturingPool, make_window


@pytest.fixture
def panel():
    widget = QWidget()
    layout = QVBoxLayout(widget)
    yield widget, layout
    widget.close()
    APP.processEvents()


def show_panel(widget):
    widget.show()
    APP.setActiveWindow(widget)
    APP.processEvents()


def test_fixed_choices_separate_keyboard_focus_and_committed_selection(panel):
    widget, layout = panel
    first, after = QLineEdit(), QLineEdit()
    choices = FixedChoice([("学生练习", "student"), ("教师批改", "teacher")])
    for control in (first, choices, after):
        layout.addWidget(control)
    show_panel(widget)
    selected, next_choice = choices.option_buttons
    choices.setFocus()
    assert selected.hasFocus() and selected.isChecked()
    changed = QSignalSpy(choices.currentIndexChanged)

    QTest.keyClick(selected, Qt.Key.Key_Right)
    assert next_choice.hasFocus()
    assert selected.isChecked() and not next_choice.isChecked()
    assert choices.currentData() == "student" and len(changed) == 0

    QTest.keyClick(next_choice, Qt.Key.Key_Escape)
    assert selected.hasFocus() and len(changed) == 0
    QTest.keyClick(selected, Qt.Key.Key_Right)
    QTest.keyClick(next_choice, Qt.Key.Key_Return)
    assert choices.currentData() == "teacher" and next_choice.isChecked()
    assert len(changed) == 1
    QTest.keyClick(next_choice, Qt.Key.Key_Return)
    assert len(changed) == 1
    QTest.keyClick(next_choice, Qt.Key.Key_Tab)
    assert after.hasFocus()


def test_fixed_choices_wrap_in_a_narrow_panel(panel):
    widget, layout = panel
    choices = FixedChoice(["在线识别（推荐）", "本地识别", "仅手动粘贴"])
    layout.addWidget(choices)
    widget.resize(215, 180)
    show_panel(widget)
    assert len({option.y() for option in choices.option_buttons}) > 1
    assert all(choices.rect().contains(option.geometry()) for option in choices.option_buttons)


def test_search_popup_stable_duplicate_keys_and_single_confirmation(panel):
    widget, layout = panel
    choices = SearchChoice(
        [("全部题目", None), ("共享题目", "CET-4:shared"), ("共享题目", "CET-6:shared")]
        + [(f"其它题目 {number}", f"other:{number}") for number in range(250)]
    )
    layout.addWidget(choices)
    show_panel(widget)
    changed = QSignalSpy(choices.currentIndexChanged)
    choices.open_button.setFocus()
    QTest.keyClick(choices.open_button, Qt.Key.Key_Return)
    assert choices.isPopupVisible()
    assert choices.results.item(0).text().startswith("✓")
    assert not choices.open_button.icon().isNull()
    choices.search_edit.setText("共享题目")
    assert choices.results.count() == 2
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Down)
    assert choices.currentData() is None and len(changed) == 0
    assert choices.itemData(choices.results.currentItem().data(Qt.ItemDataRole.UserRole)) == "CET-6:shared"

    QTest.keyClick(choices.search_edit, Qt.Key.Key_Return)
    assert choices.currentData() == "CET-6:shared"
    assert not choices.isPopupVisible() and choices.open_button.hasFocus()
    assert len(changed) == 1
    choices.showPopup()
    choices.search_edit.setText("不存在的题目")
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Return)
    assert choices.isPopupVisible() and choices.results.count() == 0
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Escape)
    assert not choices.isPopupVisible() and choices.open_button.hasFocus()
    assert choices.currentData() == "CET-6:shared" and len(changed) == 1


def test_popup_stays_inside_a_narrow_window(panel):
    widget, layout = panel
    layout.addStretch()
    choices = SearchChoice([f"A very long model name {number}" for number in range(30)])
    layout.addWidget(choices)
    widget.resize(230, 215)
    show_panel(widget)
    choices.showPopup()
    APP.processEvents()

    viewport = QRect(widget.mapToGlobal(QPoint()), widget.size())
    viewport = viewport.intersected(widget.screen().availableGeometry())
    popup = choices.findChild(QWidget, "choicePopup")
    assert popup is not None and popup.isVisible()
    assert viewport.contains(popup.geometry())
    assert popup.width() < 250
    choices.hidePopup()


@pytest.fixture
def setting_panel(tmp_path, monkeypatch):
    window, _db = make_window(tmp_path)
    monkeypatch.setattr(window.config, "get_ocr_api_key", lambda provider=None, fallback=True: None)
    monkeypatch.setattr(window.config, "set_api_key", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(window.config, "set_ocr_api_key", lambda *_args, **_kwargs: None)
    pool = CapturingPool()
    monkeypatch.setattr("gui.settings_page.QThreadPool", SimpleNamespace(globalInstance=lambda: pool))
    show_panel(window)
    window._open_settings()
    mode = window.settings_page.ocr_mode_combo
    mode.setCurrentIndex(mode.findData("online"))
    APP.processEvents()
    yield window, window.settings_page, pool
    window.close()
    APP.processEvents()


def model_fields(page, purpose):
    if purpose == "scoring":
        return page.model_combo, page.model_edit, page.models_btn
    return page.online_ocr_model_combo, page.online_ocr_model_edit, page.ocr_models_btn


def catalog(*models):
    return ModelCatalog(models, "api", "https://example.test/models")


def test_settings_use_direct_choices_for_all_five_short_groups(setting_panel):
    _window, page, _pool = setting_panel
    direct = (
        page.provider_combo, page.ocr_mode_combo, page.online_ocr_provider_combo,
        page.usage_mode_combo, page.theme_combo,
    )
    assert all(isinstance(widget, FixedChoice) and len(widget.option_buttons) >= 2 for widget in direct)
    assert isinstance(page.model_combo, SearchChoice) and page.model_combo.isEditable()
    assert isinstance(page.online_ocr_model_combo, SearchChoice) and page.online_ocr_model_combo.isEditable()


@pytest.mark.parametrize("purpose", ["scoring", "ocr"])
def test_pending_model_lists_preserve_custom_text_and_no_result_escape(setting_panel, purpose):
    _window, page, pool = setting_panel
    combo, edit, fetch = model_fields(page, purpose)
    fetch.click()
    assert len(pool.workers) == 1
    edit.setText("my-custom-model")
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key.Key_F4)
    assert combo.isPopupVisible()
    combo.search_edit.setText("does-not-match")
    pool.workers[0].signals.finished.emit(catalog("provider-model-a", "provider-model-b"))

    assert combo.isPopupVisible()
    assert combo.search_edit.text() == "does-not-match"
    assert combo.results.count() == 0
    assert combo.findText("provider-model-b") >= 0
    assert combo.currentText() == edit.text() == "my-custom-model"
    QTest.keyClick(combo.search_edit, Qt.Key.Key_Escape)
    assert not combo.isPopupVisible() and edit.hasFocus()
    assert edit.text() == "my-custom-model"


@pytest.mark.parametrize("purpose", ["scoring", "ocr"])
@pytest.mark.parametrize("change", ["provider", "key", "leave"])
def test_stale_catalog_cannot_overwrite_or_open_popup(setting_panel, purpose, change):
    window, page, pool = setting_panel
    combo, edit, fetch = model_fields(page, purpose)
    fetch.click()
    assert len(pool.workers) == 1
    combo.showPopup()
    assert combo.isPopupVisible()
    if change == "provider":
        provider = page.provider_combo if purpose == "scoring" else page.online_ocr_provider_combo
        provider.setCurrentIndex((provider.currentIndex() + 1) % provider.count())
    elif change == "key":
        key = page.api_key_edit if purpose == "scoring" else page.ocr_api_key_edit
        key.setText("synthetic-new-key")
    else:
        window._navigate(0)
    text = edit.text()
    assert not combo.isPopupVisible()
    pool.workers[0].signals.finished.emit(catalog("obsolete-model"))

    assert not combo.isPopupVisible() and combo.findText("obsolete-model") == -1
    assert edit.text() == text


def test_disabling_ocr_controls_keeps_online_value_and_closes_search(setting_panel):
    _window, page, _pool = setting_panel
    mode = page.ocr_mode_combo
    combo = page.online_ocr_model_combo
    page.online_ocr_model_edit.setText("custom-vision-model")
    combo.showPopup()
    assert combo.isPopupVisible()
    for alternative in ("local", "manual"):
        mode.setCurrentIndex(mode.findData(alternative))
        assert not combo.isEnabled() and not combo.isPopupVisible()
        assert not page.ocr_balance_btn.isEnabled()
        assert page.online_ocr_model_edit.text() == "custom-vision-model"
    mode.setCurrentIndex(mode.findData("online"))
    assert combo.isEnabled() and page.ocr_balance_btn.isEnabled()
    assert page.online_ocr_model_edit.text() == "custom-vision-model"

def test_atomic_search_refresh_keeps_pending_key_and_does_not_commit_missing_preview(panel):
    widget, layout = panel
    options = [("全部题目", None), ("同名题", "CET-4:ask"), ("同名题", "CET-6:ask")]
    choices = SearchChoice(options)
    layout.addWidget(choices)
    show_panel(widget)
    changed = QSignalSpy(choices.currentIndexChanged)

    choices.showPopup()
    choices.search_edit.setText("同名题")
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Down)
    assert choices.itemData(choices.results.currentItem().data(Qt.ItemDataRole.UserRole)) == "CET-6:ask"

    # Reordering duplicate labels is not a new preview or a committed choice.
    choices.replaceItems([options[0], options[2], options[1]], current_data=None)
    assert choices.search_edit.text() == "同名题"
    assert choices.currentData() is None and len(changed) == 0
    assert choices.itemData(choices.results.currentItem().data(Qt.ItemDataRole.UserRole)) == "CET-6:ask"

    # If the preview disappears, the remaining row must not silently become enter's target.
    choices.replaceItems(options[:2], current_data=None)
    assert choices.results.count() == 1 and choices.results.currentItem() is None
    choices.replaceItems(options[:2], current_data=None)
    assert choices.results.currentItem() is None
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Return)
    assert choices.isPopupVisible() and choices.currentData() is None and len(changed) == 0
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Down)
    QTest.keyClick(choices.search_edit, Qt.Key.Key_Return)
    assert choices.currentData() == "CET-4:ask" and len(changed) == 1
