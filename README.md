# Akashic Biomedical Evidence Agent

Read more about the design: https://andyzpb.github.io/blog/biomedical-evidence-agent/

Akashic is a plugin-based AI agent framework with memory, tools, background
workflows, channel integrations, and a FastAPI dashboard. This repository shows
how that framework can power a **research-only biomedical evidence agent**:
search papers, extract evidence, audit claims, and make every answer
inspectable.

Current biomedical baseline: **Release 1.6: Review Decision Loop**, with
generic Dashboard Chat and run-centric Trace/Audit/Export workspaces.

## Highlights

- **Evidence-first answers**: retrieval, extraction, evidence packets,
  synthesis, citation audit, logic audit, and revision are separate,
  inspectable steps.
- **Reviewable claims**: Evidence Graph v1 and Run Evidence Review turn each
  answer run into claim cards with support/refute/limitation links, reviewer
  decisions, trace, provenance, and graph hash.
- **Framework-native Dashboard Chat**: chat runs through the shared `dashboard`
  channel, agent loop, session history, event stream, and tool hooks; biomedical
  policy stays in the plugin.
- **Research-only safety**: clinical or patient-specific prompts are refused
  before memory, retrieval, LLM calls, export, or provenance work.
- **Toolized workflow**: retrieval, batch extraction, gap analysis, packet
  building, trace lookup, provenance export, Obsidian export, and release smoke
  are exposed as structured tools.
- **Works offline by default**: demos and evals use deterministic mock
  literature data. Live PubMed and OpenAI-compatible/Ollama LLM providers are
  opt-in.

## Dashboard

Run locally:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and select **Biomedical Evidence**. The panel is
review-first: ask a question, inspect the answer run, review claim support,
trace the evidence packet, and export redacted provenance when needed.

Try:

```text
What recent evidence links microglial activation to Alzheimer's disease progression?
```

Patient-specific clinical requests are refused by design. Dashboard Chat is a
generic framework channel, with sensitive biomedical write/export/review tools
blocked until durable approval and resume support exists.

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
