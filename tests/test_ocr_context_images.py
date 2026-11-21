import os
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog

from gui.styles import get_app_style, prepare_fonts
from tests.test_workflow_sessions import APP, make_window


@pytest.mark.parametrize("usage_index", [0, 1], ids=["student", "teacher"])
@pytest.mark.parametrize("input_method", ["mouse", "keyboard"])
@pytest.mark.parametrize("cet4_uses_image", [False, True], ids=["manual-and-ocr", "two-images"])
def test_context_restore_has_its_own_ocr_picture_and_actions(
    tmp_path: Path, monkeypatch, usage_index: int, input_method: str, cet4_uses_image: bool,
) -> None:
    colors = {"CET-4": QColor("#e13d47"), "CET-6": QColor("#286cd9")}
    pictures = {}
    for level, color in colors.items():
        img = QImage(94, 70, QImage.Format.Format_RGB32)
        img.fill(color)
        path = tmp_path / f"{level}-synthetic.png"
        assert img.save(str(path))
        pictures[level] = str(path)
    prepare_fonts(APP, private_dir=Path(__file__).resolve().parents[1] / 'work/preview/fonts')
    window, db = make_window(tmp_path)
    theme = 'dark' if os.environ.get('QT_SCALE_FACTOR') == '1.5' else 'light'
    window.setStyleSheet(get_app_style(theme))
    engine = object()
    fake_factory_calls = []
    monkeypatch.setattr(window, "_create_ocr_engine", lambda: fake_factory_calls.append(True) or engine)
    bodies = {"CET-4": "Original text for level four.", "CET-6": "Different source text for level six."}
    try:
        window.resize(800, 600)
        window.show()
        APP.setActiveWindow(window)
        window.mode_combo.setCurrentIndex(usage_index)
        window._open_new_setup()
        page = window.setup_page
        review = window.ocr_page
        click = lambda control: QTest.mouseClick(control, Qt.MouseButton.LeftButton)

        def switch(level: str) -> None:
            current = window.exam_combo.option_buttons[0 if level == "CET-6" else 1]
            target = window.exam_combo.option_buttons[1 if level == "CET-6" else 0]
            if input_method == "mouse":
                click(target)
            else:
                current.setFocus()
                QTest.keyClick(current, Qt.Key.Key_Right if level == "CET-6" else Qt.Key.Key_Left)
                assert target.hasFocus()
                QTest.keyClick(target, Qt.Key.Key_Space)
            APP.processEvents()
            assert window.exam_level == window.exam_combo.currentText() == level
            assert page.mode_group.checkedButton() is page.mode_buttons[level]

        def confirm(level: str, with_image: bool) -> None:
            page.student_name.setText(level + " test name")
            page.question_edit.setPlainText(level + " isolated topic.")
            if with_image:
                if not page.ocr_mode_radio.isChecked():
                    click(page.ocr_mode_radio)
                monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (pictures[level], ""))
                click(page.pick_image_btn)
                assert page.capture_draft()["image_path"] == pictures[level]
            elif not page.manual_mode_radio.isChecked():
                click(page.manual_mode_radio)
            click(page.start_btn)
            APP.processEvents()
            assert window.stack.currentWidget() is review
            if with_image:
                worker = window.thread_pool.workers[-1]
                assert worker.image_path == pictures[level] and worker.engine is engine
                worker.signals.finished.emit(bodies[level])
            else:
                QTest.keyClicks(review.text_edit, bodies[level])
            APP.processEvents()

        def assert_review_matches(level: str, with_image: bool) -> None:
            assert window.stack.currentWidget() is review
            expected_picture = pictures[level] if with_image else ""
            assert window._draft["image_path"] == expected_picture
            assert review.get_text() == bodies[level]
            assert review._current_image_path == expected_picture
            assert review.image_panel.isVisible() is with_image
            assert review.re_btn.isVisible() is with_image
            assert review.re_btn.isEnabled() is with_image
            assert review.image_label.toolTip() == expected_picture
            if with_image:
                assert review.image_label.pixmap().toImage().pixelColor(1, 1) == colors[level]
                assert review.text_header.text() == "识别文本（可直接修改）"
            else:
                assert review.image_label.pixmap().isNull()
                assert review.text_header.text() == "作文原文（可直接编辑）"

        confirm("CET-4", cet4_uses_image)
        assert_review_matches("CET-4", cet4_uses_image)
        switch("CET-6")
        assert window.stack.currentWidget() is page
        assert page.manual_mode_radio.isChecked() is (not cet4_uses_image)
        confirm("CET-6", True)
        assert_review_matches("CET-6", True)

        initialized = len(fake_factory_calls)
        switch("CET-4")
        assert_review_matches("CET-4", cet4_uses_image)
        assert window.grab().save(str(tmp_path / "restored-CET-4.png"))
        assert page.ocr_mode_radio.isChecked()   # The current form preference is not the saved workflow's source.
        switch("CET-6")
        assert_review_matches("CET-6", True)
        assert window.grab().save(str(tmp_path / "restored-CET-6.png"))
        assert len(fake_factory_calls) == initialized   # No recognition or engine prompts just by switching.
        click(review.re_btn)
        APP.processEvents()
        worker = window.thread_pool.workers[-1]
        assert worker.image_path == pictures["CET-6"] and worker.engine is engine
        assert len(fake_factory_calls) == initialized + 1
        assert review.re_btn.isVisible() and not review.re_btn.isEnabled()
        switch("CET-4")
        worker.signals.finished.emit("Stale OCR text must not cross contexts.")
        APP.processEvents()
        assert_review_matches("CET-4", cet4_uses_image)
    finally:
        window.close()
        db.close()
        APP.processEvents()

@pytest.mark.parametrize("action", ["same", "different-topic", "different-student", "fresh"])
def test_return_to_setup_only_resumes_same_manual_workflow(tmp_path: Path, action: str) -> None:
    from PyQt6.QtWidgets import QPushButton

    window, db = make_window(tmp_path)
    try:
        window.show()
        window._open_new_setup()
        page, review = window.setup_page, window.ocr_page
        page.student_name.setText("Synthetic student")
        page.question_edit.setPlainText("One independent question.")
        QTest.mouseClick(page.start_btn, Qt.MouseButton.LeftButton)
        assert window.stack.currentWidget() is review
        original = "  A manually edited paragraph.\nAnd a second line.  "
        review.text_edit.setPlainText(original)
        back = next(button for button in review.findChildren(QPushButton) if button.text() == "返回题目设置")
        QTest.mouseClick(back, Qt.MouseButton.LeftButton)
        assert window.stack.currentWidget() is page

        if action == "fresh":
            QTest.mouseClick(window.nav_buttons[1], Qt.MouseButton.LeftButton)
            assert not page.question_edit.toPlainText()
            page.student_name.setText("Synthetic student")
            page.question_edit.setPlainText("One independent question.")
        elif action == "different-topic":
            page.question_edit.setPlainText("An unrelated question.")
        elif action == "different-student":
            page.student_name.setText("Other synthetic student")

        QTest.keyClick(page.start_btn, Qt.Key.Key_Space)
        assert window.stack.currentWidget() is review
        assert review.text_edit.toPlainText() == (original if action == "same" else "")
        assert review.image_panel.isHidden() and review.re_btn.isHidden()
        assert db.count_essays() == 0
    finally:
        window.close()
        db.close()
        APP.processEvents()
