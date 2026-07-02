# NeMo Gym Biomedical Audit Revision Design

## Goal

Use NeMo Gym as the evaluation and rollout layer for Biomedical Evidence
post-training. The first version trains nothing. It proves that an
audit/revision task, verifier, reward, and rollout artifact format are stable
enough to feed later SFT, DPO, or RL work.

The target capability is audit/revision: given a draft biomedical answer and an
evidence packet, the model revises the answer so it is citation-grounded,
cautious, and free of unsupported or overclaimed biomedical claims.

## Approved Direction

- Use the two-step path: NeMo Gym eval and rollout data first, training method
  second.
- Start with audit/revision, not full tool workflow.
- Give the model a draft answer plus an evidence packet.
- Build the smallest NeMo Gym adapter around the existing harness and audit
  code.
- Deploy the workflow on the remote GPU server through Docker:
  `mrlab@10.94.125.131`.

## Architecture

The first environment is a single-step task:

```text
harness scenario
  -> Biomedical Evidence run
  -> draft answer + evidence packet
  -> NeMo Gym task prompt
  -> model revised answer + audit notes
  -> existing audit/verifier
  -> reward + rollout JSONL
```

Components:

- Task builder: converts existing biomedical harness scenarios into
  audit/revision tasks.
- Environment wrapper: runs each episode in a temporary workspace so real
  `.akashic-workspace` state is not touched.
- Verifier: reuses existing citation, claim, clinical-boundary, and harness
  gates.
- Rollout exporter: writes prompt, draft, evidence packet, model output,
  metrics, reward, and failure reason as JSONL.
- Training exporter: converts successful rollouts into at least one simple SFT
  JSONL format for later training.

Do not add a new biomedical service, dashboard runtime, approval broker, or
LLM judge in v1.

## Remote Docker Workflow

Local work remains the source of truth. Remote execution runs as a batch job:

```text
local repo
  -> sync or clone on mrlab@10.94.125.131
  -> build NeMo Gym Docker image
  -> run batch episodes with mounted artifacts
  -> inspect or pull rollout JSONL
```

Remote paths should be explicit:

- app: `/app`
- artifacts: `/artifacts`
- cache: `/cache`
- workspace base: `/workspace`

Use a separate NeMo Gym Docker image instead of the existing dashboard
`Dockerfile`. The current dashboard image is slim and CPU-oriented; the NeMo
Gym image needs a CUDA/PyTorch/NeMo-compatible base.

Secrets and live-provider settings stay in a remote `.env` file. They are not
committed. The v1 default source is `mock`, so the first smoke does not need
PubMed, DeepSeek, or OpenAI credentials.

## Data Contract

Input task fields:

- `scenario_id`
- `question`
- `draft_answer`
- `evidence_packet`
- `citations`
- `source`
- `constraints`

Model output fields:

- `revised_answer`
- `audit_notes`

Rollout fields:

- `task_id`
- `scenario_id`
- `prompt`
- `draft_answer`
- `evidence_packet`
- `model_output`
- `metrics`
- `reward`
- `passed`
- `failure_reason`
- `created_at`

The rollout artifact is JSONL. Each line must be self-contained enough to
recompute or inspect the reward without reading dashboard state.

## Reward

V1 reward is rule-based:

```text
reward = citation_precision - unsupported_claim_rate - overclaim_rate
```

Hard failures set reward to `0`:

- clinical or patient-specific behavior is not refused when it should be;
- output cannot be parsed into `revised_answer` and `audit_notes`;
- revised answer cites sources outside the evidence packet;
- verifier crashes or cannot produce metrics.

The verifier should preserve the existing Biomedical Evidence invariant:

```text
Memory, reviewer notes, model output, and project context may guide workflow.
Only retrieved papers, evidence spans, retrieval manifests, citation audit,
logic audit, and evidence packets may support biomedical claims.
```

## Testing And Acceptance

V1 acceptance:

- Deterministic smoke: run one mock audit/revision episode and write rollout
  JSONL with prompt, draft, packet, output, metrics, and reward.
- Verifier regression: an unsupported or overclaiming output scores lower or
  gets reward `0`.
- Training-readiness check: rollout JSONL converts to a simple SFT JSONL
  format.
- Remote Docker smoke: build and run the batch job on
  `mrlab@10.94.125.131` with mounted `/artifacts`, using `source=mock`.

Local checks for the implementation plan:

```text
.venv/bin/pytest -q tests/test_biomed_harness.py
.venv/bin/python -m eval.biomed_evidence.run_harness --scenario eval/biomed_evidence/sample_harness_scenarios.jsonl --output /tmp/biomed_harness.json --markdown /tmp/biomed_harness.md
```

Remote smoke shape:

```text
ssh mrlab@10.94.125.131 'cd /home/mrlab/bio-agent && docker compose -f docker-compose.nemo-gym.yml run --rm nemo-gym-smoke'
```

Use `/home/mrlab/bio-agent` as the default remote checkout path unless server
inspection shows that the repo already lives somewhere else.

## Non-goals

- No full multi-step tool-calling environment in v1.
- No live PubMed or live LLM requirement in the first smoke.
- No dashboard UI.
- No Kubernetes or Slurm job spec.
- No actual SFT, DPO, GRPO, or NeMo RL training run.
- No new judge model.
- No new biomedical evidence database tables.
