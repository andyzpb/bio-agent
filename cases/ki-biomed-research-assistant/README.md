# KI Biomedical Research Assistant Case Study

## Problem

Biomedical researchers need to track fast-moving literature, compare claims across papers, preserve project context, and see exactly which citations support a summary.

## Solution

This case extends a collaborative Akashic plugin-based agent framework with a
Biomedical Evidence plugin:

- deterministic mock literature search and optional PubMed retrieval;
- structured evidence extraction from abstracts;
- citation-grounded biomedical research answers;
- retrieval manifests for source, query, pagination, warnings, and returned paper IDs;
- lightweight evidence graph over papers, claims, entities, methods, datasets, and limitations;
- Research Watch topics with relevance scoring, retrieval snapshots, and push/skip decision logs;
- dashboard views for asking questions, inspecting evidence, reviewing graph structure, and checking responsible AI boundaries.

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
- Mock evaluation harness for citation coverage, schema validity, refusal behavior, and watch precision.
- Retrieval reliability metrics for manifest validity and repeatability.
- Docker and CI support for reproducible review.

## Implemented Surface

The case is implemented as Portfolio V1, not only a prototype. It includes:

- ten registered agent tools for biomedical search, paper fetch, extraction, answering, watch management, graph retrieval, and export;
- `/api/biomed/*` FastAPI routes for dashboard use and automated tests;
- local SQLite persistence at `biomed_evidence/biomed.db`;
- deterministic mock data for offline demos and optional PubMed retrieval through NCBI E-utilities;
- idempotent paper, claim, entity, watch, decision, and answer-run persistence;
- persisted retrieval manifests, retrieval-paper links, and Watch snapshots;
- Research Watch check events with push/skip decisions and relevance reasons;
- markdown and JSON report export.

## Validation

The implementation has been checked with Python type checking, targeted
biomedical/API tests, dashboard type checking, plugin/dashboard builds, the mock
biomedical eval runner, and a root Docker image build.

## Responsible AI Boundary

The system is for biomedical research support only. It does not provide clinical diagnosis, treatment recommendations, or patient-specific medical advice. Outputs require expert review.
