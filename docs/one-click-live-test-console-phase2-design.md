# MeetFlow 一键真实联调控制台第二阶段设计方案

本文档描述 MeetFlow Console 一键真实联调的第二阶段建设方案。第一阶段已经完成服务控制、M4/M5 前端触发、M4/M5 真实写入二次确认、命令结果展示和基础运行表查询。第二阶段的目标是把“能点按钮跑脚本”升级为“能稳定编排完整真实飞书群闭环，并能解释每一步状态”。

## 1. 第二阶段目标

第二阶段重点解决四个问题：

```text
1. 长耗时真实链路不应卡住浏览器请求
2. M3 -> M4 -> M5 演示需要有明确步骤编排和状态推进
3. M4 待确认任务、M5 风险提醒不能只展示 SQLite 原始行
4. 真实飞书联调前需要清楚知道配置、OAuth、SDK、Worker 是否可用
```

第二阶段交付后，理想使用方式是：

```text
打开真实联调页面
点击“完整演示模式”
填写会议标题 / event_id、飞书妙记链接、测试群 chat_id
逐步执行 M3 会前卡片 -> M4 会后总结和任务确认 -> 群内点击确认 -> M5 风险巡检
每一步都能看到 job_id、状态、报告、失败原因和下一步操作
```

## 2. 范围与非目标

### 2.1 必做范围

- M3/M4/M5 支持异步入队执行。
- 前端支持 job 轮询和步骤状态展示。
- 新增 `完整演示模式` 页面或面板。
- M4 待确认任务状态做业务化展示。
- M5 风险提醒状态做业务化展示。
- 新增飞书授权、默认群、SDK 环境、Worker 状态的健康检查。
- 报告和 stdout 解析更结构化，减少用户读终端日志的负担。

### 2.2 暂缓范围

- 多用户权限系统。
- 线上部署与公网访问。
- 在前端直接编辑飞书任务。
- 在前端保存或展示 token。
- 复杂图表大屏。

## 3. 总体架构升级

第一阶段：

```text
Frontend button
  -> Console API
  -> subprocess.run(script)
  -> stdout / parsed result
```

第二阶段：

```text
Frontend demo step
  -> Console API enqueue
  -> workflow_jobs
  -> Worker
  -> existing scripts / Agent / FeishuClient
  -> workflow_jobs.result_json
  -> reports / SQLite business tables
  -> Frontend polling and business status cards
```

同步执行仍保留，用于 dry-run、小命令和排查；真实飞书链路优先走 job queue。

## 4. 后端设计

### 4.1 新增异步入队 API

建议新增：

```text
POST /api/m3/enqueue
POST /api/m4/enqueue
POST /api/m5/enqueue
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/result
```

也可以复用现有 `/api/m5/risk-scan` 的 `mode=enqueue`，但为了前端语义清晰，建议统一提供 `enqueue` API。

请求结构示例：

```json
{
  "workflow": "m4",
  "minute": "https://xxx.feishu.cn/minutes/xxx",
  "chat_id": "oc_xxx",
  "allow_write": true,
  "show_card_json": false,
  "idempotency_suffix": "m4-demo-20260506"
}
```

返回：

```json
{
  "job_id": "job_xxx",
  "queue_name": "workflow",
  "job_type": "post_meeting.send_cards",
  "status": "pending",
  "idempotency_key": "m4:minute:xxx"
}
```

### 4.2 Job Payload 规范

M3：

```json
{
  "date": "tomorrow",
  "event_title": "MeetFlow 测试会议",
  "event_id": "",
  "project_id": "meetflow",
  "llm_provider": "scripted_debug",
  "write_report": true,
  "force_index": false,
  "allow_write": true,
  "idempotency_suffix": "m3-demo-20260506"
}
```

对应：

```text
queue_name = workflow
job_type = pre_meeting.send_card
```

M4：

```json
{
  "minute": "https://xxx.feishu.cn/minutes/xxx",
  "identity": "user",
  "chat_id": "oc_xxx",
  "show_card_json": false,
  "skip_related_knowledge": false,
  "allow_write": true
}
```

对应：

```text
queue_name = workflow
job_type = post_meeting.send_cards
```

M5：

```json
{
  "backend": "feishu",
  "chat_id": "oc_xxx",
  "identity": "user",
  "send_identity": "tenant",
  "completed": "false",
  "show_card": true,
  "allow_write": true
}
```

对应：

```text
queue_name = risk_scan
job_type = risk_scan.run
```

### 4.3 Job Result 解析

扩展 Worker 的 `result_json`，统一写入：

```json
{
  "returncode": 0,
  "stdout_tail": "...",
  "stderr_tail": "",
  "report_path": "storage/reports/m4/button_flow/xxx.md",
  "trace_id": "xxx",
  "workflow_type": "post_meeting_followup",
  "feishu_message_id": "om_xxx",
  "duration_ms": 1234
}
```

M3/M4/M5 脚本 stdout 的解析逻辑应逐步从前端专用解析，下沉到后端通用函数：

```text
parse_m3_stdout()
parse_m4_stdout()
parse_m5_stdout()
parse_worker_result()
```

### 4.4 演示会话 Demo Session

建议新增轻量演示会话概念，保存完整演示上下文：

```text
demo_sessions
```

字段建议：

```text
demo_session_id
status
meeting_title
event_id
minute
chat_id
m3_job_id
m4_job_id
m5_job_id
review_session_id
task_id
created_at
updated_at
last_error
```

如果不想新增 migration，第一版可以先存到：

```text
storage/runtime/demo_sessions.json
```

但长期建议进入 SQLite，方便审计和恢复。

### 4.5 健康检查 API

新增：

```text
GET /api/live/health
```

返回：

```json
{
  "console_api": {"ok": true},
  "storage": {"ok": true, "db_exists": true, "migration_ok": true},
  "feishu_config": {
    "app_id_present": true,
    "app_secret_present": true,
    "default_chat_id_present": true
  },
  "oauth": {
    "user_access_token_present": true,
    "user_access_token_expired": false,
    "refresh_token_present": true
  },
  "sdk": {
    "venv_python_exists": true,
    "lark_oapi_import_ok": true
  },
  "services": {
    "worker_running": true,
    "sdk_callback_running": false,
    "m4_callback_running": true
  }
}
```

注意：

- 不返回完整 token。
- 不返回 app_secret。
- 只返回是否存在、是否过期、错误摘要。

## 5. 前端设计

### 5.1 新增完整演示模式

在 `真实联调` 页面新增一个 `完整演示模式` 区域，也可拆成独立页面：

```text
LiveDemoPage.tsx
```

推荐第一版直接放在 `LiveFlowPage.tsx` 顶部，减少路由复杂度。

页面步骤：

```text
Step 0：健康检查
Step 1：启动 Worker / 回调服务
Step 2：M3 发送会前卡片
Step 3：M4 发送会后总结和待确认任务卡
Step 4：等待群内确认任务
Step 5：M5 运行风险巡检
Step 6：验收摘要
```

每一步状态：

```text
idle
ready
running
waiting_user
succeeded
failed
skipped
```

### 5.2 Demo Step UI

新增组件：

```text
frontend/src/components/DemoStepTimeline.tsx
frontend/src/components/JobStatusCard.tsx
frontend/src/components/LiveHealthPanel.tsx
```

`DemoStepTimeline` 展示步骤、状态、下一步按钮。

`JobStatusCard` 展示：

```text
job_id
queue_name
job_type
status
attempts
last_error
result_json 摘要
```

`LiveHealthPanel` 展示：

```text
OAuth 是否有效
默认测试群是否存在
Worker 是否 running
回调服务是否 running
SDK 环境是否可用
```

### 5.3 M4 待确认任务业务视图

从原始表格升级为业务卡片：

```text
待确认
已创建
已拒绝
缺少负责人
缺少截止时间
旧卡被拦截
```

每个任务展示：

```text
标题
负责人
截止时间
证据来源
review_session_id
pending_action_id
task_id
状态
更新时间
```

前端不直接创建任务，只展示状态和引导用户去飞书群点击卡片按钮。

### 5.4 M5 风险提醒业务视图

展示：

```text
任务标题
负责人
风险类型
严重级别
是否已提醒
降噪截止时间
关联 M4 会议 / 妙记
证据来源
```

从：

```text
risk_notifications
task_mappings
workflow_jobs.result_json
```

聚合。

## 6. API 设计明细

### 6.1 Demo Session API

```text
POST /api/live/demo/start
GET  /api/live/demo/{demo_session_id}
POST /api/live/demo/{demo_session_id}/run-step
POST /api/live/demo/{demo_session_id}/cancel
```

`start` 请求：

```json
{
  "meeting_title": "MeetFlow 测试会议",
  "date": "tomorrow",
  "event_id": "",
  "minute": "https://xxx.feishu.cn/minutes/xxx",
  "chat_id": "oc_xxx",
  "project_id": "meetflow",
  "llm_provider": "scripted_debug"
}
```

`run-step` 请求：

```json
{
  "step": "m4_send_cards",
  "allow_write": true
}
```

### 6.2 Business Summary API

```text
GET /api/m4/review-summary?limit=20
GET /api/m5/risk-summary?limit=20
```

M4 summary 返回：

```json
{
  "items": [
    {
      "review_session_id": "xxx",
      "title": "确认接口字段",
      "owner": "李四",
      "due_date": "2026-05-08",
      "status": "created",
      "task_id": "task_xxx",
      "missing_fields": [],
      "updated_at": 1778054400
    }
  ]
}
```

M5 summary 返回：

```json
{
  "items": [
    {
      "risk_key": "risk_scan:task_xxx:overdue:20260506",
      "task_id": "task_xxx",
      "title": "完成客户方案评审",
      "risk_type": "overdue",
      "severity": "high",
      "status": "notified",
      "suppressed_until": 1778140800,
      "meeting_id": "xxx",
      "minute_token": "xxx"
    }
  ]
}
```

## 7. 数据与迁移设计

第二阶段建议新增 migration：

```text
demo_sessions
demo_steps
```

`demo_steps` 字段：

```text
demo_session_id
step_key
status
job_id
started_at
finished_at
result_json
last_error
```

这样完整演示可以中断恢复：

```text
浏览器刷新后仍能看到刚才跑到 M4 等待用户点击按钮
```

## 8. 安全设计

第二阶段新增功能仍遵守：

- 前端不能传任意命令。
- 入队 payload 必须白名单字段。
- 真实写入必须 `allow_write=true`。
- M3/M4/M5 真实写入前必须二次确认。
- `demo_session` 中不存 token。
- 健康检查不返回密钥内容。
- 回调服务建议二选一，避免重复处理 card.action.trigger。

## 9. 推荐实施顺序

### 阶段 2.1：Job 轮询与异步入队

后端：

- 新增 `/api/m3/enqueue`
- 新增 `/api/m4/enqueue`
- 完善 `/api/m5/risk-scan mode=enqueue`
- 新增 `/api/jobs/{job_id}`

前端：

- `JobStatusCard`
- job 轮询 hook：`useJobPolling(jobId)`

验收：

```text
M4 点击入队后立即返回 job_id
Worker running 时 job 最终 succeeded
前端不因 M4/M5 长耗时请求卡住
```

### 阶段 2.2：完整演示模式

后端：

- 新增 demo session 存储
- 新增 `/api/live/demo/*`

前端：

- `DemoStepTimeline`
- Step 0 到 Step 6 串联

验收：

```text
能从一个页面完成 M3 -> M4 -> 等待群内确认 -> M5
刷新页面后演示状态不丢
```

### 阶段 2.3：M4/M5 业务状态可视化

后端：

- `/api/m4/review-summary`
- `/api/m5/risk-summary`

前端：

- `ReviewTaskBoard`
- `RiskNotificationBoard`

验收：

```text
不用看 SQLite 原始字段，也能判断待确认任务是否创建、风险是否提醒和是否被降噪
```

### 阶段 2.4：配置和 OAuth 健康检查

后端：

- `/api/live/health`

前端：

- `LiveHealthPanel`

验收：

```text
联调前能明确看到 OAuth、默认群、SDK 环境、Worker、回调服务是否满足要求
```

## 10. 测试计划

后端单测：

```text
tests.test_console_api
tests.test_jobs
tests.test_migrations
新增 tests.test_live_demo
新增 tests.test_live_health
```

前端构建：

```bash
cd frontend
npm run build
```

真实联调验收：

```text
1. M3 入队成功并发送会前卡片
2. M4 入队成功并发送会后总结卡和待确认任务卡
3. 群内点击确认后，review summary 显示 created
4. M5 入队或直接执行后，risk summary 显示 notified 或 suppressed
5. Jobs 页面没有 failed / dead_letter
```

## 11. 第二阶段完成标准

满足以下条件即可认为第二阶段完成：

```text
1. M3/M4/M5 真实链路支持异步入队和 job 轮询
2. 前端有完整演示模式，能串起 M3 -> M4 -> M5
3. M4 待确认任务状态不再只是 SQLite 原始表
4. M5 风险提醒状态不再只是 SQLite 原始表
5. 健康检查能提前提示 OAuth、SDK、Worker、默认群等问题
6. 所有真实写入仍保留 allow_write 和二次确认
7. 相关文档和 tasks.md 已同步记录
```

第二阶段的核心价值不是增加更多按钮，而是让 MeetFlow 的真实飞书群演示变成一个可恢复、可解释、可验收的业务闭环。
