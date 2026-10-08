"""Read and append human-approved grading correction rules.

The SQLite ``feedback_rules`` table is the source of truth because only it
carries the enable/disable state. The Markdown file stays a human-readable
mirror: the scoring-dispute flow keeps writing it, and rules created by older
versions (Markdown only) are imported into the database once.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from logger_config import get_logger


log = get_logger("memory.manager")


class MemoryManager:
    """Manage the Markdown file used as long-term RAG context."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                "# CET Writing Studio 教师确认规则\n\n> 本文件由系统自动维护。\n",
                encoding="utf-8",
            )

    def read_rules(self) -> list[dict[str, str]]:
        """Parse Markdown rule blocks into structured records."""
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)^##\s+Rule\d+", text)
        rules: list[dict[str, str]] = []
        for block in blocks[1:]:
            content = block.strip()
            if content:
                rules.append({"content": f"## Rule{len(rules) + 1}\n{content}"})
        return rules

    def append_rule(self, rule_text: str) -> None:
        """Append a new rule using the standard feedback template."""
        if not rule_text.strip():
            raise ValueError("规则内容不能为空")
        current = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        next_number = len(self.read_rules()) + 1
        block = (
            f"\n## Rule{next_number:03d}\n"
            f"{rule_text.strip()}\n"
        )
        if current and not current.endswith("\n"):
            current += "\n"
        self.path.write_text(current + block, encoding="utf-8")
        log.info("Appended %s", f"Rule{next_number:03d}")

    def build_feedback_rule(
        self,
        original_score: str,
        suggested_score: str,
        reason: str,
    ) -> str:
        """Create the standard Chinese rule template."""
        time_text = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"时间：{time_text}\n"
            f"用户反馈：评分标准错误\n"
            f"原AI评分：{original_score}\n"
            f"用户建议：{suggested_score}\n"
            f"用户理由：{reason}\n"
            "AI分析：待人工复核后采用\n"
            "最终采用规则：在相似题型、相似表达水平下，应参考用户建议的评分边界，"
            "并重点复核用户理由中涉及的维度。"
        )


def import_markdown_rules(db: Any, memory: MemoryManager) -> int:
    """Never promote unreviewed Markdown automatically in a fresh CET project."""
    return 0

def rules_for_grading(db: Any, memory: MemoryManager, exam_level: str = "CET-4") -> list[dict[str, str]]:
    return [{"content": row["content"]} for row in db.list_feedback_rules(enabled_only=True, exam_level=exam_level) if row["content"].strip()]
