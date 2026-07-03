# Live PubMed ASV Quick Pilot Results

Date: 2026-07-03

Artifact root: `/tmp/asv-live-pubmed-step-value-real-actor-20260703`

## Scope

This is the Phase 2 quick pilot: live PubMed retrieval, live DeepSeek-backed
bio-agent actor, and live DeepSeek logprob evaluator.

The two model roles are separate:

| role | provider | model |
| --- | --- | --- |
| bio-agent actor | deepseek | deepseek-v4-flash |
| ASV evaluator | deepseek | deepseek-chat |

Balanced three-claim set:

| claim_id | gold_label | status | papers | packet evidence | compact facts |
| --- | --- | --- | ---: | ---: | ---: |
| supported-apoe-ad-risk | supported | completed | 5 | 6 | 5 supported + 1 conflicting + 1 gap |
| refuted-beta-carotene-smokers | refuted | completed | 5 | 6 | 1 supported + 5 conflicting + 1 gap |
| nei-microglia-sufficient-ad | not_enough_information | completed | 1 | 2 | 2 supported + 2 gaps |

## Actor Coverage

Collector summary:
`/tmp/asv-live-pubmed-step-value-real-actor-20260703/collection/collection_summary.json`

| component | mode counts |
| --- | --- |
| classifier | llm: 3 |
| planner | llm: 3 |
| claim logic parser | llm: 30 |
| advisory verifier | llm: 3 |
| synthesis | llm: 1, fallback: 2 |
| revision | llm: 2, fallback: 1 |

The key Phase 2 gate is met: `planner_mode` is `llm` for all three planning
steps when the provider is configured.

## Evaluator Result

Final report: `/tmp/asv-live-pubmed-step-value-real-actor-20260703/report`

| metric | value |
| --- | ---: |
| trajectories | 3 |
| steps | 33 |
| evaluated states | 66 |
| missing-label steps | 0 |
| floor-score steps | 0 |
| fallback evaluator steps | 0 |
| mean realized entropy reduction | -0.063013 |
| mean net ASV | -0.063013 |
| positive ASV steps | 0 |
| negative ASV steps | 2 |
| zero ASV steps | 31 |

## Step-Type Summary

| step_type | count | mean_net_asv | mean_oracle_gold_log_likelihood_gain |
| --- | ---: | ---: | ---: |
| advisory_verify | 3 | 0.0 | 0.0 |
| audit | 3 | 0.0 | 9.21034 |
| classify | 3 | -0.346574 | 8.748242 |
| draft | 3 | 0.0 | 0.0 |
| extract | 3 | 0.0 | -9.21034 |
| finalize | 3 | 0.0 | -9.21034 |
| plan | 3 | -0.346574 | 8.748242 |
| post_audit | 3 | 0.0 | 0.0 |
| retrieve | 3 | 0.0 | 18.420681 |
| revise | 3 | 0.0 | 9.21034 |
| validate_plan | 3 | 0.0 | 0.0 |

Full table:
`/tmp/asv-live-pubmed-step-value-real-actor-20260703/report/tables/step_type_summary.csv`

## Claim-Level Behavior

The supported APOE claim kept the clean measurement signal:
`retrieve` moved `not_enough_information=1.0` to `supported=1.0`.
Entropy gain was `0.0`; `oracle_gold_log_likelihood_gain=27.631021`.

The beta-carotene refutation claim also moved correctly on retrieval:
`not_enough_information=1.0` to `refuted=1.0`, with
`oracle_gold_log_likelihood_gain=27.631021`.

The microglia sufficiency claim stayed at `not_enough_information=1.0` on
retrieval, so the Phase 1 negative retrieve jump disappeared in the real-actor
run. Later extract/finalize states still reduced oracle gain on average, which
is useful pressure for the next actor-quality pass.

## Interpretation

Phase 2 succeeded as a real end-to-end quick pilot:

1. live PubMed retrieval completed for 3/3 claims;
2. live actor provider coverage is recorded separately from evaluator coverage;
3. planning is LLM-backed for 3/3 claims;
4. DeepSeek evaluator returned usable label logprobs for all 66 states;
5. missing-label, floor-score, and evaluator fallback counts stayed zero.

Remaining caveat: this is not yet a fully LLM actor on every component.
Synthesis fell back on 2/3 claims and revision fell back on 1/3 claim after
adapter/audit checks. That is acceptable for Phase 2 measurement; the next
small fix is actor-quality hardening, not another evaluator repair.
