# MeetFlow 开发任务索引

本文档是 MeetFlow 任务拆解的入口索引。详细任务、实现记录和验证结果已按里程碑拆分到 `docs/tasks/`，避免单个 `tasks.md` 过长难以维护。

## 文档目标

这些任务文档用于将 `MeetFlow - 飞书会议知识闭环 Agent` 的 PRD 和架构方案拆解为可执行的开发任务清单，方便团队按阶段推进开发、联调、验证和答辩准备。

任务文档强调四件事：

- 先做什么，后做什么
- 每个模块需要完成哪些任务
- 每项任务完成的验收标准是什么
- 哪些任务是 Demo 必做，哪些是增强项

## 开发原则

- 优先跑通主链路，不先追求大而全
- 优先实现“会前 - 会后 - 巡检”闭环
- 优先保证结构化输出和证据链
- 优先保证任务可演示、可验收、可回放

## 优先级说明

- `P0`：必须完成，缺失会导致 Demo 主链路无法成立
- `P1`：重要增强，影响稳定性、可解释性和答辩效果
- `P2`：可选增强，适合有余力时补充

## 里程碑文档

- [M1：项目骨架与基础设施](docs/tasks/m1-foundation.md)
- [M2：飞书接入与数据读取](docs/tasks/m2-feishu-integration.md)
- [M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md)
- [M3：会前知识卡片工作流](docs/tasks/m3-pre-meeting.md)
- [M4：会后总结与任务落地工作流](docs/tasks/m4-post-meeting.md)
- [M5：风险巡检与提醒工作流](docs/tasks/m5-risk-scan.md)
- [M6：评估、答辩材料与演示脚本](docs/tasks/m6-evaluation-demo.md)
- [技术拆分、依赖关系、开发顺序与验收总表](docs/tasks/planning-and-acceptance.md)

## 当前重点

当前开发重点在 [M3：会前知识卡片工作流](docs/tasks/m3-pre-meeting.md)。

2026-05-05 修复 M3 真实发卡时 `assistant_sessions.user_id` NOT NULL 约束失败。
根因是本地 `storage/meetflow.sqlite` 中的 `assistant_sessions` 仍保留早期实验
schema 的 `user_id`、`chat_id`、`current_workflow` 等 NOT NULL 字段，而当前代码
已迁移到 `actor`、`workflow_type`、`memory_json` 字段，`save_assistant_session()`
没有兼容写入旧字段。已修改 `core/storage.py`，保存 assistant session 时按实际表
字段动态生成 INSERT，并为旧字段写入从 `actor` 和 `memory` 推导出的非空值；同时
修改 `core/assistant_memory.py`，把 `project_id` 纳入 session memory；新增
`tests/test_assistant_memory.py` 旧 schema 回归用例。验证命令包括
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/assistant_memory.py core/storage.py scripts/card_send_live.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_assistant_memory`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations` 和
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify`，
均通过。已按用户给出的 `scripts/card_send_live.py m3 --date tomorrow ... --write-report`
真实发卡命令复测成功，trace_id 为 `53fac20460b6`，状态为 `success`。

2026-05-05 修复飞书 SDK 隔离虚拟环境与主 `meetflow` 环境的版本冲突。
根因是 `.venv-lark-oapi` 曾由系统 Python 3.8 创建，既可能缺少 `bin/python`，
又无法导入项目中使用 `dataclass(slots=True)` 的模块；同时主
`/home/tanyd/anaconda3/envs/meetflow/bin/python` 没有安装 `lark-oapi`，
导致 SDK 回调入口落在两个环境之间。已修改 `scripts/setup_lark_oapi_venv.py`，
新增 Python 3.10+ 校验和 `--recreate` 重建开关；已更新
`docs/overall-test-commands.md`，明确主业务环境与 SDK 隔离环境的边界，并要求用
主 `meetflow` Python 创建 `.venv-lark-oapi`。本轮已执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate`、
`.venv-lark-oapi/bin/python -V`、`.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"`
以及 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile scripts/setup_lark_oapi_venv.py`，
结果均通过；当前 SDK 隔离环境为 Python 3.10.20。

按照 [MeetFlow 当前代码改造思路](docs/current-code-improvement-plan.md) 的这一轮补强已经完成主链路修复：会前卡片按钮 value 不再写死 workflow 幂等键，回调层会按“本次点击”生成幂等键并兼容老卡片；`minute.ready` 和手动 `post_meeting_followup` 已补齐 `contact.get_current_user` / `contact.search_user`；会前刷新场景新增显式的只读上下文补全过程，会从当前 payload、项目记忆和本地历史工作流结果中补回会议标题、参与人、附件与相关资源；`allow_write` 不再挂在共享 loop 实例上，而是通过单次 `run()` 显式透传。对应修改文件包括 `cards/pre_meeting.py`、`core/card_actions.py`、`core/router.py`、`core/agent.py`、`core/agent_loop.py`、`core/workflows.py`、`core/pre_meeting.py`、`core/storage.py` 以及新增的 M3/M4 回归测试文件。本轮使用 `/home/tanyd/anaconda3/envs/meetflow/bin/python` 运行 `py_compile`、24 条针对性 `unittest`、以及 `scripts/agent_demo.py --event-type meeting.soon/minute.ready` 两条本地链路，结果均通过。

2026-05-04 已完成协作者 M3/M4 代码与当前 M5 仓库的融合实现，完整方案见
[MeetFlow 代码仓库融合方案](docs/codebase-fusion-plan.md)。本轮新增或合入
`core/post_meeting.py`、`core/post_meeting_tools.py`、`core/card_callback.py`、
`core/confirmation_commands.py`、`cards/post_meeting.py`、`cards/layout.py`、
M4 demo/live/watcher 脚本以及对应测试；新增统一回调适配层
`adapters/feishu_callback_payloads.py` 和统一业务分发层
`core/feishu_callback_dispatcher.py`；新增 `scripts/feishu_event_sdk_server.py`
作为飞书官方 SDK WebSocket 长连接入口，同时改造 `scripts/feishu_event_server.py`
保留公网 HTTPS fallback。`core/agent.py` 已注册 M4 工具，`core/workflows.py`
已把 `minute.ready` 接入会后 artifact、总结卡、待确认任务和 RAG 计划；
`core/policy.py` 强制会后任务创建必须带人工确认上下文，`core/storage.py`
扩展 `task_mappings` 以衔接 M4 证据链与 M5 风险巡检。验证命令包括
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests`，
结果为 58 条测试全部通过。

同时，基于当前 Agent Runtime 已完成一版结构化日志与观测增强，详细实现记录见
[M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md) 中的
`T2.8-O1 Agent 运行观测与结构化日志增强`。本次新增 `core/observability.py`
和 `tests/test_observability.py`，并接入 `MeetFlowAgent`、`MeetFlowAgentLoop`、
`LLMProvider`、`ToolRegistry`、`AgentPolicy` 判断点以及 `FeishuClient._request()`；
验证命令包括 `py_compile`、`unittest tests.test_observability` 和两条
`scripts/agent_demo.py` 本地链路，结构化事件输出到 `storage/workflow_events.jsonl`。
当前日志设计、新旧日志差异和测试方法已整理到
[MeetFlow 当前日志设计说明](docs/agent-logging-current-design.md)。

2026-05-05 已开始按
[MeetFlow 工业化代码修改方案](docs/industrialization-code-change-plan.md)
落地 P0 工程化能力。本轮新增 `core/migrations.py`、
`scripts/storage_migrate.py` 和 `tests/test_migrations.py`，把
`MeetFlowStorage.initialize()` 改造为“准备目录 -> 执行 migrations -> 校验 schema”，
并新增 `schema_migrations` 与 `workflow_jobs` 表；新增 `core/jobs.py`、
`scripts/meetflow_worker.py` 和 `tests/test_jobs.py`，支持后台任务入队、领取、
重试、失败和死信状态；`scripts/meetflow_daemon.py` 已增加 `--enqueue`，
可把 M3/M4/RAG 机会写入队列；`scripts/feishu_event_sdk_server.py` 和
`scripts/feishu_event_server.py` 已增加 `--enqueue-agent`，保留原有同步/线程执行
路径；`scripts/risk_scan_demo.py` 已增加 `--enqueue`，可让 M5 巡检由 worker 执行。
新增配置 `jobs` 已接入 `config/loader.py` 与 `config/settings.example.json`。
验证命令包括 `py_compile`、`tests.test_migrations tests.test_jobs`、全量
`unittest discover -s tests`、`scripts/storage_migrate.py --status/--verify`、
`scripts/meetflow_worker.py --once --dry-run` 和 SDK server import 检查，当前
76 条单测全部通过。

2026-05-05 修复 M4 待确认任务卡“保存修改后仍提示缺少负责人或截止时间”的问题。
根因是确认创建时会先读取 pending registry，但随后用按钮 callback value 里的空
`owner/due_date` 覆盖了用户刚保存的字段；同时 SDK 长连接归一化没有完整保留
schema 2.0 表单的 `form_value`。本次修改 `core/card_callback.py`，新增
`merge_action_values_preserving_cached()`，确保空字段不覆盖已保存的负责人/截止时间；
修改 `adapters/feishu_callback_payloads.py`，在 `event.action`、`event.operator`
和顶层 payload 间归一化并保留 `form_value/input_value`。新增回归测试覆盖
“保存李四 + 2026-05-01 后点击旧空按钮仍能创建任务”和“SDK operator.form_value
不丢失”。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback tests.test_feishu_callback_dispatcher`
以及全量 `unittest discover -s tests`，当前 79 条测试全部通过。

2026-05-05 新增第一版项目级离线评测系统，避免项目停留在“真实联调脚本集合”。
本轮新增 `core/evaluation.py`、`scripts/e2e_replay.py`、`tests/test_e2e_replay.py`
和 `tests/e2e_fixtures/**/case.json` 脱敏样本。评测 runner 支持统一读取
fixture、执行 M3 会前卡片确定性产物、M4 会后行动项抽取、M5 风险扫描与
M4 task mapping 来源富化、SQLite job queue 入队/领取/成功路径，并输出
`score`、逐条断言、业务 artifacts 和可写入的 JSON 报告。当前内置 4 个
case：`m3_pre_meeting_basic`、`m4_post_meeting_with_tasks`、
`m5_risk_from_m4_mapping`、`job_queue_recovery`。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay`，
suite score 为 1.0。

2026-05-05 新增长期维护的
[MeetFlow 整体测试命令总表](docs/overall-test-commands.md)。该文档把基础编译、
全量单测、migration/job queue、离线 E2E 评测、SDK/HTTP 回调、daemon/worker、
M3/M4/M5 真实联调、SQLite 排查和提交前检查统一收敛到一个入口，并明确了
“新增脚本、配置、migration、job_type、回调路径、评测 case 或真实联调入口时
必须同步更新测试命令”的维护规则。`docs/current-version-test-commands.md`
已增加指向该总表的说明。

2026-05-05 新增
[MeetFlow LLM Agent 评测系统方案](docs/llm-agent-evaluation-system-plan.md)。
该方案在现有 `core/evaluation.py` 和 `scripts/e2e_replay.py` 的离线确定性评测
基础上，设计了更能体现飞书会议 Agent 特色的指标体系：会议上下文理解、
妙记行动项抽取、工具调用正确性、Policy 安全、证据引用、M4 到 M5 任务风险
闭环、卡片回调交互、真实 LLM provider 稳定性和 fallback。方案同时定义了
case schema、report schema、`core/llm_eval.py`、`scripts/llm_eval_suite.py`、
`core/llm_fallback.py` 的后续改造边界，以及 PR/每日/发布前的质量门禁阈值。
`docs/overall-test-commands.md` 已增加指向该方案的入口说明。

2026-05-05 新增智能会议 Agent 与工业化评测升级第一批代码实现。
基于 [MeetFlow 智能会议 Agent 与工业化评测系统升级方案](docs/intelligent-agent-and-eval-upgrade-design.md)
和 [MeetFlow 智能会议 Agent 与工业化评测代码修改方案](docs/intelligent-agent-and-eval-code-change-plan.md)，
本轮新增 `core/eval_trace.py`、`core/eval_metrics.py`、`scripts/agent_eval_suite.py`
以及 3 条 `tests/e2e_fixtures/agent_trajectory/` 评测样本，并在 `core/agent_loop.py`
和 `core/agent.py` 中接入 `assistant_plan`、`intelligence_signals` 和
`AgentRunResult.payload["agent_trace"]`。这使每次 Agent 运行都能输出可评测的
工具调用轨迹、Policy 决策轨迹、写权限/幂等信号和下一步建议，评测系统也新增了
tool-call F1、工具顺序、禁止工具、Policy 合规、allow-write gate、幂等键覆盖和
敏感信息泄露扫描。对应实现记录见
[M6：评估、答辩材料与演示脚本](docs/tasks/m6-evaluation-demo.md) 的
`T6.3 当前实现补强：Agent 轨迹与智能度评测`，测试命令已同步更新到
[MeetFlow 整体测试命令总表](docs/overall-test-commands.md)。本轮已通过
`py_compile`、新增评测单测、`scripts/agent_eval_suite.py --suite agent_trajectory --provider scripted_debug --fail-under 0.95`、
全量 91 条 `unittest discover -s tests` 和 `scripts/e2e_replay.py --all --fail-under 1.0`。

飞书群聊卡片按钮交互的目标链路、按钮协议、回调服务、CardActionRouter、
Policy/幂等/审计要求和测试步骤已整理到
[飞书群聊卡片按钮交互实施方案](docs/feishu-card-interaction-plan.md)。
对应的文件级代码改动草案、核心类函数签名、实现顺序和验收标准已整理到
[飞书卡片交互代码改动草案](docs/feishu-card-interaction-code-change-draft.md)。
当前已完成飞书卡片按钮交互 MVP：新增 `core/card_actions.py`、
`adapters/feishu_event_handler.py`、`scripts/card_action_demo.py`、
`scripts/feishu_event_server.py` 和对应单测；会前卡片已带 `刷新背景`、
`生成待办草案`、`发给我` 三个按钮，`refresh_pre_meeting_brief` 可转换为
`AgentInput(event_type="card.refresh_pre_meeting")`。实现记录见
[M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md) 中的
`T2.17 实现飞书群聊卡片按钮交互 MVP`。
公网 HTTPS 隧道接收飞书卡片回调的联调方法，以及后续与飞书官方 SDK/长连接
方式兼容的边界设计，已整理到
[飞书卡片交互公网回调接入说明](docs/feishu-card-public-callback-guide.md)。

2026-05-05 完成多轮会话记忆、用户补字段后自动恢复 pending action、M4 真实会后任务确认闭环补强。
本轮新增 `core/assistant_memory.py` 和 `tests/test_assistant_memory.py`，并修改
`core/migrations.py`、`core/storage.py`、`core/agent_loop.py`、`core/agent.py`、
`core/card_actions.py`、`core/card_callback.py`、`core/router.py`、
`tests/test_card_actions.py`、`tests/test_post_meeting_card_callback.py`、
`tests/test_migrations.py`、`docs/overall-test-commands.md`。
核心实现包括：
`assistant_sessions`、`pending_actions`、`clarification_questions`、`review_sessions`
四张 SQLite 表；`AgentPolicy` 返回 `needs_confirmation` 时自动保存可恢复动作和澄清问题；
用户下一轮补充负责人 / 截止时间时合并回 pending action，并标记 `ready_to_resume`，
恢复出的工具调用仍准备重新进入 `AgentPolicy`；M4 `confirm_create_task`、
`edit_task_fields`、`reject_create_task` 已进入 `CardActionRouter` 可观测路由；
`core/card_callback.py` 会把真实卡片确认批次写入 `review_sessions` 审计表，继续保留
review_session 旧卡拦截和任务创建幂等键。验证命令已同步更新到
[MeetFlow 整体测试命令总表](docs/overall-test-commands.md)。当前已通过：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py`
以及 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_assistant_memory tests.test_card_actions tests.test_post_meeting_card_callback tests.test_migrations`。

M5 风险巡检与提醒工作流的仓库级详细改造计划已整理到
[M5 风险巡检与提醒工作流详细改造计划](docs/m5-risk-scan-implementation-plan.md)，
建议先实现 `core/risk_scan.py`、`cards/risk_scan.py`、`scripts/risk_scan_demo.py`
和 `tests/test_risk_scan.py`，优先用 mock 任务跑通规则扫描、卡片预览和降噪。
第二版代码施工方案已整理到
[M5 风险巡检第二版代码改造方案](docs/m5-risk-scan-code-change-plan.md)，
按 `core/risk_scan.py`、`cards/risk_scan.py`、`scripts/risk_scan_demo.py`、
`core/storage.py`、`core/workflows.py`、`adapters/feishu_tools.py`、
`core/policy.py` 拆解了具体改造点、数据契约、补丁顺序、测试文件和验收命令。
当前已按该方案完成 M5 第二版核心改造：新增 `core/risk_scan.py`、
`cards/risk_scan.py`、`scripts/risk_scan_demo.py` 以及四组单测；
`RiskScanWorkflow` 已新增 `post_process_result()`，可从 `tasks.list_my_tasks`
工具结果生成 `risk_scan.scan_result`、`notification_decision` 和 `card_payload`；
`core/storage.py` 新增 `risk_notifications` 表，`core/policy.py` 和
`adapters/feishu_tools.py` 已增强风险卡片发送边界。验证命令包括
`py_compile`、M5 单测、本地风险 demo、`agent_demo.py --event-type risk.scan.tick`
和全量 `unittest discover`，结果均通过。

M3 的核心边界是“轻量 RAG + 结构化元数据 + 增量更新”：

RAGFlow 代码阅读中可借鉴的 RAG 设计已整理到 [RAGFlow 代码阅读笔记](docs/ragflow-design-notes.md)，作为后续增强 M3 检索、chunk 元数据、rerank 和索引任务的参考。

- T3.1：定义 `pre_meeting_brief` 工作流输入输出
- T3.2：实现会议主题识别
- T3.3：实现关联资源召回
- T3.4：实现轻量知识索引与文档清洗
- T3.5：实现证据排序与摘要生成
- T3.6：实现知识检索 Agent 工具
- T3.7：实现会前卡片模板
- T3.8：接入会前定时触发
- T3.9：增加手动兜底入口
- T3.10：预留知识变更更新机制
- T3.11：知识域与 embedding 模型一致性治理
- T3.12：扩展 chunk schema 与结构化位置元数据
- T3.13：实现可配置混合检索和可解释分数
- T3.14：接入可选 reranker 阶段
- T3.15：支持 TOC 增强与父子 chunk 展开
- T3.16：实现 evidence pack token budget 与稳定引用格式

关于 T3.10 的关键设计结论已经记录在 M3 文档中：`updated_at + checksum` 只能判断“检查后是否需要重建”，不能让系统第一时间知道文档变化；实时变化感知需要飞书事件订阅、Webhook 或 WebSocket，将变更写入 `index_jobs` 后由后台 worker 异步刷新索引。

## 维护约定

- 完成某个任务后，更新对应里程碑文档中的任务条目。
- 如果新增、删除或调整里程碑文档，更新本索引。
- 如果实现改变架构边界、Agent 流程或安全策略，同步更新 `architecture.md`。
- 如果实现改变用户场景、验收方式或产品目标，同步更新 `prd.md`。
