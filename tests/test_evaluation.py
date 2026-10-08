import csv
import json
from pathlib import Path

import pytest
from tests.test_cet_contract import valid_report

from evaluation.metrics import (
    character_error_rate,
    export_details_csv,
    load_jsonl_samples,
    run_evaluation,
)


def sample(sample_id: str, essay_type: str, gold: float) -> dict:
    return {
        "sample_id": sample_id,
        "essay_type": essay_type,
        "max_score": 15,
        "question": "Synthetic question",
        "student_text": "Synthetic student text.",
        "teacher_score": gold,
    }


def test_evaluation_metrics_count_failures_and_exclude_them_from_mae() -> None:
    samples = [
        sample("stable", "CET-4", 10),
        sample("partial", "CET-6", 10),
        sample("failed", "CET-6", 10),
    ]
    calls: dict[str, int] = {}

    def fake_grader(item: dict) -> dict:
        sample_id = item["sample_id"]
        calls[sample_id] = calls.get(sample_id, 0) + 1
        if sample_id == "failed":
            raise RuntimeError("simulated API failure")
        if sample_id == "partial" and calls[sample_id] == 1:
            raise RuntimeError("simulated transient failure")
        return valid_report(12 if sample_id == "stable" else 8)

    result = run_evaluation(
        samples,
        fake_grader,
        repeat_runs=2,
        severe_error_threshold=2,
    )
    summary = result["summary"]
    assert summary["sample_count"] == 3
    assert summary["successful_sample_count"] == 1
    assert summary["partial_failure_sample_count"] == 1
    assert summary["failed_sample_count"] == 1
    assert summary["samples_with_api_failures"] == 2
    assert summary["successful_call_count"] == 3
    assert summary["failed_call_count"] == 3
    assert summary["mae"] == 2
    assert summary["within_1_rate"] == 0
    assert summary["within_2_rate"] == 1
    assert summary["mean_bias"] == 2
    assert summary["severe_error_count"] == 1
    assert summary["failed_sample_ids"] == ["failed"]
    assert summary["api_failure_sample_ids"] == ["partial", "failed"]
    assert summary["mae_by_type"]["CET-6"]["sample_count"] == 2
    assert summary["mae_by_type"]["CET-6"]["mae"] is None


def test_evaluation_reports_repeat_variability_and_ocr_cer() -> None:
    item = sample("repeat", "CET-4", 10)
    item.update(ocr_text="abc", corrected_text="adc")
    scores = iter([9, 11, 10])
    result = run_evaluation(
        [item],
        lambda _sample: valid_report(next(scores)),
        repeat_runs=3,
    )
    detail = result["details"][0]
    assert detail["prediction"] == 10
    assert detail["score_range"] == 2
    assert detail["score_stddev"] == pytest.approx(0.81649658)
    assert detail["ocr_cer"] == pytest.approx(1 / 3)
    assert result["summary"]["ocr_sample_count"] == 1
    assert character_error_rate("abc", "adc") == pytest.approx(1 / 3)


def test_jsonl_loading_and_csv_export_are_deidentified(tmp_path: Path) -> None:
    source = tmp_path / "samples.jsonl"
    source.write_text(
        json.dumps(
            {
                **sample("S-001", "CET-4", 11),
                "teacher_score_2": 12,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    samples = load_jsonl_samples(source)
    assert samples[0]["teacher_score"] == "11"
    assert samples[0]["teacher_score_2"] == "12"

    result = run_evaluation(samples, lambda _item: valid_report(10))
    destination = tmp_path / "details.csv"
    export_details_csv(result["details"], destination)
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["sample_id"] == "S-001"
    assert "student_text" not in rows[0]


def test_jsonl_rejects_duplicate_ids(tmp_path: Path) -> None:
    source = tmp_path / "duplicates.jsonl"
    line = json.dumps(sample("same", "CET-4", 11), ensure_ascii=False)
    source.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sample_id 重复"):
        load_jsonl_samples(source)
