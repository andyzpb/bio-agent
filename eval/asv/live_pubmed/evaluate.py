from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "x-api-key",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bsk-(?:live|proj)-[A-Za-z0-9._-]+"),
)
SAFE_SECRET_VALUES = {
    "DEEPSEEK_API_KEY",
}
SAFE_SECRET_KEYS = {
    "credential_env",
    "prompt_hash",
    "prompt_tokens",
    "completion_tokens",
    "max_tokens",
    "total_tokens",
}


@dataclass(frozen=True)
class EvaluationRun:
    input_path: Path
    output_dir: Path
    cache_path: Path
    evaluated_path: Path
    fallback_policy: str = "floor"
    floor_score: float = -20.0
    model: str = "deepseek-v4-flash"
    python_executable: str = sys.executable


def build_evaluate_command(run: EvaluationRun) -> list[str]:
    return [
        run.python_executable,
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
        path_findings: list[str] = []
        for marker in SECRET_MARKERS:
            search_text = (
                text.replace("raw_provider_response", "")
                if marker == "provider_response"
                else text
            )
            if marker in search_text:
                _add_finding(path_findings, marker, path)
        for marker in _json_secret_markers(text):
            _add_finding(path_findings, marker, path)
        for pattern in SECRET_VALUE_PATTERNS:
            for match in pattern.findall(text):
                normalized = match.split()[0].lower() if " " in match else match[:7].lower()
                if match in SAFE_SECRET_VALUES:
                    continue
                if normalized.startswith("bearer"):
                    _add_finding(path_findings, "bearer", path)
                elif normalized.startswith("sk-"):
                    _add_finding(path_findings, "sk-", path)
        findings.extend(path_findings)
    return findings


def _json_secret_markers(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _jsonl_secret_markers(text)
    return _walk_secret_keys(payload)


def _jsonl_secret_markers(text: str) -> list[str]:
    findings: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        findings.extend(_walk_secret_keys(payload))
    return findings


def _walk_secret_keys(value: Any) -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            if normalized in SAFE_SECRET_KEYS:
                findings.extend(_walk_secret_keys(item))
                continue
            for marker in SECRET_KEY_PARTS:
                marker_normalized = marker.replace("-", "_")
                if marker_normalized in normalized and key_text not in findings:
                    findings.append(key_text)
            findings.extend(_walk_secret_keys(item))
    elif isinstance(value, list):
        for item in value:
            findings.extend(_walk_secret_keys(item))
    return findings


def _add_finding(findings: list[str], marker: str, path: Path) -> None:
    normalized_marker = marker.strip().lower()
    if normalized_marker in _finding_markers(findings, path):
        return
    findings.append(f"{marker} found in {path}")


def _finding_markers(findings: list[str], path: Path) -> set[str]:
    suffix = f" found in {path}"
    return {finding.removesuffix(suffix).strip().lower() for finding in findings}


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
    parser.add_argument("--fallback-policy", choices=["error", "floor"], default="floor")
    parser.add_argument("--floor-score", type=float, default=-20.0)
    args = parser.parse_args(argv)
    run = EvaluationRun(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        cache_path=Path(args.cache),
        evaluated_path=Path(args.evaluated),
        model=str(args.model),
        fallback_policy=str(args.fallback_policy),
        floor_score=float(args.floor_score),
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
