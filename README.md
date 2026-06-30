# bio-agent

`bio-agent` is a research-only biomedical evidence workspace. The interesting
path is not a chatbot with citations at the end. It is a live PubMed run where
LLM stages plan, extract, synthesize, verify, revise, and parse claim logic, and
then the system audits every biomedical claim after the model writes it.

Read the design essay: https://andyzpb.github.io/blog/biomedical-evidence-agent/

Detailed manual: https://andyzpb.github.io/blog/bio-agent-deployment-guide/

The project is built on the Akashic plugin framework, but the biomedical layer
has its own safety boundary, retrieval policy, tool contracts, storage, audit
trail, and dashboard workspace. It is for literature research and review, not
clinical advice.

Current biomedical baseline: **Release 2.0: Full-Text Evidence Review**. The
strongest demo path is live PubMed plus DeepSeek/OpenAI-compatible LLM calls
with planner, extractor, synthesis, verifier, revision, support/refute search,
and claim-logic parsing enabled.

## Highlights

- **Live PubMed, not a fake demo**: the live path checks source readiness,
  stores retrieval manifests, persists papers, and keeps warnings visible
  before an LLM drafts anything.
- **All-LLM chain, narrow jobs**: planner, extractor, synthesis, advisory
  verifier, revision, and claim-logic parser can all run in one audited path.
  Each stage records mode, model, prompt hash, fallback reason, and trace data.
- **Post-synthesis citation audit**: the answer is parsed back into atomic
  claims after synthesis. Citations are checked against the evidence packet,
  producing claim support rate, citation precision, overclaim rate,
  uncertainty calibration, failed claims, and a recommended action.
- **LLM logic parser, deterministic judge**: the LLM can parse claim and
  evidence frames, but deterministic rules decide whether association,
  mechanism, animal or in-vitro evidence, weak evidence, or biomarker evidence
  actually entails the generated claim.
- **Review cockpit**: the dashboard keeps the final answer, audit checks,
  evidence items, packet limitations, scientific confidence, review priority,
  trace, full text, and review actions together.
- **Research-only boundary**: patient-specific or clinical requests are refused
  before memory, retrieval, LLM calls, export, or provenance work can run.
- **Offline by default**: deterministic mock literature keeps demos and evals
  repeatable. Live PubMed and provider-backed LLM calls are explicit opt-ins.

## Dashboard

Run locally:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and select **Biomedical Evidence**. The panel is
organized as Chat, Runs, Review Queue, Library, and Settings. Use Runs as the
main workbench: create or open an answer run, inspect the evidence packet,
audit claim support, compare pre/post-revision audit state, inspect claim logic,
and export redacted provenance when needed.

Try:

```text
What recent evidence links microglial activation to Alzheimer's disease progression?
```

Patient-specific clinical requests are refused by design. Dashboard Chat is a
generic framework channel, but Biomedical Evidence keeps the source policy,
tool contracts, LLM options, and command previews in the plugin.

### Dashboard Chat and `/biomed` commands

Dashboard Chat now includes a Codex-style `/biomed` command surface for
research-only biomedical workflows. The command layer stays framework-native:
commands preview into the shared dashboard chat route instead of bypassing the
agent loop, while deterministic control commands such as help and status return
directly without triggering an extra LLM response.

Useful commands:

```text
/biomed help
/biomed status
/biomed enable pubmed
/biomed check pubmed
/biomed audit "Evidence linking microglial activation to Alzheimer's disease progression" --source pubmed --papers 10 --llm all --support-refute
/biomed literature "TREM2 microglia Alzheimer" --source pubmed --papers 10
/biomed review biomed-run-...
/biomed export provenance biomed-run-...
```

The live audit command is the main high-signal path: live PubMed retrieval,
LLM planner, LLM extractor, LLM synthesis, LLM advisory verifier, LLM revision,
support/refute search, claim-logic parsing, post-revision audit, and trace
metadata in one run. The composer keeps common actions visible as compact
chips: Help, Status, Mock audit, and Live audit.

Dashboard screenshots and demo recordings are generated as release artifacts,
not committed to the source tree.

`/biomed status` separates PubMed command policy from network reachability, so
the UI can explain whether live PubMed is disabled by configuration or simply
unchecked. `/biomed enable pubmed` explicitly sets
`allow_live_pubmed_tools = true` in the active Biomedical Evidence config, after
which PubMed-backed audit and literature commands are no longer blocked by the
policy gate. Markdown answers are rendered as normal tables, lists, and code
blocks, while tool progress is folded into one compact work panel per assistant
turn instead of raw log spam. Completed audit and watch flows expose immediate
next actions in chat, including copyable run/watch IDs and review-oriented
artifact links where available.

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
# Optional Telegram/QQ/Feishu/Textual support: uv pip install -r requirements-optional.txt
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
