# Live ASV Real Actor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing live PubMed ASV collector with a real LLM-backed bio-agent actor and record actor-mode coverage separately from evaluator coverage.

**Architecture:** Keep the existing `BiomedEvidenceService` actor stack. The collector optionally builds a `revision_provider` from an environment-backed DeepSeek-compatible provider and passes it into the existing service constructor; collection output adds a small actor coverage summary derived from existing trace metadata.

**Tech Stack:** Python 3.11, pytest, existing `agent.provider.LLMProvider`, existing `BiomedEvidenceService`, existing live PubMed ASV scripts.

---

## File Structure

- Modify `eval/asv/live_pubmed/collect.py`: add actor provider CLI/config fields, pass provider/model into `BiomedEvidenceService`, and write `collection_summary.json`.
- Modify `tests/test_asv_live_pubmed_experiment.py`: add focused tests for provider wiring and actor coverage summary.
- Modify `eval/asv/experiments/live_pubmed_step_value/README.md`: document the actor-provider quick command.
- Modify `eval/asv/experiments/live_pubmed_step_value/results.quick.md`: update after the real-actor quick pilot.

---

### Task 1: Actor Provider Wiring

**Files:**
- Modify: `tests/test_asv_live_pubmed_experiment.py`
- Modify: `eval/asv/live_pubmed/collect.py`

- [ ] **Step 1: Write failing provider-wiring test**

Add a fake service that records constructor kwargs, then assert `collect_claims` forwards `revision_provider`, `revision_model`, and `allow_live_pubmed_tools=True`.

- [ ] **Step 2: Run focused test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_collect_claims_passes_actor_provider_to_service
```

Expected: FAIL because `CollectionConfig` has no actor provider fields.

- [ ] **Step 3: Implement minimal wiring**

Add optional fields to `CollectionConfig`:

```python
actor_provider: Any | None = None
actor_model: str | None = None
actor_provider_name: str | None = None
```

Pass them into the service constructor as:

```python
revision_provider=config.actor_provider,
revision_model=config.actor_model,
allow_live_pubmed_tools=True,
```

- [ ] **Step 4: Run focused test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_collect_claims_passes_actor_provider_to_service
```

Expected: PASS.

---

### Task 2: Actor Coverage Summary

**Files:**
- Modify: `tests/test_asv_live_pubmed_experiment.py`
- Modify: `eval/asv/live_pubmed/collect.py`

- [ ] **Step 1: Write failing coverage summary tests**

Add a test that writes one trajectory with trace metadata containing:

```python
classification.classifier_mode = "llm"
query_plan.planner_mode = "llm"
synthesis_mode = "llm"
verifier_mode = "fallback"
revision_mode = "llm"
logic_audit.parser_mode_counts = {"llm": 1}
```

Assert `collection_summary.json` contains separate `actor` coverage with counts for those modes.

- [ ] **Step 2: Run focused test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_write_collection_outputs_records_actor_mode_coverage
```

Expected: FAIL because no collection summary is written.

- [ ] **Step 3: Implement minimal summary**

Add `summarize_actor_coverage(trajectories, actor_provider_name, actor_model)` that walks `step.observation["metadata"]` and counts:

- classifier modes from `classification.classifier_mode`
- planner modes from `query_plan.planner_mode`
- synthesis modes from `synthesis_mode`
- verifier modes from `verifier_mode`
- revision modes from `revision_mode`
- claim logic parser modes from `logic_audit.parser_mode_counts`

Write it in `write_collection_outputs` as `collection_summary.json`.

- [ ] **Step 4: Run focused test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py::test_write_collection_outputs_records_actor_mode_coverage
```

Expected: PASS.

---

### Task 3: CLI, Docs, Live Rerun

**Files:**
- Modify: `eval/asv/live_pubmed/collect.py`
- Modify: `eval/asv/experiments/live_pubmed_step_value/README.md`
- Modify: `eval/asv/experiments/live_pubmed_step_value/results.quick.md`

- [ ] **Step 1: Add CLI env-backed provider options**

Add collector options:

```text
--actor-provider deepseek
--actor-model deepseek-v4-flash
--actor-api-key-env DEEPSEEK_API_KEY
--actor-base-url https://api.deepseek.com/v1
```

Build `LLMProvider` only when `--actor-provider` is set. Read the key from the named env var and fail with `parser.error` if missing.

- [ ] **Step 2: Update README command**

Document the quick command with actor provider flags and keep the old no-actor command as fallback-free baseline.

- [ ] **Step 3: Run provider-free tests**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_live_pubmed_experiment.py tests/test_asv_eval.py tests/test_biomed_workflow_asv.py
```

Expected: PASS.

- [ ] **Step 4: Run real actor quick pilot**

Run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && .venv/bin/python -m eval.asv.live_pubmed.collect --claims eval/asv/experiments/live_pubmed_step_value/claims.quick.jsonl --workspace /tmp/asv-live-pubmed-step-value-real-actor-20260703/workspace --output-dir /tmp/asv-live-pubmed-step-value-real-actor-20260703/collection --actor-provider deepseek --actor-model deepseek-v4-flash --actor-api-key-env DEEPSEEK_API_KEY --actor-base-url https://api.deepseek.com/v1 --ack-live'
```

Then evaluate with `deepseek-chat` as before and run analysis.

- [ ] **Step 5: Update report and commit**

Update `results.quick.md` with actor coverage and evaluator coverage. Commit:

```bash
git add -f docs/superpowers/plans/2026-07-03-live-asv-real-actor.md
git add eval/asv/live_pubmed/collect.py tests/test_asv_live_pubmed_experiment.py eval/asv/experiments/live_pubmed_step_value/README.md eval/asv/experiments/live_pubmed_step_value/results.quick.md
git commit -m "feat: run live asv with llm actor"
```

---

## Self-Review

- Spec coverage: provider/model path is in Task 1/3; actor-mode coverage is in Task 2; live rerun and report separation are in Task 3.
- Non-goals preserved: no DSPy, no new provider abstraction, no PubMed retrieval behavior change, no service rewrite, no raw `/tmp` artifacts committed.
- Placeholder scan: no `TBD` or open-ended steps remain.
