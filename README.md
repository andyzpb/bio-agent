# Akashic Biomedical Evidence Agent

Read more about the design: https://andyzpb.github.io/blog/biomedical-evidence-agent/

Akashic is a plugin-based AI agent framework with memory, tools, background
workflows, channel integrations, and a FastAPI dashboard. This repository shows
how that framework can power a **research-only biomedical evidence agent**:
search papers, extract evidence, audit claims, and make every answer
inspectable.

Current biomedical baseline: **Release 2.0: Full-Text Evidence Review**, with
deterministic full-text/PDF ingestion, Research Watch graph drift, Argument
Graph v2, generic Dashboard Chat, and run-centric Trace/Audit/Export/Review
workspaces.

## Highlights

- **Evidence-first answers**: retrieval, extraction, evidence packets,
  synthesis, citation audit, logic audit, and revision are separate,
  inspectable steps.
- **Reviewable claims**: Evidence Graph v1 and Run Evidence Review turn each
  answer run into claim cards with support/refute/limitation links, reviewer
  decisions, trace, provenance, and graph hash.
- **Immutable graph snapshots**: answer runs can be backfilled into persisted
  Evidence Graph snapshots, stale snapshots are detected from newer audits,
  snapshot diffs are inspectable, and risky graph states are captured in the
  project review queue.
- **Full-text evidence locators**: known papers can store deterministic
  full-text/PDF parser output as document sections, source hashes, and
  section/page/character-offset locators. Parser output is not evidence until
  extracted `EvidenceItem` records pass through packet, audit, graph,
  provenance, and review contracts.
- **Release 2.0 reviewer signals**: Research Watch graph drift compares paper,
  claim, method, limitation, entity, and support-shift changes across
  snapshots; Argument Graph v2 links support/attack/qualifier relationships
  back to Evidence Graph node IDs. Both are advisory QA context, not evidence.
- **Codex-style Biomed workspace**: the plugin is organized around Chat, Runs,
  Review Queue, Library, and Settings. Runs are the main inspector surface for
  review, diff, trace, evidence packet, audit, logic, argument, math, and
  provenance artifacts; Library includes Watch drift and full-text inspection.
- **Framework-native Dashboard Chat**: chat runs through the shared `dashboard`
  channel, agent loop, session history, event stream, and tool hooks; biomedical
  policy stays in the plugin. Dashboard chat replies default to English unless
  the user asks for another language.
- **Research-only safety**: clinical or patient-specific prompts are refused
  before memory, retrieval, LLM calls, export, or provenance work.
- **Toolized workflow**: retrieval, batch extraction, gap analysis, packet
  building, trace lookup, provenance export, Obsidian export, and release smoke
  are exposed as structured tools.
- **Works offline by default**: demos and evals use deterministic mock
  literature data. Live PubMed and DeepSeek/OpenAI-compatible LLM calls are
  opt-in and covered by release smoke artifacts.

## Dashboard

Run locally:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and select **Biomedical Evidence**. The panel is
organized as Chat, Runs, Review Queue, Library, and Settings. Use Runs as the
main workbench: create or open an answer run, inspect review/snapshot status,
compare graph snapshots, trace the evidence packet, audit claim support, and
export redacted provenance when needed.

Try:

```text
What recent evidence links microglial activation to Alzheimer's disease progression?
```

Patient-specific clinical requests are refused by design. Dashboard Chat is a
generic framework channel, with sensitive biomedical write/export/review tools
blocked until durable approval and resume support exists.

Release 2.0 live smoke was validated with live PubMed plus DeepSeek
`deepseek-v4-flash`: `27/27` checks passed, including audited answer, trace,
evidence packet, provenance graph, and clinical guardrail checks.

## Quickstart

Requires Python 3.12. Node/npm is needed for dashboard and plugin panel builds.

```bash
git clone <this-repo>
cd bio-agent
uv venv
uv pip install -r requirements.txt
npm ci
uv run python main.py setup
uv run python main.py init
uv run python main.py dashboard
```

Docker dashboard:

```bash
docker compose up -d --build
```

## Documentation

| Topic | File |
| --- | --- |
| Architecture and trust model | [docs/architecture.md](./docs/architecture.md) |
| Biomedical plugin details | [plugins/biomed_evidence/README.md](./plugins/biomed_evidence/README.md) |
| Evaluation and release gates | [docs/evaluation.md](./docs/evaluation.md) |
| Deployment and local smoke | [docs/deployment.md](./docs/deployment.md) |
| Responsible AI boundary | [docs/responsible_ai.md](./docs/responsible_ai.md) |
| Case study | [cases/ki-biomed-research-assistant/README.md](./cases/ki-biomed-research-assistant/README.md) |

## License

Licensed under the [Apache License 2.0](./LICENSE).

> **License Note:** This project is a fork of
> [kachofugetsu09/akashic-agent](https://github.com/kachofugetsu09/akashic-agent),
> which is licensed under the MIT License. This fork has been relicensed under
> Apache 2.0 in accordance with MIT's permissive terms.
