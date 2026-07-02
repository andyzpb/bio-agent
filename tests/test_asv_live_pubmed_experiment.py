from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.asv.live_pubmed.claims import (
    CLAIM_LABELS,
    ClaimRecord,
    load_claims_jsonl,
    validate_claim_set,
)


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = (
    ROOT
    / "eval"
    / "asv"
    / "experiments"
    / "live_pubmed_step_value"
    / "claims.pilot.jsonl"
)


def test_live_pubmed_claim_loader_reads_pilot_set() -> None:
    claims = load_claims_jsonl(CLAIMS_PATH)

    assert len(claims) == 30
    assert {claim.gold_label for claim in claims} == set(CLAIM_LABELS)
    assert all(claim.source == "pubmed" for claim in claims)
    assert all(claim.max_papers >= 3 for claim in claims)
    assert all(claim.question.endswith("?") for claim in claims)


def test_live_pubmed_claim_set_is_balanced_and_has_unique_ids() -> None:
    claims = load_claims_jsonl(CLAIMS_PATH)

    summary = validate_claim_set(claims, min_per_label=8)

    assert summary["total"] == 30
    assert summary["labels"] == {
        "supported": 10,
        "refuted": 10,
        "not_enough_information": 10,
    }
    assert summary["duplicate_ids"] == []


def test_live_pubmed_claim_loader_rejects_invalid_label(tmp_path: Path) -> None:
    path = tmp_path / "claims.jsonl"
    path.write_text(
        json.dumps(
            {
                "claim_id": "bad-1",
                "question": "Does alpha improve beta?",
                "gold_label": "yes",
                "source": "pubmed",
                "max_papers": 3,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid gold_label"):
        load_claims_jsonl(path)


def test_claim_record_to_answer_request_payload_uses_live_flags() -> None:
    claim = ClaimRecord(
        claim_id="claim-test",
        question="Does APOE e4 increase Alzheimer's disease risk?",
        gold_label="supported",
        source="pubmed",
        max_papers=4,
    )

    payload = claim.to_answer_request_payload()

    assert payload == {
        "question": "Does APOE e4 increase Alzheimer's disease risk?",
        "source": "pubmed",
        "max_papers": 4,
        "use_llm_planner": True,
        "execute_support_refute": True,
        "use_llm_extractor": True,
        "use_llm_synthesis": True,
        "use_llm_verifier": True,
        "use_llm_revision": True,
        "use_llm_claim_logic": True,
        "export_logic_facts": True,
    }
