from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox, QSpinBox

from cet_scoring import length_requirement
from tests.test_workflow_sessions import APP, finish_current_grading, make_window, report


@pytest.mark.parametrize(("level", "default_words"), [("CET-4", 120), ("CET-6", 150)])
def test_minimum_words_hides_only_native_buttons(tmp_path: Path, level: str, default_words: int) -> None:
    window, db = make_window(tmp_path)
    try:
        window.show()
        window._open_new_setup()
        setup = window.setup_page
        setup.mode_buttons[level].click()
        setup.student_name.setText("测试学生")
        question = "Practice topic with no stated word count."
        setup.question_edit.setPlainText(question)
        spin = setup.minimum_words
        spin.setFocus()
        APP.processEvents()

        assert spin.buttonSymbols() == QSpinBox.ButtonSymbols.NoButtons
        assert (spin.minimum(), spin.maximum()) == (0, 5000)
        assert spin.text() == "按题目文字 / 考试默认"
        QTest.keyClick(spin, Qt.Key.Key_Down)
        assert spin.value() == 0
        setup.start_btn.click()
        assert window._draft["minimum_words"] is None
        assert length_requirement(level, question, window._draft["minimum_words"]) == (default_words, None)

        window._open_new_setup()
        setup.mode_buttons[level].click()
        setup.student_name.setText("测试学生")
        setup.question_edit.setPlainText(question)
        spin.setFocus()
        APP.processEvents()
        spin.setValue(5000)
        QTest.keyClick(spin, Qt.Key.Key_Up)
        assert spin.value() == 5000
        spin.setValue(2)
        QTest.keyClick(spin, Qt.Key.Key_Up)
        assert spin.value() == 3
        QTest.keyClick(spin, Qt.Key.Key_Down)
        assert spin.value() == 2
        spin.setValue(0)
        entry = spin.lineEdit()
        entry.selectAll()
        QTest.keyClicks(entry, "137")
        spin.interpretText()
        assert spin.value() == 137
        assert spin.text() == "137 词"
        setup.start_btn.click()
        assert window._draft["minimum_words"] == 137

        window._start_grading("A synthetic essay with enough text for the grading form.")
        essay_id = finish_current_grading(window, report(12))
        assert db.get_essay(essay_id)["minimum_words"] == 137
    finally:
        window.close()
        db.close()


def test_history_hint_matches_all_three_existing_search_fields(tmp_path: Path) -> None:
    window, db = make_window(tmp_path)
    try:
        expected_id = db.create_essay("海星", "CET-4", "城市漫步", question_summary="周末观察")
        other_id = db.create_essay("松树", "CET-4", "校园图书馆", question_summary="读书分享")
        window._open_history()
        page = window.history_page
        search = page.search_edit
        assert search.placeholderText() == "搜索学生姓名或题目，也可搜摘要"
        for term in ("海星", "城市漫步", "周末观察"):
            search.setText(term)
            assert [record["id"] for record in page.records] == [expected_id]
        search.setText("没有匹配")
        assert not page.records
        search.clear()
        assert {record["id"] for record in page.records} == {expected_id, other_id}
    finally:
        window.close()
        db.close()


def test_manual_setup_copy_persists_on_restore_and_continue_accepts_keyboard(tmp_path: Path) -> None:
    window, db = make_window(tmp_path)
    try:
        setup = window.setup_page
        hint = "可上传本考试级别的优秀作文作评分参考"
        assert setup.example_label.text() == hint

        window.resize(800, 600)
        window.show()
        APP.setActiveWindow(window)
        window._open_new_setup()
        assert setup.example_label.text() == hint
        assert setup.start_btn.text() == "继续输入作文正文"
        setup.restore_draft({"excellent_path": "sample.txt"})
        assert setup.example_label.text() == "sample.txt"
        setup.restore_draft({"question": "A synthetic essay topic."})
        assert setup.example_label.text() == hint

        setup.pick_example_btn.setFocus(Qt.FocusReason.TabFocusReason)
        APP.processEvents()
        QTest.keyClick(setup.pick_example_btn, Qt.Key.Key_Tab)
        assert APP.focusWidget().text() == "返回首页"
        QTest.keyClick(APP.focusWidget(), Qt.Key.Key_Tab)
        assert setup.start_btn.hasFocus()
        QTest.keyClick(setup.start_btn, Qt.Key.Key_Space)
        assert window.stack.currentWidget() is window.ocr_page
        assert window._draft["input_mode"] == "manual"
        assert window._draft["image_path"] == ""
    finally:
        window.close()
        db.close()


def test_ocr_keeps_recognition_action_and_requires_a_selected_image(tmp_path: Path, monkeypatch) -> None:
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _widget, title, _text: warnings.append(title))
    window, db = make_window(tmp_path)
    try:
        window.show()
        window._open_new_setup()
        setup = window.setup_page
        setup.question_edit.setPlainText("A synthetic essay topic.")
        setup.ocr_mode_radio.click()
        assert setup.start_btn.text() == "识别图片并确认文本"
        assert setup.image_field.isVisible() and setup.pick_image_btn.isEnabled()
        QTest.mouseClick(setup.start_btn, Qt.MouseButton.LeftButton)
        assert warnings == ["缺少图片"]
        assert window.stack.currentWidget() is setup

        picture = tmp_path / "synthetic.png"
        image = QImage(100, 50, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(picture))
        setup.restore_draft({"manual": False, "question": "A synthetic essay topic.", "image_path": str(picture)})
        QTest.mouseClick(setup.start_btn, Qt.MouseButton.LeftButton)
        assert window.stack.currentWidget() is window.ocr_page
        assert window._draft["input_mode"] == "ocr"
        assert window._draft["image_path"] == str(picture)
        assert not window.thread_pool.workers  # Manual fixture intentionally has no real OCR backend.
    finally:
        window.close()
        db.close()
