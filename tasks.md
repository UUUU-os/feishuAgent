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

2026-05-06 修复 M4 飞书待确认任务卡填写后仍提示缺负责人/截止时间的问题。
真实飞书群卡片中，用户在“修改字段”窗口填写负责人和截止时间后，点击“保存修改”或
“确认创建”仍可能返回“任务缺少负责人或截止时间”。根因是飞书 schema 2.0 回调会把
`form_value` 包装在表单名下，例如 `{pending_form_x: {owner_override__item: ...}}`，
旧逻辑只读取顶层字段，导致后端继续拿到空值。本轮修改 `core/card_callback.py`，
新增 `find_form_value_by_key()`、`find_form_value_by_prefix()` 和
`sanitize_callback_text()`，支持递归读取嵌套表单字段，并清理 NUL 等控制字符，避免
卡片输入继续触发 `embedded null byte`。新增
`tests/test_post_meeting_card_callback.py` 回归用例，覆盖嵌套 form_value、负责人
`李健文\u0000` 清理、保存后再用旧空按钮确认创建仍成功的完整路径。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/card_callback.py tests/test_post_meeting_card_callback.py`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback`，
均通过；当前 M4 卡片回调测试 18 条通过。

2026-05-06 修复真实联调页 M4 真实发送时 `embedded null byte` 与布局溢出问题。
用户在前端点击 M4 真实发送后，Console API 返回底层 `embedded null byte`，页面同时出现
局部布局被长内容撑开的现象。根因是 M4/M5 前端输入可能从飞书页面复制时混入不可见控制
字符，后端直接把该字符串放入 `subprocess.run()` 参数时触发 Python 底层 ValueError。
本轮修改 `core/console_api.py`，新增 `clean_text_argument()` 和
`validate_command_arguments()`，在 M3/M4/M5 参数校验和命令执行前拒绝空字符及控制字符，
并返回可读的中文业务错误；新增 `tests/test_console_api.py` 回归用例覆盖 M4 minute 中
混入 `\x00` 的场景。前端修改 `frontend/src/pages/LiveFlowPage.tsx`，在 minute/chat_id
输入时清理控制字符；修改 `frontend/src/styles/app.css`，为真实联调布局、面板、日志和
表格长文本增加 `min-width: 0`、`overflow-wrap` 和 `pre-wrap`，避免错误或 stdout 撑坏页面。
验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/console_api.py tests/test_console_api.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api` 和
`git diff --check -- core/console_api.py tests/test_console_api.py frontend/src/pages/LiveFlowPage.tsx frontend/src/styles/app.css`，
均通过；当前 Console API 测试 11 条通过。

2026-05-06 按完整联调 Runbook 改进真实飞书群演示视频录制稿。
本轮更新 `MeetFlow_真实飞书群联调演示视频录制稿.md`，将视频主线从早期命令行脚本演示
调整为与 `docs/meetflow-full-live-test-runbook.md` 对齐的 Console 版真实联调录制方案。
新增录制窗口布局、终端启动脚本、前端 Dashboard/Jobs/真实联调/M3/M4/M5 操作镜头、
逐镜头解说词、飞书群按钮确认任务录制步骤、M5 风险巡检录制步骤、成片时间轴、失败兜底
素材、项目亮点和录制收尾检查。原智能客服工单会议素材继续保留，作为 M4 妙记内容准备
材料。本次为文档录制方案更新，未修改业务运行代码。

2026-05-06 新增一键真实联调控制台第二阶段设计方案。
本轮新增 `docs/one-click-live-test-console-phase2-design.md`，承接第一阶段真实联调
控制台落地结果，规划第二阶段重点能力：M3/M4/M5 异步入队与 job 轮询、完整
M3 -> M4 -> M5 演示模式、demo session 状态恢复、M4 待确认任务业务视图、M5
风险提醒业务视图，以及 OAuth、默认群、SDK 环境、Worker/回调服务健康检查。文档
包含后端 API、job payload、demo session 表、前端组件、实施顺序、测试计划和完成
标准。本次为设计文档更新，未修改业务运行代码。

2026-05-06 新增 MeetFlow 从零启动到真实飞书群完整联调 Runbook。
本轮新增 `docs/meetflow-full-live-test-runbook.md`，用于指导从基础质量检查、OAuth
授权、Console API、前端 Vite、前端真实联调页面，到 M3 会前卡片、M4 会后总结和待确认
任务卡、群内按钮确认、M5 风险巡检卡的完整运行与验收。文档明确推荐只手动启动
Console API 与前端两个长期终端，其余 Worker、SDK 回调和 M4 按钮回调优先通过前端
`真实联调` 页面启动；同时提供手动备用终端命令，并说明 SDK 统一回调与 M4 按钮回调
监听 card.action.trigger 时应二选一，避免重复处理。本次为文档 runbook 更新，未修改
业务运行代码。

2026-05-06 落地 MeetFlow Console 一键真实联调第一阶段。
本轮按照 `docs/one-click-live-test-console-code-design.md` 开始实现真实联调控制台。新增
`core/service_manager.py`，用白名单 profile 管理 Worker、SDK 回调和 M4 按钮回调等
长期服务，记录 PID、启动命令、日志路径和 `storage/runtime/services.json` 状态；扩展
`core/console_api.py`，新增 `M4ReadMinuteRequest`、`M4SendCardsRequest`、
`M5RiskScanRequest`，提供 `/api/services`、`/api/services/start`、
`/api/services/stop`、`/api/services/logs`、`/api/m4/read-minute`、
`/api/m4/send-cards`、`/api/m5/risk-scan` 以及 M4/M5 运行表查询能力，继续通过
`scripts/post_meeting_live_test.py`、`scripts/card_send_live.py` 和
`scripts/risk_scan_demo.py` 执行真实链路，不允许前端传任意 shell 命令。前端新增
`frontend/src/pages/LiveFlowPage.tsx`、`ServiceControlPanel`、`CommandResultPanel`，
并在 `App.tsx` 增加“真实联调”导航；页面支持服务启动/停止/日志查看、M4 妙记只读解析、
M4 dry-run/真实发卡、M5 local/feishu direct/enqueue 巡检和真实写入二次确认。同步更新
`docs/frontend-system-design.md` 与 `docs/overall-test-commands.md`。已执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/service_manager.py core/console_api.py scripts/meetflow_console_server.py tests/test_console_api.py`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api`，
10 条 Console API 测试通过；`npm run build` 因当前环境 `npm: command not found`
未能执行，需安装 Node.js/npm 后补跑前端构建。

2026-05-06 新增真实飞书群联调演示视频录制稿。
本轮新增 `MeetFlow_真实飞书群联调演示视频录制稿.md`，用于录制 MeetFlow 项目
Demo 视频。文档包含视频录制流程、可直接照念的解说词、终端演示命令、飞书群真实
测试步骤、独立的“大厂项目开发需求评审会”会议内容准备稿、项目整体功能介绍、各模块
演示目的和异常情况处理话术。会议素材覆盖 M4 会后总结、待确认任务和 M5 风险巡检
所需的需求澄清、前后端接口、数据库字段、权限、排期、测试策略和风险点。本次只新增
录制文档，未修改业务代码。

2026-05-06 重写 MeetFlow 整体测试命令文档，补齐前端启动与终端分工。
本轮重写 `docs/overall-test-commands.md`，在不改变原有测试命令含义的前提下，
将文档整理为 16 个执行章节：文档用途、快速启动总览、终端分工、最小测试流程、
前端启动、后端基础检查、SDK/HTTP 回调、Worker/Daemon、OAuth/飞书基础读、
M3/M4/M5 真实测试、SQLite 排查、提交前检查、按改动类型选择测试范围和常见问题
排查。新增 `frontend/` 启动命令、`npm run build` 构建检查、`127.0.0.1:5173`
访问地址，以及 Vite `/api` 代理到 `127.0.0.1:8787` 的说明；同时明确终端 1-5
分别用于前端、Console API/HTTP fallback、SDK 回调、Worker 和一次性测试排查。
已执行 `git diff --check -- docs/overall-test-commands.md` 通过。

2026-05-06 完成 MeetFlow Console 前端 UI/UX 优化。
本轮在不修改后端接口路径、不删除既有功能的前提下，重点优化 `frontend/src/**`
展示层。新增 `PageHeader`、`FeatureCard`、`StepList` 三个通用展示组件，改造
`App.tsx` 侧边导航、Dashboard、M3 会前背景卡、Agent 评测中心和 Jobs/Health 页面，
让首屏具备系统状态、核心能力入口、功能说明、状态标签、空状态提示和操作引导。M3
页面补充“配置参数 -> 连接飞书 -> Dry-run/真实发卡 -> 查看结果”步骤感，真实发卡仍
保留 `allow_write` 与二次确认弹窗；评测和 Jobs 页面补充质量门禁、migration、worker
dry-run 的说明和结果摘要。样式集中更新在 `frontend/src/styles/app.css`，采用更清晰的
SaaS/AI Agent 工作台布局、卡片层级、按钮状态、响应式布局和窄屏适配。已执行
`git diff --check` 通过；当前机器仍未安装 Node.js/npm，`node -v`、`npm -v` 不可用，
因此 `npm run build` 尚未在本机执行。`docs/overall-test-commands.md` 已补充前端
UI/UX 回归检查步骤。

2026-05-06 修正 M3 真实发卡日期窗口排查说明。
用户在 2026-05-06 执行 `scripts/card_send_live.py m3 --date tomorrow --event-title "MeetFlow 测试会议"`
时，实际查询窗口为 2026-05-07 本地整天；飞书日历中该窗口没有匹配会议，因此
`pre_meeting_live_test.py` 返回“给定时间窗口内没有可用于测试的会议”。本轮修改
`scripts/pre_meeting_live_test.py`，在无会议时输出查询窗口的本地绝对时间，并提示
使用 `--date today`、`--date YYYY-MM-DD` 或 `--event-id`；同步更新
`docs/overall-test-commands.md`，说明 `--date tomorrow` 的日期含义、today/绝对日期
替代命令以及 `--dry-run` 只打印下游命令不查询飞书。已执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile scripts/pre_meeting_live_test.py scripts/card_send_live.py`
和 M3 `--dry-run` 命令，均通过。

2026-05-06 完成 MeetFlow Console 第一版代码落地。
本轮新增 `core/console_api.py`、`scripts/meetflow_console_server.py`、
`tests/test_console_api.py` 和 `frontend/` React/Vite 控制台骨架。后端 facade
已提供 `/api/health`、`/api/dashboard`、`/api/jobs`、`/api/reports/latest`、
`/api/migrations/status`、`/api/evaluation/run`、`/api/m3/send-card`、
`/api/worker/run-once`，继续复用现有 `MigrationRunner`、`workflow_jobs`、
`storage/reports/**`、`scripts.agent_eval_suite.run_agent_eval_suite()` 和
`scripts/card_send_live.py m3`，不绕过 `AgentPolicy`、`ToolRegistry` 或
`FeishuClient`。前端第一版包含 Dashboard、M3 会前发卡、Agent 评测中心和
Jobs/Health 页面，所有真实发卡入口保留 `allow_write` 和二次确认。已同步更新
`architecture.md` 和 `docs/overall-test-commands.md`。验证命令包括
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/console_api.py scripts/meetflow_console_server.py tests/test_console_api.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api`，
以及启动 `/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py --host 127.0.0.1 --port 8787`
后用 `curl --noproxy '*'` 验证 `/api/health`、`/api/dashboard` 和
`/api/evaluation/run`，均通过；`/api/evaluation/run` 返回 `score=1.0`、
`safety_score=1.0`。当前机器未安装 Node.js/npm，前端 `npm install` 和
`npm run build` 尚未执行，测试命令文档已记录该前置条件。

2026-05-06 新增 MeetFlow Console 代码实现设计方案。
本轮新增 `docs/frontend-code-implementation-plan.md`，承接
`docs/frontend-system-design.md`，进一步明确前端控制台落地时的目录结构、
`core/console_api.py`、`scripts/meetflow_console_server.py`、`frontend/src/**`
职责划分、HTTP API、TypeScript DTO、M3 发卡 / Agent 评测 / Jobs Health 的实现
映射、安全副作用控制、分阶段实施顺序和验收命令。已同步更新
`docs/frontend-system-design.md`，加入代码实现方案入口。本次为文档设计更新，
未修改业务运行代码。

2026-05-05 补充 Agent 评测系统使用说明，并新增前端控制台设计方案。
`docs/overall-test-commands.md` 已补齐 `scripts/agent_eval_suite.py` 的单 case 运行、
写报告、报告路径、内置 case、输出字段、细项指标和当前 `scripted_debug` 基线结果；
`docs/tasks/m6-evaluation-demo.md` 已同步当前评测口径、指标解释和新增 case 时的文档
同步要求；新增 `docs/frontend-system-design.md`，提出 `MeetFlow Console` 工作台、
M3 会前发卡、M4 会后确认、M5 风险巡检、Agent 评测中心、Jobs/Health 的页面与 API
设计；`prd.md` 已补充管理控制台作为记忆与效果评估层的产品方向。本次为文档设计更新，
未修改业务运行代码。

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
