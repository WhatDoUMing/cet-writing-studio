"""CET holistic rubric, strict report contract and deterministic length handling."""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

ESSAY_TYPES = {"CET-4": "15", "CET-6": "15"}
RUBRIC_VERSIONS = {level: f"{level.lower()}-holistic-2026-v1" for level in ESSAY_TYPES}
RUBRIC_SOURCE = "https://dxs.moe.gov.cn/zx/a/kskt_yy/210601/1693612.shtml"

def validate_level(level: str) -> str:
    if level not in ESSAY_TYPES:
        raise ValueError("考试级别须为 CET-4 或 CET-6")
    return level

def word_count(text: str) -> int:
    """Contractions/hyphenated compounds/initialisms count once; punctuation splits.

    English alphanumeric tokens only. Unicode apostrophes/hyphens normalize,
    line breaks delimit words. Pure punctuation and Chinese characters add zero.
    """
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace("‘", "'")
    text = re.sub("[‐‑]", "-", text)
    tokens = re.findall(r"(?:[A-Za-z]\.){2,}|[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", text)
    return len(tokens)

def length_requirement(level: str, question: str = "", minimum: int | None = None) -> tuple[int, int | None]:
    validate_level(level)
    if minimum is not None:
        if type(minimum) is not int or not 1 <= minimum <= 5000:
            raise ValueError("题目最低词数须为 1—5000 的整数")
        return minimum, None
    # Accept explicit English/Chinese ranges and minimum instructions.
    match = re.search(r"(\d{2,4})\s*(?:-|—|–|to|至|到)\s*(\d{2,4})\s*(?:words?|词)", question, re.I)
    if match:
        lo, hi = map(int, match.groups())
        if lo > hi:
            raise ValueError("题目词数区间顺序错误")
        return lo, hi
    match = re.search(r"(?:at least|no less than|not less than|不少于|至少|最低)\s*(\d{2,4})\s*(?:words?|词)", question, re.I)
    if match:
        return int(match.group(1)), None
    return (120 if level == "CET-4" else 150), None

def length_notice(text: str, level: str, question: str = "", minimum: int | None = None) -> str:
    count = word_count(text)
    low, high = length_requirement(level, question, minimum)
    target = f"{low}—{high} 词" if high is not None else f"至少 {low} 词"
    state = "低于要求" if count < low else "超过题目上限" if high and count > high else "达到长度要求"
    return f"本地词数 {count}  ·  {level} / {target}  ·  {state}；长度纳入整体评判"

def integer_score(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 15:
        raise ValueError("score 须为 0—15 的整数（布尔值、小数和字符串无效）")
    return value

def score_band(score: int) -> str:
    integer_score(score)
    if score == 0:
        return "0 分"
    for low, label in ((13, "14 分档"), (10, "11 分档"), (7, "8 分档"), (4, "5 分档"), (1, "2 分档")):
        if score >= low:
            return label
    raise AssertionError(score)

def validate_report(report: Any, max_score: Any = 15, student_text: str | None = None) -> dict[str, Any]:
    if isinstance(max_score, bool) or str(max_score) != "15":
        raise ValueError("CET 作文满分固定为 15")
    if not isinstance(report, dict):
        raise ValueError("评分报告须为 JSON 对象")
    score = integer_score(report.get("score"))
    diagnosis = report.get("dimension_feedback")
    if not isinstance(diagnosis, dict):
        raise ValueError("dimension_feedback 须为对象")
    for key in ("content", "language", "structure"):
        if not isinstance(diagnosis.get(key), str) or not diagnosis[key].strip():
            raise ValueError(f"dimension_feedback.{key} 须为非空文字")
    if not isinstance(report.get("overall_comment"), str) or not report["overall_comment"].strip():
        raise ValueError("overall_comment 须为非空文字")
    for key in ("advantages", "disadvantages", "grammar_errors", "sentence_upgrade"):
        items = report.get(key)
        if not isinstance(items, list):
            raise ValueError(f"{key} 须为数组")
        for item in items:
            if key in ("advantages", "disadvantages"):
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(f"{key} 条目须为非空文字")
            else:
                fields = ("sentence", "problem", "correct") if key == "grammar_errors" else ("original", "rewrite", "reason")
                if not isinstance(item, dict) or any(not isinstance(item.get(f), str) or not item[f].strip() for f in fields):
                    raise ValueError(f"{key} 条目须包含文字字段 {fields}")
    result = copy.deepcopy(report)
    # Model-provided derived values are never authoritative.
    result["score_band"] = score_band(score)
    result.pop("word_count", None)
    if student_text is not None:
        result["word_count"] = word_count(student_text)
    return result
