---
name: biomed-clinical-boundary
description: Enforce the biomedical research-only boundary before any retrieval, LLM, memory, export, or provenance workflow runs.
---

# Biomedical Clinical Boundary

## Goal

Use this skill whenever a biomedical request may involve patient-specific
diagnosis, treatment, dosing, prognosis, triage, or medical decision-making.

The boundary check must run before literature retrieval, project memory,
Obsidian export, LLM planning, extraction, synthesis, verifier, revision, or
claim-logic audit.

## Clinical Boundary Signals

Treat the request as clinical or patient-specific when it asks for:

- dose, dosage, titration, tapering, contraindications, or drug switching;
- what a named person should take or do medically;
- diagnosis, prognosis, emergency triage, or care decisions;
- interpreting symptoms, labs, scans, or individual records;
- choosing between treatments for a real person.

## Allowed Redirection

When a request crosses the boundary:

- refuse or redirect without retrieving literature;
- do not provide dose, diagnosis, treatment, or prognosis advice;
- suggest reframing as a general research question;
- recommend consulting a qualified clinician for patient-specific decisions.

Example redirection:

```text
I cannot provide patient-specific medical advice or dosing guidance. I can help
summarize research evidence about Alzheimer disease mechanisms or treatment
classes at a general, non-clinical level.
```

## Tool Rules

- Do not call `search_literature`, `run_multi_pass_literature_search`,
  `answer_with_evidence`, `answer_with_audit`, or saved workflow templates after
  a clinical boundary hit.
- If a saved template is used, require the template runner to fail fast with
  `clinical_boundary`.
- Memory, project notes, and Obsidian exports cannot soften this boundary.
- Advisory verifier or revision models cannot overrule this boundary.

## Safe Research Framing

If the user agrees to reframe, the next turn can use a research-only question
such as:

```text
What does recent literature report about medication class X in Alzheimer disease
research, including limitations and uncertainty?
```
