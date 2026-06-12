# Biomedical Evidence Evaluation

The lightweight evaluation harness uses deterministic mock data so it can run in CI without external API keys.

## Run

```bash
python -m eval.biomed_evidence.run_eval \
  --output /tmp/biomed_eval_results.json
```

## Metrics

- `citation_coverage`: answer runs with at least one citation.
- `schema_validity`: extracted evidence objects that validate against the Pydantic schema.
- `refusal_success`: clinical requests that are refused or redirected.
- `watch_precision`: watch decisions above threshold that are marked `push`.
- `retrieval_manifest_validity`: retrieval manifests contain IDs, queries, and returned paper IDs.
- `retrieval_repeatability`: repeated mock retrievals return the same ordered paper IDs.
- `retrieval_count_stability`: repeated retrievals return the same result count.
- `literature_access_ready`: source readiness check succeeded before answer eval.
- `literature_access_item_count`: papers returned by the readiness check.
- `literature_access_abstract_coverage`: fraction of readiness-check papers with stored abstracts.
- `literature_access_live`: whether the readiness check used a live source.
- `literature_search_manifest_validity`: controlled search returned a valid retrieval manifest.
- `literature_search_item_count`: normalized paper records returned by `search_literature`.
- `literature_search_stored_paper_count`: returned papers persisted for downstream workflows.
- `literature_search_abstract_coverage`: fraction of controlled-search records with abstracts.
- `literature_search_warning_count`: explicit warnings surfaced by controlled search.
- `multi_pass_plan_validity`: planner produced V2.6 retrieval subquestions.
- `multi_pass_query_count`: average executed retrieval records in the bounded multi-pass bundle.
- `multi_pass_manifest_coverage`: every executed retrieval record has a manifest.
- `multi_pass_dedupe_rate`: unique paper ratio across multi-query results.
- `coverage_matrix_validity`: V2.6 coverage rows have valid status, query, and subquestion IDs.
- `gap_detection_rate`: coverage gaps or sufficient-coverage stop reasons are recorded.
- `gap_followup_precision`: executed gap follow-ups have traceable returned/added paper IDs.
- `evidence_packet_schema_validity`: structured evidence packet is present and schema-consistent.
- `evidence_packet_traceability_rate`: evidence packet IDs match extracted evidence items.
- `unsupported_intermediate_summary_rate`: answer runs that bypassed the evidence packet path.
- `clinical_boundary_before_multi_pass_rate`: clinical requests refuse before multi-pass retrieval.
- `final_answer_uses_packet_only_rate`: final citations are drawn from packet paper IDs.
- `claim_support_rate`: audited atomic claims marked supported or partially supported.
- `citation_precision`: citations that support at least one audited claim.
- `unsupported_claim_rate`: audited claims that are uncited, irrelevant, or insufficiently supported.
- `overclaim_rate`: audited claims that upgrade evidence strength beyond what the citation supports.
- `conflict_awareness_rate`: answers that surface known contradicting or inconclusive evidence when present.
- `uncertainty_calibration_rate`: answers whose uncertainty is at least as cautious as the audit-derived uncertainty.
- `audit_trace_completeness`: audited answer runs that persist classify, plan,
  retrieve, extract, draft, audit, revise, post-audit, and finalize steps.
- `revision_success_rate`: runs where audit-required changes produce a revise, abstain, or refuse action.
- `overclaim_revision_success_rate`: audited overclaims that are softened, removed, abstained, or refused.
- `unsupported_claim_revision_success_rate`: unsupported claims that are removed or explicitly marked insufficient.
- `clinical_refusal_revision_success_rate`: clinical or patient-specific prompts that end in refusal.
- `project_context_application_rate`: project-aware answer runs that record project memory use in trace.
- `rejected_paper_exclusion_rate`: project-rejected papers excluded from answer evidence by default.
- `saved_paper_prioritization_rate`: project-saved papers are prioritized when present in retrieved results.
- `memory_not_used_as_evidence_rate`: project memory is not converted into evidence items.
- `review_queue_capture_rate`: audit/verifier issues are captured in the project review queue when present.
- `project_brief_audit_pass_rate`: project evidence briefs include audit-linked claims rather than memory-only claims.
- `project_trace_completeness`: project-aware runs expose original and filtered paper IDs in trace metadata.
- `clinical_boundary_before_memory_rate`: clinical requests refuse before project memory is loaded.
- `tool_schema_validity`: Release 1.0 tool contracts exist and declare the release envelope schema.
- `tool_output_schema_validity`: Release 1.0 tool calls return schema-valid envelopes.
- `tool_chain_parity_rate`: toolized packet building remains consistent with answer-run evidence.
- `clinical_boundary_before_tool_chain_rate`: clinical prompts are blocked before tool-chain retrieval.
- `live_source_policy_before_tool_chain_rate`: live PubMed policy can block live retrieval before execution.
- `memory_trace_completeness`: memory trace reports use, sources, effects, and `memory_as_evidence=false`.
- `memory_source_ref_validity`: memory source references point to stable biomedical project IDs.
- `tool_transition_trace_rate`: step telemetry exposes transition matrix and advisory-only status.
- `mean_tool_step_count`: average observed tool/trace step count.
- `p95_tool_step_count`: release smoke p95 step count approximation for local runs.
- `budget_compliance_rate`: over-budget tool requests fail with structured `budget_exceeded`.
- `structured_error_validity`: structured tool errors include code, recoverability, and next actions.
- `obsidian_frontmatter_validity`: exported Obsidian notes include required YAML frontmatter.
- `obsidian_duplicate_note_rate`: deterministic re-export duplicate path rate.
- `obsidian_export_not_imported_as_evidence_rate`: exported notes remain one-way reviewer artifacts.
- `submodular_packet_coverage_rate`: packet selection retains protected conflict/limitation evidence.
- `submodular_duplicate_reduction_rate`: packet selection does not increase duplicate evidence.
- `bandit_advisory_schema_validity`: retrieval advisory is schema-valid and advisory-only.
- `provenance_graph_validity`: provenance graph links answer, evidence, manifests, audit, revision, and tools.
- `prompt_injection_boundary_success_rate`: prompt-injection-like clinical requests still hit the clinical boundary.

## Release 1.0 Gate

The Release 1.0 mock gate is:

```bash
.venv/bin/python -m eval.biomed_evidence.run_eval \
  --output /tmp/biomed_eval_release_1_0.json
```

Expected release-specific checks should be `1.0` except
`obsidian_duplicate_note_rate`, which should be `0.0`. The mock gate does not
exercise live PubMed or real LLM network calls; those remain opt-in smoke
tests.

## Optional Live PubMed Eval

Real PubMed evaluation is opt-in and is not used by default CI:

```bash
python -m eval.biomed_evidence.run_eval \
  --source pubmed \
  --live-pubmed \
  --output /tmp/biomed_live_eval_results.json
```

For a narrower dashboard/API smoke before running full eval:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/check" \
  -H "Content-Type: application/json" \
  -d '{"query":"microglia Alzheimer disease","source":"pubmed","max_results":3}' | jq

curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"microglia Alzheimer disease","source":"pubmed","max_results":3,"retrieval_intent":"primary","require_abstract":true,"store":true}' \
  | jq '{source, item_count:.coverage.item_count, stored:.coverage.stored_paper_count, abstract_coverage:.coverage.abstract_coverage, retrieval_id:.retrieval_manifest.retrieval_id, warnings}'
```

## Interpretation

This evaluation checks engineering behavior, citation-audit behavior, and safety
boundaries. It is not a substitute for biomedical expert review, but it does
verify that the mock demo is traceable, deterministic, citation-audited,
revision-aware, and safe enough for portfolio review.
