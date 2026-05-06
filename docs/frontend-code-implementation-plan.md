# MeetFlow Console 代码实现设计方案

本文档承接 [MeetFlow 前端系统设计方案](frontend-system-design.md)，进一步描述如何把 `MeetFlow Console` 落成代码，并与当前 Python 项目无缝衔接。

目标是：前端只做控制台和可视化，所有飞书读写、Agent 决策、工具调用、安全策略、幂等和审计继续复用现有后端能力，不能另开绕过 `AgentPolicy` / `ToolRegistry` / `FeishuClient` 的捷径。

## 1. 实现边界

### 1.1 第一阶段交付范围

第一阶段只实现本地单机控制台，服务开发联调、答辩演示和真实测试。

必做能力：

- Dashboard：展示系统健康、最近报告、最新评测分数、队列摘要。
- M3 会前发卡：通过前端触发 `scripts/card_send_live.py m3` 等价能力。
- Evaluation 评测中心：运行 `scripts/agent_eval_suite.py` 等价能力并展示指标。
- Jobs / Health：展示 `workflow_jobs`、migration 状态、worker dry-run 结果。

暂缓能力：

- 多用户权限系统。
- 在线编辑评测 case。
- 复杂图表和大屏。
- 前端直接处理飞书 OAuth token。

### 1.2 工程原则

- 后端 API facade 必须使用项目现有 `config`、`core`、`scripts` 能力。
- 真实写操作必须显式传 `allow_write=true` 和幂等键。
- 前端所有 write action 必须有二次确认。
- API 返回值必须脱敏，不返回 token、secret、API key、refresh_token。
- 第一版可以使用 Python 标准库 HTTP server，避免引入 FastAPI 等新依赖；后续再按需要升级。
- 前端可以新增 Node 工具链，但必须隔离在 `frontend/`，不影响 Python 主环境。

## 2. 目录规划

建议新增目录：

```text
frontend/
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  src/
    main.tsx
    App.tsx
    api/
      client.ts
      types.ts
    components/
      MetricCard.tsx
      StatusBadge.tsx
      ConfirmWriteDialog.tsx
      JsonPreview.tsx
      DataTable.tsx
    pages/
      DashboardPage.tsx
      M3ConsolePage.tsx
      EvaluationPage.tsx
      JobsHealthPage.tsx
    styles/
      app.css

core/console_api.py
  # 后端 facade 的业务函数，供 HTTP server 和后续测试复用。

scripts/meetflow_console_server.py
  # 本地 HTTP API + 静态资源服务入口。

tests/test_console_api.py
  # 后端 API facade 单元测试。
```

后续 M4/M5 页面成熟后再补：

```text
frontend/src/pages/M4ConsolePage.tsx
frontend/src/pages/RiskScanPage.tsx
```

## 3. 后端 Facade 设计

### 3.1 文件职责

`core/console_api.py`：

- 不直接启动网络服务。
- 提供可测试的纯 Python facade 函数。
- 查询 SQLite、读取 reports、调用现有评测 runner。
- 对真实脚本执行做参数白名单和超时控制。

`scripts/meetflow_console_server.py`：

- 负责 HTTP 路由、JSON 编解码、错误响应。
- 调用 `core.console_api`。
- 本地开发时监听 `127.0.0.1:8787`。
- 可选服务 `frontend/dist` 静态资源。

### 3.2 后端函数草案

建议在 `core/console_api.py` 中提供：

```python
def get_health() -> dict[str, Any]:
    """返回配置、SQLite、migration、报告目录等健康状态。"""


def get_dashboard() -> dict[str, Any]:
    """聚合最近报告、评测分数、队列状态和服务提示。"""


def list_jobs(limit: int = 50, status: str = "", queue_name: str = "") -> dict[str, Any]:
    """读取 workflow_jobs，供 Jobs 页面展示。"""


def get_latest_report(report_type: str) -> dict[str, Any]:
    """读取 evaluation/m3/m4 最新报告摘要。"""


def run_m3_send_card(request: M3SendCardRequest) -> dict[str, Any]:
    """触发 M3 会前发卡。第一版可安全包装 card_send_live.py。"""


def run_agent_evaluation(request: EvaluationRunRequest) -> dict[str, Any]:
    """复用 scripts.agent_eval_suite.run_agent_eval_suite 输出评测值。"""


def run_worker_once(dry_run: bool = True) -> dict[str, Any]:
    """执行 worker once dry-run，用于健康检查。"""


def get_migration_status() -> dict[str, Any]:
    """复用 MigrationRunner.status/verify。"""
```

请求模型可先用 dataclass，避免引入 Pydantic：

```python
@dataclass(slots=True)
class M3SendCardRequest:
    date: str = "tomorrow"
    event_title: str = ""
    event_id: str = ""
    llm_provider: str = "scripted_debug"
    project_id: str = "meetflow"
    allow_write: bool = False
    write_report: bool = True
    force_index: bool = False
    idempotency_suffix: str = ""


@dataclass(slots=True)
class EvaluationRunRequest:
    suite: str = "agent_trajectory"
    case_id: str = ""
    provider: str = "scripted_debug"
    fail_under: float = 0.95
    write_report: bool = True
```

### 3.3 HTTP API 路由

第一版接口：

```text
GET  /api/health
GET  /api/dashboard
GET  /api/jobs?limit=50&status=&queue_name=
GET  /api/reports/latest?type=evaluation|m3|m4
GET  /api/migrations/status
POST /api/m3/send-card
POST /api/evaluation/run
POST /api/worker/run-once
```

统一响应格式：

```json
{
  "ok": true,
  "data": {},
  "error": ""
}
```

错误响应：

```json
{
  "ok": false,
  "data": {},
  "error": "schema verify failed: ..."
}
```

### 3.4 API 与现有能力映射

```text
/api/health
  -> load_settings()
  -> MigrationRunner.verify()
  -> 检查 storage/reports/evaluation/agent_trajectory_latest.json 是否存在

/api/dashboard
  -> get_latest_report("evaluation")
  -> workflow_jobs status count
  -> storage/reports/m3 最新文件
  -> storage/reports/m4 最新文件

/api/jobs
  -> SQLite SELECT workflow_jobs

/api/migrations/status
  -> MigrationRunner.status()
  -> MigrationRunner.verify()

/api/m3/send-card
  -> 校验 allow_write 和 idempotency_suffix
  -> 组装白名单命令调用 scripts/card_send_live.py m3
  -> 解析 stdout 中 trace_id/status/report path
  -> 返回报告路径和关键摘要

/api/evaluation/run
  -> from scripts.agent_eval_suite import run_agent_eval_suite
  -> 写 storage/reports/evaluation/agent_trajectory_latest.json
  -> 返回 score/safety_score/results

/api/worker/run-once
  -> 只允许 dry_run=true
  -> 调用 scripts/meetflow_worker.py --once --dry-run
```

M3 发卡第一版用 subprocess 包装是为了最快衔接现有真实联调脚本；第二阶段可以下沉为直接调用 `pre_meeting_live_test.py` 中的可复用函数，减少 stdout 解析。

## 4. 前端实现设计

### 4.1 技术栈

建议：

```text
React
TypeScript
Vite
Tailwind CSS
lucide-react
Recharts
```

如果希望少引依赖，第一版可以不用 shadcn/ui，仅实现本地组件。

### 4.2 页面路由

第一版不一定引入 React Router，可以用内部状态做 tab：

```text
Dashboard
M3 Console
Evaluation
Jobs / Health
```

后续页面超过 6 个时再引入 router。

### 4.3 前端 API 类型

`frontend/src/api/types.ts`：

```ts
export type ApiResponse<T> = {
  ok: boolean;
  data: T;
  error: string;
};

export type EvaluationMetric = {
  name: string;
  score: number;
  passed: boolean;
  expected?: unknown;
  actual?: unknown;
  reason?: string;
};

export type EvaluationCaseResult = {
  case_id: string;
  score: number;
  passed: boolean;
  metrics: EvaluationMetric[];
  trace_summary: {
    workflow_type: string;
    status: string;
    tool_calls: string[];
    policy_statuses: string[];
  };
};

export type EvaluationReport = {
  suite: string;
  provider: string;
  total_cases: number;
  passed_cases: number;
  score: number;
  safety_score: number;
  generated_at: number;
  results: EvaluationCaseResult[];
};

export type JobRow = {
  job_id: string;
  queue_name: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string;
  created_at: number;
  updated_at: number;
};
```

### 4.4 前端页面细节

#### DashboardPage

模块：

- 系统状态：SQLite、migration、reports、config。
- 最新评测：`score`、`safety_score`、`passed_cases / total_cases`。
- 队列状态：pending/running/succeeded/failed/dead。
- 最近 M3/M4 报告入口。

调用：

```text
GET /api/dashboard
GET /api/health
```

#### M3ConsolePage

表单字段：

- `date`：today / tomorrow / YYYY-MM-DD
- `event_title`
- `event_id`
- `llm_provider`
- `write_report`
- `force_index`
- `allow_write`
- `idempotency_suffix`

交互规则：

- 默认 `allow_write=false`，按钮显示为 dry-run。
- 开启 `allow_write=true` 时弹出确认框。
- 如果 `idempotency_suffix` 为空，前端生成 `m3-YYYYMMDDHHmmss`。

调用：

```text
POST /api/m3/send-card
```

结果展示：

- `trace_id`
- `workflow_type`
- `status`
- `selected_event`
- `report_markdown`
- `report_json`
- `tool_results`

#### EvaluationPage

表单字段：

- `suite`
- `case_id`
- `provider`
- `fail_under`
- `write_report`

展示：

- 顶部指标卡：`score`、`safety_score`、`passed_cases`、`total_cases`
- case 列表：每个 case 的分数、通过状态、workflow
- metric 表格：每个细项指标的 score / passed / expected / actual

调用：

```text
GET  /api/reports/latest?type=evaluation
POST /api/evaluation/run
```

#### JobsHealthPage

模块：

- migration status / verify
- worker dry-run 按钮
- workflow_jobs 表格
- last_error 展开查看

调用：

```text
GET  /api/migrations/status
GET  /api/jobs
POST /api/worker/run-once
```

## 5. 安全与副作用控制

后端必须做以下校验：

- `allow_write=true` 时，必须有 `idempotency_suffix` 或后端生成幂等后缀。
- `/api/worker/run-once` 第一阶段只允许 dry-run。
- `/api/m3/send-card` 只允许 provider 白名单：`scripted_debug`、`dry-run`、`configured`，真实 provider 后续显式扩展。
- 所有 subprocess 命令必须使用 list 参数，不使用 shell 拼接。
- 返回 stdout 前必须脱敏，至少过滤：

```text
access_token
refresh_token
app_secret
api_key
Authorization
```

前端必须做以下控制：

- 真实写操作按钮用明确的危险态样式。
- 二次确认文案必须包含会议标题、日期、provider 和 allow_write。
- 失败时展示真实错误摘要和 trace_id，不吞掉错误。

## 6. 实施顺序

### 阶段 A：后端 facade

新增：

```text
core/console_api.py
scripts/meetflow_console_server.py
tests/test_console_api.py
```

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/console_api.py scripts/meetflow_console_server.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py --host 127.0.0.1 --port 8787
```

### 阶段 B：前端骨架

新增：

```text
frontend/package.json
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/api/client.ts
frontend/src/api/types.ts
frontend/src/pages/*.tsx
```

验收：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
npm run build
```

### 阶段 C：Dashboard + Evaluation

优先接只读和低风险操作：

- `/api/health`
- `/api/dashboard`
- `/api/reports/latest`
- `/api/evaluation/run`

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

前端应显示：

```text
score = 1.0
safety_score = 1.0
passed_cases = 3
total_cases = 3
```

### 阶段 D：M3 发卡

接入：

- `/api/m3/send-card`
- M3 表单
- 发卡结果和 report 链接

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

前端同等参数应能得到 `status=success`、`trace_id` 和报告路径。

### 阶段 E：Jobs / Health

接入：

- `/api/jobs`
- `/api/migrations/status`
- `/api/worker/run-once`

验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
```

## 7. 与现有文档同步

实现过程中必须同步更新：

- `docs/overall-test-commands.md`：新增 console server、前端 dev/build、API 测试命令。
- `tasks.md`：记录新增文件、核心函数、验证命令和结果。
- `architecture.md`：如果新增后端 API facade 或改变运行架构，需要补充 Console 层。
- `prd.md`：如果前端引入新的用户场景或验收方式，需要同步。

## 8. 后续演进

第二阶段：

- 把 M3 subprocess 包装下沉为直接调用 Python 函数。
- 接入 M4 会后总结与 review_session 页面。
- 接入 M5 风险巡检页面。
- 为 `/api/evaluation/run` 增加执行历史。

第三阶段：

- 增加 OAuth 授权状态页。
- 支持评测 case 编辑和 diff。
- 支持 Agent trace 时间线可视化。
- 支持演示模式，一键串联 M3 -> M4 -> M5。

