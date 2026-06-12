---
name: biomed-project-memory-watch
description: Manage biomedical project memory, Research Watch, reviewer decisions, and one-way Obsidian export without treating memory as evidence.
---

# Biomedical Project Memory And Research Watch

## Goal

Use this skill when a biomedical task needs project context, saved/rejected
papers, review queues, Research Watch topics, evidence briefs, or one-way
Obsidian export.

Project memory is preference and reviewer context only. It must never be cited
as biomedical evidence.

## When To Use

- The user wants to save, reject, or mark papers for review.
- The user wants a project evidence brief.
- The user wants Research Watch topic setup or manual checks.
- The user wants Obsidian Markdown export of packets, projects, or watch topics.
- The user wants to reuse prior project preferences during retrieval.

## Preferred Tool Sequence

For projects:

1. `list_biomed_projects` or `create_biomed_project`
2. `record_project_paper_decision` / `save_project_paper` /
   `reject_project_paper`
3. `record_project_claim` when a claim is linked to evidence/audit IDs
4. `list_project_evidence` or `list_project_review_queue`
5. `generate_project_evidence_brief`

For Research Watch:

1. `watch_research_topic`
2. `list_research_watch_topics`
3. dashboard/API manual check of the watch topic
4. inspect snapshot/diff decisions
5. export only after reviewing results

For Obsidian:

1. Build or retrieve an evidence packet, project, or watch topic.
2. Confirm one-way export is enabled.
3. Use the export tool.
4. Treat exported notes as reviewer artifacts, not importable evidence.

## Boundaries

- Memory can filter rejected papers or prioritize include keywords.
- Memory can add review queue context and reviewer notes.
- Memory cannot create biomedical facts.
- Obsidian notes cannot be imported back as citations or evidence.
- Watch decisions are triage signals until linked to retrieved papers and
  audited evidence.
- Clinical-boundary requests must stop before project memory or watch context is
  used.

## Useful Template Pairings

- `biomed-template-deep-audit` when project context should influence retrieval
  preferences but not evidence status.
- `biomed-template-pubmed-live-research` when the user explicitly opts into live
  PubMed and wants fresh project-aware retrieval.
