# 开发约定 0：共享契约和开发护栏

这组任务优先级最高。先把边界定住，后续 AI/RAG/LLM 与 Runtime 两条线才能并行开发。

## TASK-00-01 确认 Agent 工作规则

- 状态：`[x]`
- 负责人：共享
- 优先级：`P0`
- 任务目标：让后续 Agent 开发前自动知道要遵守 Git 规则和分工边界。

建议修改文件：

- `AGENTS.md`
- `team-work-division.md`
- `tasks.md`
- `docs/tasks/shared-contracts.md`

验收标准：

- `AGENTS.md` 说明默认集成分支为 `d3-post-meeting-card-enhancement-plan`。
- `AGENTS.md` 要求开发前检查 `git-instruction.md` 和 `team-work-division.md`。
- `AGENTS.md` 要求开发前阅读 `tasks.md` 和对应 `docs/tasks/**` 任务文档。
- `AGENTS.md` 要求提交前记录检查结果。
- `AGENTS.md` 要求大型修改完成后给出简短关键改动记录，不写冗长流水账。
- 文档要求禁止提交本地数据、真实密钥、第三方源码包、虚拟环境和运行产物。

完成记录：

- 状态：已完成
- 分支/提交：待提交
- 修改文件：
  - `AGENTS.md`
  - `team-work-division.md`
  - `tasks.md`
  - `docs/tasks/shared-contracts.md`
- 实现功能：
  - 新增 Agent 开发守则，约束默认集成分支、职责边界、提交前检查和任务文档同步。
  - 新增 `team-work-division.md`，明确 Agent Runtime、飞书适配、工具策略、M3/M4/M5、Console/CLI/OpenClaw、评测与文档演示等开发线边界。
  - 补充要求：开工前阅读 `tasks.md` 对应任务，完成后在对应任务记录核心完成内容。
  - 补充要求：每次大型代码修改后给出精简关键改动记录，重点说明改动、验证和风险，避免过度占用上下文。
- 验证方式：
  - 人工阅读 `AGENTS.md`、`team-work-division.md` 和本任务记录。
  - 未运行测试，因为只修改文档。
- 遗留问题：无。
