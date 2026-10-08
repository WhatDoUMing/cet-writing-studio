"""Pure evaluation metrics for AI grading and optional OCR text."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Callable, Iterable

from grading_review import validate_teacher_score
from cet_scoring import validate_level, validate_report, word_count, RUBRIC_VERSIONS


REQUIRED_SAMPLE_FIELDS = (
    "sample_id",
    "essay_type",
    "max_score",
    "question",
    "student_text",
    "teacher_score",
)


def load_jsonl_samples(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a de-identified JSONL evaluation dataset."""
    samples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSONL 第 {line_number} 行格式错误：{exc}"
                ) from exc
            if not isinstance(sample, dict):
                raise ValueError(f"JSONL 第 {line_number} 行必须是对象")
            missing = [key for key in REQUIRED_SAMPLE_FIELDS if key not in sample]
            if missing:
                raise ValueError(
                    f"JSONL 第 {line_number} 行缺少字段：{', '.join(missing)}"
                )
            sample_id = str(sample["sample_id"]).strip()
            if not sample_id:
                raise ValueError(f"JSONL 第 {line_number} 行 sample_id 为空")
            if sample_id in seen_ids:
                raise ValueError(f"sample_id 重复：{sample_id}")
            seen_ids.add(sample_id)
            normalized = dict(sample)
            validate_level(sample["essay_type"])
            if not isinstance(sample["question"], str) or not sample["question"].strip():
                raise ValueError("评测样本题目必填")
            if not isinstance(sample["student_text"], str) or not sample["student_text"].strip():
                raise ValueError("评测样本作文原文必填")
            normalized["sample_id"] = sample_id
            normalized["teacher_score"] = validate_teacher_score(
                sample["teacher_score"],
                sample["max_score"],
            )
            if sample.get("teacher_score_2") not in (None, ""):
                normalized["teacher_score_2"] = validate_teacher_score(
                    sample["teacher_score_2"],
                    sample["max_score"],
                )
            samples.append(normalized)
    return samples


def run_evaluation(
    samples: Iterable[dict[str, Any]],
    grader: Callable[[dict[str, Any]], dict[str, Any] | str | float],
    *,
    repeat_runs: int = 1,
    severe_error_threshold: float = 5.0,
) -> dict[str, Any]:
    """Grade samples repeatedly and return aggregate and per-sample metrics."""
    if repeat_runs < 1:
        raise ValueError("repeat_runs 必须至少为 1")
    if not math.isfinite(severe_error_threshold) or severe_error_threshold < 0:
        raise ValueError("severe_error_threshold 必须是非负有限数字")

    details: list[dict[str, Any]] = []
    for raw_sample in samples:
        sample = dict(raw_sample)
        sample_id = str(sample.get("sample_id", "")).strip()
        if not sample_id:
            raise ValueError("评测样本缺少 sample_id")
        gold_text = validate_teacher_score(
            sample.get("teacher_score"),
            sample.get("max_score"),
        )
        gold = float(gold_text)
        run_scores: list[float] = []
        errors: list[str] = []
        for _run_index in range(repeat_runs):
            try:
                result = grader(sample)
                if isinstance(result, dict):
                    result = validate_report(result, sample.get("max_score"), sample.get("student_text", ""))
                value = result.get("score") if isinstance(result, dict) else result
                normalized = validate_teacher_score(value, sample.get("max_score"))
                run_scores.append(float(normalized))
            except Exception as exc:  # noqa: BLE001 - per-sample boundary
                errors.append(f"{type(exc).__name__}: {exc}")

        prediction = statistics.fmean(run_scores) if run_scores else None
        bias = prediction - gold if prediction is not None else None
        score_range = (
            max(run_scores) - min(run_scores) if len(run_scores) >= 2 else 0.0
        )
        score_stddev = (
            statistics.pstdev(run_scores) if len(run_scores) >= 2 else 0.0
        )
        detail = {
            "sample_id": sample_id,
            "essay_type": str(sample.get("essay_type", "")),
            "max_score": str(sample.get("max_score", "")),
            "word_count": word_count(sample.get("student_text", "")),
            "rubric_version": RUBRIC_VERSIONS.get(sample.get("essay_type"), ""),
            "teacher_score": gold_text,
            "teacher_score_2": str(sample.get("teacher_score_2", "")),
            "prediction": prediction,
            "error": bias,
            "absolute_error": abs(bias) if bias is not None else None,
            "run_scores": run_scores,
            "successful_runs": len(run_scores),
            "failed_runs": len(errors),
            "score_range": score_range,
            "score_stddev": score_stddev,
            "status": (
                "failed"
                if not run_scores
                else "partial"
                if errors
                else "success"
            ),
            "error_messages": errors,
            "ocr_cer": _sample_ocr_cer(sample),
        }
        details.append(detail)

    successful = [item for item in details if item["status"] == "success"]
    partial = [item for item in details if item["status"] == "partial"]
    failed = [item for item in details if item["status"] == "failed"]
    absolute_errors = [float(item["absolute_error"]) for item in successful]
    biases = [float(item["error"]) for item in successful]
    by_type: dict[str, dict[str, Any]] = {}
    for essay_type in sorted({item["essay_type"] for item in details}):
        type_all = [item for item in details if item["essay_type"] == essay_type]
        type_success = [item for item in type_all if item["status"] == "success"]
        by_type[essay_type] = {
            "sample_count": len(type_all),
            "successful_sample_count": len(type_success),
            "mae": _mean_or_none(
                [float(item["absolute_error"]) for item in type_success]
            ),
        }

    cer_values = [
        float(item["ocr_cer"])
        for item in details
        if item["ocr_cer"] is not None
    ]
    summary = {
        "sample_count": len(details),
        "successful_sample_count": len(successful),
        "partial_failure_sample_count": len(partial),
        "failed_sample_count": len(failed),
        "samples_with_api_failures": sum(
            1 for item in details if item["failed_runs"] > 0
        ),
        "successful_call_count": sum(item["successful_runs"] for item in details),
        "failed_call_count": sum(item["failed_runs"] for item in details),
        "mae": _mean_or_none(absolute_errors),
        "mae_by_type": by_type,
        "within_1_rate": _rate(absolute_errors, 1.0),
        "within_2_rate": _rate(absolute_errors, 2.0),
        "mean_bias": _mean_or_none(biases),
        "severe_error_threshold": severe_error_threshold,
        "severe_error_count": sum(
            1 for error in absolute_errors if error >= severe_error_threshold
        ),
        "repeat_runs": repeat_runs,
        "mean_score_range": _mean_or_none(
            [float(item["score_range"]) for item in successful]
        ),
        "max_score_range": max(
            (float(item["score_range"]) for item in successful),
            default=None,
        ),
        "mean_score_stddev": _mean_or_none(
            [float(item["score_stddev"]) for item in successful]
        ),
        "ocr_sample_count": len(cer_values),
        "ocr_mean_cer": _mean_or_none(cer_values),
        "failed_sample_ids": [item["sample_id"] for item in failed],
        "api_failure_sample_ids": [
            item["sample_id"]
            for item in details
            if item["failed_runs"] > 0
        ],
    }
    return {"summary": summary, "details": details}


def export_details_csv(
    details: Iterable[dict[str, Any]],
    path: str | Path,
) -> None:
    """Export review-oriented metrics without essay text or student identity."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "essay_type",
        "max_score",
        "teacher_score",
        "teacher_score_2",
        "prediction",
        "error",
        "absolute_error",
        "run_scores",
        "successful_runs",
        "failed_runs",
        "score_range",
        "score_stddev",
        "ocr_cer",
        "status",
        "error_messages",
    ]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for raw in details:
            row = {key: raw.get(key, "") for key in fieldnames}
            row["run_scores"] = json.dumps(
                row["run_scores"], ensure_ascii=False
            )
            row["error_messages"] = json.dumps(
                row["error_messages"], ensure_ascii=False
            )
            writer.writerow(row)


def character_error_rate(ocr_text: str, corrected_text: str) -> float:
    """Compute Levenshtein CER using the corrected text as reference."""
    hypothesis = _normalize_ocr_text(ocr_text)
    reference = _normalize_ocr_text(corrected_text)
    return _levenshtein_distance(hypothesis, reference) / max(1, len(reference))


def _sample_ocr_cer(sample: dict[str, Any]) -> float | None:
    if "ocr_text" not in sample or "corrected_text" not in sample:
        return None
    if sample.get("ocr_text") is None or sample.get("corrected_text") is None:
        return None
    return character_error_rate(
        str(sample.get("ocr_text", "")),
        str(sample.get("corrected_text", "")),
    )


def _normalize_ocr_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _levenshtein_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _mean_or_none(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _rate(values: list[float], tolerance: float) -> float | None:
    if not values:
        return None
    return sum(value <= tolerance for value in values) / len(values)
