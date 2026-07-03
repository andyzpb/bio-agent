# Live ASV Measurement Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live PubMed ASV quick pilot paper-usable by carrying compact evidence facts through ASV states and adding finite oracle gold-label gain metrics.

**Architecture:** Keep the evaluator stateless over standard ASV JSONL. The biomedical workflow exporter deterministically projects compact facts from trace metadata into `state_after`; ASV core computes the validation-only oracle metric from existing belief distributions; reporting and live analysis expose the new metric without changing prompts or retrieval behavior.

**Tech Stack:** Python 3.11, pytest, existing `asv_eval` package, existing `plugins.biomed_evidence.workflow.asv` adapter, existing live PubMed experiment scripts.

---

## File Structure

- Modify `plugins/biomed_evidence/workflow/asv.py`: add deterministic compact `evidence_facts` projection from trace metadata and carry it forward through output states.
- Modify `asv_eval/core.py`: add epsilon-smoothed `oracle_gold_log_likelihood_gain` while preserving existing `gold_log_likelihood_gain`.
- Modify `asv_eval/reporting.py`: include `oracle_gold_log_likelihood_gain` in `tables/steps.csv`.
- Modify `eval/asv/live_pubmed/analyze.py`: aggregate oracle gold gain by step type.
- Modify `tests/test_biomed_workflow_asv.py`: prove evidence facts are compacted, redacted, and carried forward.
- Modify `tests/test_asv_eval.py`: prove zero-probability gold candidates get finite oracle gain while old gold gain remains `None`.
- Modify `tests/test_asv_live_pubmed_experiment.py`: prove analysis tables include oracle summary columns.
- Update `eval/asv/experiments/live_pubmed_step_value/results.quick.md`: record the repaired quick pilot results.

---

### Task 1: Compact Evidence Facts Tests

**Files:**
- Modify: `tests/test_biomed_workflow_asv.py`
- Later modify: `plugins/biomed_evidence/workflow/asv.py`

- [ ] **Step 1: Write the failing evidence projection test**

Add this test after `test_workflow_trace_step_projects_state_action_observation_and_cost`:

```python
def test_workflow_trace_step_carries_compact_evidence_facts_forward() -> None:
    long_fact = "A" * 650
    retrieve = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-retrieve",
            run_id="run-1",
            step="retrieve",
            status="completed",
            input_summary="Does APOE4 increase Alzheimer risk?",
            output_summary="evidence-packet-1",
            metadata={
                "evidence_packet": {
                    "supported_claims": [
                        "APOE epsilon4 is associated with increased Alzheimer risk.",
                        long_fact,
                    ],
                    "conflicting_claims": [
                        {"claim": "Effect differs by ancestry", "pmid": "123"}
                    ],
                    "coverage_gaps": ["No randomized intervention evidence."],
                    "api_key": "secret-should-not-leak",
                }
            },
            created_at="2026-07-02T12:00:00Z",
        ),
        state_before={
            "run_id": "run-1",
            "question": "Does APOE4 increase Alzheimer risk?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )
    audit = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-audit",
            run_id="run-1",
            step="audit",
            status="completed",
            input_summary="draft",
            output_summary="audit-1",
            metadata={
                "claim_support_rate": 1.0,
                "unsupported_claim_rate": 0.0,
                "overclaim_rate": 0.0,
                "recommended_action": "accept",
            },
            created_at="2026-07-02T12:00:01Z",
        ),
        state_before=retrieve.output_state,
    )

    facts = retrieve.output_state["evidence_facts"]
    assert facts["supported_claims"][0] == (
        "APOE epsilon4 is associated with increased Alzheimer risk."
    )
    assert len(facts["supported_claims"][1]) == 500
    assert facts["conflicting_claims"] == [
        '{"claim": "Effect differs by ancestry", "pmid": "123"}'
    ]
    assert facts["coverage_gaps"] == ["No randomized intervention evidence."]
    assert "secret-should-not-leak" not in json.dumps(facts, sort_keys=True)

    assert audit.input_state["evidence_facts"] == retrieve.output_state["evidence_facts"]
    assert audit.output_state["evidence_facts"]["audit"] == {
        "claim_support_rate": 1.0,
        "overclaim_rate": 0.0,
        "recommended_action": "accept",
        "unsupported_claim_rate": 0.0,
    }
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py::test_workflow_trace_step_carries_compact_evidence_facts_forward
```

Expected: FAIL with `KeyError: 'evidence_facts'`.

- [ ] **Step 3: Implement minimal compact facts projection**

In `plugins/biomed_evidence/workflow/asv.py`:

1. Add `import json`.
2. Add constants:

```python
_EVIDENCE_FACT_LIST_KEYS = (
    "supported_claims",
    "conflicting_claims",
    "coverage_gaps",
)
_EVIDENCE_FACT_AUDIT_KEYS = (
    "claim_support_rate",
    "overclaim_rate",
    "recommended_action",
    "unsupported_claim_rate",
)
_MAX_EVIDENCE_FACTS = 8
_MAX_EVIDENCE_FACT_CHARS = 500
```

3. Before `output_state = { ... }`, compute:

```python
evidence_facts = _evidence_facts_from_metadata(
    metadata,
    previous=state_before.get("evidence_facts"),
)
```

4. After `output_state = { ... }`, attach:

```python
if evidence_facts:
    output_state["evidence_facts"] = evidence_facts
```

5. Add helpers near `_artifact_ids_from_metadata`:

```python
def _evidence_facts_from_metadata(
    metadata: dict[str, Any],
    *,
    previous: Any,
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    if isinstance(previous, dict):
        for key in _EVIDENCE_FACT_LIST_KEYS:
            facts[key] = _compact_fact_list(previous.get(key))
        audit = previous.get("audit")
        if isinstance(audit, dict):
            facts["audit"] = dict(audit)

    packet = metadata.get("evidence_packet")
    if isinstance(packet, dict):
        for key in _EVIDENCE_FACT_LIST_KEYS:
            merged = [*facts.get(key, []), *_compact_fact_list(packet.get(key))]
            facts[key] = _dedupe_limited(merged)

    audit_metrics = {
        key: metadata[key]
        for key in _EVIDENCE_FACT_AUDIT_KEYS
        if key in metadata and metadata[key] is not None
    }
    if audit_metrics:
        facts["audit"] = {**facts.get("audit", {}), **audit_metrics}

    return {
        key: value
        for key, value in facts.items()
        if (isinstance(value, list) and value) or (isinstance(value, dict) and value)
    }


def _compact_fact_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_limited(_compact_fact(item) for item in value)


def _compact_fact(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return _redact_secret_strings(text)[:_MAX_EVIDENCE_FACT_CHARS]


def _dedupe_limited(values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
        if len(output) >= _MAX_EVIDENCE_FACTS:
            break
    return output
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_workflow_asv.py::test_workflow_trace_step_carries_compact_evidence_facts_forward
```

Expected: PASS.

---

### Task 2: Oracle Gold Gain Tests And Implementation

**Files:**
- Modify: `tests/test_asv_eval.py`
- Modify: `asv_eval/core.py`

- [ ] **Step 1: Write the failing oracle metric assertions**

In `test_evaluate_trajectory_computes_realized_entropy_reduction_and_gold_gain`, add:

```python
assert row["gold_metrics"]["oracle_gold_log_likelihood_gain"] == row[
    "gold_metrics"
]["gold_log_likelihood_gain"]
```

In `test_evaluate_trajectory_skips_gold_gain_for_zero_probability_gold`, change the `belief_after` for `supported` to `1.0` and `not_enough_information` to `0.0`, then add:

```python
assert row["gold_metrics"]["oracle_gold_log_likelihood_gain"] == round(
    math.log(1.0) - math.log(1e-12),
    6,
)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py::test_evaluate_trajectory_computes_realized_entropy_reduction_and_gold_gain tests/test_asv_eval.py::test_evaluate_trajectory_skips_gold_gain_for_zero_probability_gold
```

Expected: FAIL with missing `oracle_gold_log_likelihood_gain`.

- [ ] **Step 3: Implement minimal oracle metric**

In `asv_eval/core.py`, add module constant near imports/config constants:

```python
_GOLD_METRIC_EPSILON = 1e-12
```

In `evaluate_trajectory`, initialize `oracle_gold_gain = None` beside `gold_gain = None`. Inside the existing `if gold_id ...` block, compute:

```python
oracle_gold_gain = round(
    math.log(max(step.belief_after[gold_id], _GOLD_METRIC_EPSILON))
    - math.log(max(step.belief_before[gold_id], _GOLD_METRIC_EPSILON)),
    6,
)
```

Add it to `gold_metrics`:

```python
"oracle_gold_log_likelihood_gain": oracle_gold_gain,
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py::test_evaluate_trajectory_computes_realized_entropy_reduction_and_gold_gain tests/test_asv_eval.py::test_evaluate_trajectory_skips_gold_gain_for_zero_probability_gold
```

Expected: PASS.

---

### Task 3: Reporting And Analysis Columns

**Files:**
- Modify: `asv_eval/reporting.py`
- Modify: `eval/asv/live_pubmed/analyze.py`
- Modify: `tests/test_asv_live_pubmed_experiment.py`

- [ ] **Step 1: Write failing analysis tests**

Update gold metrics in `test_aggregate_step_type_rows_computes_mean_asv`:

```python
"gold_metrics": {
    "gold_log_likelihood_gain": 0.5,
    "oracle_gold_log_likelihood_gain": 2.0,
},
```

and for the second row:

```python
"gold_metrics": {
    "gold_log_likelihood_gain": None,
    "oracle_gold_log_likelihood_gain": 1.0,
},
```

Extend the expected summary with:

```python
"mean_oracle_gold_log_likelihood_gain": 1.5,
"oracle_gold_metric_step_count": 2,
"missing_oracle_gold_metric_step_count": 0,
```

In `test_write_analysis_tables_creates_csv_and_json`, set:

```python
"gold_metrics": {
    "gold_log_likelihood_gain": 0.0,
    "oracle_gold_log_likelihood_gain": 0.0,
},
```

and assert:

```python
assert "mean_oracle_gold_log_likelihood_gain" in csv_text
```

In `test_aggregate_step_type_rows_uses_null_when_all_gold_metrics_missing`, set:

```python
"gold_metrics": {
    "gold_log_likelihood_gain": None,
    "oracle_gold_log_likelihood_gain": None,
},
```

and assert:

```python
assert summary[0]["mean_oracle_gold_log_likelihood_gain"] is None
assert summary[0]["oracle_gold_metric_step_count"] == 0
assert summary[0]["missing_oracle_gold_metric_step_count"] == 1
```

- [ ] **Step 2: Run analysis tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_aggregate_step_type_rows_computes_mean_asv tests/test_asv_live_pubmed_experiment.py::test_write_analysis_tables_creates_csv_and_json tests/test_asv_live_pubmed_experiment.py::test_aggregate_step_type_rows_uses_null_when_all_gold_metrics_missing
```

Expected: FAIL because oracle summary keys are absent.

- [ ] **Step 3: Implement CSV and analysis fields**

In `asv_eval/reporting.py`, add `"oracle_gold_log_likelihood_gain"` after `"gold_log_likelihood_gain"` in `fields`, and add:

```python
"oracle_gold_log_likelihood_gain": row["gold_metrics"].get(
    "oracle_gold_log_likelihood_gain"
),
```

to the row writer.

In `eval/asv/live_pubmed/analyze.py`:

1. Replace `_has_numeric_gold_gain` with:

```python
def _numeric_gold_metric(row: dict[str, Any], key: str) -> float | None:
    metrics = row.get("gold_metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None
```

2. In `aggregate_step_type_rows`, compute:

```python
gold_values = [
    value
    for item in items
    if (value := _numeric_gold_metric(item, "gold_log_likelihood_gain")) is not None
]
oracle_gold_values = [
    value
    for item in items
    if (value := _numeric_gold_metric(item, "oracle_gold_log_likelihood_gain"))
    is not None
]
```

3. Add summary fields:

```python
"mean_oracle_gold_log_likelihood_gain": (
    _mean(oracle_gold_values) if oracle_gold_values else None
),
"oracle_gold_metric_step_count": len(oracle_gold_values),
"missing_oracle_gold_metric_step_count": len(items) - len(oracle_gold_values),
```

- [ ] **Step 4: Run analysis tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_aggregate_step_type_rows_computes_mean_asv tests/test_asv_live_pubmed_experiment.py::test_write_analysis_tables_creates_csv_and_json tests/test_asv_live_pubmed_experiment.py::test_aggregate_step_type_rows_uses_null_when_all_gold_metrics_missing
```

Expected: PASS.

---

### Task 4: Verification, Live Recheck, And Report

**Files:**
- Modify: `eval/asv/experiments/live_pubmed_step_value/results.quick.md`
- Do not commit raw `/tmp` artifacts.

- [ ] **Step 1: Run provider-free test bundle**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_runtime.py tests/test_biomed_workflow_asv.py tests/test_asv_live_pubmed_experiment.py
```

Expected: PASS.

- [ ] **Step 2: Run live quick collection**

Run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && .venv/bin/python -m eval.asv.live_pubmed.collect --claims eval/asv/experiments/live_pubmed_step_value/claims.quick.jsonl --workspace /tmp/asv-live-pubmed-step-value-quick-repair/workspace --output-dir /tmp/asv-live-pubmed-step-value-quick-repair/collection --ack-live'
```

Expected: three claims collected and `trajectory.jsonl` created under `/tmp/asv-live-pubmed-step-value-quick-repair/collection`.

- [ ] **Step 3: Run live DeepSeek evaluation**

Run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && .venv/bin/python -m eval.asv.live_pubmed.evaluate --input /tmp/asv-live-pubmed-step-value-quick-repair/collection/trajectory.jsonl --cache /tmp/asv-live-pubmed-step-value-quick-repair/deepseek-cache.jsonl --evaluated /tmp/asv-live-pubmed-step-value-quick-repair/evaluated.jsonl --output-dir /tmp/asv-live-pubmed-step-value-quick-repair/report'
```

Expected: `report/steps.jsonl`, `report/tables/steps.csv`, and ASV summaries generated with zero evaluator fallback states.

- [ ] **Step 4: Run analysis table generation**

Run:

```bash
.venv/bin/python -m eval.asv.live_pubmed.analyze --report-dir /tmp/asv-live-pubmed-step-value-quick-repair/report
```

Expected: `analysis_summary.json` and `tables/step_type_summary.csv` include `mean_oracle_gold_log_likelihood_gain`.

- [ ] **Step 5: Inspect acceptance metrics**

Run a short local inspection that checks:

```text
3 collected claims
33 evaluated steps
0 missing-label steps
0 floor-score steps
0 evaluator-fallback steps
APOE retrieve has oracle_gold_log_likelihood_gain > 0
no secret marker appears in committed report text
```

- [ ] **Step 6: Update quick results report**

Edit `eval/asv/experiments/live_pubmed_step_value/results.quick.md` with:

```text
- run path: /tmp/asv-live-pubmed-step-value-quick-repair
- compact evidence facts are present in exported ASV states
- oracle_gold_log_likelihood_gain is present in step rows and step-type summaries
- APOE retrieve oracle gain value
- caveat: PubMed retrieval and DeepSeek evaluator are live; actor classify/plan remains fallback until Phase 2
```

- [ ] **Step 7: Commit Phase 1 repair**

Run:

```bash
git add -f docs/superpowers/plans/2026-07-03-live-asv-measurement-repair.md
git add plugins/biomed_evidence/workflow/asv.py asv_eval/core.py asv_eval/reporting.py eval/asv/live_pubmed/analyze.py tests/test_biomed_workflow_asv.py tests/test_asv_eval.py tests/test_asv_live_pubmed_experiment.py eval/asv/experiments/live_pubmed_step_value/results.quick.md
git commit -m "feat: repair live asv measurement"
```

Expected: commit succeeds on branch `codex/asv-eval-tool`.

---

## Self-Review

- Spec coverage: compact evidence facts are covered by Task 1; finite oracle gold gain by Task 2; reporting/analysis columns by Task 3; quick pilot rerun and report update by Task 4.
- Non-goals preserved: no actor LLM integration, no DSPy, no retrieval behavior change, no UI, no raw provider artifacts committed.
- Placeholder scan: no `TBD`, `TODO`, or vague "handle edge cases" instructions remain.
- Type consistency: the new metric key is consistently `oracle_gold_log_likelihood_gain`; compact state key is consistently `evidence_facts`.
