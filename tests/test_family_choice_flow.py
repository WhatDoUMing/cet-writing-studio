"""Integration boundaries for family art, selection and durable success events."""
from pathlib import Path

import pytest
from PyQt6.QtCore import QAbstractAnimation, Qt
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtTest import QTest

from gui.choice_controls import FixedChoice, SearchChoice
from gui.history_page import HistoryPage
from gui.theme_art import ThemeArt
from tests.test_cet_contract import valid_report
from tests.test_workflow_sessions import APP, draft, make_window
from gui.styles import get_app_style


def test_grading_persistence_triggers_once_and_never_on_replay(tmp_path, monkeypatch):
    w, db = make_window(tmp_path)
    effects = []
    monkeypatch.setattr(w, "_confirm_success", effects.append)
    try:
        w._start_recognition(draft("Sample", "Write about your city."))
        w._start_grading("A short example with a clear sentence.")
        tok, pending = w._active_jobs["grading"], w._pending_grading
        w._on_grade_finished(tok, pending, valid_report())
        assert effects == ["评分已保存"]
        w._on_grade_finished(tok, pending, valid_report())
        w._open_history()
        w._open_record_report(pending["essay_id"])
        assert effects == ["评分已保存"]
        w.mode_combo.setCurrentIndex(1)
        w._confirm_teacher_score({"teacher_score": "9", "reviewer": ""})
        assert effects == ["评分已保存"]
        w._confirm_teacher_score({"teacher_score": "13", "reviewer": "Sample",
                                  "teacher_reason": "Checked", "teacher_comment": "Checked"})
        assert effects == ["评分已保存", "复核已保存"]
    finally:
        w.close()


@pytest.mark.parametrize("failure", ["invalid", "storage", "stale"])
def test_failed_grading_never_celebrates(tmp_path, monkeypatch, failure):
    w, _ = make_window(tmp_path)
    effects = []
    monkeypatch.setattr(w, "_confirm_success", effects.append)
    try:
        w._start_recognition(draft("Sample", "Write about food."))
        w._start_grading("A paragraph submitted for the test.")
        tok, pending = w._active_jobs["grading"], w._pending_grading
        if failure == "storage":
            def fail(*args):
                raise OSError("synthetic persistence failure")
            monkeypatch.setattr(w, "_commit_grading_result", fail)
        if failure == "stale":
            w._open_settings()
        w._on_grade_finished(tok, pending, {} if failure == "invalid" else valid_report())
        assert effects == []
    finally:
        w.close()


def test_settings_success_not_failure_triggers(tmp_path, monkeypatch):
    w, _ = make_window(tmp_path)
    effects = []
    monkeypatch.setattr(w, "_confirm_success", effects.append)
    try:
        monkeypatch.setattr(w, "_switch_database_from_settings", lambda: False)
        w._on_settings_saved()
        assert effects == []
        monkeypatch.setattr(w, "_switch_database_from_settings", lambda: True)
        w._on_settings_saved()
        assert effects == ["设置已保存"]
    finally:
        w.close()


def test_static_and_reduced_companion_never_animates(tmp_path):
    image=QImage(32,32,QImage.Format.Format_ARGB32)
    image.fill(QColor("gold"))
    assert image.save(str(tmp_path/"naiwa.png"))
    art=ThemeArt(48, directory=tmp_path)
    assert art.show_role("naiwa")
    art.show(); APP.processEvents()
    assert art._animation is None
    assert not art.play_feedback(reduced=True) and art._animation is None
    assert art.play_feedback(reduced=False)
    assert art._animation.state() == QAbstractAnimation.State.Running
    art.close(); APP.processEvents()
    assert art._animation.state() == QAbstractAnimation.State.Stopped


def test_history_long_group_search_and_explicit_confirmation():
    page=HistoryPage()
    groups=[{"group_key": f"CET-4:exam {i}", "exam_level":"CET-4", "question":f"Question {i}",
             "question_summary":f"作文主题{i}", "record_count":2} for i in range(108)]
    for level in ("CET-4", "CET-6"):
        groups.append({"group_key":level+":same question", "exam_level":level, "question":"Same question",
                       "question_summary":"相同题名", "record_count":3})
    page.load_history_page([], [], total_count=0, groups=groups)
    page.resize(670, 510);page.show();QTest.qWait(20)
    choice=page.group_combo
    try:
        assert isinstance(choice,SearchChoice) and choice.count()==111 and choice.currentData() is None
        choice.showPopup();choice.search_edit.setText("相同题名")
        assert choice.results.count()==2
        assert "CET-4" in choice.results.item(0).text() and "CET-6" in choice.results.item(1).text()
        QTest.keyClick(choice.search_edit,Qt.Key.Key_Down)
        QTest.keyClick(choice.search_edit,Qt.Key.Key_Escape)
        assert not choice.isPopupVisible() and page.current_query()[1] is None
        choice.showPopup();choice.search_edit.setText("CET-6  /  相同题名")
        assert choice.results.count()==1
        QTest.keyClick(choice.search_edit,Qt.Key.Key_Return)
        assert page.current_query()[1]=="CET-6:same question"
        page.load_history_page([], [], total_count=0,groups=groups)
        assert choice.currentData()=="CET-6:same question"
        choice.setCurrentIndex(choice.findData(None));assert choice.currentData() is None
        page.load_history_page([], [],total_count=0,groups=[])
        assert choice.count()==1 and choice.currentData() is None
    finally:
        page.close()


@pytest.mark.parametrize("refresh", ["same_order", "reordered", "removed"])
def test_open_history_search_keeps_preview_identity_during_refresh(refresh):
    page = HistoryPage()
    rows = [
        {"group_key": level + ":same", "exam_level": level, "question": "Same",
         "question_summary": "同名题目", "record_count": 1}
        for level in ("CET-4", "CET-6")
    ]
    events = []
    page.query_changed.connect(lambda text, key: events.append((text, key)))
    page.load_history_page([], [], total_count=0, groups=rows)
    page.show()
    control = page.group_combo
    try:
        control.showPopup()
        control.search_edit.setText("同名题目")
        QTest.keyClick(control.search_edit, Qt.Key.Key_Down)
        def preview_key():
            item = control.results.currentItem()
            return control.itemData(item.data(Qt.ItemDataRole.UserRole)) if item else None
        assert preview_key() == "CET-6:same"
        preview_removed = refresh == "removed"
        refreshed = {"same_order": rows, "reordered": rows[::-1], "removed": rows[:1]}[refresh]
        for _ in range(2):
            page.load_history_page([], [], total_count=0, groups=refreshed)
            assert control.isPopupVisible() and control.search_edit.text() == "同名题目"
            assert page.current_query()[1] is None and not events
            assert preview_key() == (None if preview_removed else "CET-6:same")
        QTest.keyClick(control.search_edit, Qt.Key.Key_Return)
        if preview_removed:
            assert page.current_query()[1] is None and not events
        else:
            assert page.current_query()[1] == "CET-6:same"
            assert events == [("", "CET-6:same")]
    finally:
        page.close()


@pytest.mark.parametrize("theme",["light","dark"])
def test_800_layout_without_usable_assets(tmp_path, monkeypatch,theme):
    bad=tmp_path/"broken";bad.mkdir()
    (bad/"naiwa.png").write_bytes(b"invalid png")
    monkeypatch.setenv("CET_COMPANIONS_DIR",str(bad))
    w,_=make_window(tmp_path);APP.setStyleSheet(get_app_style(theme))
    try:
        w.resize(800,600);w.show();QTest.qWait(60)
        assert w.width()==800 and w.height()==600
        assert w.home_page.scroll.horizontalScrollBar().maximum()==0
        assert not any(a.isVisible() for a in w.findChildren(ThemeArt))
        assert isinstance(w.mode_combo,FixedChoice)
        w._open_history();QTest.qWait(30)
        for group in w.history_page.filter_groups:
            assert group.isVisible()
            for btn in group.option_buttons:
                assert btn.isVisible() and btn.width()>=btn.fontMetrics().horizontalAdvance(btn.text())+4
        assert w.history_page.group_combo.isVisible()
    finally:
        w.close()
