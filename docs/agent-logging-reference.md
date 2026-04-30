# Agent 日志与观测参考输出

本文档参考 OpenAI Agents SDK、Microsoft AutoGen、LangChain/LangGraph + LangSmith、Google ADK 等开源或公开 Agent 框架的观测设计，整理 MeetFlow 后续日志与审计输出可以采用的形态。

目标不是照搬某个框架，而是把这些项目共通的成熟做法转成 MeetFlow 可落地的日志规范。

## 1. 参考项目的共同结论

这些项目虽然实现不同，但在 Agent 日志上有明显共识：

- 一次用户请求或一次工作流运行应有一个全局 `trace_id`。
- 一次工作流内部应拆成多个 span/run，例如 agent run、LLM generation、tool call、policy check、external API call。
- 普通日志给人看，结构化事件给系统消费；两者不要混成一种文本。
- 工具调用、模型调用、外部 API 调用都要记录开始、结束、耗时、状态和错误。
- DEBUG 级日志可能包含 prompt、工具参数、模型输出等敏感内容，生产默认不应开启。
- 日志应支持脱敏、截断、采样和关联到业务上下文。

## 2. 参考来源

### OpenAI Agents SDK

OpenAI Agents SDK 使用 trace/span 模型。一次 `run()` 会形成一个 trace，内部包含 agent span、LLM generation span、function tool span、guardrail span、handoff span 等。

对 MeetFlow 的启发：

- `MeetFlowAgent.run()` 应生成 workflow 级 trace。
- 每次 LLM 调用应是 `generation` span。
- 每次工具调用应是 `function_tool` span。
- Policy 判断可作为自定义 span。
- 对敏感数据提供开关，例如是否记录 prompt、tool input/output。

参考：

- https://openai.github.io/openai-agents-python/tracing/
- https://openai.github.io/openai-agents-js/guides/tracing/

### Microsoft AutoGen

AutoGen 明确区分两类日志：

- trace logging：面向开发者的人类可读调试日志。
- structured logging：面向系统消费的结构化事件日志。

它还支持 OpenTelemetry，将 runtime、tool、agent 调用映射为可导出的 span。

对 MeetFlow 的启发：

- `meetflow.trace` 用于文本调试日志。
- `meetflow.event` 用于 JSONL / 后续日志平台消费。
- 工具、Agent、Runtime 应用不同事件类型，而不是只写自然语言字符串。

参考：

- https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/logging.html
- https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/logging.html
- https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/telemetry.html

### LangChain / LangGraph + LangSmith

LangSmith 以 project、trace、run 组织数据。一个 trace 表示一次完整请求，trace 内每个步骤是 run；可附加 tags、metadata，用于过滤、评估和监控。

对 MeetFlow 的启发：

- 每次工作流运行应记录 `project_id`、`workflow_type`、`environment`、`app_version` 等 metadata。
- 多轮会话或同一会议多次运行可用 `group_id` / `thread_id` 关联。
- 对文档、任务、会议等业务对象应记录稳定 ID，而不是只记录自然语言标题。
- 应支持匿名化或脱敏规则，避免 trace 中泄露 token、手机号、邮箱等。

参考：

- https://docs.langchain.com/oss/python/langgraph/observability
- https://docs.langchain.com/oss/python/langchain/observability
- https://docs.langchain.com/langsmith/observability-concepts

### Google ADK

Google ADK 使用标准 logging，也支持 OpenTelemetry 兼容 traces。它强调 agent run、tool call、model request、runner execution 都应被自动记录，并能导出到本地文件、控制台或云端 trace 系统。

对 MeetFlow 的启发：

- stdout 日志负责本地阅读，JSONL / OTel span 负责后续分析。
- 本地开发可导出到文件，部署后再接 OTLP / Cloud Trace / 其他观测平台。
- 日志级别要分清：INFO 记录生命周期，DEBUG 才记录 prompt 和详细响应。

参考：

- https://google.github.io/adk-docs/observability/logging/
- https://google.github.io/adk-docs/observability/monocle/
- https://adk.dev/observability/traces/

## 3. MeetFlow 建议日志分层

### 3.1 Console Trace Log

面向开发者，适合本地联调时阅读。

示例：

```text
[2026-04-30 20:30:12,104] [INFO] [trace_id=trace_01HMF] [meetflow.agent] workflow=pre_meeting_brief stage=started event_type=meeting.soon source=pre_meeting_scheduler allow_write=false
[2026-04-30 20:30:12,118] [INFO] [trace_id=trace_01HMF] [meetflow.router] route_decision workflow=pre_meeting_brief confidence=1.00 required_tools=7 idempotency_key=pre_meeting_brief:evt_123
[2026-04-30 20:30:12,146] [INFO] [trace_id=trace_01HMF] [meetflow.agent_loop] iteration=1 workflow=pre_meeting_brief tools_available=calendar.list_events,knowledge.search,docs.fetch_resource
[2026-04-30 20:30:13,802] [INFO] [trace_id=trace_01HMF] [meetflow.tool] tool=knowledge.search call_id=call_001 status=success duration_ms=328 result_count=3
[2026-04-30 20:30:15,422] [INFO] [trace_id=trace_01HMF] [meetflow.agent] workflow=pre_meeting_brief stage=finished status=success duration_ms=3318 side_effects=0
```

特点：

- 保持短句，适合人眼扫读。
- 不输出完整 token、secret、access token、refresh token、API key。
- 默认不输出完整 prompt、完整文档正文、完整模型输出。

### 3.2 Structured Event JSONL

面向系统消费，建议写入 `storage/workflow_runs.jsonl` 或后续日志平台。

每一行是一个完整 JSON 对象。

#### workflow_started

```json
{
  "event_type": "workflow_started",
  "trace_id": "trace_01HMF",
  "workflow_type": "pre_meeting_brief",
  "group_id": "meeting:evt_123",
  "timestamp": "2026-04-30T20:30:12.104+08:00",
  "source": "pre_meeting_scheduler",
  "actor": "ou_xxx_masked",
  "allow_write": false,
  "idempotency_key": "pre_meeting_brief:evt_123",
  "metadata": {
    "project_id": "meetflow",
    "calendar_event_id": "evt_123",
    "meeting_id": "meeting_123",
    "environment": "dev"
  }
}
```

#### route_decision

```json
{
  "event_type": "route_decision",
  "trace_id": "trace_01HMF",
  "workflow_type": "pre_meeting_brief",
  "timestamp": "2026-04-30T20:30:12.118+08:00",
  "status": "ready",
  "confidence": 1.0,
  "reason": "会议即将开始，需要读取日历、关联文档和任务，生成会前背景卡。",
  "required_tools": [
    "calendar.list_events",
    "knowledge.search",
    "knowledge.fetch_chunk",
    "docs.fetch_resource",
    "minutes.fetch_resource",
    "tasks.list_my_tasks",
    "im.send_card"
  ]
}
```

#### llm_generation

```json
{
  "event_type": "llm_generation",
  "trace_id": "trace_01HMF",
  "span_id": "span_llm_001",
  "parent_span_id": "span_agent_loop_001",
  "workflow_type": "pre_meeting_brief",
  "iteration": 1,
  "timestamp": "2026-04-30T20:30:12.146+08:00",
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
  "sensitive_payload_recorded": false,
  "tool_calls_requested": [
    {
      "call_id": "call_001",
      "tool_name": "knowledge_search",
      "argument_keys": ["query", "meeting_id", "project_id", "top_k"]
    }
  ]
}
```

注意：

- 默认只记录参数 key，不记录完整参数值。
- 如需排查，可在本地 DEBUG 模式开启脱敏后的参数摘要。

#### tool_call

```json
{
  "event_type": "tool_call",
  "trace_id": "trace_01HMF",
  "span_id": "span_tool_001",
  "parent_span_id": "span_agent_loop_001",
  "workflow_type": "pre_meeting_brief",
  "timestamp": "2026-04-30T20:30:13.474+08:00",
  "call_id": "call_001",
  "tool_name": "knowledge.search",
  "llm_tool_name": "knowledge_search",
  "read_only": true,
  "side_effect": "none",
  "status": "success",
  "duration_ms": 328,
  "result_summary": {
    "count": 3,
    "omitted_count": 2,
    "low_confidence": false
  },
  "evidence_refs": [
    {
      "ref_id": "ref_1",
      "source_type": "doc",
      "document_id": "doc_xxx_masked",
      "source_url_present": true
    }
  ]
}
```

#### policy_decision

```json
{
  "event_type": "policy_decision",
  "trace_id": "trace_01HMF",
  "span_id": "span_policy_001",
  "parent_span_id": "span_tool_002",
  "workflow_type": "post_meeting_followup",
  "timestamp": "2026-04-30T21:12:01.216+08:00",
  "tool_name": "tasks.create_task",
  "side_effect": "create_task",
  "allow_write": true,
  "status": "needs_confirmation",
  "reason": "任务缺少负责人或截止时间，进入待确认。",
  "required_fields": ["assignee_ids", "due_timestamp_ms"],
  "idempotency_key": "post_meeting_followup:min_123:create_task:20260430"
}
```

#### external_api_call

```json
{
  "event_type": "external_api_call",
  "trace_id": "trace_01HMF",
  "span_id": "span_api_001",
  "parent_span_id": "span_tool_003",
  "service": "feishu",
  "api": "calendar.instance_view",
  "method": "GET",
  "url_template": "/calendar/v4/calendars/{calendar_id}/events/instance_view",
  "identity": "user",
  "status": "success",
  "http_status": 200,
  "feishu_code": 0,
  "duration_ms": 247,
  "request_id": "req_xxx_masked",
  "retry_attempt": 1
}
```

注意：

- 记录 `url_template`，不要记录完整带 token 或敏感 ID 的 URL。
- 如果必须记录业务 ID，使用短 hash 或 mask。

#### workflow_finished

```json
{
  "event_type": "workflow_finished",
  "trace_id": "trace_01HMF",
  "workflow_type": "pre_meeting_brief",
  "group_id": "meeting:evt_123",
  "timestamp": "2026-04-30T20:30:15.422+08:00",
  "status": "success",
  "duration_ms": 3318,
  "iterations": 2,
  "tool_call_count": 3,
  "llm_call_count": 2,
  "side_effects": [],
  "summary": "已生成会前背景卡草案，包含 3 条证据来源。",
  "output_refs": {
    "workflow_result_trace_id": "trace_01HMF"
  }
}
```

#### workflow_failed

```json
{
  "event_type": "workflow_failed",
  "trace_id": "trace_01HMF",
  "workflow_type": "pre_meeting_brief",
  "timestamp": "2026-04-30T20:30:15.422+08:00",
  "status": "failed",
  "duration_ms": 3318,
  "error_type": "LLMAPIError",
  "error_code": "authentication_error",
  "error_message": "LLM authentication failed.",
  "safe_detail": "provider=openai-compatible http_status=401 endpoint=/chat/completions",
  "retryable": false,
  "next_action": "检查 MEETFLOW_LLM_API_KEY 或 llm provider 配置。"
}
```

## 4. MeetFlow 推荐字段集

### 每条事件都应包含

- `event_type`
- `trace_id`
- `workflow_type`
- `timestamp`
- `status`
- `duration_ms`，如果事件有开始和结束

### Agent 工作流事件建议包含

- `group_id`：例如 `meeting:{calendar_event_id}` 或 `minute:{minute_token}`
- `source`
- `actor`
- `project_id`
- `idempotency_key`
- `allow_write`
- `effective_required_tools`

### LLM 事件建议包含

- `provider`
- `model`
- `iteration`
- `finish_reason`
- `duration_ms`
- `usage`
- `tool_calls_requested`
- `sensitive_payload_recorded`

### 工具事件建议包含

- `call_id`
- `tool_name`
- `llm_tool_name`
- `read_only`
- `side_effect`
- `argument_keys`
- `status`
- `duration_ms`
- `result_summary`
- `error_type`
- `error_message`

### 飞书 API 事件建议包含

- `service=feishu`
- `api`
- `method`
- `url_template`
- `identity`
- `http_status`
- `feishu_code`
- `request_id` 或 `log_id`
- `retry_attempt`
- `duration_ms`

## 5. 日志级别建议

### INFO

记录：

- workflow started / finished / skipped
- route decision
- agent loop iteration
- tool call success / failed
- external API call success / failed
- policy allow / blocked / needs_confirmation

不记录：

- 完整 prompt
- 完整文档正文
- 完整 token
- 完整 access token / refresh token / API key

### DEBUG

仅本地排障开启，可记录：

- 脱敏后的 LLM messages 摘要
- 脱敏后的 tool arguments
- 截断后的 tool result content
- 飞书响应结构摘要

必须限制：

- 单字段最大长度，例如 1000 字符
- 单事件最大长度，例如 16KB
- 明确标记 `sensitive_payload_recorded=true`

### WARNING

记录：

- 可恢复错误
- 重试
- 低置信检索
- FTS / 向量索引降级
- Policy 拦截写操作

### ERROR

记录：

- LLM 调用失败
- 飞书 API 不可恢复失败
- 工具执行异常
- workflow failed

## 6. MeetFlow 当前日志与参考差距

当前已有能力：

- `core/logging.py` 已有 `trace_id` 注入。
- `core/audit.py` 已有 JSONL 审计雏形。
- `MeetFlowAgent`、`MeetFlowAgentLoop`、`ToolRegistry`、`FeishuClient` 都有基础日志。
- 飞书请求会记录 method、url、attempt。

主要差距：

- `WorkflowRunRecorder` 尚未接入 `MeetFlowAgent.run()` 主链路。
- `ToolRegistry.execute()` 成功时缺少 `duration_ms` 和结果摘要日志。
- `LLMProvider.chat()` 缺少独立的 generation 事件和 token usage 审计。
- `FeishuClient._request()` 缺少成功耗时、url_template、request_id/log_id 的结构化记录。
- 错误信息需要统一脱敏和截断，避免把 provider 原始 body 直接进入用户可见结果。
- 现在日志更多是自然语言字符串，结构化事件还不足。

## 7. 建议实施顺序

1. 在 `MeetFlowAgent.run()` 接入 workflow started / finished / failed JSONL 审计。
2. 在 `ToolRegistry.execute()` 增加 tool_call JSONL 事件，记录耗时、状态、结果摘要。
3. 在 `OpenAICompatibleProvider.chat()` 增加 llm_generation JSONL 事件，记录模型、耗时、finish_reason、usage。
4. 在 `FeishuClient._request()` 增加 external_api_call JSONL 事件，记录 api、身份、HTTP 状态、飞书 code、耗时。
5. 新增统一脱敏函数，例如 `mask_secret()`、`mask_open_id()`、`truncate_text()`。
6. 将 `config/settings.example.json` 增加观测配置，例如：

```json
{
  "observability": {
    "structured_events_enabled": true,
    "record_sensitive_payload": false,
    "max_event_chars": 16000,
    "max_field_chars": 1000
  }
}
```

## 8. 推荐最终形态

MeetFlow 最适合采用三层观测：

```text
stdout human logs
  -> 本地开发和脚本联调

storage/workflow_runs.jsonl structured events
  -> 本地复盘、比赛答辩、失败归因

OpenTelemetry-compatible spans
  -> 后续服务化部署、接入云端观测平台
```

这样既不会过早引入复杂基础设施，也能把 Agent 的关键行为完整保留下来。
