from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from plugins.biomed_evidence.workflow.asv import redact_for_asv
from plugins.biomed_evidence.workflow.types import BiomedWorkflowStep

StepStatus = Literal["completed", "skipped", "failed"]
SourcePolicy = Literal["mock_only", "live_opt_in"]
SourceMode = Literal["mock", "pubmed"]


@dataclass(frozen=True)
class MockRetrievalArtifact:
    paper_id: str
    title: str
    abstract: str
    source: SourceMode = "mock"

    def summary(self) -> dict[str, str]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "source": self.source,
        }


@dataclass(frozen=True)
class StepInput:
    run_id: str
    question: str
    source_policy: SourcePolicy = "mock_only"
    source: SourceMode = "mock"
    project_id: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    available_artifacts: list[str] = field(default_factory=list)
    artifact_payloads: list[MockRetrievalArtifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "run_id": self.run_id,
            "question": self.question,
            "source_policy": self.source_policy,
            "source": self.source,
            "completed_steps": list(self.completed_steps),
            "available_artifacts": list(self.available_artifacts),
        }
        if self.project_id:
            state["project_id"] = self.project_id
        return state


@dataclass(frozen=True)
class StepOutput:
    step_id: str
    step_name: str
    status: StepStatus
    input_state: dict[str, Any]
    action: dict[str, Any]
    observation: dict[str, Any]
    output_state: dict[str, Any]
    cost: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifact_ids: dict[str, str] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class ProjectionComparisonIssue:
    code: str
    message: str
    severity: Literal["warning", "error"] = "error"


@dataclass(frozen=True)
class ProjectionComparisonSummary:
    ok: bool
    old_step_count: int
    stateless_step_count: int
    issues: list[ProjectionComparisonIssue] = field(default_factory=list)


def step_output_to_workflow_step(run_id: str, output: StepOutput) -> BiomedWorkflowStep:
    return BiomedWorkflowStep(
        step_id=output.step_id,
        run_id=run_id,
        step_name=output.step_name,
        status=output.status,
        input_state=redact_for_asv(output.input_state),
        action=redact_for_asv(output.action),
        observation=redact_for_asv(output.observation),
        output_state=redact_for_asv(output.output_state),
        cost=dict(output.cost),
        warnings=list(output.warnings),
        errors=list(output.errors),
        artifact_ids=dict(output.artifact_ids),
        created_at=output.created_at,
    )
