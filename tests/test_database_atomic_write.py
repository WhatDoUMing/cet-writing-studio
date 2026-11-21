"""Regression tests for atomic essay persistence and audit defaults."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from database.sqlite import Database


def test_create_essay_inserts_complete_audit_fields(tmp_path: Path) -> None:
    with closing(Database(tmp_path / "cet.db")) as db:
        db.connect().execute(
            """
            CREATE TRIGGER require_audit_fields BEFORE INSERT ON essays
            WHEN NEW.usage_mode != 'teacher'
                OR NEW.submitted_text != 'Original submission.'
                OR NEW.raw_ai_report != '{"score": 12}'
                OR NEW.minimum_words IS NOT 150
            BEGIN
                SELECT RAISE(ABORT, 'incomplete audit fields');
            END
            """
        )
        essay_id = db.create_essay(
            "   ",
            "CET-6",
            "Topic",
            score="12",
            ai_score="12",
            usage_mode="teacher",
            submitted_text="Original submission.",
            raw_ai_report='{"score": 12}',
            minimum_words=150,
        )
        essay = db.get_essay(essay_id)
        assert essay is not None
        assert essay["student_id"] == db.get_or_create_student(None)
        assert essay["student_name"] is None
        assert essay["usage_mode"] == "teacher"
        assert essay["submitted_text"] == "Original submission."
        assert essay["raw_ai_report"] == '{"score": 12}'
        assert essay["minimum_words"] == 150


def test_create_essay_rolls_back_new_student_when_insert_fails(tmp_path: Path) -> None:
    path = tmp_path / "cet.db"
    with closing(Database(path)) as db:
        db.connect().execute(
            """
            CREATE TRIGGER reject_essay BEFORE INSERT ON essays
            WHEN NEW.question = 'Rejected'
            BEGIN
                SELECT RAISE(ABORT, 'rejected essay');
            END
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="rejected essay"):
            db.create_essay("New student", "CET-4", "Rejected")

        with closing(sqlite3.connect(path)) as observer:
            assert observer.execute("SELECT name FROM students").fetchall() == []
            assert observer.execute("SELECT id FROM essays").fetchall() == []

        assert db.create_essay("New student", "CET-4", "Accepted") > 0


def test_update_essay_preserves_omitted_metadata_and_clears_explicit_values(
    tmp_path: Path,
) -> None:
    with closing(Database(tmp_path / "cet.db")) as db:
        essay_id = db.create_essay(
            "Original student",
            "CET-4",
            "Topic",
            question_summary="Previous summary",
            usage_mode="teacher",
            submitted_text="Original submission.",
            raw_ai_report='{"score": 12}',
            minimum_words=160,
        )

        db.update_essay(essay_id, student_name="  Renamed student  ", question_summary="")
        essay = db.get_essay(essay_id)
        assert essay is not None
        assert essay["student_name"] == "Renamed student"
        assert essay["student_id"] == db.get_or_create_student("Renamed student")
        assert essay["question_summary"] == ""
        assert essay["minimum_words"] == 160

        db.update_essay(essay_id, minimum_words=None)
        essay = db.get_essay(essay_id)
        assert essay is not None
        assert essay["minimum_words"] is None
        assert essay["usage_mode"] == "teacher"
        assert essay["submitted_text"] == "Original submission."
        assert essay["raw_ai_report"] == '{"score": 12}'


def test_update_essay_rolls_back_new_student_when_write_fails(tmp_path: Path) -> None:
    path = tmp_path / "cet.db"
    with closing(Database(path)) as db:
        essay_id = db.create_essay("Original student", "CET-4", "Topic")
        db.connect().execute(
            """
            CREATE TRIGGER reject_rename BEFORE UPDATE ON essays
            WHEN NEW.student_name = 'Rejected name'
            BEGIN
                SELECT RAISE(ABORT, 'rejected rename');
            END
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="rejected rename"):
            db.update_essay(essay_id, student_name="Rejected name")

        essay = db.get_essay(essay_id)
        assert essay is not None
        assert essay["student_name"] == "Original student"
        with closing(sqlite3.connect(path)) as observer:
            assert observer.execute("SELECT name FROM students").fetchall() == [
                ("Original student",),
            ]
