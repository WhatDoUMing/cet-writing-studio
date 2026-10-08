"""Lightweight English spell hints for the text confirmation page."""

from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from spellchecker import SpellChecker
except ImportError:  # pragma: no cover - UI remains usable without hints
    SpellChecker = None


WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")


@dataclass(frozen=True)
class SpellingHint:
    start: int
    end: int
    original: str
    suggestion: str
    confident: bool = False


class SpellingHintService:
    """Find and suggest corrections for English words in recognized text."""

    def __init__(self) -> None:
        self._checker = None
        if SpellChecker is not None:
            try:
                self._checker = SpellChecker(language="en")
            except Exception:
                self._checker = None

    def find_hints(self, text: str) -> list[SpellingHint]:
        if self._checker is None or not text:
            return []
        hints: list[SpellingHint] = []
        for match in WORD_RE.finditer(text):
            word = match.group(0)
            if len(word) <= 1 or not word.isalpha():
                continue
            corrected = self._checker.correction(word)
            repeated = self._repeated_half(word)
            if repeated:
                corrected = repeated
            if corrected is None:
                continue
            if corrected.lower() == word.lower():
                continue
            suggestion = str(corrected)
            hints.append(
                SpellingHint(
                    start=match.start(),
                    end=match.end(),
                    original=word,
                    suggestion=suggestion,
                    confident=(
                        repeated is not None
                        or self._is_confident_correction(word, suggestion)
                    ),
                )
            )
        return hints

    def apply_safe_corrections(
        self,
        text: str,
    ) -> tuple[str, list[SpellingHint]]:
        """Replace only high-confidence spelling errors."""
        corrections = [
            hint for hint in self.find_hints(text) if hint.confident
        ]
        if not corrections:
            return text, []
        result = text
        for hint in reversed(corrections):
            suggestion = self._match_case(hint.original, hint.suggestion)
            result = result[: hint.start] + suggestion + result[hint.end :]
        return result, corrections

    def _repeated_half(self, word: str) -> str | None:
        if len(word) < 6 or len(word) % 2:
            return None
        half = len(word) // 2
        left, right = word[:half], word[half:]
        if left.lower() != right.lower():
            return None
        return left if self._checker.word_frequency[left.lower()] > 0 else None

    def _is_confident_correction(
        self,
        word: str,
        suggestion: str,
    ) -> bool:
        if len(word) < 4 or not suggestion.isalpha():
            return False
        if _edit_distance(word.lower(), suggestion.lower()) > 2:
            return False
        candidates = self._checker.candidates(word) or set()
        if not candidates:
            return False
        ranked = sorted(
            candidates,
            key=lambda item: self._checker.word_frequency[item],
            reverse=True,
        )
        best_frequency = self._checker.word_frequency[ranked[0]]
        second_frequency = (
            self._checker.word_frequency[ranked[1]]
            if len(ranked) > 1
            else 0
        )
        if best_frequency < 1000:
            return False
        return len(ranked) == 1 or best_frequency >= second_frequency * 5

    @staticmethod
    def _match_case(original: str, suggestion: str) -> str:
        if original.isupper():
            return suggestion.upper()
        if original[:1].isupper():
            return suggestion.capitalize()
        return suggestion


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
