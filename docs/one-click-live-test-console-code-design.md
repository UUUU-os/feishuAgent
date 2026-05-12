# MeetFlow 一键真实联调控制台代码设计方案

本文档承接 [MeetFlow 一键真实联调控制台设计方案](one-click-live-test-console-design.md)，进一步给出代码级落地方案。目标是把多终端真实联调流程收敛为前端按钮和后端白名单 API，同时保持 MeetFlow 现有 Agent、Policy、ToolRegistry、FeishuClient、JobQueue 和真实联调脚本边界不被破坏。

## 1. 代码改动总览

建议按后端基础设施、业务 API、前端页面、测试与文档四组落地。

新增文件：

```text
core/service_manager.py
frontend/src/pages/LiveFlowPage.tsx
frontend/src/components/ServiceControlPanel.tsx
frontend/src/components/CommandResultPanel.tsx
docs/one-click-live-test-console-code-design.md
```

修改文件：

```text
core/console_api.py
scripts/meetflow_console_server.py
frontend/src/App.tsx
frontend/src/api/client.ts
frontend/src/api/types.ts
frontend/src/styles/app.css
tests/test_console_api.py
tasks.md
docs/overall-test-commands.md
docs/frontend-system-design.md
```

可选新增测试文件：

```text
tests/test_service_manager.py
```

## 2. 后端模块设计

### 2.1 `core/service_manager.py`

职责：

- 统一管理 Console 启动的长期本地服务。
- 只允许启动固定白名单 profile。
- 记录 PID、命令、启动时间和日志路径。
- 停止时只停止由 Console 启动并记录的进程。
- 提供日志 tail 读取能力。

建议数据结构：

```python
@dataclass(slots=True)
class ManagedServiceStatus:
    """Console 管理的本地长期服务状态。"""

    name: str
    profile: str
    status: str
    pid: int
    started_at: int
    command: list[str]
    log_path: str
    error: str = ""


@dataclass(slots=True)
class ServiceStartRequest:
    """启动本地长期服务的请求。"""

    name: str
    profile: str = "default"
    force_restart: bool = False
```

建议核心类：

```python
class ServiceManager:
    """管理 MeetFlow Console 启动的长期服务进程。

    这里保存的是本地联调服务状态，不保存任何飞书 token 或 LLM key。
    """

    def __init__(self, project_root: Path, *, runtime_dir: Path | None = None) -> None:
        ...

    def list_services(self) -> dict[str, Any]:
        ...

    def start_service(self, request: ServiceStartRequest) -> dict[str, Any]:
        ...

    def stop_service(self, name: str) -> dict[str, Any]:
        ...

    def tail_logs(self, name: str, *, tail: int = 200) -> dict[str, Any]:
        ...
```

运行状态位置：

```text
storage/runtime/services.json
storage/runtime/logs/worker.log
storage/runtime/logs/sdk_callback.log
storage/runtime/logs/m4_callback.log
```

白名单服务 profile：

```python
SERVICE_PROFILES = {
    "worker": {
        "default": [
            MEETFLOW_PYTHON,
            "scripts/meetflow_worker.py",
            "--queues",
            "workflow,risk_scan,rag_refresh",
            "--poll-seconds",
            "2",
        ],
    },
    "sdk_callback": {
        "enqueue": [
            SDK_PYTHON,
            "scripts/feishu_event_sdk_server.py",
            "--enqueue-agent",
            "--agent-provider",
            "dry-run",
            "--job-queue",
            "workflow",
            "--log-level",
            "info",
        ],
    },
    "m4_callback": {
        "default": [
            MEETFLOW_PYTHON,
            "scripts/card_send_live.py",
            "m4-callback",
            "--log-level",
            "info",
        ],
    },
}
```

其中 `MEETFLOW_PYTHON` 和 `SDK_PYTHON` 建议从项目现有约定生成：

```text
/home/tanyd/anaconda3/envs/meetflow/bin/python
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python
```

实现细节：

- 启动前创建 `storage/runtime/logs/`。
- 使用 `subprocess.Popen(..., stdout=log_file, stderr=subprocess.STDOUT, cwd=project_root)`。
- 写入 `services.json` 时使用临时文件替换，避免中途写坏。
- `list_services()` 要检查 PID 是否仍存活，不只相信状态文件。
- `stop_service()` 只停止状态文件中对应服务的 PID。
- 停止后状态改为 `stopped`，保留最近日志路径。
- 读取日志时最多返回 tail 行，避免前端一次加载过大。

### 2.2 扩展 `core/console_api.py`

新增请求 dataclass：

```python
@dataclass(slots=True)
class CommandRunResult:
    """Console 包装脚本执行后的统一结果。"""

    ok: bool
    returncode: int
    dry_run: bool
    command: list[str]
    stdout: str
    stderr: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)
    report_path: str = ""
    job: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class M4ReadMinuteRequest:
    """读取飞书妙记并生成会后只读摘要的请求。"""

    minute: str
    identity: str = "user"
    content_limit: int = 800
    show_card_json: bool = False
    timeout_seconds: int = 180


@dataclass(slots=True)
class M4SendCardsRequest:
    """发送 M4 会后总结卡和待确认任务卡的请求。"""

    minute: str
    identity: str = "user"
    chat_id: str = ""
    receive_id_type: str = "chat_id"
    content_limit: int = 300
    related_top_n: int = 5
    skip_related_knowledge: bool = False
    show_card_json: bool = False
    allow_write: bool = False
    timeout_seconds: int = 180


@dataclass(slots=True)
class M5RiskScanRequest:
    """触发 M5 任务风险提醒的请求。"""

    backend: str = "local"
    mode: str = "direct"
    chat_id: str = ""
    identity: str = "user"
    send_identity: str = "tenant"
    completed: str = "false"
    page_size: int = 50
    page_limit: int = 20
    stale_update_days: int = 0
    due_soon_hours: int = 0
    max_reminders: int = 0
    show_card: bool = True
    allow_write: bool = False
    timeout_seconds: int = 180
```

新增 facade 方法：

```python
class MeetFlowConsoleAPI:
    def list_services(self) -> dict[str, Any]:
        ...

    def start_service(self, request: ServiceStartRequest) -> dict[str, Any]:
        ...

    def stop_service(self, name: str) -> dict[str, Any]:
        ...

    def tail_service_logs(self, name: str, *, tail: int = 200) -> dict[str, Any]:
        ...

    def run_m4_read_minute(self, request: M4ReadMinuteRequest) -> dict[str, Any]:
        ...

    def run_m4_send_cards(self, request: M4SendCardsRequest) -> dict[str, Any]:
        ...

    def run_m5_risk_scan(self, request: M5RiskScanRequest) -> dict[str, Any]:
        ...

    def list_review_sessions(self, *, limit: int = 20) -> dict[str, Any]:
        ...

    def list_pending_actions(self, *, limit: int = 20) -> dict[str, Any]:
        ...

    def list_task_mappings(self, *, limit: int = 20) -> dict[str, Any]:
        ...

    def list_risk_notifications(self, *, limit: int = 20) -> dict[str, Any]:
        ...
```

建议抽取通用脚本执行函数：

```python
def run_console_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    """执行 Console 白名单命令，并统一脱敏输出。"""
```

`dry_run=True` 时有两种情况：

- 脚本本身支持 `--dry-run`：仍运行脚本，让它打印下游命令。
- 只想展示命令：不启动长期服务，不执行副作用。

M4 只读命令映射：

```python
[
    sys.executable,
    str(self.project_root / "scripts" / "post_meeting_live_test.py"),
    "--minute",
    request.minute,
    "--identity",
    request.identity,
    "--read-only",
    "--show-card-json",
    "--content-limit",
    str(request.content_limit),
]
```

M4 发卡命令映射：

```python
[
    sys.executable,
    str(self.project_root / "scripts" / "card_send_live.py"),
    "m4",
    "--minute",
    request.minute,
    "--identity",
    request.identity,
    "--receive-id-type",
    request.receive_id_type,
    "--content-limit",
    str(request.content_limit),
    "--related-top-n",
    str(request.related_top_n),
]
```

当 `allow_write=False` 时追加：

```text
--dry-run
```

当 `allow_write=True` 时：

- 不追加 `--dry-run`
- 如有 `chat_id`，追加 `--chat-id`
- 如 `chat_id` 为空，允许脚本使用 `settings.feishu.default_chat_id`

M5 直接执行命令映射：

```python
[
    sys.executable,
    str(self.project_root / "scripts" / "risk_scan_demo.py"),
    "--backend",
    request.backend,
    "--identity",
    request.identity,
    "--send-identity",
    request.send_identity,
    "--completed",
    request.completed,
    "--page-size",
    str(request.page_size),
    "--page-limit",
    str(request.page_limit),
]
```

当 `show_card=True` 时追加 `--show-card`。

当 `allow_write=True` 时追加 `--allow-write`。

当 `mode=enqueue` 时追加 `--enqueue`，并返回 job 信息或 stdout 中的 job 摘要。

### 2.3 参数校验函数

新增：

```python
def validate_m4_read_minute_request(request: M4ReadMinuteRequest) -> None:
    ...

def validate_m4_send_cards_request(request: M4SendCardsRequest) -> None:
    ...

def validate_m5_risk_scan_request(request: M5RiskScanRequest) -> None:
    ...

def validate_service_name(name: str) -> None:
    ...
```

校验规则：

- `minute` 不能为空。
- `identity` 只能是 `user` 或 `tenant`。
- M4 默认读取妙记使用 `user`。
- `receive_id_type` 第一阶段只允许 `chat_id`。
- `backend` 只能是 `local` 或 `feishu`。
- `mode` 只能是 `direct` 或 `enqueue`。
- `completed` 只能是 `true`、`false`、`all`。
- `page_size` 限制在 `1..100`。
- `page_limit` 限制在 `1..100`。
- `content_limit` 限制在 `100..5000`。
- 所有 timeout 限制在 `10..600`。

### 2.4 SQLite 查询函数

新增查询：

```python
def query_review_sessions(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    ...

def query_pending_actions(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    ...

def query_task_mappings(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    ...

def query_risk_notifications(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    ...
```

注意：

- 查询不存在的表时返回空列表，不让前端崩溃。
- `payload_json`、`result_json` 这类字段可以只返回摘要，避免超大 JSON。
- 不返回 token、secret、authorization header。

## 3. HTTP 路由设计

修改：

```text
scripts/meetflow_console_server.py
```

新增 import：

```python
from core.console_api import (
    M4ReadMinuteRequest,
    M4SendCardsRequest,
    M5RiskScanRequest,
)
from core.service_manager import ServiceStartRequest
```

新增 GET 路由：

```text
GET /api/services
GET /api/services/logs?name=worker&tail=200
GET /api/m4/review-sessions?limit=20
GET /api/m4/pending-actions?limit=20
GET /api/m4/task-mappings?limit=20
GET /api/m5/risk-notifications?limit=20
```

新增 POST 路由：

```text
POST /api/services/start
POST /api/services/stop
POST /api/m4/read-minute
POST /api/m4/send-cards
POST /api/m5/risk-scan
```

路由解析示例：

```python
if parsed.path == "/api/m4/send-cards":
    request = M4SendCardsRequest(
        minute=str(payload.get("minute") or ""),
        identity=str(payload.get("identity") or "user"),
        chat_id=str(payload.get("chat_id") or ""),
        receive_id_type=str(payload.get("receive_id_type") or "chat_id"),
        content_limit=int(payload.get("content_limit") or 300),
        related_top_n=int(payload.get("related_top_n") or 5),
        skip_related_knowledge=bool(payload.get("skip_related_knowledge", False)),
        show_card_json=bool(payload.get("show_card_json", False)),
        allow_write=bool(payload.get("allow_write", False)),
        timeout_seconds=int(payload.get("timeout_seconds") or 180),
    )
    self.write_json({"ok": True, "data": api.run_m4_send_cards(request), "error": ""})
    return
```

## 4. 前端类型设计

修改：

```text
frontend/src/api/types.ts
```

新增类型：

```ts
export type CommandRunResult = {
  ok: boolean;
  returncode: number;
  dry_run: boolean;
  command: string[];
  stdout: string;
  stderr?: string;
  parsed: Record<string, unknown>;
  report_path?: string;
  job?: Record<string, unknown>;
};

export type ManagedServiceStatus = {
  name: string;
  profile: string;
  status: string;
  pid: number;
  started_at: number;
  command: string[];
  log_path: string;
  error: string;
};

export type ServicesResult = {
  items: ManagedServiceStatus[];
};

export type ServiceLogsResult = {
  name: string;
  log_path: string;
  content: string;
};

export type M4SendCardsRequest = {
  minute: string;
  identity: string;
  chat_id: string;
  receive_id_type: string;
  content_limit: number;
  related_top_n: number;
  skip_related_knowledge: boolean;
  show_card_json: boolean;
  allow_write: boolean;
  timeout_seconds: number;
};

export type M5RiskScanRequest = {
  backend: string;
  mode: string;
  chat_id: string;
  identity: string;
  send_identity: string;
  completed: string;
  page_size: number;
  page_limit: number;
  stale_update_days: number;
  due_soon_hours: number;
  max_reminders: number;
  show_card: boolean;
  allow_write: boolean;
  timeout_seconds: number;
};
```

## 5. 前端 API Client 设计

修改：

```text
frontend/src/api/client.ts
```

新增方法：

```ts
services: () => request<ServicesResult>("/api/services"),
serviceLogs: (name: string, tail = 200) =>
  request<ServiceLogsResult>(`/api/services/logs?name=${encodeURIComponent(name)}&tail=${tail}`),
startService: (body: { name: string; profile: string; force_restart?: boolean }) =>
  request<ManagedServiceStatus>("/api/services/start", {
    method: "POST",
    body: JSON.stringify(body)
  }),
stopService: (body: { name: string }) =>
  request<ManagedServiceStatus>("/api/services/stop", {
    method: "POST",
    body: JSON.stringify(body)
  }),
readM4Minute: (body: { minute: string; identity: string; content_limit: number; show_card_json: boolean }) =>
  request<CommandRunResult>("/api/m4/read-minute", {
    method: "POST",
    body: JSON.stringify(body)
  }),
sendM4Cards: (body: M4SendCardsRequest) =>
  request<CommandRunResult>("/api/m4/send-cards", {
    method: "POST",
    body: JSON.stringify(body)
  }),
runM5RiskScan: (body: M5RiskScanRequest) =>
  request<CommandRunResult>("/api/m5/risk-scan", {
    method: "POST",
    body: JSON.stringify(body)
  }),
reviewSessions: (limit = 20) => request<{ items: Record<string, unknown>[] }>(`/api/m4/review-sessions?limit=${limit}`),
pendingActions: (limit = 20) => request<{ items: Record<string, unknown>[] }>(`/api/m4/pending-actions?limit=${limit}`),
taskMappings: (limit = 20) => request<{ items: Record<string, unknown>[] }>(`/api/m4/task-mappings?limit=${limit}`),
riskNotifications: (limit = 20) => request<{ items: Record<string, unknown>[] }>(`/api/m5/risk-notifications?limit=${limit}`)
```

## 6. 前端组件设计

### 6.1 `ServiceControlPanel.tsx`

职责：

- 展示所有服务状态。
- 支持启动、停止、刷新、查看日志。
- 不负责业务流程，只负责长期服务控制。

Props：

```ts
type ServiceControlPanelProps = {
  services: ManagedServiceStatus[];
  loading: boolean;
  onRefresh: () => void;
  onStart: (name: string, profile: string) => void;
  onStop: (name: string) => void;
  onViewLogs: (name: string) => void;
};
```

UI：

- 使用 `DataTable` 展示服务列表。
- 状态使用 `StatusBadge`。
- 操作按钮使用 lucide 图标：`Play`、`Square`、`RefreshCw`、`FileText`。
- 日志可以展示在 `JsonPreview` 或 `<pre>` 面板中。

### 6.2 `CommandResultPanel.tsx`

职责：

- 统一展示 M3/M4/M5 脚本结果。
- 展示 command、returncode、stdout、report path、job 摘要。

Props：

```ts
type CommandResultPanelProps = {
  title: string;
  result: CommandRunResult | null;
};
```

UI：

- returncode 成功显示 ok，失败显示 danger。
- `dry_run=true` 时明确显示没有真实写入。
- stdout 使用 `JsonPreview`，限制高度。
- command 用折叠区展示，避免占屏。

## 7. `LiveFlowPage.tsx` 页面设计

页面 state：

```ts
const [services, setServices] = useState<ServicesResult | null>(null);
const [m4Form, setM4Form] = useState<M4SendCardsRequest>(initialM4Form);
const [m5Form, setM5Form] = useState<M5RiskScanRequest>(initialM5Form);
const [m4Result, setM4Result] = useState<CommandRunResult | null>(null);
const [m5Result, setM5Result] = useState<CommandRunResult | null>(null);
const [confirm, setConfirm] = useState<null | { kind: "m4" | "m5"; title: string }>(null);
const [error, setError] = useState("");
const [running, setRunning] = useState("");
```

页面布局：

```text
PageHeader
服务控制区
M4 会后总结区
M5 任务风险提醒区
最近 M4/M5 状态表
```

M3 已有单独页面，第一阶段可以不嵌入；也可以在 `LiveFlowPage` 顶部提供跳转说明。第二阶段再把 M3 表单抽成组件复用。

真实写入流程：

```ts
const submitM4 = () => {
  if (m4Form.allow_write) {
    setConfirm({ kind: "m4", title: "确认真实发送 M4 卡片" });
    return;
  }
  void runM4();
};
```

确认弹窗复用：

```text
frontend/src/components/ConfirmWriteDialog.tsx
```

## 8. App 导航设计

修改：

```text
frontend/src/App.tsx
```

新增页面 key：

```ts
type PageKey = "dashboard" | "m3" | "live" | "evaluation" | "jobs";
```

新增 nav item：

```ts
{ key: "live", label: "真实联调", description: "一键 M4/M5/服务", icon: RadioTower }
```

渲染：

```tsx
{page === "live" ? <LiveFlowPage /> : null}
```

## 9. 样式设计

修改：

```text
frontend/src/styles/app.css
```

新增样式：

```css
.live-grid
.service-table
.log-panel
.command-summary
.danger-zone
.form-panel--compact
.split-panel
.status-dot
```

风格要求：

- 保持现有 Console 的运维型界面，不做营销页。
- 真实写入按钮使用已有 `button--danger`。
- 日志区域固定高度，避免撑爆页面。
- 表单在窄屏下单列展示。
- 不使用大面积渐变或装饰背景。

## 10. 测试设计

### 10.1 `tests/test_service_manager.py`

建议测试：

- `list_services()` 在状态文件不存在时返回默认 stopped。
- 未知服务名启动失败。
- 未知 profile 启动失败。
- `tail_logs()` 限制行数。
- 状态文件读写不包含敏感字段。
- 停止不存在 PID 时返回 stopped 或明确错误。

为了避免测试真的启动长期服务，可以设计一个 test profile：

```python
["/bin/sh", "-c", "printf ready; sleep 1"]
```

但 profile 必须只在测试注入，不写入生产白名单。

### 10.2 扩展 `tests/test_console_api.py`

建议测试：

- M4 read-only 构造命令包含 `--read-only`。
- M4 `allow_write=False` 构造命令包含 `--dry-run`。
- M4 `allow_write=True` 构造命令不包含 `--dry-run`。
- M5 `mode=enqueue` 构造命令包含 `--enqueue`。
- M5 `allow_write=False` 不包含 `--allow-write`。
- M5 `backend` 非法时报 `ConsoleAPIError`。
- 服务 start/stop 调用 `ServiceManager`。
- SQLite 查询表不存在时返回空列表。

为了让测试不真实访问飞书，建议：

- 对 `subprocess.run` 使用 `unittest.mock.patch`。
- 模拟 returncode/stdout。
- 使用临时 SQLite。

### 10.3 前端构建测试

```bash
cd frontend
npm run build
```

如果新增 TypeScript 类型或组件，必须通过构建。

## 11. 验证命令

后端：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py

/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_console_api \
  tests.test_jobs \
  tests.test_risk_scan \
  tests.test_post_meeting_card_callback
```

前端：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm run build
```

Console API 手工检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

另开命令检查：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
curl --noproxy '*' -sS http://127.0.0.1:8787/api/services
```

## 12. 推荐提交拆分

### Commit 1：ServiceManager

范围：

- `core/service_manager.py`
- `tests/test_service_manager.py`

验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_service_manager
```

### Commit 2：Console API 扩展

范围：

- `core/console_api.py`
- `scripts/meetflow_console_server.py`
- `tests/test_console_api.py`

验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
```

### Commit 3：前端真实联调页面

范围：

- `frontend/src/pages/LiveFlowPage.tsx`
- `frontend/src/components/ServiceControlPanel.tsx`
- `frontend/src/components/CommandResultPanel.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/App.tsx`
- `frontend/src/styles/app.css`

验证：

```bash
cd frontend
npm run build
```

### Commit 4：文档同步

范围：

- `docs/overall-test-commands.md`
- `docs/frontend-system-design.md`
- `tasks.md`

验证：

```text
人工检查文档中新增入口、命令和验收结果是否完整。
```

## 13. 第一阶段最小可用版本

如果希望尽快落地，第一阶段可以只做以下能力：

后端：

- `/api/services`
- `/api/services/start`
- `/api/services/stop`
- `/api/services/logs`
- `/api/m4/read-minute`
- `/api/m4/send-cards`
- `/api/m5/risk-scan`

前端：

- `真实联调` 页面
- 服务列表和启动停止按钮
- M4 妙记链接输入和发送按钮
- M5 任务风险提醒输入和执行按钮
- 结果面板

暂缓：

- M4 review_sessions 可视化
- M5 risk_notifications 可视化
- daemon 管理
- HTTP fallback 管理
- M3 表单组件化复用

这样可以最短路径解决“多终端和手动输入命令”的核心痛点。

## 14. 关键风险控制

### 14.1 防止任意命令执行

所有命令必须由后端固定模板生成。前端只能传业务参数。

禁止：

```json
{
  "command": "python scripts/xxx.py"
}
```

允许：

```json
{
  "minute": "https://xxx.feishu.cn/minutes/xxx",
  "allow_write": false
}
```

### 14.2 防止误发生产群

前端真实发送前展示：

- chat_id 来源：用户输入或默认配置
- 操作类型：发卡 / 创建任务 / 风险提醒
- 是否 `allow_write`

后端仍然依赖现有配置和脚本内安全开关。

### 14.3 防止敏感信息泄露

所有命令输出继续使用 `redact_sensitive()`。

需要新增脱敏模式：

```text
tenant_access_token
user_access_token
refresh_token
app_secret
api_key
Authorization: Bearer xxx
```

前端不展示完整环境变量、配置 JSON 或 token bundle。

## 15. 完成后的用户路径

用户只需：

1. 启动 Console API。
2. 打开浏览器进入 `真实联调` 页面。
3. 点击启动 Worker / SDK callback / M4 callback。
4. M3 页面填写会议标题或 event_id，点击真实发送会前卡片。
5. M4 区填写飞书妙记链接，点击真实发送会后总结和待确认任务卡。
6. 在飞书群点击确认任务按钮。
7. 回到 Console 查看 review session、task mapping 和 job 状态。
8. M5 区点击任务风险提醒，测试群收到任务风险提醒卡。

这样原本需要多终端手工输入的流程，收敛为一个本地控制台中的可视化、安全、可复现操作链路。
