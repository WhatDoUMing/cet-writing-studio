"""Behavior for the six real workflow slots; source art remains private and optional."""

from hashlib import sha256
import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QAbstractAnimation, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog

from gui import motion, workflow_art
from gui.history_page import HistoryPage
from gui.home_page import HomePage
from gui.ocr_page import OCRPage
from gui.score_page import ScorePage
from gui.setup_page import SetupPage
from gui.workflow_art import REVIEW_FEEDBACK_MS, ROLE_ASSET_IDS, WorkflowArt
from tests.test_cet_contract import valid_report
from tests.test_workflow_sessions import APP, draft, finish_current_grading, make_window


@pytest.fixture
def art_directory(tmp_path, monkeypatch):
    directory = tmp_path / "verified-art"
    directory.mkdir()
    assets = {}
    for index, asset_id in enumerate(ROLE_ASSET_IDS.values()):
        name = f"role-{index}.png"
        pixels = QImage(40 + index, 32, QImage.Format.Format_RGB32)
        pixels.fill(QColor(120 + index * 10, 80, 25))
        assert pixels.save(str(directory / name))
        assets[asset_id] = {"file": name, "sha256": sha256((directory / name).read_bytes()).hexdigest()}
    manifest = directory / "ui-meme-assets.json"
    manifest.write_text(json.dumps({"version": 1, "assets": assets}), encoding="utf-8")
    monkeypatch.setattr(workflow_art, "ui_meme_directory", lambda: directory)
    yield directory, manifest, assets
    motion.set_reduce_motion(False)


@pytest.mark.parametrize("tamper", ["missing", "changed", "outside", "video"])
def test_art_fails_closed_without_a_valid_local_still(art_directory, tamper):
    directory, manifest, assets = art_directory
    item = assets[ROLE_ASSET_IDS["guide"]]
    original = (directory / item["file"]).read_bytes()
    if tamper == "missing":
        manifest.unlink()
    if tamper == "changed":
        item["sha256"] = "0" * 64
    if tamper == "outside":
        (directory.parent / "elsewhere.png").write_bytes(original)
        item["file"] = "../elsewhere.png"
    if tamper == "video":
        (directory / "looks-local.mp4").write_bytes(original)
        item["file"] = "looks-local.mp4"
    if manifest.exists():
        manifest.write_text(json.dumps({"version": 1, "assets": assets}), encoding="utf-8")
    slot = WorkflowArt("guide", 52, 44)
    assert not slot.set_active(True)
    assert slot.isHidden()


def test_upload_peek_only_on_unfilled_image_input(art_directory, monkeypatch, tmp_path):
    page = SetupPage()
    page.show()
    assert not page.upload_empty_art.active
    page.ocr_mode_radio.click()
    assert page.upload_empty_art.active
    assert page.upload_empty_art.asset_id == "dot-naiwa-1118"
    assert page.upload_empty_art.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert page.upload_empty_art.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("", ""))
    page.pick_image_btn.click()
    assert page.upload_empty_art.active
    path = tmp_path / "sample.png"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    page.pick_image_btn.click()
    assert not page.upload_empty_art.active
    assert page.capture_draft()["image_path"] == str(path)
    page.restore_draft({"manual": False})
    assert page.upload_empty_art.active
    page.manual_mode_radio.click()
    assert not page.upload_empty_art.active
    page.close()


def test_egg_means_unfiltered_empty_history_not_empty_search(art_directory):
    page = HistoryPage()
    page.show()
    page.load_history_page([], [], total_count=0, groups=[])
    assert page.empty_history_art.active and page.empty_history_label.text() == "还没有评分记录"
    assert page.history_stamp.isHidden()
    page.search_edit.setText("No match")
    assert not page.empty_history_art.active
    assert page.empty_history_label.text() == "没有符合条件的历史记录"
    page.search_edit.clear()
    assert page.empty_history_art.active
    page.review_combo.setCurrentIndex(1)
    assert not page.empty_history_art.active
    page.review_combo.setCurrentIndex(0)
    page.load_history([{
        "id": 1, "type": "CET-4", "question": "A synthetic question", "student_name": "",
        "usage_mode": "student", "review_status": "pending", "ai_score": "12",
    }], [])
    assert not page.empty_history_art.active and page.empty_state.isHidden()
    page.close()


def test_thinking_is_static_and_only_inside_existing_guide(art_directory):
    home = HomePage()
    page = OCRPage()
    page.show()
    page.clear_image()
    assert not home.findChildren(WorkflowArt)
    assert page.guide_art.asset_id == "ghn-naiwa-wallpaper-6a040e71f9b2"
    assert page.guide_art.isVisible()
    assert not page.guide_art.play_review_once(reduced=False)
    assert "确认原文进入评分" in page.subtitle.text()
    page.set_text("A synthetic essay.")
    assert page.get_text() == "A synthetic essay."
    assert page.skip_btn.isEnabled()
    page.close()


def test_thumbs_up_requires_successful_persistence_and_never_replays(art_directory, tmp_path, monkeypatch):
    window, db = make_window(tmp_path)
    window.show()
    page = window.score_page
    try:
        window.mode_combo.setCurrentIndex(1)
        window._start_recognition(draft("Synthetic", "Write about reading."))
        window._start_grading("A short synthetic paragraph written for test.")
        assert page.review_reading_art.isVisible()
        essay = finish_current_grading(window, valid_report())
        assert page.review_reading_art.isVisible() and not page.review_completed_art.active
        review = {"teacher_score": "13", "teacher_comment": "Checked", "teacher_reason": "Checked", "reviewer": "Test"}
        write = db.confirm_essay_review

        def fail(*_args, **_kwargs):
            raise OSError("synthetic failure")

        monkeypatch.setattr(db, "confirm_essay_review", fail)
        window._confirm_teacher_score(review)
        assert page.review_reading_art.isVisible() and not page.review_completed_art.active
        assert db.get_essay(essay)["review_status"] != "confirmed"

        monkeypatch.setattr(db, "confirm_essay_review", write)
        window._confirm_teacher_score(review)
        assert db.get_essay(essay)["review_status"] == "confirmed"
        assert page.review_completed_art.isVisible() and not page.review_reading_art.active
        animation = page.review_completed_art._animation
        assert animation.loopCount() == 1 and animation.duration() == REVIEW_FEEDBACK_MS
        assert animation.state() == QAbstractAnimation.State.Running
        QTest.qWait(REVIEW_FEEDBACK_MS + 75)
        assert animation.state() == QAbstractAnimation.State.Stopped and page.review_completed_art._angle == 0
        window._open_record_report(essay)
        assert not page.review_completed_art.active and not page.review_reading_art.active
        assert "已由" in page.review_status.text()
    finally:
        window.close()


def test_reduced_motion_is_static_even_on_confirmed_review(art_directory):
    page = ScorePage()
    page.usage_mode = "teacher"
    page.show()
    page.show_report(valid_report())
    motion.set_reduce_motion(True)
    page.mark_confirmed({"reviewer": "Test", "teacher_score": "12"}, celebrate=True)
    assert page.review_completed_art.active and page.review_completed_art._animation is None
    page.close()


def test_export_only_commits_chosen_utf8_and_then_shows_dog(art_directory, tmp_path, monkeypatch):
    page = ScorePage()
    page.show()
    page.show_report(valid_report())
    assert not page.export_corrected_btn.isEnabled()
    body = "A corrected rehearsal.\n中文标注\n"
    page.set_corrected_essay(body, 1, [])
    assert page.export_corrected_btn.isEnabled()
    target = tmp_path / "export.txt"
    assert not target.exists()
    assert not page.export_success_art.active
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    page.export_corrected_btn.click()
    assert target.read_bytes() == body.encode("utf-8")
    assert page.export_success_art.isVisible() and page.export_success_art.asset_id == "dot-naiwa-1166"
    assert page.export_success_art._animation is None
    assert "已保存" in page.correction_status.text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    page.export_corrected_btn.click()
    assert target.read_bytes() == body.encode("utf-8")
    assert not page.export_success_art.active and "取消" in page.correction_status.text()
    page.close()


@pytest.mark.parametrize("case", ["unwritable", "not-a-text-file", "unc", "stale-report"])
def test_export_cannot_claim_saved_when_nothing_commits(art_directory, tmp_path, monkeypatch, case):
    page = ScorePage()
    page.show()
    page.show_report(valid_report())
    page.set_corrected_essay("Synthetic.", 1, [])
    path = {
        "unwritable": tmp_path / "no-such-parent" / "out.txt",
        "not-a-text-file": tmp_path / "out.csv",
        "unc": r"\\not-used\example\never-open.txt",
        "stale-report": tmp_path / "stale.txt",
    }[case]

    def select(*_args):
        if case == "stale-report":
            page.show_report(valid_report())
        return str(path), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", select)
    page.export_corrected_btn.click()
    assert not page.export_success_art.active and "已保存" not in page.correction_status.text()
    if isinstance(path, Path):
        assert not path.exists()
    page.close()



@pytest.mark.parametrize("result", ["saved", "reduce", "validation", "persistence", "stale"])
def test_student_thumbs_up_only_after_new_saved_grade(art_directory, tmp_path, monkeypatch, result):
    window, db = make_window(tmp_path)
    window.show()
    try:
        motion.set_reduce_motion(result == "reduce")
        window._start_recognition(draft("Synthetic", "Write about planning."))
        window._start_grading("A synthetic essay from a temporary test database.")
        page = window.score_page
        assert page.review_reading_art.active
        assert not page.practice_completed_art.active and not page.review_completed_art.active
        token = window._active_jobs["grading"]
        pending = window._pending_grading
        essay_id = int(pending["essay_id"])
        if result == "persistence":
            def failed_write(*_args):
                raise OSError("intentional synthetic write failure")
            monkeypatch.setattr(window, "_commit_grading_result", failed_write)
        if result == "stale":
            window._open_new_setup()
        window._on_grade_finished(token, pending, {} if result == "validation" else valid_report())
        teacher_art, art = page.review_completed_art, page.practice_completed_art
        assert not teacher_art.active
        if result in {"saved", "reduce"}:
            assert db.get_essay(essay_id)["ai_score"]
            assert art.isVisible() and art.active and art.asset_id == "dot-naiwa-1005"
            if result == "reduce":
                assert art._animation is None
            else:
                assert art._animation.loopCount() == 1
                QTest.qWait(REVIEW_FEEDBACK_MS + 65)
                assert art._animation.state() == QAbstractAnimation.State.Stopped
            window._on_grade_finished(token, pending, valid_report())  # Duplicate token cannot replay the badge.
            assert art._animation is None or art._animation.state() == QAbstractAnimation.State.Stopped
            window._open_record_report(essay_id)
            assert not art.active
        else:
            assert not art.active and art._animation is None
            assert not db.get_essay(essay_id)["ai_score"]
    finally:
        window.close()
        db.close()
        APP.processEvents()


def test_saved_student_badge_cannot_stay_active_on_teacher_report(art_directory, tmp_path):
    window, db = make_window(tmp_path)
    window.show()
    try:
        window._start_recognition(draft("Synthetic", "A test prompt."))
        window._start_grading("A synthetic original essay for role switching.")
        essay_id = finish_current_grading(window, valid_report())
        assert db.get_essay(essay_id)["review_status"] == "pending"
        page = window.score_page
        art = page.practice_completed_art
        assert art.active and art._animation.state() == QAbstractAnimation.State.Running

        student, teacher = window.mode_combo.option_buttons
        QTest.mouseClick(teacher, Qt.MouseButton.LeftButton)
        assert window.stack.currentWidget() is page
        assert page.title.text() == "04 教师复核报告"
        assert not art.active and art._animation.state() == QAbstractAnimation.State.Stopped
        assert page.review_reading_art.active and not page.review_completed_art.active
        QTest.mouseClick(student, Qt.MouseButton.LeftButton)
        assert page.title.text() == "04 学生练习报告"
        assert not art.active and not page.review_reading_art.active
        QTest.qWait(REVIEW_FEEDBACK_MS + 35)
        assert not art.active and art._animation.state() == QAbstractAnimation.State.Stopped
    finally:
        window.close()
        db.close()
        APP.processEvents()
