# Biomed Stateless ASV Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive DSPy-like `answer_with_audit` ASV export path that turns saved biomedical audited-answer runs into standard ASV trajectories without changing existing product behavior.

**Architecture:** Keep `BiomedEvidenceService.answer_with_audit()` behavior intact and add a deterministic workflow projection layer under `plugins/biomed_evidence/workflow/`. The projection turns persisted `AnswerWithEvidenceResult` plus `AgentTraceStep` rows into `BiomedWorkflowStep` records and then into `asv_eval.core.TrajectoryRecord` objects. Storage and service own persistence; the workflow ASV module owns redaction, state snapshots, cost extraction, artifact IDs, and candidate-space mapping.

**Tech Stack:** Python 3.12, stdlib dataclasses/json/re, Pydantic models already in `plugins.biomed_evidence.schemas`, existing `asv_eval` package, existing `pytest`.

---

## File Structure

- Create `plugins/biomed_evidence/workflow/__init__.py`: exports the workflow ASV helpers.
- Create `plugins/biomed_evidence/workflow/types.py`: defines `BiomedWorkflowStep` and biomedical ASV candidates.
- Create `plugins/biomed_evidence/workflow/asv.py`: redacts trace metadata, converts trace steps to workflow steps, converts a saved answer run into `TrajectoryRecord`.
- Modify `plugins/biomed_evidence/storage.py`: add `get_answer_run_question(run_id)` so ASV export uses the original research question.
- Modify `plugins/biomed_evidence/service.py`: add `export_answer_run_asv_trajectory(run_id)`.
- Modify `asv_eval/adapters.py`: route `adapt_bio_agent_run_from_storage()` through the new rich biomedical workflow projection.
- Modify `asv_eval/__main__.py`: add optional `--belief-fixture` to `evaluate`.
- Modify `asv_eval/adapters.py`: add `load_belief_fixture()` and `apply_belief_fixture()` for provided-belief experiments.
- Create `tests/test_biomed_workflow_asv.py`: tests workflow projection and service export.
- Modify `tests/test_asv_adapters.py`: update the bio-agent adapter expectations from conservative trace-only projection to rich workflow projection.
- Modify `tests/test_asv_cli.py`: test belief fixture overlay.

---

### Task 1: Workflow ASV Projection Types

**Files:**
- Create: `plugins/biomed_evidence/workflow/__init__.py`
- Create: `plugins/biomed_evidence/workflow/types.py`
- Create: `plugins/biomed_evidence/workflow/asv.py`
- Test: `tests/test_biomed_workflow_asv.py`

- [ ] **Step 1: Write failing workflow projection tests**

Create `tests/test_biomed_workflow_asv.py` with this content:

```python
from __future__ import annotations

import json

from plugins.biomed_evidence.schemas import AgentTraceStep
from plugins.biomed_evidence.workflow.asv import (
    trajectory_from_workflow_steps,
    workflow_step_from_trace,
)
from plugins.biomed_evidence.workflow.types import BIOMED_ASV_CANDIDATE_IDS


def test_workflow_trace_step_projects_state_action_observation_and_cost() -> None:
    trace = AgentTraceStep(
        step_id="trace-retrieve",
        run_id="run-1",
        step="retrieve",
        status="completed",
        input_summary="Does alpha improve beta?",
        output_summary="retrieval-1",
        warnings=["source warning"],
        metadata={
            "retrieval_id": "retrieval-1",
            "papers": ["PMID:1"],
            "observability": {
                "llm_call_count": 1,
                "source_call_count": 2,
                "prompt_tokens": 321,
                "latency_ms": 140,
                "artifact_cache_hit_count": 1,
            },
            "raw_provider_response": {"authorization": "Bearer secret"},
            "synthesis_prompt_hash": "sha256:abc",
        },
        created_at="2026-07-02T12:00:00Z",
    )

    step = workflow_step_from_trace(
        trace,
        state_before={
            "run_id": "run-1",
            "question": "Does alpha improve beta?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )

    assert step.step_name == "retrieve"
    assert step.action["type"] == "retrieve"
    assert step.action["status"] == "completed"
    assert step.artifact_ids["retrieval_id"] == "retrieval-1"
    assert step.cost["llm_call_count"] == 1
    assert step.cost["source_call_count"] == 2
    assert step.cost["prompt_tokens"] == 321
    assert step.cost["latency_ms"] == 140
    assert step.output_state["completed_steps"] == ["retrieve"]
    assert step.output_state["available_artifacts"] == ["retrieval_id:retrieval-1"]

    rendered = json.dumps(step.observation, sort_keys=True)
    assert "Bearer secret" not in rendered
    assert "raw_provider_response" in rendered
    assert "sha256:abc" in rendered


def test_workflow_steps_convert_to_standard_asv_trajectory() -> None:
    first = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-classify",
            run_id="run-1",
            step="classify",
            status="completed",
            input_summary="Does alpha improve beta?",
            output_summary="research_ok",
            metadata={},
            created_at="2026-07-02T12:00:00Z",
        ),
        state_before={
            "run_id": "run-1",
            "question": "Does alpha improve beta?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )
    second = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-audit",
            run_id="run-1",
            step="audit",
            status="completed",
            input_summary="draft",
            output_summary="audit-1",
            metadata={
                "claim_support_rate": 1.0,
                "citation_precision": 1.0,
                "unsupported_claim_rate": 0.0,
                "overclaim_rate": 0.0,
                "observability": {"prompt_tokens": 222},
            },
            created_at="2026-07-02T12:00:01Z",
        ),
        state_before=first.output_state,
    )

    trajectory = trajectory_from_workflow_steps(
        run_id="run-1",
        question="Does alpha improve beta?",
        steps=[first, second],
    )

    assert trajectory.trajectory_id == "bio-agent-run-1"
    assert trajectory.source_adapter == "bio_agent_workflow"
    assert trajectory.run_id == "run-1"
    assert [item.id for item in trajectory.task.candidate_space.candidates] == list(
        BIOMED_ASV_CANDIDATE_IDS
    )
    assert [step.action["type"] for step in trajectory.steps] == [
        "classify",
        "audit",
    ]
    assert trajectory.steps[0].state_before is not None
    assert trajectory.steps[0].state_after is not None
    assert trajectory.steps[1].cost["prompt_tokens"] == 222
    assert trajectory.steps[1].belief_before is None
    assert trajectory.steps[1].belief_after is None
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'plugins.biomed_evidence.workflow'`.

- [ ] **Step 3: Create workflow package exports**

Create `plugins/biomed_evidence/workflow/__init__.py`:

```python
from __future__ import annotations

from plugins.biomed_evidence.workflow.asv import (
    trajectory_from_answer_run,
    trajectory_from_workflow_steps,
    workflow_step_from_trace,
)
from plugins.biomed_evidence.workflow.types import (
    BIOMED_ASV_CANDIDATE_IDS,
    BiomedWorkflowStep,
)

__all__ = [
    "BIOMED_ASV_CANDIDATE_IDS",
    "BiomedWorkflowStep",
    "trajectory_from_answer_run",
    "trajectory_from_workflow_steps",
    "workflow_step_from_trace",
]
```

- [ ] **Step 4: Add workflow step types**

Create `plugins/biomed_evidence/workflow/types.py`:

```python
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
```

- [ ] **Step 5: Add ASV projection helpers**

Create `plugins/biomed_evidence/workflow/asv.py`:

```python
from __future__ import annotations

import re
from typing import Any

from asv_eval.core import (
    Candidate,
    CandidateSpace,
    StepRecord,
    TaskRecord,
    TrajectoryRecord,
)
from plugins.biomed_evidence.workflow.types import (
    BIOMED_ASV_CANDIDATE_IDS,
    BiomedWorkflowStep,
)

_REDACTED = "[redacted]"
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
    "raw_provider_response",
    "llm_raw_response",
)
_SAFE_SECRETISH_KEYS = {
    "prompt_tokens",
    "completion_tokens",
    "synthesis_prompt_hash",
    "llm_prompt_hash",
    "extractor_prompt_hash",
}


def workflow_step_from_trace(
    trace_step: Any,
    *,
    state_before: dict[str, Any],
) -> BiomedWorkflowStep:
    metadata = redact_for_asv(dict(getattr(trace_step, "metadata", {}) or {}))
    artifact_ids = _artifact_ids_from_metadata(metadata)
    cost = _cost_from_metadata(metadata)
    step_name = str(getattr(trace_step, "step", ""))
    status = str(getattr(trace_step, "status", ""))
    completed_steps = list(state_before.get("completed_steps", []))
    completed_steps.append(step_name)
    available_artifacts = sorted(
        {
            *[str(item) for item in state_before.get("available_artifacts", [])],
            *[f"{key}:{value}" for key, value in artifact_ids.items()],
        }
    )
    output_state = {
        "run_id": getattr(trace_step, "run_id", ""),
        "question": state_before.get("question", ""),
        "completed_steps": completed_steps,
        "available_artifacts": available_artifacts,
        "last_step": step_name,
        "last_status": status,
        "last_artifact_ids": artifact_ids,
    }
    return BiomedWorkflowStep(
        step_id=str(getattr(trace_step, "step_id", "")),
        run_id=str(getattr(trace_step, "run_id", "")),
        step_name=step_name,
        status=status,
        input_state=redact_for_asv(state_before),
        action={
            "type": step_name,
            "status": status,
            "is_external_observation": step_name
            in {
                "retrieve",
                "extract",
                "audit",
                "advisory_verify",
                "post_audit",
                "revise",
                "finalize",
            },
        },
        observation={
            "input_summary": getattr(trace_step, "input_summary", ""),
            "output_summary": getattr(trace_step, "output_summary", ""),
            "warnings": list(getattr(trace_step, "warnings", []) or []),
            "metadata": metadata,
            "artifact_ids": artifact_ids,
        },
        output_state=redact_for_asv(output_state),
        cost=cost,
        warnings=list(getattr(trace_step, "warnings", []) or []),
        artifact_ids=artifact_ids,
        created_at=getattr(trace_step, "created_at", None),
    )


def trajectory_from_answer_run(
    *,
    run: Any,
    question: str,
    trace: list[Any],
) -> TrajectoryRecord:
    state: dict[str, Any] = {
        "run_id": getattr(run, "run_id", ""),
        "question": question,
        "completed_steps": [],
        "available_artifacts": [],
    }
    steps: list[BiomedWorkflowStep] = []
    for trace_step in trace:
        step = workflow_step_from_trace(trace_step, state_before=state)
        steps.append(step)
        state = step.output_state
    return trajectory_from_workflow_steps(
        run_id=str(getattr(run, "run_id", "")),
        question=question,
        steps=steps,
        final_score=_final_score_from_run(run),
        success=_success_from_run(run),
    )


def trajectory_from_workflow_steps(
    *,
    run_id: str,
    question: str,
    steps: list[BiomedWorkflowStep],
    final_score: float | None = None,
    success: bool | None = None,
) -> TrajectoryRecord:
    candidates = [
        Candidate(id="supported", label="A", text="supported"),
        Candidate(id="refuted", label="B", text="refuted"),
        Candidate(
            id="not_enough_information",
            label="C",
            text="not enough information",
        ),
    ]
    task = TaskRecord(
        task_id=run_id,
        question=question,
        candidate_space=CandidateSpace(candidates=candidates),
        domain="biomedical",
    )
    return TrajectoryRecord(
        trajectory_id=f"bio-agent-{run_id}",
        source_adapter="bio_agent_workflow",
        run_id=run_id,
        task=task,
        steps=[
            StepRecord(
                step_id=step.step_id,
                index=index,
                action=step.action,
                observation=step.observation,
                state_before=step.input_state,
                state_after=step.output_state,
                cost=step.cost,
                label=step.status,
                label_source="biomed_agent_trace",
            )
            for index, step in enumerate(steps)
        ],
        metadata={
            "workflow_step_count": len(steps),
            "candidate_ids": list(BIOMED_ASV_CANDIDATE_IDS),
        },
        final_score=final_score,
        success=success,
    )


def redact_for_asv(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            str_key = str(key)
            if _is_secret_key(str_key):
                redacted[str_key] = _REDACTED
            else:
                redacted[str_key] = redact_for_asv(item)
        return redacted
    if isinstance(value, list):
        return [redact_for_asv(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_asv(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"Bearer\\s+[^\\s]+", "Bearer [redacted]", value)
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SAFE_SECRETISH_KEYS or lowered.endswith("_prompt_hash"):
        return False
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def _artifact_ids_from_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key in (
        "retrieval_id",
        "evidence_packet_id",
        "audit_id",
        "revision_id",
        "post_revision_audit_id",
        "snapshot_id",
        "graph_id",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            ids[key] = value
    return ids


def _cost_from_metadata(metadata: dict[str, Any]) -> dict[str, float]:
    observability = metadata.get("observability")
    if not isinstance(observability, dict):
        return {}
    cost: dict[str, float] = {}
    for key in (
        "llm_call_count",
        "source_call_count",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "artifact_cache_hit_count",
        "artifact_cache_miss_count",
        "artifact_cache_write_count",
        "saved_source_call_count",
    ):
        value = observability.get(key)
        if isinstance(value, (int, float)):
            cost[key] = float(value)
    tool_calls = cost.get("llm_call_count", 0.0) + cost.get("source_call_count", 0.0)
    if tool_calls:
        cost["tool_calls"] = tool_calls
    return cost


def _final_score_from_run(run: Any) -> float | None:
    if getattr(run, "evidence_summary", None):
        return 1.0
    if "could not retrieve citation-backed evidence" in str(getattr(run, "answer", "")):
        return 0.0
    return None


def _success_from_run(run: Any) -> bool | None:
    if getattr(run, "evidence_summary", None):
        return True
    if "could not retrieve citation-backed evidence" in str(getattr(run, "answer", "")):
        return False
    return None
```

- [ ] **Step 6: Run projection tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py
```

Expected: `2 passed`.

- [ ] **Step 7: Commit Task 1**

```bash
git add plugins/biomed_evidence/workflow/__init__.py \
  plugins/biomed_evidence/workflow/types.py \
  plugins/biomed_evidence/workflow/asv.py \
  tests/test_biomed_workflow_asv.py
git commit -m "feat: add biomed workflow asv projection"
```

---

### Task 2: Service-Level ASV Export

**Files:**
- Modify: `plugins/biomed_evidence/storage.py`
- Modify: `plugins/biomed_evidence/service.py`
- Modify: `tests/test_biomed_workflow_asv.py`

- [ ] **Step 1: Add failing service export tests**

Append this to `tests/test_biomed_workflow_asv.py`:

```python
from pathlib import Path

import pytest

from plugins.biomed_evidence.schemas import AnswerWithEvidenceRequest
from plugins.biomed_evidence.service import BiomedEvidenceService


@pytest.mark.asyncio
async def test_service_exports_saved_audited_run_as_asv_trajectory(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question=(
                    "What recent evidence links microglial activation to "
                    "Alzheimer's disease progression?"
                ),
                source="mock",
                max_papers=5,
            )
        )

        trajectory = service.export_answer_run_asv_trajectory(
            audited.answer_result.run_id
        )
    finally:
        await service.aclose()

    assert trajectory.run_id == audited.answer_result.run_id
    assert trajectory.task.question.startswith("What recent evidence")
    step_types = [step.action["type"] for step in trajectory.steps]
    assert {"classify", "retrieve", "extract", "audit", "revise", "finalize"} <= set(
        step_types
    )
    assert all(step.state_before is not None for step in trajectory.steps)
    assert all(step.state_after is not None for step in trajectory.steps)
    assert any(step.cost for step in trajectory.steps)
    rendered = json.dumps(
        [step.observation for step in trajectory.steps],
        sort_keys=True,
    ).lower()
    assert "authorization" not in rendered
    assert "bearer secret" not in rendered
    assert "raw_provider_response" not in rendered or "[redacted]" in rendered


def test_service_export_asv_trajectory_reports_missing_run(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        with pytest.raises(ValueError, match="answer_run_not_found"):
            service.export_answer_run_asv_trajectory("missing-run")
    finally:
        service.storage.close()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py
```

Expected: FAIL with `AttributeError: 'BiomedEvidenceService' object has no attribute 'export_answer_run_asv_trajectory'`.

- [ ] **Step 3: Add storage question lookup**

In `plugins/biomed_evidence/storage.py`, add this method directly after `get_answer_run()`:

```python
    def get_answer_run_question(self, run_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT question FROM biomed_answer_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["question"])
```

- [ ] **Step 4: Add service export method**

In `plugins/biomed_evidence/service.py`, add this import near the other biomedical imports:

```python
from plugins.biomed_evidence.workflow.asv import trajectory_from_answer_run
```

Then add this method near `get_answer_trace()`:

```python
    def export_answer_run_asv_trajectory(self, run_id: str):
        result = self.storage.get_answer_run(run_id)
        if result is None:
            raise ValueError(f"answer_run_not_found: {run_id}")
        trace = self.storage.list_agent_trace_steps(run_id)
        if not trace:
            raise ValueError(f"answer_trace_not_found: {run_id}")
        question = (
            self.storage.get_answer_run_question(run_id)
            or _pilot_question(result)
            or result.answer[:240]
            or run_id
        )
        return trajectory_from_answer_run(
            run=result,
            question=question,
            trace=trace,
        )
```

If `pyright` reports a return type issue, import `TrajectoryRecord` from `asv_eval.core` under the existing imports and annotate the method as:

```python
    def export_answer_run_asv_trajectory(self, run_id: str) -> TrajectoryRecord:
```

- [ ] **Step 5: Run service export tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py
```

Expected: `4 passed`.

- [ ] **Step 6: Run existing audited-answer regression tests**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_evidence.py::test_trace_answer_run_uses_latest_revision_as_display_answer
```

Expected: `2 passed`.

- [ ] **Step 7: Commit Task 2**

```bash
git add plugins/biomed_evidence/storage.py \
  plugins/biomed_evidence/service.py \
  tests/test_biomed_workflow_asv.py
git commit -m "feat: export biomed answer runs as asv trajectories"
```

---

### Task 3: Rich Bio-Agent Adapter And Belief Fixtures

**Files:**
- Modify: `asv_eval/adapters.py`
- Modify: `asv_eval/__main__.py`
- Modify: `tests/test_asv_adapters.py`
- Modify: `tests/test_asv_cli.py`

- [ ] **Step 1: Update failing bio-agent adapter test**

In `tests/test_asv_adapters.py`, replace `test_bio_agent_adapter_maps_trace_steps_conservatively()` with:

```python
def test_bio_agent_adapter_uses_workflow_asv_projection() -> None:
    storage = SimpleNamespace(
        get_answer_run=lambda run_id: SimpleNamespace(
            run_id=run_id,
            answer="Final answer",
            evidence_summary=[{"evidence_id": "ev-1"}],
            citations=[],
        ),
        get_answer_run_question=lambda run_id: "Does alpha improve beta?",
        list_agent_trace_steps=lambda run_id: [
            SimpleNamespace(
                step_id="classify-1",
                run_id=run_id,
                step="classify",
                status="completed",
                input_summary="question",
                output_summary="research_ok",
                metadata={},
                warnings=[],
                created_at="2026-07-02T12:00:00Z",
            ),
            SimpleNamespace(
                step_id="retrieve-1",
                run_id=run_id,
                step="retrieve",
                status="completed",
                input_summary="question",
                output_summary="papers",
                metadata={
                    "retrieval_id": "retrieval-1",
                    "papers": ["P1"],
                    "observability": {"source_call_count": 1},
                },
                warnings=[],
                created_at="2026-07-02T12:00:01Z",
            ),
            SimpleNamespace(
                step_id="audit-1",
                run_id=run_id,
                step="audit",
                status="completed",
                input_summary="draft",
                output_summary="audit",
                metadata={"claim_support_rate": 1.0},
                warnings=[],
                created_at="2026-07-02T12:00:02Z",
            ),
            SimpleNamespace(
                step_id="final-1",
                run_id=run_id,
                step="finalize",
                status="completed",
                input_summary="revise",
                output_summary="done",
                metadata={},
                warnings=[],
                created_at="2026-07-02T12:00:03Z",
            ),
        ],
    )

    trajectory = adapt_bio_agent_run_from_storage(storage, "run-1")

    assert trajectory.source_adapter == "bio_agent_workflow"
    assert trajectory.task.question == "Does alpha improve beta?"
    assert [step.action["type"] for step in trajectory.steps] == [
        "classify",
        "retrieve",
        "audit",
        "finalize",
    ]
    assert trajectory.steps[1].state_before is not None
    assert trajectory.steps[1].state_after is not None
    assert trajectory.steps[1].cost["source_call_count"] == 1.0
```

- [ ] **Step 2: Add failing belief fixture CLI test**

Append this to `tests/test_asv_cli.py`:

```python
def test_cli_evaluate_applies_belief_fixture(tmp_path) -> None:
    input_path = tmp_path / "sample.jsonl"
    output_dir = tmp_path / "out"
    fixture_path = tmp_path / "beliefs.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "task": {
                    "task_id": "task-1",
                    "question": "Does the evidence support alpha?",
                    "candidate_space": {
                        "candidates": [
                            {"id": "supported", "label": "A", "text": "supported"},
                            {"id": "refuted", "label": "B", "text": "refuted"},
                        ]
                    },
                },
                "steps": [
                    {
                        "step_id": "s1",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "observation": {"text": "trial found benefit"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fixture_path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "step_id": "s1",
                "belief_before": {"supported": 0.5, "refuted": 0.5},
                "belief_after": {"supported": 0.8, "refuted": 0.2},
            }
        )
        + "\n",
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
    assert summary["mean_realized_entropy_reduction"] > 0
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_adapters.py tests/test_asv_cli.py
```

Expected: FAIL with the old adapter returning only selected steps, and CLI reporting `unrecognized arguments: --belief-fixture`.

- [ ] **Step 4: Add belief fixture helpers and rich adapter**

Modify imports at the top of `asv_eval/adapters.py`:

```python
from dataclasses import replace
```

Add these functions after `load_standard_jsonl()`:

```python
def load_belief_fixture(path: Path) -> dict[tuple[str, str], dict[str, dict[str, float]]]:
    fixture: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            key = (str(payload["trajectory_id"]), str(payload["step_id"]))
            fixture[key] = {
                "belief_before": {
                    str(k): float(v)
                    for k, v in dict(payload["belief_before"]).items()
                },
                "belief_after": {
                    str(k): float(v)
                    for k, v in dict(payload["belief_after"]).items()
                },
            }
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid belief fixture: {exc}") from exc
    return fixture


def apply_belief_fixture(
    trajectories: list[TrajectoryRecord],
    fixture: dict[tuple[str, str], dict[str, dict[str, float]]],
) -> list[TrajectoryRecord]:
    updated: list[TrajectoryRecord] = []
    for trajectory in trajectories:
        steps: list[StepRecord] = []
        for step in trajectory.steps:
            beliefs = fixture.get((trajectory.trajectory_id, step.step_id))
            if beliefs is None:
                steps.append(step)
                continue
            steps.append(
                replace(
                    step,
                    belief_before=beliefs["belief_before"],
                    belief_after=beliefs["belief_after"],
                )
            )
        updated.append(replace(trajectory, steps=steps))
    return updated
```

Replace `adapt_bio_agent_run_from_storage()` with:

```python
def adapt_bio_agent_run_from_storage(storage: Any, run_id: str) -> TrajectoryRecord:
    from plugins.biomed_evidence.workflow.asv import trajectory_from_answer_run

    run = storage.get_answer_run(run_id)
    if run is None:
        raise ValueError(f"bio-agent run not found: {run_id}")
    question_getter = getattr(storage, "get_answer_run_question", None)
    question = (
        str(question_getter(run_id))
        if callable(question_getter) and question_getter(run_id)
        else getattr(run, "answer", "")[:240]
        or run_id
    )
    return trajectory_from_answer_run(
        run=run,
        question=question,
        trace=list(storage.list_agent_trace_steps(run_id)),
    )
```

- [ ] **Step 5: Add CLI belief fixture argument**

In `asv_eval/__main__.py`, import the new helpers:

```python
from asv_eval.adapters import (
    adapt_bio_agent_workspace,
    apply_belief_fixture,
    load_belief_fixture,
    load_standard_jsonl,
    react_transcript_to_trajectory,
)
```

In `_evaluate()`, change the trajectory loading block to:

```python
    trajectories = load_standard_jsonl(Path(args.input))
    if args.belief_fixture:
        trajectories = apply_belief_fixture(
            trajectories,
            load_belief_fixture(Path(args.belief_fixture)),
        )
```

In `_build_parser()`, add this argument to the `evaluate` parser:

```python
    evaluate.add_argument("--belief-fixture")
```

- [ ] **Step 6: Run adapter and CLI tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_adapters.py tests/test_asv_cli.py
```

Expected: `7 passed`.

- [ ] **Step 7: Commit Task 3**

```bash
git add asv_eval/adapters.py asv_eval/__main__.py \
  tests/test_asv_adapters.py tests/test_asv_cli.py
git commit -m "feat: enrich bio-agent asv adapter"
```

---

### Task 4: End-To-End ASV Export Smoke

**Files:**
- Modify: `tests/test_biomed_workflow_asv.py`

- [ ] **Step 1: Add failing end-to-end evaluation test**

Append this to `tests/test_biomed_workflow_asv.py`:

```python
import subprocess
import sys
from dataclasses import asdict


@pytest.mark.asyncio
async def test_exported_biomed_asv_trajectory_can_be_evaluated_with_fixture(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question=(
                    "What recent evidence links microglial activation to "
                    "Alzheimer's disease progression?"
                ),
                source="mock",
                max_papers=5,
            )
        )
        trajectory = service.export_answer_run_asv_trajectory(
            audited.answer_result.run_id
        )
    finally:
        await service.aclose()

    input_path = tmp_path / "biomed-asv.jsonl"
    fixture_path = tmp_path / "beliefs.jsonl"
    output_dir = tmp_path / "asv-report"
    input_path.write_text(
        json.dumps(asdict(trajectory), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fixture_rows = []
    for step in trajectory.steps:
        fixture_rows.append(
            {
                "trajectory_id": trajectory.trajectory_id,
                "step_id": step.step_id,
                "belief_before": {
                    "supported": 0.34,
                    "refuted": 0.33,
                    "not_enough_information": 0.33,
                },
                "belief_after": {
                    "supported": 0.70,
                    "refuted": 0.15,
                    "not_enough_information": 0.15,
                },
            }
        )
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
    assert summary["step_count"] == len(trajectory.steps)
    assert summary["mean_realized_entropy_reduction"] > 0
```

- [ ] **Step 2: Run the new end-to-end test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py
```

Expected: `5 passed`.

- [ ] **Step 3: Run focused ASV and biomedical test bundle**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py tests/test_asv_cli.py tests/test_biomed_workflow_asv.py
```

Expected: all tests pass.

- [ ] **Step 4: Run existing biomedical audit/API sanity tests**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_api.py::test_biomed_api_answer_extract_graph_and_audit
```

Expected: both tests pass.

- [ ] **Step 5: Run Python compile check**

Run:

```bash
.venv/bin/python -m py_compile \
  plugins/biomed_evidence/workflow/__init__.py \
  plugins/biomed_evidence/workflow/types.py \
  plugins/biomed_evidence/workflow/asv.py \
  plugins/biomed_evidence/storage.py \
  plugins/biomed_evidence/service.py \
  asv_eval/adapters.py \
  asv_eval/__main__.py
```

Expected: exit code `0`.

- [ ] **Step 6: Commit Task 4 if it added the end-to-end test**

```bash
git add tests/test_biomed_workflow_asv.py
git commit -m "test: cover biomed asv export smoke"
```

- [ ] **Step 7: Push branch**

```bash
git status --short --branch
git push
```

Expected: branch `codex/asv-eval-tool` pushes cleanly to `origin/codex/asv-eval-tool`.
