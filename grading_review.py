"""Validation and status constants for teacher grading review."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


REVIEW_PENDING = "pending"
REVIEW_CONFIRMED = "confirmed"
VALID_REVIEW_STATUSES = {REVIEW_PENDING, REVIEW_CONFIRMED}


def validate_teacher_score(value: Any, max_score: Any = 15) -> str:
    if isinstance(max_score, bool) or str(max_score) != "15":
        raise ValueError("CET 满分固定为 15")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if type(value) is not int or not 0 <= value <= 15:
        raise ValueError("教师最终分须为 0—15 整数")
    return str(value)


def format_score(value: Decimal) -> str:
    """Return a stable decimal string suitable for UI and SQLite."""
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
