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

按照 [MeetFlow 当前代码改造思路](docs/current-code-improvement-plan.md) 的这一轮补强已经完成主链路修复：会前卡片按钮 value 不再写死 workflow 幂等键，回调层会按“本次点击”生成幂等键并兼容老卡片；`minute.ready` 和手动 `post_meeting_followup` 已补齐 `contact.get_current_user` / `contact.search_user`；会前刷新场景新增显式的只读上下文补全过程，会从当前 payload、项目记忆和本地历史工作流结果中补回会议标题、参与人、附件与相关资源；`allow_write` 不再挂在共享 loop 实例上，而是通过单次 `run()` 显式透传。对应修改文件包括 `cards/pre_meeting.py`、`core/card_actions.py`、`core/router.py`、`core/agent.py`、`core/agent_loop.py`、`core/workflows.py`、`core/pre_meeting.py`、`core/storage.py` 以及新增的 M3/M4 回归测试文件。本轮使用 `/home/tanyd/anaconda3/envs/meetflow/bin/python` 运行 `py_compile`、24 条针对性 `unittest`、以及 `scripts/agent_demo.py --event-type meeting.soon/minute.ready` 两条本地链路，结果均通过。

同时，基于当前 Agent Runtime 已完成一版结构化日志与观测增强，详细实现记录见
[M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md) 中的
`T2.8-O1 Agent 运行观测与结构化日志增强`。本次新增 `core/observability.py`
和 `tests/test_observability.py`，并接入 `MeetFlowAgent`、`MeetFlowAgentLoop`、
`LLMProvider`、`ToolRegistry`、`AgentPolicy` 判断点以及 `FeishuClient._request()`；
验证命令包括 `py_compile`、`unittest tests.test_observability` 和两条
`scripts/agent_demo.py` 本地链路，结构化事件输出到 `storage/workflow_events.jsonl`。
当前日志设计、新旧日志差异和测试方法已整理到
[MeetFlow 当前日志设计说明](docs/agent-logging-current-design.md)。

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
