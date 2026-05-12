# MeetFlow 日志与观测改造实施方案

本文档基于 [Agent 日志与观测参考输出](agent-logging-reference.md)，给出适合当前 MeetFlow 代码库的分阶段改造方案。

目标是把当前“可调试日志”升级为“可复盘、可审计、可扩展到 OpenTelemetry 的 Agent 观测体系”，同时保持项目轻量，不一次性引入复杂基础设施。

## 1. 当前状态判断

当前代码已有较好的日志基础：

- `core/logging.py` 已实现 `trace_id` 上下文注入。
- `core/audit.py` 已有 `AuditLogger` 和 `WorkflowRunRecorder`。
- `core/agent.py` 会在 `MeetFlowAgent.run()` 中绑定 `trace_id`。
- `core/agent_loop.py` 会记录每轮 Agent Loop。
- `core/tools.py` 会记录工具开始执行和失败。
- `adapters/feishu_client.py` 会记录飞书请求 method、url 和 retry attempt。

主要缺口：

- `WorkflowRunRecorder` 尚未接入主 Agent 流程。
- 缺少统一结构化事件模型。
- 工具、LLM、飞书 API 调用缺少统一 `duration_ms`。
- 成功路径日志不够完整，失败路径错误信息未统一脱敏和截断。
- 日志和审计事件没有稳定 schema，后续难以做统计和回放。

## 2. 改造目标

### P0 目标

完成后应具备：

- 每次 Agent 运行都有 `workflow_started` / `workflow_finished` / `workflow_failed` JSONL 记录。
- 每次 LLM 调用都有 `llm_generation` JSONL 记录。
- 每次工具调用都有 `tool_call` JSONL 记录。
- 每次写操作策略判断都有 `policy_decision` JSONL 记录。
- 每次飞书 HTTP 请求都有 `external_api_call` JSONL 记录。
- 所有结构化事件都带 `trace_id`、`workflow_type`、`timestamp`、`status`。
- 默认不记录完整 prompt、token、secret、文档正文、模型完整输出。

### P1 目标

完成后应具备：

- 支持按配置开启 DEBUG 级脱敏 payload 摘要。
- 支持对错误信息、工具结果和模型输出做统一截断。
- 支持以 `group_id` 关联同一会议、同一妙记、同一任务的多次运行。
- 支持本地 JSONL 审计文件按天切分。

### P2 目标

后续服务化部署时考虑：

- 增加 OpenTelemetry span 导出。
- 对接 LangSmith / Phoenix / Cloud Trace / OTLP collector。
- 增加 metrics：成功率、耗时分布、工具失败率、LLM token 使用量、写操作拦截率。

## 3. 推荐目录与文件变更

### 新增文件

```text
core/observability.py
tests/test_observability.py
docs/agent-logging-implementation-plan.md
```

### 修改文件

```text
config/loader.py
config/settings.example.json
core/__init__.py
core/agent.py
core/agent_loop.py
core/llm.py
core/tools.py
core/policy.py
adapters/feishu_client.py
docs/tasks/m2_8-agent-runtime.md
docs/tasks/m3-pre-meeting.md
```

## 4. 新增 Observability 配置

在 `config/settings.example.json` 中新增：

```json
{
  "observability": {
    "structured_events_enabled": true,
    "structured_event_path": "storage/workflow_events.jsonl",
    "record_sensitive_payload": false,
    "max_event_chars": 16000,
    "max_field_chars": 1000,
    "mask_ids": true,
    "daily_rotate": false
  }
}
```

在 `config/loader.py` 中新增：

```python
@dataclass(slots=True)
class ObservabilitySettings:
    structured_events_enabled: bool
    structured_event_path: str
    record_sensitive_payload: bool
    max_event_chars: int
    max_field_chars: int
    mask_ids: bool
    daily_rotate: bool
```

并把 `Settings` 扩展为：

```python
observability: ObservabilitySettings
```

同时加入环境变量覆盖：

```text
MEETFLOW_OBSERVABILITY_STRUCTURED_EVENTS_ENABLED
MEETFLOW_OBSERVABILITY_EVENT_PATH
MEETFLOW_OBSERVABILITY_RECORD_SENSITIVE_PAYLOAD
MEETFLOW_OBSERVABILITY_MAX_EVENT_CHARS
MEETFLOW_OBSERVABILITY_MAX_FIELD_CHARS
MEETFLOW_OBSERVABILITY_MASK_IDS
MEETFLOW_OBSERVABILITY_DAILY_ROTATE
```

## 5. `core/observability.py` 设计

### 5.1 核心职责

`core/observability.py` 负责：

- 生成结构化事件。
- 写入 JSONL。
- 统一时间戳格式。
- 统一脱敏和截断。
- 统一记录 duration。
- 提供轻量 span 上下文工具。

### 5.2 建议核心类

```python
@dataclass(slots=True)
class StructuredEventWriter:
    settings: ObservabilitySettings

    def emit(self, event_type: str, **fields: Any) -> None:
        ...
```

```python
@dataclass(slots=True)
class SpanTimer:
    event_writer: StructuredEventWriter
    event_type: str
    fields: dict[str, Any]

    def __enter__(self) -> "SpanTimer":
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        ...
```

### 5.3 建议核心函数

```python
def utc_now_iso() -> str:
    ...

def truncate_value(value: Any, max_chars: int) -> Any:
    ...

def mask_secret(value: str) -> str:
    ...

def mask_id(value: str, prefix_chars: int = 6, suffix_chars: int = 4) -> str:
    ...

def safe_error_message(error: Exception, max_chars: int = 1000) -> str:
    ...

def summarize_tool_result(data: dict[str, Any]) -> dict[str, Any]:
    ...

def summarize_arguments(arguments: dict[str, Any], record_sensitive_payload: bool) -> dict[str, Any]:
    ...
```

### 5.4 事件写入策略

建议所有结构化事件写入：

```text
storage/workflow_events.jsonl
```

保留 `storage/workflow_runs.jsonl` 给旧版 `WorkflowRunRecorder` 或逐步迁移。

写入失败时：

- 不应中断业务主流程。
- 应在普通 logger 中打一条 warning。
- 避免审计系统故障导致 Agent 不可用。

## 6. 主链路接入方案

### 6.1 `MeetFlowAgent.run()`

目标：记录工作流生命周期。

修改点：`core/agent.py`

建议在 `run()` 开始时写：

```json
{
  "event_type": "workflow_started",
  "trace_id": "...",
  "workflow_type": "...",
  "source": "...",
  "event_type_input": "...",
  "allow_write": false,
  "idempotency_key": "...",
  "metadata": {
    "project_id": "...",
    "meeting_id": "...",
    "calendar_event_id": "..."
  }
}
```

正常返回前写：

```json
{
  "event_type": "workflow_finished",
  "trace_id": "...",
  "workflow_type": "...",
  "status": "success",
  "duration_ms": 3318,
  "iterations": 2,
  "tool_call_count": 3,
  "side_effects": []
}
```

异常兜底时写：

```json
{
  "event_type": "workflow_failed",
  "trace_id": "...",
  "workflow_type": "agent_error",
  "error_type": "...",
  "error_message": "...",
  "retryable": false
}
```

### 6.2 `WorkflowRouter.route()`

目标：记录路由决策。

修改点：`core/agent.py` 中 router 调用后即可记录，避免让 Router 依赖观测模块。

建议事件：

```json
{
  "event_type": "route_decision",
  "trace_id": "...",
  "workflow_type": "pre_meeting_brief",
  "status": "ready",
  "confidence": 1.0,
  "required_tools": ["calendar.list_events"],
  "idempotency_key": "..."
}
```

### 6.3 `MeetFlowAgentLoop.run()`

目标：记录每轮 Agent Loop。

修改点：`core/agent_loop.py`

建议增加：

- `agent_loop_iteration_started`
- `agent_loop_iteration_finished`
- `agent_loop_max_iterations`

示例：

```json
{
  "event_type": "agent_loop_iteration_finished",
  "trace_id": "...",
  "workflow_type": "pre_meeting_brief",
  "iteration": 1,
  "status": "tool_calls",
  "tool_call_count": 1,
  "duration_ms": 1432
}
```

## 7. LLM 调用接入方案

### 修改点

```text
core/llm.py
```

### 目标

在 `OpenAICompatibleProvider.chat()` 中记录：

- provider
- model
- endpoint host/path
- duration_ms
- finish_reason
- tool_calls_requested
- usage
- status
- error_type / error_message

### 成功事件

```json
{
  "event_type": "llm_generation",
  "trace_id": "...",
  "workflow_type": "pre_meeting_brief",
  "provider": "openai-compatible",
  "model": "ep-20260423222531-dnqtj",
  "status": "success",
  "finish_reason": "tool_calls",
  "duration_ms": 1210,
  "usage": {
    "prompt_tokens": 1830,
    "completion_tokens": 120,
    "total_tokens": 1950
  },
  "tool_calls_requested": [
    {
      "call_id": "call_001",
      "tool_name": "knowledge_search",
      "argument_keys": ["query", "top_k"]
    }
  ],
  "sensitive_payload_recorded": false
}
```

### 失败事件

```json
{
  "event_type": "llm_generation",
  "trace_id": "...",
  "provider": "openai-compatible",
  "model": "ep-20260423222531-dnqtj",
  "status": "failed",
  "http_status": 401,
  "error_type": "LLMAPIError",
  "error_message": "LLM authentication failed.",
  "duration_ms": 381,
  "retryable": false
}
```

### 注意

- 默认不记录 messages。
- 默认不记录完整 tool arguments。
- 对 endpoint 只记录 path，不记录完整 key 或敏感 query。

## 8. 工具调用接入方案

### 修改点

```text
core/tools.py
```

### 目标

在 `ToolRegistry.execute()` 中记录 `tool_call` 事件。

成功时：

```json
{
  "event_type": "tool_call",
  "trace_id": "...",
  "call_id": "call_001",
  "tool_name": "knowledge.search",
  "llm_tool_name": "knowledge_search",
  "read_only": true,
  "side_effect": "none",
  "status": "success",
  "duration_ms": 328,
  "argument_keys": ["query", "meeting_id", "project_id", "top_k"],
  "result_summary": {
    "count": 3,
    "omitted_count": 2
  }
}
```

失败时：

```json
{
  "event_type": "tool_call",
  "trace_id": "...",
  "call_id": "call_001",
  "tool_name": "docs.fetch_resource",
  "status": "failed",
  "duration_ms": 247,
  "error_type": "FeishuAPIError",
  "error_message": "飞书接口业务错误 code=4000002 ..."
}
```

### 注意

- tool result 的完整内容仍保存在 `AgentToolResult.data`，结构化日志只保存摘要。
- 写工具必须记录 `side_effect`。

## 9. Policy 接入方案

### 修改点

```text
core/agent_loop.py
core/policy.py
```

建议不要让 `AgentPolicy` 直接依赖 writer；由 `MeetFlowAgentLoop._handle_tool_calls()` 在拿到 `PolicyDecision` 后写事件。

事件示例：

```json
{
  "event_type": "policy_decision",
  "trace_id": "...",
  "workflow_type": "post_meeting_followup",
  "tool_name": "tasks.create_task",
  "side_effect": "create_task",
  "allow_write": true,
  "status": "needs_confirmation",
  "reason": "任务缺少负责人或截止时间，进入待确认。",
  "required_fields": ["assignee_ids", "due_timestamp_ms"],
  "idempotency_key": "..."
}
```

## 10. 飞书 API 接入方案

### 修改点

```text
adapters/feishu_client.py
```

### 目标

在 `_request()` 中记录 `external_api_call` 事件。

建议字段：

- `service=feishu`
- `api`
- `method`
- `url_template`
- `identity`
- `status`
- `http_status`
- `feishu_code`
- `request_id`
- `retry_attempt`
- `duration_ms`
- `retryable`

### URL 处理

不要直接写完整 URL 到结构化事件。

建议新增：

```python
def normalize_feishu_api_path(url_or_path: str) -> str:
    ...
```

把：

```text
https://open.feishu.cn/open-apis/calendar/v4/calendars/xxx/events/instance_view
```

转成：

```text
/calendar/v4/calendars/{calendar_id}/events/instance_view
```

### 成功事件

```json
{
  "event_type": "external_api_call",
  "trace_id": "...",
  "service": "feishu",
  "api": "calendar.instance_view",
  "method": "GET",
  "url_template": "/calendar/v4/calendars/{calendar_id}/events/instance_view",
  "identity": "user",
  "status": "success",
  "http_status": 200,
  "feishu_code": 0,
  "request_id": "req_xxx_masked",
  "retry_attempt": 1,
  "duration_ms": 247
}
```

## 11. 错误脱敏与截断策略

### 必须脱敏

- `access_token`
- `refresh_token`
- `app_secret`
- `api_key`
- `Authorization`
- `Bearer ...`
- 飞书 open_id / user_id，默认保留前后少量字符或 hash
- 文档 token、妙记 token，默认 mask

### 必须截断

- LLM 原始响应 body
- prompt
- tool result content
- 文档正文
- 飞书错误 response text

### 建议默认值

```text
max_field_chars = 1000
max_event_chars = 16000
```

## 12. 测试方案

### 单元测试

新增 `tests/test_observability.py`：

- `mask_secret()` 不泄露完整 key。
- `truncate_value()` 能递归截断字符串。
- `summarize_arguments()` 默认只返回 keys。
- `summarize_tool_result()` 对 `count/items/hits/omitted_count` 提取摘要。
- `StructuredEventWriter.emit()` 能写入 JSONL。

### 集成测试

建议命令：

```bash
python3 -m py_compile core/*.py adapters/*.py scripts/*.py
python3 scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 3
python3 scripts/agent_policy_demo.py --scenario missing_task_fields
```

验证：

- `storage/workflow_events.jsonl` 生成。
- 文件内至少包含 workflow、route、llm、tool、policy 事件。
- 无完整 token、secret、API key。

### 真实飞书回归

```bash
python3 scripts/calendar_live_test.py --identity user --calendar-id primary
python3 scripts/agent_demo.py --event-type meeting.soon --backend feishu --llm-provider settings --max-iterations 3
```

验证：

- 结构化事件中有 `external_api_call`。
- 飞书 API 失败时有 `http_status`、`feishu_code`、`safe_detail`。
- 不泄露 `Authorization`。

## 13. 实施顺序

### Step 1：基础事件写入器

文件：

- `core/observability.py`
- `config/loader.py`
- `config/settings.example.json`
- `core/__init__.py`

完成：

- 配置加载。
- JSONL writer。
- 脱敏、截断、摘要函数。
- 基础测试。

### Step 2：接入 Agent 生命周期

文件：

- `core/agent.py`

完成：

- workflow started / finished / failed。
- route decision。
- duration_ms。

### Step 3：接入 LLM 与工具

文件：

- `core/llm.py`
- `core/tools.py`
- `core/agent_loop.py`

完成：

- llm_generation。
- tool_call。
- policy_decision。
- agent_loop_iteration。

### Step 4：接入飞书 API

文件：

- `adapters/feishu_client.py`

完成：

- external_api_call。
- url_template。
- request_id / feishu code。
- retry attempt。

### Step 5：文档与任务记录

文件：

- `docs/tasks/m2_8-agent-runtime.md`
- `docs/tasks/m3-pre-meeting.md`
- `tasks.md`

完成：

- 记录新增文件、核心类函数、验证命令和结果。

## 14. 风险与取舍

### 风险 1：日志过大

原因：

- Agent Loop、工具结果、文档内容容易很长。

控制：

- 默认不记录 payload。
- 强制 `max_field_chars` 和 `max_event_chars`。
- 只记录摘要和引用。

### 风险 2：泄露密钥或业务数据

原因：

- LLM 错误 body、飞书 URL、工具参数可能包含敏感字段。

控制：

- 所有结构化事件统一走 `sanitize_event()`。
- DEBUG 才允许记录脱敏 payload。
- 文档 token、open_id 默认 mask。

### 风险 3：观测代码侵入主流程

原因：

- 每个模块都直接写 JSONL 会造成耦合。

控制：

- 使用轻量全局 writer 或注入 writer。
- writer 失败只 warning，不影响业务。
- 保持观测模块无飞书、无 LLM 依赖。

### 风险 4：过早引入 OpenTelemetry

原因：

- 当前项目仍以脚本和本地 Demo 为主。

控制：

- P0 只做 JSONL。
- OTel 留到服务化部署后再接。

## 15. 完成后的预期效果

完成 P0 后，一次会前 Agent 运行应能回答：

- 这次工作流从哪里触发？
- 路由到了哪个 workflow？
- 暴露了哪些工具？
- LLM 调用了几次？
- 调用了哪些工具？
- 每个工具耗时多久，成功还是失败？
- 飞书 API 请求成功还是失败？
- 写操作有没有被 Policy 拦截？
- 最终成功、跳过、失败还是达到最大轮数？
- 如果失败，下一步应该检查什么？

这会让 MeetFlow 从“能跑通”进入“能复盘”的阶段。
