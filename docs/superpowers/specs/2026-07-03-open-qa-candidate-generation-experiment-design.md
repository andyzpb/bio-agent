# Open QA Candidate Generation ASV Experiment Design

## Purpose

Run a realistic open QA ASV experiment without mixing two different questions:

1. Can an LLM produce a useful candidate answer set for open QA?
2. Given a frozen reviewed candidate set, does each agent step move evaluator
   belief toward the correct candidate answer?

The experiment treats candidate generation as preprocessing. ASV measures only
step value after the candidate set is reviewed and frozen.

## Chosen Approach

Use an end-to-end candidate-generation workflow with human review:

1. Build a 10-question mixed biomedical open QA quick set.
2. Use an LLM to generate four candidate answers per question.
3. Ask the LLM to recommend `gold_candidate_id`.
4. Human review confirms or edits candidate answers and gold candidate.
5. Freeze the reviewed candidate set before any ASV scoring.
6. Run the bio-agent with live PubMed retrieval on each question.
7. Evaluate the resulting steps against the frozen candidate set.

This is easier than manually writing all candidates and more realistic than a
closed-set biomedical label task. It is still defensible because the generated
candidates are saved separately from the reviewed, frozen candidate set.

## Question Mix

Use 10 biomedical open QA questions:

- 3 intervention or treatment questions;
- 2 risk or adverse-outcome questions;
- 2 mechanism or explanation questions;
- 2 diagnostic, biomarker, or prognosis questions;
- 1 insufficient-evidence or disputed-evidence question.

Each question should be answerable from PubMed abstracts but not trivially
answered from the question text alone.

## Candidate Answer Spec

Each reviewed JSONL row is the source of truth for ASV:

```json
{
  "trajectory_id": "open-qa-001",
  "question": "Which answer best reflects the evidence about ...?",
  "category": "intervention",
  "candidate_answers": [
    {"id": "answer-a", "text": "Candidate answer A."},
    {"id": "answer-b", "text": "Candidate answer B."},
    {"id": "answer-c", "text": "Candidate answer C."},
    {"id": "none-of-the-above", "text": "The available evidence is insufficient to support any of the specific candidate answers."}
  ],
  "gold_candidate_id": "answer-b",
  "review": {
    "status": "accepted",
    "reviewer": "human",
    "notes": "Candidate set reviewed before ASV evaluation."
  }
}
```

The raw generated file must also be retained, including the model, prompt hash,
recommended gold candidate, and any warnings. The reviewed file may edit answer
text or gold labels, but it must preserve the original question ID.

Every reviewed row must include one explicit insufficiency candidate:

```json
{
  "id": "none-of-the-above",
  "text": "The available evidence is insufficient to support any of the specific candidate answers."
}
```

This prevents the evaluator from being forced to rank only wrong substantive
answers when PubMed evidence does not support any of them.

## Evaluator Bias Controls

The evaluator should not be asked to output chain-of-thought text. The current
DeepSeek evaluator measures one-token option-label log probabilities; asking it
to emit reasoning before a label would change the scored token and break the
metric.

Instead:

1. The forced-choice prompt must instruct the evaluator to compare the evidence
   against every candidate answer before choosing one label.
2. The prompt must display candidate answer text, not only answer IDs.
3. The experiment must run a candidate-label permutation audit and aggregate
   candidate scores back to stable candidate IDs.

This handles positional bias without changing the logprob scoring contract.

## Required Implementation Before Running

Two small code gaps must be closed before the experiment is valid:

1. The evaluator prompt must display candidate answer text, not only candidate
   IDs. Open QA IDs such as `answer-a` are not semantically meaningful.
2. Open QA state rendering must redact reference-answer and gold-answer fields,
   including `reference_answer`, `gold_answer`, `correct_answer`,
   `gold_candidate_id`, and near variants.
3. The experiment runner must support a candidate-label permutation audit for
   open QA candidate sets.

The existing ASV JSONL contract should remain unchanged. The open QA adapter
should only emit standard `CandidateSpace(type="candidate_set")` trajectories.

## Metric Policy

Primary metric:

- `gold_margin_gain`

Compatibility metric:

- `oracle_gold_log_likelihood_gain`

Diagnostic metric:

- entropy reduction and `net_asv`

Not used as a primary open QA metric:

- `semantic_gold_gain`

`semantic_gold_gain` remains defined only for the biomedical
`supported/refuted/not_enough_information` label geometry. Generic open QA
candidate answers do not get a hand-written semantic embedding in this
experiment.

## Artifact Policy

Write all experiment artifacts under a timestamped directory, for example:

```text
/tmp/asv-open-qa-candidate-generation-YYYYMMDD-HHMMSS/
```

Keep:

- generated candidate specs;
- reviewed candidate specs;
- adapted ASV trajectories;
- bio-agent collection logs;
- raw bio-agent collection outputs;
- workspace database;
- evaluator cache;
- evaluated trajectories;
- report bundle;
- step-type analysis tables;
- final markdown result report.

Do not overwrite the existing live PubMed quick pilot artifacts.

## Success Criteria

The experiment is ready to interpret when:

1. 10 reviewed open QA rows exist with four candidate answers each.
2. Each reviewed row has exactly one `none-of-the-above` candidate.
3. Each reviewed row has a valid `gold_candidate_id`.
4. The adapted ASV trajectory file uses `candidate_set`.
5. Evaluator prompts include candidate answer text.
6. Gold/reference answers are redacted from evaluator states.
7. Candidate-label permutation audit artifacts are preserved.
8. Live PubMed collection completes or records explicit per-question failures.
9. Evaluated trajectories and evaluator cache are preserved.
10. The report exposes `gold_margin_gain` by step and by step type.
11. The final report distinguishes candidate-generation quality from ASV step
   value.

## Non-Goals

- Do not build a review UI.
- Do not define learned or hand-written embeddings for arbitrary answer text.
- Do not make the bio-agent generate the candidate set during ASV scoring.
- Do not ask the evaluator to output chain-of-thought reasoning in the scored
  logprob call.
- Do not delete or rewrite existing quick-pilot artifacts.
- Do not run a large public benchmark until the 10-question quick set is clean.

## Spec Self-Review

- Open-marker scan: clean.
- Internal consistency: generation is preprocessing; ASV scoring uses only the
  reviewed frozen candidate set.
- Scope check: this is one experiment slice with two small code hardening
  requirements plus a permutation audit before running.
- Ambiguity check: primary open QA metric is `gold_margin_gain`; semantic gain
  is not used for generic candidate answers.
