import json
import pytest
from PyQt6.QtWidgets import QInputDialog, QMessageBox
from PyQt6.QtTest import QTest
from tests.test_workflow_sessions import make_window, draft, finish_current_grading, APP
from tests.test_cet_contract import valid_report
from database.sqlite import Database
from memory.manager import rules_for_grading
from config_manager import ConfigManager
from cet_scoring import RUBRIC_VERSIONS
from security import SERVICE_NAME, _default_user_key_dir
from gui.styles import get_app_style

def grade(window, level="CET-4", score=11):
    d=draft("Learner", "Discuss lifelong learning. Write at least 120 words.");d["essay_type"]=level
    window._start_recognition(d)
    window._start_grading("I enjoys reading. It helps me learn.")
    return finish_current_grading(window, valid_report(score))

def test_student_autosave_teacher_review_preserves_source(tmp_path):
    w,db=make_window(tmp_path)
    i=grade(w)
    original=db.get_essay(i)
    assert original["usage_mode"]=="student" and original["review_status"]=="pending"
    assert original["submitted_text"]=="I enjoys reading. It helps me learn."
    assert json.loads(original["raw_ai_report"])["score"]==11
    assert w.score_page.review_frame.isHidden()
    assert db.get_score_trend()[0]["numeric_score"]==11
    assert db.get_score_trend(usage_mode="teacher")==[]
    w.mode_combo.setCurrentIndex(1)
    w._open_history()
    w.history_page.report_requested.emit(i)
    assert w.stack.currentWidget() is w.score_page
    assert not w.score_page.review_frame.isHidden()
    w._confirm_teacher_score({"teacher_score":"12", "teacher_comment":"More precise", "teacher_reason":"Task fulfilled", "reviewer":"Teacher"})
    record=db.get_essay(i)
    assert record["usage_mode"]=="student" and record["review_status"]=="confirmed"
    assert record["report_json"]==original["report_json"] and record["raw_ai_report"]==original["raw_ai_report"]
    assert db.get_score_trend()[0]["numeric_score"]==11
    assert db.get_score_trend(usage_mode="teacher")[0]["numeric_score"]==12
    w.close()

def test_student_feedback_never_promotes(tmp_path, monkeypatch):
    w,db=make_window(tmp_path);i=grade(w)
    monkeypatch.setattr(QInputDialog,"getText",lambda *a,**k:("12",True))
    monkeypatch.setattr(QInputDialog,"getMultiLineText",lambda *a,**k:("Examples need more attention",True))
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k:pytest.fail("Student should not see promotion dialog"))
    w._collect_score_dispute()
    assert db.get_essay(i)["feedback"] and db.list_feedback_rules()==[]
    with pytest.raises(ValueError):w._approve_feedback_rule(i,"feedback","Teacher")
    w.mode_combo.setCurrentIndex(1)
    w._confirm_teacher_score({"teacher_score":"11","teacher_comment":w._current_report["overall_comment"],"reviewer":"Teacher","use_long_term":True})
    assert len(db.list_feedback_rules(exam_level="CET-4"))==1
    assert db.list_feedback_rules(exam_level="CET-6")==[]
    w.close()

def test_exam_isolation_examples_groups_rules_trends(tmp_path):
    w,db=make_window(tmp_path)
    for level,score in (("CET-4",9),("CET-6",13)):
        i=grade(w,level,score)
        assert db.get_essay(i)["rubric_version"]==RUBRIC_VERSIONS[level]
        db.add_excellent_example(level,level+" example")
        db.add_feedback_rule(level+" rule",exam_level=level,reviewer="teacher")
    for level,score in (("CET-4",9),("CET-6",13)):
        assert db.count_essays(exam_level=level)==1
        assert db.list_excellent_examples(level)[0]["text"]==level+" example"
        assert rules_for_grading(db,w.memory,level)==[{"content":level+" rule"}]
        assert db.get_score_trend(exam_level=level)[0]["numeric_score"]==score
        groups=db.list_essay_groups(exam_level=level)
        assert groups[0]["group_key"].startswith(level+":")
        assert db.count_essays(question_group=groups[0]["group_key"])==1
    assert len(db.list_essay_groups())==2
    w.close()

@pytest.mark.parametrize("change", ["mode","level","task"])
def test_switch_discards_all_async_generations(tmp_path,change):
    w,db=make_window(tmp_path)
    w._start_recognition(draft("A","Question"));w._start_grading("old text")
    token=w._active_jobs["grading"];pending=w._pending_grading
    ocr=w._new_job("ocr");reference=w._new_job("reference")
    if change=="mode":w.mode_combo.setCurrentIndex(1)
    elif change=="level":w.exam_combo.setCurrentText("CET-6")
    else:w._open_new_setup()
    w._on_grade_finished(token,pending,valid_report())
    w._on_ocr_finished(ocr,draft("A","Question"),"stale")
    assert not w._is_current_job("reference",reference)
    assert db.get_essay(pending["essay_id"])["ai_score"]==""
    assert w._current_report=={} and w.ocr_page.get_text()!="stale"
    w.close()

def test_task_draft_retained_per_exam(tmp_path):
    w,db=make_window(tmp_path)
    w._start_recognition(draft("A","Original question"));w.ocr_page.set_text("Original text")
    w.exam_combo.setCurrentText("CET-6")
    assert w.ocr_page.get_text()==""
    w.exam_combo.setCurrentText("CET-4")
    assert w.ocr_page.get_text()=="Original text" and w._draft["question"]=="Original question"
    w.close()

def test_reference_selection_isolated_in_setup_drafts(tmp_path):
    w,db=make_window(tmp_path)
    w._open_new_setup()
    w.setup_page._excellent_path = "CET4-reference.txt"
    w.setup_page.minimum_words.setValue(160)
    w.exam_combo.setCurrentText("CET-6")
    assert w.setup_page._excellent_path == "" and w.setup_page.minimum_words.value() == 0
    w.setup_page._excellent_path = "CET6-reference.txt"
    w.exam_combo.setCurrentText("CET-4")
    assert w.setup_page._excellent_path == "CET4-reference.txt" and w.setup_page.minimum_words.value() == 160
    w._open_new_setup()
    assert w.setup_page._excellent_path == ""
    w.close()

def test_keyboard_navigation_is_immediate(tmp_path):
    from PyQt6.QtCore import Qt
    w,db=make_window(tmp_path);w.show();APP.processEvents()
    QTest.keyClick(w,Qt.Key.Key_H,Qt.KeyboardModifier.ControlModifier)
    assert w.stack.currentWidget() is w.history_page
    QTest.keyClick(w,Qt.Key.Key_2,Qt.KeyboardModifier.ControlModifier)
    assert w.stack.currentWidget() is w.setup_page
    w.close()

def test_new_config_and_credentials_namespace(tmp_path):
    from pathlib import Path
    config=ConfigManager(tmp_path,resource_root=Path(__file__).parents[1])
    assert config.get("app.usage_mode")=="student"
    assert config.get("app.exam_level")=="CET-4" and config.get("app.theme")=="light"
    assert config.resolve_path("paths.database")==tmp_path/'data/cet_writing.db'
    assert SERVICE_NAME=="CETWritingStudio" and _default_user_key_dir().name==SERVICE_NAME
    assert all(v.startswith("cet_") for v in config.PROVIDER_SECRET_NAMES.values())
    assert not config.user_path.exists()
    assert config._secrets.config_dir == tmp_path/'config/CETWritingStudio'

@pytest.mark.parametrize("theme", ["light","dark"])
@pytest.mark.parametrize("size", [(960,640),(1280,820),(1600,1000)])
def test_pages_layout_and_keyboard_focus(tmp_path,theme,size):
    w,db=make_window(tmp_path)
    APP.setStyleSheet(get_app_style(theme));w.resize(*size);w.show();APP.processEvents()
    i=grade(w)
    for page in (0,1,2,3,4,5):
        w._navigate(page);APP.processEvents()
        assert (w.width(),w.height())==size
        assert w.centralWidget().width()<=w.width()
        assert w.stack.currentWidget().width()>500
    w.mode_combo.setFocus();QTest.keyClick(w.mode_combo, __import__('PyQt6.QtCore',fromlist=['Qt']).Qt.Key.Key_Tab)
    assert APP.focusWidget() is not None
    w.close()
