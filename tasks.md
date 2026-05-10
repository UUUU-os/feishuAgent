# MeetFlow 冲刺任务拆解

本文档用于管理本轮比赛冲刺要做的任务。每完成一个小任务，都必须在对应任务下更新“完成记录”，说明修改了哪些文件、实现了哪些功能、跑了哪些验证。

相关约束：

- 开发和提交前遵守 `AGENTS.md`。
- Git 流程遵守 `git-instruction.md`。
- 职责边界遵守 `team-work-division.md`。
- 默认集成分支是 `feature/one-click-live-test-console`。

## 状态约定

- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成
- `[!]` 阻塞或需要讨论

## 完成记录模板

每完成一个任务，在对应任务下补充：

```text
完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：
```

## 0. 共享契约和开发护栏

这组任务优先级最高。先把边界定住，后续 AI/RAG/LLM 与 Runtime 两条线才能并行开发。

### TASK-00-01 确认 Agent 工作规则

- 状态：`[x]`
- 负责人：共享
- 任务目标：让后续 Agent 开发前自动知道要遵守 Git 规则和分工边界。
- 建议修改文件：
  - `AGENTS.md`
- 验收标准：
  - 文档说明默认集成分支。
  - 文档要求开发前检查 `git-instruction.md` 和 `team-work-division.md`。
  - 文档要求提交前记录检查结果。

完成记录：
- 状态：已完成
- 分支 / 提交：待提交
- 修改文件：`AGENTS.md`
- 实现功能：新增 Agent 开发守则，约束默认分支、职责边界、提交前检查、禁止提交本地数据和第三方源码；补充要求：开工前阅读 `tasks.md` 对应任务，完成后在对应任务记录核心完成内容。
- 验证方式：人工阅读 `AGENTS.md` 和本任务记录；未运行测试，因为只修改文档。
- 遗留问题：无。

### TASK-00-02 固化 AI 与 Runtime 的调用契约

- 状态：`[x]`
- 负责人：共享，建议由 AI 负责人先起草，Runtime 负责人确认字段。
- 任务目标：新增最小共享契约，让 Runtime 只依赖稳定输入输出，不依赖 RAG/LLM 内部实现。
- 建议修改文件：
  - `core/contracts.py`
  - `tests/test_ai_facade.py`
- 不建议修改：
  - `core/jobs.py`
  - `core/knowledge.py`
  - `core/llm.py`
- 验收标准：
  - 定义 `AIWorkflowInput`。
  - 定义 `AIWorkflowResult`。
  - 字段覆盖 `trace_id`、`workflow_type`、`status`、`summary`、`data`、`metrics`、`errors`。
  - 有单测覆盖默认值和序列化/字典化需求。

完成记录：
- 状态：已完成
- 分支 / 提交：`feature/ai-rag-auto-strategy/lear` / 待提交
- 修改文件：`core/contracts.py`、`tests/test_ai_facade.py`
- 实现功能：新增 `AIWorkflowInput`、`AIWorkflowResult`，支持默认值、`to_dict()`、`from_dict()`，字段覆盖 Runtime 与 AI 的最小共享契约。
- 验证方式：`python3 -m unittest tests.test_ai_facade tests.test_config_loader`；`python3 -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py`；`python3 -m unittest discover -s tests -p 'test_*.py'`
- 遗留问题：无。

### TASK-00-03 新增 AI Facade 空壳

- 状态：`[x]`
- 负责人：AI/RAG/LLM
- 任务目标：提供 Runtime 可调用的唯一 AI 入口，先返回可测试的稳定结果，后续逐步接入真实 RAG 和 LLM。
- 建议修改文件：
  - `core/ai_facade.py`
  - `tests/test_ai_facade.py`
- 验收标准：
  - 暴露 `run_ai_workflow(input)`。
  - 暴露 `run_pre_meeting_brief(input)`。
  - 暴露 `run_post_meeting_summary(input)`。
  - 暴露 `run_risk_scan_reasoning(input)`。
  - Runtime 不需要 import `core/knowledge.py` 或 `core/llm.py`。

完成记录：
- 状态：已完成
- 分支 / 提交：`feature/ai-rag-auto-strategy/lear` / 待提交
- 修改文件：`core/ai_facade.py`、`tests/test_ai_facade.py`
- 实现功能：新增 `run_ai_workflow()`、`run_pre_meeting_brief()`、`run_post_meeting_summary()`、`run_risk_scan_reasoning()`，先返回稳定 stub 结果，不依赖 `core/knowledge.py` 或 `core/llm.py`。
- 验证方式：`python3 -m unittest tests.test_ai_facade tests.test_config_loader`；`python3 -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py`；`python3 -m unittest discover -s tests -p 'test_*.py'`
- 遗留问题：后续 TASK-03 集成时再接入真实 AI 工作流。

### TASK-00-04 明确配置边界

- 状态：`[x]`
- 负责人：共享
- 任务目标：把 AI 配置和 Runtime 配置分区，减少双方同时修改 `config/settings.example.json` 的冲突。
- 建议修改文件：
  - `config/settings.example.json`
  - `config/llm_providers.example.json`
  - `config/loader.py`
  - `tests/test_config_loader.py` 或现有配置测试
- 验收标准：
  - AI 配置段只包含 LLM、embedding、reranker、knowledge search、LiteLLM。
  - Runtime 配置段只包含 worker、queue、db、console、health。
  - 本地配置文件不进入提交。

完成记录：
- 状态：已完成
- 分支 / 提交：`feature/ai-rag-auto-strategy/lear` / 待提交
- 修改文件：`config/loader.py`、`config/__init__.py`、`config/settings.example.json`、`config/llm_providers.example.json`、`tests/test_config_loader.py`
- 实现功能：新增 LiteLLM 配置、Runtime 配置、`ai_config` 和 `runtime_config` 只读边界视图；`llm_providers.example.json` 增加 LiteLLM Proxy provider 示例。
- 验证方式：`python3 -m json.tool config/settings.example.json`；`python3 -m json.tool config/llm_providers.example.json`；`python3 -m unittest tests.test_ai_facade tests.test_config_loader`；`python3 -m unittest discover -s tests -p 'test_*.py'`
- 遗留问题：无。

## 1. AI/RAG/LLM 任务线

这条线由 AI/RAG/LLM 负责人主导，目标是提升答案质量、降低接入模型的风险，并保持对 Runtime 的稳定接口。

### TASK-01-01 梳理现有 RAG 数据规模与检索链路

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：明确当前知识库文档数量、索引位置、检索入口、召回排序逻辑，为自动策略做准备。
- 建议修改文件：
  - `docs/rag-current-state.md` 或 `storage/reports/evaluation/effect_eval_latest.md`
- 主要阅读文件：
  - `core/knowledge.py`
  - `core/tools.py`
  - `scripts/pre_meeting_retrieval_demo.py`
  - `tests/test_pre_meeting_retrieval.py`
- 验收标准：
  - 文档说明当前 direct/FTS/vector 检索能力。
  - 文档说明小文档量和大文档量的差异。
  - 列出后续需要改造的函数入口。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-02 实现 RAG 自动策略选择器

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：当文档数量较少时使用 direct/manifest 策略，当文档数量较大时使用现有 RAG 检索策略。
- 建议修改文件：
  - `core/ai_runtime/rag_strategy.py`
  - `core/knowledge.py`
  - `tests/test_rag_strategy.py`
- 验收标准：
  - 支持配置阈值，例如 `small_corpus_threshold=200`。
  - 小语料返回 direct/manifest 策略。
  - 大语料返回 vector/FTS/RRF 策略。
  - 策略选择逻辑可单独测试。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-03 接入小语料 direct/manifest 检索

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：对少量文档生成轻量 manifest，让模型直接基于候选文档摘要、标题、来源做判断，减少不必要的向量检索链路。
- 建议修改文件：
  - `core/knowledge.py`
  - `core/ai_runtime/rag_strategy.py`
  - `scripts/pre_meeting_retrieval_demo.py`
  - `tests/test_pre_meeting_retrieval.py`
- 验收标准：
  - 小语料路径能返回文档标题、来源、摘要、片段引用。
  - 输出结构兼容现有 evidence 逻辑。
  - 不破坏现有 RAG 检索测试。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-04 优化大语料 RAG 召回与融合

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：保留或增强大语料场景下的 Chroma / FTS5 / RRF 检索链路。
- 建议修改文件：
  - `core/knowledge.py`
  - `tests/test_knowledge_tools.py`
  - `tests/test_pre_meeting_retrieval.py`
- 验收标准：
  - 大语料路径继续支持关键词和语义检索。
  - RRF 或等价融合逻辑结果稳定。
  - 有测试覆盖不同检索策略的排序输出。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-05 增加 evidence pack 输出

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：让 AI 输出附带可展示的证据引用，便于演示时解释答案来源。
- 建议修改文件：
  - `core/knowledge.py`
  - `core/tools.py`
  - `core/ai_facade.py`
  - `tests/test_ai_facade.py`
- 验收标准：
  - `AIWorkflowResult.evidence_refs` 有稳定结构。
  - 每条 evidence 至少包含来源、标题、片段或定位信息。
  - Runtime 可直接展示 evidence，不需要理解 RAG 内部对象。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-06 设计 LiteLLM 配置示例

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：给出可运行的 LiteLLM Proxy 示例配置，为后续统一模型调用做准备。
- 建议修改文件：
  - `config/litellm_config.example.yaml`
  - `docs/litellm-integration.md`
  - `scripts/litellm_gateway_demo.py`
- 参考源码：
  - `storage/third_party/litellm/litellm/router.py`
  - `storage/third_party/litellm/litellm/proxy/proxy_server.py`
  - `storage/third_party/litellm/litellm/proxy/example_config_yaml/load_balancer.yaml`
- 验收标准：
  - 配置示例包含 `model_list`。
  - 配置示例包含 `router_settings`。
  - 配置示例说明 fallback、timeout、retry、routing strategy。
  - 不提交真实 API key。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-07 实现 LiteLLM Provider 适配

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：让现有 LLM 调用可以走 LiteLLM 的 OpenAI-compatible endpoint。
- 建议修改文件：
  - `core/llm.py`
  - `core/ai_runtime/litellm_gateway.py`
  - `config/llm_providers.example.json`
  - `scripts/llm_provider_demo.py`
  - `tests/test_litellm_gateway_config.py`
- 验收标准：
  - 支持配置 `base_url` 指向 LiteLLM Proxy。
  - 支持配置对外模型名，例如 `meetflow-default`。
  - 现有非 LiteLLM provider 不被破坏。
  - Demo 可以在有本地配置时发起一次调用。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-08 增加模型侧指标记录

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：记录每次 LLM 调用的延迟、模型名、token 用量、fallback 情况，方便演示稳定性。
- 建议修改文件：
  - `core/ai_runtime/llm_metrics.py`
  - `core/llm.py`
  - `core/ai_facade.py`
  - `tests/test_ai_facade.py`
- 验收标准：
  - `AIWorkflowResult.metrics` 包含模型调用指标。
  - 没有 token usage 时也能正常返回。
  - Runtime 只消费 metrics 字段，不理解 provider 内部细节。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-01-09 建立 AI 评测用例

- 状态：`[ ]`
- 负责人：AI/RAG/LLM
- 任务目标：用少量高价值 case 验证 RAG 策略和 LLM 输出质量，服务比赛演示。
- 建议修改文件：
  - `core/evaluation.py`
  - `core/eval_metrics.py`
  - `tests/test_agent_eval_suite.py`
  - `tests/test_eval_metrics.py`
  - `storage/reports/evaluation/effect_eval_latest.md`
- 验收标准：
  - 覆盖预会简报、会后总结、风险扫描至少 3 类场景。
  - 评测结果可复现。
  - 文档说明当前效果和限制。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

## 2. Runtime / 高并发任务线

这条线由 Runtime 负责人主导，目标是让系统能稳定处理多个任务，并且 Console 能展示运行状态。

### TASK-02-01 梳理现有 Console 和 Worker 链路

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：明确请求从 Console 到后台执行的路径，找出阻塞点和共享状态。
- 建议修改文件：
  - `docs/runtime-current-state.md`
- 主要阅读文件：
  - `scripts/meetflow_console_server.py`
  - `scripts/meetflow_worker.py`
  - `core/console_api.py`
  - `core/jobs.py`
  - `core/storage.py`
- 验收标准：
  - 文档说明当前任务提交、执行、状态查询路径。
  - 标出会阻塞 API 的地方。
  - 标出数据库并发风险点。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-02 定义任务队列和任务状态模型

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：让长任务进入队列，由 worker 执行，Console API 快速返回 job id。
- 建议修改文件：
  - `core/jobs.py`
  - `core/contracts.py`
  - `tests/test_jobs.py`
- 验收标准：
  - 支持 `queued`、`running`、`succeeded`、`failed`、`retrying`。
  - 支持记录 `trace_id`、任务类型、创建时间、更新时间、错误信息。
  - 状态模型与 AI facade 的结果结构兼容。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-03 Console API 改为非阻塞提交任务

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：用户点击 Console 操作后立即得到 job id，不等待 AI/RAG/LLM 完成。
- 建议修改文件：
  - `core/console_api.py`
  - `scripts/meetflow_console_server.py`
  - `tests/test_console_api.py`
- 验收标准：
  - 提交任务接口快速返回。
  - 状态查询接口可查询 job 状态。
  - 不直接调用 RAG/LLM 内部实现，只调用 AI facade 或任务队列。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-04 Worker 并发执行与限流

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：支持多个 job 并发执行，同时避免把本地服务或模型服务压垮。
- 建议修改文件：
  - `scripts/meetflow_worker.py`
  - `core/runtime_service/concurrency.py`
  - `tests/test_worker_concurrency.py`
- 验收标准：
  - 支持配置最大并发数。
  - 支持任务执行超时。
  - 单个任务失败不影响其他任务。
  - 并发逻辑有单测。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-05 增加重试和死信处理

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：让临时失败任务可以重试，多次失败后进入可观察的失败状态。
- 建议修改文件：
  - `core/jobs.py`
  - `scripts/meetflow_worker.py`
  - `tests/test_jobs.py`
- 验收标准：
  - 支持最大重试次数。
  - 支持记录最近一次错误。
  - 多次失败后状态稳定为 `failed` 或 `dead_letter`。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-06 SQLite 并发和持久化优化

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：提升本地 SQLite 在 worker 并发读写时的稳定性。
- 建议修改文件：
  - `core/storage.py`
  - `core/migrations.py`
  - `tests/test_migrations.py`
- 验收标准：
  - 启用或确认 WAL 模式。
  - 设置合理的 `busy_timeout`。
  - 并发读写测试不容易出现 database locked。
  - 迁移逻辑向后兼容。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-07 Runtime 指标和健康检查

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：Console 能看到服务是否活着、队列长度、运行中任务、失败任务等状态。
- 建议修改文件：
  - `core/observability.py`
  - `core/runtime_service/job_metrics.py`
  - `core/console_api.py`
  - `tests/test_observability.py`
- 验收标准：
  - 提供 health 接口。
  - 提供 queue/job metrics。
  - 可展示 LiteLLM Proxy 是否可用，但不直接管理 LiteLLM 配置。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-08 Console 前端任务状态展示

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：让演示时能看到任务提交、运行、成功、失败、日志等状态。
- 建议修改文件：
  - `frontend/src/api/client.ts`
  - `frontend/src/api/types.ts`
  - `frontend/src/pages/JobsHealthPage.tsx`
  - `frontend/src/pages/LiveFlowPage.tsx`
  - `frontend/src/components/ServiceControlPanel.tsx`
  - `frontend/src/components/CommandResultPanel.tsx`
- 验收标准：
  - 页面能显示 job id、状态、耗时、错误摘要。
  - 页面能刷新或轮询任务状态。
  - 前端构建通过，或明确记录构建失败原因。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-02-09 高并发压测脚本

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：用轻量脚本验证 Console API 和 Worker 在多个任务下可用。
- 建议修改文件：
  - `scripts/runtime_load_test.py`
  - `docs/runtime-load-test.md`
- 验收标准：
  - 可配置并发数和任务数。
  - 输出成功数、失败数、平均耗时、P95 耗时。
  - 不依赖真实 LLM 时也能用 mock/fake 任务跑通。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

## 3. 集成任务

这组任务需要双方协作，但每个任务仍然要尽量小，避免一次性改太多共享文件。

### TASK-03-01 Runtime 接入 AI Facade

- 状态：`[ ]`
- 负责人：共享，Runtime 负责人主改，AI 负责人确认输入输出。
- 任务目标：Runtime Worker 执行任务时通过 `core/ai_facade.py` 调用 AI 能力。
- 建议修改文件：
  - `scripts/meetflow_worker.py`
  - `core/console_api.py`
  - `core/ai_facade.py`
  - `tests/test_console_api.py`
  - `tests/test_ai_facade.py`
- 验收标准：
  - Runtime 不直接 import `core/knowledge.py` 或 `core/llm.py`。
  - AI 返回结果能持久化到 job result。
  - 错误能转为 job failed 状态。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-03-02 端到端预会简报链路

- 状态：`[ ]`
- 负责人：共享
- 任务目标：从 Console 提交预会简报任务，到 Worker 调 AI Facade，再到前端展示结果。
- 建议修改文件：
  - `core/ai_facade.py`
  - `core/console_api.py`
  - `scripts/meetflow_worker.py`
  - `frontend/src/pages/LiveFlowPage.tsx`
  - `tests/test_console_api.py`
- 验收标准：
  - 可以用 demo 数据创建任务。
  - 任务最终产出摘要和 evidence。
  - Console 能看到成功状态和结果摘要。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-03-03 端到端会后总结链路

- 状态：`[ ]`
- 负责人：共享
- 任务目标：从 Console 提交会后总结任务，到 Worker 调 AI Facade，再到前端展示结果。
- 建议修改文件：
  - `core/ai_facade.py`
  - `core/console_api.py`
  - `scripts/meetflow_worker.py`
  - `frontend/src/pages/LiveFlowPage.tsx`
  - `tests/test_console_api.py`
- 验收标准：
  - 可以用 demo transcript 创建任务。
  - 输出包含 summary、action items、risks 或等价结构。
  - 失败时有明确错误信息。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-03-04 端到端风险扫描链路

- 状态：`[ ]`
- 负责人：共享
- 任务目标：从 Console 提交风险扫描任务，到 Worker 调 AI Facade，再到前端展示结果。
- 建议修改文件：
  - `core/ai_facade.py`
  - `core/console_api.py`
  - `scripts/meetflow_worker.py`
  - `frontend/src/pages/LiveFlowPage.tsx`
  - `tests/test_console_api.py`
- 验收标准：
  - 输出风险列表、原因、证据引用。
  - Runtime 只展示 AI 返回的数据，不理解风险推理内部过程。
  - 测试覆盖成功和失败路径。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-03-05 LiteLLM Proxy 健康状态接入 Console

- 状态：`[ ]`
- 负责人：共享，AI 负责人提供健康检查方式，Runtime 负责人展示。
- 任务目标：Console 能展示 LiteLLM Proxy 是否可访问，但不让 Runtime 管理模型路由策略。
- 建议修改文件：
  - `core/ai_runtime/litellm_gateway.py`
  - `core/observability.py`
  - `core/console_api.py`
  - `frontend/src/pages/JobsHealthPage.tsx`
- 验收标准：
  - health 信息只包含可用性、延迟、错误摘要。
  - 模型路由配置仍由 AI 负责人维护。
  - LiteLLM 不可用时系统能给出友好提示。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

## 4. 测试、演示和交付

这组任务服务最后演示。优先保证闭环跑通，而不是追求大而全。

### TASK-04-01 后端基础测试通过

- 状态：`[ ]`
- 负责人：共享
- 任务目标：确保集成分支后端基础能力不被破坏。
- 建议执行命令：
  - `python3 -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py`
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
- 验收标准：
  - Python 编译检查通过。
  - 后端单测通过，或明确记录失败原因和负责人。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-04-02 前端构建通过

- 状态：`[ ]`
- 负责人：Runtime/高并发
- 任务目标：确保 Console 前端可以构建，用于比赛演示。
- 建议执行命令：
  - `cd frontend`
  - `npm run build`
- 建议修改文件：
  - `frontend/package.json`
  - `frontend/package-lock.json`
  - 前端源码中导致构建失败的文件
- 验收标准：
  - `npm run build` 通过。
  - 如果依赖缺失，单独提交依赖修复。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-04-03 一键演示脚本跑通

- 状态：`[ ]`
- 负责人：共享
- 任务目标：保证评委或演示者能通过一套固定步骤启动服务并跑通核心流程。
- 建议修改文件：
  - `scripts/pre_meeting_live_test.py`
  - `scripts/meetflow_console_server.py`
  - `storage/demo_materials/meetflow_recording_runbook.md`
  - `README.md`
- 验收标准：
  - 文档写明启动步骤。
  - Demo 数据路径明确。
  - 失败时有清晰排查步骤。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-04-04 更新 README 的比赛演示入口

- 状态：`[ ]`
- 负责人：共享
- 任务目标：让评委或队友打开 README 就知道如何启动、如何演示、核心亮点是什么。
- 建议修改文件：
  - `README.md`
- 验收标准：
  - 说明核心功能。
  - 说明本地启动命令。
  - 说明 LiteLLM 可选配置。
  - 说明 Console 演示路径。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

### TASK-04-05 最终演示验收清单

- 状态：`[ ]`
- 负责人：共享
- 任务目标：比赛前一天冻结功能，只验证演示闭环。
- 建议修改文件：
  - `storage/demo_materials/meetflow_recording_runbook.md`
  - `docs/final-demo-checklist.md`
- 验收标准：
  - Console 可以启动。
  - 预会简报链路可以跑通。
  - 会后总结链路可以跑通。
  - 风险扫描链路可以跑通。
  - LiteLLM 不可用时有降级说明。
  - 高并发演示有可展示的状态或压测结果。

完成记录：
- 状态：
- 分支 / 提交：
- 修改文件：
- 实现功能：
- 验证方式：
- 遗留问题：

## 5. 推荐执行顺序

第一阶段：先完成共享契约。

1. TASK-00-02
2. TASK-00-03
3. TASK-00-04

第二阶段：两人并行。

AI/RAG/LLM 负责人：

1. TASK-01-01
2. TASK-01-02
3. TASK-01-03
4. TASK-01-06
5. TASK-01-07
6. TASK-01-08

Runtime 负责人：

1. TASK-02-01
2. TASK-02-02
3. TASK-02-03
4. TASK-02-04
5. TASK-02-06
6. TASK-02-07

第三阶段：集成闭环。

1. TASK-03-01
2. TASK-03-02
3. TASK-03-03
4. TASK-03-04
5. TASK-04-01
6. TASK-04-02
7. TASK-04-03

第四阶段：演示冻结。

1. TASK-04-04
2. TASK-04-05

## 6. 每次完成任务后的记录要求

完成任何任务后，必须在本文件对应任务的“完成记录”中补充：

- 实际修改文件，而不是计划修改文件。
- 实际实现功能，而不是任务标题复述。
- 实际验证方式，包括命令、测试名称或人工验证步骤。
- 未完成内容或遗留风险。

如果任务修改了共享文件，例如 `core/contracts.py`、`core/ai_facade.py`、`config/loader.py`、`README.md`、`frontend/src/api/types.ts`，必须额外说明：

- 为什么必须修改共享文件。
- AI/RAG/LLM 侧是否需要适配。
- Runtime 侧是否需要适配。
