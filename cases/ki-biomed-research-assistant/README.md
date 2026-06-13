# KI Biomedical Research Assistant Case Study

## Problem

Biomedical researchers need to track fast-moving literature, compare claims across papers, preserve project context, and see exactly which citations support a summary.

## Solution

This case extends a collaborative Akashic plugin-based agent framework with a
Biomedical Evidence plugin:

- deterministic mock literature search and optional PubMed retrieval;
- controlled `search_literature` tool with retrieval manifests, coverage, and
  source trace;
- structured evidence extraction from abstracts;
- citation-grounded biomedical research answers;
- claim-level citation audit with support verdicts, overclaim detection, and
  uncertainty calibration;
- audit/revise answer loop with persisted draft, final answer, revision action,
  and trace steps;
- logic audit and symbolic fact export for inspectable overclaim checks;
- retrieval manifests for source, query, pagination, warnings, and returned
  paper IDs;
- typed Biomedical Evidence Graph v1 over papers, evidence spans, claims,
  entities, methods, limitations, retrieval manifests, packets, answer runs, and
  audits;
- snapshot-backed Run Evidence Review with claim cards, support reasons,
  evidence cards, graph validation, trace/provenance/export links, and
  clinical-refusal zero-claim reviews;
- Research Watch topics with relevance scoring, retrieval snapshots, and push/skip decision logs;
- review-first Codex-style dashboard workspace with `Review`, `Run`,
  `Projects`, `Watch`, `Advanced`, and `Boundary` surfaces.

## Demo

1. Start the dashboard:

   ```bash
   uv run python main.py dashboard
   ```

2. Open `http://127.0.0.1:2236`.
3. Select `Biomedical Evidence`.
4. Ask:

   ```text
   What recent evidence links microglial activation to Alzheimer's disease progression?
   ```

5. Create and check a watch topic:

   ```text
   spatial transcriptomics in tumor microenvironment
   ```

## Engineering Highlights

- Modular plugin implementation under `plugins/biomed_evidence`.
- Typed Pydantic schemas and SQLite storage.
- FastAPI routes shared by dashboard and tests.
- TypeScript dashboard panel using the existing plugin runtime.
- Mock evaluation harness for citation coverage, schema validity, refusal
  behavior, watch precision, retrieval reliability, and claim-level audit
  metrics, plus trace completeness and revision-success metrics.
- Retrieval reliability metrics for manifest validity and repeatability.
- Docker and CI support for reproducible review.

## Implemented Surface

The case is implemented as Portfolio V1, not only a prototype. It includes:

- registered agent tools for biomedical planning, controlled literature search,
  multi-pass retrieval, batch extraction, evidence-packet construction,
  answering, citation audit, conflict checks, Run Evidence Review, watch
  management, graph retrieval, provenance export, and one-way Obsidian export;
- `/api/biomed/*` FastAPI routes for dashboard use and automated tests;
- local SQLite persistence at `biomed_evidence/biomed.db`;
- deterministic mock data for offline demos and optional PubMed retrieval through NCBI E-utilities;
- idempotent paper, claim, entity, watch, decision, and answer-run persistence;
- persisted retrieval manifests, retrieval-paper links, and Watch snapshots;
- persisted answer audits and claim audits;
- persisted answer revisions and agent trace steps;
- Research Watch check events with push/skip decisions and relevance reasons;
- markdown, redacted JSON, graph, packet, and provenance export.

## Validation

The implementation has been checked with Python type checking, targeted
biomedical/API/graph tests, dashboard type checking, plugin/dashboard builds,
the mock biomedical eval runner, Docker dashboard rebuilds, and desktop/mobile
browser screenshot validation for the review-first workspace.

## Responsible AI Boundary

The system is for biomedical research support only. It does not provide clinical diagnosis, treatment recommendations, or patient-specific medical advice. Outputs require expert review.
