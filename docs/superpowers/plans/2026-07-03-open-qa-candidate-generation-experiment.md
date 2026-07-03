# Open QA Candidate Generation ASV Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a 10-question mixed biomedical open QA ASV experiment with generated/reviewed candidate answers, preserved raw artifacts, candidate-text evaluator prompts, leakage guards, and label-permutation audit.

**Architecture:** Keep the ASV core contract as standard JSONL trajectories. Add only a small open-QA experiment slice under `eval/asv/open_qa/`; reuse existing `asv_eval` runtime/reporting, live PubMed evaluation, and bio-agent export paths. Candidate generation is preprocessing; ASV scoring uses only reviewed/frozen candidate sets.

**Tech Stack:** Python 3.12, stdlib `argparse/json/dataclasses/pathlib/subprocess`, existing `LLMProvider`, existing `BiomedEvidenceService`, existing `asv_eval` runtime/reporting, pytest, pyright.

---

## File Structure

- Modify `asv_eval/evaluators.py`: render candidate answer text in forced-choice prompts while keeping one-token label logprob scoring.
- Modify `asv_eval/runtime.py`: carry candidate text into rendered/provider prompts and redact open-QA answer-key fields from state.
- Modify `asv_eval/adapters.py`: finish `candidate_answers` spec loading and enforce exactly one `none-of-the-above` candidate.
- Modify `asv_eval/__main__.py`: expose `adapt-open-qa`.
- Create `eval/asv/open_qa/questions.quick.jsonl`: 10 mixed biomedical open QA questions.
- Create `eval/asv/open_qa/generate.py`: generate raw candidate-answer specs with DeepSeek.
- Create `eval/asv/open_qa/collect.py`: run bio-agent/PubMed and attach reviewed candidate sets to ASV trajectories.
- Create `eval/asv/open_qa/run_experiment.py`: orchestrate generation/review copy/adapt/collect/evaluate/analyze/permutation and preserve artifacts.
- Create `eval/asv/open_qa/README.md`: commands and artifact policy.
- Modify `tests/test_asv_eval.py`, `tests/test_asv_runtime.py`, `tests/test_asv_adapters.py`, `tests/test_asv_cli.py`.
- Create `tests/test_asv_open_qa_experiment.py`.

---

### Task 1: Candidate Text Prompt And Open QA Redaction

**Files:**
- Modify: `asv_eval/evaluators.py`
- Modify: `asv_eval/runtime.py`
- Test: `tests/test_asv_eval.py`
- Test: `tests/test_asv_runtime.py`

- [ ] **Step 1: Write failing evaluator prompt test**

Add to `tests/test_asv_eval.py`:

```python
def test_forced_choice_prompt_includes_candidate_answer_text_without_cot() -> None:
    prompt = render_forced_choice_prompt(
        question="Which answer best explains the response?",
        evidence_text='{"evidence":"alpha pathway evidence"}',
        labels={"A": "answer-a", "B": "answer-b"},
        candidate_texts={
            "answer-a": "Alpha pathway activation explains the response.",
            "answer-b": "Beta pathway inhibition explains the response.",
        },
    )

    assert "A: answer-a - Alpha pathway activation explains the response." in prompt
    assert "B: answer-b - Beta pathway inhibition explains the response." in prompt
    assert "compare the evidence against every candidate" in prompt
    assert "chain-of-thought" not in prompt.lower()
    assert "Output exactly one option label." in prompt
```

- [ ] **Step 2: Write failing runtime redaction test**

Add to `tests/test_asv_runtime.py`:

```python
def test_render_state_for_evaluator_redacts_open_qa_answer_keys() -> None:
    trajectory = _trajectory_with_missing_beliefs()
    step = StepRecord(
        step_id="open-qa-redaction",
        index=0,
        action={"type": "read"},
        state_after={
            "evidence": "safe evidence",
            "reference_answer": "leaked reference",
            "gold_answer": "leaked gold",
            "correct_answer": "leaked correct",
            "answer_key": "leaked key",
        },
    )

    rendered = render_state_for_evaluator(
        trajectory.task,
        step,
        position="after",
        config=EvaluatorRuntimeConfig(state_text_max_chars=2000),
    )

    assert "safe evidence" in rendered.prompt
    for leaked in ("leaked reference", "leaked gold", "leaked correct", "leaked key"):
        assert leaked not in rendered.prompt
```

- [ ] **Step 3: Run red tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_asv_eval.py::test_forced_choice_prompt_includes_candidate_answer_text_without_cot \
  tests/test_asv_runtime.py::test_render_state_for_evaluator_redacts_open_qa_answer_keys
```

Expected: FAIL because `candidate_texts` is unsupported and answer-key redaction is incomplete.

- [ ] **Step 4: Implement minimal prompt support**

In `asv_eval/evaluators.py`, change `render_forced_choice_prompt` to accept optional `candidate_texts` and render:

```python
def _option_line(label: str, candidate_id: str, candidate_texts: dict[str, str] | None) -> str:
    text = (candidate_texts or {}).get(candidate_id)
    return f"{label}: {candidate_id} - {text}" if text else f"{label}: {candidate_id}"
```

Add this sentence to the prompt before the evidence block:

```python
"Compare the evidence against every candidate before choosing one option label. "
```

- [ ] **Step 5: Thread candidate texts through runtime**

In `RenderedState`, add:

```python
candidate_texts: dict[str, str]
```

In `render_state_for_evaluator`, set:

```python
candidate_texts = {
    candidate.id: candidate.text
    for candidate in task.candidate_space.candidates
}
```

Pass `candidate_texts=rendered.candidate_texts` in `_provider_prompt`.

- [ ] **Step 6: Implement redaction**

In `asv_eval/runtime.py`, add exact leaky keys:

```python
_OPEN_QA_LEAKY_KEYS = {
    "reference_answer",
    "reference_answers",
    "gold_answer",
    "gold_answers",
    "correct_answer",
    "correct_answers",
    "expected_answer",
    "expected_answers",
    "answer_key",
}
```

Use `_is_leaky_key(key)` in `_redact` so these keys are removed before state rendering.

- [ ] **Step 7: Run task tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_asv_eval.py tests/test_asv_runtime.py
```

Expected: PASS.

### Task 2: Candidate Answer Spec Validation

**Files:**
- Modify: `asv_eval/adapters.py`
- Modify: `asv_eval/__main__.py`
- Test: `tests/test_asv_adapters.py`
- Test: `tests/test_asv_cli.py`

- [ ] **Step 1: Write failing validation tests**

Add to `tests/test_asv_adapters.py`:

```python
def test_open_qa_candidate_answer_spec_requires_none_of_the_above(tmp_path) -> None:
    path = tmp_path / "open_qa.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "missing-none",
                "question": "Which answer is right?",
                "candidate_answers": [
                    {"id": "answer-a", "text": "Alpha."},
                    {"id": "answer-b", "text": "Beta."},
                ],
                "gold_candidate_id": "answer-a",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="none-of-the-above"):
        load_open_qa_candidate_specs(path)
```

Add:

```python
def test_open_qa_candidate_answer_spec_rejects_duplicate_none_of_the_above(tmp_path) -> None:
    path = tmp_path / "open_qa.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "duplicate-none",
                "question": "Which answer is right?",
                "candidate_answers": [
                    {"id": "answer-a", "text": "Alpha."},
                    {"id": "none-of-the-above", "text": "Insufficient evidence."},
                    {"id": "none-of-the-above", "text": "No support."},
                ],
                "gold_candidate_id": "none-of-the-above",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate candidate answer id"):
        load_open_qa_candidate_specs(path)
```

- [ ] **Step 2: Run red tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_asv_adapters.py::test_open_qa_candidate_answer_spec_requires_none_of_the_above \
  tests/test_asv_adapters.py::test_open_qa_candidate_answer_spec_rejects_duplicate_none_of_the_above
```

Expected: first test fails until `none-of-the-above` is enforced.

- [ ] **Step 3: Implement minimal validation**

In `open_qa_candidate_spec_to_trajectory`, after candidate parsing:

```python
none_count = sum(item["id"] == "none-of-the-above" for item in candidates)
if none_count != 1:
    raise ValueError("open QA candidate spec must include exactly one none-of-the-above candidate")
```

- [ ] **Step 4: Run adapter/CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_asv_adapters.py tests/test_asv_cli.py
```

Expected: PASS.

### Task 3: Open QA Experiment Files And Candidate Generation

**Files:**
- Create: `eval/asv/open_qa/__init__.py`
- Create: `eval/asv/open_qa/questions.quick.jsonl`
- Create: `eval/asv/open_qa/generate.py`
- Test: `tests/test_asv_open_qa_experiment.py`

- [ ] **Step 1: Write tests for question set and generation prompt**

Create `tests/test_asv_open_qa_experiment.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path

from eval.asv.open_qa.generate import build_generation_prompt, load_open_qa_questions

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "asv" / "open_qa" / "questions.quick.jsonl"


def test_open_qa_question_set_has_expected_mix() -> None:
    questions = load_open_qa_questions(QUESTIONS)

    assert len(questions) == 10
    counts = {category: 0 for category in {
        "intervention",
        "risk",
        "mechanism",
        "diagnostic",
        "insufficient_evidence",
    }}
    for row in questions:
        counts[row.category] += 1
    assert counts == {
        "intervention": 3,
        "risk": 2,
        "mechanism": 2,
        "diagnostic": 2,
        "insufficient_evidence": 1,
    }


def test_generation_prompt_requires_four_candidates_and_none_option() -> None:
    question = load_open_qa_questions(QUESTIONS)[0]
    prompt = build_generation_prompt(question)

    assert "four candidate answers" in prompt
    assert "none-of-the-above" in prompt
    assert "gold_candidate_id" in prompt
    assert "Return only JSON" in prompt
```

- [ ] **Step 2: Run red tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_asv_open_qa_experiment.py
```

Expected: FAIL because `eval.asv.open_qa.generate` and question file do not exist.

- [ ] **Step 3: Add question file**

Create `eval/asv/open_qa/questions.quick.jsonl` with 10 JSON rows using fields:

```json
{"question_id":"open-qa-intervention-001","category":"intervention","question":"Which answer best reflects evidence about GLP-1 receptor agonists and cardiovascular outcomes in adults with type 2 diabetes?","source":"pubmed","max_papers":5}
```

Use exactly 3 intervention, 2 risk, 2 mechanism, 2 diagnostic, 1 insufficient-evidence rows.

- [ ] **Step 4: Add generator module**

Create `eval/asv/open_qa/generate.py` with:

```python
@dataclass(frozen=True)
class OpenQAQuestion:
    question_id: str
    category: str
    question: str
    source: str = "pubmed"
    max_papers: int = 5
```

Add `load_open_qa_questions(path: Path) -> list[OpenQAQuestion]`.

Add `build_generation_prompt(question: OpenQAQuestion) -> str` that requests four candidates, one `none-of-the-above`, and a recommended `gold_candidate_id`.

Add a CLI `main` that writes raw generated rows to `--output`; use `LLMProvider` only when called with `--provider deepseek`.

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_asv_open_qa_experiment.py
```

Expected: PASS.

### Task 4: Open QA Collection And Artifact Runner

**Files:**
- Create: `eval/asv/open_qa/collect.py`
- Create: `eval/asv/open_qa/run_experiment.py`
- Modify: `eval/asv/open_qa/README.md`
- Test: `tests/test_asv_open_qa_experiment.py`

- [ ] **Step 1: Write collection/unit tests**

Append to `tests/test_asv_open_qa_experiment.py`:

```python
from eval.asv.open_qa.collect import attach_candidate_set_to_trajectory
from asv_eval.core import Candidate, CandidateSpace, StepRecord, TaskRecord, TrajectoryRecord


def test_attach_candidate_set_to_trajectory_preserves_steps() -> None:
    base = TrajectoryRecord(
        trajectory_id="bio-agent-run-1",
        task=TaskRecord(
            task_id="run-1",
            question="Which answer is right?",
            candidate_space=CandidateSpace(candidates=[
                Candidate(id="supported", label="A", text="supported"),
                Candidate(id="refuted", label="B", text="refuted"),
            ]),
        ),
        steps=[StepRecord(step_id="retrieve", index=0, action={"type": "retrieve"})],
    )
    reviewed = {
        "trajectory_id": "open-qa-1",
        "question": "Which answer is right?",
        "candidate_answers": [
            {"id": "answer-a", "text": "Alpha."},
            {"id": "answer-b", "text": "Beta."},
            {"id": "answer-c", "text": "Gamma."},
            {"id": "none-of-the-above", "text": "Insufficient evidence."},
        ],
        "gold_candidate_id": "answer-b",
    }

    updated = attach_candidate_set_to_trajectory(base, reviewed)

    assert updated.task.candidate_space.type == "candidate_set"
    assert updated.task.candidate_space.gold_candidate_id == "answer-b"
    assert [candidate.id for candidate in updated.task.candidate_space.candidates] == [
        "answer-a",
        "answer-b",
        "answer-c",
        "none-of-the-above",
    ]
    assert updated.steps == base.steps
```

- [ ] **Step 2: Run red test**

Run:

```bash
.venv/bin/python -m pytest tests/test_asv_open_qa_experiment.py::test_attach_candidate_set_to_trajectory_preserves_steps
```

Expected: FAIL because `collect.py` does not exist.

- [ ] **Step 3: Implement collection helper**

Create `eval/asv/open_qa/collect.py` with `attach_candidate_set_to_trajectory(base, reviewed)` that builds `CandidateSpace(type="candidate_set")` from reviewed `candidate_answers` and returns a replaced trajectory with metadata `experiment="open_qa_candidate_generation"`.

Add CLI collection code modeled on `eval/asv/live_pubmed/collect.py`, but reading reviewed open QA specs and attaching candidate sets after `service.export_answer_run_asv_trajectory(run_id)`.

- [ ] **Step 4: Implement orchestration runner**

Create `eval/asv/open_qa/run_experiment.py` that:

1. creates a timestamped artifact root;
2. writes `commands.log`;
3. runs candidate generation or accepts `--reviewed`;
4. copies reviewed specs into artifact root;
5. adapts reviewed specs to ASV JSONL;
6. runs live collection when `--ack-live`;
7. runs ASV evaluation;
8. runs `eval.asv.live_pubmed.analyze`;
9. builds label permutations with `eval.asv.live_pubmed.robustness`;
10. writes `results.md`.

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_asv_open_qa_experiment.py
```

Expected: PASS.

### Task 5: Verification And Experiment Smoke

**Files:**
- Modify: `docs/evaluation.md`
- Create: `eval/asv/open_qa/README.md`

- [ ] **Step 1: Add README commands**

Document:

```bash
.venv/bin/python -m eval.asv.open_qa.generate \
  --questions eval/asv/open_qa/questions.quick.jsonl \
  --output /tmp/asv-open-qa/generated.jsonl \
  --provider deepseek \
  --model deepseek-v4-flash

.venv/bin/python -m eval.asv.open_qa.run_experiment \
  --reviewed /tmp/asv-open-qa/reviewed.jsonl \
  --artifact-root /tmp/asv-open-qa-candidate-generation-$(date +%Y%m%d-%H%M%S) \
  --actor-provider deepseek \
  --actor-model deepseek-v4-flash \
  --ack-live
```

- [ ] **Step 2: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_asv_eval.py \
  tests/test_asv_runtime.py \
  tests/test_asv_adapters.py \
  tests/test_asv_cli.py \
  tests/test_asv_open_qa_experiment.py
```

Expected: PASS.

- [ ] **Step 3: Run targeted pyright**

Run:

```bash
.venv/bin/pyright asv_eval eval/asv/open_qa eval/asv/live_pubmed tests/test_asv_open_qa_experiment.py --level error
```

Expected: `0 errors`.

- [ ] **Step 4: Run full tests**

Run:

```bash
.venv/bin/pytest -q tests/
```

Expected: PASS.

- [ ] **Step 5: Run live open QA experiment**

Run with `zsh -ic` so `DEEPSEEK_API_KEY` is loaded:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.open_qa.run_experiment \
    --questions eval/asv/open_qa/questions.quick.jsonl \
    --artifact-root /tmp/asv-open-qa-candidate-generation-$(date +%Y%m%d-%H%M%S) \
    --candidate-provider deepseek \
    --candidate-model deepseek-v4-flash \
    --actor-provider deepseek \
    --actor-model deepseek-v4-flash \
    --evaluator-model deepseek-chat \
    --ack-live'
```

Expected: artifact root contains generated/reviewed specs, collection outputs, evaluator cache, evaluated trajectories, report bundle, permutation artifacts, and `results.md`.

---

## Plan Self-Review

- Spec coverage: candidate text prompt, answer-key redaction, `none-of-the-above`, candidate generation, reviewed freeze, live collection, evaluator cache, report, and permutation artifacts are all mapped to tasks.
- Open-marker scan: clean.
- Type consistency: open QA specs use `candidate_answers`, `gold_candidate_id`, `none-of-the-above`, and standard `CandidateSpace(type="candidate_set")` throughout.
