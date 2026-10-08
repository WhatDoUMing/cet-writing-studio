from pathlib import Path

from ai.prompt import (
    build_grading_prompt,
    normalize_report,
    parse_ai_json,
    sanitize_question_summary,
)
from database.sqlite import Database
from memory.manager import MemoryManager, rules_for_grading


def test_parse_ai_json_handles_code_fence() -> None:
    raw = '```json\n{"score":"12","advantages":["good"]}\n```'
    report = parse_ai_json(raw)
    assert normalize_report(report)["score"] == "12"


def test_parse_ai_json_repairs_common_syntax_errors() -> None:
    raw = (
        '{"score":"12","content_score":"8","language_score":"7",'
        '"struct_score":"5","advantages":["clear structure",],}'
    )
    report = parse_ai_json(raw)
    assert report["score"] == "12"
    assert report["advantages"] == ["clear structure"]


def test_prompt_contains_context() -> None:
    messages = build_grading_prompt(
        "CET-4",
        "15",
        "题目",
        "I like this activty.",
        [{"text": "Great", "analysis": "advanced"}],
        [{"content": "Rule001"}],
    )
    assert len(messages) == 2
    assert "CET-4" in messages[1]["content"]
    assert "Great" in messages[1]["content"]
    assert "Rule001" in messages[1]["content"]


def test_memory_manager_appends_rule(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path / "personal_design.md")
    rule = manager.build_feedback_rule("12", "13", "语言分偏低")
    manager.append_rule(rule)
    assert len(manager.read_rules()) == 1


def test_question_summary_rejects_model_reasoning() -> None:
    summary = sanitize_question_summary(
        "我们需要回答用户。用户是作文题。",
        "A short question",
    )
    assert summary is None
    assert sanitize_question_summary("传统文化传承", "Some question") == (
        "传统文化传承"
    )
    question = "口语课上外教组织同学们讨论"
    assert sanitize_question_summary(question[:12], question) is None


def test_grading_rules_follow_database_enabled_state(tmp_path: Path) -> None:
    db = Database(tmp_path / "rules.db")
    db.connect()
    memory = MemoryManager(tmp_path / "memory" / "rules.md")
    try:
        assert rules_for_grading(db, memory) == []

        disabled_id = db.add_feedback_rule("这条规则已被停用")
        db.set_feedback_rule_enabled(disabled_id, False)
        db.add_feedback_rule("这条规则仍然启用")

        assert [
            rule["content"] for rule in rules_for_grading(db, memory)
        ] == ["这条规则仍然启用"]

        db.set_feedback_rule_enabled(disabled_id, True)
        assert {
            rule["content"] for rule in rules_for_grading(db, memory)
        } == {"这条规则已被停用", "这条规则仍然启用"}
    finally:
        db.close()


def test_unapproved_markdown_is_not_promoted(tmp_path):
    db = Database(tmp_path / "rules.db")
    memory = MemoryManager(tmp_path / "rules.md")
    memory.append_rule("Unreviewed feedback")
    assert rules_for_grading(db, memory) == []
    assert db.list_feedback_rules() == []
    db.close()


def test_blank_database_rules_are_ignored(tmp_path: Path) -> None:
    db = Database(tmp_path / "blank.db")
    db.connect()
    memory = MemoryManager(tmp_path / "memory" / "rules.md")
    db.add_feedback_rule("   ")
    try:
        assert rules_for_grading(db, memory) == []
    finally:
        db.close()
