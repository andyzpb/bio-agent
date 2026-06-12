# Changelog

## Release 1.0 - 2026-06-12

Release 1.0 stabilizes the Biomedical Evidence plugin as a research-only,
toolized evidence workflow on top of the Akashic plugin framework.

### Added

- Release tool contracts with structured `release-tool-envelope-v1` outputs,
  tool metadata, stable IDs, warnings, errors, traces, and schema-valid failure
  responses.
- Fail-fast policy errors for clinical boundary, live-source policy, invalid
  input, unknown run/retrieval/paper IDs, budget exhaustion, export path policy,
  packet unavailability, and provenance unavailability.
- Toolized workflow APIs and tools for multi-pass retrieval, batch extraction,
  coverage-gap analysis, evidence-packet build/lookup, answer trace lookup,
  Obsidian export, and provenance export.
- Memory-context bridge metadata for project preferences, saved/rejected paper
  decisions, reviewer preferences, excluded terms, and workflow preferences,
  with explicit `memory_as_evidence=false` trace fields.
- Budget snapshots and step telemetry for workflow step counts, transition
  records, transition matrix summaries, and unusual-path warnings.
- One-way Obsidian Markdown export for evidence packets, projects, and Research
  Watch topics with deterministic filenames, YAML frontmatter, and wiki links.
- Deterministic evidence-packet selection with submodular-style coverage and
  redundancy scoring.
- Contextual-bandit-style retrieval advisory that recommends next search
  actions without controlling runtime or overriding safety policy.
- PROV/OpenLineage-compatible provenance graph export linking answer runs,
  papers, evidence, retrieval manifests, packets, audits, revisions, tools,
  activities, and agents while redacting prompts, secrets, and raw provider
  responses.
- Dashboard Trace polish for memory effects, budget snapshots, step telemetry,
  packet selection, Obsidian export, provenance export, and Release 1.0
  Responsible AI boundaries.
- Release 1.0 eval metrics for tool schema validity, output schema validity,
  tool-chain parity, policy-before-tool execution, memory trace completeness,
  structured error validity, Obsidian export safety, packet selection quality,
  advisory schema validity, provenance graph validity, and prompt-injection
  boundary success.

### Changed

- Reframed public documentation around the current Release 1.0 architecture
  rather than a feature-by-feature development log.
- Expanded README, plugin README, deployment, evaluation, responsible-AI, and
  agent handoff docs to describe the tool chain, safety boundary, release
  gates, and post-release hardening path.
- Kept `mock` as the deterministic default source while preserving opt-in live
  PubMed and Ollama/OpenAI-compatible smoke paths.

### Safety

- Clinical and patient-specific requests are blocked before memory, retrieval,
  LLM, export, or provenance work can run.
- Project memory, Obsidian notes, reviewer comments, Watch topics, and model
  output remain workflow context only; they cannot satisfy biomedical claims or
  citation support.
- Mathematical aids are advisory or deterministic packet-selection helpers.
  They cannot override citation audit, logic audit, source policy, result caps,
  or clinical refusal.

