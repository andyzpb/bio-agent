# Live PubMed ASV Experiment Design

## Purpose

This spec defines the first paper-facing experiment suite for Agent Step Value
(ASV). The goal is to support the RQ1 claim:

```text
Can we define and validate a principled value measure for each intermediate
step of a real LLM agent?
```

The experiment should not stop at synthetic provided-belief fixtures. The main
result uses a real biomedical evidence agent, live PubMed retrieval, real LLM
agent behavior, and an LLM logprob evaluator. Controlled fixtures remain useful,
but they serve as calibration rather than the main scientific result.

## Current Baseline

The repository already has the required measurement foundation:

- ASV trajectory records with `state_before`, `action`, `observation`,
  `state_after`, cost, and quality flags.
- `provided-belief` evaluation for controlled fixtures.
- DeepSeek chat logprob belief filling for forced-choice candidate spaces.
- Secret-safe state rendering and evaluator cache provenance.
- Bio-agent workflow export from saved audited-answer runs.
- A stateless `ClassifyStep` and `RetrieveStep` slice that projects into the
  same ASV trajectory format.

This experiment design should build on that foundation without rewriting the
production `answer_with_audit` path.

## Experiment Suite

The paper should use three experiments, ordered by scientific importance.

### Experiment 1: Live PubMed LLM-Agent Step Value Profiling

This is the main result.

Input:

- 30-50 manually curated biomedical claim-verification questions.
- Gold labels in:

```text
supported
refuted
not_enough_information
```

Execution:

```text
question
-> live PubMed retrieval
-> real LLM bio-agent run through answer_with_audit
-> saved agent trace
-> ASV trajectory export
-> DeepSeek chat-logprob belief filling
-> step-level ASV report
```

The production workflow remains the agent under study. The stateless slice is
not the main agent in this experiment; it is the architecture direction and
projection reference.

Primary analysis:

- aggregate ASV by step type:

```text
classify
retrieve
extract
audit
revise
finalize
```

- compare:
  - realized entropy reduction;
  - net ASV after cost;
  - gold log-likelihood gain;
  - cost fields;
  - floor-score usage;
  - missing-label rate;
  - cache-hit rate.

Expected paper claim:

```text
ASV exposes which intermediate steps in a real biomedical LLM agent reduce
task uncertainty, which steps mostly add cost, and which steps move belief away
from the gold label.
```

### Experiment 2: Controlled ASV Calibration

This is the sanity and calibration layer.

Use the existing stateless `ClassifyStep` and `RetrieveStep` machinery plus
provided-belief fixtures to construct controlled cases:

```text
good evidence
empty retrieval
irrelevant evidence
misleading evidence
high-cost useful evidence
clinical refusal
unsupported request
```

Purpose:

- verify that useful evidence yields positive realized entropy reduction;
- verify that empty or irrelevant steps yield low value;
- verify that misleading evidence can produce negative gold log-likelihood gain;
- verify that high action cost lowers net ASV even when entropy reduction is
  positive;
- verify that refusal and unsupported-request paths are measurable, not hidden.

This experiment proves the metric behaves sensibly under known conditions. It
does not replace the live-agent experiment.

### Experiment 3: External Public-Dataset Validation

This is the external validity layer.

Use a public biomedical QA or claim-verification source as a secondary dataset.
The preferred first choices are:

- PubMedQA yes/no/maybe mapped to supported/refuted/not_enough_information.
- BioASQ yes/no subset mapped to supported/refuted where feasible.

The external validation does not need to run every production workflow feature
for the first paper. It should show that ASV evaluation can be applied beyond
the manually curated claim set.

Minimum useful external validation:

```text
public question/claim
-> live or frozen retrieval artifact
-> ASV trajectory
-> LLM logprob belief filling
-> relationship between final belief/gold gain and answer correctness
```

## Data Flow

### Collection Run

The first pass is a live collection run:

```text
curated claim set
-> answer_with_audit(source=pubmed, llm enabled)
-> saved run
-> exported ASV trajectory JSONL
-> frozen experiment artifact
```

Live PubMed and real LLM calls happen here. This run is allowed to be noisy and
network-dependent. It must persist enough information to make later analysis
reproducible:

- run id;
- question;
- retrieval manifest;
- returned paper ids;
- paper titles and abstracts used by the agent;
- evidence spans or extracted evidence summaries;
- trace steps;
- final answer and audit/revision metadata;
- ASV trajectory JSONL.

### Evaluation Run

The second pass evaluates frozen artifacts:

```text
frozen ASV trajectory JSONL
-> DeepSeek chat-logprob evaluator
-> evaluated trajectory JSONL
-> ASV report artifacts
```

The evaluator sees state renderings, not the gold label. Gold is used only for
validation metrics such as gold log-likelihood gain.

### Analysis Run

The final pass aggregates report rows:

```text
steps.jsonl
-> step-type summary
-> per-question profile
-> calibration summary
-> robustness checks
```

The analysis should preserve both raw step rows and paper-facing tables.

## Metrics

Primary ASV metrics:

- `entropy_before_nats`;
- `entropy_after_nats`;
- `realized_entropy_reduction`;
- `normalized_entropy_reduction`;
- `cost_scalar`;
- `net_asv`;
- `gold_log_likelihood_gain`;
- `gold_rank_before`;
- `gold_rank_after`.

Evaluator quality metrics:

- missing-label rate;
- floor-score usage rate;
- floor-score sensitivity across at least:

```text
-10
-15
-20
-30
```

- evaluator cache-hit rate on repeated evaluation;
- label permutation audit on a main-experiment subset.

Agent workflow metrics:

- final answer correctness against gold label;
- support/refute/NEI confusion matrix;
- audit changed answer rate;
- revise changed answer rate;
- unsupported or clinical-refusal rate.

## LLM Roles

The experiment distinguishes two roles.

### Agent Actor

The agent actor is the LLM-backed bio-agent workflow under study. It performs
retrieval planning, evidence extraction/synthesis, audit, revision, and final
answer generation where the production workflow already supports those steps.

### Belief Evaluator

The belief evaluator is the forced-choice logprob scorer that estimates:

```text
p(supported | state)
p(refuted | state)
p(not_enough_information | state)
```

The evaluator should use DeepSeek chat-logprob mode for v1. If the same provider
family is used for both actor and evaluator, the paper must report that as a
limitation. The preferred stronger setting is actor/evaluator separation when a
second compatible model is available.

## Gold Leakage Controls

Gold labels must never enter evaluator prompts. The rendered evaluator state
must not include:

- `gold_candidate_id`;
- gold label text as a validation field;
- final score;
- final success flag;
- step labels;
- human usefulness labels.

Gold labels may be used only after belief estimation to compute validation
metrics such as gold log-likelihood gain and rank movement.

## Label Bias Controls

The evaluator uses forced-choice labels:

```text
A
B
C
```

The main experiment should include a label permutation audit on a subset of
questions. The audit should:

1. score the same states under multiple label-to-candidate permutations;
2. map scores back to stable candidate ids;
3. report rank stability and ASV stability across permutations.

If full permutation ensembling is too expensive for all examples, it should be
run on a representative subset and reported as a robustness check.

## Reproducibility

The live collection run is not expected to be exactly reproducible because
PubMed and providers can change. The paper artifact must therefore freeze:

- trajectory JSONL;
- retrieval manifests;
- paper ids and text snippets used in states;
- evaluator configuration;
- evaluated trajectory JSONL;
- ASV report summary and step rows.

The frozen artifacts are the reproducibility target for tables and figures.
Fresh live runs may be reported separately as a replication check.

## Error Handling

Live collection errors should be categorized, not silently dropped:

- PubMed timeout or empty retrieval;
- provider timeout;
- malformed response;
- clinical-refusal or unsupported-request classification;
- audit/revision failure;
- ASV evaluator missing labels;
- floor-score fallback use;
- secret-redaction failure.

Each failed or partial run should produce a row-level status so the denominator
for every reported metric is explicit.

## Testing And Validation

Provider-free tests:

- controlled provided-belief fixtures still run offline;
- frozen ASV trajectory parsing works;
- report summaries include evaluator provenance;
- gold leakage checks pass;
- committed artifacts contain no secrets or raw provider payloads.

Optional live tests:

- live PubMed collection smoke on a tiny question subset;
- live DeepSeek logprob evaluation on a frozen trajectory;
- second evaluator run uses cache;
- generated artifacts under `/tmp` or an untracked experiment directory pass
  secret scans.

Paper validation checks:

- controlled calibration recovers the expected ordering:

```text
good evidence > neutral/empty evidence
misleading evidence has negative or lower gold gain
high-cost useful evidence has lower net ASV than low-cost useful evidence
```

- live main experiment reports per-step ASV distributions;
- external dataset validation reports final belief/gold relationship;
- label permutation audit reports bias sensitivity;
- floor-score sensitivity reports whether conclusions change.

## Non-Goals

- Do not train or fine-tune an agent.
- Do not claim ASV is a reinforcement learning value function in this paper.
- Do not rewrite production `answer_with_audit`.
- Do not make live PubMed or live LLM tests mandatory for CI.
- Do not use patient-specific or private medical data.
- Do not expose raw provider responses or secrets in committed artifacts.

## Acceptance Criteria

The experiment suite is ready for implementation planning when the design can
support:

1. a live PubMed LLM-agent collection run on a curated claim set;
2. frozen trajectory artifacts for reproducible ASV evaluation;
3. DeepSeek logprob ASV evaluation over frozen trajectories;
4. controlled provided-belief calibration fixtures;
5. one public-dataset validation path;
6. gold leakage, secret leakage, floor-score, cache, and label-bias checks;
7. paper-facing tables for step-type ASV profiles and robustness summaries.

