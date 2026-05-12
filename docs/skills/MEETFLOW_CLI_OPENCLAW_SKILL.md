# MeetFlow CLI / OpenClaw Skill

本 Skill 面向 AI / Agent / OpenClaw。它的作用是把用户的自然语言需求映射到当前仓库已经实现的
MeetFlow CLI 白名单入口，安全、正确、可复现地完成会前准备、会后复盘、任务卡片生成、风险巡检、
评测回放和真实飞书联调。

统一入口必须保持为：

```bash
python3 scripts/meetflow_cli.py <command> [options]
```

本 Skill 以当前代码和现有手册为准，核心依据包括：
`docs/openclaw-meetflow-tool-guide.md`、`scripts/meetflow_cli.py`、`core/cli_facade.py`、
`core/console_api.py`、`config/openclaw_tools.example.json`、`core/service_manager.py`、
`scripts/card_send_live.py`、`scripts/risk_scan_demo.py`、`scripts/meetflow_worker.py`、
`scripts/feishu_event_sdk_server.py` 和 `scripts/oauth_device_login.py`。

## 1. Skill 适用场景

当用户提出以下需求时，应使用本 Skill：

- 检查 MeetFlow 环境健康状态；
- 生成 M3 会前背景知识卡；
- 读取飞书妙记并生成 M4 会后总结卡；
- 从妙记中生成任务卡片视角；
- 执行 M5 风险巡检；
- 运行 Agent 评测；
- 运行离线 demo-replay；
- 启动 SDK 长连接回调服务；
- 启动 workflow / risk / rag worker；
- 观察飞书卡片回调日志；
- 管理白名单后台服务；
- 输出 OpenClaw 工具清单；
- 让 OpenClaw 调度 MeetFlow 的会前、会后、任务、风险、评测流程。

不适用场景：

- 用户要求执行任意 shell、任意 Python 表达式或自定义脚本；
- 用户要求绕过 `AgentPolicy`、幂等策略或直接写业务 SQLite；
- 用户要求把 token、secret、refresh token、API key 写入文档、日志或提交；
- 用户要求默认向真实飞书群发送消息，但没有明确测试群和写入授权。

## 2. 当前真实 CLI 能力总览

下表只列当前代码中真实存在的 `scripts/meetflow_cli.py` 命令。

| 命令 | 功能 | 典型场景 | 真实写入飞书 | 默认 dry-run | 需要 `--allow-write` | 依赖底层脚本/模块 | AI / OpenClaw 应该何时调用 | 不应该何时调用 |
|---|---|---|---|---|---|---|---|---|
| `health` | 检查配置、storage、migration、服务状态、LLM provider | 演示前自检、报错排查第一步 | 否 | 是 | 否 | `core.cli_facade.MeetFlowCLI.health()`、`core.console_api` | 任何真实联调或写入前 | 不应替代 OAuth 登录本身 |
| `pre-meeting` | 触发 M3 会前背景知识卡 | 会前卡片 dry-run 或真实发卡 | 可选 | 是 | 真实发卡需要 | `scripts/card_send_live.py m3` -> `scripts/pre_meeting_live_test.py` | 用户要会前背景卡、RAG/Evidence Pack | 没有 `event-title`/`event-id` 时不要调用 |
| `post-meeting` | 触发 M4 妙记复盘和会后总结卡 | 用户提供妙记链接做会后复盘 | 可选 | 是 | 真实发卡需要 | `scripts/card_send_live.py m4` -> `scripts/post_meeting_live_test.py` | 用户要会后总结、行动项、开放问题、风险点 | 没有 `minute` 时不要调用；不要默认真实发卡 |
| `task-cards` | 基于妙记生成任务卡视角摘要 | 展示待办识别、任务卡数量 | 可选 | 是 | 真实发卡需要 | 复用 `post-meeting` / M4 链路 | 用户强调“任务卡”“待办”“按人分组” | 不要直接写 `pending_actions` 或任务表 |
| `risk-scan` | 触发 M5 风险巡检 | local 演示或真实飞书任务风险扫描 | 可选 | 是 | 真实发送风险卡需要 | `scripts/risk_scan_demo.py` | 用户要求风险扫描、逾期任务、风险卡 | `mode=enqueue` 但 worker 未运行时不要直接宣称已处理 |
| `eval` | 运行 Agent 轨迹评测 | 验证工具调用、安全边界、答辩质量 | 否 | 是 | 否 | `scripts/agent_eval_suite.py` via `core.console_api` | 用户要求评测、评分、回归验证 | 不应作为真实飞书联调成功证明 |
| `demo-replay` | 运行离线 E2E 回放 | 无飞书网络、无 token、答辩兜底 | 否 | 是 | 否 | `scripts/e2e_replay.py` | 用户需要离线演示或网络不可用降级 | 不应伪装成真实飞书发送成功 |
| `live sdk-callback` | 前台启动飞书 SDK 回调服务 | D3 四终端真实按钮联调终端 1 | 不直接发卡 | 否，前台长进程 | 不需要；可传 SDK 自身 `--agent-provider` | `.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py` | 用户要真实点击飞书卡片按钮联调 | SDK 环境缺失或已启动同类回调时不要重复启动 |
| `live worker` | 前台启动 workflow/risk/rag worker | D3 四终端真实按钮联调终端 2 | 处理队列任务，是否写入取决于任务 payload | 否，前台长进程 | 不直接使用 | `scripts/meetflow_worker.py` | `risk-scan --mode enqueue` 或按钮回调入队后 | 已有 worker 正在消费同队列时不要重复启动 |
| `live d3-card` | 重新发送 D3 会后总结卡 | D3 四终端真实按钮联调终端 3 | 是，除非加 `--dry-run` | 否；不加 `--dry-run` 会执行下游发卡 | 下游脚本内显式带写入开关 | `scripts/card_send_live.py m4` | 用户明确要重新发一张 D3 卡给测试群 | 没有测试群/default_chat_id 或用户只要预览时不要直接调用 |
| `live watch-callbacks` | 前台 tail 卡片回调和 workflow 事件日志 | D3 四终端真实按钮联调终端 4 | 否 | 不适用，前台 tail | 否 | `tail storage/card_callbacks.jsonl storage/workflow_events.jsonl` | 用户要观察三个按钮回调是否到达 | 日志文件路径不存在时应先说明可能暂无日志 |
| `service list` | 列出白名单后台服务状态 | Console/CLI 服务状态检查 | 否 | 是 | 否 | `core.service_manager.ServiceManager` | 用户问服务是否启动 | 不应用它执行非白名单服务 |
| `service logs <name>` | 查看白名单服务日志尾部 | 排查 worker / sdk_callback / m4_callback | 否 | 是 | 否 | `core.service_manager.ServiceManager.tail_logs()` | 用户问服务报错或回调无日志 | 不应用来读取任意文件 |
| `service stop <name>` | 停止由 service manager 启动的服务 | 结束后台 worker 或 callback | 否 | 是 | 否 | `core.service_manager.ServiceManager.stop_service()` | 用户明确要停止白名单服务 | 不应停止非本项目管理的进程 |
| `service start <name>` | 启动白名单后台服务 | Console 风格后台服务管理 | 否 | 不适用，会启动进程 | 否 | `core.service_manager.build_default_profiles()` | 需要后台托管 worker/sdk_callback/m4_callback 时 | D3 四终端手工联调优先使用 `live` 命令 |
| `openclaw-tools` | 输出 OpenClaw 工具清单 JSON | OpenClaw 注册工具前检查 | 否 | 是 | 否 | `config/openclaw_tools.example.json` | 用户要接入 OpenClaw 工具 | 不应把它当作执行具体业务流程 |

说明：

- 常规业务命令通过 `MeetFlowCLI` 输出标准 JSON。
- `live` 命令组当前是前台联调包装命令，会先打印“将执行：”再运行底层命令；它不是标准 JSON 输出。
- `openclaw_tools.example.json` 当前只注册 7 个工具：`meetflow_health`、`meetflow_pre_meeting`、`meetflow_post_meeting`、`meetflow_task_cards`、`meetflow_risk_scan`、`meetflow_eval`、`meetflow_demo_replay`，尚未注册 `live` 和 `service` 工具。

## 3. 标准调用格式

统一入口：

```bash
python3 scripts/meetflow_cli.py <command> [options]
```

AI / OpenClaw 调用要求：

- 优先消费 CLI 的 JSON 输出；
- 根据 `status` 判断成功失败；
- 根据 `workflow_type` 判断业务流程；
- 根据 `trace_id` 串联日志、报告和排查记录；
- 根据 `report_path` 打开 M3/M4/M5/eval/replay 报告；
- 根据 `agent_trace_path` 查 Agent 评测 trace 或报告；
- 根据 `safety_summary` 判断是否保持安全边界；
- 如果 `status=failed`，必须读取 `error`；若输出中包含 `suggested_fix`，必须同时读取并展示；
- 当前代码尚未稳定输出顶层 `suggested_fix` 字段，AI 应把 `error`、`data.stdout_tail`、服务日志和本文错误处理策略组合成修复建议；
- 不要只看 stdout 的自然语言描述。

标准 JSON 字段：

| 字段 | 含义 | AI / OpenClaw 使用方式 |
|---|---|---|
| `status` | `success` 或 `failed` | 第一判断条件，失败时不要继续宣称成功 |
| `workflow_type` | 业务流程类型，如 `pre_meeting_brief`、`post_meeting_followup`、`risk_scan` | 用于路由 UI、报告和后续动作 |
| `trace_id` | CLI 层 trace id | 用于串联日志和报告 |
| `dry_run` | 本次是否为 dry-run | 判断是否真的产生飞书副作用 |
| `allow_write` | 本次是否允许写入 | 写操作审计字段 |
| `report_path` | 报告路径 | 给用户打开报告或作为 OpenClaw artifact |
| `agent_trace_path` | Agent 评测 trace/report 路径 | eval 场景优先使用 |
| `command` | 实际下游白名单命令，已脱敏 | 用于复现，不应被用户任意改写后执行 |
| `data` | 结构化结果，如计数、job、stdout_tail | 提取业务摘要和排查信息 |
| `error` | 脱敏错误信息 | 失败时必须展示 |
| `safety_summary` | 安全摘要 | 检查 `secret_redacted`、`raw_shell_disabled`、`whitelist_entrypoint` 等 |

JSON 样例：

```json
{
  "status": "success",
  "workflow_type": "pre_meeting_brief",
  "trace_id": "cli_m3_177...",
  "dry_run": true,
  "allow_write": false,
  "report_path": "storage/reports/...",
  "agent_trace_path": "",
  "command": ["python3", "scripts/card_send_live.py", "m3", "..."],
  "data": {},
  "error": "",
  "safety_summary": {
    "policy_checked": true,
    "write_blocked_or_confirmed": true,
    "idempotency_key_present": true,
    "secret_redacted": true,
    "raw_shell_disabled": true,
    "whitelist_entrypoint": true
  }
}
```

## 4. AI 调用流程

### 4.1 健康检查流程

用户要求检查环境或演示前自检时：

1. 调用 `health`；
2. 检查 `data.feishu_config_present`；
3. 检查本地 OAuth token 状态。`health` 当前不直接验证 token 有效性，若真实飞书读写失败，应引导重新运行 OAuth；
4. 检查 `data.storage` 和 `data.migration`；
5. 检查 `data.services`；
6. 检查 `data.llm_provider` 和 `data.llm_model_configured`；
7. 如果失败，给出具体修复建议。

命令：

```bash
python3 scripts/meetflow_cli.py health
```

OAuth token 失效或缺失时：

```bash
python3 scripts/oauth_device_login.py
```

### 4.2 会前卡片流程

用户要求生成会前准备卡时：

1. 先运行 `health`；
2. 调用 `pre-meeting`；
3. 默认 dry-run；
4. 如果用户明确要求发送到飞书测试群，才允许加入 `--allow-write`；
5. 如果带 `--doc` / `--minute`，说明它们会进入会前 RAG / Evidence Pack；
6. 如果真实发卡，必须带 `--idempotency-suffix` 或使用 CLI 自动生成的幂等后缀。

Dry-run：

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

真实发卡到测试群配置：

```bash
python3 scripts/meetflow_cli.py pre-meeting \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --provider settings \
  --project-id meetflow \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/YGY5dOFrMoVu5Ox7DJnc7AaSnyb" \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --idempotency-suffix "m3-cli-live-20260512-01" \
  --allow-write \
  --write-report
```

### 4.3 会后总结流程

用户给出飞书妙记链接，要求会后复盘时：

1. 先运行 `health`；
2. 调用 `post-meeting`；
3. 默认 dry-run；
4. 如果要真实发卡，必须提供测试群 `chat-id`，或确认使用 `config/settings.local.json` 中的 `feishu.default_chat_id`；
5. 不要默认发送真实飞书卡片；
6. 从 JSON 的 `data` 和 `report_path` 返回摘要、关键结论、开放问题、行动项、风险点和报告路径；如果 JSON 只提供路径，应让用户查看报告文件。

Dry-run：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

真实发卡：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --identity user \
  --chat-id "<测试群 chat_id>" \
  --content-limit 300 \
  --related-top-n 5 \
  --allow-write
```

### 4.4 任务卡片流程

用户要求从妙记生成任务卡片时：

1. 调用 `task-cards`；
2. 默认 dry-run；
3. 说明该命令复用 M4 链路；
4. 说明它突出 `pending_action_count` 和 `action_item_count`；
5. 说明它不直接写 `pending_actions` 或任务表；
6. 真实发送任务卡必须显式 `--allow-write`。

Dry-run：

```bash
python3 scripts/meetflow_cli.py task-cards \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

真实发送：

```bash
python3 scripts/meetflow_cli.py task-cards \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --chat-id "<测试群 chat_id>" \
  --allow-write
```

### 4.5 风险巡检流程

用户要求风险扫描时：

1. 判断使用 `local` backend 还是 `feishu` backend；
2. 默认 dry-run；
3. 如果真实读取飞书任务并发送风险卡，必须显式 `--allow-write`；
4. 如果使用 `--mode enqueue`，必须确认 worker 正在运行；
5. 输出风险卡、报告路径、错误和建议动作。

本地 dry-run：

```bash
python3 scripts/meetflow_cli.py risk-scan \
  --backend local \
  --show-card
```

真实飞书任务巡检并发送风险卡：

```bash
python3 scripts/meetflow_cli.py risk-scan \
  --backend feishu \
  --identity user \
  --send-identity tenant \
  --chat-id "<测试群 chat_id>" \
  --completed false \
  --page-size 50 \
  --page-limit 20 \
  --allow-write \
  --show-card
```

只入队给 worker：

```bash
python3 scripts/meetflow_cli.py risk-scan \
  --backend feishu \
  --mode enqueue \
  --chat-id "<测试群 chat_id>" \
  --allow-write
```

入队前确认 worker：

```bash
python3 scripts/meetflow_cli.py live worker
```

### 4.6 D3 四终端真实联调流程

AI 如果需要指导用户复现“发送一张新的 D3 会后总结卡，然后点击三个按钮观察回调”，应按四个终端：

终端 1：

```bash
python3 scripts/meetflow_cli.py live sdk-callback
```

终端 2：

```bash
python3 scripts/meetflow_cli.py live worker
```

终端 3：

```bash
python3 scripts/meetflow_cli.py live d3-card \
  --minute "<minute>" \
  --show-card-json
```

终端 4：

```bash
python3 scripts/meetflow_cli.py live watch-callbacks
```

注意：

- SDK 回调和 M4 专用回调只启动一个；
- `live d3-card` 如果只想打印下游命令，需要加 `--dry-run`；
- 指定测试群时加 `--chat-id "<测试群 chat_id>" --receive-id-type chat_id`；
- 点击飞书卡片按钮后重点观察：
  - `view_pending_tasks_sent`
  - `start_risk_scan_sent`
  - `view_post_meeting_report_sent`
- 如果无日志，应优先检查 SDK 回调服务是否还在运行，以及飞书开放平台回调订阅是否指向当前应用。

### 4.7 评测流程

用户要求评测时：

1. 调用 `eval`；
2. 说明 `suite`、`provider`、`fail-under`、`write-report`；
3. 输出 `score`、`safety_score`、`passed_threshold`、`report_path`；
4. 不产生真实飞书写入。

命令：

```bash
python3 scripts/meetflow_cli.py eval \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

### 4.8 离线 Demo 回放流程

用户要求无网络演示或答辩兜底时：

1. 调用 `demo-replay`；
2. 推荐使用 `--all --fail-under 1.0 --write-report`；
3. 说明适用于无飞书网络、无 token 或答辩兜底；
4. 不产生真实飞书写入。

命令：

```bash
python3 scripts/meetflow_cli.py demo-replay \
  --all \
  --fail-under 1.0 \
  --write-report
```

## 5. OpenClaw 工具使用说明

OpenClaw 应先读取工具清单：

```bash
python3 scripts/meetflow_cli.py openclaw-tools
```

当前 `config/openclaw_tools.example.json` 可注册以下工具：

| 工具 | 用途 | 输入参数 | 推荐调用场景 | 是否允许写入 | 默认 dry-run | 输出字段 | 安全边界 |
|---|---|---|---|---|---|---|---|
| `meetflow_health` | 检查配置、存储、migration、服务状态 | 无 | 所有流程前置自检 | 否 | 是 | `status`、`workflow_type=health`、`data`、`safety_summary` | 不访问真实写接口 |
| `meetflow_pre_meeting` | 生成 M3 会前背景知识卡 | `date` 必填；可选 `event_title`、`event_id`、`provider`、`project_id`、`doc`、`minute`、`allow_write`、`idempotency_suffix` | 会前准备、RAG/Evidence Pack | 可选 | 是 | `report_path`、`data.parsed`、`command` | 真实发卡需 `allow_write=true` 和幂等后缀 |
| `meetflow_post_meeting` | 读取妙记生成 M4 会后总结卡和待确认任务卡 | `minute` 必填；可选 `chat_id`、`allow_write` | 会后复盘 | 可选 | 是 | `pending_action_count`、`action_item_count`、`report_path` | 真实发卡需测试群 |
| `meetflow_task_cards` | 基于妙记生成 D4 任务卡视角摘要 | `minute` 必填；可选 `allow_write` | 展示任务识别和任务卡 | 可选 | 是 | `pending_action_count`、`action_item_count` | 复用 M4，不直接写业务表 |
| `meetflow_risk_scan` | 执行 M5 风险巡检 | 可选 `backend`、`mode`、`chat_id`、`allow_write` | 风险扫描、风险卡 | 可选 | 是 | `risk_count`、`should_notify`、`job`、`report_path` | `feishu + allow_write` 才可真实发送 |
| `meetflow_eval` | 运行 Agent 轨迹评测 | 可选 `suite`、`case_id`、`fail_under`、`write_report` | 回归评测、安全评分 | 否 | 是 | `score`、`safety_score`、`passed_threshold`、`report_path` | 不代表真实飞书写入成功 |
| `meetflow_demo_replay` | 运行离线 E2E 回放 | 可选 `case`、`all`、`write_report` | 无网络/无 token 兜底 | 否 | 是 | `score`、`case_count`、`report_path` | 不伪造成真实联调 |

OpenClaw 不应直接拼接任意 shell 命令，而应只调用白名单 CLI 工具。`live` 和 `service` 当前未出现在
`openclaw_tools.example.json` 中；如果需要让 OpenClaw 管理长进程，应先扩展工具清单 schema 和权限策略。

## 6. 安全规则

AI 必须遵守：

- 默认 dry-run；
- 真实写入必须显式 `--allow-write`；
- 真实写入只允许测试群；
- 发送飞书卡片前必须确认 `chat-id` 或 `feishu.default_chat_id`；
- 不允许自动创建真实飞书任务，除非用户明确授权且字段完整；
- 不允许绕过 `AgentPolicy`；
- 不允许绕过幂等策略；
- 不允许直接调用 `FeishuClient.send_*` 或 `FeishuClient.create_*`；
- 不允许直接写业务 SQLite 表伪造结果；
- 不允许提供任意 shell 命令或 Python 表达式入口；
- 不允许输出 token、secret、refresh token、API key、Authorization Bearer；
- 检测到 `config/settings.local.json` 或 `config/llm_providers.local.json` 时，要提醒不要提交；
- OAuth token 失效时，引导运行 `python3 scripts/oauth_device_login.py`；
- 飞书 SDK 或 OAuth 不可用时，降级到 `demo-replay` 或脱敏样例；
- `live d3-card` 是真实联调命令，不加 `--dry-run` 会执行下游发卡链路，必须先确认测试群。

## 7. 错误处理策略

| 错误 | 现象 | 可能原因 | 建议命令 | 可否降级 demo-replay |
|---|---|---|---|---|
| `feishu_config_present=false` | `health` 显示飞书配置不存在 | `config/settings.local.json` 缺少 app_id/app_secret | 补齐本地配置后运行 `python3 scripts/meetflow_cli.py health` | 可以 |
| OAuth token 失效 | 真实读日历、文档、妙记失败，提示 user token 不可用 | token 过期、refresh 失败、scope 不足 | `python3 scripts/oauth_device_login.py` | 可以 |
| 后端服务未启动 | Console 页面无法访问 API | `meetflow_console_server.py` 未运行 | 使用 CLI 直接跑流程，或启动 Console server | 可以 |
| SDK 回调服务未启动 | 点击飞书卡片无回调日志 | 终端 1 未运行或进程退出 | `python3 scripts/meetflow_cli.py live sdk-callback` | 部分可以 |
| worker 未启动 | `mode enqueue` 后没有后续处理 | worker 未消费 `workflow,risk_scan,rag_refresh` | `python3 scripts/meetflow_cli.py live worker` | 可以 |
| 飞书开放平台回调订阅未配置 | SDK 运行但点击无日志 | 订阅未指向当前应用或事件未启用 | 检查开放平台回调订阅和应用配置 | 部分可以 |
| LLM provider 不可用 | M3/M4 生成失败或 provider 报错 | `settings` 指向的模型配置缺失或 API 不可用 | 改用 `--provider scripted_debug` 或检查 `config/llm_providers.local.json` | 可以 |
| storage 或 migration 异常 | `health` 的 migration verify 失败 | SQLite 缺失、迁移未跑、文件权限问题 | `python3 scripts/storage_migrate.py --status` 与 `python3 scripts/storage_migrate.py --verify` | 可以 |
| 妙记链接无权限 | M4 读取失败 | 当前用户无妙记权限或 scope 不足 | 重新 OAuth，确认妙记对当前用户可访问 | 可以 |
| `chat-id` 缺失 | 真实发卡失败或发送到默认群不确定 | 未传 `--chat-id` 且 default_chat_id 未配置 | 加 `--chat-id "<测试群 chat_id>"`，或确认 `settings.local.json` | 不影响 dry-run |
| `allow-write` 未开启 | 命令只打印或 `dry_run=true` | 默认安全门禁生效 | 用户明确授权后加 `--allow-write` | 不需要 |
| `mode enqueue` 但 worker 未运行 | 有 job 但无处理结果 | 后台 worker 未启动 | `python3 scripts/meetflow_cli.py live worker` | 可以 |
| 幂等键重复 | 重复发卡或提醒被跳过 | 使用了相同 `idempotency_suffix` 或 risk dedupe | 更换测试用幂等后缀，确认不是误重复 | 可以 |
| 真实飞书网络不可用 | 飞书 API 请求超时或网络错误 | 网络、代理、飞书服务、沙箱限制 | 先跑 dry-run / `demo-replay`，网络恢复后再真实联调 | 可以 |

## 8. 示例用户请求与 AI 调用方案

### 示例 1：演示前健康检查

- 用户请求：帮我检查 MeetFlow 现在能不能演示。
- AI 判断：先做无副作用自检。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py health
```

- dry-run：是。
- 需要 `--allow-write`：否。
- 预期输出：`status=success`，`workflow_type=health`，`data.feishu_config_present`、`migration`、`services`。
- 失败处理：根据 `error` 和 `data.migration` 修配置或 migration；token 问题运行 OAuth；可降级 `demo-replay`。

### 示例 2：生成会前卡片

- 用户请求：根据这个飞书文档和妙记生成今天的会前背景卡。
- AI 判断：先 health，再 M3 dry-run；用户明确发测试群后再写入。
- 应调用命令：

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

- dry-run：是。
- 需要 `--allow-write`：真实发卡才需要。
- 预期输出：`workflow_type=pre_meeting_brief`，`report_path` 或 `data.parsed.report_json`。
- 失败处理：检查 event title/date、OAuth、文档权限、LLM provider；可降级 scripted_debug。

### 示例 3：根据飞书妙记生成会后总结

- 用户请求：用这个妙记生成会后复盘卡。
- AI 判断：默认 M4 dry-run，不默认发飞书卡。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

- dry-run：是。
- 需要 `--allow-write`：真实发测试群才需要。
- 预期输出：`workflow_type=post_meeting_followup`、`pending_action_count`、`action_item_count`、`report_path`。
- 失败处理：检查妙记权限、OAuth scope、`chat-id`；可降级离线 demo。

### 示例 4：根据妙记生成任务卡片

- 用户请求：从妙记里抽取任务卡，看看有多少待办。
- AI 判断：调用 `task-cards`，复用 M4 链路，不直接写表。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py task-cards \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

- dry-run：是。
- 需要 `--allow-write`：真实发送任务卡才需要。
- 预期输出：`workflow_type=task_cards`，`pending_action_count`，`action_item_count`。
- 失败处理：同 M4；不要伪造 `pending_actions`。

### 示例 5：执行风险巡检

- 用户请求：跑一下风险巡检，先看卡片效果。
- AI 判断：先用 local backend dry-run。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py risk-scan \
  --backend local \
  --show-card
```

- dry-run：是。
- 需要 `--allow-write`：真实飞书任务巡检并发卡才需要。
- 预期输出：`workflow_type=risk_scan`，`risk_count`，`should_notify`，`report_path`。
- 失败处理：feishu backend 失败时检查 OAuth、任务权限、chat-id；可降级 local/demo-replay。

### 示例 6：运行离线 demo-replay

- 用户请求：现在没有飞书网络，给我跑一个答辩兜底演示。
- AI 判断：调用离线回放。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py demo-replay \
  --all \
  --fail-under 1.0 \
  --write-report
```

- dry-run：是。
- 需要 `--allow-write`：否。
- 预期输出：`workflow_type=demo_replay`、`score`、`case_count`、`report_path`。
- 失败处理：查看 `error` 和 replay stdout；不宣称真实飞书成功。

### 示例 7：D3 四终端真实联调

- 用户请求：重新做真实飞书点击联调，给我四个终端命令。
- AI 判断：启动 SDK 回调、worker、发送 D3 卡、tail 日志。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py live sdk-callback
python3 scripts/meetflow_cli.py live worker
python3 scripts/meetflow_cli.py live d3-card --minute "obcngy8e7x2883b6f9f5x4l9" --show-card-json
python3 scripts/meetflow_cli.py live watch-callbacks
```

- dry-run：前两个是长进程；`d3-card` 默认真实发卡，加 `--dry-run` 才只打印命令。
- 需要 `--allow-write`：`live d3-card` 不暴露该参数，下游 `card_send_live.py m4` 包装真实发卡链路。
- 预期输出：点击后日志出现 `view_pending_tasks_sent`、`start_risk_scan_sent`、`view_post_meeting_report_sent`。
- 失败处理：检查 SDK 回调、开放平台订阅、worker、测试群、妙记权限。

### 示例 8：输出 OpenClaw 工具清单

- 用户请求：给 OpenClaw 注册 MeetFlow 工具。
- AI 判断：输出当前工具清单。
- 应调用命令：

```bash
python3 scripts/meetflow_cli.py openclaw-tools
```

- dry-run：是。
- 需要 `--allow-write`：否。
- 预期输出：包含 `meetflow_health`、`meetflow_pre_meeting`、`meetflow_post_meeting`、`meetflow_task_cards`、`meetflow_risk_scan`、`meetflow_eval`、`meetflow_demo_replay`。
- 失败处理：检查 `config/openclaw_tools.example.json` 是否有效；缺失时代码有最小默认清单。

## 9. 已实现能力与建议增强项

| 能力 | 已有 CLI 命令 | 依赖脚本/模块 | 支持 dry-run | 支持 allow-write | 适合 OpenClaw 调用 | 仍需增强的点 |
|---|---|---|---|---|---|---|
| 环境健康检查 | `health` | `core.cli_facade`、`core.console_api` | 是 | 不需要 | 是 | 增加 OAuth token 有效性显式检查 |
| M3 会前卡片 | `pre-meeting` | `card_send_live.py m3` | 是 | 是 | 是 | 输出更稳定的卡片摘要字段 |
| M4 会后总结 | `post-meeting` | `card_send_live.py m4` | 是 | 是 | 是 | JSON 中补充结论、开放问题、风险点结构 |
| D4 任务卡视角 | `task-cards` | M4 链路 | 是 | 是 | 是 | 输出更详细的 per-owner 任务结构 |
| M5 风险巡检 | `risk-scan` | `risk_scan_demo.py` | 是 | 是 | 是 | 输出更完整的 risk evidence |
| Agent 评测 | `eval` | `agent_eval_suite.py` | 是 | 不需要 | 是 | 输出更适合 Console 展示的摘要 |
| 离线回放 | `demo-replay` | `e2e_replay.py` | 是 | 不需要 | 是 | 增加完整演示 summary |
| D3 SDK 回调 | `live sdk-callback` | `feishu_event_sdk_server.py` | 不适用 | 不直接写 | 暂不建议作为 OpenClaw 工具 | 需要长进程管理 schema |
| D3 worker | `live worker` | `meetflow_worker.py` | 不适用 | 不直接写 | 暂不建议作为 OpenClaw 工具 | 需要队列状态和健康探针输出 |
| D3 发卡 | `live d3-card` | `card_send_live.py m4` | 仅显式 `--dry-run` | 下游真实发卡 | 暂不建议作为 OpenClaw 工具 | 增加标准 JSON 和显式 `--allow-write` 口径 |
| D3 日志观察 | `live watch-callbacks` | `tail` 固定日志 | 不适用 | 不需要 | 暂不建议作为 OpenClaw 工具 | 增加结构化日志查询命令 |
| 服务管理 | `service list/logs/stop/start` | `core.service_manager` | 不适用 | 不直接写飞书 | 可作为受控内部工具 | openclaw-tools 增加更明确的 schema |
| 工具清单 | `openclaw-tools` | `openclaw_tools.example.json` | 是 | 不需要 | 是 | openclaw-tools 增加更明确的 schema |
| 报告串联 | 多命令 `report_path` | `core.cli_facade` | 是 | 视命令而定 | 是 | 将 Agent Trace 和 `report_path` 更稳定地串联到 Console |
| 标准 JSON | 常规命令已支持 | `CLIResult` | 是 | 视命令而定 | 是 | CLI 增加更稳定的 `--json` 参数；`live` 命令结构化输出 |
