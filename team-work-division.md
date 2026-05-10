# MeetFlow 团队分工边界

本文用于配合 `AGENTS.md` 和 `git-instruction.md`，给 Agent、协作者和自动化脚本提供最小分工边界。它不是固定组织架构，而是为了减少并行开发时的覆盖、重复和安全边界漂移。

## 1. 默认协作原则

- 默认集成分支为 `main`，开发改动应先在功能分支或文档分支中完成。
- 开工前先读 `tasks.md` 和对应 `docs/tasks/**`，确认自己负责的任务编号、文件范围和验收标准。
- 同一轮任务尽量保持写入范围清晰；如果跨越 `core/`、`adapters/`、`frontend/`、`docs/` 多个边界，必须在任务记录中说明原因。
- 遇到别人已修改的文件，不要直接回滚；如果影响当前任务，先记录冲突点和处理方式。
- 大型改动完成后，在任务记录中给出精简关键改动记录，避免把实现细节写成流水账。

## 2. 主要开发线

| 开发线 | 主要目录 | 边界说明 |
|---|---|---|
| Agent Runtime | `core/agent.py`、`core/agent_loop.py`、`core/router.py`、`core/context.py`、`core/workflows.py` | 维护主链路，不绕过 `ToolRegistry` 和 `AgentPolicy`。 |
| 飞书适配 | `adapters/`、`scripts/*live*`、`scripts/feishu_*` | 封装真实飞书 API、OAuth、SDK/HTTP 回调；不得泄露 token 或 secret。 |
| 工具与策略 | `core/tools.py`、`adapters/feishu_tools.py`、`core/policy.py`、`core/knowledge.py` | 工具 schema、工具执行、RAG 和写操作安全边界集中维护。 |
| M3/M4/M5 业务 | `core/pre_meeting.py`、`core/post_meeting.py`、`core/risk_scan.py`、`cards/` | 保持会前、会后、风险巡检的结构化产物和证据链。 |
| Console / CLI / OpenClaw | `core/console_api.py`、`scripts/meetflow_console_server.py`、`scripts/meetflow_cli.py`、`frontend/` | 只能调用受控 Agent、Console facade 或白名单脚本，默认 dry-run。 |
| 评测与回放 | `core/evaluation.py`、`core/eval_trace.py`、`core/eval_metrics.py`、`scripts/*eval*`、`tests/e2e_fixtures/**` | 负责可回放、可评分、可解释报告，不伪造真实联调成功。 |
| 文档与演示 | `tasks.md`、`docs/tasks/**`、`docs/**`、`README.md` | 所有架构、任务、验收、Runbook 和演示变化必须保持同步。 |

## 3. 并行开发护栏

- AI/RAG/LLM 能力线可以和 Runtime 工程线并行，但共享 `ToolRegistry`、`AgentPolicy`、`AgentTrace` 等契约时必须先定 schema。
- 前端 Console 可以和后端 Agent 并行，但前端不得直接调用飞书 API 或直接写 SQLite 业务表。
- OpenClaw / CLI 增强可以和 M3/M4/M5 卡片增强并行，但 CLI 入口不得接受任意 shell 命令。
- 真实飞书写入联调必须使用测试群、测试任务和显式 `--allow-write`。
- 修改安全策略、任务创建、卡片回调、OAuth token 持久化、schema migration 时，必须补测试或明确未测试原因。

## 4. 提交前记录模板

建议在 `tasks.md` 或对应任务文档中用精简格式记录：

```text
完成记录:
- 分支/提交: 待提交
- 修改文件: ...
- 核心改动: ...
- 验证方式: ...
- 共享契约检查: 已阅读 AGENTS.md / git-instruction.md / team-work-division.md
- 遗留问题: 无 / ...
```
