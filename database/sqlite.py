"""SQLite persistence layer for essays, examples, and feedback rules."""

from __future__ import annotations

import sqlite3
import math
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from logger_config import get_logger
from grading_review import REVIEW_CONFIRMED, REVIEW_PENDING


log = get_logger("database.sqlite")

# Compatibility contract: ``score`` remains the effective score for older
# integrations. Pending records mirror the AI suggestion; confirmed records
# mirror the teacher score. New UI and trend code use the explicit audit fields.


def utc_now_iso() -> str:
    """Return a timezone-aware ISO timestamp for database records."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    """Small repository around a single SQLite database file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            journal = "WAL"
            self._conn.execute(f"PRAGMA journal_mode = {journal}")
            self._initialize_schema()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _initialize_schema(self) -> None:
        conn = self.connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                create_time TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS essays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                student_name TEXT,
                type TEXT NOT NULL,
                question TEXT NOT NULL DEFAULT '',
                question_summary TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                ocr_text TEXT NOT NULL DEFAULT '',
                score TEXT NOT NULL DEFAULT '',
                ai_score TEXT NOT NULL DEFAULT '',
                teacher_score TEXT NOT NULL DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'pending',
                teacher_comment TEXT NOT NULL DEFAULT '',
                teacher_reason TEXT NOT NULL DEFAULT '',
                reviewer TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL DEFAULT '',
                ai_provider TEXT NOT NULL DEFAULT '',
                ai_model TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                rubric_version TEXT NOT NULL DEFAULT '',
                max_score TEXT NOT NULL DEFAULT '',
                report_json TEXT NOT NULL DEFAULT '{}',
                feedback TEXT NOT NULL DEFAULT '',
                time TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_essays_student_time
                ON essays(student_id, time DESC);

            CREATE TABLE IF NOT EXISTS excellent_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                text TEXT NOT NULL,
                analysis TEXT NOT NULL DEFAULT '',
                score TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                time TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                source_essay_id INTEGER,
                reviewer TEXT NOT NULL DEFAULT '',
                time TEXT NOT NULL
            );
            """
        )
        self._migrate_essay_columns(conn)

    def _migrate_essay_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(essays)").fetchall()
        }
        if "student_name" not in columns:
            conn.execute("ALTER TABLE essays ADD COLUMN student_name TEXT")
            conn.execute(
                """
                UPDATE essays
                SET student_name = (
                    SELECT name FROM students
                    WHERE students.id = essays.student_id
                )
                WHERE student_name IS NULL
                """
            )
        if "question_summary" not in columns:
            conn.execute(
                "ALTER TABLE essays "
                "ADD COLUMN question_summary TEXT NOT NULL DEFAULT ''"
            )
        trace_columns = {
            "ai_score": "TEXT NOT NULL DEFAULT ''",
            "teacher_score": "TEXT NOT NULL DEFAULT ''",
            "review_status": "TEXT NOT NULL DEFAULT 'pending'",
            "teacher_comment": "TEXT NOT NULL DEFAULT ''",
            "teacher_reason": "TEXT NOT NULL DEFAULT ''",
            "reviewer": "TEXT NOT NULL DEFAULT ''",
            "reviewed_at": "TEXT NOT NULL DEFAULT ''",
            "ai_provider": "TEXT NOT NULL DEFAULT ''",
            "ai_model": "TEXT NOT NULL DEFAULT ''",
            "prompt_version": "TEXT NOT NULL DEFAULT ''",
            "rubric_version": "TEXT NOT NULL DEFAULT ''",
            "max_score": "TEXT NOT NULL DEFAULT ''",
            "usage_mode": "TEXT NOT NULL DEFAULT 'student'",
            "submitted_text": "TEXT NOT NULL DEFAULT ''",
            "raw_ai_report": "TEXT NOT NULL DEFAULT '{}'",
            "minimum_words": "INTEGER",

        }
        for name, definition in trace_columns.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE essays ADD COLUMN {name} {definition}"
                )
        conn.execute(
            """
            UPDATE essays
            SET ai_score = score
            WHERE TRIM(ai_score) = '' AND TRIM(score) <> ''
            """
        )
        conn.execute(
            """
            UPDATE essays
            SET review_status = ?
            WHERE review_status NOT IN (?, ?)
               OR TRIM(review_status) = ''
            """,
            (REVIEW_PENDING, REVIEW_PENDING, REVIEW_CONFIRMED),
        )
        conn.execute(
            """
            UPDATE essays
            SET max_score = CASE type
                WHEN 'CET-4' THEN '15'
                WHEN 'CET-6' THEN '15'
                ELSE ''
            END
            WHERE TRIM(max_score) = ''
            """
        )
        feedback_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(feedback_rules)"
            ).fetchall()
        }
        if "enabled" not in feedback_columns:
            conn.execute(
                "ALTER TABLE feedback_rules "
                "ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
            )
        if "source_essay_id" not in feedback_columns:
            conn.execute(
                "ALTER TABLE feedback_rules ADD COLUMN source_essay_id INTEGER"
            )
        if "reviewer" not in feedback_columns:
            conn.execute(
                "ALTER TABLE feedback_rules "
                "ADD COLUMN reviewer TEXT NOT NULL DEFAULT ''"
            )
        if "exam_level" not in feedback_columns:
            conn.execute("ALTER TABLE feedback_rules ADD COLUMN exam_level TEXT NOT NULL DEFAULT 'CET-4'")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_essays_question
            ON essays(question)
            """
        )
        conn.commit()

    def get_or_create_student(self, name: str | None) -> int:
        """Return the id of an existing student or create one."""
        name = (name or "").strip() or "默认学生"
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM students WHERE name = ?", (name,)
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cursor = conn.execute(
                "INSERT INTO students(name, create_time) VALUES (?, ?)",
                (name, utc_now_iso()),
            )
            return int(cursor.lastrowid)

    def create_essay(
        self,
        student_name: str | None,
        essay_type: str,
        question: str,
        question_summary: str = "",
        image_path: str = "",
        ocr_text: str = "",
        score: str = "",
        report_json: str = "{}",
        feedback: str = "",
        ai_score: str = "",
        teacher_score: str = "",
        review_status: str = REVIEW_PENDING,
        teacher_comment: str = "",
        teacher_reason: str = "",
        reviewer: str = "",
        reviewed_at: str = "",
        ai_provider: str = "",
        ai_model: str = "",
        prompt_version: str = "",
        rubric_version: str = "",
        max_score: str = "15",
        usage_mode: str = "student",
        submitted_text: str = "",
        raw_ai_report: str = "{}",
        minimum_words: int | None = None,
    ) -> int:
        from cet_scoring import validate_level
        validate_level(essay_type)
        if usage_mode not in {"student", "teacher"}:
            raise ValueError("usage_mode 须为 student 或 teacher")
        display_name = (student_name or "").strip() or None
        student_id = self.get_or_create_student(display_name)
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO essays(
                    student_id, student_name, type, question,
                    question_summary, image_path, ocr_text, score,
                    ai_score, teacher_score, review_status,
                    teacher_comment, teacher_reason, reviewer, reviewed_at,
                    ai_provider, ai_model, prompt_version, rubric_version,
                    max_score, report_json, feedback, time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id,
                    display_name,
                    essay_type,
                    question,
                    question_summary,
                    image_path,
                    ocr_text,
                    score,
                    ai_score,
                    teacher_score,
                    review_status,
                    teacher_comment,
                    teacher_reason,
                    reviewer,
                    reviewed_at,
                    ai_provider,
                    ai_model,
                    prompt_version,
                    rubric_version,
                    max_score,
                    report_json,
                    feedback,
                    utc_now_iso(),
                ),
            )
            essay_id = int(cursor.lastrowid)
        self.update_essay(essay_id, submitted_text=submitted_text, raw_ai_report=raw_ai_report, minimum_words=minimum_words)
        with self.transaction() as conn:
            conn.execute("UPDATE essays SET usage_mode = ? WHERE id = ?", (usage_mode, essay_id))
        log.info("Created essay id=%s type=%s", essay_id, essay_type)
        return essay_id

    def update_essay(
        self,
        essay_id: int,
        *,
        student_name: str | None = None,
        essay_type: str | None = None,
        question: str | None = None,
        question_summary: str | None = None,
        image_path: str | None = None,
        ocr_text: str | None = None,
        score: str | None = None,
        report_json: str | None = None,
        feedback: str | None = None,
        ai_score: str | None = None,
        teacher_score: str | None = None,
        review_status: str | None = None,
        teacher_comment: str | None = None,
        teacher_reason: str | None = None,
        reviewer: str | None = None,
        reviewed_at: str | None = None,
        ai_provider: str | None = None,
        ai_model: str | None = None,
        prompt_version: str | None = None,
        rubric_version: str | None = None,
        max_score: str | None = None,
        submitted_text: str | None = None,
        raw_ai_report: str | None = None,
        minimum_words: int | None = None,
    ) -> None:
        fields: dict[str, Any] = {}
        for key, value in (("submitted_text", submitted_text), ("raw_ai_report", raw_ai_report), ("minimum_words", minimum_words)):
            if value is not None:
                fields[key] = value
        if student_name is not None:
            display_name = student_name.strip() or None
            fields["student_name"] = display_name
            fields["student_id"] = self.get_or_create_student(display_name)
        if essay_type is not None:
            fields["type"] = essay_type
        if question is not None:
            fields["question"] = question
        if question_summary is not None:
            fields["question_summary"] = question_summary
        if image_path is not None:
            fields["image_path"] = image_path
        if ocr_text is not None:
            fields["ocr_text"] = ocr_text
        if score is not None:
            fields["score"] = score
        if report_json is not None:
            fields["report_json"] = report_json
        if feedback is not None:
            fields["feedback"] = feedback
        if ai_score is not None:
            fields["ai_score"] = ai_score
        if teacher_score is not None:
            fields["teacher_score"] = teacher_score
        if review_status is not None:
            fields["review_status"] = review_status
        if teacher_comment is not None:
            fields["teacher_comment"] = teacher_comment
        if teacher_reason is not None:
            fields["teacher_reason"] = teacher_reason
        if reviewer is not None:
            fields["reviewer"] = reviewer
        if reviewed_at is not None:
            fields["reviewed_at"] = reviewed_at
        if ai_provider is not None:
            fields["ai_provider"] = ai_provider
        if ai_model is not None:
            fields["ai_model"] = ai_model
        if prompt_version is not None:
            fields["prompt_version"] = prompt_version
        if rubric_version is not None:
            fields["rubric_version"] = rubric_version
        if max_score is not None:
            fields["max_score"] = max_score
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE essays SET {assignments} WHERE id = ?",
                (*fields.values(), essay_id),
            )

    def delete_essay(self, essay_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM essays WHERE id = ?", (essay_id,))

    def confirm_essay_review(
        self,
        essay_id: int,
        *,
        teacher_score: str,
        teacher_comment: str,
        teacher_reason: str,
        reviewer: str,
    ) -> None:
        """Atomically mark an AI suggestion as a teacher-confirmed grade."""
        from grading_review import validate_teacher_score
        teacher_score = validate_teacher_score(teacher_score, 15)
        if not reviewer.strip():
            raise ValueError("请填写审核教师")
        reviewed_at = utc_now_iso()
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE essays
                SET teacher_score = ?, teacher_comment = ?,
                    teacher_reason = ?, reviewer = ?, reviewed_at = ?,
                    review_status = ?, score = ?
                WHERE id = ?
                """,
                (
                    teacher_score,
                    teacher_comment,
                    teacher_reason,
                    reviewer,
                    reviewed_at,
                    REVIEW_CONFIRMED,
                    teacher_score,
                    essay_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("作文记录不存在")

    def find_question_summary(self, question: str, exam_level: str = "CET-4") -> str | None:
        normalized = question.strip()
        if not normalized:
            return None
        row = self.connect().execute(
            """
            SELECT question_summary FROM essays
            WHERE TRIM(question) = ? COLLATE NOCASE
              AND type = ? AND TRIM(question_summary) <> ''
            ORDER BY time DESC
            LIMIT 1
            """,
            (normalized, exam_level),
        ).fetchone()
        if row is None:
            return None
        summary = str(row["question_summary"]).strip()
        return summary or None

    def update_question_summary(self, question: str, summary: str, exam_level: str = "CET-4") -> None:
        normalized = question.strip()
        if not normalized or not summary.strip():
            return
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE essays
                SET question_summary = ?
                WHERE TRIM(question) = ? COLLATE NOCASE AND type = ?
                """,
                (summary.strip(), normalized, exam_level),
            )

    def get_essay(self, essay_id: int) -> dict[str, Any] | None:
        row = self.connect().execute(
            """
            SELECT e.*
            FROM essays e
            WHERE e.id = ?
            """,
            (essay_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def list_essays(
        self,
        limit: int | None = 100,
        offset: int = 0,
        *,
        search: str = "",
        question_group: str | None = None,
        exam_level: str | None = None,
        usage_mode: str | None = None,
        review_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a stable page of history records with database-side filters."""
        where, params = self._history_filters(search, question_group, exam_level, usage_mode, review_status)
        sql = (
            "SELECT e.* FROM essays e "
            f"{where} ORDER BY e.time DESC, e.id DESC"
        )
        if limit is not None:
            if limit < 0 or offset < 0:
                raise ValueError("limit and offset must be non-negative")
            sql += " LIMIT ? OFFSET ?"
            params.extend((limit, offset))
        rows = self.connect().execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def count_essays(
        self,
        *,
        search: str = "",
        question_group: str | None = None,
        exam_level: str | None = None,
        usage_mode: str | None = None,
        review_status: str | None = None,
    ) -> int:
        """Count all history rows matching the same filters as list_essays."""
        where, params = self._history_filters(search, question_group, exam_level, usage_mode, review_status)
        row = self.connect().execute(
            f"SELECT COUNT(*) AS count FROM essays e {where}", params
        ).fetchone()
        return int(row["count"])

    def list_essay_groups(self, *, search: str = "", exam_level: str | None = None, usage_mode: str | None = None, review_status: str | None = None) -> list[dict[str, Any]]:
        """Return complete question-group metadata for a history search."""
        where, params = self._history_filters(search, None, exam_level, usage_mode, review_status)
        rows = self.connect().execute(
            f"""
            SELECT e.type || ':' || LOWER(TRIM(e.question)) AS group_key, MAX(e.type) AS exam_level,
                   MAX(e.question) AS question,
                   MAX(NULLIF(TRIM(e.question_summary), '')) AS question_summary,
                   COUNT(*) AS record_count,
                   MAX(e.time) AS latest_time
            FROM essays e
            {where}
            GROUP BY e.type, LOWER(TRIM(e.question))
            ORDER BY latest_time DESC, group_key ASC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _history_filters(
        search: str,
        question_group: str | None,
        exam_level: str | None = None,
        usage_mode: str | None = None,
        review_status: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("type", exam_level), ("usage_mode", usage_mode), ("review_status", review_status)):
            if value is not None:
                clauses.append(f"e.{column} = ?")
                params.append(value)
        normalized_search = search.strip()
        if normalized_search:
            escaped = (
                normalized_search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            clauses.append(
                "(COALESCE(e.student_name, '') LIKE ? ESCAPE '\\' "
                "COLLATE NOCASE OR e.question LIKE ? ESCAPE '\\' "
                "COLLATE NOCASE OR e.question_summary LIKE ? ESCAPE '\\' "
                "COLLATE NOCASE)"
            )
            params.extend((pattern, pattern, pattern))
        if question_group is not None:
            clauses.append("e.type || ':' || LOWER(TRIM(e.question)) = ?")
            params.append(question_group.strip())
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def get_score_trend(self, student_name: str | None = None, *, exam_level: str = "CET-4", usage_mode: str = "student") -> list[dict[str, Any]]:
        where, params = self._history_filters("", None, exam_level, "student" if usage_mode == "student" else None,
                                              REVIEW_CONFIRMED if usage_mode == "teacher" else None)
        if student_name:
            where += " AND e.student_name = ?"
            params.append(student_name)
        rows = self.connect().execute(f"SELECT e.* FROM essays e {where} ORDER BY e.time, e.id", params).fetchall()
        trend = []
        for row in rows:
            item = dict(row)
            numeric = self._coerce_score(item["ai_score"] if usage_mode == "student" else item["teacher_score"], 15)
            if numeric is not None and numeric.is_integer():
                item["numeric_score"] = int(numeric)
                trend.append(item)
        return trend

    def add_excellent_example(
        self,
        essay_type: str,
        text: str,
        analysis: str = "",
        score: str = "",
        source: str = "",
    ) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO excellent_examples(
                    type, text, analysis, score, source, time
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (essay_type, text, analysis, score, source, utc_now_iso()),
            )
            return int(cursor.lastrowid)

    def list_excellent_examples(
        self, essay_type: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if essay_type:
            rows = self.connect().execute(
                """
                SELECT * FROM excellent_examples
                WHERE type = ?
                ORDER BY time DESC
                LIMIT ?
                """,
                (essay_type, limit),
            ).fetchall()
        else:
            rows = self.connect().execute(
                """
                SELECT * FROM excellent_examples
                ORDER BY time DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_feedback_rule(
        self,
        content: str,
        *,
        source_essay_id: int | None = None,
        reviewer: str = "",
        exam_level: str = "CET-4",
    ) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feedback_rules(
                    content, enabled, source_essay_id, reviewer, time, exam_level
                ) VALUES (?, 1, ?, ?, ?, ?)
                """,
                (content, source_essay_id, reviewer, utc_now_iso(), exam_level),
            )
            return int(cursor.lastrowid)

    def list_feedback_rules(
        self,
        limit: int = 200,
        *,
        enabled_only: bool = False,
        exam_level: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["enabled = 1"] if enabled_only else []
        params = []
        if exam_level is not None:
            clauses.append("exam_level = ?")
            params.append(exam_level)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = self.connect().execute(
            f"""
            SELECT * FROM feedback_rules
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def set_feedback_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE feedback_rules SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, rule_id),
            )

    def delete_feedback_rule(self, rule_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM feedback_rules WHERE id = ?", (rule_id,))

    @staticmethod
    def _coerce_score(
        value: str,
        maximum: float | None = None,
    ) -> float | None:
        if not value:
            return None
        try:
            number = float(value)
            if not math.isfinite(number) or number < 0:
                return None
            if maximum is not None and number > maximum:
                return None
            return number
        except ValueError:
            return None
