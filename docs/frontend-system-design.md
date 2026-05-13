# MeetFlow 前端系统设计方案

本文档描述 MeetFlow 当前代码库之上的前端系统方案。目标不是做一个展示页，而是做一个能连接飞书真实业务、Agent 运行、后台任务、评测报告和安全审计的运维型控制台。

代码落地的目录、API、DTO、实施顺序和测试命令见
[MeetFlow Console 代码实现设计方案](frontend-code-implementation-plan.md)。

## 1. 产品定位

前端系统建议命名为 `MeetFlow Console`。

它面向两类用户：

- 项目开发者 / 演示人员：快速发起 M3/M4/M5 联调、查看报告、确认质量门禁。
- 业务管理员：查看会议知识服务运行状态、待确认任务、风险提醒和飞书回调健康度。

第一版不做营销首页，打开后直接进入工作台。系统应该服务真实操作：选会议、发卡、看 Agent 轨迹、跑评测、查失败原因、启动或检查 worker。

## 2. 总体架构

```text
Browser
  -> MeetFlow Console Frontend
  -> Backend API Facade
  -> MeetFlow Python Core
       -> Storage / SQLite / Reports
       -> FeishuClient
       -> MeetFlowAgent
       -> JobQueue / Worker
       -> Evaluation Suite
```

建议新增一个轻量后端 facade，而不是让前端直接执行脚本：

```text
scripts/web_console_server.py 或 apps/api/
  -> 调用 core/storage.py 查询状态
  -> 调用 core/agent.py 发起 Agent run
  -> 调用 core/jobs.py 入队后台任务
  -> 调用 scripts/agent_eval_suite.py 复用评测逻辑
  -> 读取 storage/reports/** 展示报告
```

这样前端只对 HTTP API 负责，Agent、Policy、ToolRegistry 和 FeishuClient 的边界不被破坏。

## 3. 页面结构

### 3.1 首页工作台

目的：让用户一眼知道系统是否可用。

核心模块：

- 今日 / 明日会议数量
- 最近一次 M3 发卡状态
- 最近一次 M4 会后任务确认状态
- 最近一次 M5 任务风险提醒状态
- Worker / callback / daemon 健康状态
- 最新评测分数：`score`、`safety_score`、`passed_cases / total_cases`

数据来源：

- `storage/meetflow.sqlite`
- `storage/reports/m3/**`
- `storage/reports/m4/**`
- `storage/reports/evaluation/agent_trajectory_latest.json`
- `workflow_jobs`

### 3.2 会前 M3 控制台

目的：替代命令行中的 `scripts/card_send_live.py m3`。

核心能力：

- 选择日期：today / tomorrow / 自定义日期
- 输入或选择会议标题
- 选择 LLM provider：默认 `scripted_debug`
- 开关：是否写报告、是否强制重建索引、是否允许真实发卡
- 运行后展示：
  - 选中的会议
  - 召回资料数量
  - Agent trace_id
  - 工具调用链路
  - 飞书消息 ID
  - 报告链接

对应命令能力：

```bash
scripts/card_send_live.py m3
scripts/pre_meeting_live_test.py
```

### 3.3 会后 M4 控制台

目的：管理妙记总结、待确认任务和任务创建闭环。

核心能力：

- 输入 minute token / 妙记 URL
- 选择测试群 chat_id
- 发送会后总结卡
- 展示待确认任务列表
- 展示 review_session 状态：
  - pending_count
  - created_count
  - rejected_count
  - 是否旧卡被拦截
- 展示按钮回调最新事件

对应数据：

- `review_sessions`
- `pending_actions`
- `task_mappings`
- `storage/reports/m4/**`

### 3.4 M5 任务风险提醒控制台

目的：查看任务风险、提醒降噪和后台巡检。

核心能力：

- 手动运行 risk scan
- 选择 dry-run / enqueue / allow-write
- 展示风险列表：
  - task_id
  - risk_type
  - severity
  - recipient
  - suppressed_until
  - last trace_id
- 查看是否已经发送过提醒

对应能力：

```bash
scripts/risk_scan_demo.py
scripts/meetflow_worker.py --queues risk_scan
```

### 3.5 Agent 轨迹与评测中心

目的：让“智能度”可见、可解释、可验收。

核心能力：

- 一键运行评测套件：

```bash
scripts/agent_eval_suite.py --suite agent_trajectory --provider scripted_debug --fail-under 0.95 --write-report
```

- 展示评测总览：
  - `score`
  - `safety_score`
  - `passed_cases`
  - `total_cases`
- 展示 case 明细：
  - `tool_call_f1`
  - `forbidden_tools_absent`
  - `tool_order_score`
  - `policy_compliance`
  - `allow_write_gate`
  - `idempotency_key_rate`
- 展示 Agent trace：
  - 工具调用顺序
  - Policy 决策
  - allow_write 状态
  - 幂等键是否存在
  - 最终回答摘要

第一版可以只读取：

```text
storage/reports/evaluation/agent_trajectory_latest.json
tests/e2e_fixtures/agent_trajectory/**/case.json
```

### 3.6 后台任务与服务健康

目的：让工业化链路可运维。

核心能力：

- 查看 `workflow_jobs` 队列：
  - queue_name
  - job_type
  - status
  - attempts
  - last_error
  - locked_by
  - created_at / updated_at
- 手动触发 worker dry-run
- 查看 migration 状态
- 查看 SDK callback / HTTP fallback 启动命令和最近错误

对应命令：

```bash
scripts/storage_migrate.py --status
scripts/storage_migrate.py --verify
scripts/meetflow_worker.py --once --dry-run
```

### 3.7 真实联调控制台

目的：把原本需要多个终端手工输入的 M4/M5 真实群聊联调收敛到一个页面。

核心能力：

- 启动 / 停止 Console 白名单长期服务：
  - Worker
  - SDK 回调
  - M4 按钮回调
- 输入飞书妙记链接，触发 M4 只读解析、M4 dry-run 或真实发送会后总结卡和待确认任务卡。
- 输入任务风险提醒参数，触发 M5 local/feishu dry-run、入队或真实发送任务风险提醒卡。
- 展示命令返回结果、脱敏 stdout、report path、job 摘要和最近业务状态表。
- 真实飞书写入继续要求 `allow_write` 和二次确认。

对应实现文档：

```text
docs/one-click-live-test-console-design.md
docs/one-click-live-test-console-code-design.md
```

## 4. API 设计建议

第一版后端 facade 可以提供这些接口：

```text
GET  /api/health
GET  /api/dashboard
GET  /api/reports/latest?type=evaluation|m3|m4
GET  /api/services
GET  /api/services/logs
POST /api/m3/send-card
POST /api/m4/read-minute
POST /api/m4/send-cards
POST /api/m5/risk-scan
POST /api/services/start
POST /api/services/stop
POST /api/evaluation/run
GET  /api/evaluation/latest
GET  /api/jobs
GET  /api/migrations/status
POST /api/worker/run-once
```

写操作必须显式传：

```json
{
  "allow_write": true,
  "idempotency_key": "..."
}
```

后端必须继续复用 `AgentPolicy` 和现有脚本逻辑，不能让前端新增绕过安全策略的直接飞书写接口。

## 5. 前端技术选型

建议：

- React + TypeScript + Vite
- Tailwind CSS 或现有轻量 CSS
- shadcn/ui 风格组件，但不要做成营销页
- Recharts 或 ECharts 展示评测分数和任务状态
- 前端目录建议为 `frontend/` 或 `apps/console/`

界面风格：

- 工作台型、密度适中、信息优先
- 颜色克制，不做大面积渐变
- 关键按钮区分 dry-run、enqueue、allow-write
- 对真实写操作使用二次确认
- 所有 trace_id、report path、job_id 都要可复制

## 6. 第一阶段 MVP

建议先做 4 个页面：

```text
Dashboard
M3 会前发卡
真实联调
Evaluation 评测中心
Jobs / Health
```

第一阶段验收标准：

- 能在前端跑 M3 scripted_debug 发卡并看到 trace_id 和 report path
- 能在真实联调页启动 / 停止 Worker、查看服务日志
- 能输入飞书妙记链接触发 M4 只读解析和 M4 dry-run
- 能触发 M5 local dry-run 并展示命令结果
- 能一键运行 Agent 评测并展示 `score = 1.0`、`safety_score = 1.0`
- 能查看 `workflow_jobs` 最近状态
- 能查看 migration verify 结果
- 所有真实写操作都有 `allow_write` 显式开关

## 7. 后续增强

- 接入 OAuth 授权状态展示
- 展示飞书卡片 JSON 预览
- 展示 Agent trace 时间线
- 支持 M4 待确认任务的人工审核视图
- 支持 M5 风险提醒历史图表
- 支持评测 case 编辑器
- 支持演示模式，一键按脚本跑完整 M3 -> M4 -> M5 闭环
