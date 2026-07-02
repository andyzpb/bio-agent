# Live PubMed ASV Experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run the first paper-facing live PubMed ASV experiment harness for real LLM bio-agent step-value profiling.

**Architecture:** Add a focused `eval/asv/live_pubmed/` experiment package that reads a curated claim set, runs `BiomedEvidenceService.answer_with_audit(...)` with live PubMed and LLM flags, exports frozen ASV trajectories, evaluates them with existing ASV CLI/runtime, and aggregates paper-facing step-value tables. Keep production `answer_with_audit`, ASV core metrics, and stateless workflow code unchanged unless a focused test exposes a contract bug.

**Tech Stack:** Python 3.12, stdlib `argparse`/`asyncio`/`csv`/`json`, existing `BiomedEvidenceService`, existing `asv_eval` JSONL/evaluator/reporting modules, pytest, DeepSeek env via `zsh -ic`, PubMed via existing literature client.

---

## File Structure

- Create `eval/asv/live_pubmed/__init__.py`: package marker.
- Create `eval/asv/live_pubmed/claims.py`: curated claim schema, JSONL loader, and validation.
- Create `eval/asv/live_pubmed/collect.py`: live collection runner that executes audited answer runs and freezes ASV trajectories.
- Create `eval/asv/live_pubmed/evaluate.py`: wrapper around ASV evaluation for floor-score sensitivity and cache/secret checks.
- Create `eval/asv/live_pubmed/analyze.py`: report aggregation into paper-facing CSV/JSON summaries.
- Create `eval/asv/live_pubmed/robustness.py`: label permutation audit helpers for frozen trajectories.
- Create `eval/asv/live_pubmed/external.py`: public dataset row mapping for PubMedQA/BioASQ-style validation.
- Create `eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl`: 30-row curated claim set.
- Create `eval/asv/experiments/live_pubmed_step_value/README.md`: live experiment commands, artifact policy, and safety notes.
- Create `tests/test_asv_live_pubmed_experiment.py`: provider-free tests for claim validation, dry-run collection, evaluation wrappers, analysis, robustness, and secret/gold leakage guards.

---

### Task 1: Curated Claim Set And Loader

**Files:**
- Create: `eval/asv/live_pubmed/__init__.py`
- Create: `eval/asv/live_pubmed/claims.py`
- Create: `eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl`
- Create: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Write failing claim loader tests**

Create `tests/test_asv_live_pubmed_experiment.py` with:

```python
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
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_live_pubmed_claim_loader_reads_pilot_set
```

Expected: FAIL with `ModuleNotFoundError: No module named 'eval.asv.live_pubmed'`.

- [ ] **Step 3: Create the live PubMed experiment package marker**

Create `eval/asv/live_pubmed/__init__.py`:

```python
from __future__ import annotations
```

- [ ] **Step 4: Implement `claims.py`**

Create `eval/asv/live_pubmed/claims.py`:

```python
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
```

- [ ] **Step 5: Create the 30-row pilot claim set**

Create `eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl` exactly:

```jsonl
{"claim_id":"supported-apoe-ad-risk","question":"Does APOE e4 increase Alzheimer's disease risk?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"alzheimer_genetics","rationale":"Established genetic association."}
{"claim_id":"supported-trem2-ad-risk","question":"Are rare TREM2 variants associated with increased Alzheimer's disease risk?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"alzheimer_genetics","rationale":"Established risk association in human studies."}
{"claim_id":"supported-brca1-cancer-risk","question":"Do pathogenic BRCA1 variants increase breast and ovarian cancer risk?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"cancer_genetics","rationale":"Established hereditary cancer risk claim."}
{"claim_id":"supported-hpv-vaccine-precancer","question":"Does HPV vaccination reduce cervical precancer incidence?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"vaccines","rationale":"Supported by vaccine effectiveness and trial evidence."}
{"claim_id":"supported-hpylori-ulcer-recurrence","question":"Does Helicobacter pylori eradication reduce peptic ulcer recurrence?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"gastroenterology","rationale":"Established treatment effect."}
{"claim_id":"supported-pcsk9-ldl","question":"Do PCSK9 inhibitors reduce LDL cholesterol?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"cardiometabolic","rationale":"Established pharmacologic effect."}
{"claim_id":"supported-imatinib-cml","question":"Does imatinib improve outcomes in BCR-ABL positive chronic myeloid leukemia?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"oncology","rationale":"Established targeted therapy effect."}
{"claim_id":"supported-pd1-melanoma","question":"Do PD-1 inhibitors improve survival in metastatic melanoma?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"immuno_oncology","rationale":"Supported by randomized trial evidence."}
{"claim_id":"supported-cftr-modulator-cf","question":"Do CFTR modulators improve lung function in eligible cystic fibrosis patients?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"rare_disease","rationale":"Supported in genotype-eligible populations."}
{"claim_id":"supported-sglt2-heart-failure","question":"Do SGLT2 inhibitors reduce heart failure hospitalization risk in appropriate adult patients?","gold_label":"supported","source":"pubmed","max_papers":5,"topic":"cardiometabolic","rationale":"Supported by cardiovascular outcome trials."}
{"claim_id":"refuted-beta-carotene-smokers","question":"Does beta-carotene supplementation reduce lung cancer incidence in smokers?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"cancer_prevention","rationale":"Large trials found no reduction and possible harm in smokers."}
{"claim_id":"refuted-vitamin-e-prostate","question":"Does vitamin E supplementation prevent prostate cancer?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"cancer_prevention","rationale":"SELECT trial evidence refutes prevention claim."}
{"claim_id":"refuted-antibiotics-viral-uri","question":"Do antibiotics improve outcomes for uncomplicated viral upper respiratory infections?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"infectious_disease","rationale":"Antibiotics do not treat viral infections."}
{"claim_id":"refuted-donepezil-cures-ad","question":"Does donepezil cure Alzheimer's disease?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"neurology","rationale":"Symptomatic treatment does not cure disease."}
{"claim_id":"refuted-hcq-covid-mortality","question":"Does hydroxychloroquine reduce mortality in hospitalized COVID-19 patients?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"infectious_disease","rationale":"Randomized evidence did not support mortality benefit."}
{"claim_id":"refuted-vitamin-c-cures-cancer","question":"Does high-dose vitamin C cure metastatic cancer?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"oncology","rationale":"Cure claim is not supported by clinical evidence."}
{"claim_id":"refuted-hrt-coronary-prevention","question":"Does menopausal hormone therapy prevent coronary heart disease in postmenopausal women?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"cardiology","rationale":"Primary prevention claim was not supported by major trial evidence."}
{"claim_id":"refuted-arthroscopy-oa","question":"Does arthroscopic lavage reliably improve knee osteoarthritis outcomes compared with sham or optimized nonoperative care?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"orthopedics","rationale":"Controlled trials do not support reliable benefit for degenerative knee osteoarthritis."}
{"claim_id":"refuted-antioxidants-mortality","question":"Do antioxidant vitamin supplements reliably reduce all-cause mortality in adults?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"prevention","rationale":"Meta-analytic evidence does not support reliable mortality reduction."}
{"claim_id":"refuted-ivermectin-covid-mortality","question":"Does ivermectin reliably reduce mortality in unselected COVID-19 patients?","gold_label":"refuted","source":"pubmed","max_papers":5,"topic":"infectious_disease","rationale":"High-quality evidence does not support reliable mortality benefit."}
{"claim_id":"nei-microglia-sufficient-ad","question":"Is microglial activation alone sufficient to cause Alzheimer's disease progression in humans?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"neuroinflammation","rationale":"Mechanistic sufficiency in humans is not established."}
{"claim_id":"nei-blood-tau-mortality-screening","question":"Does blood-based tau screening reduce dementia mortality in asymptomatic adults?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"diagnostics","rationale":"Clinical outcome benefit from screening is not established."}
{"claim_id":"nei-taurine-brain-aging","question":"Does taurine supplementation slow human brain aging?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"aging","rationale":"Human brain-aging outcome evidence is insufficient."}
{"claim_id":"nei-fmt-parkinson-motor","question":"Does fecal microbiota transplantation reliably improve Parkinson's disease motor symptoms?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"microbiome","rationale":"Evidence remains preliminary and not definitive."}
{"claim_id":"nei-base-editing-hypercholesterolemia","question":"Is in vivo base editing proven safe long term for treating common hypercholesterolemia?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"gene_editing","rationale":"Long-term safety evidence is not established."}
{"claim_id":"nei-psilocybin-five-year-relapse","question":"Does a single psilocybin dose prevent depression relapse for five years?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"psychiatry","rationale":"Long-term relapse prevention claim is not established."}
{"claim_id":"nei-hrv-pancreatic-cancer","question":"Can wearable heart-rate variability reliably diagnose early pancreatic cancer?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"digital_biomarkers","rationale":"Diagnostic reliability for this claim is not established."}
{"claim_id":"nei-low-dose-lithium-ad-prevention","question":"Does low-dose lithium prevent Alzheimer's disease in the general older adult population?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"prevention","rationale":"Population prevention evidence is not definitive."}
{"claim_id":"nei-nad-boosters-longevity","question":"Do NAD boosters increase human lifespan?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"aging","rationale":"Human lifespan benefit is not established."}
{"claim_id":"nei-glp1-ad-prevention","question":"Do GLP-1 receptor agonists prevent Alzheimer's disease in non-diabetic adults?","gold_label":"not_enough_information","source":"pubmed","max_papers":5,"topic":"neurodegeneration","rationale":"Preventive causal evidence in this population is not established."}
```

- [ ] **Step 6: Run claim tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py
```

Expected: PASS for the four claim tests.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add \
  eval/asv/live_pubmed/__init__.py \
  eval/asv/live_pubmed/claims.py \
  eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl \
  tests/test_asv_live_pubmed_experiment.py
git commit -m "feat: add live pubmed asv claim set"
```

---

### Task 2: Live Collection Runner

**Files:**
- Create: `eval/asv/live_pubmed/collect.py`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Add failing dry-run collection tests**

Append to `tests/test_asv_live_pubmed_experiment.py`:

```python
from dataclasses import asdict

from asv_eval.core import Candidate, CandidateSpace, StepRecord, TaskRecord, TrajectoryRecord
from eval.asv.live_pubmed.collect import (
    CollectionConfig,
    CollectionRow,
    collect_claims,
    write_collection_outputs,
)


class FakeLiveCollectorService:
    def __init__(self, workspace: Path, **kwargs) -> None:
        self.workspace = Path(workspace)
        self.closed = False

    async def answer_with_audit(self, request):
        run_id = f"run-{request.question.split()[1].lower()}"
        return type(
            "Audited",
            (),
            {
                "answer_result": type("AnswerResult", (), {"run_id": run_id})(),
                "trace": [],
                "model_dump": lambda self, mode="json": {
                    "answer_result": {"run_id": run_id},
                    "trace": [],
                },
            },
        )()

    def export_answer_run_asv_trajectory(self, run_id: str) -> TrajectoryRecord:
        return TrajectoryRecord(
            trajectory_id=f"bio-agent-{run_id}",
            run_id=run_id,
            source_adapter="bio_agent_workflow",
            task=TaskRecord(
                task_id=run_id,
                question=f"Question for {run_id}",
                domain="biomedical",
                candidate_space=CandidateSpace(
                    candidates=[
                        Candidate(id="supported", label="A", text="supported"),
                        Candidate(id="refuted", label="B", text="refuted"),
                        Candidate(
                            id="not_enough_information",
                            label="C",
                            text="not enough information",
                        ),
                    ],
                    gold_candidate_id=None,
                ),
            ),
            steps=[
                StepRecord(
                    step_id="retrieve",
                    index=0,
                    action={"type": "retrieve"},
                    observation={"summary": "retrieved fake papers"},
                    state_before={"question": f"Question for {run_id}"},
                    state_after={
                        "question": f"Question for {run_id}",
                        "evidence": ["fake evidence"],
                    },
                    cost={"source_call_count": 1, "tool_calls": 1},
                )
            ],
        )

    async def aclose(self) -> None:
        self.closed = True


def test_collect_claims_dry_run_writes_frozen_trajectories(tmp_path: Path) -> None:
    claim = ClaimRecord(
        claim_id="supported-test",
        question="Does APOE e4 increase Alzheimer's disease risk?",
        gold_label="supported",
        source="pubmed",
        max_papers=3,
    )
    config = CollectionConfig(
        claims_path=tmp_path / "claims.jsonl",
        output_dir=tmp_path / "out",
        workspace=tmp_path / "workspace",
        limit=1,
        require_ack_live=True,
    )

    rows, trajectories = collect_claims.run_sync(
        [claim],
        config=config,
        service_factory=FakeLiveCollectorService,
    )

    assert [row.status for row in rows] == ["completed"]
    assert rows[0].claim_id == "supported-test"
    assert rows[0].gold_label == "supported"
    assert len(trajectories) == 1
    assert trajectories[0].task.candidate_space.gold_candidate_id == "supported"

    write_collection_outputs(config.output_dir, rows, trajectories)

    assert (config.output_dir / "collection.jsonl").exists()
    assert (config.output_dir / "trajectory.jsonl").exists()
    payload = json.loads(
        (config.output_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert payload["task"]["candidate_space"]["gold_candidate_id"] == "supported"
    assert payload["task"]["gold_visible_to_evaluator"] is False
    assert payload["task"]["gold_used_only_for_validation"] is True


def test_collection_row_records_failures_without_throwing() -> None:
    row = CollectionRow.failure(
        claim_id="claim-failed",
        gold_label="refuted",
        message="provider timeout",
    )

    assert row.status == "failed"
    assert row.error == "provider timeout"
    assert row.run_id is None
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_collect_claims_dry_run_writes_frozen_trajectories
```

Expected: FAIL with `ModuleNotFoundError` for `eval.asv.live_pubmed.collect`.

- [ ] **Step 3: Implement `collect.py`**

Create `eval/asv/live_pubmed/collect.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from asv_eval.adapters import write_standard_jsonl
from asv_eval.core import TrajectoryRecord
from eval.asv.live_pubmed.claims import ClaimRecord, load_claims_jsonl
from plugins.biomed_evidence.schemas import AnswerWithEvidenceRequest
from plugins.biomed_evidence.service import BiomedEvidenceService


@dataclass(frozen=True)
class CollectionConfig:
    claims_path: Path
    output_dir: Path
    workspace: Path
    limit: int | None = None
    require_ack_live: bool = True


@dataclass(frozen=True)
class CollectionRow:
    claim_id: str
    gold_label: str
    status: str
    run_id: str | None = None
    trajectory_id: str | None = None
    step_count: int = 0
    error: str | None = None

    @classmethod
    def completed(
        cls,
        *,
        claim: ClaimRecord,
        run_id: str,
        trajectory_id: str,
        step_count: int,
    ) -> "CollectionRow":
        return cls(
            claim_id=claim.claim_id,
            gold_label=claim.gold_label,
            status="completed",
            run_id=run_id,
            trajectory_id=trajectory_id,
            step_count=step_count,
        )

    @classmethod
    def failure(
        cls,
        *,
        claim_id: str,
        gold_label: str,
        message: str,
    ) -> "CollectionRow":
        return cls(
            claim_id=claim_id,
            gold_label=gold_label,
            status="failed",
            error=message,
        )


class collect_claims:
    @staticmethod
    def run_sync(
        claims: list[ClaimRecord],
        *,
        config: CollectionConfig,
        service_factory: Callable[..., Any] = BiomedEvidenceService,
    ) -> tuple[list[CollectionRow], list[TrajectoryRecord]]:
        return asyncio.run(
            collect_claims.run(
                claims,
                config=config,
                service_factory=service_factory,
            )
        )

    @staticmethod
    async def run(
        claims: list[ClaimRecord],
        *,
        config: CollectionConfig,
        service_factory: Callable[..., Any] = BiomedEvidenceService,
    ) -> tuple[list[CollectionRow], list[TrajectoryRecord]]:
        active_claims = claims[: config.limit] if config.limit else claims
        service = service_factory(
            config.workspace,
            allow_live_pubmed_tools=True,
        )
        rows: list[CollectionRow] = []
        trajectories: list[TrajectoryRecord] = []
        try:
            for claim in active_claims:
                try:
                    audited = await service.answer_with_audit(
                        AnswerWithEvidenceRequest(**claim.to_answer_request_payload())
                    )
                    run_id = audited.answer_result.run_id
                    trajectory = service.export_answer_run_asv_trajectory(run_id)
                    trajectory = _attach_gold_label(trajectory, claim.gold_label)
                    trajectories.append(trajectory)
                    rows.append(
                        CollectionRow.completed(
                            claim=claim,
                            run_id=run_id,
                            trajectory_id=trajectory.trajectory_id,
                            step_count=len(trajectory.steps),
                        )
                    )
                except Exception as exc:
                    rows.append(
                        CollectionRow.failure(
                            claim_id=claim.claim_id,
                            gold_label=claim.gold_label,
                            message=str(exc),
                        )
                    )
        finally:
            closer = getattr(service, "aclose", None)
            if callable(closer):
                await closer()
        return rows, trajectories


def _attach_gold_label(
    trajectory: TrajectoryRecord,
    gold_label: str,
) -> TrajectoryRecord:
    from dataclasses import replace

    task = trajectory.task
    candidate_space = replace(task.candidate_space, gold_candidate_id=gold_label)
    return replace(
        trajectory,
        task=replace(
            task,
            candidate_space=candidate_space,
            gold_visible_to_evaluator=False,
            gold_used_only_for_validation=True,
        ),
        metadata={
            **trajectory.metadata,
            "experiment": "live_pubmed_step_value",
        },
    )


def write_collection_outputs(
    output_dir: Path,
    rows: list[CollectionRow],
    trajectories: list[TrajectoryRecord],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "collection.jsonl").write_text(
        "".join(json.dumps(asdict(row), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    write_standard_jsonl(output_dir / "trajectory.jsonl", trajectories)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect live PubMed ASV trajectories.")
    parser.add_argument("--claims", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ack-live", action="store_true")
    args = parser.parse_args(argv)
    if not args.ack_live:
        parser.error("--ack-live is required because this command calls live PubMed and LLM providers")
    config = CollectionConfig(
        claims_path=Path(args.claims),
        output_dir=Path(args.output_dir),
        workspace=Path(args.workspace),
        limit=args.limit,
    )
    rows, trajectories = collect_claims.run_sync(
        load_claims_jsonl(config.claims_path),
        config=config,
    )
    write_collection_outputs(config.output_dir, rows, trajectories)
    completed = sum(row.status == "completed" for row in rows)
    print(
        f"collection_count={len(rows)} completed={completed} "
        f"trajectory_count={len(trajectories)} output_dir={config.output_dir}"
    )
    return 0 if trajectories else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run dry-run collection tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_collect_claims_dry_run_writes_frozen_trajectories tests/test_asv_live_pubmed_experiment.py::test_collection_row_records_failures_without_throwing
```

Expected: PASS.

- [ ] **Step 5: Run pyright for the live PubMed package**

Run:

```bash
.venv/bin/pyright --level error eval/asv/live_pubmed tests/test_asv_live_pubmed_experiment.py
```

Expected: `0 errors`.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add eval/asv/live_pubmed/collect.py tests/test_asv_live_pubmed_experiment.py
git commit -m "feat: collect live pubmed asv trajectories"
```

---

### Task 3: Evaluation Wrapper, Secret Scan, And Floor Sensitivity

**Files:**
- Modify: `asv_eval/__main__.py`
- Modify: `tests/test_asv_cli.py`
- Create: `eval/asv/live_pubmed/evaluate.py`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Add failing ASV CLI floor-score test**

Append to `tests/test_asv_cli.py`:

```python
def test_evaluate_accepts_floor_score_runtime_config(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    beliefs_path = tmp_path / "beliefs.jsonl"
    output_dir = tmp_path / "report"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "floor-score-cli",
                "task": {
                    "task_id": "floor-score-cli-task",
                    "question": "Does alpha improve beta?",
                    "candidate_space": {
                        "candidates": [
                            {"id": "supported", "label": "A", "text": "supported"},
                            {"id": "refuted", "label": "B", "text": "refuted"},
                            {
                                "id": "not_enough_information",
                                "label": "C",
                                "text": "not enough information",
                            },
                        ]
                    },
                },
                "steps": [
                    {
                        "step_id": "retrieve",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "observation": {"summary": "evidence"},
                        "state_before": {"question": "Does alpha improve beta?"},
                        "state_after": {"evidence": "alpha improved beta"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    beliefs_path.write_text(
        json.dumps(
            {
                "trajectory_id": "floor-score-cli",
                "step_id": "retrieve",
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
            str(beliefs_path),
            "--floor-score",
            "-15",
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluator"]["floor_score"] == -15.0
```

- [ ] **Step 2: Run the floor-score CLI test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_cli.py::test_evaluate_accepts_floor_score_runtime_config
```

Expected: FAIL because `--floor-score` is not accepted.

- [ ] **Step 3: Expose `--floor-score` in the ASV CLI**

Modify `asv_eval/__main__.py` in `_evaluate(...)`:

```python
    runtime_config = EvaluatorRuntimeConfig(
        mode=evaluator_mode,
        model=args.model,
        api_key_env=args.api_key_env,
        fallback_policy=args.fallback_policy,
        floor_score=args.floor_score,
        state_text_max_chars=args.state_text_max_chars,
    )
```

Modify `_build_parser()`:

```python
    evaluate.add_argument("--floor-score", type=float, default=-20.0)
```

- [ ] **Step 4: Run the floor-score CLI test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_cli.py::test_evaluate_accepts_floor_score_runtime_config
```

Expected: PASS.

- [ ] **Step 5: Add failing evaluation wrapper tests**

Append to `tests/test_asv_live_pubmed_experiment.py`:

```python
from eval.asv.live_pubmed.evaluate import (
    EvaluationRun,
    build_evaluate_command,
    scan_for_secret_markers,
)


def test_build_evaluate_command_uses_deepseek_cache_and_frozen_input(tmp_path: Path) -> None:
    run = EvaluationRun(
        input_path=tmp_path / "trajectory.jsonl",
        output_dir=tmp_path / "report",
        cache_path=tmp_path / "cache.jsonl",
        evaluated_path=tmp_path / "evaluated.jsonl",
        fallback_policy="floor",
        floor_score=-20.0,
    )

    command = build_evaluate_command(run)

    assert command[:4] == [".venv/bin/python", "-m", "asv_eval", "evaluate"]
    assert "--evaluator" in command
    assert "deepseek-chat-logprob" in command
    assert "--cache" in command
    assert str(run.cache_path) in command
    assert "--write-evaluated-trajectories" in command
    assert str(run.evaluated_path) in command
    assert "--fallback-policy" in command
    assert "floor" in command
    assert "--floor-score" in command
    assert "-20.0" in command


def test_secret_scan_allows_safe_env_var_name(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text('{"credential_env": "DEEPSEEK_API_KEY"}', encoding="utf-8")

    assert scan_for_secret_markers([path]) == []


def test_secret_scan_flags_raw_provider_payload(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"raw_provider_response": {"Authorization": "Bearer abc"}}', encoding="utf-8")

    assert scan_for_secret_markers([path]) == [
        f"raw_provider_response found in {path}",
        f"Authorization found in {path}",
        f"Bearer  found in {path}",
    ]
```

- [ ] **Step 6: Run wrapper tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_build_evaluate_command_uses_deepseek_cache_and_frozen_input
```

Expected: FAIL with `ModuleNotFoundError` for `eval.asv.live_pubmed.evaluate`.

- [ ] **Step 7: Implement `evaluate.py`**

Create `eval/asv/live_pubmed/evaluate.py`:

```python
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
            if marker in text:
                findings.append(f"{marker} found in {path}")
    return findings


def output_files_for_secret_scan(output_dir: Path, evaluated_path: Path, cache_path: Path) -> list[Path]:
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
```

- [ ] **Step 8: Run evaluation wrapper tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_build_evaluate_command_uses_deepseek_cache_and_frozen_input tests/test_asv_live_pubmed_experiment.py::test_secret_scan_allows_safe_env_var_name tests/test_asv_live_pubmed_experiment.py::test_secret_scan_flags_raw_provider_payload
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Run:

```bash
git add asv_eval/__main__.py tests/test_asv_cli.py eval/asv/live_pubmed/evaluate.py tests/test_asv_live_pubmed_experiment.py
git commit -m "feat: add live pubmed asv evaluation wrapper"
```

---

### Task 4: Paper-Facing Analysis Tables

**Files:**
- Create: `eval/asv/live_pubmed/analyze.py`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Add failing analysis tests**

Append to `tests/test_asv_live_pubmed_experiment.py`:

```python
from eval.asv.live_pubmed.analyze import (
    aggregate_step_type_rows,
    write_analysis_tables,
)


def test_aggregate_step_type_rows_computes_mean_asv() -> None:
    rows = [
        {
            "trajectory_id": "t1",
            "step_id": "retrieve",
            "asv_components": {
                "realized_entropy_reduction": 0.4,
                "net_asv": 0.3,
                "cost_scalar": 0.1,
            },
            "gold_metrics": {"gold_log_likelihood_gain": 0.5},
            "quality_flags": {"used_floor_score": False, "used_cache": True},
        },
        {
            "trajectory_id": "t2",
            "step_id": "retrieve",
            "asv_components": {
                "realized_entropy_reduction": 0.2,
                "net_asv": 0.1,
                "cost_scalar": 0.1,
            },
            "gold_metrics": {"gold_log_likelihood_gain": -0.1},
            "quality_flags": {"used_floor_score": True, "used_cache": False},
        },
    ]

    summary = aggregate_step_type_rows(rows)

    assert summary == [
        {
            "step_type": "retrieve",
            "count": 2,
            "mean_realized_entropy_reduction": 0.3,
            "mean_net_asv": 0.2,
            "mean_cost_scalar": 0.1,
            "mean_gold_log_likelihood_gain": 0.2,
            "floor_score_step_count": 1,
            "cache_hit_step_count": 1,
        }
    ]


def test_write_analysis_tables_creates_csv_and_json(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "trajectory_id": "t1",
                "step_id": "classify",
                "asv_components": {
                    "realized_entropy_reduction": 0.0,
                    "net_asv": 0.0,
                    "cost_scalar": 0.0,
                },
                "gold_metrics": {"gold_log_likelihood_gain": 0.0},
                "quality_flags": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    write_analysis_tables(report_dir)

    assert (report_dir / "tables" / "step_type_summary.csv").exists()
    assert (report_dir / "analysis_summary.json").exists()
```

- [ ] **Step 2: Run analysis tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_aggregate_step_type_rows_computes_mean_asv
```

Expected: FAIL with `ModuleNotFoundError` for `eval.asv.live_pubmed.analyze`.

- [ ] **Step 3: Implement `analyze.py`**

Create `eval/asv/live_pubmed/analyze.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_steps(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def aggregate_step_type_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["step_id"])].append(row)
    output: list[dict[str, Any]] = []
    for step_type in sorted(groups):
        items = groups[step_type]
        output.append(
            {
                "step_type": step_type,
                "count": len(items),
                "mean_realized_entropy_reduction": _mean(
                    float(item["asv_components"]["realized_entropy_reduction"]) for item in items
                ),
                "mean_net_asv": _mean(float(item["asv_components"]["net_asv"]) for item in items),
                "mean_cost_scalar": _mean(float(item["asv_components"]["cost_scalar"]) for item in items),
                "mean_gold_log_likelihood_gain": _mean(
                    float((item.get("gold_metrics") or {}).get("gold_log_likelihood_gain") or 0.0)
                    for item in items
                ),
                "floor_score_step_count": sum(
                    (item.get("quality_flags") or {}).get("used_floor_score") is True for item in items
                ),
                "cache_hit_step_count": sum(
                    (item.get("quality_flags") or {}).get("used_cache") is True for item in items
                ),
            }
        )
    return output


def write_analysis_tables(report_dir: Path) -> dict[str, Any]:
    rows = load_steps(report_dir / "steps.jsonl")
    summary = aggregate_step_type_rows(rows)
    tables_dir = report_dir / "tables"
    tables_dir.mkdir(exist_ok=True)
    csv_path = tables_dir / "step_type_summary.csv"
    fields = list(summary[0].keys()) if summary else ["step_type", "count"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)
    payload = {"step_type_summary": summary}
    (report_dir / "analysis_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _mean(values: Any) -> float:
    items = [float(value) for value in values]
    if not items:
        return 0.0
    return round(sum(items) / len(items), 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build live PubMed ASV analysis tables.")
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args(argv)
    write_analysis_tables(Path(args.report_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run analysis tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_aggregate_step_type_rows_computes_mean_asv tests/test_asv_live_pubmed_experiment.py::test_write_analysis_tables_creates_csv_and_json
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add eval/asv/live_pubmed/analyze.py tests/test_asv_live_pubmed_experiment.py
git commit -m "feat: summarize live pubmed asv reports"
```

---

### Task 5: Label Permutation Robustness Helper

**Files:**
- Create: `eval/asv/live_pubmed/robustness.py`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Add failing label permutation tests**

Append to `tests/test_asv_live_pubmed_experiment.py`:

```python
from asv_eval.adapters import write_standard_jsonl
from eval.asv.live_pubmed.robustness import (
    build_label_permuted_trajectories,
    summarize_permutation_stability,
)


def test_build_label_permuted_trajectories_rotates_candidate_labels() -> None:
    trajectory = TrajectoryRecord(
        trajectory_id="t1",
        task=TaskRecord(
            task_id="task-1",
            question="Does alpha improve beta?",
            candidate_space=CandidateSpace(
                candidates=[
                    Candidate(id="supported", label="A", text="supported"),
                    Candidate(id="refuted", label="B", text="refuted"),
                    Candidate(id="not_enough_information", label="C", text="not enough information"),
                ],
                gold_candidate_id="supported",
            ),
        ),
        steps=[],
    )

    permuted = build_label_permuted_trajectories([trajectory], permutation_count=3)

    assert [item.trajectory_id for item in permuted] == [
        "t1-permutation-0",
        "t1-permutation-1",
        "t1-permutation-2",
    ]
    assert [
        candidate.label
        for candidate in permuted[1].task.candidate_space.candidates
    ] == ["C", "A", "B"]


def test_summarize_permutation_stability_reads_reports(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "steps.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "trajectory_id": "t1-permutation-0",
                        "step_id": "retrieve",
                        "asv_components": {"net_asv": 0.2},
                    }
                ),
                json.dumps(
                    {
                        "trajectory_id": "t1-permutation-1",
                        "step_id": "retrieve",
                        "asv_components": {"net_asv": 0.1},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_permutation_stability(report_dir)

    assert summary == {
        "step_count": 2,
        "mean_net_asv": 0.15,
        "min_net_asv": 0.1,
        "max_net_asv": 0.2,
        "range_net_asv": 0.1,
    }
```

- [ ] **Step 2: Run robustness tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_build_label_permuted_trajectories_rotates_candidate_labels
```

Expected: FAIL with `ModuleNotFoundError` for `eval.asv.live_pubmed.robustness`.

- [ ] **Step 3: Implement `robustness.py`**

Create `eval/asv/live_pubmed/robustness.py`:

```python
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from asv_eval.adapters import load_standard_jsonl, write_standard_jsonl
from asv_eval.core import Candidate, CandidateSpace, TrajectoryRecord


def build_label_permuted_trajectories(
    trajectories: list[TrajectoryRecord],
    *,
    permutation_count: int,
) -> list[TrajectoryRecord]:
    output: list[TrajectoryRecord] = []
    for trajectory in trajectories:
        labels = [candidate.label for candidate in trajectory.task.candidate_space.candidates]
        for index in range(permutation_count):
            rotated = labels[-index:] + labels[:-index] if index else labels
            candidates = [
                Candidate(
                    id=candidate.id,
                    label=rotated[candidate_index],
                    text=candidate.text,
                    prior=candidate.prior,
                )
                for candidate_index, candidate in enumerate(
                    trajectory.task.candidate_space.candidates
                )
            ]
            candidate_space = CandidateSpace(
                candidates=candidates,
                gold_candidate_id=trajectory.task.candidate_space.gold_candidate_id,
                type=trajectory.task.candidate_space.type,
            )
            output.append(
                replace(
                    trajectory,
                    trajectory_id=f"{trajectory.trajectory_id}-permutation-{index}",
                    task=replace(trajectory.task, candidate_space=candidate_space),
                    metadata={
                        **trajectory.metadata,
                        "label_permutation_index": index,
                    },
                )
            )
    return output


def summarize_permutation_stability(report_dir: Path) -> dict[str, float | int]:
    values = [
        float(json.loads(line)["asv_components"]["net_asv"])
        for line in (report_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not values:
        return {
            "step_count": 0,
            "mean_net_asv": 0.0,
            "min_net_asv": 0.0,
            "max_net_asv": 0.0,
            "range_net_asv": 0.0,
        }
    return {
        "step_count": len(values),
        "mean_net_asv": round(sum(values) / len(values), 6),
        "min_net_asv": round(min(values), 6),
        "max_net_asv": round(max(values), 6),
        "range_net_asv": round(max(values) - min(values), 6),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build label-permutation ASV trajectories.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--permutations", type=int, default=3)
    args = parser.parse_args(argv)
    trajectories = load_standard_jsonl(Path(args.input))
    write_standard_jsonl(
        Path(args.output),
        build_label_permuted_trajectories(
            trajectories,
            permutation_count=max(1, int(args.permutations)),
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run robustness tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_build_label_permuted_trajectories_rotates_candidate_labels tests/test_asv_live_pubmed_experiment.py::test_summarize_permutation_stability_reads_reports
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add eval/asv/live_pubmed/robustness.py tests/test_asv_live_pubmed_experiment.py
git commit -m "feat: add live pubmed asv robustness helpers"
```

---

### Task 6: Public Dataset Validation Mapper

**Files:**
- Create: `eval/asv/live_pubmed/external.py`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Add failing public dataset mapper tests**

Append to `tests/test_asv_live_pubmed_experiment.py`:

```python
from eval.asv.live_pubmed.external import (
    load_public_validation_rows,
    public_row_to_claim,
)


def test_pubmedqa_rows_map_yes_no_maybe_to_asv_labels(tmp_path: Path) -> None:
    path = tmp_path / "pubmedqa.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "pqa-1",
                        "question": "Does treatment alpha improve beta?",
                        "final_decision": "yes",
                    }
                ),
                json.dumps(
                    {
                        "id": "pqa-2",
                        "question": "Does treatment gamma improve delta?",
                        "final_decision": "no",
                    }
                ),
                json.dumps(
                    {
                        "id": "pqa-3",
                        "question": "Does biomarker epsilon predict zeta?",
                        "final_decision": "maybe",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    claims = load_public_validation_rows(path, dataset="pubmedqa", max_papers=4)

    assert [claim.claim_id for claim in claims] == [
        "pubmedqa-pqa-1",
        "pubmedqa-pqa-2",
        "pubmedqa-pqa-3",
    ]
    assert [claim.gold_label for claim in claims] == [
        "supported",
        "refuted",
        "not_enough_information",
    ]
    assert all(claim.max_papers == 4 for claim in claims)


def test_bioasq_yes_no_rows_map_to_asv_labels() -> None:
    yes = public_row_to_claim(
        {
            "id": "bioasq-1",
            "body": "Does alpha improve beta?",
            "exact_answer": "yes",
        },
        dataset="bioasq",
    )
    no = public_row_to_claim(
        {
            "id": "bioasq-2",
            "body": "Does gamma improve delta?",
            "exact_answer": "no",
        },
        dataset="bioasq",
    )

    assert yes.gold_label == "supported"
    assert no.gold_label == "refuted"
    assert yes.question == "Does alpha improve beta?"


def test_public_validation_mapper_rejects_unknown_label() -> None:
    with pytest.raises(ValueError, match="unsupported pubmedqa label"):
        public_row_to_claim(
            {
                "id": "bad-label",
                "question": "Does alpha improve beta?",
                "final_decision": "unclear",
            },
            dataset="pubmedqa",
        )
```

- [ ] **Step 2: Run public mapper tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_pubmedqa_rows_map_yes_no_maybe_to_asv_labels
```

Expected: FAIL with `ModuleNotFoundError` for `eval.asv.live_pubmed.external`.

- [ ] **Step 3: Implement `external.py`**

Create `eval/asv/live_pubmed/external.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.asv.live_pubmed.claims import ClaimRecord


PUBMEDQA_LABEL_MAP = {
    "yes": "supported",
    "no": "refuted",
    "maybe": "not_enough_information",
}

BIOASQ_LABEL_MAP = {
    "yes": "supported",
    "no": "refuted",
}


def public_row_to_claim(
    row: dict[str, Any],
    *,
    dataset: str,
    max_papers: int = 5,
) -> ClaimRecord:
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
        if isinstance(exact_answer, list):
            raw_label = str(exact_answer[0] if exact_answer else "").strip().lower()
        else:
            raw_label = str(exact_answer or row.get("label") or "").strip().lower()
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
```

- [ ] **Step 4: Run public mapper tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_pubmedqa_rows_map_yes_no_maybe_to_asv_labels tests/test_asv_live_pubmed_experiment.py::test_bioasq_yes_no_rows_map_to_asv_labels tests/test_asv_live_pubmed_experiment.py::test_public_validation_mapper_rejects_unknown_label
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add eval/asv/live_pubmed/external.py tests/test_asv_live_pubmed_experiment.py
git commit -m "feat: map public biomedical qa rows to asv claims"
```

---

### Task 7: Controlled Calibration Gate

**Files:**
- No expected source changes unless verification exposes a bug.

- [ ] **Step 1: Run controlled stateless ASV calibration tests**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_stateless_workflow.py::test_stateless_classify_retrieve_slice_evaluates_with_provided_beliefs tests/test_asv_experiment_bundle.py::test_biomed_step_value_bundle_runs_with_provided_beliefs
```

Expected: PASS. This is the provider-free calibration anchor for Experiment 2: the same ASV math must produce known directionality on fixed belief fixtures before live LLM evaluator results are trusted.

- [ ] **Step 2: Run controlled ASV CLI fixture test**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_cli.py::test_evaluate_accepts_floor_score_runtime_config
```

Expected: PASS and the generated `summary.json` records the configured `floor_score`.

- [ ] **Step 3: Commit only if calibration exposes a fix**

If a code fix was required, commit it:

```bash
git add asv_eval eval/asv tests
git commit -m "fix: preserve controlled asv calibration"
```

If no fix was needed, do not create a verification-only commit.

---

### Task 8: Experiment README And Secret Safety Tests

**Files:**
- Create: `eval/asv/experiments/live_pubmed_step_value/README.md`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Add failing README safety tests**

Append to `tests/test_asv_live_pubmed_experiment.py`:

```python
LIVE_EXPERIMENT_DIR = ROOT / "eval" / "asv" / "experiments" / "live_pubmed_step_value"


def test_live_pubmed_experiment_readme_documents_real_run_commands() -> None:
    readme = (LIVE_EXPERIMENT_DIR / "README.md").read_text(encoding="utf-8")

    assert "Live PubMed Step Value Experiment" in readme
    assert "--ack-live" in readme
    assert "answer_with_audit" in readme
    assert "deepseek-chat-logprob" in readme
    assert "claims.pilot.jsonl" in readme
    assert "/tmp/asv-live-pubmed-step-value" in readme
    assert "gold labels are used only after belief estimation" in readme


def test_live_pubmed_experiment_committed_files_are_secret_safe() -> None:
    for path in LIVE_EXPERIMENT_DIR.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in SECRET_MARKERS:
            assert marker not in text, f"{marker!r} leaked in {path}"
```

- [ ] **Step 2: Run README tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_live_pubmed_experiment_readme_documents_real_run_commands
```

Expected: FAIL with `FileNotFoundError` for the README.

- [ ] **Step 3: Create README**

Create `eval/asv/experiments/live_pubmed_step_value/README.md`:

```markdown
# Live PubMed Step Value Experiment

This experiment is the paper-facing ASV live-agent study. It runs the real
biomedical evidence workflow with live PubMed retrieval, freezes ASV
trajectories, and evaluates step value with the DeepSeek chat-logprob evaluator.

gold labels are used only after belief estimation. They must not appear in
evaluator prompts.

## Claim Set

`claims.pilot.jsonl` contains 30 curated biomedical claim-verification questions
balanced across:

- `supported`
- `refuted`
- `not_enough_information`

## Live Collection

Run only on a machine with provider credentials configured through the shell.
The command writes artifacts under `/tmp` so live provider outputs are not
committed by accident.

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.collect \
    --claims eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl \
    --workspace /tmp/asv-live-pubmed-step-value/workspace \
    --output-dir /tmp/asv-live-pubmed-step-value/collection \
    --limit 3 \
    --ack-live'
```

The collector calls `answer_with_audit` with live PubMed source and LLM workflow
flags enabled.

## LLM ASV Evaluation

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.evaluate \
    --input /tmp/asv-live-pubmed-step-value/collection/trajectory.jsonl \
    --cache /tmp/asv-live-pubmed-step-value/deepseek-cache.jsonl \
    --evaluated /tmp/asv-live-pubmed-step-value/evaluated.jsonl \
    --output-dir /tmp/asv-live-pubmed-step-value/report'
```

The evaluator uses `deepseek-chat-logprob` through the existing ASV runtime.

## Analysis Tables

```bash
.venv/bin/python -m eval.asv.live_pubmed.analyze \
  --report-dir /tmp/asv-live-pubmed-step-value/report
```

## Label Permutation Audit

```bash
.venv/bin/python -m eval.asv.live_pubmed.robustness \
  --input /tmp/asv-live-pubmed-step-value/collection/trajectory.jsonl \
  --output /tmp/asv-live-pubmed-step-value/permuted-trajectories.jsonl \
  --permutations 3
```

Evaluate the permuted trajectories with the same evaluator command and compare
ASV stability across permutations.
```

- [ ] **Step 4: Run README tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_live_pubmed_experiment_readme_documents_real_run_commands tests/test_asv_live_pubmed_experiment.py::test_live_pubmed_experiment_committed_files_are_secret_safe
```

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

Run:

```bash
git add eval/asv/experiments/live_pubmed_step_value/README.md tests/test_asv_live_pubmed_experiment.py
git commit -m "docs: add live pubmed asv experiment commands"
```

---

### Task 9: Provider-Free Closeout Gates

**Files:**
- No expected source changes unless verification exposes a bug.

- [ ] **Step 1: Run live PubMed experiment unit tests**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py
```

Expected: PASS.

- [ ] **Step 2: Run ASV regression suite**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py tests/test_asv_cli.py tests/test_asv_runtime.py tests/test_asv_experiment_bundle.py tests/test_biomed_workflow_asv.py tests/test_biomed_stateless_workflow.py tests/test_asv_live_pubmed_experiment.py
```

Expected: PASS.

- [ ] **Step 3: Run key biomed regressions**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_evidence.py::test_trace_answer_run_uses_latest_revision_as_display_answer tests/test_biomed_api.py::test_biomed_api_answer_extract_graph_and_audit
```

Expected: PASS.

- [ ] **Step 4: Run compile and whitespace checks**

Run:

```bash
.venv/bin/python -m py_compile \
  eval/asv/live_pubmed/__init__.py \
  eval/asv/live_pubmed/claims.py \
  eval/asv/live_pubmed/collect.py \
  eval/asv/live_pubmed/evaluate.py \
  eval/asv/live_pubmed/analyze.py \
  eval/asv/live_pubmed/robustness.py \
  eval/asv/live_pubmed/external.py \
  tests/test_asv_live_pubmed_experiment.py
git diff --check
```

Expected: both commands exit `0`.

- [ ] **Step 5: Run focused pyright**

Run:

```bash
.venv/bin/pyright --level error eval/asv/live_pubmed tests/test_asv_live_pubmed_experiment.py
```

Expected: `0 errors`.

- [ ] **Step 6: Commit only if verification required fixes**

If a fix was needed, commit it:

```bash
git add eval/asv/live_pubmed tests/test_asv_live_pubmed_experiment.py
git commit -m "fix: harden live pubmed asv experiment harness"
```

If no fix was needed, do not create a verification-only commit.

---

### Task 10: Live Pilot Experiment Run

**Files:**
- No committed source changes.
- Live artifacts are written under `/tmp/asv-live-pubmed-step-value`.

- [ ] **Step 1: Confirm credentials are available without printing them**

Run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && test -n "${DEEPSEEK_API_KEY:-}" && echo deepseek_key=present'
```

Expected: `deepseek_key=present`.

- [ ] **Step 2: Run a 3-claim live collection pilot**

Run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  rm -rf /tmp/asv-live-pubmed-step-value && \
  .venv/bin/python -m eval.asv.live_pubmed.collect \
    --claims eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl \
    --workspace /tmp/asv-live-pubmed-step-value/workspace \
    --output-dir /tmp/asv-live-pubmed-step-value/collection \
    --limit 3 \
    --ack-live'
```

Expected: command exits `0` and prints `trajectory_count=3`.

- [ ] **Step 3: Run DeepSeek ASV evaluation on frozen pilot trajectories**

Run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.evaluate \
    --input /tmp/asv-live-pubmed-step-value/collection/trajectory.jsonl \
    --cache /tmp/asv-live-pubmed-step-value/deepseek-cache.jsonl \
    --evaluated /tmp/asv-live-pubmed-step-value/evaluated.jsonl \
    --output-dir /tmp/asv-live-pubmed-step-value/report'
```

Expected: command exits `0`, report summary exists, and no secret scan findings print.

- [ ] **Step 4: Build analysis tables**

Run:

```bash
cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.analyze \
    --report-dir /tmp/asv-live-pubmed-step-value/report
```

Expected: `/tmp/asv-live-pubmed-step-value/report/tables/step_type_summary.csv` exists.

- [ ] **Step 5: Build label permutation pilot trajectories**

Run:

```bash
cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.robustness \
    --input /tmp/asv-live-pubmed-step-value/collection/trajectory.jsonl \
    --output /tmp/asv-live-pubmed-step-value/permuted-trajectories.jsonl \
    --permutations 3
```

Expected: command exits `0` and the output JSONL has 9 trajectories for a 3-claim pilot.

- [ ] **Step 6: Report pilot facts**

Summarize these facts in the final response:

```text
collection rows completed/failed
trajectory count
step count
mean realized entropy reduction
mean net ASV
floor-score step count
missing-label step count
cache-hit state count
path to step_type_summary.csv
```

Do not paste raw provider responses or API keys.
