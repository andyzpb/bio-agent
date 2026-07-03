# Live PubMed ASV Quick Pilot Results

Date: 2026-07-03

Artifact root: `/tmp/asv-live-pubmed-step-value-quick`

## Scope

This was a balanced three-claim live pilot:

| claim_id | gold_label | status | PubMed papers |
| --- | --- | --- | --- |
| supported-apoe-ad-risk | supported | completed | 5 |
| refuted-beta-carotene-smokers | refuted | completed | 5 |
| nei-microglia-sufficient-ad | not_enough_information | completed | 2 |

PubMed retrieval was live. The ASV evaluator used `deepseek-chat` with chat
logprobs. The bio-agent actor still used fallback classify/plan paths because
the service instance did not have a framework LLM provider configured.

## Main Result

Final report: `/tmp/asv-live-pubmed-step-value-quick/report-observation`

| metric | value |
| --- | ---: |
| trajectories | 3 |
| steps | 33 |
| evaluated states | 66 |
| missing-label steps | 0 |
| floor-score steps | 0 |
| fallback evaluator steps | 0 |
| mean realized entropy reduction | -0.031967 |
| mean net ASV | -0.031967 |
| positive ASV steps | 2 |
| negative ASV steps | 4 |
| zero ASV steps | 27 |

The 12k state-text control matched the 6k run exactly, so the observed result
was not caused by the default state text truncation.

## Step-Type Summary

| step_type | count | mean_net_asv |
| --- | ---: | ---: |
| classify | 3 | -0.346574 |
| plan | 3 | -0.346574 |
| retrieve | 3 | 0.0 |
| extract | 3 | -0.346574 |
| draft | 3 | 0.346574 |
| audit | 3 | -0.005066 |
| post_audit | 3 | 0.346574 |
| validate_plan | 3 | 0.0 |
| advisory_verify | 3 | 0.0 |
| revise | 3 | 0.0 |
| finalize | 3 | 0.0 |

Full table:
`/tmp/asv-live-pubmed-step-value-quick/report-observation/tables/step_type_summary.csv`

## Claim-Level Behavior

The supported APOE claim had one meaningful transition: `retrieve` moved the
belief from `not_enough_information=1.0` to `supported=1.0`. Its entropy did
not change because both states were one-hot, so entropy-only ASV scored that
step as zero.

The beta-carotene refutation claim had the most movement. `retrieve` moved the
belief to `refuted=1.0`; `audit` improved the gold label rank to first with
`gold_log_likelihood_gain=0.470004`. Several metadata-heavy steps increased
uncertainty instead of reducing it.

The microglia sufficiency claim stayed at `not_enough_information=1.0` across
all steps.

## Interpretation

The live evaluator path works mechanically: DeepSeek returned usable label
logprobs for all 66 states, with no missing labels and no floor-score fallback.

The current ASV measurement is not paper-ready yet. Two issues matter most:

1. Entropy reduction misses correctness-changing label switches when both
   before and after beliefs are one-hot. The APOE retrieve step is the clean
   example: it changes the answer from NEI to supported, but ASV is zero.
2. Later workflow states often contain artifact IDs or audit metadata instead
   of compact evidence facts, so a state-grounded evaluator can lose access to
   the actual evidence after retrieval.

## Next Small Fix

Before the full 30-claim run, add a compact evidence-facts field to ASV states
and add a finite, epsilon-smoothed oracle gold log-likelihood gain. Then rerun
this same three-claim quick pilot. Only run the full pilot after the quick run
shows nonzero value for obvious evidence-acquisition steps like `retrieve`.
