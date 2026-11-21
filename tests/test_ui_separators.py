"""Application-authored UI separators do not edit the data shown by those views."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QLabel, QTableWidget

from gui.home_page import RecordLink
from gui.main_window import MainWindow
from gui.styles import get_app_style, prepare_fonts
from tests.test_workflow_sessions import APP, draft, finish_current_grading, make_window, report


DOT = "\N{MIDDLE DOT}"
APP_TITLE = "CET Writing Studio 四六级作文批改"


def test_legacy_builtin_window_title_is_display_only(tmp_path: Path) -> None:
    window, db = make_window(tmp_path)
    try:
        shipped = json.loads(
            (Path(__file__).resolve().parents[1] / "config/default_settings.json").read_text(encoding="utf-8")
        )
        assert shipped["app"]["name"] == APP_TITLE
        for saved, expected in (
            (f"CET Writing Studio {DOT} 四六级作文批改", APP_TITLE),
            (f"我的学校{DOT}英语", f"我的学校{DOT}英语"),
        ):
            window.config.set("app.name", saved)
            with_title = MainWindow(window.config, db, window.memory, window.ocr_engine)
            try:
                assert with_title.windowTitle() == expected
                assert window.config.get("app.name") == saved
            finally:
                with_title.close()
    finally:
        window.close()
        db.close()


@pytest.mark.parametrize("mode", ["student", "teacher"])
def test_visible_labels_remove_only_app_owned_separators(tmp_path: Path, mode: str) -> None:
    root = Path(__file__).resolve().parents[1]
    prepare_fonts(APP, private_dir=root / "work/preview/fonts")
    window, db = make_window(tmp_path)
    window.setStyleSheet(get_app_style("light" if mode == "student" else "dark"))
    try:
        window.resize(800, 600)
        window.show()
        APP.setActiveWindow(window)
        window.mode_combo.setCurrentIndex(0 if mode == "student" else 1)
        name = f"学生甲{DOT}乙"
        topic = f"校园{DOT}观察"
        essay = f"Original{DOT} text from a student."
        assert db.count_essays() == 0
        window._start_recognition(draft(name, topic))
        window.ocr_page.set_text(essay)
        APP.processEvents()
        assert window.ocr_page.get_text() == essay
        assert window.ocr_page.length_label.text().startswith("本地词数 ")
        assert DOT not in window.ocr_page.length_label.text()
        assert "03 文本确认" in {
            label.text() for label in window.ocr_page.findChildren(QLabel) if label.isVisible()
        }
        assert window.grab().save(str(tmp_path / "01-ocr.png"))

        window._start_grading(essay)
        essay_id = finish_current_grading(window, report(12))
        APP.processEvents()
        assert window.score_page.title.text() == ("04 学生练习报告" if mode == "student" else "04 教师复核报告")
        assert window.score_page.status.text() == (
            "练习报告已自动保存。AI 练习分用于学生趋势" if mode == "student" else
            "AI 建议与教师最终分分别保存，原始报告保留"
        )
        assert DOT not in window.score_page.source_label.text()
        assert DOT not in next(
            label.text() for label in window.score_page.findChildren(QLabel)
            if label.property("subtitle") and " 词 CET-4" in label.text()
        )
        assert window.score_page.original_edit.toPlainText() == essay
        assert window.grab().save(str(tmp_path / "02-report.png"))

        record = db.get_essay(essay_id)
        assert (record["student_name"], record["question"], record["ocr_text"]) == (name, topic, essay)
        window._open_history()
        search = window.history_page.search_edit
        assert search.placeholderText() == "搜索学生姓名或题目，也可搜摘要"
        search.setText(topic)
        APP.processEvents()
        table = next(table for table in window.history_page.findChildren(QTableWidget) if table.isVisible())
        assert table.item(0, 1).text() == name
        assert table.item(0, 2).text().endswith(topic)
        if mode == "teacher":
            window.history_page._update_trend([{"numeric_score": 11}, {"numeric_score": 12}])
        assert "共 " in window.history_page.trend_label.text()
        assert DOT not in window.history_page.trend_label.text()
        assert window.grab().save(str(tmp_path / "03-history-user-middle-dot.png"))

        window._switch_page(0)
        window.home_page.load_recent([record])
        APP.processEvents()
        link = next(link for link in window.home_page.findChildren(RecordLink) if link.isVisible())
        assert link.toolTip().splitlines()[0] == topic
        assert DOT not in link.details
        assert "CET-4 默认至少 120 词" in {
            label.text() for label in window.home_page.findChildren(QLabel) if label.isVisible()
        }
        assert window.grab().save(str(tmp_path / "04-home.png"))

        window._open_settings()
        settings = window.settings_page
        public = SimpleNamespace(source="public_catalog", models=("offline-mock-model",))
        settings._populate_models("scoring", "", catalog=public)
        APP.processEvents()
        assert settings.models_status.text().startswith("已获取 1 个模型。官方公开目录")
        assert DOT not in settings.models_status.text()
        assert DOT not in settings._catalog_message(
            "ocr", SimpleNamespace(source="provider_api", models=("offline-mock-vision",))
        )
        assert "CET Writing Studio 设置" in {
            label.text() for label in settings.findChildren(QLabel) if label.isVisible()
        }
        assert window.grab().save(str(tmp_path / "05-settings.png"))
    finally:
        window.close()
        db.close()
        APP.processEvents()
