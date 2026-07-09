# Qwen/DashScope ASV Provider Gate

Use this gate before any full Qwen replay. Qwen may support native `logprobs`,
but ASV likelihood scoring requires every physical option label to appear in
the returned `top_logprobs` for each scored state.

## E0: Source-label gate

```bash
zsh -ic 'python -m asv_eval probe-provider \
  --input eval/asv/experiments/asv_medium_openqa_20260705_live_main/collection/trajectory.jsonl \
  --output-dir eval/asv/experiments/asv_medium_openqa_20260705_dashscope_qwen37plus/gate_source \
  --provider dashscope \
  --model qwen3.7-plus \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --api-key-env DASHSCOPE_API_KEY \
  --top-logprobs 5 \
  --max-logprob-candidates 5 \
  --fallback-policy floor \
  --sample-trajectories 2 \
  --sample-steps 5 \
  --min-all-label-coverage 1.0 \
  --max-concurrency 4'
```

Expected for the current prompt: likely fails because `A/B/C/D` labels are
crowded out of DashScope top-5 by non-label continuations.

## E1: Numeric-label gate

```bash
zsh -ic 'python -m asv_eval probe-provider \
  --input eval/asv/experiments/asv_medium_openqa_20260705_live_main/collection/trajectory.jsonl \
  --output-dir eval/asv/experiments/asv_medium_openqa_20260705_dashscope_qwen37plus/gate_numeric \
  --provider dashscope \
  --model qwen3.7-plus \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --api-key-env DASHSCOPE_API_KEY \
  --top-logprobs 5 \
  --max-logprob-candidates 5 \
  --fallback-policy floor \
  --option-label-scheme numeric \
  --disable-thinking \
  --sample-trajectories 2 \
  --sample-steps 5 \
  --min-all-label-coverage 1.0 \
  --max-concurrency 4'
```

Run the full Qwen direct and rationale replay only if E1 passes. If E1 fails,
keep `provider_gate.json` as the artifact and stop.
