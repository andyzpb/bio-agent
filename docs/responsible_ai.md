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
- Run Evidence Review surfaces graph validation, audit verdicts, evidence
  cards, and immutable graph snapshot metadata as a reviewer and eval gate. It
  does not turn graph structure into a new biomedical fact source, and it does
  not override deterministic citation audit.
- Full-text/PDF ingestion stores parser output as document sections, source
  hashes, and span locators only. Parser output is not biomedical evidence until
  extracted `EvidenceItem` records pass through packet selection, citation
  audit, logic audit, Evidence Graph validation, provenance, and Run Evidence
  Review.

## Tool And Memory Boundary

- Clinical or patient-specific prompts are refused before memory, retrieval,
  LLM calls, export, or provenance graph construction.
- Dashboard Chat is a generic framework channel, but biomedical safety still
  applies before memory/context preparation through the plugin before-turn
  guard.
- Project memory can influence planner preferences, include/exclude terms,
  saved-paper priority, rejected-paper filtering, and review queues.
- Project memory, Watch topics, Obsidian notes, reviewer comments, and model
  drafts cannot satisfy citation support and cannot become evidence items.
- Release tool errors are structured and fail fast for `clinical_boundary`,
  `source_policy_blocked`, `budget_exceeded`, `export_path_blocked`,
  `unknown_run_id`, and related policy failures.
- Sensitive biomedical write/export/review tools are marked as requiring
  confirmation. Until the framework provides durable approval and
  resume-after-approval, those tools deny from Dashboard Chat and do not write
  storage, export files, or record review decisions.

## Export And Provenance Boundary

- Obsidian export is one-way and disabled by default.
- Exported Markdown notes include `source_of_truth=biomed_sqlite` and
  `imported_as_evidence=false`.
- Provenance graphs link stable local IDs for answer runs, papers, evidence,
  manifests, packets, audits, revisions, activities, agents, and tools.
- Provenance output redacts raw prompts, raw provider responses, API keys, and
  secrets.
- Dashboard Chat streamed events and history responses redact raw prompts,
  provider raw responses, secrets, authorization headers, and API-key-like
  values before sending data to the browser.
- Evidence Graph JSON export is read-only and recursively redacts raw prompt
  fields, provider responses, API keys, tokens, authorization headers, secrets,
  and common secret-like strings.
- Run Evidence Review snapshots store redacted graph JSON and validation
  metadata so old answer-run reviews remain reproducible without exposing raw
  prompts, provider responses, or secrets.
- Evidence Graph and Provenance Graph share stable local IDs, but the former is
  the claim/evidence/source relationship graph and the latter is the execution
  lineage graph.
- Watch graph drift compares snapshots for reviewer QA. New papers, changed
  claims, support shifts, methods, limitations, and entity changes are advisory
  context only and cannot assert biomedical truth.

## Advisory Math Boundary

- Submodular-style packet selection is deterministic and cannot drop protected
  conflict or limitation evidence for optimization convenience.
- Contextual-bandit-style retrieval advice is advisory-only. It suggests
  whether to stop, broaden, or run a bounded support/refute/mechanism/limitation
  query, but it cannot override caps or policy.
- Step telemetry and Markov-style transition summaries are descriptive only and
  cannot assert biomedical truth.
- Argument Graph v2 support, attack, qualifier, limitation, and citation edges
  are advisory review signals linked back to Evidence Graph IDs. They do not
  replace citation audit or deterministic logic audit.

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
