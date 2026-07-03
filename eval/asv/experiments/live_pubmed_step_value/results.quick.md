# Live PubMed ASV Quick Pilot Results

Date: 2026-07-03

Artifact root: `/tmp/asv-live-pubmed-step-value-quick-repair-20260703`

## Scope

This is the repaired Phase 1 quick pilot. PubMed retrieval was live. The ASV
evaluator used `deepseek-chat` with chat logprobs. The bio-agent actor still
used fallback classify/plan paths because the service instance did not have a
framework LLM provider configured.

Balanced three-claim set:

| claim_id | gold_label | status | papers | packet evidence | compact facts |
| --- | --- | --- | ---: | ---: | ---: |
| supported-apoe-ad-risk | supported | completed | 5 | 5 | 5 supported |
| refuted-beta-carotene-smokers | refuted | completed | 5 | 5 | 5 supported |
| nei-microglia-sufficient-ad | not_enough_information | completed | 1 | 2 | 2 supported + 2 gaps |

## Main Result

Final report: `/tmp/asv-live-pubmed-step-value-quick-repair-20260703/report`

| metric | value |
| --- | ---: |
| trajectories | 3 |
| steps | 33 |
| evaluated states | 66 |
| missing-label steps | 0 |
| floor-score steps | 0 |
| fallback evaluator steps | 0 |
| mean realized entropy reduction | -0.09452 |
| mean net ASV | -0.09452 |
| positive ASV steps | 0 |
| negative ASV steps | 3 |
| zero ASV steps | 30 |

The repair added two measurement fields without changing the evaluator prompt
contract:

- `state_after.evidence_facts` now carries compact evidence facts forward after
  retrieval, and later steps receive those facts in `state_before`.
- `gold_metrics.oracle_gold_log_likelihood_gain` now stays finite for
  zero-probability gold labels using epsilon `1e-12`.

## Step-Type Summary

| step_type | count | mean_net_asv | mean_oracle_gold_log_likelihood_gain |
| --- | ---: | ---: | ---: |
| advisory_verify | 3 | 0.0 | 9.21034 |
| audit | 3 | 0.0 | 0.0 |
| classify | 3 | -0.346574 | 8.748242 |
| draft | 3 | 0.0 | 9.21034 |
| extract | 3 | 0.0 | 9.21034 |
| finalize | 3 | 0.0 | 0.0 |
| plan | 3 | -0.346574 | 8.748242 |
| post_audit | 3 | 0.0 | 0.0 |
| retrieve | 3 | 0.0 | 9.21034 |
| revise | 3 | 0.0 | 0.0 |
| validate_plan | 3 | -0.346574 | 8.748242 |

Full table:
`/tmp/asv-live-pubmed-step-value-quick-repair-20260703/report/tables/step_type_summary.csv`

## Claim-Level Behavior

The supported APOE claim had one meaningful transition: `retrieve` moved the
belief from `not_enough_information=1.0` to `supported=1.0`. Its entropy did
not change because both states were one-hot, so entropy-only ASV scored that
step as zero. The repaired oracle metric now captures it:
`oracle_gold_log_likelihood_gain=27.631021`.

The beta-carotene refutation claim also had a correctness-changing retrieve
transition: `not_enough_information=1.0` to `refuted=1.0`, with
`oracle_gold_log_likelihood_gain=27.631021`.

The microglia sufficiency claim shows why Phase 2 should separate actor quality
from evaluator measurement. The retrieve step moved the belief away from the
gold `not_enough_information` label to `refuted=1.0`, giving
`oracle_gold_log_likelihood_gain=-27.631021`; later extract/draft/advisory
states moved back toward NEI. This is a useful negative control, not a
measurement failure.

## Interpretation

The live evaluator path works mechanically: DeepSeek returned usable label
logprobs for all 66 states, with no missing labels and no floor-score fallback.

The Phase 1 measurement repair succeeded:

1. Compact evidence facts are present in exported ASV states and persist into
   later steps.
2. The new oracle metric exposes correctness-changing one-hot transitions that
   entropy cannot see.
3. The report and step-type analysis now expose
   `oracle_gold_log_likelihood_gain`.

The main remaining caveat is unchanged: this is still live PubMed plus live LLM
evaluator, not live LLM actor plus live LLM evaluator. Classify/plan still use
fallback logic in the current service construction.

## Next Small Fix

Phase 2 should connect the existing `BiomedEvidenceService` construction to a
real actor provider and record actor-mode coverage. After that, rerun this same
three-claim quick pilot before expanding to the full 30-claim run.
