# Biomedical Evidence Agent Responsible AI

The Biomedical Evidence Agent is a research support tool. It is not a clinical decision system.

## Research-Only Scope

- Supports literature search, evidence extraction, citation-grounded summaries, and project monitoring.
- Does not diagnose patients, recommend treatment, interpret private medical records, or replace expert review.
- Uses public literature and synthetic project context by default.

## Citation Policy

- Biomedical factual claims should be grounded in retrieved papers.
- If no citation is available, the agent must say so and avoid strong claims.
- Project memory is treated as user preference or project context, not biomedical fact.
- Retrieval manifests expose source, compiled query, pagination, result counts, warnings, and returned paper IDs so reviewers can inspect how evidence was found.
- Citation presence is not treated as sufficient. Claim-level audit separates
  supported, partially supported, overclaimed, contradicted, insufficient,
  irrelevant, and uncited claims.
- Release 1.0 routes toolized retrieval, extraction, packet construction,
  synthesis, audit, revision, export, and provenance through structured
  envelopes and persisted traces.
- Optional LLM revision can only be used as a framework-injected reviser over
  supplied evidence and citations. The deterministic citation audit remains the
  verifier of record.
- Optional claim-logic parsing can assist frame extraction, but deterministic
  logic-audit rules remain the entailment verifier of record.
- Biomedical Evidence Graph v1 validation checks structural evidence
  invariants, including supported-claim support edges, evidence-to-paper
  traceability, clinical refusal graphs without biomedical claims, and
  support/contradiction direction consistency.

## Tool And Memory Boundary

- Clinical or patient-specific prompts are refused before memory, retrieval,
  LLM calls, export, or provenance graph construction.
- Project memory can influence planner preferences, include/exclude terms,
  saved-paper priority, rejected-paper filtering, and review queues.
- Project memory, Watch topics, Obsidian notes, reviewer comments, and model
  drafts cannot satisfy citation support and cannot become evidence items.
- Release tool errors are structured and fail fast for `clinical_boundary`,
  `source_policy_blocked`, `budget_exceeded`, `export_path_blocked`,
  `unknown_run_id`, and related policy failures.

## Export And Provenance Boundary

- Obsidian export is one-way and disabled by default.
- Exported Markdown notes include `source_of_truth=biomed_sqlite` and
  `imported_as_evidence=false`.
- Provenance graphs link stable local IDs for answer runs, papers, evidence,
  manifests, packets, audits, revisions, activities, agents, and tools.
- Provenance output redacts raw prompts, raw provider responses, API keys, and
  secrets.
- Evidence Graph JSON export is read-only and recursively redacts raw prompt
  fields, provider responses, API keys, tokens, authorization headers, secrets,
  and common secret-like strings.
- Evidence Graph and Provenance Graph share stable local IDs, but the former is
  the claim/evidence/source relationship graph and the latter is the execution
  lineage graph.

## Advisory Math Boundary

- Submodular-style packet selection is deterministic and cannot drop protected
  conflict or limitation evidence for optimization convenience.
- Contextual-bandit-style retrieval advice is advisory-only. It suggests
  whether to stop, broaden, or run a bounded support/refute/mechanism/limitation
  query, but it cannot override caps or policy.
- Step telemetry and Markov-style transition summaries are descriptive only and
  cannot assert biomedical truth.

## Uncertainty Policy

The system raises uncertainty when evidence is conflicting, observational,
abstract-only, missing abstracts, heuristic-extracted, or based on small/animal
cohorts. The citation audit also derives an uncertainty calibration signal from
claim-support failures, retrieval warnings, conflicting evidence, and indirect
animal/in-vitro evidence.

When the audit detects unsupported, overclaimed, contradicted, or clinical-risk
claims, the revised answer should remove the claim, soften it, add limitations,
abstain, or refuse rather than present the draft as-is.

## Human Review

All evidence items include `requires_expert_review=true` by default. Researchers should inspect source papers, evidence spans, limitations, and conflicting findings before using outputs in research decisions.

## Data Handling

- Demo mode uses mock public-domain-style literature data.
- Secrets must be provided through environment variables or local config excluded from Git.
- Watch topics and biomedical evidence are stored in the local workspace database and can be deleted.
