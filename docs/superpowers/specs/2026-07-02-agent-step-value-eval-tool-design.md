# Agent Step Value Evaluation Tool Design

## Goal

Build an open-source evaluation tool for Agent Step Value (ASV): a
step-level value measure for LLM agent trajectories. The first version focuses
on RQ1: how to define, compute, and validate the marginal value of each
intermediate agent action.

The tool should feel closer to a DSPy-style stateless evaluation pipeline than
to a long-running agent runtime. Every module receives explicit inputs and
returns explicit outputs. The evaluator does not own sessions, background
state, tools, or a database.

## Approved Direction

- Support the standard ASV JSONL format plus two first-party adapters:
  bio-agent and ReAct.
- Keep the architecture generic so future DSPy-native adapters can be added,
  but do not require a DSPy dependency in v1.
- Support both explicit state/belief inputs and automatic reconstruction from
  trace events.
- Support closed-set classification and open QA schemas, while making
  closed-set classification the v1 experiment path.
- Make the LLM evaluator first-class.
- Use DeepSeek chat-completion token logprobs as the primary belief estimator
  when available.
- Fall back to prompt-scored LLM evaluation when token logprobs are missing,
  incomplete, or unusable.

## Architecture

The pipeline is:

```text
raw trace
  -> adapter
  -> normalized trajectory
  -> state builder
  -> belief evaluator
  -> ASV calculator
  -> validation report
```

Core modules:

- `TraceAdapter`: converts a source trace format into normalized trajectory
  records.
- `StateBuilder`: returns `X_t` and `X_{t+1}` for each step. If the input
  already includes state and belief, it passes those through. If not, it
  accumulates observations into a state object.
- `BeliefEvaluator`: estimates `p(Y_q | X_t)` for each state.
- `ASVCalculator`: computes entropy reduction, action cost, net ASV, and
  cumulative ASV.
- `Validator`: computes step-level, trajectory-level, and intervention-ready
  validation artifacts.
- `Reporter`: writes JSONL, JSON summary, CSV tables, and a Markdown report.

Each module is stateless. Caching is allowed only through an explicit cache
object or file path passed into the run.

## Data Contracts

### Standard Trajectory JSONL

Each line represents one trajectory:

```json
{
  "trajectory_id": "traj-001",
  "task": {
    "task_id": "pubmedqa-001",
    "question": "Does intervention X improve outcome Y?",
    "candidate_space": {
      "type": "closed_set",
      "candidates": [
        {"id": "yes", "label": "A", "text": "yes"},
        {"id": "no", "label": "B", "text": "no"},
        {"id": "maybe", "label": "C", "text": "maybe"}
      ],
      "gold_candidate_id": "yes"
    }
  },
  "steps": [
    {
      "step_id": "s1",
      "index": 0,
      "action": {"type": "search", "query": "intervention X outcome Y"},
      "observation": {"text": "retrieved paper summaries"},
      "state_before": null,
      "state_after": null,
      "belief_before": null,
      "belief_after": null,
      "cost": {"prompt_tokens": 1200, "tool_calls": 1, "latency_ms": 800},
      "label": "useful"
    }
  ],
  "final_score": 1.0,
  "success": true
}
```

The schema supports open QA through a candidate set:

```json
{
  "type": "candidate_set",
  "candidates": [
    {"id": "c1", "label": "A", "text": "candidate answer 1"},
    {"id": "c2", "label": "B", "text": "candidate answer 2"}
  ],
  "gold_candidate_id": "c1"
}
```

Open QA candidate generation is outside the v1 core. Users can provide
candidates directly. A post-v1 candidate-generation adapter may add them as an
explicit preprocessing step without changing the ASV schema.

### Normalized Step Output

The evaluator writes one JSONL row per step:

```json
{
  "trajectory_id": "traj-001",
  "step_id": "s1",
  "candidate_log_scores_before": {"yes": -1.2, "no": -2.8, "maybe": -0.7},
  "candidate_log_scores_after": {"yes": -0.2, "no": -4.1, "maybe": -2.3},
  "belief_before": {"yes": 0.34, "no": 0.07, "maybe": 0.59},
  "belief_after": {"yes": 0.83, "no": 0.02, "maybe": 0.15},
  "entropy_before": 0.824,
  "entropy_after": 0.510,
  "cost": 0.04,
  "asv": 0.274,
  "gold_log_likelihood_gain": 1.04,
  "evaluator_mode": "deepseek_logprob",
  "warnings": []
}
```

## DeepSeek Logprob Belief Evaluator

DeepSeek's chat-completion API supports `logprobs` and `top_logprobs` for
generated output tokens. The v1 evaluator uses this as a forced-choice label
scorer.

For closed-set candidates, each candidate receives a single ASCII label:
`A`, `B`, `C`, and so on. The prompt asks the model to output exactly one
label, with `max_tokens=1`, `temperature=0`, `logprobs=true`, and
`top_logprobs=20`.

The evaluator extracts the first generated token's top logprobs and maps label
tokens back to candidate IDs. It then normalizes log scores with softmax:

```text
belief(y_i | X_t) = exp(score_i) / sum_j exp(score_j)
```

If a label is absent from `top_logprobs`, the evaluator records a warning and
uses one of these policies:

1. Use a configured floor score, default `-20.0`.
2. If too many labels are missing, fall back to prompt-scored LLM evaluation.

The raw logprob response is retained in redacted output for auditability.

This is provider-native token scoring for the label choice, not a claim that
the full long-form answer probability has been measured. Long-form open QA is
therefore represented as a labeled candidate set before scoring.

## Fallback LLM Score Evaluator

When token logprobs are unavailable or incomplete, the fallback evaluator asks
the LLM to assign comparable log-style support scores to each candidate:

```json
{
  "scores": [
    {"candidate_id": "yes", "log_score": -0.4, "rationale": "..."},
    {"candidate_id": "no", "log_score": -3.1, "rationale": "..."}
  ]
}
```

The output scores are normalized with the same softmax path. Reports must mark
these rows as `evaluator_mode=llm_score` so experiments can separate
provider-native logprob scoring from prompt-scored estimation.

## Adapters

### Standard ASV JSONL

This adapter validates and passes through the standard schema. It is the
reference input format for external users.

### bio-agent Adapter

The bio-agent adapter reads existing Biomedical Evidence artifacts:

- `AgentTraceStep` rows;
- answer run metadata;
- retrieval manifests;
- evidence packets;
- citation audit and revision records;
- run observability fields such as prompt tokens, source calls, and latency.

It maps trace steps such as `plan`, `retrieve`, `extract`, `draft`, `audit`,
`revise`, and `finalize` into ASV step records. The first version should use
mock or saved runs by default. It must not mutate `.akashic-workspace` or the
Biomedical Evidence database.

### ReAct Adapter

The ReAct adapter supports two forms:

- structured JSONL with `thought`, `action`, `observation`, and optional
  `final_answer`;
- plain transcript parsing for common `Thought:`, `Action:`, `Observation:`,
  and `Final:` blocks.

The adapter keeps parsing conservative. Ambiguous transcripts should produce
warnings rather than guessed actions.

## ASV Computation

For each step:

```text
ASV_t = H(Y_q | X_t) - H(Y_q | X_{t+1}) - lambda * C(a_t)
```

Where:

- `H` is entropy over the normalized belief distribution.
- `C(a_t)` is a configured scalar cost from tokens, tool calls, latency, and
  optional risk weights.
- `lambda` defaults to `0.0` for pure information-gain experiments and can be
  configured per run.

When a gold candidate exists:

```text
G_t = log p(y* | X_{t+1}) - log p(y* | X_t)
```

The report keeps both ASV and `G_t` because ASV measures uncertainty reduction,
while `G_t` measures movement toward the known correct answer.

## Validation Report

The v1 report includes:

- step-level discrimination: AUROC, AUPRC, precision@k, and mean ASV by
  `useful`, `useless`, and `harmful` labels when labels are present;
- oracle movement: Spearman correlation between ASV and gold
  log-likelihood gain, plus AUROC for predicting `G_t > 0`;
- trajectory-level prediction: cumulative ASV, correlation with final score,
  and success/failure distribution summaries;
- baseline comparison hooks: relevance score, retriever score,
  confidence-only gain, token length, step index, random score, and ASV;
- intervention manifest: step IDs for removing highest-ASV, lowest-ASV, and
  random steps. V1 writes the manifest but does not rerun arbitrary agents.

## CLI Shape

Proposed commands:

```bash
python -m asv_eval evaluate \
  --input trajectories.jsonl \
  --adapter asv-jsonl \
  --evaluator deepseek-logprob \
  --candidate-mode closed-set \
  --output-dir /tmp/asv-report

python -m asv_eval adapt-bio-agent \
  --workspace /path/to/.akashic-workspace \
  --run-id biomed-run-... \
  --output /tmp/trajectory.jsonl

python -m asv_eval adapt-react \
  --input react_transcripts.jsonl \
  --output /tmp/trajectory.jsonl
```

The public v1 module path is `asv_eval`, and the CLI should preserve these
verbs and concepts.

## Error Handling

- Invalid trajectory rows fail fast with row number and schema path.
- Missing candidate labels fail before evaluator calls.
- Missing DeepSeek credentials fail with a clear auth error unless a fallback
  evaluator is configured.
- Logprob responses with missing labels are marked with warnings and either
  floor-filled or routed to fallback.
- Provider outputs are redacted before being written to report artifacts.
- Adapter ambiguity produces warnings and partial output, not silent guessed
  state.
- The tool never treats project memory, reviewer notes, or model output as
  biomedical evidence in the bio-agent adapter.

## Testing And Acceptance

V1 acceptance:

- A deterministic unit test computes entropy, softmax, ASV, cumulative ASV, and
  gold log-likelihood gain from fixture log scores.
- The standard ASV JSONL adapter validates a minimal closed-set trajectory.
- The ReAct adapter parses a fixture transcript into ordered steps.
- The bio-agent adapter converts a fixture or mock Biomedical Evidence run
  into standard ASV trajectory JSONL without mutating storage.
- The DeepSeek logprob evaluator is covered by a mocked API response including
  `top_logprobs` for labels `A`, `B`, and `C`.
- Missing-label logprob responses trigger floor or fallback behavior with
  explicit warnings.
- The reporter writes step JSONL, summary JSON, CSV tables, Markdown, and an
  intervention manifest.

Suggested local checks for the implementation plan:

```bash
.venv/bin/pytest -q tests/test_asv_eval.py tests/test_asv_adapters.py
.venv/bin/python -m asv_eval evaluate \
  --input eval/asv/sample_trajectories.jsonl \
  --adapter asv-jsonl \
  --evaluator mock-logprob \
  --output-dir /tmp/asv_eval_smoke
```

## Non-goals

- No RL training, PIRL, PPO, GRPO, controller, or stopping policy in v1.
- No long-running agent runtime.
- No dashboard UI.
- No new Biomedical Evidence database tables.
- No live PubMed dependency for the first smoke.
- No claim that token logprobs over short labels equal calibrated probabilities
  for long-form answers.
- No automatic rerun of arbitrary agents for intervention tests in v1.
