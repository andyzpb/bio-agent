# Biomedical Negative Trial Finding Design

## Problem

Logic audit currently conflates trial-level negative findings with universal no-effect conclusions. A claim such as "adding azithromycin did not improve clinical outcomes" can cite evidence that says nearly the same thing, but the LLM logic frame may parse the claim as `has_no_effect/definitive` and the evidence as `uncertain_or_inconclusive/inconclusive`. The citation audit then upgrades an otherwise aligned citation into `overclaimed`.

## Design

Add one predicate:

```text
no_observed_benefit
```

This means a study, trial, population, comparator, outcome, or timepoint did not show improvement or benefit. It is weaker than universal `has_no_effect` and stronger than directionless `uncertain_or_inconclusive`.

Use existing `qualifiers` for scope instead of adding a new schema object:

```text
trial_scoped
population_scoped
comparator_scoped
outcome_scoped
timepoint_scoped
```

## Rules

- `no_observed_benefit` supports the same predicate.
- `no_observed_benefit` only partially supports universal `has_no_effect`.
- `uncertain_or_inconclusive` does not entail `no_observed_benefit`.
- A trial-scoped `no_observed_benefit` claim should not be downgraded solely because the evidence modality is inconclusive when the evidence text reports the same negative finding.

## Touch Points

- `schemas.py`: allow the new predicate.
- `claim_logic.py`: deterministic predicate, claim modality, evidence modality, qualifiers.
- `service.py`: LLM prompt allowed values and LLM payload normalization.
- `claim_logic_rules.py`: entailment boundary rules.
- `citation_auditor.py`: avoid converting trial-level negative finding modality mismatch into overclaimed.
- `tests/test_biomed_claim_logic.py`: regression tests for azithromycin-style trial findings.

## Acceptance

The azithromycin example should produce `no_observed_benefit` frames and land as `entailed` or `partially_entailed`, not `overclaimed`, when claim and evidence are scope-compatible. A universal no-effect claim supported only by trial-level no-observed-benefit evidence should remain partial or overclaimed depending on wording.
