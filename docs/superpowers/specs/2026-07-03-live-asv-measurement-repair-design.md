# Live ASV Measurement Repair Design

## Purpose

The quick live PubMed ASV pilot proved that the collection and evaluator loop
can run, but it also exposed two measurement problems:

1. The bio-agent actor was not fully LLM-backed in the live collector because
   `BiomedEvidenceService` was created without a framework `revision_provider`.
2. The ASV measurement is not yet paper-ready because the evaluator state loses
   compact evidence facts after retrieval, and entropy-only ASV scores a
   correctness-changing one-hot label switch as zero.

This design chooses the two-step path:

```text
Phase 1: repair the ASV measurement
Phase 2: run the same measurement with a real LLM actor
```

Phase 1 is the implementation scope for the next plan. Phase 2 is documented
here only so Phase 1 does not accidentally grow into an actor integration.

## Baseline Evidence

The latest quick report is:

```text
eval/asv/experiments/live_pubmed_step_value/results.quick.md
```

Key observed facts:

- PubMed retrieval completed for all three balanced quick claims.
- DeepSeek `deepseek-chat` returned usable label logprobs for all 66 evaluated
  states.
- Missing-label, floor-score, and evaluator-fallback step counts were all zero.
- Mean net ASV was `-0.031967`.
- The APOE supported claim had a meaningful `retrieve` transition from
  `not_enough_information=1.0` to `supported=1.0`, but entropy reduction scored
  it as `0.0` because both distributions were one-hot.
- Later workflow states often contain artifact ids and audit metadata, not a
  compact stable evidence-fact view.

## Phase 1 Scope: Measurement Repair

Phase 1 repairs the meter, not the actor.

### Compact Evidence Facts

Add a deterministic compact evidence projection to ASV states exported from the
biomedical workflow.

The projection will be built from existing trace metadata only. Do not query
storage during evaluation and do not call an LLM to summarize evidence.

Minimum fields:

```text
evidence_facts.supported_claims
evidence_facts.conflicting_claims
evidence_facts.coverage_gaps
evidence_facts.audit
```

Sources:

- `observation.metadata.evidence_packet.supported_claims`
- `observation.metadata.evidence_packet.conflicting_claims`
- `observation.metadata.evidence_packet.coverage_gaps`
- audit metrics already present in trace metadata, such as
  `claim_support_rate`, `unsupported_claim_rate`, `overclaim_rate`, and
  `recommended_action`

The projection will keep at most eight facts per list field and at most 500
characters per fact. These limits are deliberately small for the quick pilot.

The projection will be carried forward in `state_after` so later steps are
evaluated against the same compact evidence context instead of only artifact
ids. It must remain bounded and redacted by the existing ASV redaction path.

### Oracle Gold Gain

Keep the existing entropy metrics. Add an oracle gold metric that remains
finite when candidate probabilities are zero:

```text
oracle_gold_log_likelihood_gain
```

It will use epsilon-smoothed probabilities for the gold candidate, with
`epsilon=1e-12`:

```text
log(max(p_after_gold, epsilon)) - log(max(p_before_gold, epsilon))
```

The metric is validation-only. It must not be visible to the evaluator prompt
and must not replace realized entropy reduction. The report will preserve
both metrics because they answer different questions:

- entropy reduction: did uncertainty shrink?
- oracle gold gain: did the step move probability toward the known label?

### Quick Pilot Recheck

Rerun the existing three-claim quick pilot after Phase 1.

Expected minimum result:

- 3/3 collection completed;
- 33 steps evaluated;
- zero missing-label steps;
- zero floor-score steps;
- APOE `retrieve` has positive `oracle_gold_log_likelihood_gain`;
- the report table exposes the new oracle metric by step type.

The full 30-claim run remains out of scope until the quick pilot shows a sane
signal for obvious evidence-acquisition steps.

## Phase 2 Scope: Real LLM Actor

Phase 2 runs after Phase 1. It will use the existing service constructor
instead of creating a new actor stack:

```text
BiomedEvidenceService(
  workspace,
  revision_provider=provider,
  revision_model=model,
  allow_live_pubmed_tools=True,
)
```

The live collector will accept an optional provider/model adapter path and
record actor-mode coverage in the collection summary.

Minimum success criteria:

- live PubMed retrieval still completes on the quick claim set;
- `planner_mode` is `llm` for at least the planning step when the provider is
  configured;
- synthesis, verifier, revision, or claim logic modes are reported explicitly
  as `llm`, `fallback`, or `deterministic`;
- the final report clearly separates actor provider coverage from evaluator
  provider coverage.

## Non-Goals

- Do not run the full 30-claim pilot in Phase 1.
- Do not add a new LLM provider abstraction.
- Do not add DSPy or another agent framework dependency.
- Do not rewrite `answer_with_audit`.
- Do not change PubMed retrieval behavior.
- Do not add UI work.
- Do not commit raw `/tmp` live provider artifacts.

## Data Flow After Phase 1

```text
answer_with_audit trace
-> bio-agent ASV trajectory export
-> compact evidence facts attached to state_after
-> DeepSeek evaluator renders redacted state
-> beliefs
-> ASV report
-> entropy metrics + oracle gold metrics
```

The evaluator still consumes frozen ASV JSONL. It must not read the bio-agent
database directly.

## Files Expected To Change In Phase 1

Expected small set:

- `plugins/biomed_evidence/workflow/asv.py`
- `asv_eval/core.py`
- `asv_eval/reporting.py`
- `eval/asv/live_pubmed/analyze.py`
- focused tests for ASV export, metrics, and live PubMed analysis
- `eval/asv/experiments/live_pubmed_step_value/results.quick.md` after rerun

Avoid broad refactors. If a change wants more files than this, stop and justify
why the smaller path cannot work.

## Testing

Provider-free tests:

- compact evidence facts are carried from retrieve/extract/audit observations
  into later `state_after` values;
- secret-like fields are still redacted;
- zero-probability gold candidates produce finite oracle gold gain;
- step-type CSV includes oracle gold gain columns;
- existing ASV evaluator and live PubMed experiment tests remain green.

Live check:

- rerun the three-claim quick pilot with live PubMed and DeepSeek evaluator;
- scan generated artifacts for secret markers;
- update `results.quick.md` with the new summary.

## Acceptance Criteria

Phase 1 is done when:

1. the quick pilot report shows usable compact evidence facts in ASV states;
2. `oracle_gold_log_likelihood_gain` is present in step rows and step-type
   summaries;
3. APOE `retrieve` is no longer invisible to gold-label validation;
4. missing-label, floor-score, and evaluator-fallback counts remain zero;
5. the working tree contains no raw live provider artifacts.

Phase 2 may start only after these criteria are met.
