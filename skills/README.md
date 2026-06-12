# Builtin Skills Index

本文件描述仓库内置技能（`skills/*/SKILL.md`）。

## 目录与格式

- 每个技能目录必须包含 `SKILL.md`。
- `SKILL.md` 建议包含 frontmatter：`name`、`description`、`metadata.akashic`。
- 主循环可按需读取具体技能文件；本索引只做发现与导航，不承载执行细节。

## 当前内置技能

- `feed-manage`
  - 管理和查询 RSS/信息来源订阅，支持列订阅、查最新、查概况、关键词搜索。
  - 文件：`skills/feed-manage/SKILL.md`

- `meme-manage`
  - 维护工作区表情包库，支持新增图片、整理类别和更新 manifest。
  - 文件：`skills/meme-manage/SKILL.md`

- `create-drift-skill`
  - 在工作区 drift/skills 下创建或更新 drift skill。
  - 文件：`skills/create-drift-skill/SKILL.md`

- `codex-delegate`
  - 把长代码库任务委托给本机 Codex CLI 后台执行，并等待完成后回灌结果。
  - 文件：`skills/codex-delegate/SKILL.md`

- `biomed-evidence-review`
  - 使用受控文献检索、证据包、audit/revision、trace 和 provenance 执行 research-only biomedical evidence review。
  - 文件：`skills/biomed-evidence-review/SKILL.md`

- `biomed-clinical-boundary`
  - 在任何检索、LLM、记忆、导出或 provenance 之前执行临床/患者特异性请求边界拦截。
  - 文件：`skills/biomed-clinical-boundary/SKILL.md`

- `biomed-project-memory-watch`
  - 管理 biomedical project memory、Research Watch、reviewer decisions 和 Obsidian 单向导出，同时禁止把记忆当证据。
  - 文件：`skills/biomed-project-memory-watch/SKILL.md`

- `skill-creater`
  - 创建或改写技能 `SKILL.md`，用于新增技能与结构迁移。
  - 文件：`skills/skill-creater/SKILL.md`

- `summarize`
  - 总结 URL/文件/YouTube 内容，支持提取转写。
  - 文件：`skills/summarize/SKILL.md`

- `weather`
  - 通过 wttr.in / Open-Meteo 查询天气与预报。
  - 文件：`skills/weather/SKILL.md`

## 维护约定

- 新增内置技能：新增目录与 `SKILL.md`，并更新本索引。
- 删除内置技能：移除条目，避免索引悬空。
- 以本文件为“仓库内置技能真相源”；运行时用户自定义技能应在 workspace 的 `skills/README.md` 维护。
