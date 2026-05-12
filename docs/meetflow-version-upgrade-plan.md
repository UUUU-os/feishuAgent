# MeetFlow 项目版本提升计划

## 1. 文档目的

本文面向当前 MeetFlow 代码库，给出下一阶段版本提升计划。它不是重新立项文档，而是在已有
M3/M4/M5 飞书会议闭环、卡片回调、后台队列、Console、结构化日志和 Agent 轨迹评测基础上，
把项目进一步提升为更贴合“办公场景驱动的智能知识助手”课题要求的可演示、可评测、可持续迭代版本。

本计划围绕课题一的三项核心挑战展开：

```text
Define it：把飞书文档、妙记、任务、消息提炼成当前场景最需要的高密度知识。
Build it：围绕会议和项目协作，在恰当时机主动推送卡片、报告、CLI/Console 提示。
Prove it：用业务评测、Agent 轨迹评测和真实飞书闭环数据证明准确性与效率价值。
```

方向选择继续保持：

```text
方向 B：会议与项目的全链路伴侣
核心主线：会前背景知识 -> 会后行动项落地 -> 会后风险追踪 -> 项目记忆沉淀
```

## 2. 阅读入口与当前基线

本计划基于以下文档和代码入口梳理：

- `prd.md`：已经明确 MeetFlow 是主动型会议知识协作 Agent，而不是普通问答机器人。
- `architecture.md`：主链路定义为 `AgentInput -> WorkflowRouter -> WorkflowContextBuilder -> MeetFlowAgentLoop -> ToolRegistry -> AgentPolicy -> FeishuClient / Storage`。
- `tasks.md` 与 `docs/tasks/**`：记录 M1-M6 里程碑、M3/M4/M5/M6 当前完成状态和验证命令。
- `docs/llm-agent-evaluation-system-plan.md`：定义 L0-L6 评测层级、Agent 工具调用、Policy、Evidence 和真实飞书闭环指标。
- `docs/intelligent-agent-and-eval-upgrade-design.md`：指出当前短板是“智能度不足”和“评测不够体现 Agent 特色”。
- `docs/intelligent-agent-and-eval-code-change-plan.md`：已有 Trace、PendingAction、M4 智能闭环、RAG 指标、LLM judge 等代码改造方向。
- `docs/feishu-card-interaction-plan.md` 与 `docs/feishu-card-interaction-code-change-draft.md`：已有飞书卡片按钮回调和 CardActionRouter 基础。
- `docs/frontend-system-design.md`、`docs/one-click-live-test-console-*.md`：已有 MeetFlow Console 运维与真实联调控制台方案。
- `docs/tasks/openclaw-demo-enhancement.md`：OpenClaw / CLI / Console 智能化演示增强的正式任务指引。
- `core/agent.py`、`core/agent_loop.py`、`core/workflows.py`、`core/tools.py`：当前 Agent 主运行时。
- `core/pre_meeting.py`、`core/post_meeting.py`、`core/risk_scan.py`、`core/knowledge.py`：当前 M3/M4/M5 与轻量 RAG 核心能力。
- `core/eval_trace.py`、`core/eval_metrics.py`、`core/evaluation.py`、`scripts/agent_eval_suite.py`、`scripts/e2e_replay.py`：当前离线回放与 Agent 轨迹评测能力。

当前项目已经具备的基础：

- M3 会前背景卡：会议主题识别、相关资源召回、会前卡片 payload、真实发卡脚本。
- M4 会后总结与待确认任务：妙记解析、总结卡、待确认任务卡、按钮回调、人工确认后创建任务。
- M5 风险巡检：任务风险扫描、M4 task mapping 来源富化、风险提醒卡、降噪记录。
- 飞书接入：SDK WebSocket 回调、HTTP fallback、OAuth Device Flow、真实读写联调脚本。
- 工程化：SQLite migrations、workflow_jobs、worker、daemon、结构化事件日志。
- 控制台：Dashboard、M3 发卡、真实联调、评测中心、Jobs/Health。
- 评测：确定性 E2E fixture、Agent trace、tool-call F1、Policy 合规、allow-write gate、幂等键覆盖。

当前主要版本短板：

- 知识定义仍偏“召回资料 + 摘要”，还没有统一的高密度知识对象和知识成熟度评分。
- 主动分发已经跑通 M3/M4/M5，但场景触发策略、卡片交互闭环和项目记忆还不够产品化。
- M4 是最能证明智能度的链路，但行动项抽取、负责人消歧、澄清恢复、任务映射仍可继续增强。
- RAG 已有 chunk、FTS、向量、evidence pack，但缺少面向 Docs/Minutes/Tasks/Messages 的统一证据质量门禁。
- 评测已有基础分数，但还需要补充真实 LLM 小样本、RAG faithfulness、用户反馈和效率指标。
- Console 已经能联调，但还可以升级为“演示总控台”和“评测证据展示台”。
- OpenClaw / CLI 需要从“可运行脚本集合”升级为有工具说明、统一入口、标准 JSON 输出和安全边界的受控调度入口。

## 3. 下一版本产品定位

下一版本建议命名为：

```text
MeetFlow V2：飞书会议与项目知识伴侣
```

一句话目标：

```text
在会议发生前后，自动识别当前项目上下文，从飞书知识碎片中提炼高密度背景、行动项和风险，
通过卡片/Console/CLI 主动触达相关人，并用可回放评测证明内容准确、安全可控、提升协作效率。
```

V2 不追求“全企业知识库”，而是聚焦一个强闭环：

```text
会前：这个会为什么开、上次结论是什么、现在必须看什么、还有哪些风险？
会后：会议决定了什么、谁要做什么、缺哪些字段、证据来自哪里？
跟进：哪些任务超期/阻塞、风险来自哪场会议、该提醒谁、是否需要再次开会？
证明：每条结论是否有证据、每个写操作是否安全、每次运行是否可复现可评分？
```

## 4. 版本路线图

### 4.1 V1.6：知识密度与证据质量补强

目标：让 MeetFlow 不只是“找到了资料”，而是能稳定输出“当前会议最该看的知识包”。

计划周期：1-2 周。

重点能力：

- 定义统一的 `KnowledgeBrief` / `EvidencePack` 业务对象。
- 强化 `knowledge.search` 返回字段：相关性原因、时间新鲜度、来源类型、证据覆盖实体、可信度。
- 为会前卡片增加“知识密度”结构：上次结论、当前问题、待确认事项、风险、必读材料。
- 为 M4 行动项增加证据片段质量检查：每个行动项必须能回链妙记片段或相关资料。
- 在评测中新增 RAG context precision / recall / citation rate / unsupported claim rate。

建议修改：

- `core/knowledge.py`
- `core/pre_meeting.py`
- `core/post_meeting.py`
- `core/eval_metrics.py`
- `scripts/agent_eval_suite.py`
- `tests/e2e_fixtures/**`
- `docs/llm-agent-evaluation-system-plan.md`

验收标准：

- M3 会前卡片中每个关键结论都有 `evidence_refs` 或明确标注“证据不足”。
- M4 行动项 `evidence_refs` 覆盖率达到 90% 以上。
- 新增至少 5 条 RAG/Evidence fixture。
- `scripts/agent_eval_suite.py --suite agent_trajectory --fail-under 0.95` 继续通过。
- `scripts/e2e_replay.py --all --fail-under 1.0` 继续通过。

### 4.2 V1.7：M4 会后智能闭环增强

目标：把 M4 做成最能展示 Agent 智能度的核心链路。

计划周期：1-2 周。

重点能力：

- 将妙记处理拆成更清晰的阶段：清洗、决策抽取、行动项抽取、负责人解析、字段缺失判断、review session 构建。
- 引入更强的 pending action 恢复：用户回复“负责人改成我”“截止明天下午”后能回到原行动项。
- 对“我/本人/姓名/多人候选”统一走联系人解析工具，不允许 LLM 编造 open_id。
- 确认创建任务后写入更完整的 `task_mappings`：会议、妙记、行动项、证据片段、任务 URL。
- M4 卡片按钮支持更完整动作：确认创建、修改字段、忽略任务、查看证据、全部确认。

建议修改：

- `core/assistant_memory.py`
- `core/card_callback.py`
- `core/post_meeting.py`
- `core/post_meeting_tools.py`
- `cards/post_meeting.py`
- `adapters/feishu_callback_payloads.py`
- `tests/test_post_meeting_card_callback.py`
- `tests/test_assistant_memory.py`

验收标准：

- 缺负责人/截止时间时不创建任务，而是进入待确认。
- 用户补字段后，pending action 重新经过 `AgentPolicy`。
- 重复点击旧卡片不会重复创建任务。
- 成功创建任务后，M5 能从 `task_mappings` 解释风险来源。
- 真实飞书群 M4 按钮回调链路可按 Runbook 完整录制。

### 4.3 V1.8：主动触发与项目记忆产品化

目标：从“能手动联调”提升到“能按会议/项目节奏主动工作”。

计划周期：1-2 周。

重点能力：

- 固化三类主动触发：
  - 会前 15-30 分钟自动推送 M3。
  - 妙记 ready 后自动推送 M4。
  - 每日或指定时间自动执行 M5。
- 沉淀项目记忆：
  - 项目背景、历史决策、常见参会人、开放风险、历史行动项。
  - 每条记忆包含来源、置信度、更新时间、过期策略。
- 为会前检索做 query 增强：会议标题弱时，结合参会人、历史会议、项目记忆、近期资料。
- Console 增加“项目记忆 / 会议记忆”只读视图，方便答辩展示系统不是一次性脚本。

建议修改：

- `core/assistant_memory.py`
- `core/storage.py`
- `core/pre_meeting_trigger.py`
- `scripts/meetflow_daemon.py`
- `scripts/meetflow_worker.py`
- `core/console_api.py`
- `frontend/src/pages/**`
- `tests/test_storage_risk_notifications.py`
- 新增 `tests/test_project_memory.py` 或合并到现有 memory 测试。

验收标准：

- M3 能用历史 M4/M5 结果增强会前背景。
- daemon/worker dry-run 能产生可解释的入队记录。
- 项目记忆不会保存敏感 token/secret/open_id 明文。
- Console 能展示最近项目记忆、来源和更新时间。

### 4.4 V2.0：效果证明与演示总控台

目标：让项目可以清楚证明“准确、可控、有价值”。

计划周期：1 周。

重点能力：

- 形成三层评测报告：
  - `deterministic_replay`：M3/M4/M5 确定性业务闭环。
  - `agent_trajectory`：工具调用、Policy、安全、幂等。
  - `knowledge_value`：证据召回、引用、行动项准确性、效率估计。
- 增加真实 LLM 小样本评测：
  - DeepSeek / OpenAI-compatible provider tool calling 稳定性。
  - 输出是否遵守证据与安全策略。
  - 失败原因分类和 fallback 记录。
- Console 评测中心升级：
  - 展示 case 明细、失败原因、trace timeline、RAG evidence。
  - 一键生成答辩材料需要的 JSON/Markdown 摘要。
- 定义业务价值指标：
  - 会前资料准备节省时间。
  - 行动项抽取准确率。
  - 负责人/截止时间补全率。
  - 卡片点击率/确认率。
  - 风险提醒有效率。
- 落地 OpenClaw / CLI 演示增强：
  - 统一 `scripts/meetflow_cli.py` 入口。
  - 提供 OpenClaw 工具说明和工具清单示例。
  - CLI 输出 `trace_id`、`workflow_type`、`status`、`report_path`、`safety_summary`。
  - CLI 默认 dry-run，真实写操作继续经过 `AgentPolicy` 和幂等检查。

建议修改：

- `core/evaluation.py`
- `core/eval_metrics.py`
- `scripts/e2e_replay.py`
- `scripts/agent_eval_suite.py`
- 新增或完善 `scripts/llm_eval_suite.py`
- `core/console_api.py`
- `frontend/src/pages/EvaluationPage.tsx`
- `docs/overall-test-commands.md`
- `docs/tasks/m6-evaluation-demo.md`
- `docs/tasks/openclaw-demo-enhancement.md`
- 新增 `docs/openclaw-meetflow-tool-guide.md`
- 新增 `docs/openclaw-demo-commands.md`
- 新增或完善 `scripts/meetflow_cli.py`

验收标准：

- 一键运行基础评测和 Agent 评测均通过。
- 评测报告中无 token、secret、API key、refresh token。
- 至少 10 条脱敏业务样本覆盖 M3/M4/M5。
- 至少 3 条真实 LLM 小样本记录，失败原因不伪造成功。
- Console 能展示评测分数、失败 case、trace、evidence 和建议修复项。
- OpenClaw / CLI 能以受控方式触发 health、M3、M4、M5、eval 和 demo replay。
- CLI 不允许绕过 `ToolRegistry`、`AgentPolicy` 或直接执行任意 shell 命令。

## 5. 核心设计升级

### 5.1 高密度知识对象

建议新增或强化统一数据结构：

```text
KnowledgeBrief
- brief_id
- workflow_type
- meeting_id
- project_id
- title
- summary
- last_decisions
- current_questions
- action_items
- risks
- must_read_resources
- evidence_refs
- confidence
- generated_at
```

业务含义：

- M3 输出的是会前 `KnowledgeBrief`。
- M4 输出的是会后 `KnowledgeBrief + ActionItems`。
- M5 输出的是风险 `KnowledgeBrief`。
- Console 和评测都围绕同一结构展示和打分。

落地建议：

- 先不新增过重表结构，可先放在 `workflow_results.payload` 与评测 fixture 中。
- 稳定后再加 `knowledge_briefs` 表，支持按项目/会议查询历史知识产物。

### 5.2 证据优先的 RAG 策略

当前 `core/knowledge.py` 已经有 FTS、向量、RRF、rerank、evidence pack 和 token budget。下一步要把它从“检索模块”提升为“证据治理模块”：

- 每条 evidence 必须有 `ref_id`、`source_type`、`source_url`、`snippet`、`updated_at`。
- 每条结论尽量引用 1-3 条 evidence。
- 低分证据只进入“可能相关资料”，不能支撑确定性结论。
- 召回混入无关资料时，评测要验证 Agent 是否能过滤噪声。
- `knowledge.fetch_chunk` 只在需要展开证据时调用，避免全文塞进上下文。

### 5.3 卡片成为交互界面

当前卡片已经能发送和回调。下一步把卡片从“展示结果”升级成“可继续推进的工作台”：

```text
M3 会前卡片：
- 刷新背景
- 标记资料无关
- 补充资料
- 发给我

M4 会后卡片：
- 确认创建
- 修改负责人
- 修改截止时间
- 忽略任务
- 查看证据

M5 风险卡片：
- 提醒负责人
- 标记已处理
- 稍后提醒
- 查看来源会议
```

所有按钮 value 统一带：

```json
{
  "action": "confirm_pending_action",
  "workflow_type": "post_meeting_followup",
  "session_id": "as_xxx",
  "meeting_id": "meeting_xxx",
  "review_session_id": "rv_xxx",
  "pending_action_id": "pa_xxx",
  "idempotency_key": "card_click:xxx"
}
```

安全边界：

- 回调入口只做验签、归一化、分发和快速响应。
- 写操作必须进入 `ToolRegistry` 与 `AgentPolicy`。
- M4 创建任务必须具备负责人、截止时间、人工确认和幂等键。

### 5.4 Agent 智能度补强

建议下一阶段把智能度放在三件可证明的事情上：

- 会理解上下文：能区分会前、会后、风险、补字段、确认、问答。
- 会追问和恢复：缺字段时提出澄清，用户补充后恢复 pending action。
- 会利用证据：生成结论时引用工具返回的真实 evidence，而不是泛泛总结。

可以逐步引入：

```text
core/intent.py
core/clarification.py
core/project_memory.py
core/meeting_memory.py
```

但不要急于推翻现有主链路。规则路由和卡片 action 仍然优先，自然语言意图理解作为补充。

## 6. 评测与证明体系

### 6.1 评测分层

建议最终保留四个可执行入口：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py \
  --all \
  --fail-under 1.0

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py \
  --suite knowledge_value \
  --provider deepseek \
  --case-limit 5 \
  --write-report
```

如果 `scripts/llm_eval_suite.py` 尚未完全落地，V2.0 前应补齐或将真实 LLM 小样本能力合并进 `agent_eval_suite.py`。

### 6.2 核心指标

准确性指标：

- `action_item_precision`
- `action_item_recall`
- `owner_resolution_accuracy`
- `due_date_extraction_accuracy`
- `risk_detection_precision`

证据指标：

- `context_precision`
- `context_recall`
- `evidence_citation_rate`
- `unsupported_claim_rate`
- `source_url_preservation`
- `evidence_budget_compliance`

Agent 指标：

- `tool_call_f1`
- `tool_order_score`
- `forbidden_tools_absent`
- `policy_compliance`
- `allow_write_gate`
- `idempotency_key_rate`
- `max_iteration_efficiency`

业务价值指标：

- `pre_meeting_minutes_saved_estimate`
- `task_confirmation_rate`
- `task_created_from_meeting_count`
- `risk_notification_ack_rate`
- `card_click_through_rate`
- `manual_correction_rate`

### 6.3 质量门禁

建议在提交前或答辩前执行：

```text
单元测试：全部通过
确定性 E2E：score >= 1.0
Agent 轨迹评测：score >= 0.95
安全分：safety_score == 1.0
写操作：必须显式 allow_write，且通过 AgentPolicy
真实飞书写入：只允许测试群/测试任务，必须有记录和可回滚说明
```

## 7. 演示路线

推荐答辩演示不从代码开始，而从一个真实业务故事开始：

```text
场景：一次项目需求评审会。
痛点：背景资料分散、会后待办容易丢、风险没人持续盯。
MeetFlow：
1. 会前自动推送背景卡，告诉参会人上次结论、必读资料和当前风险。
2. 会后读取妙记，生成总结和待确认任务卡。
3. 用户在群里补负责人/截止时间并确认创建飞书任务。
4. 任务进入系统后，M5 定时扫描并提醒逾期/阻塞风险。
5. Console 展示 trace、工具调用、Policy 决策和评测分数。
```

演示材料建议：

- 飞书群真实卡片录屏。
- Console Dashboard 和真实联调页。
- Agent trace 页面或 JSON 报告片段。
- 一份评测报告截图：score、safety_score、case 明细。
- 一张架构图：飞书事件 -> Agent -> 工具 -> Policy -> 飞书回写 -> 评测。

## 8. 风险与控制

### 8.1 飞书真实 API 不稳定

控制方式：

- 保留 `scripted_debug`、dry-run、fixture replay。
- 真实写操作必须手动 `allow_write`。
- 失败记录写入 `tasks.md` 或对应任务文档，说明真实失败原因。

### 8.2 LLM 幻觉和工具调用不稳定

控制方式：

- 工具返回结构化 evidence pack。
- Prompt 明确“证据不足就说明不足”。
- Policy 拦截写操作。
- Agent trace 评测工具调用顺序和结果使用。

### 8.3 卡片交互重复点击或旧卡片误触

控制方式：

- 使用点击级幂等键和任务级写操作幂等键。
- review session 状态机拦截旧卡。
- 回调层快速响应，复杂任务入队。

### 8.4 项目范围膨胀

控制方式：

- V2 仍只聚焦会议与项目协作。
- 不做全企业通用知识库。
- 不做无边界群聊机器人。
- 优先把 M4/M5 闭环和评测证明做深。

## 9. 推荐执行顺序

```text
第 1 步：补齐 KnowledgeBrief / EvidencePack 口径和评测 case。
第 2 步：增强 M4 pending action、负责人解析、证据回链和确认状态机。
第 3 步：让 M5 风险卡片支持来源会议解释和简单交互动作。
第 4 步：把项目记忆接入 M3 query 增强和 Console 只读展示。
第 5 步：扩展评测报告，补真实 LLM 小样本和业务价值指标。
第 6 步：整理演示 Runbook、录制稿、答辩指标页和失败兜底素材。
```

优先级建议：

```text
P0：M4 智能闭环、Policy 安全、证据回链、评测门禁。
P1：项目记忆、主动触发、Console 评测展示、真实 LLM 小样本。
P2：更多卡片交互、用户偏好、部署脚本、趋势图表。
```

## 10. 版本完成定义

MeetFlow V2 可以认为完成，当且仅当：

- M3/M4/M5 在本地 dry-run、离线 replay 和真实飞书测试群中都有可复现路径。
- 关键结论、行动项和风险都有来源或明确的证据不足说明。
- 飞书写操作全部经过 `AgentPolicy`，并保留幂等键与审计轨迹。
- Console 能一键跑评测，并展示分数、trace、失败原因和报告路径。
- 至少 10 条脱敏评测样本覆盖会前、会后、风险和卡片回调。
- 至少 1 条完整演示视频脚本能展示“主动知识推送 -> 任务确认落地 -> 风险追踪 -> 效果证明”。

最终答辩时应突出：

```text
不是“会议总结脚本”，而是“会前、会后、跟进、评测”一体化的飞书会议知识闭环 Agent。
不是“模型直接写飞书”，而是“LLM 负责推理，ToolRegistry 和 AgentPolicy 负责可控执行”。
不是“只看起来有用”，而是“用 trace、evidence、fixture 和真实联调记录证明它有用”。
```
