# Live PubMed Step Value Experiment

This experiment is the paper-facing ASV live-agent study. It runs the real
biomedical evidence workflow with live PubMed retrieval, freezes ASV
trajectories, and evaluates step value with the DeepSeek chat-logprob evaluator.

gold labels are used only after belief estimation. They must not appear in
evaluator prompts.

## Claim Set

`claims.quick.jsonl` contains three smoke-test questions, one per label.
`claims.pilot.jsonl` contains 30 curated biomedical claim-verification questions
balanced across:

- `supported`
- `refuted`
- `not_enough_information`

## Live Collection

Run only on a machine with provider credentials configured through the shell.
The command writes artifacts under `/tmp` so live provider outputs are not
committed by accident.

This is a balanced three-claim run for quick verification:

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.collect \
    --claims eval/asv/experiments/live_pubmed_step_value/claims.quick.jsonl \
    --workspace /tmp/asv-live-pubmed-step-value/workspace \
    --output-dir /tmp/asv-live-pubmed-step-value/collection \
    --ack-live'
```

For the full 30-claim run, switch `--claims` to
`eval/asv/experiments/live_pubmed_step_value/claims.pilot.jsonl` and keep the
same output directory policy.

The collector calls `answer_with_audit` with live PubMed source and LLM workflow
flags enabled.

## LLM ASV Evaluation

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.evaluate \
    --input /tmp/asv-live-pubmed-step-value/collection/trajectory.jsonl \
    --model deepseek-chat \
    --cache /tmp/asv-live-pubmed-step-value/deepseek-cache.jsonl \
    --evaluated /tmp/asv-live-pubmed-step-value/evaluated.jsonl \
    --output-dir /tmp/asv-live-pubmed-step-value/report'
```

The evaluator uses `deepseek-chat-logprob` through the existing ASV runtime.
Use `deepseek-chat` for label-token scoring; `deepseek-v4-flash` returns
reasoning-token logprobs and is not suitable for this evaluator path.

## Analysis Tables

```bash
.venv/bin/python -m eval.asv.live_pubmed.analyze \
  --report-dir /tmp/asv-live-pubmed-step-value/report
```

## Label Permutation Audit

```bash
.venv/bin/python -m eval.asv.live_pubmed.robustness \
  --input /tmp/asv-live-pubmed-step-value/collection/trajectory.jsonl \
  --output /tmp/asv-live-pubmed-step-value/permuted-trajectories.jsonl \
  --permutations 3
```

Evaluate the permuted trajectories with the same evaluator wrapper and separate
artifact paths, then compare ASV stability across permutations.

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  .venv/bin/python -m eval.asv.live_pubmed.evaluate \
    --input /tmp/asv-live-pubmed-step-value/permuted-trajectories.jsonl \
    --cache /tmp/asv-live-pubmed-step-value/permuted-deepseek-cache.jsonl \
    --evaluated /tmp/asv-live-pubmed-step-value/permuted-evaluated.jsonl \
    --output-dir /tmp/asv-live-pubmed-step-value/permuted-report'
```
