# Biomed Stateless ASV Kernel Design

## Context

Biomedical Evidence is currently strongest as a product artifact system:
retrieval manifests, evidence packets, audited answer runs, revisions,
Evidence Graph snapshots, review decisions, watch snapshots, provenance, and
Pilot Reports are durable records. That durability should remain.

The problem is narrower: `answer_with_audit` is still experienced as a large
workflow whose internal stage boundaries are easier to inspect after the fact
than to evaluate as first-class agent steps. The ASV evaluator now gives us a
standard way to measure the value of each action, but the biomedical workflow
needs explicit per-step state, action, observation, cost, warning, and artifact
records to feed it cleanly.

## Decision

Adopt a DSPy-like direction for the `answer_with_audit` main path:

```text
stateless execution kernel + persistent evidence artifacts
```

The workflow should move toward explicit input/output stage contracts while
leaving existing product persistence intact. The service and storage layer keep
owning database writes. The workflow kernel should be shaped so each stage can
be reasoned about as:

```text
StepInput -> StepOutput + ASV step metadata + domain artifacts
```

The first implementation slice should prioritize ASV evaluator integration over
a full DSPy optimizer layer.

## Non-Goals

- Do not rewrite `AgentLoop`, Dashboard Chat, message bus, memory runtime,
  session storage, or stream handling.
- Do not remove `biomed.db` or stop persisting evidence artifacts.
- Do not introduce a DSPy dependency in the first slice.
- Do not change existing public API, tool, dashboard, Pilot Report, or trace
  response shapes unless an additive field is required.
- Do not make live DeepSeek or PubMed required for tests.

## Recommended Approach

Use an ASV-native shadow kernel migration.

The first slice wraps the existing `answer_with_audit` path with a workflow
recorder rather than moving every stage into new pure functions immediately.
That recorder emits explicit biomedical workflow steps and exports them as an
ASV trajectory. Later slices can replace recorder boundaries with true
stateless stage functions one by one.

This gives us value quickly:

- existing behavior stays stable;
- ASV JSONL can be generated from real biomedical runs;
- stage state contracts become visible;
- future DSPy-like modules have a concrete migration target.

## Architecture

Keep the current outer entrypoint:

```text
BiomedEvidenceService.answer_with_audit(request)
```

Internally, introduce the workflow representation under:

```text
plugins/biomed_evidence/workflow/
  types.py
  recorder.py
  asv.py
```

The target workflow stages are:

```text
classify
plan
validate_plan
retrieve
extract
synthesize
audit
advisory_verify
revise
post_audit
finalize
```

Each recorded step should carry:

- `step_name`
- `input_state`
- `action`
- `observation`
- `output_state`
- `cost`
- `warnings`
- `errors`
- `artifact_ids`

The recorder should generate two projections:

1. Existing domain trace compatibility: `AgentTraceStep` remains the product
   trace used by dashboard, audit, review, and reports.
2. ASV trajectory: standard `TrajectoryRecord` data compatible with
   `python -m asv_eval evaluate`.

## ASV Contract

The first ASV candidate space for biomedical answer status is:

```text
supported
refuted
not_enough_information
```

The ASV trajectory should use the biomedical research question as the task
question and the candidate space above as the candidate set. For each workflow
stage:

- `state_before` summarizes the explicit artifacts available before the stage.
- `action` describes the module/tool action, policy settings, and source mode.
- `observation` summarizes the new evidence, artifact, audit result, or warning.
- `state_after` summarizes the explicit artifacts available after the stage.
- `cost` includes derivable `llm_call_count`, `source_call_count`,
  `prompt_tokens`, `latency_ms`, `artifact_cache_hit_count`, and related
  observability fields where available.

Belief values are not required during production execution. The trajectory must
support two evaluator modes:

- `provided_belief`: tests or fixtures provide `belief_before` and
  `belief_after`.
- `llm_evaluator`: a post-processing evaluator, such as the DeepSeek logprob
  evaluator, computes beliefs over the saved state snapshots.

This keeps product runs fast while making paper experiments reproducible.

## Data Flow

The first slice data flow is:

```text
AnswerWithEvidenceRequest
  -> existing answer_with_audit workflow
  -> WorkflowRecorder records stage states and observations
  -> existing AnswerWithEvidenceResult / audit / revision / trace persistence
  -> ASV trajectory export for the run
```

The service layer remains responsible for:

- reading project context and existing stored artifacts;
- calling the workflow;
- persisting answer runs, audits, revisions, trace steps, packets, and reviews;
- exposing API/tool outputs.

The recorder and ASV projection should be deterministic transformations over
request/result/audit/revision/trace/artifacts. They should not perform provider
calls or write storage.

## Error Handling

Clinical refusals, source-policy blocks, provider fallback, parser fallback,
schema validation failures, missing evidence, and skipped stages should appear
as explicit workflow steps rather than disappearing from ASV export.

Stage status should be preserved as one of the existing trace statuses where
possible. ASV observations should include warnings and fallback reasons, but
must redact prompts, raw provider payloads, secrets, authorization headers, and
secret-like values before export.

If ASV export cannot construct a valid trajectory for a saved run, the export
path should return a structured error that names the missing artifact or invalid
step instead of silently producing partial JSONL.

## Compatibility

Existing tests and consumers should keep working:

- `answer_with_audit` still returns the same `AnswerWithEvidenceResult` shape.
- `get_answer_trace` still returns the current trace surface.
- dashboard panels and Pilot Report continue to use current artifacts.
- the new ASV path is additive: a service method exports one run as a standard
  ASV `TrajectoryRecord`, and any API/tool surface that follows it wraps that
  same method.

The implementation may add trace metadata that points to the ASV projection,
but existing fields must not be repurposed.

## Testing

The first implementation plan should include tests for:

- mock `answer_with_audit` behavior remains stable;
- a saved audited answer run can be exported as one ASV trajectory;
- core stages include `state_before`, `action`, `observation`, `state_after`,
  `cost`, warnings, and artifact IDs where applicable;
- clinical refusal runs produce valid ASV trajectories with skipped or refused
  downstream steps;
- ASV export redacts prompt/raw-provider/secret-like data;
- the exported JSONL can be evaluated with `python -m asv_eval evaluate`.

Live DeepSeek and PubMed checks remain optional smoke tests, not the unit-test
baseline.

## Future Direction

After the ASV export is stable, migrate stages from recorder projections into
true stateless step functions:

```text
ClassifyStep
PlanStep
RetrieveStep
ExtractStep
SynthesizeStep
AuditStep
ReviseStep
FinalizeStep
```

Each step can then expose DSPy-like signatures and metric hooks. A later
optimizer layer can tune prompts, demonstrations, or model choices against ASV,
audit quality, citation precision, unsupported-claim rate, overclaim rate,
latency, and cost metrics.
