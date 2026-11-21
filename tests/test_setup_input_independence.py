from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from tests.test_workflow_sessions import APP, make_window


@pytest.mark.parametrize("usage_index", [0, 1])
def test_exam_choice_and_input_method_are_independent(tmp_path: Path, usage_index: int) -> None:
    window, db = make_window(tmp_path)
    try:
        window.resize(800, 600)
        window.show()
        APP.setActiveWindow(window)
        window.mode_combo.setCurrentIndex(usage_index)
        window._open_new_setup()
        APP.processEvents()
        page = window.setup_page
        cet4, cet6 = (page.mode_buttons[level] for level in ("CET-4", "CET-6"))
        header4, header6 = window.exam_combo.option_buttons

        def check(level: str, *, manual: bool) -> None:
            APP.processEvents()
            assert window.exam_level == window.exam_combo.currentText() == level
            assert page.mode_group.checkedButton() is page.mode_buttons[level]
            assert page.input_mode_group.checkedButton() is (page.manual_mode_radio if manual else page.ocr_mode_radio)
            assert page.image_field.isVisible() != manual
            assert page.start_btn.text() == ("继续输入作文正文" if manual else "识别图片并确认文本")
            assert window.stack.currentWidget() is page

        page.student_name.setText("四级草稿")
        page.question_edit.setPlainText("CET-4 is an independent question.")
        page.minimum_words.setValue(132)
        page._excellent_path = "cet4-reference.txt"

        QTest.mouseClick(cet6, Qt.MouseButton.LeftButton)
        check("CET-6", manual=True)
        assert page.student_name.text() == page.question_edit.toPlainText() == ""
        assert page.minimum_words.value() == 0 and not page._excellent_path
        page.student_name.setText("六级草稿")
        page.question_edit.setPlainText("CET-6 is another question.")
        page.minimum_words.setValue(156)
        page._excellent_path = "cet6-reference.txt"
        page.manual_mode_radio.setFocus()
        QTest.keyClick(page.manual_mode_radio, Qt.Key.Key_Right)
        check("CET-6", manual=False)

        cet6.setFocus()
        QTest.keyClick(cet6, Qt.Key.Key_Left)
        check("CET-4", manual=False)
        assert page.student_name.text() == "四级草稿"
        assert page.question_edit.toPlainText() == "CET-4 is an independent question."
        assert page.minimum_words.value() == 132 and page._excellent_path == "cet4-reference.txt"

        QTest.mouseClick(page.manual_mode_radio, Qt.MouseButton.LeftButton)
        check("CET-4", manual=True)
        QTest.mouseClick(header6, Qt.MouseButton.LeftButton)
        check("CET-6", manual=True)
        assert page.student_name.text() == "六级草稿"
        assert page.question_edit.toPlainText() == "CET-6 is another question."
        assert page.minimum_words.value() == 156 and page._excellent_path == "cet6-reference.txt"

        header6.setFocus()
        QTest.keyClick(header6, Qt.Key.Key_Left)
        check("CET-6", manual=True)
        assert header4.hasFocus()
        QTest.keyClick(header4, Qt.Key.Key_Space)
        check("CET-4", manual=True)
        QTest.keyClick(page.start_btn, Qt.Key.Key_Space)
        assert window.stack.currentWidget() is window.ocr_page
        assert window._draft["input_mode"] == "manual"
        assert window._draft["essay_type"] == "CET-4"
        assert window._draft["student_name"] == "四级草稿"
        assert db.count_essays() == 0
    finally:
        window.close()
        db.close()
        APP.processEvents()
