# Open QA Candidate Generation ASV

This experiment evaluates open biomedical QA runs by freezing reviewed candidate
answer sets, then scoring each bio-agent step against those candidates.

Generate raw candidate specs:

```bash
.venv/bin/python -m eval.asv.open_qa.generate \
  --questions eval/asv/open_qa/questions.quick.jsonl \
  --output /tmp/asv-open-qa/generated.jsonl \
  --provider deepseek \
  --model deepseek-v4-flash
```

Review `generated.jsonl` manually, keeping exactly one
`none-of-the-above` candidate per row. Then run the live experiment:

```bash
.venv/bin/python -m eval.asv.open_qa.run_experiment \
  --reviewed /tmp/asv-open-qa/reviewed.jsonl \
  --artifact-root /tmp/asv-open-qa-candidate-generation-$(date +%Y%m%d-%H%M%S) \
  --actor-provider deepseek \
  --actor-model deepseek-v4-flash \
  --ack-live
```

The artifact root preserves generated and reviewed specs, adapted ASV JSONL,
collection outputs, evaluator cache, evaluated trajectories, reports,
label-permutation inputs, and `results.md`.
