"""Each live OCR workflow owns only its own pending SQLite row."""

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest

from tests.test_workflow_sessions import APP, draft, make_window


def setup_picture(tmp_path: Path, level: str) -> str:
    image = QImage(70, 52, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red if level == "CET-4" else Qt.GlobalColor.blue)
    p = tmp_path / f"{level}-own.png"
    assert image.save(str(p))
    return str(p)


def submit_new_ocr(window, tmp_path: Path, level: str, text: str) -> int:
    setup = dict(draft("Synthetic " + level, level + " independent question."),
                 essay_type=level, input_mode="ocr", image_path=setup_picture(tmp_path, level))
    window._start_recognition(setup)
    window.thread_pool.workers[-1].signals.finished.emit(text)
    APP.processEvents()
    assert window.ocr_page.get_text() == text
    return window._current_essay_id


def switch(window, level: str, input_method: str) -> None:
    source, target = (window.exam_combo.option_buttons if level == "CET-6"
                      else tuple(reversed(window.exam_combo.option_buttons)))
    if input_method == "mouse":
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    else:
        source.setFocus()
        QTest.keyClick(source, Qt.Key.Key_Right if level == "CET-6" else Qt.Key.Key_Left)
        assert target.hasFocus()
        QTest.keyClick(target, Qt.Key.Key_Space)
    APP.processEvents()
    assert window.exam_level == level


@pytest.mark.parametrize("usage", [0, 1], ids=["student", "teacher"])
@pytest.mark.parametrize("input_method", ["mouse", "keyboard"])
def test_successful_reocr_after_context_restore_updates_only_target(tmp_path, usage, input_method):
    window, db = make_window(tmp_path)
    try:
        window.resize(800, 600)
        window.show()
        window.config.set("ocr.mode", "local")
        window.ocr_engine = object()
        window.mode_combo.setCurrentIndex(usage)
        window._open_new_setup()
        id4 = submit_new_ocr(window, tmp_path, "CET-4", "Original FOUR.")
        switch(window, "CET-6", input_method)
        id6 = submit_new_ocr(window, tmp_path, "CET-6", "Original SIX.")
        before4, before6 = db.get_essay(id4), db.get_essay(id6)
        assert id4 != id6 and db.count_essays() == 2
        switch(window, "CET-4", input_method)
        switch(window, "CET-6", input_method)
        QTest.mouseClick(window.ocr_page.re_btn, Qt.MouseButton.LeftButton)
        retry = window.thread_pool.workers[-1]
        assert retry.image_path == before6["image_path"]
        retry.signals.finished.emit("Corrected new SIX.")
        APP.processEvents()
        assert window.ocr_page.get_text() == "Corrected new SIX."
        assert db.count_essays() == 2
        assert window._current_essay_id == id6 and db.get_essay(id4) == before4
        assert db.get_essay(id6) == {**before6, "ocr_text": "Corrected new SIX."}
    finally:
        window.close()
        db.close()
        APP.processEvents()


@pytest.mark.parametrize("conflict", ["name", "question", "source", "ocr-text", "score", "missing", "write-error"])
def test_conflicting_ocr_retry_never_inserts_or_overwrites(tmp_path, conflict, monkeypatch):
    import sqlite3

    from database.sqlite import Database

    window, db = make_window(tmp_path)
    other = Database(db.db_path)
    try:
        window.show()
        window.config.set("ocr.mode", "local")
        window.ocr_engine = object()
        window._open_new_setup()
        id4 = submit_new_ocr(window, tmp_path, "CET-4", "Level four source.")
        switch(window, "CET-6", "mouse")
        id6 = submit_new_ocr(window, tmp_path, "CET-6", "Level six source.")
        before4 = db.get_essay(id4)
        switch(window, "CET-4", "mouse")
        if conflict == "missing":
            other.delete_essay(id6)  # Anonymous fixture, never a user record.
        switch(window, "CET-6", "mouse")
        QTest.mouseClick(window.ocr_page.re_btn, Qt.MouseButton.LeftButton)
        retry = window.thread_pool.workers[-1]

        # A different SQLite connection changes the record after the retry started.
        if conflict == "name":
            other.update_essay(id6, student_name="Different synthetic student")
        elif conflict == "question":
            other.update_essay(id6, question="Changed source question")
        elif conflict == "source":
            with other.transaction() as conn:
                conn.execute("UPDATE essays SET usage_mode = ? WHERE id = ?", ("teacher", id6))
        elif conflict == "ocr-text":
            other.update_essay(id6, ocr_text="Another editor already saved this.")
        elif conflict == "score":
            other.update_essay(id6, ai_score="13", score="13", submitted_text="Finished.", report_json='{"score":13}')
        elif conflict == "write-error":
            def blocked(*_args):
                raise sqlite3.OperationalError("Synthetic write failure")
            monkeypatch.setattr(db, "update_owned_ocr_draft", blocked)
        before6 = db.get_essay(id6)
        count = db.count_essays()
        retry.signals.finished.emit("New result available locally.")
        APP.processEvents()
        assert db.count_essays() == count
        assert db.get_essay(id6) == before6 and db.get_essay(id4) == before4
        assert window.ocr_page.get_text() == "New result available locally."
        assert "文本仍保留在当前页面" in window.ocr_page.hint_label.text()
    finally:
        other.close()
        window.close()
        db.close()
        APP.processEvents()


def test_explicit_new_ocr_workflow_never_borrows_an_old_matching_id(tmp_path):
    window, db = make_window(tmp_path)
    try:
        window.show()
        window.config.set("ocr.mode", "local")
        window.ocr_engine = object()
        window._open_new_setup()
        first = submit_new_ocr(window, tmp_path, "CET-4", "The first task.")
        original = db.get_essay(first)
        window._open_new_setup()
        second = submit_new_ocr(window, tmp_path, "CET-4", "The new task, same fixture identity.")
        assert first != second and db.count_essays() == 2
        assert db.get_essay(first) == original
    finally:
        window.close()
        db.close()
        APP.processEvents()


def test_restored_ocr_draft_does_not_claim_an_identical_id_in_another_database(tmp_path):
    from database.sqlite import Database

    window, old = make_window(tmp_path)
    new = Database(tmp_path / "data/replacement.db")
    try:
        window.show()
        window.config.set("ocr.mode", "local")
        window.ocr_engine = object()
        window._open_new_setup()
        prior_id = submit_new_ocr(window, tmp_path, "CET-4", "Matching original body.")
        original = old.get_essay(prior_id)
        switch(window, "CET-6", "mouse")
        matching_id = new.create_essay(
            student_name=original["student_name"], essay_type=original["type"],
            question=original["question"], ocr_text=original["ocr_text"], image_path=original["image_path"],
        )
        with new.transaction() as conn:
            conn.execute("UPDATE essays SET time = ? WHERE id = ?", (original["time"], matching_id))
        match = new.get_essay(matching_id)
        assert matching_id == prior_id and match == original
        new.close()
        window.config.set("paths.database", str(new.db_path))
        assert window._switch_database_from_settings()
        switch(window, "CET-4", "mouse")
        assert window.ocr_page.get_text() == "Matching original body."
        QTest.mouseClick(window.ocr_page.re_btn, Qt.MouseButton.LeftButton)
        window.thread_pool.workers[-1].signals.finished.emit("Must not enter another database.")
        APP.processEvents()
        assert window.db.count_essays() == 1 and window.db.get_essay(matching_id) == match
        assert old.get_essay(prior_id) == original
        assert window.ocr_page.get_text() == "Must not enter another database."
    finally:
        new.close()
        window.close()
        old.close()
        APP.processEvents()


@pytest.mark.parametrize("usage", [0, 1], ids=["student", "teacher"])
def test_finalized_ocr_scope_disables_retry_but_explicit_new_task_can_scan(tmp_path, usage):
    from tests.test_workflow_sessions import finish_current_grading, report

    window, db = make_window(tmp_path)
    try:
        window.resize(800, 600)
        window.show()
        window.config.set("ocr.mode", "local")
        window.ocr_engine = object()
        window.mode_combo.setCurrentIndex(usage)
        window._open_new_setup()
        final_id = submit_new_ocr(window, tmp_path, "CET-4", "Recognized original.")
        window._start_grading("Final submitted text for the synthetic worksheet.")
        assert finish_current_grading(window, report(12)) == final_id
        final = db.get_essay(final_id)
        assert final["ai_score"] and db.count_essays() == 1

        switch(window, "CET-6", "mouse")
        switch(window, "CET-4", "keyboard")
        assert window.stack.currentWidget() is window.ocr_page
        assert window.ocr_page.image_panel.isVisible()  # The original image is still readable.
        selected = window.ocr_page.re_btn
        workers_before = len(window.thread_pool.workers)
        if selected.isVisible() and selected.isEnabled():
            QTest.mouseClick(selected, Qt.MouseButton.LeftButton)
        if len(window.thread_pool.workers) > workers_before:
            window.thread_pool.workers[-1].signals.finished.emit("Misplaced new OCR result.")
        APP.processEvents()
        assert db.count_essays() == 1 and db.get_essay(final_id) == final
        assert not selected.isVisible() and not selected.isEnabled()
        assert window.grab().save(str(tmp_path / "finalized-confirmation.png"))

        window._restart_recognition()
        window._active_ocr_engine = window.ocr_engine  # Prove the low-level guard even with an engine.
        window._run_ocr(final["image_path"])
        APP.processEvents()
        assert len(window.thread_pool.workers) == workers_before
        assert db.get_essay(final_id) == final

        window._return_to_setup()
        setup_page = window.setup_page
        setup_page.restore_draft({"student_name": final["student_name"], "question": final["question"],
                                  "image_path": final["image_path"], "manual": False})
        QTest.mouseClick(setup_page.start_btn, Qt.MouseButton.LeftButton)
        APP.processEvents()
        assert window.stack.currentWidget() is window.ocr_page
        assert window.ocr_page.image_panel.isVisible() and not selected.isVisible()
        assert len(window.thread_pool.workers) == workers_before and db.count_essays() == 1
        assert db.get_essay(final_id) == final

        window._open_new_setup()
        new_id = submit_new_ocr(window, tmp_path, "CET-4", "New explicit task.")
        assert new_id != final_id and db.count_essays() == 2
        assert db.get_essay(new_id)["ocr_text"] == "New explicit task."
        assert db.get_essay(final_id) == final
        assert window.ocr_page.re_btn.isVisible() and window.ocr_page.re_btn.isEnabled()
        (tmp_path / "scored-row-proof.json").write_text(
            '{"same_scored_draft":1,"after_explicit_new":2,"old_row_identical":true}\n',
            encoding="utf-8",
        )
    finally:
        window.close()
        db.close()
        APP.processEvents()
