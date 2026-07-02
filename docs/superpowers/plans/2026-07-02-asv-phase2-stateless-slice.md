# ASV Phase 2 Stateless Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first DSPy-like stateless bio-agent workflow slice: deterministic `ClassifyStep`, mocked-source `RetrieveStep`, ASV projection, and an old-vs-stateless comparison helper.

**Architecture:** Keep the production `answer_with_audit` path unchanged. Add a focused `plugins/biomed_evidence/workflow/stateless/` package whose step functions accept explicit dataclass inputs and return explicit dataclass outputs. Convert those outputs into existing `BiomedWorkflowStep` objects and reuse `trajectory_from_workflow_steps(...)` plus the Phase 1 provided-belief ASV evaluator path.

**Tech Stack:** Python 3.12, dataclasses, existing `plugins.biomed_evidence.workflow.asv` projection helpers, existing guardrails/mock paper data, pytest, stdlib JSON/subprocess.

---

## File Structure

- Create `plugins/biomed_evidence/workflow/stateless/__init__.py`: public exports for the stateless slice.
- Create `plugins/biomed_evidence/workflow/stateless/types.py`: shared `StepInput`, `StepOutput`, `MockRetrievalArtifact`, `ProjectionComparisonIssue`, `ProjectionComparisonSummary`, and `step_output_to_workflow_step(...)`.
- Create `plugins/biomed_evidence/workflow/stateless/classify.py`: deterministic `classify_step(...)` using existing clinical-boundary guardrails.
- Create `plugins/biomed_evidence/workflow/stateless/retrieve.py`: deterministic mocked-source `retrieve_step(...)` using explicit input artifacts only.
- Create `plugins/biomed_evidence/workflow/stateless/compare.py`: comparison helper for old workflow projection vs stateless projection fixtures.
- Create `tests/test_biomed_stateless_workflow.py`: unit/integration tests for contracts, steps, ASV projection, provided-belief evaluation, and comparison helper.

---

### Task 1: Stateless Types And Projection Contract

**Files:**
- Create: `plugins/biomed_evidence/workflow/stateless/__init__.py`
- Create: `plugins/biomed_evidence/workflow/stateless/types.py`
- Create: `tests/test_biomed_stateless_workflow.py`

- [ ] **Step 1: Write the failing projection contract test**

Create `tests/test_biomed_stateless_workflow.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from plugins.biomed_evidence.workflow.asv import trajectory_from_workflow_steps
from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)


def test_stateless_step_output_projects_to_biomed_workflow_step() -> None:
    step_input = StepInput(
        run_id="stateless-run-1",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
    )
    step_output = StepOutput(
        step_id="retrieve",
        step_name="retrieve",
        status="completed",
        input_state=step_input.to_state(),
        action={"type": "retrieve", "source_mode": "mock"},
        observation={"summary": "retrieved one mocked paper"},
        output_state={
            **step_input.to_state(),
            "completed_steps": ["classify", "retrieve"],
            "available_artifacts": ["classification:research", "retrieval_id:retrieval-1"],
        },
        cost={"source_call_count": 1, "tool_calls": 1},
        warnings=["mock source"],
        artifact_ids={"retrieval_id": "retrieval-1"},
    )

    workflow_step = step_output_to_workflow_step("stateless-run-1", step_output)

    assert workflow_step.step_name == "retrieve"
    assert workflow_step.run_id == "stateless-run-1"
    assert workflow_step.action["source_mode"] == "mock"
    assert workflow_step.output_state["completed_steps"] == ["classify", "retrieve"]
    assert workflow_step.cost["source_call_count"] == 1
    assert workflow_step.warnings == ["mock source"]
    assert workflow_step.artifact_ids == {"retrieval_id": "retrieval-1"}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_stateless_step_output_projects_to_biomed_workflow_step
```

Expected: FAIL with `ModuleNotFoundError: No module named 'plugins.biomed_evidence.workflow.stateless'`.

- [ ] **Step 3: Create the stateless package exports**

Create `plugins/biomed_evidence/workflow/stateless/__init__.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    ProjectionComparisonIssue,
    ProjectionComparisonSummary,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)

__all__ = [
    "MockRetrievalArtifact",
    "ProjectionComparisonIssue",
    "ProjectionComparisonSummary",
    "StepInput",
    "StepOutput",
    "step_output_to_workflow_step",
]
```

- [ ] **Step 4: Create `types.py` with explicit contracts**

Create `plugins/biomed_evidence/workflow/stateless/types.py`:

```python
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
```

- [ ] **Step 5: Run the projection test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_stateless_step_output_projects_to_biomed_workflow_step
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add \
  plugins/biomed_evidence/workflow/stateless/__init__.py \
  plugins/biomed_evidence/workflow/stateless/types.py \
  tests/test_biomed_stateless_workflow.py
git commit -m "feat: add stateless biomed workflow contracts"
```

---

### Task 2: Deterministic ClassifyStep

**Files:**
- Modify: `plugins/biomed_evidence/workflow/stateless/__init__.py`
- Create: `plugins/biomed_evidence/workflow/stateless/classify.py`
- Modify: `tests/test_biomed_stateless_workflow.py`

- [ ] **Step 1: Add failing tests for research and clinical-refusal classification**

Append to `tests/test_biomed_stateless_workflow.py`:

```python
from plugins.biomed_evidence.workflow.stateless.classify import classify_step


def test_classify_step_returns_research_contract() -> None:
    step_input = StepInput(
        run_id="stateless-run-2",
        question="What evidence links microglial activation to Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.step_name == "classify"
    assert output.status == "completed"
    assert output.action == {
        "type": "classify",
        "policy": "deterministic_guardrail",
        "source_policy": "mock_only",
    }
    assert output.observation["classification"] == "research"
    assert output.observation["allowed_next_step"] == "retrieve"
    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == ["classification:research"]
    assert output.cost == {"llm_call_count": 0, "tool_calls": 0}
    assert output.artifact_ids == {"classification": "research"}


def test_classify_step_refuses_patient_specific_clinical_request() -> None:
    step_input = StepInput(
        run_id="stateless-run-3",
        question="My father has symptoms, what dose of medication should he take?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.status == "skipped"
    assert output.observation["classification"] == "clinical_advice_refusal"
    assert output.observation["allowed_next_step"] == "stop"
    assert "research support only" in output.observation["refusal_reason"]
    assert output.warnings == ["clinical_boundary"]
    assert output.output_state["clinical_boundary"] is True
    assert output.output_state["available_artifacts"] == [
        "classification:clinical_advice_refusal"
    ]
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_classify_step_returns_research_contract tests/test_biomed_stateless_workflow.py::test_classify_step_refuses_patient_specific_clinical_request
```

Expected: FAIL with `ModuleNotFoundError` for `plugins.biomed_evidence.workflow.stateless.classify`.

- [ ] **Step 3: Create `classify.py`**

Create `plugins/biomed_evidence/workflow/stateless/classify.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.guardrails import clinical_refusal, is_clinical_request
from plugins.biomed_evidence.workflow.stateless.types import StepInput, StepOutput


def classify_step(step_input: StepInput) -> StepOutput:
    input_state = step_input.to_state()
    is_clinical = is_clinical_request(step_input.question)
    classification = "clinical_advice_refusal" if is_clinical else "research"
    completed_steps = [*step_input.completed_steps, "classify"]
    available_artifacts = [
        *step_input.available_artifacts,
        f"classification:{classification}",
    ]
    output_state = {
        **input_state,
        "completed_steps": completed_steps,
        "available_artifacts": available_artifacts,
        "request_type": classification,
        "clinical_boundary": is_clinical,
    }
    observation = {
        "classification": classification,
        "allowed_next_step": "stop" if is_clinical else "retrieve",
        "summary": (
            "Patient-specific clinical advice request refused."
            if is_clinical
            else "The request is a bounded biomedical research question."
        ),
    }
    if is_clinical:
        observation["refusal_reason"] = clinical_refusal()

    return StepOutput(
        step_id="classify",
        step_name="classify",
        status="skipped" if is_clinical else "completed",
        input_state=input_state,
        action={
            "type": "classify",
            "policy": "deterministic_guardrail",
            "source_policy": step_input.source_policy,
        },
        observation=observation,
        output_state=output_state,
        cost={"llm_call_count": 0, "tool_calls": 0},
        warnings=["clinical_boundary"] if is_clinical else [],
        artifact_ids={"classification": classification},
    )
```

- [ ] **Step 4: Update stateless package exports**

Modify `plugins/biomed_evidence/workflow/stateless/__init__.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.workflow.stateless.classify import classify_step
from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    ProjectionComparisonIssue,
    ProjectionComparisonSummary,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)

__all__ = [
    "MockRetrievalArtifact",
    "ProjectionComparisonIssue",
    "ProjectionComparisonSummary",
    "StepInput",
    "StepOutput",
    "classify_step",
    "step_output_to_workflow_step",
]
```

- [ ] **Step 5: Run classify tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_classify_step_returns_research_contract tests/test_biomed_stateless_workflow.py::test_classify_step_refuses_patient_specific_clinical_request
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add \
  plugins/biomed_evidence/workflow/stateless/__init__.py \
  plugins/biomed_evidence/workflow/stateless/classify.py \
  tests/test_biomed_stateless_workflow.py
git commit -m "feat: add stateless biomed classify step"
```

---

### Task 3: Mocked-Source RetrieveStep

**Files:**
- Modify: `plugins/biomed_evidence/workflow/stateless/__init__.py`
- Create: `plugins/biomed_evidence/workflow/stateless/retrieve.py`
- Modify: `tests/test_biomed_stateless_workflow.py`

- [ ] **Step 1: Add failing tests for mocked retrieval and clinical-boundary skip**

Append to `tests/test_biomed_stateless_workflow.py`:

```python
from plugins.biomed_evidence.workflow.stateless.retrieve import retrieve_step


def test_retrieve_step_returns_mock_artifacts_from_explicit_input() -> None:
    step_input = StepInput(
        run_id="stateless-run-4",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
        artifact_payloads=[
            MockRetrievalArtifact(
                paper_id="MOCK-PMID-1001",
                title="Microglial activation signatures track disease progression",
                abstract="Activated microglia correlated with Braak stage.",
            )
        ],
    )

    output = retrieve_step(step_input)

    assert output.step_name == "retrieve"
    assert output.status == "completed"
    assert output.action == {
        "type": "retrieve",
        "source_mode": "mock",
        "query": "Does microglial activation track Alzheimer's progression?",
    }
    assert output.observation["retrieval_id"] == "stateless-run-4-retrieval-mock"
    assert output.observation["paper_count"] == 1
    assert output.observation["papers"][0]["paper_id"] == "MOCK-PMID-1001"
    assert output.output_state["completed_steps"] == ["classify", "retrieve"]
    assert output.output_state["available_artifacts"] == [
        "classification:research",
        "retrieval_id:stateless-run-4-retrieval-mock",
    ]
    assert output.cost == {
        "source_call_count": 1,
        "artifact_cache_hit_count": 0,
        "tool_calls": 1,
    }
    assert output.artifact_ids == {
        "retrieval_id": "stateless-run-4-retrieval-mock",
    }


def test_retrieve_step_skips_after_clinical_boundary() -> None:
    step_input = StepInput(
        run_id="stateless-run-5",
        question="What dose should my father take?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:clinical_advice_refusal"],
    )

    output = retrieve_step(step_input)

    assert output.status == "skipped"
    assert output.observation["summary"] == "clinical boundary stopped retrieval"
    assert output.warnings == ["clinical_boundary"]
    assert output.cost == {
        "source_call_count": 0,
        "artifact_cache_hit_count": 0,
        "tool_calls": 0,
    }
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_retrieve_step_returns_mock_artifacts_from_explicit_input tests/test_biomed_stateless_workflow.py::test_retrieve_step_skips_after_clinical_boundary
```

Expected: FAIL with `ModuleNotFoundError` for `plugins.biomed_evidence.workflow.stateless.retrieve`.

- [ ] **Step 3: Create `retrieve.py`**

Create `plugins/biomed_evidence/workflow/stateless/retrieve.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.workflow.stateless.types import StepInput, StepOutput


def retrieve_step(step_input: StepInput) -> StepOutput:
    input_state = step_input.to_state()
    if "classification:clinical_advice_refusal" in step_input.available_artifacts:
        output_state = {
            **input_state,
            "last_step": "retrieve",
            "last_status": "skipped",
        }
        return StepOutput(
            step_id="retrieve",
            step_name="retrieve",
            status="skipped",
            input_state=input_state,
            action={
                "type": "retrieve",
                "source_mode": step_input.source,
                "query": step_input.question,
            },
            observation={"summary": "clinical boundary stopped retrieval", "paper_count": 0},
            output_state=output_state,
            cost={
                "source_call_count": 0,
                "artifact_cache_hit_count": 0,
                "tool_calls": 0,
            },
            warnings=["clinical_boundary"],
        )

    if step_input.source_policy != "mock_only" or step_input.source != "mock":
        output_state = {
            **input_state,
            "last_step": "retrieve",
            "last_status": "failed",
        }
        return StepOutput(
            step_id="retrieve",
            step_name="retrieve",
            status="failed",
            input_state=input_state,
            action={
                "type": "retrieve",
                "source_mode": step_input.source,
                "query": step_input.question,
            },
            observation={"summary": "stateless retrieve supports mock source only"},
            output_state=output_state,
            cost={
                "source_call_count": 0,
                "artifact_cache_hit_count": 0,
                "tool_calls": 0,
            },
            errors=["unsupported_source_policy"],
        )

    retrieval_id = f"{step_input.run_id}-retrieval-mock"
    papers = [artifact.summary() for artifact in step_input.artifact_payloads]
    completed_steps = [*step_input.completed_steps, "retrieve"]
    available_artifacts = [
        *step_input.available_artifacts,
        f"retrieval_id:{retrieval_id}",
    ]
    output_state = {
        **input_state,
        "completed_steps": completed_steps,
        "available_artifacts": available_artifacts,
        "retrieval_id": retrieval_id,
        "retrieved_paper_ids": [paper["paper_id"] for paper in papers],
        "last_step": "retrieve",
        "last_status": "completed",
    }
    return StepOutput(
        step_id="retrieve",
        step_name="retrieve",
        status="completed",
        input_state=input_state,
        action={
            "type": "retrieve",
            "source_mode": "mock",
            "query": step_input.question,
        },
        observation={
            "retrieval_id": retrieval_id,
            "summary": f"retrieved {len(papers)} mocked paper(s)",
            "paper_count": len(papers),
            "papers": papers,
        },
        output_state=output_state,
        cost={
            "source_call_count": 1 if papers else 0,
            "artifact_cache_hit_count": 0,
            "tool_calls": 1 if papers else 0,
        },
        warnings=[] if papers else ["empty_mock_retrieval"],
        artifact_ids={"retrieval_id": retrieval_id},
    )
```

- [ ] **Step 4: Update stateless package exports**

Modify `plugins/biomed_evidence/workflow/stateless/__init__.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.workflow.stateless.classify import classify_step
from plugins.biomed_evidence.workflow.stateless.retrieve import retrieve_step
from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    ProjectionComparisonIssue,
    ProjectionComparisonSummary,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)

__all__ = [
    "MockRetrievalArtifact",
    "ProjectionComparisonIssue",
    "ProjectionComparisonSummary",
    "StepInput",
    "StepOutput",
    "classify_step",
    "retrieve_step",
    "step_output_to_workflow_step",
]
```

- [ ] **Step 5: Run retrieve tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_retrieve_step_returns_mock_artifacts_from_explicit_input tests/test_biomed_stateless_workflow.py::test_retrieve_step_skips_after_clinical_boundary
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add \
  plugins/biomed_evidence/workflow/stateless/__init__.py \
  plugins/biomed_evidence/workflow/stateless/retrieve.py \
  tests/test_biomed_stateless_workflow.py
git commit -m "feat: add stateless biomed retrieve step"
```

---

### Task 4: ASV Evaluation Over Stateless Slice

**Files:**
- Modify: `tests/test_biomed_stateless_workflow.py`

- [ ] **Step 1: Add failing end-to-end ASV evaluation test**

Append to `tests/test_biomed_stateless_workflow.py`:

```python
def test_stateless_classify_retrieve_slice_evaluates_with_provided_beliefs(
    tmp_path: Path,
) -> None:
    classify_output = classify_step(
        StepInput(
            run_id="stateless-run-6",
            question="Does microglial activation track Alzheimer's progression?",
            source_policy="mock_only",
            source="mock",
        )
    )
    retrieve_output = retrieve_step(
        StepInput(
            run_id="stateless-run-6",
            question="Does microglial activation track Alzheimer's progression?",
            source_policy="mock_only",
            source="mock",
            completed_steps=classify_output.output_state["completed_steps"],
            available_artifacts=classify_output.output_state["available_artifacts"],
            artifact_payloads=[
                MockRetrievalArtifact(
                    paper_id="MOCK-PMID-1001",
                    title="Microglial activation signatures track disease progression",
                    abstract="Activated microglia correlated with Braak stage.",
                )
            ],
        )
    )
    workflow_steps = [
        step_output_to_workflow_step("stateless-run-6", classify_output),
        step_output_to_workflow_step("stateless-run-6", retrieve_output),
    ]
    trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-6",
        question="Does microglial activation track Alzheimer's progression?",
        steps=workflow_steps,
    )

    input_path = tmp_path / "stateless-asv.jsonl"
    fixture_path = tmp_path / "beliefs.jsonl"
    output_dir = tmp_path / "asv-report"
    input_path.write_text(
        json.dumps(asdict(trajectory), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fixture_rows = [
        {
            "trajectory_id": trajectory.trajectory_id,
            "step_id": "classify",
            "belief_before": {
                "supported": 0.34,
                "refuted": 0.33,
                "not_enough_information": 0.33,
            },
            "belief_after": {
                "supported": 0.36,
                "refuted": 0.31,
                "not_enough_information": 0.33,
            },
        },
        {
            "trajectory_id": trajectory.trajectory_id,
            "step_id": "retrieve",
            "belief_before": {
                "supported": 0.36,
                "refuted": 0.31,
                "not_enough_information": 0.33,
            },
            "belief_after": {
                "supported": 0.78,
                "refuted": 0.08,
                "not_enough_information": 0.14,
            },
        },
    ]
    fixture_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fixture_rows),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(input_path),
            "--belief-fixture",
            str(fixture_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["trajectory_count"] == 1
    assert summary["step_count"] == 2
    assert summary["positive_net_asv_steps"] == 2
    assert summary["evaluator"]["mode"] == "provided-belief"
```

- [ ] **Step 2: Run the test and verify RED if previous tasks are incomplete**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_stateless_classify_retrieve_slice_evaluates_with_provided_beliefs
```

Expected before Task 2/3 implementation: FAIL due missing imports/functions. Expected after Task 2/3: PASS.

- [ ] **Step 3: Run the full stateless test file and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py
```

Expected: PASS.

- [ ] **Step 4: Commit Task 4**

Run:

```bash
git add tests/test_biomed_stateless_workflow.py
git commit -m "test: evaluate stateless biomed slice with asv"
```

---

### Task 5: Old-Vs-Stateless Comparison Helper

**Files:**
- Modify: `plugins/biomed_evidence/workflow/stateless/__init__.py`
- Create: `plugins/biomed_evidence/workflow/stateless/compare.py`
- Modify: `tests/test_biomed_stateless_workflow.py`

- [ ] **Step 1: Add failing comparison helper tests**

Append to `tests/test_biomed_stateless_workflow.py`:

```python
from plugins.biomed_evidence.workflow.stateless.compare import compare_projections


def test_compare_projections_accepts_matching_stateless_slice() -> None:
    old_first = step_output_to_workflow_step(
        "stateless-run-7",
        classify_step(
            StepInput(
                run_id="stateless-run-7",
                question="Does microglial activation track Alzheimer's progression?",
            )
        ),
    )
    old_second = step_output_to_workflow_step(
        "stateless-run-7",
        retrieve_step(
            StepInput(
                run_id="stateless-run-7",
                question="Does microglial activation track Alzheimer's progression?",
                completed_steps=["classify"],
                available_artifacts=["classification:research"],
                artifact_payloads=[
                    MockRetrievalArtifact(
                        paper_id="MOCK-PMID-1001",
                        title="Microglial activation signatures track disease progression",
                        abstract="Activated microglia correlated with Braak stage.",
                    )
                ],
            )
        ),
    )
    old_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-7",
        question="Does microglial activation track Alzheimer's progression?",
        steps=[old_first, old_second],
    )
    stateless_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-7",
        question="Does microglial activation track Alzheimer's progression?",
        steps=[old_first, old_second],
    )

    summary = compare_projections(old_trajectory, stateless_trajectory)

    assert summary.ok is True
    assert summary.old_step_count == 2
    assert summary.stateless_step_count == 2
    assert summary.issues == []


def test_compare_projections_reports_missing_core_step() -> None:
    old_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-8",
        question="Does microglial activation track Alzheimer's progression?",
        steps=[
            step_output_to_workflow_step(
                "stateless-run-8",
                classify_step(
                    StepInput(
                        run_id="stateless-run-8",
                        question="Does microglial activation track Alzheimer's progression?",
                    )
                ),
            )
        ],
    )
    stateless_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-8",
        question="Does microglial activation track Alzheimer's progression?",
        steps=[
            step_output_to_workflow_step(
                "stateless-run-8",
                classify_step(
                    StepInput(
                        run_id="stateless-run-8",
                        question="Does microglial activation track Alzheimer's progression?",
                    )
                ),
            )
        ],
    )

    summary = compare_projections(old_trajectory, stateless_trajectory)

    assert summary.ok is False
    assert [issue.code for issue in summary.issues] == ["missing_core_step"]
```

- [ ] **Step 2: Run comparison tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_compare_projections_accepts_matching_stateless_slice tests/test_biomed_stateless_workflow.py::test_compare_projections_reports_missing_core_step
```

Expected: FAIL with `ModuleNotFoundError` for `plugins.biomed_evidence.workflow.stateless.compare`.

- [ ] **Step 3: Create `compare.py`**

Create `plugins/biomed_evidence/workflow/stateless/compare.py`:

```python
from __future__ import annotations

import json

from asv_eval.core import TrajectoryRecord
from plugins.biomed_evidence.workflow.stateless.types import (
    ProjectionComparisonIssue,
    ProjectionComparisonSummary,
)

_CORE_STEPS = ("classify", "retrieve")


def compare_projections(
    old_projection: TrajectoryRecord,
    stateless_projection: TrajectoryRecord,
) -> ProjectionComparisonSummary:
    issues: list[ProjectionComparisonIssue] = []
    if old_projection.task.question != stateless_projection.task.question:
        issues.append(
            ProjectionComparisonIssue(
                code="question_mismatch",
                message="Old and stateless projections use different questions.",
            )
        )
    old_candidates = [item.id for item in old_projection.task.candidate_space.candidates]
    stateless_candidates = [
        item.id for item in stateless_projection.task.candidate_space.candidates
    ]
    if old_candidates != stateless_candidates:
        issues.append(
            ProjectionComparisonIssue(
                code="candidate_space_mismatch",
                message="Old and stateless projections use different candidate IDs.",
            )
        )
    stateless_step_names = [
        str(step.action.get("type") or step.step_id) for step in stateless_projection.steps
    ]
    for required_step in _CORE_STEPS:
        if required_step not in stateless_step_names:
            issues.append(
                ProjectionComparisonIssue(
                    code="missing_core_step",
                    message=f"Stateless projection is missing {required_step}.",
                )
            )
    for step in stateless_projection.steps:
        if not step.state_before or not step.state_after:
            issues.append(
                ProjectionComparisonIssue(
                    code="missing_state",
                    message=f"Step {step.step_id} is missing state_before/state_after.",
                )
            )
        if not step.action or not step.observation:
            issues.append(
                ProjectionComparisonIssue(
                    code="missing_projection_fields",
                    message=f"Step {step.step_id} is missing action or observation.",
                )
            )
    rendered = json.dumps(
        [step.quality_flags for step in stateless_projection.steps],
        sort_keys=True,
        ensure_ascii=False,
    )
    for marker in ("api_key", "raw_provider_response", "provider raw secret"):
        if marker in rendered:
            issues.append(
                ProjectionComparisonIssue(
                    code="quality_flag_marker_leak",
                    message=f"Stateless projection quality flags contain {marker}.",
                )
            )
            break
    return ProjectionComparisonSummary(
        ok=not any(issue.severity == "error" for issue in issues),
        old_step_count=len(old_projection.steps),
        stateless_step_count=len(stateless_projection.steps),
        issues=issues,
    )
```

- [ ] **Step 4: Update stateless package exports**

Modify `plugins/biomed_evidence/workflow/stateless/__init__.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.workflow.stateless.classify import classify_step
from plugins.biomed_evidence.workflow.stateless.compare import compare_projections
from plugins.biomed_evidence.workflow.stateless.retrieve import retrieve_step
from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    ProjectionComparisonIssue,
    ProjectionComparisonSummary,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)

__all__ = [
    "MockRetrievalArtifact",
    "ProjectionComparisonIssue",
    "ProjectionComparisonSummary",
    "StepInput",
    "StepOutput",
    "classify_step",
    "compare_projections",
    "retrieve_step",
    "step_output_to_workflow_step",
]
```

- [ ] **Step 5: Run comparison tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_compare_projections_accepts_matching_stateless_slice tests/test_biomed_stateless_workflow.py::test_compare_projections_reports_missing_core_step
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add \
  plugins/biomed_evidence/workflow/stateless/__init__.py \
  plugins/biomed_evidence/workflow/stateless/compare.py \
  tests/test_biomed_stateless_workflow.py
git commit -m "feat: compare stateless biomed asv projections"
```

---

### Task 6: Closeout Verification

**Files:**
- No expected source changes unless a previous task exposed a missing export or typo.

- [ ] **Step 1: Run stateless workflow tests**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py
```

Expected: PASS.

- [ ] **Step 2: Run ASV regression suite**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py tests/test_asv_cli.py tests/test_asv_runtime.py tests/test_asv_experiment_bundle.py tests/test_biomed_workflow_asv.py tests/test_biomed_stateless_workflow.py
```

Expected: PASS.

- [ ] **Step 3: Run key Biomedical Evidence regressions**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_evidence.py::test_trace_answer_run_uses_latest_revision_as_display_answer tests/test_biomed_api.py::test_biomed_api_answer_extract_graph_and_audit
```

Expected: PASS.

- [ ] **Step 4: Run compile and whitespace checks**

Run:

```bash
.venv/bin/python -m py_compile \
  plugins/biomed_evidence/workflow/stateless/__init__.py \
  plugins/biomed_evidence/workflow/stateless/types.py \
  plugins/biomed_evidence/workflow/stateless/classify.py \
  plugins/biomed_evidence/workflow/stateless/retrieve.py \
  plugins/biomed_evidence/workflow/stateless/compare.py \
  plugins/biomed_evidence/workflow/asv.py \
  asv_eval/core.py \
  asv_eval/adapters.py \
  asv_eval/reporting.py \
  asv_eval/runtime.py \
  asv_eval/__main__.py
git diff --check
```

Expected: both commands exit `0`.

- [ ] **Step 5: Confirm production path stayed unchanged**

Run:

```bash
git diff --name-only origin/codex/asv-eval-tool..HEAD
```

Expected: the diff includes the stateless package, stateless tests, and plan docs. It should not include large edits to `plugins/biomed_evidence/service.py`, dashboard files, or production storage paths unless a previous review explicitly required them.

- [ ] **Step 6: Final code review**

Dispatch a final reviewer over the Phase 2 commits and ask it to verify:

- `ClassifyStep` and `RetrieveStep` are stateless;
- no storage/dashboard/global mutation;
- both steps project to `BiomedWorkflowStep`;
- projected trajectory evaluates with provided beliefs;
- comparison helper catches missing core steps;
- existing production regressions passed.

- [ ] **Step 7: Commit any verification-only doc adjustment**

Only if verification found a README/spec wording mismatch, commit that correction:

```bash
git add docs/superpowers/plans/2026-07-02-asv-phase2-stateless-slice.md
git commit -m "docs: correct asv stateless slice plan"
```

If no correction was needed, do not create a commit for this step.

---

## Final Verification

Before claiming Phase 2 first slice complete, run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py tests/test_asv_cli.py tests/test_asv_runtime.py tests/test_asv_experiment_bundle.py tests/test_biomed_workflow_asv.py tests/test_biomed_stateless_workflow.py
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_evidence.py::test_trace_answer_run_uses_latest_revision_as_display_answer tests/test_biomed_api.py::test_biomed_api_answer_extract_graph_and_audit
.venv/bin/python -m py_compile plugins/biomed_evidence/workflow/stateless/__init__.py plugins/biomed_evidence/workflow/stateless/types.py plugins/biomed_evidence/workflow/stateless/classify.py plugins/biomed_evidence/workflow/stateless/retrieve.py plugins/biomed_evidence/workflow/stateless/compare.py plugins/biomed_evidence/workflow/asv.py asv_eval/core.py asv_eval/adapters.py asv_eval/reporting.py asv_eval/runtime.py asv_eval/__main__.py
git diff --check
git status --short --branch
```
