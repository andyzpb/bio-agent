# ASV One-Hot Robust Metrics Design

## Purpose

The Phase 2 live quick pilot showed that the ASV measurement loop can run with
live PubMed retrieval, a live LLM actor, and a live LLM evaluator. It also made
one measurement problem too central to leave as a caveat:

```text
wrong one-hot belief -> correct one-hot belief
```

has zero entropy change, even though it is the most important kind of
correctness movement.

This design adds two metrics that handle one-hot saturation without changing
the agent, the evaluator prompt, PubMed retrieval, or the ASV JSONL contract.

## Chosen Approach

Use both:

1. raw evaluator score margins;
2. semantic label geometry.

Do not try to solve the problem by smoothing probabilities alone. Smoothing is
allowed as a diagnostic, but it is not the primary fix.

## Metric A: Gold Margin Gain

The evaluator already produces label log scores before they are normalized into
belief probabilities. Preserve those scores in ASV step records.

For each labeled trajectory, define:

```text
gold_margin(state) =
  raw_score(gold_label) - logsumexp(raw_score(non_gold_labels))

gold_margin_gain =
  gold_margin(after) - gold_margin(before)
```

This is validation-only. The gold label is never shown to the evaluator.

Why this helps:

- it uses the evaluator score scale before softmax saturation;
- it can distinguish a barely-won one-hot from a strongly-won one-hot;
- it keeps the metric close to log-likelihood scoring, which is easy to defend
  in the paper.

Expected reporting names:

```text
gold_margin_before
gold_margin_after
gold_margin_gain
```

## Metric B: Semantic Gold Gain

The biomedical labels are not arbitrary classes. They encode evidence direction
and evidence sufficiency.

Use this fixed two-dimensional label embedding:

```text
supported                = (+1, 1)
refuted                  = (-1, 1)
not_enough_information   = ( 0, 0)
```

Interpretation:

```text
dimension 1: evidence direction
dimension 2: evidence sufficiency
```

For each state belief distribution:

```text
z(state) = sum_label p(label | state) * embedding(label)
```

For a labeled trajectory:

```text
semantic_distance(state, gold) =
  euclidean_distance(z(state), embedding(gold))

semantic_gold_gain =
  semantic_distance(before, gold) - semantic_distance(after, gold)
```

Positive means the step moved the evaluator belief closer to the correct
biomedical label geometry.

Why this helps:

- it assigns meaningful distance to `NEI -> supported` and `NEI -> refuted`;
- it treats `supported` and `refuted` as opposite evidence directions;
- it keeps `NEI` as lack of sufficient directional evidence rather than as a
  third unrelated class;
- it remains computable from existing belief probabilities.

Expected reporting names:

```text
semantic_gold_distance_before
semantic_gold_distance_after
semantic_gold_gain
```

## Metric Roles In The Paper

The paper should stop using one overloaded "mean net ASV" phrase.

Use this metric family:

```text
entropy_asv              = uncertainty reduction
gold_margin_gain         = raw-score correctness movement
semantic_gold_gain       = biomedical label-geometry movement
oracle_gold_log_gain     = compatibility and ablation metric
```

Primary validation tables should lead with `gold_margin_gain` and
`semantic_gold_gain`. Entropy remains useful but should be framed as an
uncertainty diagnostic, not as total step value.

## Implementation Scope

Smallest code change:

- preserve raw per-label scores from evaluator outputs;
- compute gold margin metrics in ASV core;
- compute semantic gold metrics in ASV core;
- expose both in `steps.jsonl`, `tables/steps.csv`, and live PubMed
  step-type analysis;
- update the quick report to make entropy ASV secondary.

Expected files:

- `asv_eval/core.py`
- `asv_eval/runtime.py`
- `asv_eval/reporting.py`
- `eval/asv/live_pubmed/analyze.py`
- focused ASV tests
- `eval/asv/experiments/live_pubmed_step_value/results.quick.md`

Avoid changing:

- evaluator prompts;
- agent behavior;
- PubMed retrieval;
- actor provider wiring;
- workflow state projection.

## Acceptance Criteria

The implementation is done when:

1. APOE `retrieve` has positive `gold_margin_gain` and positive
   `semantic_gold_gain`;
2. beta-carotene `retrieve` has positive `gold_margin_gain` and positive
   `semantic_gold_gain`;
3. the quick report no longer treats mean entropy net ASV as the headline
   value metric;
4. old `oracle_gold_log_likelihood_gain` remains present for compatibility;
5. provider-free ASV tests and the live quick pilot still pass.

## Non-Goals

- Do not add label smoothing as the primary metric.
- Do not add a learned embedding.
- Do not add a new evaluator model.
- Do not change gold visibility rules.
- Do not run the full 30-claim pilot until the three-claim quick pilot exposes
  the new metrics cleanly.

## Spec Self-Review

- Open-marker scan: no unresolved markers or open tasks remain.
- Internal consistency: margin uses raw scores; semantic gain uses belief
  probabilities and fixed label embeddings.
- Scope check: this is one metric-layer implementation plan, not an actor or
  retrieval change.
- Ambiguity check: `supported`, `refuted`, and `not_enough_information`
  embeddings are fixed and explicit.
