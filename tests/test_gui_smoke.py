import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

from config_manager import ConfigManager
from database.sqlite import Database
from gui.main_window import MainWindow
from memory.manager import MemoryManager
from ocr.trocr_engine import TrOCREngine


def test_main_window_initializes(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default_settings.json").write_text(
        '{"app":{"name":"Test"},"paths":{"database":"data/test.db",'
        '"models":"models","logs":"logs","memory":"memory/rules.md"},'
        '"ocr":{"mode":"local",'
        '"model_name":"microsoft/trocr-base-handwritten"}}',
        encoding="utf-8",
    )
    app = QApplication.instance() or QApplication([])
    config = ConfigManager(tmp_path)
    db = Database(tmp_path / "data" / "test.db")
    db.connect()
    memory = MemoryManager(tmp_path / "memory" / "rules.md")
    engine = TrOCREngine(config.get("ocr", {}))
    window = MainWindow(config, db, memory, engine)
    assert window.stack.count() == 6
    assert [button.text() for button in window.nav_buttons] == [
        "首页",
        "开始写作",
        "文本确认",
        "历史记录",
    ]
    window.nav_buttons[3].click()
    assert window.stack.currentWidget() is window.history_page
    window.history_page.load_history(
        [
            {
                "id": 1,
                "time": "2026-09-15T10:00:00",
                "student_name": None,
                "type": "CET-4",
                "question": "Same question",
                "question_summary": "同题摘要",
                "score": "10", "ai_score": "10",
                "report_json": "{}",
                "ocr_text": "text one",
            },
            {
                "id": 2,
                "time": "2026-09-15T11:00:00",
                "student_name": "Alice",
                "type": "CET-4",
                "question": "Same question",
                "question_summary": "同题摘要",
                "score": "13", "ai_score": "13",
                "report_json": "{}",
                "ocr_text": "text two",
            },
            {
                "id": 3,
                "time": "2026-09-15T12:00:00",
                "student_name": "Bob",
                "type": "CET-6",
                "question": "Other question",
                "question_summary": "其他摘要",
                "score": "",
                "report_json": "{}",
                "ocr_text": "",
            },
        ],
        [],
    )
    assert len(window.history_page._groups) == 2
    shared_group = window.history_page._groups["CET-4:same question"]
    scores = [
        record["score"] for record in shared_group["records"]
    ]
    assert scores == ["13", "10"]
    assert window.history_page.group_combo.count() == 3
    group_counts = [
        label.text()
        for label in window.history_page.findChildren(
            QLabel,
            "groupCount",
        )
    ]
    assert "2 条记录" in group_counts
    assert window.settings_page.provider_combo.count() == 3
    assert window.settings_page.ocr_mode_combo.count() == 3
    assert window.settings_page.online_ocr_provider_combo.count() == 3
    assert window.settings_page.ocr_api_key_edit.placeholderText()
    assert window.settings_page.balance_btn.text() == "检测余额"
    assert window.settings_page.ocr_balance_btn.text() == "检测余额"
    assert "CET-4" in window.setup_page.mode_notice.text()
    window.setup_page.mode_buttons["CET-6"].setChecked(True)
    window.setup_page._update_mode_notice()
    assert "CET-6" in window.setup_page.mode_notice.text()
    window.setup_page.manual_mode_radio.setChecked(True)
    window.setup_page._update_input_mode_controls()
    assert window.setup_page.pick_image_btn.isEnabled() is False
    openai_index = window.settings_page.provider_combo.findData("openai")
    window.settings_page.provider_combo.setCurrentIndex(openai_index)
    assert window.settings_page.model_edit.text() == "gpt-5-mini"

    image_path = tmp_path / "sample.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    window.ocr_page.set_image(image_path)
    assert window.ocr_page.image_label.pixmap() is not None

    class FakeOCR:
        def recognize(self, _path, *, use_lines=True):
            assert use_lines is True
            return "I like this activity."

    window.ocr_engine = FakeOCR()
    window._start_recognition(
        {
            "student_name": "测试学生",
            "essay_type": "CET-4",
            "max_score": "15",
            "question": "测试题目",
            "input_mode": "ocr",
            "image_path": str(image_path),
            "excellent_path": "",
        }
    )
    QTest.qWait(200)
    assert window.stack.currentWidget() is window.ocr_page
    assert window.ocr_page.get_text() == "I like this activity."

    pasted_text = (
        "First and foremost, classics consist of timeless philosophical "
        "insights and unmatched artistic expertise. They have been vividly "
        "carved in the minds of generations with great activty and walue."
    )
    window.ocr_page.set_text(pasted_text)
    assert window.ocr_page.get_text() == pasted_text
    assert not window.ocr_page.text_edit.extraSelections()
    window.ocr_page.check_btn.click()
    for _ in range(40):
        QTest.qWait(15)
        if not window.ocr_page._spell_check_running:
            break
    assert window.ocr_page._hints_checked is True
    assert window.ocr_page.fix_btn.isHidden() is False

    first_hint = next(
        hint
        for hint in window.ocr_page._hints
        if hint.original == "activty"
    )
    cursor = QTextCursor(window.ocr_page.text_edit.document())
    cursor.setPosition(first_hint.start)
    cursor.setPosition(
        first_hint.end,
        QTextCursor.MoveMode.KeepAnchor,
    )
    cursor.insertText("activity")
    QTest.qWait(50)
    assert window.ocr_page._hints_checked is True
    assert any(
        hint.original == "walue" for hint in window.ocr_page._hints
    )
    assert not any(
        hint.original == "activty" for hint in window.ocr_page._hints
    )

    window.ocr_page.fix_btn.click()
    assert "value" in window.ocr_page.get_text()
    assert "walue" not in window.ocr_page.get_text()
    assert window.ocr_page.check_btn.text() == "检查完成，进入评分"

    window._start_recognition(
        {
            "student_name": "手动输入学生",
            "essay_type": "CET-6",
            "max_score": "15",
            "question": "测试题目",
            "image_path": "",
            "excellent_path": "",
            "input_mode": "manual",
        }
    )
    assert window.stack.currentWidget() is window.ocr_page
    assert "直接输入模式" in window.ocr_page.image_label.text()

    window.close()
    db.close()
