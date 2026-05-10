# MeetFlow 冲刺分工边界

本文档用于明确两个人在后续冲刺中的职责边界，目标是让 AI/RAG/LLM 优化和高并发/高性能服务优化尽量解耦，减少合并冲突。

## 总体边界

项目按两层拆分：

```text
AI 能力层：理解会议内容、检索知识、调用模型、生成结构化结果
运行服务层：接收请求、排队、并发执行、重试、持久化状态、展示运行情况
```

两层之间只通过稳定契约交互，不互相深入修改内部实现。

推荐调用关系：

```text
Console / API / Worker
  -> AI Facade
    -> RAG Strategy
    -> LiteLLM / LLM Provider
    -> Tool Calling / Policy
```

## 角色 A：AI / RAG / LLM 负责人

这个角色负责“模型智能性”和“答案质量”。

### 负责目标

- RAG auto 策略：小语料 direct / manifest，大语料 Chroma + FTS5 + RRF。
- LiteLLM 接入：让 MeetFlow 可以通过 LiteLLM Proxy 调用模型。
- LLM fallback / retry / latency / token usage 的模型侧观测。
- Prompt、tool calling、evidence pack、reranker 策略。
- AI 相关评测 case。

### 可主要修改的文件

- `core/knowledge.py`
- `core/llm.py`
- `core/agent.py`
- `core/agent_loop.py`
- `core/tools.py`
- `core/evaluation.py`
- `core/eval_metrics.py`
- `scripts/agent_demo.py`
- `scripts/llm_provider_demo.py`
- `scripts/deepseek_llm_live_test.py`
- `scripts/rag_add_document_live.py`
- `scripts/knowledge_refresh_demo.py`
- `scripts/knowledge_tools_demo.py`
- `scripts/pre_meeting_retrieval_demo.py`
- `tests/test_knowledge_tools.py`
- `tests/test_pre_meeting_retrieval.py`
- `tests/test_agent_eval_suite.py`
- `tests/test_eval_metrics.py`

### 建议新增的文件

- `core/ai_facade.py`
- `core/ai_runtime/__init__.py`
- `core/ai_runtime/rag_strategy.py`
- `core/ai_runtime/litellm_gateway.py`
- `core/ai_runtime/llm_metrics.py`
- `config/litellm_config.example.yaml`
- `scripts/litellm_gateway_demo.py`
- `tests/test_ai_facade.py`
- `tests/test_rag_strategy.py`
- `tests/test_litellm_gateway_config.py`

### 不应主动修改的文件

除非提前沟通，否则不要改：

- `scripts/meetflow_console_server.py`
- `scripts/meetflow_worker.py`
- `core/console_api.py`
- `core/jobs.py`
- `core/service_manager.py`
- `frontend/src/api/*`
- `frontend/src/pages/JobsHealthPage.tsx`
- `frontend/src/pages/LiveFlowPage.tsx`

## 角色 B：高并发 / 高性能 / Runtime 负责人

这个角色负责“系统能稳定跑起来”。

### 负责目标

- Console API 不阻塞长任务。
- Job queue、worker、重试、死信、并发执行。
- SQLite WAL / busy_timeout / 锁等待优化。
- 服务健康检查、日志尾部、任务状态展示。
- 前端控制台运行态体验。
- 高并发压测脚本和性能指标。

### 可主要修改的文件

- `scripts/meetflow_console_server.py`
- `scripts/meetflow_worker.py`
- `scripts/meetflow_daemon.py`
- `core/console_api.py`
- `core/jobs.py`
- `core/service_manager.py`
- `core/storage.py`
- `core/migrations.py`
- `core/observability.py`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/pages/JobsHealthPage.tsx`
- `frontend/src/pages/LiveFlowPage.tsx`
- `frontend/src/components/ServiceControlPanel.tsx`
- `frontend/src/components/CommandResultPanel.tsx`
- `tests/test_console_api.py`
- `tests/test_jobs.py`
- `tests/test_observability.py`
- `tests/test_migrations.py`

### 建议新增的文件

- `core/runtime_service/__init__.py`
- `core/runtime_service/concurrency.py`
- `core/runtime_service/job_metrics.py`
- `scripts/runtime_load_test.py`
- `tests/test_worker_concurrency.py`
- `tests/test_runtime_service.py`

### 不应主动修改的文件

除非提前沟通，否则不要改：

- `core/knowledge.py`
- `core/llm.py`
- `core/agent.py`
- `core/agent_loop.py`
- `scripts/*rag*`
- `scripts/*knowledge*`
- `scripts/*llm*`

## 共享契约

共享契约是双方唯一需要共同维护的边界。建议新增：

- `core/contracts.py`
- `core/ai_facade.py`

### `core/contracts.py`

只放稳定数据结构，不放业务逻辑。任何字段变更必须双方确认。

建议包含：

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AIWorkflowInput:
    workflow_type: str
    payload: dict[str, Any]
    trace_id: str = ""
    allow_write: bool = False


@dataclass(slots=True)
class AIWorkflowResult:
    trace_id: str
    workflow_type: str
    status: str
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
```

### `core/ai_facade.py`

运行服务层只调用 facade，不直接调用 `core/knowledge.py` 或 `core/llm.py`。

建议暴露：

```python
def run_ai_workflow(input: AIWorkflowInput) -> AIWorkflowResult:
    ...


def run_pre_meeting_brief(input: AIWorkflowInput) -> AIWorkflowResult:
    ...


def run_post_meeting_summary(input: AIWorkflowInput) -> AIWorkflowResult:
    ...


def run_risk_scan_reasoning(input: AIWorkflowInput) -> AIWorkflowResult:
    ...
```

运行服务层只关心：

- `result.trace_id`
- `result.workflow_type`
- `result.status`
- `result.summary`
- `result.data`
- `result.metrics`
- `result.errors`

AI 层内部使用 RAG、LiteLLM、fallback、缓存、reranker，都不影响运行服务层。

## LiteLLM 归属

LiteLLM 网关层归 AI / RAG / LLM 负责人。

原因：

- LiteLLM 直接影响模型选择、fallback、token 成本和延迟。
- LiteLLM 配置会影响 prompt、tool calling 和模型兼容性。
- 它虽然叫 gateway，但不是普通 HTTP 网关，而是 LLM 工程层组件。

Runtime 负责人只需要知道：

- MeetFlow 调模型时调用 `core/ai_facade.py`。
- LiteLLM Proxy 是否可用可以从 health/metrics 里展示。
- 不直接操作 LiteLLM 配置和模型路由策略。

## LiteLLM 本地源码位置

LiteLLM 已拉取到：

```text
storage/third_party/litellm
```

该目录已通过 `.gitignore` 忽略，不会进入项目提交。

已重点阅读的源码路径：

- `README.md`
- `litellm/router.py`
- `litellm/proxy/proxy_server.py`
- `litellm/caching/caching.py`
- `litellm/caching/redis_semantic_cache.py`
- `litellm/proxy/example_config_yaml/load_balancer.yaml`

## LiteLLM 源码阅读结论

LiteLLM 对 MeetFlow 最有价值的能力是：

- 通过 Proxy 暴露 OpenAI-compatible `/v1/chat/completions`。
- 通过 `model_list` 把一个对外模型名映射到多个真实 provider/deployment。
- 通过 `router_settings` 配置 `routing_strategy`、`fallbacks`、`num_retries`、`timeout`、`allowed_fails`、`cooldown_time`。
- `Router` 内部会做部署选择、cooldown 过滤、health check 过滤、pre-call checks 和 fallback。
- `proxy_server.py` 会从配置文件读取 `model_list`、`general_settings`、`router_settings`，再初始化 `litellm.Router`。
- LiteLLM cache 支持 local、Redis、Redis semantic、Qdrant semantic、S3、GCS、disk。
- Redis semantic cache 使用 RedisVL 的 `SemanticCache`，`similarity_threshold` 越高越严格，并转换为 `distance_threshold = 1 - similarity_threshold`。

对 MeetFlow 的接入建议：

```text
MeetFlow core/llm.py
  -> OpenAI-compatible api_base
  -> LiteLLM Proxy
  -> DeepSeek / OpenAI / Azure / other provider
```

也就是说，业务代码仍然调用现有 `OpenAICompatibleProvider`，只把 `api_base` 指向 LiteLLM Proxy。

## 推荐 5 天拆工

### 第 1 天

AI 负责人：

- 新增 `core/contracts.py` 和 `core/ai_facade.py`。
- 定义 RAG auto strategy 的接口，不急着做完整实现。

Runtime 负责人：

- Worker/API 只调用 `core/ai_facade.py`，不再直接依赖 AI 内部模块。
- 检查 Console API 长任务是否可切到 enqueue 模式。

### 第 2 天

AI 负责人：

- 实现 RAG small-corpus direct / manifest / existing-rag 三段策略。
- 新增策略选择的 metrics，例如 `rag_strategy`、`document_count`、`estimated_tokens`。

Runtime 负责人：

- SQLite WAL / busy_timeout。
- Worker 并发参数和 job duration 指标。

### 第 3 天

AI 负责人：

- 新增 `config/litellm_config.example.yaml`。
- 文档化 LiteLLM Proxy 启动方式。
- 让 `core/llm.py` health/metrics 能显示当前 provider/base_url/model。

Runtime 负责人：

- Console 展示服务健康、job 状态、worker 并发数、错误摘要。

### 第 4 天

AI 负责人：

- 跑 M3/M4/M5 的 AI 评测和 RAG 策略回归。
- 固定模型配置和 fallback 策略。

Runtime 负责人：

- 跑本地压测脚本。
- 验证多任务并发不会破坏 job 状态。

### 第 5 天

双方：

- 冻结功能。
- 只修 bug、补文档、录演示。
- 默认集成分支保持随时可运行。

## 冲突处理规则

如果必须修改对方负责文件：

1. 先在群里说明要改什么文件、为什么必须改。
2. 优先开一个小 PR，只做接口或契约调整。
3. 不要在同一个 PR 里同时改 AI 内部和 runtime 内部。
4. 如果冲突发生在共享契约文件，以保持运行链路稳定为第一优先级。

## 最终目标

你负责让系统“更聪明”：

```text
RAG 策略、LiteLLM、模型调用、证据质量、评测得分
```

朋友负责让系统“跑得稳”：

```text
API、队列、worker、并发、状态、日志、健康检查
```

双方共享：

```text
contracts + ai_facade + README 中必要的启动说明
```

这样可以做到高度解耦，各自按自己的节奏推进，同时尽量减少文件冲突。
