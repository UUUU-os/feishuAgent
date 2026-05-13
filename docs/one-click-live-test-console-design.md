# MeetFlow 一键真实联调控制台设计方案

本文档描述如何把 `docs/overall-test-commands.md` 中分散在多个终端里的真实联调命令，收敛到 MeetFlow Console 前端按钮和后端 API 编排中。目标不是让浏览器直接执行任意 shell 命令，而是把已有脚本、后台队列、SDK 回调、Worker、飞书真实读写和报告查询包装成安全、可审计、可恢复的一键操作。

## 1. 背景与目标

当前完整测试 MeetFlow 时，通常需要分别启动：

- 前端 Vite 服务
- Console API 后端
- 飞书 SDK 回调服务
- HTTP fallback 回调服务
- Worker 长期任务消费
- Daemon 长期入队
- 一次性真实联调脚本和 SQLite 排查命令

这种方式适合开发排查，但不适合演示、验收和反复真实联调。期望效果是：

```text
启动一个 MeetFlow Console 后端
打开浏览器
填写必要业务参数，例如飞书妙记链接、会议标题、chat_id
点击按钮触发 M3/M4/M5 真实群聊链路
在前端查看服务状态、job 状态、报告路径、stdout/stderr 摘要和失败原因
```

第一阶段目标：

- 保留现有 `scripts/*.py` 真实联调入口，不重写业务主链路。
- 前端新增“一键真实联调”页面，覆盖 M3 会前卡片、M4 会后总结、待确认任务卡、M5 任务风险提醒。
- 后端新增安全 API facade，只允许调用白名单脚本和白名单长期服务。
- 真实写入飞书前必须显式 `allow_write`，并在前端二次确认。
- 所有命令输出必须脱敏后返回前端。
- 长期进程由后端管理 PID、日志和状态，不再要求用户手动打开多个终端。

非目标：

- 不做多用户权限系统。
- 不在浏览器中保存或展示 access token、refresh token、app secret、API key。
- 不允许前端传入任意 shell 命令。
- 不绕过 `AgentPolicy`、`ToolRegistry`、`FeishuClient` 或现有 workflow 入口直接执行外部副作用。

## 2. 总体架构

建议沿用现有 Console 架构，在 `core/console_api.py` 和 `scripts/meetflow_console_server.py` 上扩展能力：

```text
Browser
  -> frontend MeetFlow Console
  -> scripts/meetflow_console_server.py
  -> core/console_api.py
       -> ServiceManager
       -> JobQueue / SQLite
       -> scripts/card_send_live.py
       -> scripts/risk_scan_demo.py
       -> scripts/meetflow_worker.py
       -> scripts/feishu_event_sdk_server.py
       -> scripts/feishu_event_server.py
       -> storage/reports/**
       -> storage/runtime/logs/**
```

核心原则：

- 前端只调用 HTTP API，不直接执行命令。
- 后端 API 只接受结构化参数，转换为固定脚本的固定参数。
- 同步短任务使用 `subprocess.run(timeout=...)`。
- 长期服务使用 `subprocess.Popen`，由 `ServiceManager` 记录 PID 和日志。
- 可入队的任务优先写 `workflow_jobs`，由 Worker 消费。
- 所有真实写操作必须复用现有脚本里的 `allow-write`、`send-card`、幂等和 policy 链路。

## 3. 前端页面设计

新增页面：`真实联调`

建议文件：

```text
frontend/src/pages/LiveFlowPage.tsx
```

导航增加：

```text
真实联调：M3/M4/M5 一键真实飞书群链路
```

### 3.1 服务控制区

目标：替代长期占用的终端。

服务列表：

- Console API：当前服务自身，只展示状态。
- SDK 回调服务：`scripts/feishu_event_sdk_server.py`
- HTTP fallback：`scripts/feishu_event_server.py`
- Worker：`scripts/meetflow_worker.py`
- Daemon：`scripts/meetflow_daemon.py`
- M4 按钮回调：`scripts/card_send_live.py m4-callback`

每个服务展示：

- 服务名
- 状态：running / stopped / unknown / failed
- PID
- 启动时间
- 运行时长
- 监听端口或队列
- 最近日志尾部
- 启动命令摘要

按钮：

- 启动
- 停止
- 重启
- 查看日志
- 刷新状态

第一阶段建议默认只开放：

- SDK 回调服务启动 / 停止
- Worker 启动 / 停止
- M4 按钮回调启动 / 停止
- Worker dry-run

HTTP fallback 和 daemon 可以先展示命令，第二阶段再加入进程管理。

### 3.2 M3 会前卡片区

复用现有 `M3ConsolePage` 的设计，补齐真实联调常用字段。

输入项：

- 日期窗口：today / tomorrow / YYYY-MM-DD
- 会议标题
- event_id
- project_id
- llm_provider：默认 `scripted_debug`
- doc URL 列表
- minute URL 列表
- force_index
- write_report
- idempotency_suffix
- allow_write

按钮：

- M3 dry-run
- 真实发送会前卡片

后端映射：

```bash
scripts/card_send_live.py m3
```

展示结果：

- returncode
- dry_run
- trace_id
- workflow_type
- status
- report_json / report_markdown
- stdout tail
- 错误提示和排查建议

业务注意：

- 在 2026-05-06 执行 `tomorrow` 时，查询窗口是 2026-05-07 本地整天。
- 找不到会议时，前端提示用户检查飞书日历中是否存在对应日期和标题的测试会议。

### 3.3 M4 会后总结区

目标：把妙记读取、会后总结卡、待确认任务卡和按钮确认闭环做成可视化操作。

输入项：

- 飞书妙记 URL 或 minute token
- chat_id，可选；不填使用 `config/settings.local.json` 中的 `feishu.default_chat_id`
- identity：默认 `user`
- receive_id_type：默认 `chat_id`
- content_limit
- related_top_n
- skip_related_knowledge
- show_card_json
- allow_write

按钮：

- 只读解析妙记
- M4 dry-run
- 真实发送会后总结卡和待确认任务卡
- 启动 M4 按钮回调服务
- 刷新待确认任务状态

后端映射：

```bash
scripts/post_meeting_live_test.py --minute ... --read-only
scripts/card_send_live.py m4 --minute ...
scripts/card_send_live.py m4-callback
```

展示结果：

- 妙记标题、meeting_id、minute_token
- 决策项数量
- open questions 数量
- action items 数量
- pending action items 数量
- 会后总结卡发送状态
- 待确认任务卡发送状态
- review_session_id
- pending / created / rejected 数量
- task_mappings 最新记录
- report path
- stdout tail

### 3.4 M5 任务风险提醒区

目标：把任务风险扫描、风险卡生成、提醒发送和降噪状态集中在前端。

输入项：

- backend：local / feishu
- mode：直接执行 / 只入队
- chat_id，可选
- identity：默认 `user`
- send_identity：默认 `tenant`
- completed：false / true / all
- page_size
- page_limit
- stale_update_days
- due_soon_hours
- max_reminders
- show_card
- allow_write

按钮：

- M5 local dry-run
- M5 feishu dry-run
- 入队任务风险提醒
- 真实发送风险提醒卡
- 手动消费 risk_scan 队列一次
- 查看风险提醒历史

后端映射：

```bash
scripts/risk_scan_demo.py --backend local --show-card
scripts/risk_scan_demo.py --backend feishu --show-card
scripts/risk_scan_demo.py --backend feishu --show-card --allow-write --identity user --send-identity tenant
scripts/risk_scan_demo.py --backend feishu --show-card --allow-write --enqueue
scripts/meetflow_worker.py --queues risk_scan --once
```

展示结果：

- scan_result
- decision.should_notify
- decision.reason
- idempotency_key
- risks 列表
- suppressed_until
- risk_notifications 最新记录
- stdout tail

## 4. 后端 API 设计

### 4.1 服务管理 API

```text
GET  /api/services
POST /api/services/start
POST /api/services/stop
POST /api/services/restart
GET  /api/services/logs?name=worker&tail=200
```

启动请求：

```json
{
  "name": "worker",
  "profile": "default",
  "dry_run": false
}
```

服务名白名单：

```text
sdk_callback
http_fallback
worker
daemon
m4_callback
```

每个服务对应固定命令模板，前端不能覆盖命令主体。

### 4.2 M4 API

```text
POST /api/m4/read-minute
POST /api/m4/send-cards
GET  /api/m4/review-sessions?limit=20
GET  /api/m4/task-mappings?limit=20
```

`/api/m4/send-cards` 请求：

```json
{
  "minute": "https://xxx.feishu.cn/minutes/xxx",
  "identity": "user",
  "chat_id": "",
  "receive_id_type": "chat_id",
  "content_limit": 300,
  "related_top_n": 5,
  "skip_related_knowledge": false,
  "show_card_json": false,
  "allow_write": false,
  "timeout_seconds": 180
}
```

当 `allow_write=false` 时，只执行 dry-run 或 read-only，不发送飞书卡片。

### 4.3 M5 API

```text
POST /api/m5/risk-scan
GET  /api/m5/risk-notifications?limit=20
```

请求：

```json
{
  "backend": "feishu",
  "mode": "direct",
  "chat_id": "",
  "identity": "user",
  "send_identity": "tenant",
  "completed": "false",
  "page_size": 50,
  "page_limit": 20,
  "stale_update_days": 0,
  "due_soon_hours": 0,
  "max_reminders": 0,
  "show_card": true,
  "allow_write": false,
  "timeout_seconds": 180
}
```

`mode=enqueue` 时只写入 `workflow_jobs`，不直接执行飞书读写。

### 4.4 通用命令执行结果

所有脚本类 API 返回统一结构：

```json
{
  "ok": true,
  "returncode": 0,
  "dry_run": true,
  "command": ["python", "scripts/card_send_live.py", "m4", "..."],
  "stdout": "...",
  "stderr": "",
  "parsed": {},
  "report_path": "",
  "job": {}
}
```

注意：`command` 只用于展示，必须经过脱敏。

## 5. ServiceManager 设计

新增模块：

```text
core/service_manager.py
```

职责：

- 管理本地长期服务进程。
- 使用固定 profile 生成命令。
- 启动服务时写日志文件。
- 停止服务时只杀对应 PID。
- 检查 PID 是否仍存在。
- 返回服务状态给前端。

运行状态文件：

```text
storage/runtime/services.json
storage/runtime/logs/sdk_callback.log
storage/runtime/logs/worker.log
storage/runtime/logs/m4_callback.log
```

状态结构：

```json
{
  "worker": {
    "name": "worker",
    "status": "running",
    "pid": 12345,
    "started_at": 1778054400,
    "command": ["python", "scripts/meetflow_worker.py", "--queues", "workflow,risk_scan,rag_refresh"],
    "log_path": "storage/runtime/logs/worker.log"
  }
}
```

命令 profile 示例：

```text
worker.default
  /home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --queues workflow,risk_scan,rag_refresh --poll-seconds 2

sdk_callback.enqueue
  .venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --enqueue-agent --agent-provider dry-run --job-queue workflow --log-level info

m4_callback.default
  /home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4-callback --log-level info
```

## 6. 安全与权限设计

必须保留的安全边界：

- 前端不能直接传 shell 命令。
- 后端必须对白名单参数做校验。
- 真实写操作必须显式 `allow_write=true`。
- 前端真实写操作必须二次确认。
- M3/M4/M5 写入必须继续走现有脚本和 `AgentPolicy`。
- 命令输出必须调用脱敏函数，隐藏 token、secret、API key、Authorization。
- 配置检查只能展示字段是否存在、provider、模型名、过期时间等非敏感信息。
- 默认发送到测试群，不默认发送生产群。

建议前端对真实写操作展示确认内容：

```text
即将真实写入飞书：
- 流程：M4 会后总结
- 接收群：oc_xxx 或默认测试群
- 妙记：xxx
- 写操作：发送总结卡、发送待确认任务卡
- Provider：scripted_debug
```

用户确认后再调用 API。

## 7. 数据展示设计

### 7.1 SQLite 查询

新增或扩展 Console API 查询：

```text
GET /api/jobs
GET /api/m4/review-sessions
GET /api/m4/pending-actions
GET /api/m4/task-mappings
GET /api/m5/risk-notifications
GET /api/migrations/status
```

重点展示字段：

- `workflow_jobs.status`
- `workflow_jobs.last_error`
- `pending_actions.status`
- `review_sessions.status`
- `task_mappings.task_id`
- `risk_notifications.status`
- `risk_notifications.suppressed_until`

### 7.2 报告读取

已有：

```text
GET /api/reports/latest?type=evaluation|m3|m4
```

建议扩展：

```text
GET /api/reports/latest?type=m5
GET /api/reports/file?path=...
```

`/api/reports/file` 必须限制只能读取 `storage/reports/**` 下文件，不能读任意路径。

## 8. 实施步骤

### 阶段 1：后端基础能力

新增：

- `core/service_manager.py`
- `ServiceStatus`、`ServiceStartRequest`
- `MeetFlowConsoleAPI.list_services()`
- `MeetFlowConsoleAPI.start_service()`
- `MeetFlowConsoleAPI.stop_service()`
- `MeetFlowConsoleAPI.tail_service_logs()`

扩展：

- `scripts/meetflow_console_server.py` 增加 `/api/services*` 路由。
- `tests/test_console_api.py` 增加服务命令构造和状态文件测试。

### 阶段 2：M4/M5 API

新增：

- `M4SendCardsRequest`
- `M5RiskScanRequest`
- `run_m4_read_minute()`
- `run_m4_send_cards()`
- `run_m5_risk_scan()`
- `list_review_sessions()`
- `list_task_mappings()`
- `list_risk_notifications()`

扩展：

- `scripts/meetflow_console_server.py` 增加 `/api/m4/*` 和 `/api/m5/*`。
- `tests/test_console_api.py` 覆盖 dry-run、参数校验和 allow_write 门禁。

### 阶段 3：前端页面

新增：

- `frontend/src/pages/LiveFlowPage.tsx`
- `frontend/src/components/ServiceControlPanel.tsx`
- `frontend/src/components/CommandResultPanel.tsx`

扩展：

- `frontend/src/App.tsx` 增加导航。
- `frontend/src/api/types.ts` 增加 M4/M5/service 类型。
- `frontend/src/api/client.ts` 增加 API 方法。
- `frontend/src/styles/app.css` 增加服务状态、日志面板、流程表单样式。

### 阶段 4：文档同步

更新：

- `docs/overall-test-commands.md`：补充“前端一键联调入口”和仍需命令行排查的场景。
- `docs/frontend-system-design.md`：补充 LiveFlow 页面。
- `tasks.md`：记录新增文件、核心函数、验证命令和结果。

## 9. 验收标准

基础验收：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py

/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api

cd frontend
npm run build
```

前端验收：

- 打开 Console 后能看到 `真实联调` 页面。
- 能看到 Worker / SDK callback / M4 callback 的状态。
- 点击 Worker dry-run 后能显示 stdout。
- M3 dry-run 能返回命令和结果。
- M4 输入妙记链接后能 read-only 解析。
- M5 local dry-run 能展示风险卡 JSON 或 stdout 摘要。

真实飞书验收：

- M3 勾选真实写入后二次确认，测试群收到会前卡片。
- M4 输入妙记链接后二次确认，测试群收到会后总结卡和待确认任务卡。
- 启动 M4 callback 后，在飞书群点击确认创建，前端能看到 review session / task mapping 状态变化。
- M5 feishu 真实巡检后二次确认，测试群收到风险提醒卡；重复发送受降噪和幂等约束影响。

失败验收：

- 缺少 `chat_id` 时，M4/M5 给出明确错误。
- OAuth 失效时，前端展示“需要重新授权”，不展示 token。
- SDK 环境缺失时，服务状态显示失败，并提示运行 `scripts/setup_lark_oapi_venv.py`。
- Worker 未启动时，入队任务仍可见，状态保持 pending。

## 10. 风险与取舍

### 10.1 同步执行脚本可能超时

M3/M4/M5 真实飞书链路可能因为网络、LLM、RAG 或飞书接口耗时较长。

处理：

- 第一阶段同步按钮保留 `timeout_seconds`。
- 第二阶段把 M3/M4/M5 都支持 `enqueue`，前端轮询 `workflow_jobs`。

### 10.2 长期进程管理需要避免误杀

后端只能停止由 `ServiceManager` 启动并记录的 PID。

处理：

- 状态文件记录 PID、命令摘要、启动时间。
- 停止前检查 PID 进程仍匹配预期命令片段。
- 不提供任意 PID kill。

### 10.3 真实写入需要强提示

M3/M4/M5 都可能向真实飞书群发送消息或创建任务。

处理：

- 所有真实写入按钮使用危险色。
- 所有真实写入必须二次确认。
- 默认 provider 使用 `scripted_debug`。
- 默认群使用配置中的测试群。

## 11. 推荐最终使用方式

开发期：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787

cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

演示或验收期：

```bash
cd frontend
npm run build

cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

浏览器访问：

```text
http://127.0.0.1:8787
```

此时用户只需要在前端填写：

- M3：会议标题 / event_id / 日期
- M4：飞书妙记链接
- M5：是否真实读取飞书任务、是否真实发送风险卡
- 必要时填写测试群 `chat_id`

其余命令由 Console 后端按白名单统一触发、记录和展示。
