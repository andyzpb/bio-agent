from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


SECRET_MARKERS = (
    "raw_provider_response",
    "provider_response",
    "raw_response",
    "Authorization",
    "Bearer ",
    "api_key=",
    "client_secret",
    "password",
    "token=",
    "sk-live",
)


@dataclass(frozen=True)
class EvaluationRun:
    input_path: Path
    output_dir: Path
    cache_path: Path
    evaluated_path: Path
    fallback_policy: str = "floor"
    floor_score: float = -20.0
    model: str = "deepseek-v4-flash"


def build_evaluate_command(run: EvaluationRun) -> list[str]:
    return [
        ".venv/bin/python",
        "-m",
        "asv_eval",
        "evaluate",
        "--input",
        str(run.input_path),
        "--evaluator",
        "deepseek-chat-logprob",
        "--model",
        run.model,
        "--fallback-policy",
        run.fallback_policy,
        "--floor-score",
        str(run.floor_score),
        "--cache",
        str(run.cache_path),
        "--write-evaluated-trajectories",
        str(run.evaluated_path),
        "--output-dir",
        str(run.output_dir),
    ]


def scan_for_secret_markers(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in SECRET_MARKERS:
            search_text = (
                text.replace("raw_provider_response", "")
                if marker == "provider_response"
                else text
            )
            if marker in search_text:
                findings.append(f"{marker} found in {path}")
    return findings


def output_files_for_secret_scan(
    output_dir: Path,
    evaluated_path: Path,
    cache_path: Path,
) -> list[Path]:
    paths = [evaluated_path, cache_path]
    if output_dir.exists():
        paths.extend(path for path in output_dir.rglob("*") if path.is_file())
    return paths


def run_evaluation(run: EvaluationRun) -> subprocess.CompletedProcess[str]:
    run.output_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        build_evaluate_command(run),
        check=False,
        capture_output=True,
        text=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate frozen live PubMed ASV trajectories.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--evaluated", required=True)
    parser.add_argument("--model", default="deepseek-v4-flash")
    args = parser.parse_args(argv)
    run = EvaluationRun(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        cache_path=Path(args.cache),
        evaluated_path=Path(args.evaluated),
        model=str(args.model),
    )
    result = run_evaluation(run)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if result.returncode != 0:
        return result.returncode
    findings = scan_for_secret_markers(
        output_files_for_secret_scan(run.output_dir, run.evaluated_path, run.cache_path)
    )
    if findings:
        for finding in findings:
            print(finding)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
