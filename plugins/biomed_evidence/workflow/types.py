from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BIOMED_ASV_CANDIDATE_IDS = (
    "supported",
    "refuted",
    "not_enough_information",
)


@dataclass(frozen=True)
class BiomedWorkflowStep:
    step_id: str
    run_id: str
    step_name: str
    status: str
    input_state: dict[str, Any]
    action: dict[str, Any]
    observation: dict[str, Any]
    output_state: dict[str, Any]
    cost: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifact_ids: dict[str, str] = field(default_factory=dict)
    created_at: str | None = None
