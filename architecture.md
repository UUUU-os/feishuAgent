# MeetFlow 架构设计文档

## 1. 文档目的

本文档用于定义 `MeetFlow - 飞书会议知识闭环 Agent` 的系统架构，作为后续 Demo 开发、模块拆分、接口联调和答辩说明的基础。

本文档重点回答四个问题：

- 系统整体由哪些模块组成
- Agent 在系统中如何编排工作
- 飞书生态数据如何流入、处理、再写回
- 首版 Demo 应该如何控制复杂度并优先落地

---

## 2. 架构目标

### 2.1 设计目标

系统架构需要同时满足以下目标：

- 支持主动触发，而不是只支持对话式问答
- 支持飞书文档、妙记、消息、任务的统一编排
- 支持可溯源的知识生成，降低幻觉风险
- 支持会前、会后、会后巡检三段式工作流
- 支持后续平滑扩展成多 Agent 或更多场景

### 2.2 设计原则

- 轻量优先：首版以单主 Agent 编排为主，不引入过重的分布式设计
- 工具优先：把能力拆成工具，而不是把每个能力都塞进提示词
- 证据优先：所有结论都需要来源链接或证据片段
- 可恢复优先：关键事件与结构化结果要落盘，避免流程中断后完全丢失
- 人机协同优先：高风险自动化动作支持人工确认

---

## 3. 总体架构

### 3.1 架构概览

MeetFlow 建议采用“五层架构 + 一个业务侧垂直 Agent”的形式：

1. 接入层
2. 触发与调度层
3. Agent 编排层
4. 知识处理层
5. 执行与回写层
6. 记忆与评估层

### 3.2 逻辑架构图

```text
+----------------------+
|      飞书生态        |
| docs / minutes /     |
| calendar / messages  |
| tasks / comments     |
+----------+-----------+
           |
           v
+----------------------+
|    接入层 Adapters   |
| Feishu API Wrapper   |
| Event Parser         |
+----------+-----------+
           |
           v
+----------------------+
| 触发与调度层         |
| Event Trigger        |
| Cron Scheduler       |
| Retry Queue          |
+----------+-----------+
           |
           v
+----------------------+
| 业务侧垂直 Agent     |
| MeetFlowAgent        |
| Intent / State       |
| Workflow Router      |
| Tool Dispatcher      |
+----------+-----------+
           |
           v
+----------------------+
| 知识处理层           |
| Recall / Ranking     |
| Summarize / Extract  |
| Evidence Builder     |
| Risk Detector        |
+----------+-----------+
           |
           v
+----------------------+
| 执行与回写层         |
| Card Sender          |
| Task Writer          |
| Table Updater        |
| Notification Sender  |
+----------+-----------+
           |
           v
+----------------------+
| 记忆与评估层         |
| Session Memory       |
| Project Memory       |
| History Store        |
| Metrics & Audit      |
+----------------------+
```

### 3.3 与 nanobot 设计的对应关系

本项目可以借鉴 nanobot 的几个核心思想，但不需要完全复制其运行时：

- `MessageBus` 思想：将飞书事件与 Agent 执行解耦，避免接入逻辑直接耦合业务逻辑
- `CronService` 思想：统一管理定时任务、延时任务和失败重试
- `SessionManager` 思想：为不同会议、群聊、项目建立独立上下文
- `Memory` 思想：把历史摘要、项目事实和当前会话分层管理
- `Hook` 思想：在关键节点做日志、审计、埋点和人工确认注入

---

## 4. 核心模块设计

## 4.1 接入层

### 职责

负责与飞书平台建立连接，并将外部数据转换成系统内部统一事件格式。

### 输入来源

- 飞书机器人消息
- 飞书日历事件
- 飞书文档内容
- 飞书妙记元数据与正文
- 飞书任务数据
- 评论、状态变更、成员信息

### 输出

- 标准化事件对象
- 标准化资源对象

### 建议模块

- `FeishuClient`
- `FeishuEventAdapter`
- `FeishuResourceAdapter`

### 统一资源模型建议

```text
Resource
- resource_id
- resource_type: doc | minute | task | message | comment | meeting
- title
- content
- source_url
- source_meta
- updated_at
```

### 统一事件模型建议

```text
Event
- event_id
- event_type
- event_time
- source
- actor
- payload
- trace_id
```

### 事件类型建议

- `meeting.soon`
- `minute.ready`
- `task.updated`
- `comment.added`
- `message.command`
- `risk.scan.tick`

---

## 4.2 触发与调度层

### 职责

负责把“什么时候该启动哪个工作流”这件事从 Agent 本体中拆出来。

### 核心能力

- 事件触发
- 定时触发
- 阈值触发
- 失败重试
- 幂等去重

### 设计原因

如果把调度直接写进 Agent Prompt，系统会出现三个问题：

- 流程时机不可控
- 失败后难以恢复
- 无法稳定支持主动服务

因此建议单独设计调度器。

### 调度器建议模块

- `EventRouter`
- `CronScheduler`
- `RetryScheduler`
- `IdempotencyGuard`

### 触发规则示例

#### 规则一：会前知识卡片

- 触发源：日历事件
- 条件：距离开始时间 30 分钟以内
- 动作：执行 `pre_meeting_brief` 工作流

#### 规则二：会后任务生成

- 触发源：妙记状态更新
- 条件：妙记转写完成
- 动作：执行 `post_meeting_followup` 工作流

#### 规则三：风险提醒

- 触发源：每日定时扫描
- 条件：任务超过 3 天未更新或距截止时间不足 24 小时
- 动作：执行 `risk_scan` 工作流

### 幂等设计

每个工作流执行前，需要校验如下幂等键：

- `meeting_id + workflow_type + trigger_time_bucket`
- `minute_token + workflow_type`
- `task_id + risk_type + date`

这样可以避免重复推送、重复建任务、重复提醒。

---

## 4.3 Agent 编排层

### 职责

作为系统核心，负责理解当前业务场景、维护执行状态、决定执行哪个流程、调用哪些工具、输出什么产物。

这里的 Agent 不是简单的“脚本入口”或“LLM 问答壳”，而是一个面向会议协作场景的垂直业务 Agent。它需要知道 MeetFlow 的业务目标：会前对齐背景、会后沉淀任务、持续巡检风险，并把飞书工具组织成一个可控闭环。

### 首版建议架构

首版不建议做复杂多 Agent，而建议采用：

**一个业务侧垂直 Agent + 工作流路由器 + 一组可组合工具**

### 垂直 Agent 与普通工作流的区别

工作流描述的是“某条链路怎么跑”，而垂直 Agent 负责“在什么上下文里选择哪条链路、如何保持状态、如何处理失败、如何避免重复动作”。因此 MeetFlowAgent 至少需要承担以下职责：

- 业务意图识别：判断当前事件是会前准备、会后跟进、风险巡检，还是人工命令
- 上下文构建：把会议、参与人、项目、历史文档、妙记和任务组织成一次执行上下文
- 工具编排：通过 ToolRegistry 调用日历、文档、妙记、任务、消息等工具
- 状态管理：记录工作流阶段、幂等键、已发送卡片、已创建任务和失败原因
- 人机协同：对低置信度行动项、危险写操作、重复提醒等情况触发确认或降级
- 可观测性：为每次 Agent 执行绑定 trace_id，落审计日志和结果快照

### 核心组件

- `MeetFlowAgent`
- `WorkflowRouter`
- `ToolRegistry`
- `WorkflowContextBuilder`
- `AgentStateStore`
- `AgentPolicy`

### 核心组件职责

```text
MeetFlowAgent
- Agent 主入口，接收 Event 或手动 Command
- 加载上下文，调用 WorkflowRouter
- 管理执行状态、失败降级和最终输出

WorkflowRouter
- 根据 event_type / command / schedule_tick 选择工作流
- 输出 workflow_type 和必要参数

ToolRegistry
- 统一注册 FeishuClient 能力和后续 LLM / Recall 工具
- 给工作流提供稳定的工具调用入口

WorkflowContextBuilder
- 从事件中解析 meeting_id / minute_token / task_id / project_id
- 聚合会议、文档、妙记、任务、项目记忆等上下文

AgentStateStore
- 记录 workflow_run、幂等键、已发卡片、任务映射、失败重试状态

AgentPolicy
- 控制自动化边界，例如低置信度任务不直接创建、风险提醒降噪、写操作是否需要确认
```

### 为什么首版不做多 Agent

因为比赛首版最关键的问题不是“Agent 够不够多”，而是：

- 飞书事件是否稳定接入
- 证据链是否完整
- 任务回写是否可控
- 整条链路是否能跑通

多 Agent 适合后期增强，不适合首版压主链路。

### 工作流枚举建议

- `pre_meeting_brief`
- `post_meeting_followup`
- `task_sync`
- `risk_scan`
- `manual_qa`

### 编排层输入

- 统一事件对象
- 工作流上下文
- 项目记忆
- 资源召回结果

### 编排层输出

- 结构化中间结果
- 待回写对象
- 日志与审计记录

### 工作流上下文建议

```text
WorkflowContext
- workflow_type
- event
- meeting_id
- project_id
- related_resources
- participants
- memory_snapshot
- trace_id
```

### Agent 输入输出建议

```text
AgentInput
- trigger_type: event | schedule | command
- event_type
- payload
- actor
- trace_id

AgentDecision
- workflow_type
- confidence
- reason
- required_tools
- idempotency_key

AgentRunResult
- trace_id
- workflow_type
- status
- summary
- produced_resources
- side_effects
- next_actions
```

### 首版 Agent 决策规则

首版可以先采用规则驱动，而不是一开始就让 LLM 决策所有路由：

- `meeting.soon` -> `pre_meeting_brief`
- `minute.ready` -> `post_meeting_followup`
- `risk.scan.tick` -> `risk_scan`
- `message.command` -> `manual_qa` 或指定工作流

LLM 更适合放在工作流内部做摘要、抽取和判断，而不是一开始就接管所有系统级路由。这样实现更稳定，也更容易在答辩时解释。

---

## 4.4 知识处理层

### 职责

负责把原始飞书数据加工成“可用知识”。

### 子模块拆分

- `ResourceRecallService`
- `EvidenceRanker`
- `Summarizer`
- `ActionItemExtractor`
- `DecisionExtractor`
- `RiskDetector`

### 处理流程

1. 根据会议或任务上下文召回资源
2. 对资源做清洗、切片、去重
3. 对证据片段排序
4. 调用 LLM 做摘要或抽取
5. 输出结构化结果
6. 为结构化结果挂上来源证据

### 关键设计点一：召回不是全量拼接

系统不应把相关文档一股脑塞给模型，而应先做：

- 资源筛选
- 内容切片
- 相关性排序
- 来源保留

建议优先保留以下高价值资源：

- 最近一次相关会议妙记
- 当前项目主文档
- 未关闭任务
- 最近 7 天高相关评论/消息

### 关键设计点二：结构化抽取优先

会后场景不能只输出自然语言总结，必须输出结构化对象，便于后续创建任务和做风险巡检。

### 结构化对象建议

```text
MeetingSummary
- meeting_id
- topic
- key_decisions[]
- open_questions[]
- action_items[]
- risks[]
- evidence_refs[]
```

```text
ActionItem
- item_id
- title
- owner
- due_date
- priority
- status
- confidence
- evidence_refs[]
- needs_confirm: bool
```

### 关键设计点三：证据回链

每条关键结论都应带：

- 来源类型
- 来源链接
- 证据片段
- 资源更新时间

这样便于：

- 降低幻觉风险
- 用户快速验证
- 答辩时展示“可信知识产品”

---

## 4.5 执行与回写层

### 职责

负责把知识处理结果转化为飞书内可见、可执行的产物。

### 回写类型

- 发送会前背景卡片
- 发送会后总结卡片
- 创建飞书任务
- 更新重点事项推进表
- 发送私聊提醒

### 核心模块

- `CardRenderer`
- `CardSender`
- `TaskWriter`
- `TableWriter`
- `Notifier`

### 卡片设计建议

#### 会前卡片

- 会议主题
- 背景摘要
- 上次会议关键决策
- 当前待解决问题
- 必读资料链接

#### 会后卡片

- 会议结论
- Action Items
- 待确认事项
- 风险点
- 原始纪要链接

#### 风险提醒卡片

- 风险任务列表
- 风险原因
- 截止时间
- 建议动作
- 跳转链接

### 任务写入策略

建议支持两种模式：

- `auto_create`：高置信度 Action Item 直接创建任务
- `confirm_then_create`：低置信度或关键事项先生成确认卡片，再写入任务系统

### 幂等策略

任务创建前检查：

- 是否已存在相同标题和相同负责人任务
- 是否已绑定同一个 `item_id`
- 是否已在推进表中登记

---

## 4.6 记忆与评估层

### 职责

负责沉淀项目长期知识、保存执行历史，并为效果验证提供数据支撑。

### 记忆分层设计

参考 nanobot 的分层记忆思想，MeetFlow 建议分为三层：

#### 1. Session Memory

面向单次工作流执行，保存当前事件上下文。

用途：

- 当前会前卡片生成
- 当前妙记解析
- 当前风险扫描任务

#### 2. Project Memory

面向单个项目或会议主题，保存长期稳定事实。

包括：

- 项目背景
- 核心成员映射
- 常见会议类型
- 长期决策口径
- 文档索引

#### 3. History Store

面向审计和评估，保存结构化历史结果。

包括：

- 生成过的会前卡片
- 会后总结
- Action Item 抽取记录
- 风险提醒记录
- 用户确认/纠错记录

### 建议存储结构

```text
storage/
├── sessions/
│   └── {trace_id}.json
├── projects/
│   └── {project_id}.json
├── summaries/
│   └── {meeting_id}.json
├── tasks/
│   └── action_items.jsonl
├── audits/
│   └── workflow_runs.jsonl
└── metrics/
    └── daily_metrics.json
```

### 评估埋点建议

- 会前卡片生成次数
- 会后总结生成次数
- Action Item 总数
- 任务自动创建成功数
- 待确认任务数
- 风险提醒触发数
- 用户点击卡片次数
- 用户修正任务字段次数

---

## 5. 核心工作流设计

## 5.1 会前工作流

### 名称

`pre_meeting_brief`

### 输入

- 日历事件
- 会议参与人
- 项目上下文

### 执行步骤

1. 根据会议标题匹配项目或议题
2. 召回最近相关妙记、项目文档、未完成任务
3. 提炼背景摘要与关键风险
4. 生成会前卡片
5. 回写到群聊或核心参会人私聊
6. 记录审计日志

### 输出

- 会前背景知识卡片
- `MeetingBrief` 结构化对象

---

## 5.2 会后工作流

### 名称

`post_meeting_followup`

### 输入

- 妙记 token
- 会议元信息
- 相关文档

### 执行步骤

1. 拉取妙记信息和内容
2. 提取会议结论和 Action Items
3. 标记低置信度事项
4. 构造会后总结卡片
5. 生成任务写入请求
6. 推送总结卡片和责任人通知
7. 写入结构化历史记录

### 输出

- `MeetingSummary`
- `ActionItem[]`
- 会后总结卡片
- 任务创建记录

---

## 5.3 风险巡检工作流

### 名称

`risk_scan`

### 输入

- 当前未完成任务列表
- 历史任务状态
- 项目规则

### 执行步骤

1. 拉取未关闭任务
2. 检查状态更新时间与截止时间
3. 识别逾期、长期未更新、负责人缺失等问题
4. 聚合生成风险提醒卡片
5. 对责任人私聊或对 PM 群推送
6. 记录风险事件

### 输出

- `RiskAlert[]`
- 风险提醒卡片

---

## 5.4 人工兜底工作流

### 名称

`manual_qa`

### 用途

用于 Demo 演示或事件失败时的兜底入口，例如：

- “帮我生成这次会议的会后总结”
- “帮我查看项目 A 最近未完成的事项”
- “这次会议有哪些 Action Item 还没落到任务里”

这样即使自动触发链路出现问题，系统仍有可演示入口。

---

## 6. 工具设计

### 6.1 工具拆分原则

每个工具只负责一类明确能力，避免大而全工具难以测试和复用。

### 6.2 建议工具列表

#### 飞书读取类

- `get_calendar_event`
- `get_doc_content`
- `get_minute_meta`
- `get_minute_content`
- `get_task_list`
- `get_task_detail`
- `get_comments`

#### 知识处理类

- `recall_related_resources`
- `rank_evidence`
- `summarize_meeting_context`
- `extract_action_items`
- `detect_risks`

#### 飞书写入类

- `send_group_card`
- `send_private_card`
- `create_feishu_task`
- `update_tracking_table`

#### 存储与审计类

- `save_workflow_result`
- `load_project_memory`
- `update_project_memory`
- `record_metric`

### 6.3 工具调用边界

建议遵循：

- Agent 只决定“调用什么工具”
- 工具自己保证参数合法性、错误重试和接口兼容
- LLM 不直接拼 API URL，也不直接写原始飞书请求体

这样后续更利于稳定性与测试。

---

## 7. 数据模型设计

## 7.1 MeetingBrief

```json
{
  "meeting_id": "m_001",
  "topic": "项目周会",
  "project_id": "p_alpha",
  "participants": ["u1", "u2"],
  "last_decisions": ["上线时间延后到下周三"],
  "current_risks": ["接口联调尚未完成"],
  "must_read_docs": [
    {
      "title": "需求评审纪要",
      "url": "https://..."
    }
  ]
}
```

## 7.2 MeetingSummary

```json
{
  "meeting_id": "m_001",
  "project_id": "p_alpha",
  "decisions": ["先完成 MVP，再补统计能力"],
  "open_questions": ["埋点方案待确认"],
  "action_items": ["a1", "a2"],
  "evidence_refs": ["doc_1#block_3", "minute_2#seg_8"]
}
```

## 7.3 RiskAlert

```json
{
  "risk_id": "r_001",
  "task_id": "t_123",
  "risk_type": "overdue",
  "severity": "high",
  "reason": "距离截止时间已超 2 天且无更新",
  "owner": "ou_xxx",
  "suggestion": "请确认是否延期或补充阻塞原因"
}
```

---

## 8. 存储方案建议

### 8.1 首版 Demo 建议

首版不必引入复杂数据库，建议采用：

- 本地 JSON / JSONL
- 一个轻量 SQLite
- 或多维表格作为业务展示层

推荐组合：

- `SQLite`：存工作流记录、任务映射、幂等键、指标
- `JSON`：存项目记忆和配置
- `Feishu Bitable`：存团队推进总表，方便演示

### 8.2 为什么不建议首版直接上复杂向量库

因为比赛首版真正的关键是闭环，不是大规模知识检索。当前场景里最重要的是：

- 会议相关资源召回
- 近期文档与任务的结构化链接
- 证据链保留

如果后续资料量变大，再考虑接入向量索引。

---

## 9. 错误处理与可靠性设计

## 9.1 常见失败场景

- 飞书接口限流
- 妙记尚未完成转写
- 文档权限不足
- 任务创建失败
- 同一事件重复触发
- LLM 输出结构不稳定

## 9.2 对应策略

### 飞书接口失败

- 工具层统一重试
- 对限流错误做指数退避
- 超过阈值后进入重试队列

### 妙记未就绪

- 标记为 `pending`
- 在 5 分钟后重新调度
- 超过最大重试次数后转人工兜底

### LLM 结构化输出异常

- 使用 JSON Schema 或结构化解析
- 二次修复失败则降级为摘要模式
- 高风险动作不执行写入，只生成待确认卡片

### 重复触发

- 使用幂等键与执行锁
- 回写前检查是否已有结果

---

## 10. 安全与权限设计

### 10.1 权限原则

- 最小权限接入飞书能力
- 读写权限分离
- 高风险写入动作支持开关控制

### 10.2 数据安全原则

- 敏感信息不写入 Prompt
- 只传必要片段给模型
- 审计日志中对敏感字段做脱敏

### 10.3 回写安全策略

以下情况默认建议进入确认模式：

- 负责人置信度低
- 截止时间缺失
- 涉及多个负责人
- 任务标题语义不明确

---

## 11. 首版 Demo 技术路线

## 11.1 推荐最小可行实现

建议首版只实现以下主链路：

1. 定时检测即将开始的会议
2. 召回项目文档与最近妙记
3. 生成会前卡片并推送
4. 监听妙记完成后生成会后总结
5. 自动创建或待确认创建任务
6. 每日扫描任务风险并提醒

### 11.2 推荐技术组合

- OpenClaw：作为 Agent 运行时和通道接入基础
- CLI 调度脚本：承接定时任务与巡检逻辑
- 飞书开放平台 API：读取文档/妙记/任务，发送卡片
- SQLite：存审计、指标和幂等数据

### 11.3 目录结构建议

```text
feishuAgent/
├── prd.md
├── architecture.md
├── config/
│   └── settings.json
├── adapters/
│   └── feishu_client.py
├── workflows/
│   ├── pre_meeting.py
│   ├── post_meeting.py
│   └── risk_scan.py
├── tools/
│   ├── recall.py
│   ├── summary.py
│   ├── extract.py
│   └── task_writer.py
├── storage/
│   ├── db.sqlite
│   └── projects/
└── cards/
    ├── pre_meeting.json
    ├── post_meeting.json
    └── risk_alert.json
```

---

## 12. 后续扩展方向

在首版跑通后，可以继续扩展：

- 引入项目级向量检索
- 引入多 Agent 协作
- 将群聊消息纳入知识证据源
- 接入 CLI 本地提醒
- 增加用户反馈按钮与在线纠错
- 增加多维表格大屏看板

### 多 Agent 扩展建议

如果后续需要增强，可拆成：

- `RecallAgent`：专门负责资源召回与排序
- `MeetingAgent`：专门负责会前/会后知识生成
- `TaskAgent`：专门负责 Action Item 写入任务系统
- `RiskAgent`：专门负责周期巡检与异常提醒

但这一步建议放在首版 Demo 验证完成之后。

---

## 13. 架构结论

MeetFlow 的核心不是做一个“会聊天的飞书机器人”，而是做一个围绕会议协作链路的主动式知识执行系统。

它的架构关键点在于：

- 用事件和调度驱动工作流
- 用主编排 Agent 调用工具完成知识处理
- 用结构化对象承接摘要、任务和风险结果
- 用飞书卡片、任务和推进表作为最终知识产物
- 用分层记忆和审计数据支撑长期迭代与效果证明

对于比赛首版，最合适的实现路径是：

**单主 Agent + 多工具 + 定时/事件调度 + 结构化回写**

这条路线足够轻、足够稳，也足够展示产品价值和工程完成度。
