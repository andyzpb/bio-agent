# Biomedical Evidence Architecture

This document explains the design behind the Biomedical Evidence plugin. The
main README is intentionally short; this file keeps the deeper architecture,
tool-chain, trust-boundary, and provenance details.

## Design Goal

The Biomedical Evidence Agent is a research support workflow for biomedical
literature review. It is designed to answer questions only when each generated
claim can be traced back to retrieved papers, evidence spans, and audit records.

The central invariant is:

```text
Memory, reviewer notes, model output, and project context may guide workflow.
Only retrieved papers, evidence spans, retrieval manifests, citation audit,
logic audit, and evidence packets may support biomedical claims.
```

The system refuses diagnosis, treatment, dosing, prognosis, and
patient-specific medical requests before retrieval, memory loading, LLM calls,
or export steps run.

## Core Workflow

```text
user research question
  -> boundary classifier
  -> structured planner
  -> retrieval subquestions
  -> controlled literature search
  -> retrieval bundle
  -> evidence extraction
  -> coverage matrix
  -> bounded gap-directed follow-up
  -> evidence packet
  -> evidence-constrained synthesis
  -> citation audit
  -> logic audit
  -> advisory verifier
  -> revision
  -> final answer + citations + trace + eval record
```

The synthesis step receives a curated evidence packet. It does not consume raw
search noise, duplicate abstracts, untraceable summaries, project memory, or
reviewer notes as factual evidence.

## Framework Agent Surface

The Biomedical Evidence plugin sits on top of the shared agent framework. The
framework owns the generic agent runtime:

- inbound and outbound messages;
- passive turns;
- lifecycle phases;
- session history;
- memory retrieval;
- tool execution and tool hooks;
- event streaming;
- dashboard chat transport.

The plugin contributes biomedical behavior through normal extension points:

- registered tools;
- prompt render modules;
- before-turn modules;
- pre-tool hooks;
- FastAPI plugin routes;
- dashboard plugin panel.

This separation matters most for Dashboard Chat. Chat is a generic `dashboard`
channel. Browser messages are published as ordinary framework `InboundMessage`
objects, assistant output comes back through the agent loop, and lifecycle/tool
events are streamed as sanitized Server-Sent Events. Biomedical Evidence does
not own a separate chat backend, approval broker, or resume loop.

Sensitive biomedical actions, such as project writes, watch/template writes,
review decisions, and file exports, are marked through tool metadata. Until the
framework has durable approval and resume semantics, those actions are denied
from Dashboard Chat by plugin policy. Read-only evidence review, trace,
provenance, and evidence inspection stay available through ordinary tools and
workspace views.

## Trust Layers

| Layer | Role |
| --- | --- |
| Router and guardrail | Classify research vs clinical or clarification cases. |
| Planner | Produce structured query plans and retrieval subquestions. |
| Retrieval tool | Fetch papers from controlled sources and persist manifests. |
| Extractor | Convert paper abstracts into structured evidence spans. |
| Coverage and gap finder | Identify covered, weak, missing, conflicted, and source-limited areas. |
| Evidence packet | Compact, traceable contract consumed by answer generation. |
| Synthesizer | Draft a research answer from evidence only. |
| Citation audit | Check atomic claims against citations and evidence spans. |
| Logic audit | Detect semantic overclaims such as association-as-causation. |
| Advisory verifier | Optional LLM/judge signal that cannot override deterministic audit. |
| Reviser | Soften, limit, remove, abstain, or refuse unsupported claims. |
| Trace | Preserve each decision, fallback, manifest, and audit output. |

Optional LLM stages are explicit request flags:

- `use_llm_planner`
- `use_llm_extractor`
- `use_llm_synthesis`
- `use_llm_verifier`
- `use_llm_revision`
- `use_llm_claim_logic`

If an LLM provider fails, emits invalid JSON, or violates schema expectations,
the system records a fallback reason and falls back to deterministic behavior
where possible.

## Controlled Literature Search

`search_literature` is the core evidence retrieval tool. It returns:

- normalized paper records;
- source, query, and request trace;
- coverage metrics;
- stored paper IDs;
- warnings and errors;
- a retrieval manifest.

It does not synthesize answers and does not browse arbitrary websites.

`check_literature_access` is the readiness path for verifying `mock` or
`pubmed` connectivity before running the answer pipeline.

Supported sources:

- `mock`: deterministic, keyless default for demos, tests, and CI.
- `pubmed`: opt-in live PubMed E-utilities path.

Europe PMC remains the preferred next structured adapter after PubMed is stable.
General web search snippets are intentionally excluded from biomedical evidence.

## Multi-Pass Gap-Directed Retrieval

The planner can create subquestions such as:

- background;
- support;
- refute;
- mechanism;
- limitation;
- recent evidence.

Each query is executed through `search_literature`, deduped by stable paper ID,
and tied back to a retrieval manifest. The system then builds a coverage
matrix:

```text
subquestion | intent | papers | evidence | conflicts | limitations | status
```

Weak or missing coverage can trigger one controlled follow-up pass. The stop
reason is persisted, so reviewers can see whether the loop stopped because
coverage was sufficient, source limits were reached, policy blocked retrieval,
or no useful follow-up remained.

## Evidence Packet

The evidence packet is the handoff contract between retrieval/extraction and
answer generation. It contains:

- planner mode and source;
- retrieval manifest IDs;
- selected paper IDs;
- selected evidence IDs;
- supported claims;
- conflicting claims;
- limitations;
- coverage matrix rows;
- coverage gaps;
- stop reason;
- packet selection metadata.

The packet is intentionally smaller than the full retrieval bundle. It should
be inspectable, stable, and suitable for replay, audit, dashboard display, and
eval.

## Evidence Graph And Provenance Graph

Biomedical Evidence Graph v1 formalizes the claim/evidence/source relationships
that were previously only implicit in retrieval manifests, evidence packets,
answer runs, citation audits, and the lightweight dashboard graph. It is a typed
property graph with `schema_version=biomed-evidence-graph-v1`.

Evidence Graph nodes are research evidence objects:

```text
Paper
EvidenceSpan
Claim
Entity
Method
Limitation
RetrievalManifest
EvidencePacket
AnswerRun
AuditResult
```

The main evidence path is:

```text
RetrievalManifest -> Paper -> EvidenceSpan -> Claim
AnswerRun -> EvidencePacket -> EvidenceSpan
AuditResult -> Claim
```

This graph answers product questions such as:

- Which evidence spans support, contradict, qualify, or provide background for
  a biomedical claim?
- Which paper and retrieval manifest does each evidence span trace to?
- Which answer run used a packet, cited a claim, and received an audit result?
- Which entity, method, and limitation are attached to a claim or evidence
  span?

The Provenance Graph is a separate execution-lineage projection. It connects
activities, tools, agents, trace steps, run artifacts, packet construction,
audit, revision, and export events. It answers how an output was produced,
rather than whether a biomedical claim is supported.

The two graphs share stable IDs such as `run_id`, `paper_id`, `evidence_id`,
`retrieval_id`, `packet_id`, and `audit_id`, but they do not collapse into one
schema:

| Concern | Evidence Graph | Provenance Graph |
| --- | --- | --- |
| Primary question | What supports this claim? | How was this run produced? |
| Lifecycle | Reusable evidence projection | Usually run-scoped lineage |
| Main users | researcher, reviewer, agent tools | reviewer, developer, auditor |
| Export | redacted JSON property graph | PROV/OpenLineage-style lineage |

Graph validation is deterministic. It rejects supported claims without support
edges, evidence spans that do not trace to exactly one paper, clinical refusal
run graphs that contain biomedical claims, and direction-derived edges that
invert support and contradiction. JSON graph export is read-only and recursively
redacts prompt fields, raw provider responses, API keys, tokens, authorization
headers, and secret-like strings.

## Run Evidence Review

Run Evidence Review is the product-facing layer above Evidence Graph and
Provenance Graph. It is centered on an answer run rather than on raw nodes and
edges.

After audited answer generation or a manual run audit, the service creates an
immutable redacted Evidence Graph snapshot:

```text
AnswerRun + latest CitationAudit -> Evidence Graph v1 -> validation -> snapshot
```

The review response has `schema_version=biomed-evidence-review-v1` and
aggregates:

- snapshot metadata and graph hash;
- validation result;
- per-claim support status, audit verdict, support score, evidence card, paper
  IDs, evidence IDs, and limitations;
- run-level summary counts;
- links to graph, trace, provenance, and redacted JSON export.

Legacy runs can still be reviewed. If no persisted snapshot exists, the review
endpoint returns a derived review with `snapshot.status=missing`; the dashboard
then calls the snapshot backfill route and reloads the review.

Review validation is a UI and evaluation gate. It surfaces structural evidence
failures to reviewers and release metrics, but it does not convert graph
structure into new biomedical truth and it does not hard-fail answer generation.

## Citation And Logic Audit

Generated answers are decomposed into atomic claims. Each claim is checked
against cited papers and extracted evidence spans. The audit detects:

- missing citations;
- irrelevant citations;
- insufficient evidence;
- overclaiming;
- contradiction;
- conflict awareness gaps;
- uncertainty mismatch;
- clinical-safety violations.

The claim-logic layer can optionally ask an LLM to parse claim/evidence text
into typed logical frames. Deterministic Python rules remain the verifier of
record. Symbolic fact export makes the reasoning trace inspectable and ready
for future Datalog, Prolog, or solver experiments.

## Project Workspace And Research Watch

The biomedical plugin includes a project evidence workspace:

- save, reject, or mark papers as needing review;
- record project claims;
- generate evidence briefs;
- maintain a review queue;
- use project context as planning context only.

Research Watch tracks topics over time with retrieval snapshots, relevance
scoring, and push/skip decision logs. Saved project memory and Watch notes do
not become biomedical evidence unless they point back to retrieved papers and
evidence spans.

## Release Tool Chain

Release 1.0 turns the internal answer pipeline into independently callable,
auditable tools:

- `run_multi_pass_literature_search`
- `extract_evidence_batch`
- `analyze_coverage_gaps`
- `build_evidence_packet`
- `get_evidence_packet`
- `get_answer_trace`
- `export_evidence_packet_to_obsidian`
- `export_project_to_obsidian`
- `export_research_watch_to_obsidian`
- `export_provenance_graph`

All Release 1.0 tools return a structured envelope with:

- `ok`
- `result`
- `warnings`
- `errors`
- `error_code`
- `trace`
- `ids`
- tool metadata

Policy failures such as `clinical_boundary`, `source_policy_blocked`,
`budget_exceeded`, `export_path_blocked`, and `unknown_run_id` are returned as
schema-valid tool errors rather than unstructured strings.

## Mathematical Hardening

Release 1.0 adds deterministic or advisory math-oriented review aids without
handing them runtime authority:

- submodular-style evidence packet selection prioritizes coverage, provenance
  diversity, conflict evidence, and limitation evidence;
- contextual-bandit-style retrieval advisory suggests stop, broaden, support,
  refute, mechanism, or limitation searches but never overrides clinical
  guardrails, source policy, or caps;
- Markov-style step telemetry summarizes observed execution paths and expected
  remaining steps;
- PROV/OpenLineage-style provenance graphs connect answer, paper, evidence,
  retrieval manifest, packet, audit, logic audit, revision, tools, activities,
  and agents while redacting prompts and provider raw responses.
- Evidence Graph validation is a structural guardrail: it can fail graph
  products that violate claim/evidence/source boundaries, but it does not infer
  new biomedical facts.

These tools are used for reviewer visibility, debugging, and future evaluation.
They are not treated as biomedical evidence.

## Dashboard Views

The dashboard surfaces the workflow as a Review-first, Codex-style workspace:

- **Review**: default entry point for answer-run evidence QA. It shows recent
  runs, graph snapshot status, validation, claim cards, support reasons,
  evidence cards, audit action, and links to trace, provenance, raw graph, and
  redacted export.
- **Run**: template-first citation-grounded answer workflow with optional LLM
  stages, support/refute retrieval, packet summary, and project context.
- **Projects**: paper decisions, claims, review queue, and evidence briefs.
- **Watch**: topic monitoring, snapshots, relevance scores, and decisions.
- **Advanced**: raw evidence browser, typed Evidence Graph v1 explorer,
  run-centric Audit, run-centric Trace/Export, related/directed path lookup,
  and JSON export.
- **Boundary**: research-only boundary, memory-as-context policy, clinical
  refusal behavior, and retrieval limitations.

Trace/Export and Audit are run-centric. A reviewer starts from recent answer
runs, loads the trace or latest audit, then inspects the evidence packet,
provenance graph, or one-way Obsidian export for the same run.

## Data Boundaries

Runtime storage lives under the active workspace:

```text
biomed_evidence/biomed.db
```

Default runtime data is usually under:

```text
~/.akashic/workspace/
```

Generated Obsidian Markdown export is one-way reviewer output. Exported notes
are never imported back as biomedical evidence.

Secrets, prompt text, and provider raw responses are redacted from provenance,
Evidence Graph JSON export, and release smoke artifacts.

## Release Smoke

Release 1.1 adds a repeatable dashboard-level smoke runner for the live PubMed
and DeepSeek path:

```bash
.venv/bin/python -m eval.biomed_evidence.run_release_smoke \
  --source pubmed \
  --deepseek-model deepseek-v4-pro \
  --output-dir /tmp/biomed_release_smoke
```

The runner captures artifacts for:

- DeepSeek model/chat connectivity;
- dashboard plugin and release tool-contract readiness;
- live PubMed readiness and controlled `search_literature`;
- PubMed + DeepSeek `answer/audited`;
- persisted trace, evidence packet, retrieval manifest, and provenance graph;
- clinical guardrail regression.

Exit codes distinguish code regression, external source instability, LLM
unavailability, policy/guardrail failure, and dashboard unavailability.

## Non-Goals

- Clinical diagnosis, treatment, dosing, prognosis, or patient-specific advice.
- Treating project memory, Obsidian notes, saved papers, or reviewer comments
  as biomedical facts.
- Replacing deterministic audit with an advisory verifier.
- Making live PubMed the default source in CI or demos.
- Using general web search snippets as biomedical evidence.
- Adding full-text/PDF ingestion before abstract-level provenance and audit
  gates remain stable.
