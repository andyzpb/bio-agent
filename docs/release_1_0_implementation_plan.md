# Release 1.0 分步实施计划

本文档把 Release 1.0 的大计划拆成可逐步实现、逐步验证、逐步提交的工程阶段。后续实现应按本文档顺序推进，除非某一步发现必须先补前置依赖。

## 0. Release 1.0 目标和边界

Release 1.0 的目标是把当前 V2.6 Biomedical Evidence Agent 收束为一个稳定、可审计、可演示、可扩展的 research-only biomedical agent 工具。

当前基线：
- 已实现 controlled `search_literature`、mock/PubMed 检索、retrieval manifest、evidence packet、citation audit、logic audit、audit/revise、Trace/Audit dashboard、project workspace、Research Watch。
- 已实现 V2.6 multi-pass gap-directed literature retrieval。
- 默认 source 仍为 `mock`，live PubMed 仍为 opt-in。
- Ollama/OpenAI-compatible LLM 路径用于本地 smoke，不作为 CI 强制依赖。
- 项目采用 Apache-2.0。

核心信任规则：

```text
Memory, reviewer notes, model output, and project context may guide workflow.
Only retrieved papers, evidence spans, retrieval manifests, citation audit,
logic audit, and evidence packets may support biomedical claims.
```

Release 1.0 不做：
- clinical decision support；
- general web search as evidence；
- full-text/PDF ingestion；
- Obsidian import；
- V3.0 formal argumentation、conformal runtime、Bayesian synthesis、causal estimation、topic drift、hypergraph。

## 1. Phase A：Release 基线和最小重构护栏

目标：先保证后续大改有清晰边界，不在第一步做大规模行为重写。

改动范围：
- 保持 `release/1.0` 分支为工作分支。
- 确认 `main` 与 upstream 已同步。
- 记录当前 V2.6 baseline 测试命令和 smoke 命令。
- 在文档中明确 Release 1.0 的分步路线、非目标、验收门槛。
- 只做低风险 helper/module 提取，不改变 public API/tool 行为。

可选代码整理：
- 新建空壳或轻量 helper 模块，为后续迁移留位置：
  - `errors.py`
  - `telemetry_service.py`
  - `packet_service.py`
  - `obsidian_export.py`
  - `provenance_service.py`
- 暂时不要把 `BiomedEvidenceService` 大拆散，避免一次性引入行为差异。

验收：
- `pyright --level error`
- `pyright --project pyrightconfig.tests.json --level error`
- `pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py tests/test_biomed_audit.py tests/test_biomed_claim_logic.py`
- 现有 `/api/biomed/answer/audited`、`/api/biomed/literature/search` 不回归。

推荐提交：
- `docs: add release 1 implementation plan`
- `refactor(biomed): add release service module scaffolding`

## 2. Phase B：Tool Contract、Source Policy、Structured Error

目标：先统一新增 Release 1.0 tool/API 的契约，再开始加工作流工具。

新增/硬化内容：
- 结构化 tool envelope：

```json
{
  "ok": true,
  "result": {},
  "warnings": [],
  "errors": [],
  "trace": {},
  "ids": {}
}
```

- tool metadata：
  - `risk_level`
  - `source_policy`
  - `side_effects`
  - `requires_confirmation`
  - `max_runtime_seconds`
  - `output_schema_version`
- structured error codes：
  - `clinical_boundary`
  - `source_policy_blocked`
  - `invalid_input`
  - `unknown_run_id`
  - `unknown_retrieval_id`
  - `unknown_paper_id`
  - `missing_retrieval_manifest`
  - `empty_evidence`
  - `llm_schema_invalid`
  - `external_source_unavailable`
  - `rate_limited`
  - `timeout`
  - `budget_exceeded`
  - `export_path_blocked`
  - `packet_unavailable`
  - `provenance_unavailable`

配置新增：
- `max_tool_steps`
- `max_retrieval_queries`
- `max_followup_queries`
- `max_llm_calls`
- `max_wall_clock_seconds`
- `max_obsidian_export_files`
- `obsidian_export_dir`
- `enable_obsidian_export`
- `enable_provenance_export`
- `enable_step_telemetry`
- `enable_bandit_advisory`

约束：
- clinical guardrail 必须先于 memory、retrieval、LLM、export、provenance。
- live PubMed 仍必须经过 `allow_live_pubmed_tools`。
- 新 tool 先使用 envelope；老 route 可以保持兼容响应。

验收：
- 新 error/envelope schema 单元测试通过。
- clinical request 对新增 tool 返回 `clinical_boundary`，不触发检索。
- source policy 对 PubMed 禁用状态返回 `source_policy_blocked`。

推荐提交：
- `feat(biomed): add structured release tool contracts`

## 3. Phase C：Toolized Evidence Workflow

目标：把当前 `answer_with_audit` 内部已有的 retrieval、extraction、coverage、packet 能力拆成可独立调用的受控工具链。

新增 API/tool：
- `POST /api/biomed/retrieval/multi-pass`
  - tool: `run_multi_pass_literature_search`
- `POST /api/biomed/evidence/extract-batch`
  - tool: `extract_evidence_batch`
- `POST /api/biomed/evidence/coverage-gaps`
  - tool: `analyze_coverage_gaps`
- `POST /api/biomed/evidence/packet`
  - tool: `build_evidence_packet`
- `GET /api/biomed/answer-runs/{run_id}/evidence-packet`
  - tool: `get_evidence_packet`
- tool wrapper for existing trace:
  - `get_answer_trace`

实现策略：
- 复用现有 controlled `search_literature`，不要让 LLM 直接联网。
- 复用已有 `RetrievalBundle`、`CoverageMatrixRow`、`GapSearchDecision`、`EvidencePacketSummary`。
- `run_multi_pass_literature_search` 只做 planner + retrieval，不默认回答。
- `extract_evidence_batch` 支持 `retrieval_id`、`paper_ids`、`run_id` 三种入口，unknown id fail fast。
- `analyze_coverage_gaps` 不发明证据，只报告 missing/weak/source-limited/conflicted。
- `build_evidence_packet` 生成 downstream single packet，并返回 selected/dropped/trace。
- `get_evidence_packet` 不能触发新检索；只能返回 persisted/reconstructed/stale/unavailable。

验收：
- tool-by-tool workflow 能跑出和 `answer_with_audit` 同合同的 evidence packet。
- 临床问题在第一个 tool 前被拒绝。
- PubMed source policy 不被新增 route 绕过。
- mock 路径 deterministic。

推荐提交：
- `feat(biomed): expose toolized evidence workflow`

## 4. Phase D：Memory Context Bridge、Budget、Step Telemetry

目标：把 memory 用作 workflow preference，而不是 evidence，并记录多步执行经验。

Memory Context Bridge：
- 支持 memory 类型：
  - `biomed_active_project`
  - `biomed_reviewer_preference`
  - `biomed_saved_paper_decision`
  - `biomed_rejected_paper_decision`
  - `biomed_excluded_term`
  - `biomed_preferred_method`
  - `biomed_watch_interest`
  - `biomed_workflow_preference`
- memory 只能影响 planner preferences、include/exclude terms、saved-paper priority、rejected-paper filtering、project selection、reviewer workflow。
- memory 不得创建 evidence，不得满足 citation support，不得改写 logic audit verdict，不得覆盖 clinical refusal。

Trace 字段：

```json
{
  "memory_used": true,
  "memory_sources": ["biomed_project:..."],
  "memory_effects": [
    "prioritized_saved_papers",
    "excluded_rejected_papers",
    "added_preferred_method_filter"
  ],
  "memory_as_evidence": false
}
```

Budget：
- max tool steps
- max retrieval queries
- max follow-up queries
- max papers
- max evidence items
- max LLM calls
- max wall-clock seconds
- per-tool timeout

Step telemetry：
- states:
  - `classified`
  - `planned`
  - `searched`
  - `extracted`
  - `gap_analyzed`
  - `followup_searched`
  - `packet_built`
  - `synthesized`
  - `audited`
  - `revised`
  - `refused`
  - `failed`
- 输出：
  - transition records
  - transition matrix
  - mean/p95 step count
  - expected remaining steps
  - unusual path warnings

验收：
- `memory_not_used_as_evidence_rate == 1.0`
- `clinical_boundary_before_memory_rate == 1.0`
- budget exceeded 返回结构化 `budget_exceeded`，保留 partial trace。
- telemetry 只 advisory，不控制 truth 或绕过 caps。

推荐提交：
- `feat(biomed): add memory bridge and step telemetry`

## 5. Phase E：Obsidian One-Way Export

目标：把 reviewer memory 和 evidence packet 导出到 Obsidian 双链笔记，但 Release 1.0 只导出、不导入。

新增 API/tool：
- `POST /api/biomed/export/obsidian/evidence-packet`
  - tool: `export_evidence_packet_to_obsidian`
- `POST /api/biomed/export/obsidian/project`
  - tool: `export_project_to_obsidian`
- `POST /api/biomed/export/obsidian/watch`
  - tool: `export_research_watch_to_obsidian`

实现要求：
- export path 必须来自 config 或显式安全路径。
- 文件名 deterministic、filesystem-safe。
- re-export idempotent。
- YAML frontmatter 包含：
  - `type`
  - `paper_id`
  - `pmid`
  - `doi`
  - `claim_id`
  - `evidence_ids`
  - `retrieval_ids`
  - `run_id`
  - `project_id`
  - `audit_verdict`
  - `generated_at`
  - `source_of_truth`
- 双链格式：
  - `[[topic:...]]`
  - `[[paper:pmid-...]]`
  - `[[claim:...]]`
  - `[[gap:...]]`
  - `[[answer-run:...]]`
  - `[[evidence-packet:...]]`

验收：
- export disabled 时返回 `export_path_blocked` 或 disabled policy error。
- export enabled 时生成 deterministic markdown。
- Obsidian notes 不进入 evidence path。
- dashboard 至少能从 packet/project/watch 触发或展示 export result。

推荐提交：
- `feat(biomed): add obsidian reviewer export`

## 6. Phase F：Submodular Packet Selection 和 Bandit Advisory

目标：增加数学 hardening，但保持 deterministic/advisory，不让 fancy 方法影响安全边界。

Submodular selector：
- default strategy: `submodular_greedy`
- compatibility strategy: `all_valid`
- objective：
  - subquestion coverage
  - retrieval-intent diversity
  - support/refute/limitation balance
  - paper/provenance quality
  - abstract/span availability
  - duplicate-paper penalty
  - redundant-claim penalty
  - source-warning penalty
- 必须保留 conflicting evidence 和 limitation evidence。
- 输出 selected evidence IDs、dropped evidence IDs、drop reasons、coverage contribution、token estimate。

Contextual bandit retrieval advisory：
- 输入 trace/eval/retrieval stats。
- 输出 advisory action：
  - stop
  - broaden query
  - narrow query
  - search support
  - search refute
  - search mechanism
  - search limitation
  - switch to PubMed if policy allows
- 不做 autonomous runtime control。
- caps 和 clinical/source policy 仍为最高优先级。

验收：
- submodular selector deterministic。
- duplicate evidence 减少或不增加。
- conflict/limitation evidence 不被错误优化掉。
- bandit advisory schema valid，且只出现在 trace/dashboard/eval 中。

推荐提交：
- `feat(biomed): add packet selection and retrieval advisory`

## 7. Phase G：PROV/OpenLineage-Compatible Provenance

目标：为 answer run 输出可追踪 provenance graph，不依赖外部 provenance service。

新增 API/tool：
- `GET /api/biomed/answer-runs/{run_id}/provenance`
  - tool: `export_provenance_graph`

Graph model：
- entity：
  - paper
  - evidence item
  - retrieval manifest
  - evidence packet
  - answer
  - citation audit
  - logic audit
  - revision
  - Obsidian note
- activity：
  - classify
  - plan
  - search
  - fetch
  - extract
  - gap analyze
  - packet build
  - synthesize
  - audit
  - revise
  - export
- agent：
  - deterministic service
  - LLM provider/model
  - reviewer
  - plugin tool
- relation：
  - `used`
  - `generated`
  - `wasDerivedFrom`
  - `wasAssociatedWith`

安全要求：
- redacts prompts、secrets、raw provider responses。
- 只链接 stable SQLite IDs。
- unknown run 返回 `unknown_run_id`。
- unavailable dependency 返回 `provenance_unavailable`。

验收：
- provenance graph schema valid。
- graph links answer、packet、evidence、manifest、audit、revision、tools。
- 不泄漏 raw prompt/API key/provider raw response。

推荐提交：
- `feat(biomed): add provenance graph export`

## 8. Phase H：Dashboard、Eval、Docs、Release Gates

目标：把 Release 1.0 从“API 能跑”提升到“可演示、可评估、可发布”。

Dashboard：
- Trace view 展示 toolized workflow steps、memory effects、budget、telemetry。
- Evidence Packet view 展示 selected/dropped evidence 和 drop reasons。
- Audit view 展示 citation audit、logic audit、logic facts。
- Export actions 展示 Obsidian/provenance results。
- Responsible AI view 明确 research-only、memory boundary、clinical refusal。

Eval metrics：
- keep existing：
  - citation coverage
  - citation precision
  - unsupported claim rate
  - overclaim rate
  - clinical refusal success
  - retrieval manifest validity
  - literature search coverage
  - evidence packet validity
  - logic audit completeness
  - memory not used as evidence
- add Release 1.0：
  - `tool_schema_validity`
  - `tool_output_schema_validity`
  - `tool_chain_parity_rate`
  - `clinical_boundary_before_tool_chain_rate`
  - `live_source_policy_before_tool_chain_rate`
  - `memory_trace_completeness`
  - `memory_source_ref_validity`
  - `tool_transition_trace_rate`
  - `mean_tool_step_count`
  - `p95_tool_step_count`
  - `budget_compliance_rate`
  - `structured_error_validity`
  - `obsidian_frontmatter_validity`
  - `obsidian_duplicate_note_rate`
  - `obsidian_export_not_imported_as_evidence_rate`
  - `submodular_packet_coverage_rate`
  - `submodular_duplicate_reduction_rate`
  - `bandit_advisory_schema_validity`
  - `provenance_graph_validity`
  - `prompt_injection_boundary_success_rate`

Docs：
- `README.md`
- `plugins/biomed_evidence/README.md`
- `docs/evaluation.md`
- `docs/deployment.md`
- `docs/responsible_ai.md`
- `agent.md`
- `CHANGELOG.md`

Release gates：

```bash
.venv/bin/pyright --level error
.venv/bin/pyright --project pyrightconfig.tests.json --level error
.venv/bin/pytest -q tests/
.venv/bin/python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_release_1_0.json
npm run typecheck
npm run build
docker compose up -d --build --force-recreate
```

Optional live smoke：

```bash
.venv/bin/python -m eval.biomed_evidence.run_eval \
  --source pubmed \
  --live-pubmed \
  --max-papers 3 \
  --output /tmp/biomed_eval_release_1_0_pubmed.json
```

Ollama smoke：
- model: `gpt-oss:120b-cloud`
- verify planner、extractor、synthesis、verifier、revision、claim logic parser run or record explicit fallback reasons。

推荐提交：
- `feat(biomed): polish release dashboard`
- `test(biomed): add release 1 eval gates`
- `docs: document release 1 architecture and smoke`

## 9. Recommended Implementation Order

1. Phase A：先建立分步文档和 baseline gate。
2. Phase B：补 tool contract、structured error、source/budget config。
3. Phase C：实现 toolized workflow API/tool。
4. Phase D：实现 memory bridge、budget、telemetry。
5. Phase E：实现 Obsidian export。
6. Phase F：实现 submodular selector 和 bandit advisory。
7. Phase G：实现 provenance graph。
8. Phase H：补 dashboard、eval、docs、smoke。

每个 phase 都必须满足：
- 不破坏现有 V2.6 mock path。
- clinical guardrail 优先级不下降。
- PubMed live access 仍 opt-in。
- 新增功能先 API/test，再 dashboard polish。
- 遇到大重构时先加 characterization tests，再移动代码。

## 10. Release Completion Criteria

Release 1.0 可以合回 `main` 的条件：

- 所有现有 V2.6 行为保持兼容。
- tool-by-tool workflow 可复现 `answer_with_audit` 的 evidence packet contract。
- clinical questions 在 memory/retrieval/extraction/LLM/export/provenance 之前拒绝。
- memory influence traceable 且永不作为 evidence。
- Obsidian export one-way、idempotent。
- submodular selector deterministic，且不会错误丢弃 conflict/limitation evidence。
- bandit policy advisory only。
- provenance graph 连接 answer、packet、evidence、manifest、audit、revision、tool。
- structured errors schema-valid。
- Docker dashboard 跑当前代码。
- README/docs 描述 Release 1.0，而不是开发流水账。
- merge to `main` 后创建 `v1.0.0` tag。
