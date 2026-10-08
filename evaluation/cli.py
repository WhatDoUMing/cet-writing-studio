"""Command-line entry point for de-identified school grading evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai.chat_api import ChatCompletionClient
from config_manager import ConfigManager
from cet_scoring import RUBRIC_VERSIONS
from evaluation.metrics import (
    export_details_csv,
    load_jsonl_samples,
    run_evaluation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对脱敏作文 JSONL 批量运行评分评测并导出指标。"
    )
    parser.add_argument("--input", required=True, type=Path, help="JSONL 数据集")
    parser.add_argument("--csv", required=True, type=Path, help="评测明细 CSV")
    parser.add_argument("--summary", type=Path, help="可选汇总 JSON 输出路径")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--provider", help="覆盖项目当前 AI 服务商")
    parser.add_argument("--runs", type=int, help="每个样本重复评分次数")
    parser.add_argument(
        "--severe-threshold",
        type=float,
        help="严重跨档的绝对分差阈值，由学校确定",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "evaluation.json",
        help="评测运行参数 JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evaluation_config = _load_config(args.config)
    repeat_runs = args.runs or int(evaluation_config.get("repeat_runs", 1))
    threshold = (
        args.severe_threshold
        if args.severe_threshold is not None
        else float(evaluation_config.get("severe_error_threshold", 5.0))
    )
    config = ConfigManager(args.project_root)
    provider = (args.provider or config.get_ai_provider()).strip().lower()
    provider_config = config.get_ai_provider_config(provider)
    client = ChatCompletionClient(
        provider,
        provider_config,
        api_key=config.get_api_key(provider),
    )
    samples = load_jsonl_samples(args.input)

    def grade(sample: dict[str, Any]) -> dict[str, Any]:
        return client.grade_essay(
            essay_type=str(sample["essay_type"]),
            max_score=str(sample["max_score"]),
            question=str(sample["question"]),
            student_text=str(sample["student_text"]),
        )

    result = run_evaluation(
        samples,
        grade,
        repeat_runs=repeat_runs,
        severe_error_threshold=threshold,
    )
    result["run_metadata"] = {
        "provider": provider,
        "model": client.model,
        "prompt_version": config.get("grading.prompt_version", ""),
        "rubric_versions": RUBRIC_VERSIONS,
    }
    export_details_csv(result["details"], args.csv)
    summary_text = json.dumps(
        {"run_metadata": result["run_metadata"], "summary": result["summary"]},
        ensure_ascii=False,
        indent=2,
    )
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary_text + "\n", encoding="utf-8")
    print(summary_text)
    return 0


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("评测配置必须是 JSON 对象")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
