# Biomedical Negative Trial Finding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distinguish trial-level "no observed benefit" findings from universal no-effect conclusions in biomedical logic audit.

**Architecture:** Reuse the existing logic frame pipeline and add one predicate plus lightweight qualifier normalization. Keep the citation audit merge conservative by downgrading aligned negative trial findings instead of broadly weakening modality mismatch.

**Tech Stack:** Python, Pydantic schemas, pytest, pyright.

---

### Task 1: Add Regression Tests

**Files:**
- Modify: `tests/test_biomed_claim_logic.py`

- [ ] Add tests for deterministic parsing of `did not improve` trial findings.
- [ ] Add tests for LLM frame normalization from `has_no_effect` / `uncertain_or_inconclusive` to `no_observed_benefit`.
- [ ] Add tests that universal no-effect claims are not fully entailed by trial-level no-observed-benefit evidence.

### Task 2: Add Predicate and Parser Normalization

**Files:**
- Modify: `plugins/biomed_evidence/schemas.py`
- Modify: `plugins/biomed_evidence/claim_logic.py`
- Modify: `plugins/biomed_evidence/service.py`

- [ ] Add `no_observed_benefit` to `LogicPredicate`.
- [ ] Detect `did not improve`, `no benefit`, `failed to improve`, and `no significant improvement` as `no_observed_benefit`.
- [ ] Emit moderate modality and scope qualifiers for trial/population/comparator/outcome/timepoint wording.
- [ ] Normalize LLM predicate drift for negative benefit wording.

### Task 3: Add Logic Rules and Citation Merge Behavior

**Files:**
- Modify: `plugins/biomed_evidence/claim_logic_rules.py`
- Modify: `plugins/biomed_evidence/citation_auditor.py`

- [ ] Treat `no_observed_benefit` as matching itself.
- [ ] Treat `no_observed_benefit` evidence for universal `has_no_effect` claims as partial, unless universal wording is explicit enough to overclaim.
- [ ] Do not upgrade an aligned citation to `overclaimed` solely for a modality mismatch caused by trial-level negative finding wording.

### Task 4: Verify

**Files:**
- Test: `tests/test_biomed_claim_logic.py`
- Test: `tests/test_biomed_audit.py`
- Test: `tests/test_biomed_evidence.py`

- [ ] Run targeted claim logic tests.
- [ ] Run the biomed audit/evidence/dashboard test bundle.
- [ ] Run pyright on touched Python modules.
- [ ] Run `git diff --check`.
