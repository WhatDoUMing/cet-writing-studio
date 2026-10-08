"""Apply AI grammar and rewrite suggestions back to the original essay."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CorrectionResult:
    text: str
    applied: int
    skipped: list[str]


def apply_report_corrections(
    original_text: str,
    report: dict[str, Any],
) -> CorrectionResult:
    """Replace matched report suggestions and return the corrected essay."""
    text = original_text
    applied = 0
    skipped: list[str] = []

    correction_pairs: list[tuple[str, str]] = []
    for item in report.get("grammar_errors", []) or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("sentence", "")).strip()
        replacement = str(item.get("correct", "")).strip()
        if source and replacement:
            correction_pairs.append((source, replacement))

    for item in report.get("sentence_upgrade", []) or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("original", "")).strip()
        replacement = str(item.get("rewrite", "")).strip()
        if source and replacement:
            correction_pairs.append((source, replacement))

    for source, replacement in correction_pairs:
        match = _find_source(text, source)
        if match is None:
            skipped.append(source)
            continue
        start, end = match
        text = text[:start] + replacement + text[end:]
        applied += 1

    return CorrectionResult(text=text, applied=applied, skipped=skipped)


def _find_source(text: str, source: str) -> tuple[int, int] | None:
    exact = text.find(source)
    if exact >= 0:
        return exact, exact + len(source)

    case_insensitive = re.search(re.escape(source), text, re.IGNORECASE)
    if case_insensitive:
        return case_insensitive.start(), case_insensitive.end()

    words = source.split()
    if not words:
        return None
    whitespace_flexible = re.search(
        r"\s+".join(re.escape(word) for word in words),
        text,
        re.IGNORECASE,
    )
    if whitespace_flexible:
        return whitespace_flexible.start(), whitespace_flexible.end()
    return None
