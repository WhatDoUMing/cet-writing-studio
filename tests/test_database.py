import sqlite3
from pathlib import Path

from database.sqlite import Database


def test_database_round_trip(tmp_path: Path) -> None:
    db = Database(tmp_path / "essay.db")
    sid = db.get_or_create_student("张三")
    assert db.get_or_create_student("张三") == sid

    eid = db.create_essay(
        "张三",
        "CET-4",
        "A memorable day",
        image_path="img.png",
        ocr_text="I went to the park.",
    )
    db.update_essay(
        eid,
        score="13",
        ai_score="13",
        max_score="15",
        report_json='{"score":"13"}',
    )
    essay = db.get_essay(eid)
    assert essay is not None
    assert essay["student_name"] == "张三"
    assert essay["score"] == "13"

    db.add_excellent_example("CET-4", "Great text", analysis="advanced")
    assert len(db.list_excellent_examples("CET-4")) == 1

    db.add_feedback_rule("Rule001")
    assert len(db.list_feedback_rules()) == 1
    assert db.get_score_trend("张三", usage_mode="teacher") == []
    db.confirm_essay_review(
        eid,
        teacher_score="13",
        teacher_comment="教师确认评语",
        teacher_reason="语言项调整",
        reviewer="李老师",
    )
    reviewed = db.get_essay(eid)
    assert reviewed is not None
    assert reviewed["ai_score"] == "13"
    assert reviewed["teacher_score"] == "13"
    assert reviewed["score"] == "13"
    assert reviewed["review_status"] == "confirmed"
    assert reviewed["reviewer"] == "李老师"
    assert db.get_score_trend("张三", usage_mode="teacher")[0]["numeric_score"] == 13
    invalid = db.create_essay("张三", "CET-4", "bad", score="Infinity")
    too_high = db.create_essay("张三", "CET-6", "bad2", score="16")
    assert {item["id"] for item in db.get_score_trend("张三", usage_mode="teacher")} == {eid}
    assert invalid != too_high
    db.close()


def test_legacy_database_migration_preserves_rows_and_marks_pending(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            create_time TEXT NOT NULL
        );
        CREATE TABLE essays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            student_name TEXT,
            type TEXT NOT NULL,
            question TEXT NOT NULL DEFAULT '',
            question_summary TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            ocr_text TEXT NOT NULL DEFAULT '',
            score TEXT NOT NULL DEFAULT '',
            report_json TEXT NOT NULL DEFAULT '{}',
            feedback TEXT NOT NULL DEFAULT '',
            time TEXT NOT NULL
        );
        CREATE TABLE feedback_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            time TEXT NOT NULL
        );
        INSERT INTO students(id, name, create_time)
        VALUES (1, '旧学生', '2026-01-01T00:00:00+08:00');
        INSERT INTO essays(
            student_id, student_name, type, question, question_summary,
            image_path, ocr_text, score, report_json, feedback, time
        ) VALUES (
            1, '旧学生', 'CET-4', '旧题目', '旧摘要', 'old.png',
            'Legacy text.', '12', '{"score":"12"}', '旧反馈',
            '2026-01-01T00:00:00+08:00'
        );
        INSERT INTO feedback_rules(content, time)
        VALUES ('旧规则', '2026-01-01T00:00:00+08:00');
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    record = db.get_essay(1)
    assert record is not None
    assert record["question"] == "旧题目"
    assert record["ocr_text"] == "Legacy text."
    assert record["score"] == "12"
    assert record["ai_score"] == "12"
    assert record["teacher_score"] == ""
    assert record["review_status"] == "pending"
    assert record["max_score"] == "15"
    assert db.get_score_trend("旧学生", usage_mode="teacher") == []
    rules = db.list_feedback_rules()
    assert rules[0]["enabled"] == 1
    db.close()


def test_feedback_rules_can_be_disabled_and_deleted(tmp_path: Path) -> None:
    db = Database(tmp_path / "essay.db")
    rule_id = db.add_feedback_rule(
        "人工确认规则",
        source_essay_id=123,
        reviewer="王老师",
    )
    assert [item["id"] for item in db.list_feedback_rules(enabled_only=True)] == [
        rule_id
    ]
    db.set_feedback_rule_enabled(rule_id, False)
    assert db.list_feedback_rules(enabled_only=True) == []
    assert db.list_feedback_rules()[0]["reviewer"] == "王老师"
    db.delete_feedback_rule(rule_id)
    assert db.list_feedback_rules() == []
    db.close()


def test_history_metadata_update_summary_and_delete(tmp_path: Path) -> None:
    db = Database(tmp_path / "essay.db")
    first = db.create_essay(
        None,
        "CET-4",
        "A shared question",
        question_summary="共享题目",
    )
    essay = db.get_essay(first)
    assert essay is not None
    assert essay["student_name"] is None
    assert db.find_question_summary("a shared question") == "共享题目"

    db.update_essay(
        first,
        student_name="",
        essay_type="CET-6",
        question="A new question",
        question_summary="",
    )
    essay = db.get_essay(first)
    assert essay is not None
    assert essay["student_name"] is None
    assert essay["type"] == "CET-6"
    assert essay["question"] == "A new question"

    db.delete_essay(first)
    assert db.get_essay(first) is None
    db.close()


def test_history_pagination_is_complete_stable_and_searchable(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "essay.db")
    created: list[int] = []
    for index in range(155):
        created.append(
            db.create_essay(
                f"学生{index:03d}",
                "CET-4",
                f"题目{index % 3}",
                question_summary=f"分组{index % 3}",
                score=str(index % 15),
            )
        )

    first_page = db.list_essays(limit=100, offset=0)
    second_page = db.list_essays(limit=100, offset=100)
    ids = [record["id"] for record in first_page + second_page]
    assert len(first_page) == 100
    assert len(second_page) == 55
    assert len(ids) == len(set(ids)) == 155
    assert set(ids) == set(created)
    assert db.count_essays() == 155

    old_record = db.list_essays(search="学生000")
    assert [record["student_name"] for record in old_record] == ["学生000"]
    groups = db.list_essay_groups(search="分组1")
    assert sum(group["record_count"] for group in groups) == 52
    db.close()
