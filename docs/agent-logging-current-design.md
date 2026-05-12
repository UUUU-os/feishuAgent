# MeetFlow 当前日志设计说明

本文档说明当前 MeetFlow 日志系统的实现状态，以及它和改造前普通日志的核心区别。

## 1. 当前日志分为两类

当前项目同时保留两类日志：

- 普通运行日志：面向开发者阅读，输出到终端，用于快速判断程序跑到哪里。
- 结构化事件日志：面向排查、审计、统计和后续部署监控，输出到 `storage/workflow_events.jsonl`。

普通运行日志仍然由现有 `logging` 体系负责，例如：

```text
[INFO] [trace_id=xxx] [meetflow.agent] MeetFlowAgent 开始执行 event_type=meeting.soon
```

结构化事件日志由 `core/observability.py` 负责，每一行都是一个 JSON 事件，例如：

```json
{"event_type":"tool_call","trace_id":"d32249fd0a5c","tool_name":"calendar.list_events","status":"failed","duration_ms":0}
```

## 2. 和旧日志的核心区别

改造前日志主要回答：

- 当前程序跑到哪一步了
- 哪个模块打印了什么信息
- 异常的大致原因是什么

改造后新增的结构化日志可以回答：

- 一次 Agent 执行从触发到结束经历了哪些事件
- WorkflowRouter 做出了什么路由判断
- LLM 请求了哪些工具，参数是否完整
- AgentPolicy 为什么允许或拦截工具调用
- ToolRegistry 实际调用了哪个内部工具，成功还是失败
- 飞书 API 请求的接口、状态码、飞书错误码和 request_id 是什么
- 一次执行耗时多久、跑了几轮、产生了哪些副作用

因此，旧日志更像“运行文字记录”，新日志更像“Agent 执行轨迹”。

## 3. 当前结构化事件链路

一次典型 Agent 执行会产生如下事件：

```text
workflow_started
route_decision
agent_loop_iteration_started
llm_generation
policy_decision
tool_call
agent_loop_iteration_finished
workflow_finished
```

如果执行失败，会额外记录：

```text
workflow_failed
```

如果调用飞书 API，会记录：

```text
external_api_call
```

## 4. 关键事件说明

### workflow_started

表示一次 Agent 工作流开始执行。

主要字段：

- `trace_id`：本次执行追踪 ID
- `workflow_type`：业务流程类型
- `source`：触发来源
- `event_type_input`：输入事件类型
- `allow_write`：是否允许写操作
- `idempotency_key`：幂等键
- `metadata`：会议、日历、任务等轻量上下文字段

### route_decision

表示 `WorkflowRouter` 的路由结果。

主要字段：

- `workflow_type`
- `status`
- `confidence`
- `reason`
- `required_tools`

### llm_generation

表示一次 LLM 调用结果。

主要字段：

- `provider`
- `model`
- `status`
- `finish_reason`
- `duration_ms`
- `usage`
- `tool_calls_requested`

如果 LLM 请求工具调用，`tool_calls_requested` 会记录工具名和参数 key，但默认不记录完整敏感参数。

### policy_decision

表示 `AgentPolicy` 对工具调用的安全判断。

主要字段：

- `tool_name`
- `side_effect`
- `allow_write`
- `status`
- `reason`
- `required_fields`
- `idempotency_key`

这个事件用于解释为什么某个工具被允许、拦截，或者要求用户补充确认。

### tool_call

表示 `ToolRegistry` 执行了一次工具调用。

主要字段：

- `call_id`
- `tool_name`
- `llm_tool_name`
- `read_only`
- `side_effect`
- `status`
- `duration_ms`
- `argument_keys`
- `result_summary`
- `error_type`
- `error_message`

工具成功时会记录结果摘要；工具失败时会记录错误类型和脱敏后的错误信息。

### external_api_call

表示一次外部 API 调用，目前主要用于飞书。

主要字段：

- `service`
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

这个事件用于排查飞书权限、参数、token、限流和业务错误。

## 5. 敏感信息保护

结构化日志默认不会记录完整敏感信息。

当前会重点处理：

- `api_key`
- `app_secret`
- `access_token`
- `refresh_token`
- `authorization`
- `open_id`
- `union_id`
- `user_id`
- `chat_id`
- `tenant_key`

默认策略包括：

- 敏感 key 的值会被掩码处理
- 较长文本会被截断
- URL 会归一化为模板，避免把具体资源 ID 散落到日志里
- 工具参数默认只记录 key，不记录完整值

相关配置见 `config/settings.example.json` 中的 `observability` 段。

## 6. 配置项

示例配置：

```json
"observability": {
  "structured_events_enabled": true,
  "structured_event_path": "storage/workflow_events.jsonl",
  "record_sensitive_payload": false,
  "max_event_chars": 16000,
  "max_field_chars": 1000,
  "mask_ids": true,
  "daily_rotate": false
}
```

常用环境变量：

- `MEETFLOW_OBSERVABILITY_STRUCTURED_EVENTS_ENABLED`
- `MEETFLOW_OBSERVABILITY_EVENT_PATH`
- `MEETFLOW_OBSERVABILITY_RECORD_SENSITIVE_PAYLOAD`
- `MEETFLOW_OBSERVABILITY_MAX_EVENT_CHARS`
- `MEETFLOW_OBSERVABILITY_MAX_FIELD_CHARS`
- `MEETFLOW_OBSERVABILITY_MASK_IDS`
- `MEETFLOW_OBSERVABILITY_DAILY_ROTATE`

本地默认输出路径：

```text
storage/workflow_events.jsonl
```

该文件属于运行数据，不应提交到 Git。

## 7. 当前实现涉及的核心文件

- `core/observability.py`：结构化事件写入、脱敏、截断、摘要工具。
- `core/agent.py`：记录 workflow 启动、路由、完成、失败。
- `core/agent_loop.py`：记录 Agent Loop 轮次、Policy 决策、最大轮次等事件。
- `core/llm.py`：记录 LLM 调用、耗时、finish_reason、工具调用请求。
- `core/tools.py`：记录工具调用成功、失败和结果摘要。
- `adapters/feishu_client.py`：记录飞书 API 调用状态、错误码、request_id。
- `config/loader.py`：加载 observability 配置。
- `config/settings.example.json`：提供 observability 配置模板。
- `tests/test_observability.py`：验证脱敏、截断、摘要和 JSONL 写入。

## 8. 验证方法

### 8.1 编译检查

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  config/loader.py \
  config/__init__.py \
  core/observability.py \
  core/__init__.py \
  core/agent.py \
  core/agent_loop.py \
  core/llm.py \
  core/tools.py \
  adapters/feishu_client.py \
  scripts/agent_demo.py \
  tests/test_observability.py
```

### 8.2 单元测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_observability
```

或者：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests -p 'test_*.py'
```

### 8.3 本地 Agent 链路测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py \
  --event-type meeting.soon \
  --backend local \
  --llm-provider dry-run \
  --max-iterations 2
```

查看结构化日志：

```bash
tail -n 30 storage/workflow_events.jsonl
```

验证 JSONL 是否可解析：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -c "import json,pathlib; p=pathlib.Path('storage/workflow_events.jsonl'); rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]; print(len(rows)); print(rows[-1]['event_type'])"
```

### 8.4 飞书真实读链路测试

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py \
  --event-type meeting.soon \
  --backend feishu \
  --llm-provider scripted_debug \
  --max-iterations 3
```

然后查看是否出现：

```json
{"event_type":"external_api_call", "...":"..."}
```

## 9. 当前边界

- 当前结构化日志先落本地 JSONL，还没有接入 OpenTelemetry、Loki、ELK 或云日志平台。
- `scripted_debug` 主要用于固定脚本测试，不一定产生真实 `llm_generation` 事件。
- `dry-run` 会故意构造不完整工具参数，用来验证失败链路，不代表真实 LLM 调用失败。
- 默认不记录完整工具参数和 API payload；如需临时排查，需要谨慎打开 `record_sensitive_payload`，并确保不提交日志文件。

## 10. 后续可改进方向

- 增加按天轮转和日志清理策略。
- 增加命令行脚本，按 `trace_id` 聚合一次完整执行链路。
- 接入 OpenTelemetry trace/span 模型。
- 为飞书 API 增加更细粒度的接口名映射。
- 增加 Agent 评估指标，例如工具成功率、Policy 拦截率、平均迭代轮数。
