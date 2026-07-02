from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

CLAIM_LABELS = ("supported", "refuted", "not_enough_information")
ClaimLabel = Literal["supported", "refuted", "not_enough_information"]


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    question: str
    gold_label: ClaimLabel
    source: Literal["pubmed"] = "pubmed"
    max_papers: int = 5
    topic: str | None = None
    rationale: str | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any], *, path: Path, line_no: int) -> "ClaimRecord":
        label = str(payload.get("gold_label") or "")
        if label not in CLAIM_LABELS:
            raise ValueError(f"{path}:{line_no}: invalid gold_label: {label}")
        source = str(payload.get("source") or "pubmed")
        if source != "pubmed":
            raise ValueError(f"{path}:{line_no}: live experiment source must be pubmed")
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError(f"{path}:{line_no}: question is required")
        claim_id = str(payload.get("claim_id") or "").strip()
        if not claim_id:
            raise ValueError(f"{path}:{line_no}: claim_id is required")
        return cls(
            claim_id=claim_id,
            question=question,
            gold_label=label,  # pyright: ignore[reportArgumentType]
            source="pubmed",
            max_papers=max(1, int(payload.get("max_papers") or 5)),
            topic=str(payload["topic"]).strip() if payload.get("topic") else None,
            rationale=str(payload["rationale"]).strip() if payload.get("rationale") else None,
        )

    def to_answer_request_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "source": self.source,
            "max_papers": self.max_papers,
            "use_llm_planner": True,
            "execute_support_refute": True,
            "use_llm_extractor": True,
            "use_llm_synthesis": True,
            "use_llm_verifier": True,
            "use_llm_revision": True,
            "use_llm_claim_logic": True,
            "export_logic_facts": True,
        }


def load_claims_jsonl(path: Path) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        claims.append(ClaimRecord.from_json(json.loads(line), path=path, line_no=line_no))
    validate_claim_set(claims, min_per_label=1)
    return claims


def validate_claim_set(
    claims: list[ClaimRecord],
    *,
    min_per_label: int,
) -> dict[str, Any]:
    counts = Counter(claim.gold_label for claim in claims)
    duplicate_ids = sorted(
        claim_id for claim_id, count in Counter(claim.claim_id for claim in claims).items() if count > 1
    )
    missing = [label for label in CLAIM_LABELS if counts[label] < min_per_label]
    if duplicate_ids:
        raise ValueError(f"duplicate claim ids: {duplicate_ids}")
    if missing:
        raise ValueError(f"claim set lacks minimum rows for labels: {missing}")
    return {
        "total": len(claims),
        "labels": {label: counts[label] for label in CLAIM_LABELS},
        "duplicate_ids": duplicate_ids,
    }
