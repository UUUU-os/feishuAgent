# MeetFlow 工业化代码修改方案

本文档基于 [industrialization-roadmap.md](/home/tanyd/ye/workhard/feishuAgent-main/docs/industrialization-roadmap.md)，把工业化路线图拆成可以直接接入当前代码框架的代码改造计划。

目标不是另起一套系统，而是在现有 M3/M4/M5 闭环上补齐长期运行能力：数据库可演进、事件可恢复、服务可部署、测试可回放、真实 LLM 可评估和可降级。

## 1. 接入原则

必须保留当前核心链路：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

新增的 daemon、callback、job worker、LLM fallback 都只能作为这条链路的入口或编排层，不能绕过 `ToolRegistry`、`AgentPolicy` 直接执行飞书写操作。

本轮改造坚持几个边界：

- 首期继续使用 SQLite，不引入 Redis/Celery，降低部署复杂度。
- 先做 migrations，再做 job queue；队列表本身也必须由 migration 管理。
- callback 和 daemon 主要负责快速入队；真正耗时的 M3/M4/M5/RAG 工作交给 worker。
- M4 卡片按钮里的“确认创建任务”暂时保留同步执行，因为用户需要即时反馈；后续如需异步化，再单独做确认任务 job。
- 当前所有 live test 和 demo 命令保持兼容，新能力通过 `--enqueue`、`--execute-agent`、`--dry-run` 等开关逐步切换。
- 本地密钥仍只存在 `config/settings.local.json`、`config/llm_providers.local.json` 或环境变量中，示例配置只写占位符。

## 2. 总体目标架构

改造后的运行形态：

```text
飞书 SDK WebSocket / HTTP fallback / daemon scan
  -> EventNormalizer
  -> JobQueue.enqueue()
  -> JobWorker
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / MeetFlowStorage
  -> Observability / Audit
```

三类长期进程：

```text
meetflow-callback  接收 SDK WebSocket / HTTP 回调，做验签、归一化和快速入队
meetflow-worker    消费 workflow_jobs，执行 M3/M4/M5/RAG 等业务任务
meetflow-daemon    周期扫描日历、妙记、知识库，补偿漏掉的事件并入队
```

建议先实现单机版本。只要 `workflow_jobs`、`schema_migrations`、`idempotency_keys` 和业务表稳定，后续再切 MySQL/PostgreSQL 或 Redis 队列时，业务层不需要大改。

## 3. Phase A：数据库 migrations

这是第一优先级。当前 `MeetFlowStorage.initialize()` 同时负责建表和补列，适合 MVP，但不适合长期演进。要先把 schema 演进变成可审计、可重复、可回滚分析的结构。

### 3.1 新增文件

```text
core/migrations.py
scripts/storage_migrate.py
tests/test_migrations.py
```

### 3.2 修改文件

```text
core/storage.py
core/__init__.py
config/settings.example.json
docs/current-version-test-commands.md
```

### 3.3 核心设计

`core/migrations.py` 新增：

```python
@dataclass(frozen=True)
class Migration:
    """描述一次数据库结构升级。"""

    version: int
    name: str
    statements: tuple[str, ...]
    checksum: str = ""


class MigrationRunner:
    """执行 MeetFlow SQLite schema 迁移。"""

    def apply_pending(self) -> list[Migration]: ...
    def status(self) -> dict[str, Any]: ...
    def verify(self) -> None: ...
```

辅助函数：

```text
ensure_schema_migrations_table(conn)
get_applied_versions(conn)
table_exists(conn, table_name)
column_exists(conn, table_name, column_name)
add_column_if_missing(conn, table_name, column_sql)
get_builtin_migrations()
```

### 3.4 首批 migration

```text
0001_initial_workflow_tables
  workflow_results
  idempotency_keys
  task_mappings 基础字段

0002_task_mappings_m4_fields
  minute_token
  title
  evidence_refs_json
  source_url
  review_session_id
  confirmation_status
  confirmed_at

0003_risk_notifications
  risk_notifications
  idx_risk_notifications_key_time

0004_workflow_jobs
  workflow_jobs
  idx_workflow_jobs_status_available
  idx_workflow_jobs_idempotency

0005_callback_review_session_fields
  card callback / pending review 相关兼容补列
```

实际字段以当前 `core/storage.py` 中已经使用的字段为准。migration 的职责是兼容旧库：如果表已存在，只补缺列；如果列已存在，不重复 `ALTER TABLE`。

### 3.5 `MeetFlowStorage.initialize()` 改造

改造为：

```text
ensure_directories()
MigrationRunner(settings.db_path).apply_pending()
MigrationRunner(settings.db_path).verify()
logger.info(...)
```

短期可以保留 `_ensure_task_mapping_columns()` 作为兼容兜底，但新增字段必须优先进入 migration。等测试稳定后，再把散落在 `initialize()` 里的建表逻辑收敛到 migrations。

### 3.6 迁移脚本

`scripts/storage_migrate.py`：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --status
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --apply
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
```

脚本要求：

- 只打印 migration 版本、名称、是否已应用、应用时间。
- 不打印任何 token、secret、URL query 里的敏感参数。
- `--verify` 失败时给出缺失表/缺失列名称。

### 3.7 测试

`tests/test_migrations.py`：

```text
test_new_database_applies_all_migrations
test_old_database_gets_missing_columns
test_migration_is_idempotent
test_verify_reports_missing_required_table
```

验证命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/migrations.py scripts/storage_migrate.py
```

## 4. Phase B：事件 / Job 队列

目标是让回调、daemon 扫描、手动脚本触发出来的业务任务都能持久化、重试、恢复和审计。

### 4.1 新增文件

```text
core/jobs.py
scripts/meetflow_worker.py
tests/test_jobs.py
tests/test_worker_dispatch.py
```

### 4.2 修改文件

```text
core/storage.py
core/observability.py
scripts/meetflow_daemon.py
scripts/feishu_event_sdk_server.py
scripts/feishu_event_server.py
scripts/risk_scan_demo.py
config/loader.py
config/settings.example.json
```

### 4.3 队列表

由 `0004_workflow_jobs` migration 创建：

```sql
CREATE TABLE workflow_jobs (
  job_id TEXT PRIMARY KEY,
  queue_name TEXT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  payload_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  available_at INTEGER NOT NULL,
  locked_by TEXT NOT NULL DEFAULT '',
  locked_until INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NOT NULL DEFAULT '',
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
```

状态约定：

```text
pending
running
retrying
succeeded
failed
dead_letter
cancelled
```

`retrying` 只是便于观测的中间状态，实际再次可消费时可以回到 `pending`，并通过 `available_at` 控制延迟。

### 4.4 `core/jobs.py`

核心类：

```python
@dataclass(slots=True)
class JobRecord:
    """一条可恢复执行的后台任务。"""

    job_id: str
    queue_name: str
    job_type: str
    status: str
    payload: dict[str, Any]
    idempotency_key: str
    attempts: int
    max_attempts: int
    available_at: int


class JobQueue:
    """基于 SQLite 的轻量任务队列。"""

    def enqueue(...): ...
    def claim_due_job(...): ...
    def mark_succeeded(...): ...
    def mark_retry(...): ...
    def mark_failed(...): ...
    def mark_dead_letter(...): ...
```

关键函数：

```text
build_job_id(job_type, idempotency_key, payload)
compute_retry_delay(attempts, base_seconds, max_seconds)
classify_job_error(error)
```

`claim_due_job()` 要用事务更新，避免同一 job 被两个 worker 同时领取。SQLite 单机版可以采用：

```text
BEGIN IMMEDIATE
SELECT pending job ORDER BY priority, available_at, created_at LIMIT 1
UPDATE status='running', locked_by=?, locked_until=?, attempts=attempts+1
COMMIT
```

### 4.5 Job 类型

首批支持：

```text
agent_input.run
  payload: {"agent_input": {...}, "llm_provider": "...", "max_iterations": 5}

pre_meeting.send_card
  payload: {"calendar_id": "...", "event_id": "...", "date_window": {...}, "chat_id": "..."}

post_meeting.send_cards
  payload: {"minute_url": "...", "chat_id": "...", "review_session_id": "..."}

risk_scan.run
  payload: {"backend": "feishu|local", "chat_id": "...", "allow_write": true}

rag_refresh.document
  payload: {"doc_token": "...", "resource_type": "...", "force_index": false}
```

这些 job 的执行逻辑尽量复用现有脚本里的业务函数。如果脚本目前只有 `main()`，先把可复用逻辑下沉为函数，例如：

```text
scripts/pre_meeting_live_test.py
  run_pre_meeting_live_test(args) -> WorkflowResult

scripts/post_meeting_live_test.py
  run_post_meeting_live_test(args) -> dict

scripts/risk_scan_demo.py
  run_risk_scan(args) -> dict
```

worker 只负责解析 payload、组装参数、调用这些函数，不复制业务逻辑。

### 4.6 `scripts/meetflow_worker.py`

命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

参数：

```text
--queues
--worker-id
--poll-seconds
--once
--dry-run
--max-jobs
--lock-seconds
--log-level
```

行为：

- `--dry-run` 只领取后打印将执行的 job，不做飞书写操作，也不标记 succeeded。
- `--once` 处理一轮后退出，适合健康检查和测试。
- 执行成功写 `result_json`，失败写 `last_error`，并通过 `core/observability.py` 写结构化事件。

### 4.7 重试分类

可重试：

```text
飞书 429
飞书 5xx
网络超时
LLM timeout
LLM 5xx
SQLite database locked
```

不可重试：

```text
飞书 400 参数错误
飞书权限不足
OAuth token 缺失且无法刷新
AgentPolicy blocked
payload 缺失必填字段
卡片 JSON 格式确定性错误
```

退避建议：

```text
attempt 1: 30s
attempt 2: 2m
attempt 3: 10m
attempt >= 4: dead_letter
```

### 4.8 观测事件

`core/observability.py` 增加标准事件名：

```text
job_enqueued
job_claimed
job_succeeded
job_retry_scheduled
job_failed
job_dead_letter
job_cancelled
```

字段：

```text
trace_id
job_id
queue_name
job_type
status
attempts
max_attempts
idempotency_key_hash
error_type
duration_ms
```

注意只记录幂等键哈希，不记录可能包含真实会议标题或 URL 的完整 payload。

### 4.9 测试

`tests/test_jobs.py`：

```text
test_enqueue_creates_pending_job
test_enqueue_same_idempotency_key_is_idempotent
test_claim_due_job_locks_job
test_mark_retry_sets_available_at
test_mark_failed_after_max_attempts_goes_dead_letter
```

`tests/test_worker_dispatch.py`：

```text
test_worker_dispatches_agent_input_job
test_worker_keeps_policy_block_as_non_retryable
test_worker_dry_run_does_not_execute_side_effect
```

验证命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_jobs tests.test_worker_dispatch
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
```

## 5. Phase C：callback / daemon 入队改造

这一阶段把现有实时入口和扫描入口接到 `JobQueue`，但保留直接执行开关，避免一次性切换带来回归风险。

### 5.1 SDK callback

修改 [scripts/feishu_event_sdk_server.py](/home/tanyd/ye/workhard/feishuAgent-main/scripts/feishu_event_sdk_server.py)：

新增参数：

```text
--enqueue-agent
--execute-agent
--job-queue workflow
--job-max-attempts 3
--job-priority 100
```

策略：

- 默认保持当前行为，便于现有测试继续跑。
- 开启 `--enqueue-agent` 后，耗时 Agent run 转为 `agent_input.run` job。
- M4 “确认创建”按钮仍走当前 `core/card_callback.py` / `core/confirmation_commands.py` 同步路径，因为它需要即时返回创建结果。
- 所有 SDK payload 继续先经过 `adapters/feishu_callback_payloads.py` 归一化，再进入 dispatcher 或入队。

### 5.2 HTTP fallback

修改 [scripts/feishu_event_server.py](/home/tanyd/ye/workhard/feishuAgent-main/scripts/feishu_event_server.py)：

- 参数和 SDK server 对齐。
- 保持验签、解密、challenge 响应现有逻辑。
- 同一飞书事件通过相同 `idempotency_key` 入队，避免 SDK 和 HTTP fallback 同时收到时重复执行。

### 5.3 daemon

修改 [scripts/meetflow_daemon.py](/home/tanyd/ye/workhard/feishuAgent-main/scripts/meetflow_daemon.py)：

新增参数：

```text
--enqueue
--job-queue workflow
--worker-queue workflow
--job-priority 100
```

现有触发函数改造：

```text
trigger_m3_due_events()
  当前：subprocess 调 card_send_live.py m3
  改造：--enqueue 时写 pre_meeting.send_card job；否则保留当前直接执行

trigger_m4_finished_events()
  当前：subprocess 调 card_send_live.py m4
  改造：--enqueue 时写 post_meeting.send_cards job；否则保留当前直接执行

enqueue_document_event_refresh()
  当前：直接 refresh
  改造：--enqueue 时写 rag_refresh.document job；否则保留当前直接执行
```

`DaemonState` 继续记录扫描水位，但业务执行状态以 `workflow_jobs` 为准。这样 daemon 重启后不会丢发现过但还没执行完的工作。

### 5.4 risk scan

修改 [scripts/risk_scan_demo.py](/home/tanyd/ye/workhard/feishuAgent-main/scripts/risk_scan_demo.py)：

新增：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --enqueue
```

开启后只写 `risk_scan.run` job；真正巡检由 worker 做。

## 6. Phase D：systemd / Docker 部署

### 6.1 systemd 文件

新增：

```text
deploy/systemd/meetflow-callback.service
deploy/systemd/meetflow-worker.service
deploy/systemd/meetflow-daemon.service
deploy/systemd/meetflow.env.example
```

`meetflow-callback.service`：

```ini
[Service]
WorkingDirectory=/home/tanyd/ye/workhard/feishuAgent-main
EnvironmentFile=/home/tanyd/ye/workhard/feishuAgent-main/deploy/systemd/meetflow.env
ExecStart=/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --enqueue-agent --log-level info
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
```

`meetflow-worker.service`：

```ini
[Service]
WorkingDirectory=/home/tanyd/ye/workhard/feishuAgent-main
EnvironmentFile=/home/tanyd/ye/workhard/feishuAgent-main/deploy/systemd/meetflow.env
ExecStart=/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --queues workflow,risk_scan,rag_refresh --poll-seconds 2
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
```

`meetflow-daemon.service`：

```ini
[Service]
WorkingDirectory=/home/tanyd/ye/workhard/feishuAgent-main
EnvironmentFile=/home/tanyd/ye/workhard/feishuAgent-main/deploy/systemd/meetflow.env
ExecStart=/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py --enable-m3 --enable-m4 --enable-rag --enqueue --poll-seconds 60
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
```

### 6.2 健康检查

新增：

```text
scripts/service_health_check.py
docs/deployment-guide.md
```

健康检查内容：

```text
配置能加载
日志目录和 storage 目录可写
MigrationRunner.verify() 通过
JobQueue 可以 enqueue dry-run job
worker --once --dry-run 能启动
lark-oapi SDK import 可选检查
飞书 token 只检查字段是否存在和过期时间，不打印 token
```

命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/service_health_check.py
```

### 6.3 Docker

新增：

```text
deploy/docker/Dockerfile
deploy/docker/docker-compose.yml
deploy/docker/entrypoint.sh
```

Docker 第一版只做单机三进程：

```text
callback
worker
daemon
```

挂载：

```text
./config/settings.local.json:/app/config/settings.local.json:ro
./config/llm_providers.local.json:/app/config/llm_providers.local.json:ro
./storage:/app/storage
```

注意：Docker 镜像内直接安装 `lark-oapi`，不要依赖宿主机 `.venv-lark-oapi`。

## 7. Phase E：E2E 回放数据集

目标是让 M3/M4/M5 闭环在无飞书网络、无真实 token 的情况下可以完整回归。

### 7.1 新增目录

```text
tests/e2e_fixtures/
  m3_pre_meeting_basic/
  m4_post_meeting_with_tasks/
  m4_post_meeting_no_ai_artifacts/
  m4_repeat_review_session/
  m5_risk_from_m4_mapping/
  callback_sdk_http_equivalence/
```

每个 case 至少包含：

```text
input.json
feishu_responses.json
expected.json
README.md
```

脱敏规范：

```text
open_id -> ou_test_xxx
chat_id -> oc_test_xxx
真实 URL -> https://example.feishu.cn/...
真实姓名 -> 张三 / 李四 / 王五
```

### 7.2 新增 runner

```text
scripts/e2e_replay.py
tests/test_e2e_replay.py
```

runner 逻辑：

```text
加载 fixture
创建临时 settings 和临时 SQLite
注入 FakeFeishuClient
使用 scripted_debug LLM
执行 workflow / dispatcher / risk scan
断言输出卡片、task_mappings、risk_notifications、workflow_results
```

建议新增测试辅助：

```text
tests/fakes.py
  FakeFeishuClient
  FakeLLMProvider
  FakeClock
```

### 7.3 必覆盖用例

```text
E2E-001 M3 会前卡片带按钮
E2E-002 M4 妙记有两个待办，生成两张待确认任务卡
E2E-003 M4 妙记无 AI 产物，不生成假待办
E2E-004 M4 同一妙记重复发卡，review_session_id 重置 pending
E2E-005 M4 确认创建写 task_mappings
E2E-006 M5 从 task_mappings 富化风险卡片来源
E2E-007 同一任务同一风险当天不重复提醒
E2E-008 SDK payload 与 HTTP payload 归一到同一 dispatcher 输出
```

命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay
```

## 8. Phase F：真实 LLM 评估与 fallback

当前 `scripted_debug` 保证链路稳定，真实 LLM 则要解决工具调用稳定性、输出格式、失败降级。

### 8.1 新增文件

```text
core/llm_eval.py
core/llm_fallback.py
scripts/llm_eval_suite.py
tests/test_llm_eval.py
```

### 8.2 `core/llm_eval.py`

核心结构：

```python
@dataclass(slots=True)
class LLMEvalCase:
    """一条可重复评估的 Agent/LLM 用例。"""

    case_id: str
    workflow_name: str
    prompt: str
    expected_tools: list[str]
    forbidden_tools: list[str]
    fixture_path: str


@dataclass(slots=True)
class LLMEvalResult:
    """真实 LLM 跑完一条用例后的评分结果。"""

    case_id: str
    provider: str
    model: str
    passed: bool
    score: float
    metrics: dict[str, Any]
    errors: list[str]
```

评分维度：

```text
tool_validity
policy_compliance
evidence_use
workflow_completion
fallback_used
latency_ms
error_type
```

### 8.3 `core/llm_fallback.py`

核心结构：

```python
class FallbackLLMProvider:
    """按 provider 顺序调用真实模型，失败时降级到备用 provider。"""

    def complete(self, request): ...


class ProviderChain:
    """从配置创建 primary + fallbacks 的 provider 链。"""
```

短期接入方式：

- 先在 `scripts/llm_eval_suite.py` 和 live test 脚本中显式使用 provider chain。
- 等评估稳定后，再把 `provider-chain` 接入 `core/llm.py:create_llm_provider()`。

### 8.4 业务降级策略

```text
M3:
  真实 LLM 失败时，使用确定性 PreMeetingBriefArtifacts + scripted_debug 发送保守卡片。

M4:
  真实 LLM 失败时，使用规则抽取待办和总结；只发待确认卡，不自动创建任务。

M5:
  风险识别继续走确定性规则；LLM 只做解释增强，失败时使用模板解释。
```

### 8.5 命令

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py \
  --provider scripted_debug \
  --cases tests/e2e_fixtures \
  --write-report

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py \
  --provider deepseek \
  --cases tests/e2e_fixtures \
  --max-cases 5 \
  --write-report
```

## 9. 配置改造

### 9.1 `config/loader.py`

新增 dataclass：

```python
@dataclass(slots=True)
class JobSettings:
    """后台任务队列配置。"""

    enabled: bool
    default_queue: str
    worker_id: str
    lock_seconds: int
    max_attempts: int
    retry_base_seconds: int
    retry_max_seconds: int
    dead_letter_after_attempts: int
```

可选新增：

```python
@dataclass(slots=True)
class LLMFallbackSettings:
    """真实 LLM 降级链配置。"""

    enabled: bool
    primary: str
    fallbacks: list[str]
    max_provider_retries: int
    fallback_on: list[str]
```

`Settings` 增加：

```text
jobs: JobSettings
llm_fallback: LLMFallbackSettings
```

### 9.2 `config/settings.example.json`

新增：

```json
{
  "jobs": {
    "enabled": false,
    "default_queue": "workflow",
    "worker_id": "meetflow-local-worker",
    "lock_seconds": 300,
    "max_attempts": 3,
    "retry_base_seconds": 30,
    "retry_max_seconds": 600,
    "dead_letter_after_attempts": 4
  },
  "llm_fallback": {
    "enabled": false,
    "primary": "deepseek",
    "fallbacks": ["scripted_debug"],
    "max_provider_retries": 1,
    "fallback_on": ["timeout", "rate_limit", "server_error", "tool_schema_error"]
  }
}
```

环境变量映射：

```text
MEETFLOW_JOBS_ENABLED
MEETFLOW_JOBS_DEFAULT_QUEUE
MEETFLOW_JOBS_WORKER_ID
MEETFLOW_JOBS_LOCK_SECONDS
MEETFLOW_JOBS_MAX_ATTEMPTS
MEETFLOW_LLM_FALLBACK_ENABLED
MEETFLOW_LLM_FALLBACK_PRIMARY
MEETFLOW_LLM_FALLBACK_FALLBACKS
```

### 9.3 测试

如当前没有配置测试，新增：

```text
tests/test_config_loader.py
```

覆盖：

```text
test_default_jobs_settings_loaded
test_env_overrides_jobs_enabled
test_llm_fallback_list_env_parsed
```

## 10. 兼容策略

为了不打断现在已经跑通的真实飞书链路，迁移方式要渐进：

```text
第 1 步：migrations 接入 storage.initialize()，但业务行为不变。
第 2 步：JobQueue 和 worker 完成单测，daemon/callback 仍直接执行。
第 3 步：daemon 增加 --enqueue，默认仍直接执行。
第 4 步：callback 增加 --enqueue-agent，默认仍保持当前行为。
第 5 步：systemd 使用 --enqueue-agent + worker，开发命令仍可直接执行。
第 6 步：E2E replay 覆盖后，再考虑把生产推荐路径改为默认入队。
```

关键风险和处理：

```text
重复执行:
  使用 workflow_jobs.idempotency_key + storage.idempotency_keys + AgentPolicy 三层保护。

worker 崩溃:
  locked_until 过期后其他 worker 可重新领取。

SQLite 锁:
  claim job 使用短事务；失败按 retryable 错误退避。

M4 确认按钮重复点击:
  继续使用 review_session_id + confirmation_status + task_mappings 幂等。

真实 LLM 不稳定:
  scripted_debug 和确定性业务 fallback 保底。

SDK/HTTP 双入口重复:
  EventNormalizer 生成同一 idempotency_key。
```

## 11. 推荐施工顺序

```text
P0-1 core/migrations.py + scripts/storage_migrate.py
P0-2 workflow_jobs migration + core/jobs.py
P0-3 scripts/meetflow_worker.py
P0-4 meetflow_daemon.py --enqueue
P0-5 feishu_event_sdk_server.py / feishu_event_server.py --enqueue-agent
P1-1 deploy/systemd + service_health_check.py
P1-2 tests/e2e_fixtures + scripts/e2e_replay.py
P1-3 core/llm_eval.py + scripts/llm_eval_suite.py
P1-4 core/llm_fallback.py
P2-1 deploy/docker
```

每个 P0 小步都要保持现有 66 条单测可通过，并补充对应新单测。

## 12. 每阶段验收命令

基础编译：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py scripts/*.py config/*.py
```

migrations：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --status
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --apply
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations
```

job queue：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_jobs tests.test_worker_dispatch
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
```

callback / daemon 入队：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py --enable-m3 --enable-m4 --enable-rag --enqueue --once --dry-run
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --dry-run --enqueue-agent --log-level debug
```

E2E 回放：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay
```

LLM 评估：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py --provider scripted_debug --cases tests/e2e_fixtures --write-report
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py --provider deepseek --cases tests/e2e_fixtures --max-cases 5 --write-report
```

服务健康检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/service_health_check.py
```

## 13. 交付标准

完成这套改造后，MeetFlow 应达到：

- 任何数据库升级都有版本记录，旧库可自动补齐缺失结构。
- 飞书事件、daemon 扫描、手动触发都能入队，失败后可重试、可死信、可排查。
- worker 崩溃或服务重启后，不丢未完成任务。
- systemd 能长期拉起 callback、worker、daemon，健康检查能说明问题。
- M3/M4/M5 闭环可以用脱敏 fixture 在本地回放。
- 真实 LLM 的工具调用质量有评分报告，失败时有业务保底路径。
- 所有写操作仍经过 `ToolRegistry` 和 `AgentPolicy`，不会因为工业化改造绕过安全边界。
