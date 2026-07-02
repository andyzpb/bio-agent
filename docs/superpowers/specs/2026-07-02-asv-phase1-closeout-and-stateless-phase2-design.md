# ASV Phase 1 Closeout And Stateless Phase 2 Design

## Context

The ASV evaluator now has the core runtime path:

- standard ASV JSONL loading and writing;
- bio-agent workflow export from saved audited-answer runs;
- `provided-belief` evaluation;
- DeepSeek chat logprob belief filling;
- evaluator-safe state rendering and secret redaction;
- JSONL evaluator cache;
- evaluator provenance and coverage in reports;
- evaluated trajectory round-trip preserving `quality_flags`.

The remaining work should not expand the evaluator surface yet. The next goal is
to close Phase 1 with a real but optional live smoke, then immediately start the
first ASV-gated stateless bio-agent slice.

The guiding sequence is:

```text
Phase 1 closeout: prove the meter works on a real provider.
Phase 2 first slice: use the meter to guide stateless workflow contracts.
```

## Decision

Adopt a two-part next milestone:

```text
Milestone A: ASV live smoke and experiment bundle
Milestone B: ClassifyStep and RetrieveStep stateless slice
```

Milestone A is still Phase 1. It produces a reproducible experiment fixture and
an optional DeepSeek live smoke command. It does not add a new evaluator mode.

Milestone B is Phase 2. It introduces a small stateless workflow package for
`ClassifyStep` and `RetrieveStep` only. It does not rewrite the full
`answer_with_audit` path and does not move persistence into step functions.

Implementation should be planned in two documents after this spec is approved:

```text
Plan 1: Phase 1 closeout experiment bundle and optional live smoke
Plan 2: Phase 2 ClassifyStep/RetrieveStep stateless slice
```

Plan 2 can start after Plan 1's provider-free experiment bundle is in place.
The optional live DeepSeek smoke should be run before claiming Phase 1 closeout
when local credentials are available, but it must not block CI or offline
development.

## Non-Goals

- Do not require live DeepSeek in unit tests or CI.
- Do not make live PubMed a requirement for this milestone.
- Do not add DSPy as a dependency.
- Do not replace `answer_with_audit` as the production path.
- Do not migrate `synthesize`, `audit`, `revise`, or `finalize` in this
  milestone.
- Do not add a UI, dashboard panel, or hosted service for ASV yet.
- Do not add PyPI packaging or GitHub Actions changes in this milestone.
- Do not store API keys, raw provider payloads, or unredacted prompts in
  committed fixtures.

## Milestone A: Phase 1 Closeout

Milestone A turns the evaluator runtime from "tested" into "experiment-ready."

### Goals

1. Provide a small committed ASV experiment bundle that can be run offline with
   `provided-belief`.
2. Provide a secret-safe optional command for live DeepSeek logprob evaluation.
3. Verify evaluator cache reuse on a second run.
4. Verify report artifacts identify provider-native evaluator provenance.
5. Verify report artifacts and cache rows contain no secrets or raw provider
   payloads.

### Experiment Bundle

Add a small bundle under:

```text
eval/asv/experiments/biomed_step_value_smoke/
```

Required contents:

```text
README.md
trajectory.jsonl
beliefs.jsonl
expected_summary.provided_belief.json
```

The committed bundle should be provider-free. It should use a deterministic
trajectory with explicit states and a provided-belief fixture so any user can
run:

```bash
python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --belief-fixture eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl \
  --output-dir /tmp/asv-biomed-provided
```

The bundle should be small enough to inspect by hand. One trajectory with two
or three steps is enough. It should represent the biomedical status candidate
space:

```text
supported
refuted
not_enough_information
```

The trajectory should not contain real patient data, secrets, raw provider
responses, or long copyrighted passages.

### Optional Live DeepSeek Smoke

Add a documented live command but do not make it part of CI. The command should
use the repository virtual environment and the local shell environment that
loads `DEEPSEEK_API_KEY`.

Recommended shape:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m asv_eval evaluate \
    --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
    --evaluator deepseek-chat-logprob \
    --cache /tmp/asv-biomed-deepseek-cache.jsonl \
    --write-evaluated-trajectories /tmp/asv-biomed-deepseek-evaluated.jsonl \
    --output-dir /tmp/asv-biomed-deepseek'
```

The Phase 1 implementation plan should include a live smoke script or
documented manual command that verifies:

- exit code is `0`;
- `summary.json` has `evaluator.mode=deepseek-chat-logprob`;
- `steps.jsonl` has `quality_flags.evaluator_mode=deepseek_chat_logprob`;
- running the same command twice with the same cache reports cache-hit state
  count on the second run;
- cache and reports do not contain `Bearer`, `api_key`, `password`, `token=`,
  `raw_provider_response`, or raw provider payload fields.

Live smoke output should go to `/tmp` or another untracked directory. It should
not be committed. If local credentials are unavailable, the implementation
should still land the provider-free bundle and document the exact live command
as not run.

### Phase 1 Acceptance

Phase 1 is closed when:

- the provider-free experiment bundle runs with `--belief-fixture`;
- the optional live DeepSeek smoke command is documented and verified locally
  when credentials are present;
- the second live run demonstrates cache reuse;
- generated reports preserve evaluator provenance;
- no committed fixture contains secrets or raw provider responses;
- existing ASV and bio-agent regression tests still pass.

## Milestone B: Phase 2 First Stateless Slice

Milestone B begins the DSPy-like stateless bio-agent architecture. The first
slice is intentionally small:

```text
ClassifyStep
RetrieveStep
```

These steps create explicit contracts and ASV projections, while the current
service remains the production orchestrator and storage owner.

### Package Shape

Add a focused package:

```text
plugins/biomed_evidence/workflow/stateless/
  __init__.py
  types.py
  classify.py
  retrieve.py
  compare.py
```

Responsibilities:

- `types.py`: shared `StepInput`, `StepOutput`, and comparison result types.
- `classify.py`: deterministic clinical/research/refusal classification step.
- `retrieve.py`: retrieval request/result contract with mocked-source support.
- `compare.py`: old-projection vs stateless-projection comparison helpers.

The package should depend on existing schema types where practical, but its
core step functions should accept explicit dataclass inputs and return explicit
dataclass outputs.

### Step Contract

Each stateless step follows:

```text
StepInput -> StepOutput -> BiomedWorkflowStep -> ASV StepRecord
```

`StepInput` should include only explicit dependencies:

- run id;
- question;
- source policy;
- project context needed by the step;
- previous artifact references;
- provider/source settings for that step.

`StepOutput` should include:

- step name;
- status;
- domain result;
- artifact IDs or artifact payloads;
- warnings;
- errors;
- cost and observability fields;
- ASV projection hints.

The step function must not write storage, read session state, call dashboard
code, or mutate global state.

### ClassifyStep

`ClassifyStep` should answer:

```text
Is this request a biomedical research question the evidence workflow may answer?
```

The first version should be deterministic and provider-free. It can reuse the
existing clinical-boundary/refusal heuristics from the service layer where
available, but it should expose them through an explicit input/output contract.

Expected output fields:

- classification such as `research`, `clinical_advice_refusal`, or
  `unsupported_request`;
- refusal reason when applicable;
- warnings;
- cost with zero provider calls by default;
- ASV action/observation projection.

### RetrieveStep

`RetrieveStep` should answer:

```text
Given an allowed research question and source policy, which evidence artifacts
are available for downstream extraction?
```

The first version should support mocked sources only. It should not require
live PubMed. It should accept explicit mocked papers or retrieval artifacts in
the input and return deterministic artifact references and summaries.

Expected output fields:

- retrieval id or generated artifact id;
- source mode such as `mock`;
- retrieved paper summaries or artifact references;
- warnings;
- source call count and cache hit count where known;
- ASV action/observation projection.

### ASV Projection

Both stateless steps must be convertible to existing ASV records:

```text
StepOutput -> BiomedWorkflowStep -> trajectory_from_workflow_steps(...)
```

The projection should preserve:

- `state_before`;
- `action`;
- `observation`;
- `state_after`;
- cost;
- warnings;
- errors;
- artifact IDs.

The candidate space remains:

```text
supported
refuted
not_enough_information
```

Beliefs remain evaluator-provided or fixture-provided. Stateless steps do not
compute beliefs themselves.

### Comparison Harness

Add a comparison helper for fixtures:

```text
old saved-run workflow projection
new stateless step projection
-> comparison summary
```

The first comparison should check:

- same question;
- same candidate space;
- core step names present;
- ASV step count for the stateless slice;
- state/action/observation fields present;
- cost fields present;
- warnings preserved;
- no quality/provenance redaction regression.

The harness should not require the full `answer_with_audit` workflow to be
rewritten. It can compare a small old-projection fixture against a manually
constructed stateless fixture.

### Phase 2 Acceptance

Phase 2 first slice is accepted when:

- `ClassifyStep` and `RetrieveStep` exist as stateless step functions;
- both have deterministic unit fixtures;
- both produce `BiomedWorkflowStep` records;
- both can be turned into a standard ASV trajectory;
- the trajectory can be evaluated with provided beliefs;
- an old-vs-stateless comparison fixture is available;
- existing `answer_with_audit` tests still pass.

## Recommended Implementation Order

1. Add the Phase 1 experiment bundle with provided-belief fixture.
2. Add a documented optional live DeepSeek smoke command and smoke checklist.
3. Add tests that run the experiment bundle through `python -m asv_eval
   evaluate --belief-fixture`.
4. Add a secret scan test for the committed experiment bundle.
5. Add `workflow/stateless/types.py`.
6. Add `ClassifyStep` with deterministic tests.
7. Add `RetrieveStep` with mocked-source tests.
8. Add stateless step to `BiomedWorkflowStep` projection helpers.
9. Add old-vs-stateless comparison helper and fixture.
10. Run ASV report generation over the stateless trajectory with provided
    beliefs.

## Testing Strategy

Unit and CI tests:

- do not call DeepSeek;
- do not call live PubMed;
- use provided-belief fixtures;
- use mocked retrieval artifacts;
- assert no committed fixture contains secret-like strings;
- assert report provenance and evaluator coverage survive JSONL round-trip.

Optional local live test:

- uses `zsh -ic` so local shell config can provide `DEEPSEEK_API_KEY`;
- writes outputs under `/tmp`;
- runs twice with the same cache;
- records only summary facts in developer notes or PR text, not raw provider
  payloads.

## Risks And Mitigations

- Live provider instability:
  keep live smoke optional and separate from CI.
- Secret leakage:
  scan committed fixtures and generated smoke artifacts for secret markers.
- Stateless scope creep:
  restrict Phase 2 to `ClassifyStep` and `RetrieveStep`.
- Product regression:
  leave `answer_with_audit` as the production path and verify existing tests.
- ASV overfitting:
  use ASV as a coverage/regression gate, not as proof that every migrated step
  must increase entropy reduction.

## Open-Source Story

After this milestone, the project can show a complete first story:

```text
Export a real agent trace.
Evaluate each step with provided beliefs or a live LLM evaluator.
Inspect ASV, cost, provenance, cache behavior, and quality flags.
Start migrating the agent into stateless steps under the same metric.
```

That is the right v1 open-source wedge: the tool measures step value first, and
the bio-agent reference integration demonstrates how measurement guides agent
architecture rather than merely decorating it.
