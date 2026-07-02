# ASV LLM Evaluator Runtime And Stateless Migration Design

## Context

The ASV tool and Biomedical Evidence integration now have the first working
measurement substrate:

- standard ASV JSONL records;
- bio-agent and ReAct adapters;
- bio-agent workflow projection from saved audited-answer runs;
- ASV report generation from provided `belief_before` and `belief_after`
  values;
- DeepSeek logprob evaluator primitives in `asv_eval.evaluators`.

The missing link is the production evaluator runtime. Today the CLI can score
provided beliefs, but it cannot yet compute beliefs over saved state snapshots
with a real LLM evaluator and then run ASV over those beliefs.

The next architecture decision is therefore:

```text
LLM evaluator runtime first, ASV-gated stateless migration immediately after.
```

This keeps the work aligned with the paper's RQ1. We first make the evaluator a
real measuring instrument, then use that instrument to guide stateless workflow
migration.

## Goal

Build a reproducible LLM evaluator runtime for ASV that can:

1. read ASV trajectories whose steps have explicit `state_before` and
   `state_after`;
2. estimate `belief_before` and `belief_after` for each step with a DeepSeek
   chat logprob forced-choice evaluator;
3. cache evaluator outputs by state and evaluator configuration;
4. write evaluated trajectories and ASV reports with clear quality flags;
5. provide the regression metric for the first stateless bio-agent workflow
   slices.

The goal is not only to make one report run. The goal is to establish the
measurement loop that lets every later workflow refactor answer:

```text
Did this step contract preserve or improve measurable agent step value?
```

## Non-Goals

- Do not rewrite `BiomedEvidenceService.answer_with_audit` in this slice.
- Do not introduce DSPy as a dependency.
- Do not make live DeepSeek calls required for unit tests or CI.
- Do not change existing bio-agent public API, dashboard, Pilot Report, or
  stored artifact shapes.
- Do not claim that short-label logprob scoring estimates full long-form answer
  likelihood.
- Do not train, tune, or optimize prompts in this slice.
- Do not add a UI before the CLI/runtime path is reliable.

## Decision

Implement the next slice in two phases:

```text
Phase 1: ASV LLM evaluator runtime
Phase 2: ASV-gated stateless bio-agent slices
```

Phase 1 makes `python -m asv_eval evaluate` able to fill missing beliefs using
an evaluator mode such as:

```bash
python -m asv_eval evaluate \
  --input trajectories.jsonl \
  --evaluator deepseek-chat-logprob \
  --cache .asv-cache/deepseek-logprob.jsonl \
  --output-dir reports/asv-run-001
```

Phase 2 starts the true stateless migration, but only after Phase 1 provides a
working meter. The first stateless slices should be small and measurable:

```text
ClassifyStep
RetrieveStep
```

Each migrated step must produce the same product artifacts as before and an ASV
step projection that can be evaluated by Phase 1.

## Why LLM Evaluator Comes Before Full Stateless Refactor

The stateless direction is important, but a full workflow rewrite before the
evaluator runtime creates avoidable risk:

1. The current bio-agent workflow includes storage, evidence packets, audit
   records, revisions, trace rows, graph snapshots, review state, and reports.
   Rewriting all of that first would turn an ASV measurement project into a
   broad product refactor.
2. Stateless step contracts are only useful for the paper if they can be
   measured. The LLM evaluator runtime supplies the belief deltas needed for
   entropy reduction and gold log-likelihood gain.
3. The current workflow projection already produces ASV-like step records from
   saved runs. That is enough to evaluate the first experiments while the
   stateless kernel is introduced incrementally.

The intended story is:

```text
ASV defines the measurement.
The LLM evaluator operationalizes the measurement.
Stateless steps make the measured actions reproducible and replaceable.
```

## Phase 1 Architecture: LLM Evaluator Runtime

The runtime extends the current pipeline:

```text
ASV JSONL
  -> load trajectories
  -> build or read state_before/state_after
  -> render evaluator-safe state text
  -> score each state with BeliefEvaluator
  -> attach belief_before/belief_after to steps
  -> evaluate ASV metrics
  -> write report bundle
```

The implementation should stay stateless at the module level. Runtime state is
explicit:

- input trajectory path;
- evaluator config;
- optional cache path;
- output directory;
- optional fixture path;
- optional live-provider flag for smoke tests.

No evaluator should read bio-agent storage directly. The bio-agent adapter
exports trajectories. The evaluator consumes trajectories.

## Runtime Components

### Evaluator Config

Add an explicit evaluator config object for CLI/runtime usage. It should
include:

- `mode`: `provided-belief`, `deepseek-chat-logprob`, or future
  `llm-score-fallback`;
- `provider`: default `deepseek`;
- `model`: default `deepseek-v4-flash`;
- `api_key_env`: default `DEEPSEEK_API_KEY`;
- `top_logprobs`: default `20`;
- `max_tokens`: default `1`;
- `temperature`: default `0`;
- `floor_score`: default `-20.0`;
- `max_logprob_candidates`: default `10`;
- `cache_path`: optional JSONL cache path;
- `fallback_policy`: `error`, `floor`, or future `llm-score-fallback`;
- `state_text_max_chars`: bounded prompt text size for repeatable scoring.

The run config must be written into `summary.json`.

### State Text Renderer

Add a renderer that converts a `StepRecord` state into evaluator text. It must
be deterministic and must avoid gold leakage.

Input:

```text
task question
candidate space
state_before or state_after
step action and observation only when needed for context
```

Output:

```text
question + candidate labels + redacted evidence/state text
```

The renderer must not include:

- `gold_candidate_id`;
- `final_score`;
- `success`;
- step `label`;
- `label_source`;
- `label_confidence`;
- human usefulness annotations.

Prompt injection content from observations must be delimited as inert data.

### Belief Filling

Add a pure transformation:

```text
fill_missing_beliefs(trajectories, evaluator, cache, config) -> trajectories
```

For each step:

- if both beliefs already exist and mode is `provided-belief`, preserve them;
- if mode is `deepseek-chat-logprob`, compute beliefs for both states;
- if one state fails, surface the error with trajectory id, step id, and
  position;
- never silently mix provided beliefs and provider beliefs unless the CLI mode
  explicitly allows it.

The first implementation can compute the same state multiple times unless a
cache is provided. With a cache, identical state text plus identical evaluator
config must produce a cache hit.

### Cache

Use an append-friendly JSONL cache, keyed by:

```text
sha256(evaluator_config_without_secrets + rendered_prompt)
```

Each cache row should include:

- `cache_key`;
- `created_at`;
- `provider`;
- `model`;
- `mode`;
- `state_hash`;
- `prompt_hash`;
- `candidate_ids`;
- `scores`;
- `belief`;
- `warnings`;
- `quality_flags`.

The cache must not store API keys or raw unredacted provider payloads.

### Quality Flags

Each evaluated row should preserve enough evidence to audit the evaluator:

- `evaluator_mode`;
- `provider`;
- `model`;
- `candidate_count`;
- `top_logprobs`;
- `missing_labels`;
- `missing_label_count`;
- `used_floor_score`;
- `floor_score`;
- `used_cache`;
- `used_fallback`;
- `prompt_hash`;
- `state_hash`.

Reports should aggregate:

- missing-label rate;
- floor-score usage rate;
- cache-hit rate;
- provider error count;
- fallback count;
- evaluated-state count.

## DeepSeek Logprob Scoring Contract

The v1 logprob path remains a forced-choice label scorer.

For each state:

1. assign labels `A`, `B`, `C`, etc. to candidate IDs;
2. render a prompt asking for exactly one label;
3. call chat completions with `max_tokens=1`, `temperature=0`,
   `logprobs=true`, and `top_logprobs=20`;
4. extract first-token top logprobs;
5. normalize label variants such as `" A"`, `"\nA"`, and `"A."`;
6. combine variants with logsumexp;
7. use softmax over candidate log scores to produce a belief distribution.

Missing labels must be explicit. The evaluator may use a floor score only under
the configured fallback policy. Rows using a floor score must not be presented
as clean provider-native evidence.

Reasoning models or thinking modes must fail early or route to a configured
fallback because this scoring path requires token logprobs.

## CLI Shape

Extend the current CLI without breaking existing provided-belief runs:

```bash
python -m asv_eval evaluate \
  --input trajectories.jsonl \
  --belief-fixture beliefs.jsonl \
  --output-dir reports/provided-belief
```

Add:

```bash
python -m asv_eval evaluate \
  --input trajectories.jsonl \
  --evaluator deepseek-chat-logprob \
  --cache .asv-cache/deepseek-logprob.jsonl \
  --output-dir reports/deepseek-logprob
```

Useful options:

- `--evaluator provided-belief`;
- `--evaluator deepseek-chat-logprob`;
- `--model deepseek-v4-flash`;
- `--api-key-env DEEPSEEK_API_KEY`;
- `--cache PATH`;
- `--fallback-policy error|floor`;
- `--state-text-max-chars N`;
- `--write-evaluated-trajectories PATH`.

Default behavior should remain friendly:

- if `--belief-fixture` is provided and `--evaluator` is omitted, use
  `provided-belief`;
- if beliefs are missing and no evaluator is configured, fail with a clear
  message explaining how to use either `--belief-fixture` or
  `--evaluator deepseek-chat-logprob`.

## Output Additions

Keep the existing report bundle and add:

- optional evaluated trajectory JSONL written by
  `--write-evaluated-trajectories`;
- evaluator run config in `summary.json`;
- evaluator coverage metrics in `summary.json`;
- quality flags in each `steps.jsonl` row.

The report should clearly distinguish:

- provided-belief rows;
- provider-native DeepSeek logprob rows;
- floor-filled rows;
- fallback rows.

## Phase 2 Architecture: ASV-Gated Stateless Migration

After the evaluator runtime works, start the real stateless migration with the
smallest useful bio-agent stages:

```text
ClassifyStep
RetrieveStep
```

Each stateless step should follow this contract:

```text
StepInput -> StepOutput
StepOutput -> BiomedWorkflowStep
BiomedWorkflowStep -> ASV StepRecord
```

The service remains the orchestrator and persistence owner. The step functions
should not write to storage directly. They return outputs and artifact
references; the service persists them.

### StepInput

Each step input should include only explicit dependencies:

- run id;
- question;
- source policy;
- prior completed artifacts;
- provider settings;
- project context required for that step.

No step should read global mutable state or session memory implicitly.

### StepOutput

Each step output should include:

- domain result;
- artifact IDs or artifact payloads to persist;
- warnings;
- errors;
- cost and observability fields;
- ASV projection hints.

### Regression Gate

For each migrated step:

1. run the existing saved-run export path;
2. run the stateless-step export path on the same fixture;
3. evaluate both with provided beliefs in unit tests;
4. optionally evaluate both with DeepSeek logprob in a live smoke test;
5. compare trace shape, ASV coverage, cost fields, warning preservation, and
   final product behavior.

The gate is not "ASV must always increase." The gate is:

```text
The stateless step preserves behavior, produces cleaner step contracts, and
does not destroy measurable ASV coverage.
```

## Implementation Order

Recommended sequence:

1. Add evaluator runtime tests with fake DeepSeek responses.
2. Add state text rendering and leakage checks.
3. Add belief filling over trajectories.
4. Add JSONL cache.
5. Extend CLI with `--evaluator`, evaluator config, and evaluated trajectory
   output.
6. Extend reporting with evaluator mode and quality summaries.
7. Add one optional live DeepSeek smoke script or documented command.
8. Start `ClassifyStep` as the first stateless slice.
9. Start `RetrieveStep` as the second stateless slice.
10. Use the evaluator runtime to compare pre-migration and post-migration ASV
    reports.

## Testing

Unit tests must not require live provider calls.

Required Phase 1 tests:

- CLI fails clearly when beliefs are missing and no evaluator is configured.
- `provided-belief` mode preserves fixture behavior.
- fake DeepSeek response fills `belief_before` and `belief_after`.
- label variants are normalized and logsumexp-combined.
- missing labels record warnings and obey fallback policy.
- evaluator prompt leakage guard rejects gold, success, final score, step
  labels, and human usefulness labels.
- cache hit returns the same belief without calling the provider.
- evaluated trajectories can be written and then scored by the existing report
  path.
- `summary.json` includes evaluator config without secrets.
- provider payloads and API keys are not written to report artifacts.

Required Phase 2 tests:

- `ClassifyStep` has deterministic input/output fixtures.
- `RetrieveStep` has deterministic input/output fixtures with mocked sources.
- migrated steps still project to valid ASV `StepRecord` rows.
- migrated steps preserve warnings, costs, and artifact IDs.
- existing `answer_with_audit` tests keep passing.

Optional live checks:

- run a small exported bio-agent ASV JSONL through
  `--evaluator deepseek-chat-logprob`;
- verify the report contains provider-native evaluator rows;
- verify cache reuse on a second run;
- verify no raw provider payloads or secrets appear in outputs.

## Acceptance Criteria

Phase 1 is accepted when:

- a saved bio-agent ASV JSONL with missing beliefs can be evaluated with
  `--evaluator deepseek-chat-logprob`;
- reports include entropy reduction, net ASV, gold validation metrics when gold
  is present, and evaluator quality flags;
- unit tests cover the evaluator runtime without live credentials;
- live DeepSeek remains optional and secret-safe;
- evaluated trajectories can be saved and reused without re-calling the
  provider.

Phase 2 first slice is accepted when:

- at least `ClassifyStep` and `RetrieveStep` exist as stateless step functions;
- both produce ASV-compatible workflow projections;
- existing product behavior remains stable;
- ASV reports can compare old projection and new stateless projection on the
  same fixtures.

## Open-Source Positioning

This sequence gives the open-source project a coherent shape:

```text
1. Bring any agent trace.
2. Normalize it to ASV JSONL.
3. Use provided beliefs or an LLM evaluator to estimate belief movement.
4. Compute step value, cost-adjusted step value, and validation metrics.
5. Use the report to improve or refactor the agent.
```

The bio-agent integration becomes the reference example, not the only supported
runtime. Its stateless migration demonstrates how a real application can move
toward DSPy-like explicit modules while keeping product persistence intact.
