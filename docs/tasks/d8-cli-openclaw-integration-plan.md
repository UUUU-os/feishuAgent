# D8：后端 CLI / OpenClaw 受控接入代码改造方案

本文档承接 `docs/tasks/openclaw-demo-enhancement.md` 中的 D8 任务，基于当前仓库代码给出可直接进入开发的代码级改造方案。

D8 的目标不是新增一套绕过系统的演示脚本，而是把现有 MeetFlow Agent、Console facade 和白名单脚本包装成 OpenClaw 可调度、CLI 可复现、默认安全的统一入口：

```text
OpenClaw / CLI
  -> scripts/meetflow_cli.py
  -> core/cli_facade.py / core/console_api.py / 白名单脚本
  -> WorkflowRouter / WorkflowContextBuilder / MeetFlowAgentLoop
  -> ToolRegistry / AgentPolicy
  -> FeishuClient / Storage
```

## 1. 当前代码基线

当前仓库已经具备 D8 所需的大部分下游能力，但还没有统一 CLI 入口。

| 能力 | 当前实现 | D8 复用方式 |
|---|---|---|
| 统一真实发卡脚本 | `scripts/card_send_live.py` | 作为 M3/M4 白名单脚本入口，继续承接 `--dry-run`、`--allow-write`、幂等和真实脚本转调 |
| M3 会前卡片 | `scripts/card_send_live.py m3` -> `scripts/pre_meeting_live_test.py` | CLI `pre-meeting` 子命令优先调用 `MeetFlowConsoleAPI.run_m3_send_card()` 或等价 facade |
| M4 会后总结与任务卡 | `scripts/card_send_live.py m4` -> `scripts/post_meeting_live_test.py` | CLI `post-meeting` 子命令复用现有真实发卡链路，默认 dry-run |
| M4 任务卡按钮回调 | `scripts/card_send_live.py m4-callback` | CLI 只提供服务启动说明或 `service start`，不直接处理回调 |
| M5 风险巡检 | `scripts/risk_scan_demo.py`、`core/risk_scan.py` | CLI `risk-scan` 子命令复用 Console facade 的白名单命令 |
| 评测入口 | `scripts/agent_eval_suite.py`、`scripts/e2e_replay.py` | CLI `eval` 和 `demo-replay` 子命令复用现有评测脚本 |
| Console facade | `core/console_api.py::MeetFlowConsoleAPI` | D8 首选复用对象，避免 CLI 自己拼接所有脚本细节 |
| 服务白名单 | `core/service_manager.py` | CLI `service list/start/stop/logs` 可复用，禁止任意命令执行 |
| Console HTTP 服务 | `scripts/meetflow_console_server.py` | CLI `health` 可检查本地 Console API 状态，但不强依赖 HTTP 服务 |
| 安全脱敏 | `core/console_api.py::redact_sensitive()` | 抽出或复用，保证 CLI stdout 不泄露 token/key |
| 当前缺口 | `scripts/meetflow_cli.py` 不存在 | D8 新建统一 CLI 入口和测试 |

结论：D8 首版应以 `core/console_api.py` 为受控 facade，不直接调用 `FeishuClient.send_*` 或直接写业务表。

## 2. 设计原则

1. 默认 `dry-run`。所有可能写飞书或创建任务的命令都必须默认只打印计划，不执行真实写入。
2. 真实写入必须显式传 `--allow-write`，并由下游脚本继续带 `--allow-write`、`--send-card`、`--enable-idempotency` 或对应安全开关。
3. CLI 不接收任意 shell 命令、不执行任意 Python 表达式、不暴露 subprocess 自由入口。
4. CLI 只调用白名单 facade 方法或白名单脚本，不直接调用飞书写接口。
5. 所有 stdout 输出统一 JSON，便于 OpenClaw、Console、脚本和评测消费。
6. 所有输出必须脱敏，不打印 token、secret、refresh_token、api_key、Authorization Bearer。
7. 失败要返回真实错误摘要和非 0 exit code，不能伪造成成功。

## 3. 新增与改造文件

| 文件 | 类型 | 改造内容 |
|---|---|---|
| `scripts/meetflow_cli.py` | 新增 | 统一 CLI 入口，提供 `health`、`pre-meeting`、`post-meeting`、`task-cards`、`risk-scan`、`eval`、`demo-replay`、`service`、`openclaw-tools` 子命令 |
| `core/cli_facade.py` | 建议新增 | CLI 专用 facade，封装标准 JSON 输出、trace_id、safety_summary、OpenClaw 工具响应，不让脚本层散落解析逻辑 |
| `core/console_api.py` | 小幅改造 | 复用已有 `MeetFlowConsoleAPI`；补齐 M3 `--doc/--minute` 参数透传；必要时抽出公共脱敏与命令解析工具 |
| `tests/test_meetflow_cli.py` | 新增 | 覆盖默认 dry-run、allow-write 门禁、禁止任意命令、JSON 输出、OpenClaw 工具清单 |
| `docs/openclaw-meetflow-tool-guide.md` | 新增 | 给 OpenClaw/答辩说明 CLI 如何被外部智能流程调用 |
| `config/openclaw_tools.example.json` | 新增 | OpenClaw 工具清单示例，描述工具名、参数、命令和安全边界 |
| `docs/openclaw-demo-commands.md` | 新增 | 固定主演示命令和兜底命令 |
| `docs/tasks/d8-cli-openclaw-integration-plan.md` | 新增 | 本方案与后续完成记录 |

## 4. CLI 命令设计

### 4.1 总体命令

```bash
python3 scripts/meetflow_cli.py health
python3 scripts/meetflow_cli.py pre-meeting --date today --event-title "MeetFlow 测试会议"
python3 scripts/meetflow_cli.py post-meeting --minute "<飞书妙记链接>"
python3 scripts/meetflow_cli.py task-cards --minute "<飞书妙记链接>"
python3 scripts/meetflow_cli.py risk-scan --backend local
python3 scripts/meetflow_cli.py eval --suite agent_trajectory
python3 scripts/meetflow_cli.py demo-replay --case m3_pre_meeting_basic
python3 scripts/meetflow_cli.py service list
python3 scripts/meetflow_cli.py openclaw-tools
```

### 4.2 `health`

目标：检查本地运行环境是否具备演示条件。

复用：

- `MeetFlowConsoleAPI.get_health()`
- `MeetFlowConsoleAPI.get_migration_status()`
- `MeetFlowConsoleAPI.list_services()`
- 可选读取 `config/settings.local.json` 的字段是否存在，但不能打印密钥值。

输出字段：

```json
{
  "status": "success",
  "workflow_type": "health",
  "trace_id": "cli_health_...",
  "dry_run": true,
  "allow_write": false,
  "report_path": "",
  "data": {
    "storage_ok": true,
    "migration_ok": true,
    "feishu_config_present": true,
    "llm_provider": "settings",
    "services": []
  },
  "safety_summary": {
    "policy_checked": false,
    "write_blocked_or_confirmed": true,
    "idempotency_key_present": false,
    "secret_redacted": true
  }
}
```

### 4.3 `pre-meeting`

目标：触发 M3 会前背景知识卡。

复用：

- 首选 `MeetFlowConsoleAPI.run_m3_send_card(M3SendCardRequest)`
- 下游仍走 `scripts/card_send_live.py m3`
- `card_send_live.py m3` 再转调 `scripts/pre_meeting_live_test.py`

需要补齐：

- `M3SendCardRequest` 当前没有 `doc`、`minute`、`max_iterations`、`identity`、`calendar_id` 字段。D8 应扩展 dataclass 和 `run_m3_send_card()`，透传到 `card_send_live.py m3`。
- `validate_m3_request()` 当前允许 provider 集合里没有 `settings`，而真实 runbook 已使用 `--llm-provider settings`。D8 应把 `settings` 加入允许列表。

建议参数：

```bash
python3 scripts/meetflow_cli.py pre-meeting \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --provider settings \
  --project-id meetflow \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/YGY5dOFrMoVu5Ox7DJnc7AaSnyb" \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --write-report
```

真实发送时：

```bash
python3 scripts/meetflow_cli.py pre-meeting \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --provider settings \
  --idempotency-suffix "m3-live-20260512-01" \
  --allow-write \
  --write-report
```

安全规则：

- 未传 `--allow-write` 时必须传给下游 `--dry-run`。
- 传 `--allow-write` 时必须有 `idempotency_suffix`；如果用户没传，由 CLI 生成 `m3-cli-YYYYMMDDHHMMSS` 并写入输出。
- 不允许 CLI 直接调用 `FeishuClient.send_card_message()`。

### 4.4 `post-meeting`

目标：触发 M4 妙记复盘和会后总结卡。

复用：

- `MeetFlowConsoleAPI.run_m4_read_minute()` 用于只读复盘。
- `MeetFlowConsoleAPI.run_m4_send_cards()` 用于真实发卡，默认 dry-run。
- 下游仍走 `scripts/card_send_live.py m4`。

建议参数：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "<飞书妙记链接>" \
  --provider scripted_debug \
  --write-report
```

真实发送：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "<飞书妙记链接>" \
  --chat-id "<测试群 chat_id>" \
  --allow-write \
  --write-report
```

安全规则：

- 默认 dry-run，不发送卡片。
- `--allow-write` 时才允许下游去掉 `--dry-run`。
- `chat_id` 不传时可使用 `settings.feishu.default_chat_id`，但输出只说明“使用默认测试群”，不打印敏感配置。

### 4.5 `task-cards`

目标：让答辩中能单独强调 D4 任务卡能力。

首版实现建议：

- 复用 `post-meeting` 同一条链路。
- 在 CLI 输出里突出 `pending_action_count`、`action_item_count`、`report_path`。
- 不新增绕过 M4 的任务创建逻辑。

命令形态：

```bash
python3 scripts/meetflow_cli.py task-cards \
  --minute "<飞书妙记链接>" \
  --dry-run
```

后续 P1 可把任务卡分析拆出只读命令，但首版不要直接写 `pending_actions` 表伪造结果。

### 4.6 `risk-scan`

目标：触发 M5 风险巡检。

复用：

- `MeetFlowConsoleAPI.run_m5_risk_scan(M5RiskScanRequest)`
- 下游仍走 `scripts/risk_scan_demo.py`
- 入队模式复用 `--enqueue` 和 `workflow_jobs`

建议参数：

```bash
python3 scripts/meetflow_cli.py risk-scan \
  --backend local \
  --show-card
```

真实飞书任务读取和发送：

```bash
python3 scripts/meetflow_cli.py risk-scan \
  --backend feishu \
  --chat-id "<测试群 chat_id>" \
  --allow-write \
  --show-card
```

安全规则：

- `backend=local` 即使传 `--allow-write` 也不应发送真实消息，沿用下游脚本行为。
- `backend=feishu` 且 `--allow-write` 时才允许发送风险卡。
- `mode=enqueue` 只入队，真实副作用由 worker 再检查 payload。

### 4.7 `eval`

目标：运行 Agent 评测。

复用：

- `MeetFlowConsoleAPI.run_agent_evaluation()`
- 或直接白名单调用 `scripts/agent_eval_suite.py`

建议参数：

```bash
python3 scripts/meetflow_cli.py eval \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

输出必须包含：

- `score`
- `safety_score`
- `passed_threshold`
- `report_path`

### 4.8 `demo-replay`

目标：离线回放演示链路，适合无飞书网络或无 token 的答辩兜底。

复用：

- `scripts/e2e_replay.py`
- `tests/e2e_fixtures/m3_pre_meeting_basic`
- `tests/e2e_fixtures/m4_post_meeting_with_tasks`
- `tests/e2e_fixtures/m5_risk_from_m4_mapping`

建议参数：

```bash
python3 scripts/meetflow_cli.py demo-replay \
  --all \
  --fail-under 1.0 \
  --write-report
```

### 4.9 `service`

目标：受控管理本地 worker、SDK callback、M4 callback。

复用：

- `core/service_manager.py`
- `MeetFlowConsoleAPI.list_services()`
- `MeetFlowConsoleAPI.start_service()`
- `MeetFlowConsoleAPI.stop_service()`
- `MeetFlowConsoleAPI.tail_service_logs()`

命令形态：

```bash
python3 scripts/meetflow_cli.py service list
python3 scripts/meetflow_cli.py service start worker
python3 scripts/meetflow_cli.py service start sdk_callback --profile enqueue
python3 scripts/meetflow_cli.py service logs worker --tail 100
python3 scripts/meetflow_cli.py service stop worker
```

安全规则：

- 服务名和 profile 必须来自 `ServiceManager` 白名单。
- 不允许传入自定义命令。

### 4.10 `openclaw-tools`

目标：输出 OpenClaw 可读取的工具描述。

首版可直接读取 `config/openclaw_tools.example.json` 并输出；如果文件不存在，则由代码内置生成。

```bash
python3 scripts/meetflow_cli.py openclaw-tools
```

## 5. 标准 JSON 输出协议

建议新增 `core/cli_facade.py`：

```python
@dataclass(slots=True)
class CLIResult:
    status: str
    workflow_type: str
    trace_id: str
    dry_run: bool = True
    allow_write: bool = False
    report_path: str = ""
    agent_trace_path: str = ""
    command: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    safety_summary: dict[str, Any] = field(default_factory=dict)
```

所有子命令最终只 `print(json.dumps(result, ensure_ascii=False, indent=2))`。

统一字段：

| 字段 | 说明 |
|---|---|
| `status` | `success` / `failed` |
| `workflow_type` | `health`、`pre_meeting_brief`、`post_meeting_followup`、`risk_scan`、`agent_evaluation`、`demo_replay` |
| `trace_id` | CLI 生成或从下游解析到的 trace |
| `dry_run` | 是否 dry-run |
| `allow_write` | 是否允许真实写入 |
| `report_path` | Markdown/JSON 报告路径，优先给 JSON 或最稳定路径 |
| `agent_trace_path` | 评测/轨迹报告路径 |
| `command` | 脱敏后的白名单下游命令 |
| `data` | 子命令摘要 |
| `error` | 失败摘要，使用 `safe_error_message()` |
| `safety_summary` | 安全检查摘要 |

建议 `safety_summary`：

```json
{
  "policy_checked": true,
  "write_blocked_or_confirmed": true,
  "idempotency_key_present": true,
  "secret_redacted": true,
  "raw_shell_disabled": true,
  "whitelist_entrypoint": true
}
```

说明：

- `policy_checked=true` 对 M3/M4/M5 真实写链路表示下游仍会进入现有 AgentPolicy 或受控脚本策略。
- 对 `health/eval/demo-replay` 等无写操作命令，`policy_checked=false` 但 `write_blocked_or_confirmed=true`。

## 6. 代码实现拆分

### 阶段 1：最小统一 CLI

交付：

- 新增 `scripts/meetflow_cli.py`
- 新增 `core/cli_facade.py`
- 支持 `health`、`pre-meeting`、`post-meeting`、`risk-scan`、`eval`
- 默认 dry-run
- 统一 JSON 输出

关键代码：

```text
scripts/meetflow_cli.py
  parse_args()
  main()
  build_subparsers()
  exit code: success=0, failed=1/2

core/cli_facade.py
  MeetFlowCLI
  CLIResult
  build_trace_id()
  build_safety_summary()
  normalize_console_result()
```

验收：

```bash
python3 scripts/meetflow_cli.py health
python3 scripts/meetflow_cli.py pre-meeting --date today --event-title "MeetFlow 测试会议"
python3 scripts/meetflow_cli.py post-meeting --minute "dummy_minute"
python3 scripts/meetflow_cli.py risk-scan --backend local
python3 scripts/meetflow_cli.py eval --suite agent_trajectory --write-report
```

### 阶段 2：OpenClaw 工具说明和配置

交付：

- `docs/openclaw-meetflow-tool-guide.md`
- `config/openclaw_tools.example.json`
- `docs/openclaw-demo-commands.md`
- `scripts/meetflow_cli.py openclaw-tools`

工具建议：

| OpenClaw 工具名 | CLI 子命令 | 说明 |
|---|---|---|
| `meetflow_health` | `health` | 环境、配置、migration、服务状态 |
| `meetflow_pre_meeting` | `pre-meeting` | M3 会前背景知识卡 |
| `meetflow_post_meeting` | `post-meeting` | M4 妙记复盘和总结卡 |
| `meetflow_task_cards` | `task-cards` | D4 按人分组任务卡 |
| `meetflow_risk_scan` | `risk-scan` | M5 风险巡检 |
| `meetflow_eval` | `eval` | Agent 评测 |
| `meetflow_demo_replay` | `demo-replay` | 离线回放兜底 |

### 阶段 3：服务控制和 demo replay

交付：

- `service list/start/stop/logs`
- `demo-replay --all/--case`
- 输出报告路径

复用：

- `ServiceManager`
- `scripts/e2e_replay.py`

### 阶段 4：安全回归测试

新增 `tests/test_meetflow_cli.py`，覆盖：

1. `pre-meeting` 默认 dry-run，命令里必须出现 `--dry-run`。
2. `pre-meeting --allow-write` 必须生成或接收 `idempotency_suffix`。
3. `post-meeting` 默认 dry-run，不允许直接发送。
4. `risk-scan --backend feishu` 默认 dry-run。
5. `service start` 只接受白名单服务名。
6. CLI 不接受任意 shell 命令参数，例如不存在 `--command`。
7. stdout 是合法 JSON。
8. 输出中不包含 `access_token`、`refresh_token`、`app_secret`、`api_key` 明文。
9. `openclaw-tools` 输出工具清单且工具名稳定。

## 7. 需要同步改造的现有代码

### 7.1 `core/console_api.py`

建议小改：

1. `M3SendCardRequest` 增加：

```python
identity: str = "user"
calendar_id: str = "primary"
doc: list[str] = field(default_factory=list)
minute: list[str] = field(default_factory=list)
max_iterations: int = 5
report_dir: str = "storage/reports/m3"
```

2. `validate_m3_request()` 允许 `settings` provider：

```python
{"scripted_debug", "dry-run", "configured", "settings", "deepseek", "doubao"}
```

3. `run_m3_send_card()` 透传：

```text
--identity
--calendar-id
--doc ...
--minute ...
--max-iterations
--report-dir
```

4. 抽出公共函数：

```text
redact_sensitive()
command_for_display()
run_console_command()
```

这些函数可以继续留在 `core/console_api.py`，也可以移动到 `core/command_facade.py`，但首版为了减少风险可以先复用原位置。

### 7.2 `scripts/card_send_live.py`

首版不必重构，但需要明确：

- `m3` 已支持 `--doc`、`--minute`、`--dry-run`、`--write-report`。
- `m4` 已支持 `--dry-run`。
- 该脚本仍是“真实发卡统一入口”，`meetflow_cli.py` 是更高层 OpenClaw/CLI 入口。

### 7.3 `scripts/risk_scan_demo.py`

首版不改业务逻辑。后续可补：

- 输出稳定 JSON summary，方便 CLI 更可靠解析。
- 保留现有人类可读输出给本地调试。

### 7.4 `scripts/agent_eval_suite.py` 和 `scripts/e2e_replay.py`

首版不改业务逻辑。建议后续统一：

- 写报告后同时输出 `report_path` 字段，而不只打印中文行。
- CLI 首版可通过正则解析“评测报告已写入：...”。

## 8. OpenClaw 工具清单示例

`config/openclaw_tools.example.json` 建议结构：

```json
{
  "version": "1.0",
  "tools": [
    {
      "name": "meetflow_pre_meeting",
      "description": "生成 MeetFlow 会前背景知识卡，默认 dry-run，真实发卡必须 allow_write。",
      "command": "python3 scripts/meetflow_cli.py pre-meeting",
      "input_schema": {
        "type": "object",
        "properties": {
          "date": {"type": "string"},
          "event_title": {"type": "string"},
          "provider": {"type": "string"},
          "doc": {"type": "array", "items": {"type": "string"}},
          "minute": {"type": "array", "items": {"type": "string"}},
          "allow_write": {"type": "boolean"}
        },
        "required": ["date", "event_title"]
      },
      "safety": {
        "default_dry_run": true,
        "requires_allow_write_for_side_effects": true,
        "idempotency_required_for_write": true
      }
    }
  ]
}
```

实际实现时工具清单要覆盖 `health`、`pre_meeting`、`post_meeting`、`task_cards`、`risk_scan`、`eval`、`demo_replay`。

## 9. 验证矩阵

### 9.1 静态检查

```bash
python3 -m py_compile scripts/meetflow_cli.py core/cli_facade.py core/console_api.py tests/test_meetflow_cli.py
```

### 9.2 单元测试

```bash
python3 -m unittest tests.test_meetflow_cli tests.test_console_api
```

### 9.3 CLI dry-run 验收

```bash
python3 scripts/meetflow_cli.py health
python3 scripts/meetflow_cli.py pre-meeting --date today --event-title "MeetFlow 测试会议" --provider scripted_debug
python3 scripts/meetflow_cli.py post-meeting --minute "dummy_minute"
python3 scripts/meetflow_cli.py risk-scan --backend local --show-card
python3 scripts/meetflow_cli.py eval --suite agent_trajectory --write-report
python3 scripts/meetflow_cli.py demo-replay --all --write-report
python3 scripts/meetflow_cli.py openclaw-tools
```

### 9.4 真实写入验收

真实写入只在用户明确确认后执行：

```bash
python3 scripts/meetflow_cli.py pre-meeting \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --provider settings \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/YGY5dOFrMoVu5Ox7DJnc7AaSnyb" \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --idempotency-suffix "m3-cli-live-20260512-01" \
  --allow-write \
  --write-report
```

M4/M5 真实写入同理必须传 `--allow-write`，并使用测试群。

## 10. 风险与控制

| 风险 | 控制方式 |
---|---|
| CLI 变成任意命令执行器 | 只提供固定 subcommand，不提供 `--command`、shell 字符串或 Python 表达式 |
| 绕过 AgentPolicy | CLI 不直接调用 FeishuClient 写接口，只调用 Console facade / 白名单脚本 |
| 默认真实写入 | 所有写链路默认 dry-run，`--allow-write` 才去掉下游 `--dry-run` |
| 重复发卡或重复建任务 | 写链路必须有 idempotency suffix/key；无 suffix 时 CLI 生成并输出 |
| 输出泄露 token/key | 复用 `redact_sensitive()`，测试覆盖敏感字段脱敏 |
| OpenClaw 参数过大拖垮本地脚本 | 对字符串长度、列表长度、timeout 做上限校验 |
| 真实 LLM 接收敏感飞书内容 | provider 默认 `scripted_debug`；`settings/deepseek/doubao` 在文档里提示需确认风险 |
| 报告路径解析不稳定 | 优先让下游脚本输出 JSON 字段；首版用 parser 兼容旧 stdout |

## 11. 验收标准

D8 完成后应满足：

1. `scripts/meetflow_cli.py` 存在，并能触发 health、M3、M4、M5、eval、demo replay。
2. 所有命令默认 dry-run。
3. 真实写入必须显式 `--allow-write`。
4. CLI 输出合法 JSON，包含 `trace_id`、`workflow_type`、`status`、`report_path`、`safety_summary`。
5. CLI 不允许任意 shell/Python 执行。
6. OpenClaw 工具说明和工具清单示例可展示。
7. 单元测试覆盖安全边界。
8. Runbook 或 `docs/openclaw-demo-commands.md` 中有可复现演示命令。

## 12. 建议实施顺序

1. 新建 `core/cli_facade.py` 和 `scripts/meetflow_cli.py`，先支持 `health`、`pre-meeting`、`post-meeting`、`risk-scan`。
2. 扩展 `M3SendCardRequest` 支持 `doc/minute/settings provider`。
3. 新增 `tests/test_meetflow_cli.py`，锁定默认 dry-run 和 JSON 输出。
4. 接入 `eval`、`demo-replay`、`service`。
5. 新增 OpenClaw 工具说明、工具清单示例和演示命令文档。
6. 最后做一次 `py_compile + unittest + dry-run 命令矩阵`。

## 13. 本轮方案记录

2026-05-12 新增 D8 代码改造方案。

本轮只做方案设计和文档落地，未修改业务运行代码。已确认当前仓库没有
`scripts/meetflow_cli.py`，但已有 `core/console_api.py`、`scripts/card_send_live.py`、
`scripts/risk_scan_demo.py`、`scripts/agent_eval_suite.py`、`scripts/e2e_replay.py`
和 `core/service_manager.py` 可复用。后续实现应优先复用这些受控入口，避免新增绕过
`AgentPolicy`、幂等和 `allow_write` 的捷径。

2026-05-12 完成 D8 首轮代码落地。

本轮新增 `scripts/meetflow_cli.py` 和 `core/cli_facade.py`，形成 OpenClaw / CLI 统一入口；
支持 `health`、`pre-meeting`、`post-meeting`、`task-cards`、`risk-scan`、`eval`、
`demo-replay`、`service` 和 `openclaw-tools` 子命令。CLI 默认 dry-run，真实写入必须显式
`--allow-write`；所有子命令输出统一 JSON，包含 `status`、`workflow_type`、`trace_id`、
`report_path` 和 `safety_summary`。`core/console_api.py` 同步扩展 M3 请求字段，支持
`identity`、`calendar_id`、`doc`、`minute`、`max_iterations`、`report_dir`，并允许
`settings` provider；`health/migration` 对 storage 目录缺失做了安全兜底，不再直接抛 SQLite
底层异常。新增 `config/openclaw_tools.example.json` 和 `docs/openclaw-meetflow-tool-guide.md`
作为 OpenClaw 工具清单和 CLI 使用手册。新增 `tests/test_meetflow_cli.py`，补充 Console API
测试，覆盖默认 dry-run、allow-write 幂等后缀、M3 doc/minute 透传、OpenClaw 工具清单和禁止
任意 `--command` 参数。

验证命令：

```bash
python3 -m py_compile core/cli_facade.py scripts/meetflow_cli.py core/console_api.py tests/test_meetflow_cli.py tests/test_console_api.py
python3 -m unittest tests.test_meetflow_cli tests.test_console_api
python3 scripts/meetflow_cli.py health
python3 scripts/meetflow_cli.py openclaw-tools
python3 scripts/meetflow_cli.py pre-meeting --date today --event-title "MeetFlow 测试会议" --provider scripted_debug --doc "https://example.feishu.cn/docx/demo" --minute "https://example.feishu.cn/minutes/demo" --write-report
python3 scripts/meetflow_cli.py post-meeting --minute "dummy_minute"
python3 scripts/meetflow_cli.py risk-scan --backend local --show-card
python3 scripts/meetflow_cli.py eval --suite agent_trajectory --write-report
python3 scripts/meetflow_cli.py demo-replay --all --write-report
```

结果：编译通过；`tests.test_meetflow_cli` 和 `tests.test_console_api` 共 18 条测试通过；
CLI health、openclaw-tools、pre-meeting dry-run、post-meeting dry-run、risk-scan local、
agent eval、demo replay 均能输出标准 JSON。真实飞书写入未执行，后续需在用户确认
`--allow-write` 后再跑 M3/M4/M5 真实联调。

2026-05-12 补充 D3 四终端真实联调快捷命令。

用户确认 D3 真实按钮联调应按四个终端运行：SDK 回调、worker、重新发送 D3 会后总结卡、
tail 观察回调日志。本轮修改 `scripts/meetflow_cli.py`，新增 `live` 命令组，固定封装
`live sdk-callback`、`live worker`、`live d3-card`、`live watch-callbacks` 四个白名单命令；
其中 `live d3-card` 固定走 `scripts/card_send_live.py m4` 并默认使用
`storage/reports/m4/d3`，`live watch-callbacks` 固定 tail `storage/card_callbacks.jsonl`
和 `storage/workflow_events.jsonl`。同步更新 `docs/openclaw-meetflow-tool-guide.md`，加入
D3 四终端真实联调快捷命令说明；`tests/test_meetflow_cli.py` 增加 live 命令构造测试。

验证命令：

```bash
python3 -m py_compile scripts/meetflow_cli.py tests/test_meetflow_cli.py
python3 -m unittest tests.test_meetflow_cli
python3 scripts/meetflow_cli.py live d3-card --minute obcngy8e7x2883b6f9f5x4l9 --show-card-json --dry-run
```

结果：10 条 CLI 测试通过；`live d3-card --dry-run` 能打印等价的 `card_send_live.py m4`
下游命令。`live worker` 验证时会启动前台长进程，验证后已停止；真实联调时应在独立终端保持运行。

2026-05-12 调整 OpenClaw 使用手册结构。

根据真实联调使用习惯，将 `docs/openclaw-meetflow-tool-guide.md` 中的 D3 四终端真实联调快捷命令
移动到文档最前面作为第一入口；删除后文重复的 SDK 回调、M4 专用回调和 worker 启动说明，只保留
通用服务查看、日志和停止命令，避免同一链路出现多套口径。本次只调整文档，未修改运行代码。

2026-05-12 补充 CLI 命令功能总览表。

在 `docs/openclaw-meetflow-tool-guide.md` 开头新增 CLI 命令与功能表，覆盖 `health`、M3/M4/D4/M5、
评测、离线回放、D3 四终端 `live` 命令、服务控制和 OpenClaw 工具清单，标明典型场景和写入说明。
本次只调整文档，未修改运行代码。

2026-05-12 新增面向 AI / Agent / OpenClaw 的 Skill 文档。

本轮新增 `docs/skills/MEETFLOW_CLI_OPENCLAW_SKILL.md`，基于现有使用手册、`scripts/meetflow_cli.py`、
`core/cli_facade.py`、`core/console_api.py`、`config/openclaw_tools.example.json`、`core/service_manager.py`
和 M3/M4/M5 底层脚本，整理 AI / OpenClaw 应如何安全调用 MeetFlow CLI。文档明确区分已实现 CLI 命令
和建议增强项，覆盖 health、pre-meeting、post-meeting、task-cards、risk-scan、eval、demo-replay、
D3 四终端 live 命令、service 管理和 openclaw-tools。同步新增
`docs/skills/MEETFLOW_CLI_OPENCLAW_DOC_ISSUES.md`，记录当前手册与代码不一致点：`live` 命令非 JSON、
`live d3-card` 默认真实发卡、顶层 `suggested_fix` 尚未实现、`health` 不直接验证 OAuth token、
`service start` 已实现但手册弱化展示。本次只修改文档，未修改核心业务代码，未提交真实配置或密钥。
