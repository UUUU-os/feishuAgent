# MeetFlow 工业化落地方案

本文档面向当前 `meetflow-m3-m4-m5-closed-loop-20260505` 版本，目标是把已经跑通的
M3/M4/M5 真实飞书闭环，从“可演示、可联调的准生产 MVP”推进到“可长期运行、可恢复、可观测、可治理”的工程化项目。

核心原则：

- 不推翻现有主链路，继续保持 `AgentInput -> WorkflowRouter -> WorkflowContextBuilder -> MeetFlowAgentLoop -> ToolRegistry -> AgentPolicy -> FeishuClient / Storage`。
- 新增能力优先挂在 `core/`、`scripts/`、`config/`、`tests/` 现有边界上。
- 外部副作用仍必须经过 `ToolRegistry` 和 `AgentPolicy`。
- 事件、队列、迁移和评估都要能 dry-run、可回放、可审计。

## 1. 当前基础

当前已经具备：

- `scripts/feishu_event_sdk_server.py`：飞书官方 SDK WebSocket 长连接，处理卡片按钮回调。
- `scripts/feishu_event_server.py`：公网 HTTPS fallback。
- `scripts/meetflow_daemon.py`：扫描式后台入口，可触发 M3、M4、RAG 刷新。
- `core/storage.py`：SQLite 表初始化、workflow results、idempotency、task mappings、risk notifications。
- `core/observability.py`：结构化事件日志。
- `core/agent.py` / `core/agent_loop.py`：统一 Agent 运行时。
- `core/llm.py`：OpenAI-compatible 和 dry-run provider。
- `scripts/*_live_test.py`、`tests/`：真实联调脚本和 66 条单测。

当前主要短板：

- daemon 还不是标准服务，没有 systemd/docker 健康检查、日志轮转和重启策略。
- 事件处理更多是即时执行或扫描触发，缺少持久 job queue、失败重试和死信记录。
- SQLite schema 通过 `CREATE TABLE IF NOT EXISTS` 和补列演进，缺少 schema version 和 migrations。
- 端到端测试依赖真实飞书环境，缺少脱敏回放数据集。
- 真实 LLM 的工具调用稳定性还没有系统评估和 fallback 策略。

## 2. 目标架构

推荐最终运行形态：

```text
飞书 SDK WebSocket / HTTP fallback / daemon scan
  -> EventNormalizer
  -> JobQueue.enqueue()
  -> JobWorker
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgent
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
  -> Observability / Audit
```

进程建议拆成三类：

```text
meetflow-callback     负责 SDK/HTTP 回调快速入队
meetflow-worker       消费 job queue，执行 M3/M4/M5/RAG
meetflow-daemon       周期扫描兜底，发现缺失事件并入队
```

首期可以先保持单机 SQLite，不急着引入 Redis / Celery。关键是先把“事件可持久化、失败可重试、执行可恢复”做出来。

## 3. systemd / Docker 部署

### 3.1 systemd 方案

新增目录：

```text
deploy/systemd/
  meetflow-callback.service
  meetflow-daemon.service
  meetflow-worker.service
  meetflow.env.example
```

`meetflow-callback.service` 运行：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python \
  /home/tanyd/ye/workhard/feishuAgent-main/scripts/feishu_event_sdk_server.py \
  --log-level info
```

`meetflow-daemon.service` 运行：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python \
  /home/tanyd/ye/workhard/feishuAgent-main/scripts/meetflow_daemon.py \
  --enable-m3 --enable-m4 --enable-rag \
  --poll-seconds 60 \
  --m3-minutes-before 30 \
  --m4-delay-minutes 5
```

后续新增 `scripts/meetflow_worker.py` 后，`meetflow-worker.service` 运行：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python \
  /home/tanyd/ye/workhard/feishuAgent-main/scripts/meetflow_worker.py \
  --queues feishu_event,workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

服务配置要点：

```ini
WorkingDirectory=/home/tanyd/ye/workhard/feishuAgent-main
EnvironmentFile=/home/tanyd/ye/workhard/feishuAgent-main/deploy/systemd/meetflow.env
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
```

健康检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py --once --dry-run
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
```

### 3.2 Docker 方案

新增：

```text
deploy/docker/
  Dockerfile
  docker-compose.yml
  entrypoint.sh
```

首版 compose 服务：

```yaml
services:
  callback:
    command: python scripts/feishu_event_sdk_server.py --log-level info
  worker:
    command: python scripts/meetflow_worker.py --queues feishu_event,workflow,risk_scan,rag_refresh
  daemon:
    command: python scripts/meetflow_daemon.py --enable-m3 --enable-m4 --enable-rag
```

卷挂载：

```text
./config/settings.local.json:/app/config/settings.local.json:ro
./storage:/app/storage
```

注意：

- SDK 依赖 `lark-oapi`，目前放在 `.venv-lark-oapi`。Docker 中建议直接纳入镜像依赖，不使用本地 venv。
- 本地 conda 环境只适合开发；Docker 镜像要有固定 Python 版本和依赖锁定文件。

## 4. 事件 / Job 队列与失败重试

### 4.1 新增表

通过 migrations 新增：

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

CREATE INDEX idx_workflow_jobs_status_available
ON workflow_jobs(status, available_at, priority);

CREATE INDEX idx_workflow_jobs_idempotency
ON workflow_jobs(idempotency_key);
```

状态约定：

```text
pending -> running -> succeeded
pending -> running -> retrying -> pending
pending/running -> failed
failed -> dead_letter
cancelled
```

### 4.2 新增模块

```text
core/jobs.py
  JobRecord
  JobQueue
  JobWorker
  build_job_id()
  compute_retry_delay()
```

`JobQueue` 挂在 `MeetFlowStorage` 上或独立持有 storage settings：

```python
queue = JobQueue(settings.storage)
queue.enqueue(
    queue_name="workflow",
    job_type="pre_meeting_brief",
    payload={"agent_input": agent_input.to_dict()},
    idempotency_key="m3:calendar_event_id:20260505",
)
```

`JobWorker` 执行：

```text
claim_due_job()
  -> dispatch_job()
  -> create_meetflow_agent()
  -> agent.run()
  -> mark_succeeded / mark_retry / mark_failed
```

### 4.3 现有入口改造

`scripts/feishu_event_sdk_server.py`：

- 当前：收到按钮后直接 dispatcher，必要时后台线程跑 Agent。
- 改造后：
  - 卡片回调仍快速响应；
  - M4 确认创建这种必须立即反馈的操作可以继续同步执行；
  - M3 refresh、RAG refresh、复杂 Agent run 入 `workflow_jobs`。

`scripts/meetflow_daemon.py`：

- 当前：扫描到事件后直接 `subprocess.call(card_send_live.py)`。
- 改造后：
  - 扫描只负责发现机会和入队；
  - 真正发卡由 `meetflow_worker.py` 执行；
  - `DaemonState` 保留为扫描水位，但不再承担业务执行状态。

`scripts/risk_scan_demo.py`：

- 增加可选：

```bash
scripts/risk_scan_demo.py --backend feishu --enqueue
```

### 4.4 重试策略

按错误类型分层：

```text
飞书 429 / 5xx / 网络超时：可重试，指数退避
飞书 400 / 权限不足：不可重试，failed
LLM timeout / 5xx：可重试
AgentPolicy blocked：不可重试，succeeded_with_policy_block 或 failed_policy
卡片格式 rejected：先 fallback，再记录 warning，不直接失败
```

建议退避：

```text
attempt 1: 30s
attempt 2: 2m
attempt 3: 10m
attempt >=4: dead_letter
```

## 5. schema_version / migrations

### 5.1 目标

把 `MeetFlowStorage.initialize()` 从“同时建表和演进 schema”改成：

```text
ensure_base_directory()
MigrationRunner.apply_pending()
verify_schema()
```

### 5.2 新增表

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at INTEGER NOT NULL
);
```

### 5.3 新增模块

```text
core/migrations.py
  Migration
  MigrationRunner
  get_builtin_migrations()
```

首批 migration：

```text
0001_initial_workflow_tables
0002_task_mappings_m4_fields
0003_risk_notifications
0004_workflow_jobs
0005_callback_review_session_fields
```

因为当前项目已经有 `CREATE TABLE IF NOT EXISTS`，迁移实现要兼容旧库：

- 如果表已存在，只补缺列。
- 所有 `ALTER TABLE ADD COLUMN` 都先 `PRAGMA table_info` 检查。
- migration 成功后写入 `schema_migrations`。

### 5.4 命令

新增：

```bash
scripts/storage_migrate.py --status
scripts/storage_migrate.py --apply
scripts/storage_migrate.py --verify
```

测试：

```text
tests/test_migrations.py
  test_new_database_applies_all_migrations
  test_old_database_gets_missing_columns
  test_migration_is_idempotent
```

## 6. E2E 回放测试数据集

### 6.1 目录

```text
tests/e2e_fixtures/
  m3_pre_meeting_basic/
    agent_input.json
    calendar_event.json
    resources.json
    expected.json
  m4_post_meeting_with_tasks/
    minute_resource.json
    expected_action_items.json
    expected_cards.json
  m4_post_meeting_no_ai_artifacts/
    minute_resource.json
    expected.json
  m5_risk_from_m4_mapping/
    task_list_result.json
    task_mappings.json
    expected_risk_card.json
```

所有数据必须脱敏：

```text
open_id -> ou_test_xxx
chat_id -> oc_test_xxx
真实 URL -> https://example.feishu.cn/...
真实姓名 -> 张三 / 李四 / 王五
```

### 6.2 新增回放 runner

```text
scripts/e2e_replay.py
```

命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --case m4_post_meeting_with_tasks
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all
```

runner 逻辑：

```text
加载 fixture
构造 Settings + 临时 SQLite
使用 FakeFeishuClient / ScriptedDebugProvider
执行对应 workflow 或纯函数
断言：
  - action_items 数量
  - pending card 是否含按钮
  - task_mappings 是否写入
  - risk card 是否展示 M4 来源
```

### 6.3 必备用例

```text
E2E-001 M3 会前卡片带按钮
E2E-002 M4 妙记有两个待办，生成两张待确认任务卡
E2E-003 M4 妙记无 AI 产物，不生成假待办
E2E-004 M4 同一妙记重复发卡，review_session_id 重置 pending
E2E-005 M4 确认创建写 task_mappings
E2E-006 M5 从 task_mappings 富化风险卡片来源
E2E-007 风险降噪：同一任务同一风险当天不重复提醒
E2E-008 SDK payload 与 HTTP payload 归一到同一 dispatcher
```

## 7. 真实 LLM 稳定性评估与 fallback

### 7.1 当前问题

当前 `scripted_debug` 很稳，但真实 LLM 可能出现：

- 工具名选错。
- 缺少必填参数。
- 在 M4 主链路尝试直接创建任务。
- 工具返回结构化数据后回答不引用详情。
- 卡片 JSON 被模型自由拼坏。

### 7.2 新增 LLM 评估模块

```text
core/llm_eval.py
  LLMEvalCase
  LLMEvalResult
  evaluate_agent_run()
  score_tool_sequence()
```

```text
scripts/llm_eval_suite.py
```

命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py \
  --provider deepseek \
  --cases tests/e2e_fixtures \
  --max-cases 20 \
  --write-report
```

### 7.3 评分维度

```text
tool_validity: 工具名是否存在，参数是否通过 schema
policy_compliance: 是否绕过或触发不该触发的写操作
evidence_use: 是否调用 knowledge.search / fetch_chunk 并引用证据
workflow_completion: 是否完成目标产物
fallback_used: 是否触发 fallback
latency_ms: 延迟
cost_estimate: 估算 token 成本
```

### 7.4 fallback 策略

新增：

```text
core/llm_fallback.py
  FallbackLLMProvider
  ProviderChain
  RetryableLLMError
```

配置建议：

```json
{
  "llm": {
    "provider": "provider-chain",
    "primary": "deepseek",
    "fallbacks": ["settings", "dry-run"],
    "max_provider_retries": 1,
    "fallback_on": ["timeout", "rate_limit", "server_error", "tool_schema_error"]
  }
}
```

短期不必改 `LLMSettings` 过大，可以先通过 `scripts/meetflow_agent_live_test.py` 和 `scripts/pre_meeting_live_test.py` 的 `--llm-provider` 做显式 provider 选择；等评估稳定后再把 provider-chain 接进 `create_llm_provider()`。

### 7.5 业务 fallback

LLM 不可靠时，不应该让业务失败：

```text
M3：如果真实 LLM 失败，使用确定性 PreMeetingBriefArtifacts + scripted_debug 发送保守卡片
M4：如果真实 LLM 失败，使用规则抽取 + 待确认卡，不自动创建任务
M5：风险规则本身确定性，不依赖 LLM；LLM 只做解释增强
```

## 8. 分阶段施工计划

### Phase 1：可部署

目标：可以被 systemd/docker 拉起，服务重启不丢状态。

文件：

```text
deploy/systemd/*.service
deploy/docker/*
scripts/service_health_check.py
docs/deployment-guide.md
```

验收：

```bash
systemctl --user start meetflow-callback
systemctl --user start meetflow-daemon
systemctl --user status meetflow-callback
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/service_health_check.py
```

### Phase 2：可恢复

目标：事件入队、失败重试、死信可查。

文件：

```text
core/jobs.py
scripts/meetflow_worker.py
tests/test_jobs.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_jobs
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
sqlite3 storage/meetflow.sqlite "SELECT job_type,status,attempts,last_error FROM workflow_jobs ORDER BY created_at DESC LIMIT 20;"
```

### Phase 3：可演进

目标：数据库 schema 可版本化升级。

文件：

```text
core/migrations.py
scripts/storage_migrate.py
tests/test_migrations.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --status
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --apply
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations
```

### Phase 4：可回放

目标：脱敏 E2E 数据集覆盖 M3/M4/M5 闭环。

文件：

```text
tests/e2e_fixtures/**
scripts/e2e_replay.py
tests/test_e2e_replay.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay
```

### Phase 5：可评估

目标：真实 LLM 接入有量化结果和 fallback。

文件：

```text
core/llm_eval.py
core/llm_fallback.py
scripts/llm_eval_suite.py
tests/test_llm_eval.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py --provider scripted_debug --cases tests/e2e_fixtures --write-report
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/llm_eval_suite.py --provider deepseek --cases tests/e2e_fixtures --max-cases 5 --write-report
```

## 9. 推荐优先级

推荐施工顺序：

```text
P0-1 migrations：先让数据库演进有秩序
P0-2 job queue：让 M3/M4/M5 事件可恢复
P0-3 worker：替换 daemon 的直接 subprocess 执行
P1-1 systemd：让服务能长期运行
P1-2 e2e replay：让闭环回归不依赖真实飞书
P1-3 llm eval：让真实模型可度量
P2 docker：最后做镜像化部署
```

原因：

- 先做 migrations，可以降低后续表结构改造风险。
- 再做 job queue，能解决长期运行中最致命的“事件丢失和失败不可恢复”。
- systemd/docker 是运行外壳，应建立在 worker/job 稳定之后。
- e2e 和 LLM eval 是质量体系，可以和 job/migration 并行推进。

## 10. 与现有代码的衔接点

| 新能力 | 现有衔接点 | 说明 |
| --- | --- | --- |
| systemd callback | `scripts/feishu_event_sdk_server.py` | 直接作为服务入口 |
| systemd daemon | `scripts/meetflow_daemon.py` | 先不改行为，后续改为入队 |
| worker | `core.agent.create_meetflow_agent()` | 消费 job 后构造 AgentInput 运行 |
| job queue | `core/storage.py` | 先用 SQLite 表实现 |
| migrations | `MeetFlowStorage.initialize()` | initialize 调用 MigrationRunner |
| e2e replay | `scripts/*_demo.py`、`tests/*` | 复用 fake client 和 scripted provider |
| LLM eval | `core/llm.py`、`scripts/meetflow_agent_live_test.py` | 复用 provider 装配与 AgentRunResult |

## 11. 成功标准

达到工业化第一阶段时，应满足：

```text
1. 服务器重启后 callback / daemon / worker 自动恢复
2. 飞书事件入队后即使执行失败，也能在 workflow_jobs 中看到失败原因
3. 同一事件不会重复产生副作用，除非明确开启新的 review_session
4. 数据库迁移可重复执行，不破坏旧数据
5. 不依赖真实飞书也能回放 M3/M4/M5 闭环
6. 真实 LLM 评估报告能说明成功率、失败类型和 fallback 使用率
7. 所有写操作仍经过 AgentPolicy
```

