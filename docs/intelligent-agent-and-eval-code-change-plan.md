# MeetFlow 智能会议 Agent 与工业化评测代码修改方案

## 1. 文档目的

本文承接 `docs/intelligent-agent-and-eval-upgrade-design.md`，把“智能会议 Agent + 工业化评测系统”的总设计拆成具体代码改动方案。

目标不是一次性推翻当前代码，而是在当前已经存在的工业化基础上增量升级：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

本方案分两条主线：

- Agent 智能化：意图理解、会话状态、澄清恢复、M4 会后闭环、会议记忆、卡片交互。
- 评测工业化：trace schema、Agent 轨迹评测、RAG 证据评测、Policy 安全评测、LLM judge、baseline 对比和真实飞书样本回流。

---

## 2. 总体实施顺序

建议按下面顺序实施，避免同时改太多核心链路：

```text
Phase 1：Trace 与评测底座
Phase 2：AssistantSession / PendingAction / Clarification
Phase 3：M4 会后智能闭环
Phase 4：Agent trajectory / Policy / RAG 指标
Phase 5：LLM judge 与 baseline comparison
Phase 6：真实飞书 trace 脱敏回流
Phase 7：记忆与主动建议增强
```

为什么先做 trace：

- 没有 trace，后续很难评估“智能度”是否真的提升。
- trace 对业务行为影响小，适合作为第一批低风险基础设施。
- Agent 轨迹、RAG 证据、Policy 评测都依赖 trace。

---

## 3. Phase 1：统一 Agent Trace 底座

## 3.1 目标

把一次 Agent 运行中的关键过程记录成可评测、可回放、可脱敏的结构：

```text
input
route decision
context
assistant plan
llm messages
tool calls
tool results
policy decisions
side effects
final answer
job/callback metadata
```

## 3.2 新增文件

```text
core/eval_trace.py
tests/test_eval_trace.py
```

## 3.3 修改文件

```text
core/agent.py
core/agent_loop.py
core/tools.py
core/policy.py
core/observability.py
core/models.py
```

## 3.4 核心模型

`core/eval_trace.py`：

```python
@dataclass(slots=True)
class AgentTrace:
    """一次 Agent 运行的可评测轨迹。"""
    trace_id: str
    workflow_type: str
    case_id: str = ""
    input_summary: dict[str, Any] = field(default_factory=dict)
    route_decision: dict[str, Any] = field(default_factory=dict)
    context_summary: dict[str, Any] = field(default_factory=dict)
    assistant_plan: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    policy_decisions: list[PolicyDecisionTrace] = field(default_factory=list)
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    status: str = ""
    started_at: int = 0
    finished_at: int = 0
```

```python
@dataclass(slots=True)
class ToolCallTrace:
    """工具调用轨迹，用于评估工具选择、参数和顺序。"""
    call_id: str
    tool_name: str
    llm_tool_name: str
    arguments: dict[str, Any]
    arguments_hash: str
    schema_valid: bool
    status: str
    result_summary: dict[str, Any]
    started_at: int
    finished_at: int
```

```python
@dataclass(slots=True)
class PolicyDecisionTrace:
    """Policy 决策轨迹，用于评估写操作安全性。"""
    tool_name: str
    side_effect: str
    status: str
    reason: str
    required_fields: list[str]
    idempotency_key_present: bool
    allow_write: bool
```

## 3.5 接入点

`MeetFlowAgent.run()`：

- 创建 `AgentTrace`
- 写入 input、route、context、result
- 将 trace 放入 `AgentRunResult.payload["agent_trace"]`

`MeetFlowAgentLoop._handle_tool_calls()`：

- 每次模型请求工具时记录 tool call
- 每次 policy 判断时记录 policy decision
- 每次 tool result 时记录 result summary

`ToolRegistry.execute()`：

- 增加 `schema_valid` 和 `arguments_hash`
- 不保存完整敏感参数，只保存脱敏参数摘要和 hash

## 3.6 测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_eval_trace
```

验收：

- 一次 dry-run Agent 能生成 `agent_trace`
- trace 中包含工具调用顺序
- trace 中不包含 token、secret、API key

---

## 4. Phase 2：会话状态、待确认动作和澄清恢复

## 4.1 目标

让 Agent 从“单次运行”升级为能跨消息/卡片动作延续上下文。

## 4.2 新增文件

```text
core/assistant_state.py
core/clarification.py
core/assistant_memory.py
tests/test_assistant_state.py
tests/test_clarification.py
tests/test_pending_action_resume.py
```

## 4.3 修改文件

```text
core/storage.py
core/agent.py
core/agent_loop.py
core/policy.py
core/card_actions.py
cards/post_meeting.py
scripts/feishu_event_sdk_server.py
scripts/feishu_event_server.py
```

## 4.4 数据表

通过 migration 新增：

```sql
CREATE TABLE assistant_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT '',
  chat_id TEXT NOT NULL DEFAULT '',
  current_workflow TEXT NOT NULL DEFAULT '',
  current_meeting_id TEXT NOT NULL DEFAULT '',
  current_project_id TEXT NOT NULL DEFAULT '',
  state_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
```

```sql
CREATE TABLE pending_actions (
  action_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  workflow TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  arguments_json TEXT NOT NULL,
  missing_fields_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  reason TEXT NOT NULL,
  idempotency_key TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
```

```sql
CREATE TABLE clarification_questions (
  question_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  related_action_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  fields_json TEXT NOT NULL,
  candidates_json TEXT NOT NULL,
  prompt TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
```

## 4.5 核心流程

```text
AgentPolicy -> needs_confirmation
  -> create PendingAction
  -> create ClarificationQuestion
  -> send message/card to user
  -> user reply/card click
  -> IntentClassifier: modify_pending_action / confirm_action
  -> load PendingAction
  -> apply patch
  -> AgentPolicy again
  -> execute tool if allowed
```

## 4.6 关键函数

```python
def resolve_or_create_session(agent_input: AgentInput, decision: AgentDecision) -> AssistantSession:
    ...
```

```python
def create_pending_action_from_policy_decision(...) -> PendingAction:
    ...
```

```python
def apply_user_reply_to_pending_action(action: PendingAction, reply: str) -> PendingActionPatch:
    ...
```

```python
def resume_pending_action(action_id: str, patch: PendingActionPatch) -> AgentRunResult:
    ...
```

## 4.7 测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_assistant_state \
  tests.test_clarification \
  tests.test_pending_action_resume
```

验收：

- 缺负责人/截止时间时不会创建任务。
- pending action 能落库。
- 用户补字段后能重新经过 Policy。
- 重复确认不会重复创建任务。

---

## 5. Phase 3：M4 会后智能闭环

## 5.1 目标

让 M4 成为“智能会议 Agent”的核心演示能力：从妙记理解会议、抽取行动项、确认缺失字段、创建任务、映射到风险扫描。

## 5.2 新增文件

```text
core/post_meeting_intelligence.py
core/action_item_extractor.py
core/review_session.py
cards/post_meeting_review.py
tests/test_action_item_extractor.py
tests/test_review_session.py
tests/test_post_meeting_intelligence.py
```

## 5.3 修改文件

```text
core/workflows.py
core/models.py
core/storage.py
core/policy.py
core/card_actions.py
adapters/feishu_tools.py
cards/post_meeting.py
scripts/post_meeting_live_test.py
scripts/card_send_live.py
```

## 5.4 核心模型

```python
@dataclass(slots=True)
class ExtractedActionItem:
    """从妙记中抽取出的候选任务，落地前必须经过解析和确认。"""
    item_id: str
    title: str
    description: str
    owner_text: str = ""
    assignee_ids: list[str] = field(default_factory=list)
    due_text: str = ""
    due_timestamp_ms: int = 0
    priority: str = "medium"
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    needs_confirmation: bool = False
```

```python
@dataclass(slots=True)
class ReviewSession:
    """会后任务确认会话，用于卡片按钮确认/修改/拒绝候选任务。"""
    review_session_id: str
    meeting_id: str
    minute_token: str
    chat_id: str
    action_items: list[ExtractedActionItem]
    status: str
    created_at: int
    updated_at: int
```

## 5.5 关键函数

`core/action_item_extractor.py`：

```python
def clean_minute_text(text: str) -> CleanedMinute:
    ...
```

```python
def extract_action_items_with_llm(context: WorkflowContext, minute_text: str) -> list[ExtractedActionItem]:
    ...
```

```python
def normalize_action_item(raw: dict[str, Any]) -> ExtractedActionItem:
    ...
```

```python
def split_auto_and_pending(items: list[ExtractedActionItem]) -> tuple[list[ExtractedActionItem], list[ExtractedActionItem]]:
    ...
```

`core/review_session.py`：

```python
def create_review_session(...) -> ReviewSession:
    ...
```

```python
def confirm_review_item(review_session_id: str, item_id: str, actor: str) -> PendingAction:
    ...
```

```python
def update_review_item_field(review_session_id: str, item_id: str, field_name: str, value: Any) -> ReviewSession:
    ...
```

## 5.6 Workflow 改造

`PostMeetingFollowupWorkflow`：

```text
prepare_context
  -> fetch minute
  -> clean minute
  -> load meeting/project memory

agent_loop
  -> extract summary / decisions / actions
  -> resolve owner when possible

post_process_result
  -> create review session
  -> create pending actions
  -> render post meeting review card
  -> save mappings after confirmed task creation
```

## 5.7 测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_action_item_extractor \
  tests.test_review_session \
  tests.test_post_meeting_intelligence \
  tests.test_post_meeting_card_callback
```

真实只读：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae" \
  --read-only \
  --show-card-json
```

真实发卡：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae" \
  --show-card-json
```

---

## 6. Phase 4：Agent / Policy / RAG 指标实现

## 6.1 目标

把智能度变成可运行指标。

## 6.2 新增文件

```text
core/eval_metrics.py
core/eval_case.py
scripts/agent_eval_suite.py
scripts/rag_eval_suite.py
scripts/policy_safety_eval.py
tests/test_eval_metrics.py
tests/test_agent_eval_suite.py
tests/test_rag_eval_suite.py
tests/test_policy_safety_eval.py
```

## 6.3 Agent 轨迹指标

`core/eval_metrics.py`：

```python
def score_tool_call_precision(actual: list[str], expected: list[str]) -> float:
    ...
```

```python
def score_tool_call_recall(actual: list[str], expected: list[str]) -> float:
    ...
```

```python
def score_tool_call_f1(actual: list[str], expected: list[str]) -> float:
    ...
```

```python
def score_tool_order(actual: list[str], constraints: list[dict[str, str]]) -> float:
    ...
```

```python
def score_tool_argument_schema(trace: AgentTrace) -> float:
    ...
```

## 6.4 Policy 指标

```python
def score_policy_compliance(trace: AgentTrace) -> float:
    ...
```

```python
def score_allow_write_gate(trace: AgentTrace) -> float:
    ...
```

```python
def score_idempotency_key_rate(trace: AgentTrace) -> float:
    ...
```

```python
def score_secret_leakage_absent(report: dict[str, Any]) -> float:
    ...
```

## 6.5 RAG 指标

```python
def score_context_precision(retrieved_refs: list[str], expected_refs: list[str]) -> float:
    ...
```

```python
def score_context_recall(retrieved_refs: list[str], expected_refs: list[str]) -> float:
    ...
```

```python
def score_evidence_citation_rate(output: dict[str, Any]) -> float:
    ...
```

```python
def score_unsupported_claim_rate(output: dict[str, Any], evidence: list[dict[str, Any]]) -> float:
    ...
```

说明：

- precision / recall 优先用代码指标。
- faithfulness 可接 LLM judge。
- unsupported claim 可先用规则 + judge 混合。

## 6.6 Case schema

新增：

```text
tests/e2e_fixtures/agent_trajectory/*.json
tests/e2e_fixtures/rag_evidence/*.json
tests/e2e_fixtures/policy_safety/*.json
tests/e2e_fixtures/judge_rubrics/*.json
```

case 示例：

```json
{
  "case_id": "m4_owner_missing_needs_confirmation",
  "workflow": "post_meeting_followup",
  "input": {
    "event_type": "minute.ready",
    "payload": {"minute_text": "灰度发布下周三前完成。"}
  },
  "expected": {
    "must_call_tools": ["minutes.fetch_resource"],
    "must_not_call_tools": ["tasks.create_task"],
    "tool_order_constraints": [],
    "policy_status": "needs_confirmation",
    "missing_fields": ["assignee_ids"]
  }
}
```

## 6.7 命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/rag_eval_suite.py \
  --suite rag_evidence \
  --provider scripted_debug \
  --fail-under 0.85 \
  --write-report
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/policy_safety_eval.py \
  --fail-under 1.0 \
  --write-report
```

---

## 7. Phase 5：LLM Judge 与 Baseline

## 7.1 新增文件

```text
core/eval_judge.py
core/eval_report.py
core/eval_baseline.py
scripts/eval_report_compare.py
tests/test_eval_judge.py
tests/test_eval_report.py
tests/test_eval_baseline.py
```

## 7.2 Judge 输出协议

```python
@dataclass(slots=True)
class JudgeResult:
    """LLM judge 的结构化评分结果。"""
    metric_name: str
    score: float
    label: str
    reason: str
    evidence: list[str]
    failure_type: str = ""
    judge_model: str = ""
    judge_prompt_version: str = ""
```

judge 必须通过 JSON schema 或 tool calling 输出结构化结果，不解析自由文本。

## 7.3 Judge 类型

```text
faithfulness_judge
answer_relevancy_judge
task_completion_judge
clarification_quality_judge
next_best_action_judge
```

## 7.4 Baseline 对比

`core/eval_baseline.py`：

```python
def compare_eval_reports(current: EvalReport, baseline: EvalReport) -> BaselineComparison:
    ...
```

阻断规则：

```text
overall_score 下降 > 5%
policy_safety 任一关键指标 < 1.0
secret_leakage_absent = false
dead_letter_rate 高于阈值
```

## 7.5 命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/eval_report_compare.py \
  --current storage/reports/evaluation/latest.json \
  --baseline storage/reports/evaluation/baseline.json \
  --fail-on-regression
```

---

## 8. Phase 6：真实飞书 Trace 脱敏回流

## 8.1 目标

把真实联调中的成功/失败 trace 转成可复跑评测样本。

## 8.2 新增文件

```text
core/redaction.py
scripts/export_redacted_live_case.py
tests/test_redaction.py
tests/test_export_redacted_live_case.py
```

## 8.3 脱敏规则

必须脱敏：

```text
access_token
refresh_token
app_secret
api_key
open_id
union_id
chat_id
document_id
minute_token
calendar_event_id
task_id
真实 URL query
```

保留：

```text
资源类型
状态码
错误码
工具序列
字段是否存在
脱敏后的证据片段
任务数量
卡片按钮类型
```

## 8.4 命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/export_redacted_live_case.py \
  --trace-id <trace_id> \
  --suite agent_trajectory \
  --output tests/e2e_fixtures/agent_trajectory/from_live_<trace_id>.json
```

---

## 9. Phase 7：会议记忆与主动建议

## 9.1 新增文件

```text
core/meeting_memory.py
core/project_memory.py
core/user_preferences.py
core/proactive_suggestions.py
tests/test_meeting_memory.py
tests/test_proactive_suggestions.py
```

## 9.2 数据表

```sql
CREATE TABLE assistant_memories (
  memory_id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  owner_key TEXT NOT NULL,
  content_json TEXT NOT NULL,
  source_trace_id TEXT NOT NULL DEFAULT '',
  source_workflow TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL DEFAULT 0
);
```

## 9.3 业务接入

```text
M3：读取项目历史决策、未关闭风险、上次会议遗留问题
M4：写入会议总结、决策、任务映射、开放问题
M5：读取 M4 映射和未关闭风险，生成解释性提醒
manual_qa：回答“上次说到哪里了”“这个项目还有什么风险”
```

## 9.4 主动建议模型

```python
@dataclass(slots=True)
class ProactiveSuggestion:
    """基于会议、任务和记忆生成的下一步建议。"""
    suggestion_id: str
    suggestion_type: str
    title: str
    reason: str
    evidence_refs: list[EvidenceRef]
    recommended_action: dict[str, Any]
    requires_confirmation: bool
    confidence: float
```

---

## 10. 更新测试命令文档

实现任一 Phase 后必须更新：

```text
docs/overall-test-commands.md
docs/current-version-test-commands.md
docs/llm-agent-evaluation-system-plan.md
tasks.md
```

新增命令组：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_eval_trace \
  tests.test_eval_metrics \
  tests.test_agent_eval_suite \
  tests.test_rag_eval_suite \
  tests.test_policy_safety_eval
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider settings \
  --judge-provider settings \
  --repeat 3 \
  --fail-under 0.80 \
  --write-report
```

---

## 11. 最小第一批代码改动

如果要马上开工，建议第一批只做下面这些，范围可控且能立刻提升评测能力：

```text
1. core/eval_trace.py
2. AgentRunResult.payload["agent_trace"]
3. tests/test_eval_trace.py
4. core/eval_metrics.py 中 tool_call_f1 / tool_order_score / policy_compliance
5. tests/test_eval_metrics.py
6. scripts/agent_eval_suite.py 支持 scripted_debug
7. tests/e2e_fixtures/agent_trajectory/ 三个 case
8. docs/overall-test-commands.md 增加 agent eval 命令
```

第一批验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_eval_trace \
  tests.test_eval_metrics \
  tests.test_agent_eval_suite
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

这样先让项目能“看到 Agent 做了什么、评估 Agent 做得对不对”，后续再补 M4 智能闭环和 LLM judge。

---

## 12. 风险与规避

### 12.1 Trace 泄露敏感信息

规避：

- trace 中保存参数 hash 和脱敏摘要，不保存完整 token、secret、URL query。
- 新增 `tests/test_redaction.py`。
- 质量门中 `secret_leakage_absent` 必须为 1.0。

### 12.2 LLM Judge 不稳定

规避：

- 关键安全指标使用代码 scorer。
- judge prompt 固定版本号。
- 支持 `--repeat` 和均值/方差。
- judge 输出必须结构化。

### 12.3 评测过度依赖 scripted_debug

规避：

- scripted_debug 作为 CI 稳定门。
- settings/deepseek 作为小样本真实 LLM 门。
- 真实飞书 trace 回流形成回放样本。

### 12.4 智能化改造破坏既有闭环

规避：

- 每个 Phase 保留原脚本兼容参数。
- 新能力通过开关启用。
- M3/M4/M5 真实联调命令必须继续存在。

---

## 13. 结论

这套代码改造的核心是先把 Agent 行为变成可追踪、可评分、可回归的对象，再逐步增强 M4 会后闭环、澄清恢复、会议记忆和主动建议。

只有先建立 `trace -> metrics -> report -> baseline -> quality gate`，后续智能化才不会变成主观描述；每次 prompt、模型、工具 schema 和 workflow 改动，都能用同一套工业化评测系统证明是否真的更像智能会议 Agent。
