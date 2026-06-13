---
name: biomed-evidence-review
description: Run a research-only biomedical evidence review using controlled literature tools, evidence packets, audit, revision, trace, and provenance.
---

# Biomedical Evidence Review

## Goal

Use this skill for non-clinical biomedical research questions that need cited
evidence, traceable retrieval, claim-level audit, and a final revised answer.

The skill is a workflow guide. It does not answer from memory and does not treat
project notes, Obsidian exports, or reviewer comments as biomedical evidence.

## When To Use

- The user asks for recent or grounded biomedical research evidence.
- The user asks to compare support/refutation, mechanisms, limitations, or
  uncertainty across papers.
- The user wants an evidence packet, audit trace, provenance, or export after a
  biomedical answer.
- The user wants to inspect a completed answer run through Run Evidence Review
  claim cards, evidence cards, graph validation, or provenance links.

Do not use this skill for diagnosis, dosing, treatment choice, prognosis, or
patient-specific clinical advice. Use `biomed-clinical-boundary` first for those
requests.

## Preferred Tool Sequence

1. Run clinical-boundary classification before retrieval.
2. Use a saved workflow template when one fits the task:
   - `biomed-template-mock-ci` for deterministic checks.
   - `biomed-template-pubmed-live-research` for explicit live PubMed runs.
   - `biomed-template-deep-audit` for high-scrutiny review.
3. If no template fits, call the tools directly:
   - `plan_biomedical_search`
   - `search_literature` or `run_multi_pass_literature_search`
   - `extract_evidence_batch`
   - `analyze_coverage_gaps`
   - `build_evidence_packet`
   - `answer_with_audit`
   - `get_run_evidence_review`
   - `get_answer_trace`
   - `export_provenance_graph`
4. Use `source=mock` unless the user explicitly asks for live PubMed or the
   environment policy allows live sources.
5. Keep support/refute retrieval enabled for contested or uncertainty-heavy
   questions.

## Stop Conditions

Stop and return a structured refusal or error when:

- the request crosses the clinical boundary;
- live PubMed is requested but not explicitly enabled;
- the retrieval or evidence packet is empty;
- the tool budget is exhausted;
- audit recommends `refuse_or_abstain`;
- provenance or citation support cannot be inspected for material claims.

## Output Requirements

Return the final answer only after checking:

- citations are present for biomedical factual claims;
- evidence spans or abstracts support the cited claims;
- limitations and uncertainty are visible;
- audit/revision results are included or summarized;
- run IDs, retrieval IDs, packet IDs, and provenance are available when the user
  asks for inspection.
- Run Evidence Review is available for completed runs when reviewer-facing
  claim cards, graph snapshot status, or support reasons are needed.

Memory may guide retrieval preferences, but evidence must come from retrieved
papers and stored manifests.
