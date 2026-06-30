# Biomedical Claim Role Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make audit/revision distinguish failed core claims from failed peripheral or search-meta claims.

**Architecture:** Add a small deterministic claim role classifier to the existing citation audit path. Store role and revision detail on existing Pydantic artifacts, then make deterministic revision delete peripheral/meta failures instead of doing broad string replacement.

**Tech Stack:** Python, Pydantic schemas, pytest, existing `plugins/biomed_evidence` audit/revision modules.

---

### Task 1: Claim Role And Action Aggregation

**Files:**
- Modify: `plugins/biomed_evidence/schemas.py`
- Modify: `plugins/biomed_evidence/citation_auditor.py`
- Test: `tests/test_biomed_audit.py`

- [x] **Step 1: Write failing tests**

Add tests that build supported core HPV claims plus failed peripheral microbiome/search-meta claims and assert `recommended_action == "pass_with_limitations"` while failed clinical/core claims still produce strict actions.

- [x] **Step 2: Verify tests fail**

Run: `.venv/bin/pytest -q tests/test_biomed_audit.py::test_peripheral_logic_failures_do_not_force_revise tests/test_biomed_audit.py::test_core_overclaim_still_forces_revise`

- [x] **Step 3: Implement minimal role fields and aggregation**

Add `ClaimRole` literal, `AtomicClaim.claim_role`, `ClaimAuditItem.claim_role`, `_claim_role()`, and role-aware `_recommended_action()`.

- [x] **Step 4: Verify tests pass**

Run the same targeted tests.

### Task 2: Deterministic Revision Detail

**Files:**
- Modify: `plugins/biomed_evidence/schemas.py`
- Modify: `plugins/biomed_evidence/service.py`
- Test: `tests/test_biomed_audit.py`

- [x] **Step 1: Write failing tests**

Add tests that unsupported search-meta claims are removed, peripheral failed lines are removed, malformed `is the is associated with of` never appears, and core overclaim uses a fixed safe sentence.

- [x] **Step 2: Verify tests fail**

Run targeted pytest for the new revision tests.

- [x] **Step 3: Implement minimal revision detail**

Add `revision_action_detail` to `AnswerRevision`; set `removed_peripheral_claims`, `rewritten_core_claims`, `unchanged`, or `abstained`; replace broad `_soften_claim_line()` behavior with delete-or-fixed-template logic.

- [x] **Step 4: Verify tests pass**

Run targeted pytest for the new revision tests.

### Task 3: Regression Gate

**Files:**
- Test: `tests/test_biomed_audit.py`
- Test: `tests/test_biomed_evidence.py`

- [x] Run `.venv/bin/pytest -q tests/test_biomed_audit.py tests/test_biomed_evidence.py`
- [x] Run `.venv/bin/pyright --level error plugins/biomed_evidence/schemas.py plugins/biomed_evidence/citation_auditor.py plugins/biomed_evidence/service.py tests/test_biomed_audit.py`
- [x] Run `git diff --check`
