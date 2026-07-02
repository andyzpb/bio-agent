# ASV Phase 1 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-free ASV biomedical step-value experiment bundle and a secret-safe optional DeepSeek live smoke path that closes Phase 1 without adding new evaluator modes.

**Architecture:** Keep CI and unit tests offline by committing a small `provided-belief` experiment bundle under `eval/asv/experiments/biomed_step_value_smoke/`. Add tests that run the bundle through the existing ASV CLI, scan committed experiment files for secret-like content, and verify the live DeepSeek smoke documentation/script is safe and reproducible. Live DeepSeek execution remains manual and writes only to `/tmp`.

**Tech Stack:** Python 3.12, existing `asv_eval` CLI/runtime/reporting modules, pytest, stdlib JSON/path/subprocess, shell script for optional local smoke.

---

## File Structure

- Create `eval/asv/experiments/biomed_step_value_smoke/README.md`: offline and live commands, expected outputs, no-secret guidance.
- Create `eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl`: one provider-free ASV trajectory with three biomedical workflow-style steps.
- Create `eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl`: provided beliefs for every step in the trajectory.
- Create `eval/asv/experiments/biomed_step_value_smoke/expected_summary.provided_belief.json`: deterministic summary values for the offline path.
- Create `eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh`: optional live smoke helper that runs twice with the same cache under `/tmp`.
- Create `tests/test_asv_experiment_bundle.py`: tests the offline bundle, summary expectations, secret scanning, and live smoke script safety.

---

### Task 1: Provider-Free Experiment Bundle

**Files:**
- Create: `eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl`
- Create: `eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl`
- Create: `eval/asv/experiments/biomed_step_value_smoke/expected_summary.provided_belief.json`
- Create: `tests/test_asv_experiment_bundle.py`

- [ ] **Step 1: Write failing bundle path and CLI test**

Create `tests/test_asv_experiment_bundle.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "eval" / "asv" / "experiments" / "biomed_step_value_smoke"
TRAJECTORY_PATH = EXPERIMENT_DIR / "trajectory.jsonl"
BELIEFS_PATH = EXPERIMENT_DIR / "beliefs.jsonl"
EXPECTED_SUMMARY_PATH = EXPERIMENT_DIR / "expected_summary.provided_belief.json"


def test_biomed_step_value_bundle_runs_with_provided_beliefs(tmp_path) -> None:
    output_dir = tmp_path / "provided-report"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(TRAJECTORY_PATH),
            "--belief-fixture",
            str(BELIEFS_PATH),
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
    expected = json.loads(EXPECTED_SUMMARY_PATH.read_text(encoding="utf-8"))
    for key, value in expected.items():
        assert summary[key] == value
    assert summary["evaluator"]["mode"] == "provided-belief"
    assert summary["evaluator_coverage"]["evaluated_state_count"] == 6

    steps = [
        json.loads(line)
        for line in (output_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["step_id"] for row in steps] == [
        "classify",
        "retrieve",
        "synthesize",
    ]
    assert steps[1]["asv_components"]["realized_entropy_reduction"] > 0
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_experiment_bundle.py::test_biomed_step_value_bundle_runs_with_provided_beliefs
```

Expected: FAIL with `No such file or directory` for `trajectory.jsonl` or `expected_summary.provided_belief.json`.

- [ ] **Step 3: Create `trajectory.jsonl`**

Create `eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl` with this single JSONL line:

```json
{"metadata":{"experiment":"biomed_step_value_smoke","notes":"Synthetic provider-free ASV smoke fixture."},"run_id":"biomed-smoke-run-001","schema_version":"asv.v1","source_adapter":"standard_jsonl","task":{"candidate_space":{"candidates":[{"id":"supported","label":"A","prior":null,"text":"supported"},{"id":"refuted","label":"B","prior":null,"text":"refuted"},{"id":"not_enough_information","label":"C","prior":null,"text":"not enough information"}],"gold_candidate_id":"supported","type":"closed_set"},"difficulty":"smoke","domain":"biomedical","gold_used_only_for_validation":true,"gold_visible_to_evaluator":false,"question":"Does the synthetic evidence support that alpha improves beta?","task_id":"biomed-smoke-task-001","task_type":"closed_set_qa"},"trajectory_id":"biomed-smoke-trajectory-001","steps":[{"action":{"policy":"provider_free_fixture","type":"classify"},"cost":{"llm_call_count":0,"prompt_tokens":0,"source_call_count":0,"tool_calls":0},"index":0,"observation":{"classification":"research","summary":"The request is a bounded biomedical evidence question."},"state_after":{"available_artifacts":[],"completed_steps":["classify"],"question":"Does the synthetic evidence support that alpha improves beta?","request_type":"research"},"state_before":{"available_artifacts":[],"completed_steps":[],"question":"Does the synthetic evidence support that alpha improves beta?"},"step_id":"classify"},{"action":{"query":"alpha beta synthetic controlled trial","source_mode":"mock","type":"retrieve"},"cost":{"artifact_cache_hit_count":0,"llm_call_count":0,"source_call_count":1,"tool_calls":1},"index":1,"observation":{"retrieval_id":"retrieval-smoke-001","summary":"One synthetic abstract reports improved beta outcomes after alpha."},"state_after":{"available_artifacts":["retrieval_id:retrieval-smoke-001"],"completed_steps":["classify","retrieve"],"evidence":["Synthetic Study A: alpha group improved beta outcome compared with control."],"question":"Does the synthetic evidence support that alpha improves beta?","request_type":"research"},"state_before":{"available_artifacts":[],"completed_steps":["classify"],"question":"Does the synthetic evidence support that alpha improves beta?","request_type":"research"},"step_id":"retrieve"},{"action":{"mode":"synthetic_summary","type":"synthesize"},"cost":{"completion_tokens":80,"llm_call_count":1,"prompt_tokens":240,"tool_calls":1},"index":2,"observation":{"summary":"The synthetic evidence supports the claim with one directly relevant study."},"state_after":{"answer_status":"supported","available_artifacts":["retrieval_id:retrieval-smoke-001","answer:draft-smoke-001"],"completed_steps":["classify","retrieve","synthesize"],"evidence":["Synthetic Study A: alpha group improved beta outcome compared with control."],"question":"Does the synthetic evidence support that alpha improves beta?","request_type":"research"},"state_before":{"available_artifacts":["retrieval_id:retrieval-smoke-001"],"completed_steps":["classify","retrieve"],"evidence":["Synthetic Study A: alpha group improved beta outcome compared with control."],"question":"Does the synthetic evidence support that alpha improves beta?","request_type":"research"},"step_id":"synthesize"}],"success":true}
```

- [ ] **Step 4: Create `beliefs.jsonl`**

Create `eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl`:

```jsonl
{"trajectory_id":"biomed-smoke-trajectory-001","step_id":"classify","belief_before":{"supported":0.34,"refuted":0.33,"not_enough_information":0.33},"belief_after":{"supported":0.36,"refuted":0.31,"not_enough_information":0.33}}
{"trajectory_id":"biomed-smoke-trajectory-001","step_id":"retrieve","belief_before":{"supported":0.36,"refuted":0.31,"not_enough_information":0.33},"belief_after":{"supported":0.78,"refuted":0.08,"not_enough_information":0.14}}
{"trajectory_id":"biomed-smoke-trajectory-001","step_id":"synthesize","belief_before":{"supported":0.78,"refuted":0.08,"not_enough_information":0.14},"belief_after":{"supported":0.88,"refuted":0.04,"not_enough_information":0.08}}
```

- [ ] **Step 5: Generate expected summary from the CLI**

Run:

```bash
tmp_dir="$(mktemp -d /tmp/asv-biomed-provided.XXXXXX)"
.venv/bin/python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --belief-fixture eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl \
  --output-dir "$tmp_dir"
cat "$tmp_dir/summary.json"
```

Expected: command exits `0` and prints a summary with `trajectory_count=1` and `step_count=3`.

Create `eval/asv/experiments/biomed_step_value_smoke/expected_summary.provided_belief.json` from the printed values, keeping only these deterministic keys:

```json
{
  "trajectory_count": 1,
  "step_count": 3,
  "source_adapters": [
    "standard_jsonl"
  ],
  "positive_net_asv_steps": 3,
  "negative_net_asv_steps": 0,
  "zero_net_asv_steps": 0
}
```

If the generated `positive_net_asv_steps`, `negative_net_asv_steps`, or `zero_net_asv_steps` differ, stop and inspect the belief fixture. The fixture above is intended to produce three positive entropy reductions.

- [ ] **Step 6: Run the bundle test and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_experiment_bundle.py::test_biomed_step_value_bundle_runs_with_provided_beliefs
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add \
  eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl \
  eval/asv/experiments/biomed_step_value_smoke/expected_summary.provided_belief.json \
  tests/test_asv_experiment_bundle.py
git commit -m "test: add asv biomed smoke experiment bundle"
```

---

### Task 2: Secret Scan And Live Smoke Documentation

**Files:**
- Create: `eval/asv/experiments/biomed_step_value_smoke/README.md`
- Create: `eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh`
- Modify: `tests/test_asv_experiment_bundle.py`

- [ ] **Step 1: Add failing secret scan and documentation tests**

Append to `tests/test_asv_experiment_bundle.py`:

```python
SECRET_MARKERS = (
    "Bearer ",
    "api_key",
    "password",
    "token=",
    "raw_provider_response",
    "sk-live",
    "provider raw secret",
)


def test_biomed_step_value_bundle_contains_no_secret_markers() -> None:
    checked_paths = [
        EXPERIMENT_DIR / "trajectory.jsonl",
        EXPERIMENT_DIR / "beliefs.jsonl",
        EXPERIMENT_DIR / "expected_summary.provided_belief.json",
        EXPERIMENT_DIR / "README.md",
    ]
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        for marker in SECRET_MARKERS:
            assert marker not in text, f"{marker!r} leaked in {path.name}"


def test_live_deepseek_smoke_docs_are_secret_safe_and_untracked_output_only() -> None:
    readme = (EXPERIMENT_DIR / "README.md").read_text(encoding="utf-8")
    script = (EXPERIMENT_DIR / "run_live_deepseek_smoke.sh").read_text(
        encoding="utf-8"
    )

    assert "zsh -ic" in readme
    assert "--evaluator deepseek-chat-logprob" in readme
    assert "--cache /tmp/asv-biomed-deepseek-cache.jsonl" in readme
    assert "--write-evaluated-trajectories /tmp/asv-biomed-deepseek-evaluated.jsonl" in readme
    assert "DEEPSEEK_API_KEY" in readme
    assert "/tmp/asv-biomed-deepseek" in script
    assert "raw provider" not in script.lower()
    assert "Bearer " not in script
```

- [ ] **Step 2: Run new tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_experiment_bundle.py::test_biomed_step_value_bundle_contains_no_secret_markers tests/test_asv_experiment_bundle.py::test_live_deepseek_smoke_docs_are_secret_safe_and_untracked_output_only
```

Expected: FAIL because `README.md` and `run_live_deepseek_smoke.sh` do not exist.

- [ ] **Step 3: Create experiment README**

Create `eval/asv/experiments/biomed_step_value_smoke/README.md`:

```markdown
# Biomed Step Value Smoke

This provider-free fixture demonstrates the ASV biomedical status candidate
space:

- `supported`
- `refuted`
- `not_enough_information`

The trajectory and belief fixture are synthetic. They contain no patient data,
provider payloads, API keys, or raw prompts.

## Offline Provided-Belief Run

```bash
python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --belief-fixture eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl \
  --output-dir /tmp/asv-biomed-provided
```

Expected high-level output:

```text
trajectory_count=1 step_count=3
```

The offline path is suitable for CI and does not call DeepSeek or PubMed.

## Optional Live DeepSeek Smoke

Run this only on a local machine where the shell environment provides
`DEEPSEEK_API_KEY`. The command uses `zsh -ic` so local shell configuration can
load the key without writing it into the repository or command text.

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh'
```

The script runs:

```bash
.venv/bin/python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --evaluator deepseek-chat-logprob \
  --cache /tmp/asv-biomed-deepseek-cache.jsonl \
  --write-evaluated-trajectories /tmp/asv-biomed-deepseek-evaluated.jsonl \
  --output-dir /tmp/asv-biomed-deepseek
```

It writes live outputs under `/tmp` and should not create committed artifacts.
After a successful second run, inspect `/tmp/asv-biomed-deepseek/summary.json`
for `evaluator.mode=deepseek-chat-logprob` and nonzero cache-hit state count.
```

- [ ] **Step 4: Create live smoke script**

Create `eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT"

INPUT="eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl"
CACHE="/tmp/asv-biomed-deepseek-cache.jsonl"
EVALUATED="/tmp/asv-biomed-deepseek-evaluated.jsonl"
OUTPUT_DIR="/tmp/asv-biomed-deepseek"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is not set in the current environment." >&2
  echo "Run through: zsh -ic 'cd $ROOT && $0'" >&2
  exit 2
fi

rm -rf "$OUTPUT_DIR" "$EVALUATED"

.venv/bin/python -m asv_eval evaluate \
  --input "$INPUT" \
  --evaluator deepseek-chat-logprob \
  --cache "$CACHE" \
  --write-evaluated-trajectories "$EVALUATED" \
  --output-dir "$OUTPUT_DIR"

.venv/bin/python -m asv_eval evaluate \
  --input "$INPUT" \
  --evaluator deepseek-chat-logprob \
  --cache "$CACHE" \
  --write-evaluated-trajectories "$EVALUATED" \
  --output-dir "$OUTPUT_DIR"

.venv/bin/python - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

summary = json.loads(Path("/tmp/asv-biomed-deepseek/summary.json").read_text())
coverage = summary["evaluator_coverage"]
if summary["evaluator"]["mode"] != "deepseek-chat-logprob":
    raise SystemExit("unexpected evaluator mode")
if coverage["cache_hit_state_count"] <= 0:
    raise SystemExit("expected cache-hit state count after second run")

for path in [
    Path("/tmp/asv-biomed-deepseek/summary.json"),
    Path("/tmp/asv-biomed-deepseek/steps.jsonl"),
    Path("/tmp/asv-biomed-deepseek-cache.jsonl"),
]:
    text = path.read_text(encoding="utf-8")
    for marker in ("Bearer ", "api_key", "password", "token=", "raw_provider_response"):
        if marker in text:
            raise SystemExit(f"secret marker {marker!r} found in {path}")

print("live_deepseek_asv_smoke=passed")
print(f"cache_hit_state_count={coverage['cache_hit_state_count']}")
PY
```

- [ ] **Step 5: Make the script executable**

Run:

```bash
chmod +x eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_experiment_bundle.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add \
  eval/asv/experiments/biomed_step_value_smoke/README.md \
  eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh \
  tests/test_asv_experiment_bundle.py
git commit -m "docs: add asv deepseek smoke instructions"
```

---

### Task 3: Closeout Verification

**Files:**
- Modify: `eval/asv/experiments/biomed_step_value_smoke/README.md` only if the documented command differs from the verified command.

- [ ] **Step 1: Run provider-free bundle command exactly as documented**

Run:

```bash
rm -rf /tmp/asv-biomed-provided
.venv/bin/python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --belief-fixture eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl \
  --output-dir /tmp/asv-biomed-provided
cat /tmp/asv-biomed-provided/summary.json
```

Expected:

- command exits `0`;
- `summary.json` has `"trajectory_count": 1`;
- `summary.json` has `"step_count": 3`;
- `summary.json` has `"evaluator": {"mode": "provided-belief"}` or a superset with mode `provided-belief`.

- [ ] **Step 2: Run focused experiment tests**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_experiment_bundle.py
```

Expected: PASS.

- [ ] **Step 3: Run ASV regression suite**

Run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py tests/test_asv_cli.py tests/test_asv_runtime.py tests/test_asv_experiment_bundle.py tests/test_biomed_workflow_asv.py
```

Expected: PASS.

- [ ] **Step 4: Run key Biomedical Evidence regressions**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_evidence.py::test_trace_answer_run_uses_latest_revision_as_display_answer tests/test_biomed_api.py::test_biomed_api_answer_extract_graph_and_audit
```

Expected: PASS.

- [ ] **Step 5: Run compile and whitespace checks**

Run:

```bash
.venv/bin/python -m py_compile asv_eval/core.py asv_eval/evaluators.py asv_eval/runtime.py asv_eval/adapters.py asv_eval/reporting.py asv_eval/__main__.py
git diff --check
```

Expected: both commands exit `0`.

- [ ] **Step 6: Run optional live DeepSeek smoke when credentials are present**

First check whether the key is available without printing it:

```bash
zsh -ic 'test -n "${DEEPSEEK_API_KEY:-}" && echo deepseek_key=present || echo deepseek_key=missing'
```

If output is `deepseek_key=present`, run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh'
```

Expected:

- command exits `0`;
- stdout includes `live_deepseek_asv_smoke=passed`;
- stdout includes `cache_hit_state_count=` with a positive integer.

If output is `deepseek_key=missing`, do not run the live smoke. Record in the final status that the live smoke was not run because local credentials were unavailable.

- [ ] **Step 7: Commit README adjustment if needed**

If Step 1 or Step 6 required a README command correction, run:

```bash
git add eval/asv/experiments/biomed_step_value_smoke/README.md
git commit -m "docs: correct asv smoke command"
```

If no README correction was needed, do not create a commit in this step.

---

## Final Verification

Before claiming Phase 1 closeout, run:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py tests/test_asv_cli.py tests/test_asv_runtime.py tests/test_asv_experiment_bundle.py tests/test_biomed_workflow_asv.py
.venv/bin/pytest -q tests/test_biomed_audit.py::test_answer_with_audit_persists_revision_and_trace tests/test_biomed_evidence.py::test_trace_answer_run_uses_latest_revision_as_display_answer tests/test_biomed_api.py::test_biomed_api_answer_extract_graph_and_audit
.venv/bin/python -m py_compile asv_eval/core.py asv_eval/evaluators.py asv_eval/runtime.py asv_eval/adapters.py asv_eval/reporting.py asv_eval/__main__.py
git diff --check
git status --short --branch
```

If `DEEPSEEK_API_KEY` is available locally, also run:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh'
```

Report whether the live smoke was run, skipped for missing credentials, or failed with a concrete error.
