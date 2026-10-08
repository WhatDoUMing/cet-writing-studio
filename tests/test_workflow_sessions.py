import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

from config_manager import ConfigManager
from database.sqlite import Database
from gui.main_window import MainWindow
from gui.history_page import HistoryPage
from gui.styles import get_app_style
from memory.manager import MemoryManager
from ocr.trocr_engine import TrOCREngine


APP = QApplication.instance() or QApplication([])


class CapturingPool:
    def __init__(self) -> None:
        self.workers = []

    def start(self, worker) -> None:
        self.workers.append(worker)


def make_window(tmp_path: Path) -> tuple[MainWindow, Database]:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default_settings.json").write_text(
        '{"app":{"name":"Test","theme":"light"},'
        '"paths":{"database":"data/test.db","models":"models",'
        '"logs":"logs","memory":"memory/rules.md"},'
        '"ocr":{"mode":"manual","model_name":"test-model"}}',
        encoding="utf-8",
    )
    config = ConfigManager(tmp_path)
    config.get_api_key = lambda provider=None: "test-key"
    db = Database(tmp_path / "data" / "test.db")
    db.connect()
    window = MainWindow(
        config,
        db,
        MemoryManager(tmp_path / "memory" / "rules.md"),
        TrOCREngine(config.get("ocr", {})),
    )
    window.thread_pool = CapturingPool()
    return window, db


def draft(student: str, question: str) -> dict:
    return {
        "student_name": student,
        "essay_type": "CET-4",
        "max_score": "15",
        "question": question,
        "image_path": "",
        "excellent_path": "",
        "input_mode": "manual",
    }


def report(score, content="", language="", struct=""):
    from tests.test_cet_contract import valid_report
    try:
        score=int(score)
    except (ValueError,TypeError):
        pass
    result = valid_report(score)
    result["overall_comment"] = "ok"
    return result


def finish_current_grading(window: MainWindow, result: dict) -> int:
    token = window._active_jobs["grading"]
    pending = window._pending_grading
    essay_id = int(pending["essay_id"])
    window._on_grade_finished(token, pending, result)
    return essay_id


def test_consecutive_essays_create_independent_records(tmp_path: Path) -> None:
    window, db = make_window(tmp_path)

    window._start_recognition(draft("学生甲", "题目甲"))
    window._start_grading("First essay text.")
    first_id = finish_current_grading(window, report("12", "8", "7", "5"))

    window._open_new_setup()
    assert window._current_essay_id is None
    assert window._current_report == {}
    assert not window.score_page.dispute_btn.isEnabled()
    assert not window.score_page.apply_corrections_btn.isEnabled()
    window._start_recognition(draft("学生乙", "题目乙"))
    assert window._current_essay_id is None
    assert window._current_report == {}
    assert window._current_graded_text == ""
    assert window._pending_grading == {}
    assert not window.score_page.dispute_btn.isEnabled()
    assert not window.score_page.apply_corrections_btn.isEnabled()
    window._start_grading("Second essay text.")
    second_id = finish_current_grading(window, report("11", "7", "6", "5"))

    assert first_id != second_id
    first = db.get_essay(first_id)
    second = db.get_essay(second_id)
    assert first is not None and second is not None
    assert (first["student_name"], first["question"], first["ocr_text"], first["score"]) == (
        "学生甲",
        "题目甲",
        "First essay text.",
        "12",
    )
    assert (second["student_name"], second["question"], second["ocr_text"], second["score"]) == (
        "学生乙",
        "题目乙",
        "Second essay text.",
        "11",
    )
    window.close()


def test_stale_grading_result_is_discarded(tmp_path: Path) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("旧学生", "旧题目"))
    window._start_grading("Old essay.")
    old_token = window._active_jobs["grading"]
    old_pending = window._pending_grading
    old_id = int(old_pending["essay_id"])

    window._start_recognition(draft("新学生", "新题目"))
    window._start_grading("New essay.")
    new_token = window._active_jobs["grading"]
    new_pending = window._pending_grading
    new_id = int(new_pending["essay_id"])

    window._on_grade_finished(
        old_token,
        old_pending,
        report("14", "10", "9", "5"),
    )
    assert db.get_essay(old_id)["score"] == ""
    assert db.get_essay(new_id)["score"] == ""
    assert window._current_report == {}

    window._on_grade_finished(
        new_token,
        new_pending,
        report("10", "7", "6", "4"),
    )
    assert db.get_essay(old_id)["score"] == ""
    assert db.get_essay(new_id)["score"] == "10"
    window.close()


def test_stale_ocr_result_and_post_close_callback_are_discarded(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    old_draft = draft("旧学生", "旧题目")
    window._start_recognition(old_draft)
    old_ocr_token = window._new_job("ocr")

    window._start_recognition(draft("新学生", "新题目"))
    window._on_ocr_finished(old_ocr_token, old_draft, "stale text")
    assert window.ocr_page.get_text() == ""
    assert db.count_essays() == 0

    window._start_grading("Current text.")
    grading_token = window._active_jobs["grading"]
    pending = window._pending_grading
    essay_id = int(pending["essay_id"])
    window.close()
    window._on_grade_finished(
        grading_token,
        pending,
        report("12", "8", "7", "5"),
    )

    reopened = Database(db.db_path)
    assert reopened.get_essay(essay_id)["score"] == ""
    reopened.close()


def test_revision_reuses_record_and_duplicate_submit_is_ignored(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "原题"))
    window._start_grading("Original text.")
    essay_id = int(window._pending_grading["essay_id"])
    worker_count = len(window.thread_pool.workers)
    window._start_grading("Duplicate text.")
    assert len(window.thread_pool.workers) == worker_count
    assert db.count_essays() == 1

    window._return_to_ocr()
    window._return_to_setup()
    window._start_recognition(draft("学生", "修改后的题目"))
    window._start_grading("Revised text.")
    assert int(window._pending_grading["essay_id"]) == essay_id
    assert db.count_essays() == 1
    window.close()


def test_changed_question_cancelled_grading_preserves_original_record(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    original_draft = draft("学生", "原题目")
    window._start_recognition(original_draft)
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="原题摘要",
        feedback="原评分异议",
    )
    before = db.get_essay(essay_id)

    window._return_to_ocr()
    window._return_to_setup()
    window._start_recognition(draft("学生", "修改后的题目"))
    window._start_grading("Original text.")
    assert db.get_essay(essay_id) == before
    window._return_to_ocr()

    assert db.get_essay(essay_id) == before
    assert window.ocr_page.get_text() == "Original text."
    assert db.count_essays() == 1
    window.close()


def test_changed_text_regrade_clears_feedback_and_reuses_id(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(essay_id, feedback="原评分异议")

    window._return_to_ocr()
    window._start_grading("Revised text.")
    staged = db.get_essay(essay_id)
    assert staged["ocr_text"] == "Original text."
    assert staged["feedback"] == "原评分异议"
    assert staged["score"] == "12"
    finish_current_grading(window, report("11", "7", "6", "5"))

    revised = db.get_essay(essay_id)
    assert revised["ocr_text"] == "Revised text."
    assert revised["feedback"] == ""
    assert revised["score"] == "11"
    assert db.count_essays() == 1
    window.close()


def test_unmodified_return_to_view_preserves_summary_and_feedback(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    original_draft = draft("学生", "题目")
    window._start_recognition(original_draft)
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="有效摘要",
        feedback="有效评分异议",
    )

    window._return_to_ocr()
    window._return_to_setup()
    window._start_recognition(original_draft)

    unchanged = db.get_essay(essay_id)
    assert unchanged["question_summary"] == "有效摘要"
    assert unchanged["feedback"] == "有效评分异议"
    assert unchanged["score"] == "12"
    assert unchanged["ocr_text"] == "Original text."
    window.close()


def test_failed_reocr_preserves_completed_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    window, db = make_window(tmp_path)
    original_draft = draft("学生", "题目")
    window._start_recognition(original_draft)
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="有效摘要",
        feedback="有效评分异议",
    )
    before = db.get_essay(essay_id)

    image_path = tmp_path / "replacement.png"
    Image.new("RGB", (12, 12), "white").save(image_path)
    revised_draft = dict(original_draft)
    revised_draft.update(
        input_mode="ocr",
        image_path=str(image_path),
    )
    window._return_to_ocr()
    window._return_to_setup()
    window.config.set("ocr.mode", "local")
    window.ocr_engine = object()
    window._start_recognition(revised_draft)
    token = window._active_jobs["ocr"]
    window._on_worker_error("ocr", token, "recognition failed")

    assert db.get_essay(essay_id) == before
    assert db.count_essays() == 1
    window.close()


def test_failed_revision_grade_restores_completed_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="有效摘要",
        feedback="有效评分异议",
    )
    before = db.get_essay(essay_id)

    window._return_to_ocr()
    window._start_grading("Revised text.")
    assert db.get_essay(essay_id) == before
    token = window._active_jobs["grading"]
    window._on_worker_error("grading", token, "provider failed")

    assert db.get_essay(essay_id) == before
    assert db.count_essays() == 1
    window.close()


def test_successful_reocr_without_grading_does_not_change_history(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    original_draft = draft("学生", "原题目")
    window._start_recognition(original_draft)
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="原题摘要",
        feedback="原评分异议",
    )
    before = db.get_essay(essay_id)

    image_path = tmp_path / "replacement.png"
    Image.new("RGB", (12, 12), "white").save(image_path)
    revised_draft = dict(original_draft)
    revised_draft.update(
        question="修改后的题目",
        input_mode="ocr",
        image_path=str(image_path),
    )
    window._return_to_ocr()
    window._return_to_setup()
    window.config.set("ocr.mode", "local")
    window.ocr_engine = object()
    window._start_recognition(revised_draft)
    token = window._active_jobs["ocr"]
    window._on_ocr_finished(token, revised_draft, "New OCR text.")

    assert window.ocr_page.get_text() == "New OCR text."
    assert db.get_essay(essay_id) == before
    window._open_history()
    assert db.get_essay(essay_id) == before
    assert db.count_essays() == 1
    window.close()


@pytest.mark.parametrize(
    "cancel_path",
    ["score_back", "home", "history", "settings", "new_task"],
)
def test_all_navigation_cancellation_paths_preserve_completed_revision(
    tmp_path: Path,
    cancel_path: str,
) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "原题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="原题摘要",
        feedback="原评分异议",
    )
    before = db.get_essay(essay_id)

    window._return_to_ocr()
    window._return_to_setup()
    window._start_recognition(draft("学生", "修改后的题目"))
    window._start_grading("Revised text.")
    assert db.get_essay(essay_id) == before

    actions = {
        "score_back": window._return_to_ocr,
        "home": lambda: window._navigate_from_sidebar(0),
        "history": window._open_history,
        "settings": window._open_settings,
        "new_task": window._open_new_setup,
    }
    actions[cancel_path]()

    assert db.get_essay(essay_id) == before
    assert db.count_essays() == 1
    window.close()


def test_window_close_during_revision_preserves_completed_record(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "原题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="原题摘要",
        feedback="原评分异议",
    )
    before = db.get_essay(essay_id)
    db_path = db.db_path

    window._return_to_ocr()
    window._start_grading("Revised text.")
    window.close()

    reopened = Database(db_path)
    assert reopened.get_essay(essay_id) == before
    assert reopened.count_essays() == 1
    reopened.close()


def test_invalid_revision_report_preserves_completed_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="有效摘要",
        feedback="有效评分异议",
    )
    before = db.get_essay(essay_id)

    window._return_to_ocr()
    window._start_grading("Revised text.")
    token = window._active_jobs["grading"]
    pending = window._pending_grading
    window._on_grade_finished(
        token,
        pending,
        report("30", "10", "10", "10"),
    )

    assert db.get_essay(essay_id) == before
    assert window._current_report == {}
    assert window.score_page.report == {}
    assert window.ocr_page.get_text() == "Revised text."
    assert db.count_essays() == 1
    window.close()


def test_consecutive_successful_revisions_commit_atomically_to_same_id(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "原题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(essay_id, feedback="原评分异议")

    window._return_to_ocr()
    window._start_grading("First revision.")
    assert finish_current_grading(
        window,
        report("12", "8", "6", "5"),
    ) == essay_id
    first_revision = db.get_essay(essay_id)
    assert first_revision["ocr_text"] == "First revision."
    assert first_revision["score"] == "12"
    assert first_revision["feedback"] == ""

    window._return_to_ocr()
    window._return_to_setup()
    window._start_recognition(draft("学生", "第二次修订题目"))
    window._start_grading("Second revision.")
    token = window._active_jobs["grading"]
    pending = window._pending_grading
    window._on_question_summary_finished(token, pending, "第二次题目摘要")
    assert finish_current_grading(
        window,
        report("11", "7", "6", "5"),
    ) == essay_id

    second_revision = db.get_essay(essay_id)
    assert second_revision["question"] == "第二次修订题目"
    assert second_revision["question_summary"] == "第二次题目摘要"
    assert second_revision["ocr_text"] == "Second revision."
    assert second_revision["score"] == "11"
    assert second_revision["feedback"] == ""
    assert db.count_essays() == 1
    window.close()


def test_ai_result_is_pending_and_traceable_until_teacher_confirms(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    window.mode_combo.setCurrentIndex(1)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Essay text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )

    pending = db.get_essay(essay_id)
    assert pending is not None
    assert pending["ai_score"] == "12"
    assert pending["teacher_score"] == ""
    assert pending["review_status"] == "pending"
    assert pending["ai_provider"] == "glm"
    assert pending["ai_model"] == "glm-5.3-flash"
    assert pending["prompt_version"] == "cet-json-v1"
    assert pending["rubric_version"] == "cet-4-holistic-2026-v1"
    assert pending["max_score"] == "15"
    assert db.get_score_trend("学生", usage_mode="teacher") == []
    assert window.history_page._display_score(pending) == "待教师确认"
    assert window.score_page.title.text() == "04 · 教师复核报告"
    assert "AI 分数仅为批改建议" in window.score_page.review_status.text()

    report_json = pending["report_json"]
    window._confirm_teacher_score(
        {
            "teacher_score": "12",
            "teacher_comment": "教师最终评语",
            "teacher_reason": "综合语言准确性后调整",
            "reviewer": "陈老师",
            "accept_ai": False,
        }
    )
    confirmed = db.get_essay(essay_id)
    assert confirmed is not None
    assert confirmed["ai_score"] == "12"
    assert confirmed["teacher_score"] == "12"
    assert confirmed["score"] == "12"
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["teacher_comment"] == "教师最终评语"
    assert confirmed["teacher_reason"] == "综合语言准确性后调整"
    assert confirmed["reviewer"] == "陈老师"
    assert confirmed["reviewed_at"]
    assert confirmed["report_json"] == report_json
    assert db.get_score_trend("学生", usage_mode="teacher")[0]["numeric_score"] == 12
    assert window.history_page._display_score(confirmed) == "12"
    window.close()


def test_teacher_modification_requires_reason_and_accepting_ai_does_not(
    tmp_path: Path,
    monkeypatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: messages.append(message),
    )
    window, db = make_window(tmp_path)
    window.mode_combo.setCurrentIndex(1)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Essay text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )

    window._confirm_teacher_score(
        {
            "teacher_score": "12",
            "teacher_comment": "changed",
            "teacher_reason": "",
            "reviewer": "陈老师",
        }
    )
    assert db.get_essay(essay_id)["review_status"] == "pending"
    assert "修改原因" in messages[-1]

    window._confirm_teacher_score(
        {
            "teacher_score": "12",
            "teacher_comment": "ok",
            "teacher_reason": "",
            "reviewer": "陈老师",
            "accept_ai": True,
        }
    )
    confirmed = db.get_essay(essay_id)
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["teacher_score"] == "12"
    window.close()


def test_score_dispute_requires_explicit_long_term_rule_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, db = make_window(tmp_path)
    window.mode_combo.setCurrentIndex(1)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Essay text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("13", True),
    )
    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("语言维度需要复核", True),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    window._collect_score_dispute()
    assert db.get_essay(essay_id)["feedback"]
    assert db.list_feedback_rules() == []
    assert window.memory.read_rules() == []

    window._confirm_teacher_score({"teacher_score": "12", "teacher_comment": "ok", "reviewer": "王老师"})

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window._collect_score_dispute()
    assert len(db.list_feedback_rules()) == 1
    assert len(MemoryManager(window.memory.path.with_name("CET-4-rules.md")).read_rules()) == 1
    window.close()


def test_history_question_edit_clears_score_summary_and_feedback(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "原题目"))
    window._start_grading("Original text.")
    essay_id = finish_current_grading(
        window,
        report("12", "8", "7", "5"),
    )
    db.update_essay(
        essay_id,
        question_summary="原题摘要",
        feedback="原评分异议",
    )

    window._update_history_record(
        essay_id,
        {
            "student_name": "学生",
            "essay_type": "CET-4",
            "question": "新题目",
        },
    )

    edited = db.get_essay(essay_id)
    assert edited["question"] == "新题目"
    assert edited["question_summary"] == ""
    assert edited["score"] == ""
    assert edited["report_json"] == "{}"
    assert edited["feedback"] == ""
    window.close()


def test_grading_failure_keeps_new_session_report_empty(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生甲", "题目甲"))
    window._start_grading("First.")
    finish_current_grading(window, report("12", "8", "7", "5"))

    window._start_recognition(draft("学生乙", "题目乙"))
    window._start_grading("Second.")
    token = window._active_jobs["grading"]
    essay_id = int(window._pending_grading["essay_id"])
    window._on_worker_error("grading", token, "provider error")

    assert window._current_report == {}
    assert window.score_page.report == {}
    assert not window.score_page.dispute_btn.isEnabled()
    assert db.get_essay(essay_id)["score"] == ""
    window.close()


def test_invalid_report_is_not_displayed_or_stored(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    window, db = make_window(tmp_path)
    window._start_recognition(draft("学生", "题目"))
    window._start_grading("Essay.")
    token = window._active_jobs["grading"]
    pending = window._pending_grading
    essay_id = int(pending["essay_id"])

    window._on_grade_finished(
        token,
        pending,
        report("30", "10", "10", "10"),
    )

    assert window._current_report == {}
    assert window.score_page.report == {}
    assert db.get_essay(essay_id)["score"] == ""
    window.close()


def test_history_page_loads_more_than_one_hundred_records(
    tmp_path: Path,
) -> None:
    window, db = make_window(tmp_path)
    ids = {
        db.create_essay(f"学生{i:03d}", "CET-4", f"题目{i % 4}")
        for i in range(155)
    }

    window._open_history()
    assert len(window.history_page.records) == 100
    assert window.history_page.total_count == 155
    assert window.history_page.group_combo.count() == 5
    assert not window.history_page.load_more_btn.isHidden()
    window.history_page.load_more_btn.click()

    loaded_ids = {int(record["id"]) for record in window.history_page.records}
    assert loaded_ids == ids
    assert len(window.history_page.records) == 155
    assert window.history_page.load_more_btn.isHidden()

    window.history_page.search_edit.setText("学生000")
    assert window.history_page.total_count == 1
    assert [
        record["student_name"] for record in window.history_page.records
    ] == ["学生000"]
    window.close()


def test_runtime_settings_switch_database_model_and_theme(
    tmp_path: Path,
) -> None:
    window, old_db = make_window(tmp_path)
    new_path = tmp_path / "data" / "new.db"
    window.config.set("paths.database", str(new_path))
    window.config.set("ocr.local_model_path", "models/new-local")
    window.config.set("ocr.model_name", "models/new-local")
    window.config.set("app.theme", "dark")

    window._apply_runtime_settings()

    assert window.db.db_path == new_path
    assert window.ocr_engine.local_model_path == str(
        tmp_path / "models" / "new-local"
    )
    assert QApplication.instance().styleSheet() == get_app_style("dark")
    assert old_db._conn is None
    window.close()
