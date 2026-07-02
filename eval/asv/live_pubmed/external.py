from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.asv.live_pubmed.claims import ClaimLabel, ClaimRecord


PUBMEDQA_LABEL_MAP: dict[str, ClaimLabel] = {
    "yes": "supported",
    "no": "refuted",
    "maybe": "not_enough_information",
}

BIOASQ_LABEL_MAP: dict[str, ClaimLabel] = {
    "yes": "supported",
    "no": "refuted",
}


def public_row_to_claim(
    row: dict[str, Any],
    *,
    dataset: str,
    max_papers: int = 5,
) -> ClaimRecord:
    if not isinstance(row, dict):
        raise ValueError("row must be a JSON object")
    if max_papers <= 0:
        raise ValueError("max_papers must be positive")
    dataset_key = dataset.lower()
    if dataset_key == "pubmedqa":
        raw_id = str(row.get("id") or row.get("pubid") or row.get("pmid") or "").strip()
        question = str(row.get("question") or row.get("QUESTION") or "").strip()
        raw_label = str(row.get("final_decision") or row.get("label") or "").strip().lower()
        label = PUBMEDQA_LABEL_MAP.get(raw_label)
        if label is None:
            raise ValueError(f"unsupported pubmedqa label: {raw_label!r}")
    elif dataset_key == "bioasq":
        raw_id = str(row.get("id") or row.get("qid") or "").strip()
        question = str(row.get("body") or row.get("question") or "").strip()
        exact_answer = row.get("exact_answer")
        raw_label = str(_first_scalar(exact_answer) or row.get("label") or "").strip().lower()
        label = BIOASQ_LABEL_MAP.get(raw_label)
        if label is None:
            raise ValueError(f"unsupported bioasq label: {raw_label!r}")
    else:
        raise ValueError(f"unsupported dataset: {dataset!r}")
    if not raw_id:
        raise ValueError(f"{dataset_key} row is missing id")
    if not question:
        raise ValueError(f"{dataset_key} row is missing question")
    return ClaimRecord(
        claim_id=f"{dataset_key}-{raw_id}",
        question=question if question.endswith("?") else f"{question}?",
        gold_label=label,
        source="pubmed",
        max_papers=max_papers,
        topic=f"external:{dataset_key}",
        rationale="Mapped from a public biomedical QA benchmark label.",
    )


def _first_scalar(value: Any) -> Any:
    while isinstance(value, list):
        value = value[0] if value else ""
    return value


def load_public_validation_rows(
    path: Path,
    *,
    dataset: str,
    max_papers: int = 5,
) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            claims.append(public_row_to_claim(row, dataset=dataset, max_papers=max_papers))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return claims
