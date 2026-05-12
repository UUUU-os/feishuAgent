# MeetFlow 整体测试命令总表

本文档是 MeetFlow 后续每次代码改动后的测试入口。目标是让项目从“能跑 demo”变成“有固定质量闸口”，并让新接手的人知道：先跑什么、哪些服务要长期占用终端、哪些命令只是排查用。

LLM Agent 评测体系的指标、报告 schema 和落地计划见 [MeetFlow LLM Agent 评测系统方案](llm-agent-evaluation-system-plan.md)。

## 1. 文档用途

本文档覆盖这些场景：

```text
本地前端 Console 启动
Console API 后端启动
Python 基础编译与单元测试
SDK / HTTP 回调服务启动
Worker / Daemon 长期运行
OAuth 与飞书真实读写联调
M3 / M4 / M5 真实业务链路测试
SQLite 运行数据排查
提交前质量闸口
```

需要更新本文档的情况：

```text
新增或删除 scripts/*.py 入口
新增或删除 config/settings.example.json 配置项
新增数据库表、字段、migration 或队列 job_type
新增飞书权限 scope、OAuth 行为或回调路径
新增 M3/M4/M5 工作流能力或卡片按钮
新增评测 fixture、LLM provider、fallback 或部署方式
修改真实测试命令的参数名、默认值或安全开关
新增或修改前端启动方式、端口、API 代理或控制台页面
```

不需要更新本文档的情况：

```text
纯内部重构，所有命令仍完全相同
只改注释或文档措辞
只修复测试断言但不改变运行入口
```

## 2. 快速启动总览

先进入项目根目录：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
```

最常用的本地控制台启动顺序：

```text
终端 2：启动 Console API 后端，监听 127.0.0.1:8787
终端 1：启动前端 Vite 服务，监听 127.0.0.1:5173
浏览器：打开 http://127.0.0.1:5173
```

终端 2，启动 Console API：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

终端 1，启动前端：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器访问：

```text
http://127.0.0.1:5173
```

前端位于 `frontend/`，实际启动脚本来自 `frontend/package.json`：

```text
npm run dev      启动 Vite 开发服务
npm run build    执行 TypeScript 构建和 Vite 打包
npm run preview  预览构建产物
```

前端请求 `/api/...`，由 `frontend/vite.config.ts` 代理到 `http://127.0.0.1:8787`。因此只开前端、不启动 Console API 时，Dashboard、评测、M3 发卡和 Jobs 页面会无法加载数据。

## 3. 终端分工总览

### 终端 1：前端服务

作用：运行 MeetFlow Console 前端页面。

是否长期运行：是。开发和手动验收期间保持运行。

启动命令：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

启动成功判断：

```text
终端里出现 Vite ready / Local: http://127.0.0.1:5173
浏览器打开 http://127.0.0.1:5173 能看到 MeetFlow Console
```

什么时候关闭：不再查看或调试前端时按 `Ctrl+C`。

端口冲突处理：

```bash
npm run dev -- --host 127.0.0.1 --port 5174
```

如果改端口，浏览器也要访问对应新端口。`/api` 仍会代理到 `127.0.0.1:8787`。

### 终端 2：后端 / HTTP fallback 服务

作用：通常启动 Console API，为前端提供 `/api/health`、`/api/dashboard`、`/api/m3/send-card`、`/api/evaluation/run` 等接口；测试飞书 HTTP fallback 回调时，也可以在这个终端改为启动 `scripts/feishu_event_server.py`。

是否长期运行：是。前端联调期间 Console API 必须保持运行；HTTP fallback 回调测试期间 fallback 服务必须保持运行。

Console API 启动命令：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

启动成功判断：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
```

HTTP fallback 启动命令见第 7 节。Console API 和 HTTP fallback 是不同服务，默认端口分别是 `8787` 和 `8765`。

什么时候关闭：不再使用前端或不再接收 HTTP 回调时按 `Ctrl+C`。

端口冲突处理：把 `--port 8787` 改成空闲端口；如果前端仍要访问 Console API，需要同步调整 `frontend/vite.config.ts` 的代理目标。

### 终端 3：SDK 回调服务

作用：运行飞书官方 SDK WebSocket/事件回调入口。

是否长期运行：是。真实接收飞书 SDK 回调时保持运行。

启动前先确认 SDK 隔离环境：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -V
```

启动命令：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --enqueue-agent \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level info
```

启动成功判断：

```text
SDK 服务没有 import error
飞书事件到达时终端能看到回调日志
如果开启 --enqueue-agent，SQLite workflow_jobs 中能看到新任务
```

什么时候关闭：不再接收飞书 SDK 回调时按 `Ctrl+C`。

### 终端 4：Worker 长期任务消费

作用：消费 `workflow_jobs` 中的后台任务，例如 workflow、risk_scan、rag_refresh。

是否长期运行：是。需要后台自动消费时保持运行。

启动命令：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

启动成功判断：

```bash
ps -ef | grep meetflow_worker.py
```

什么时候关闭：不需要后台消费时按 `Ctrl+C`；如果后台运行，使用 `kill <PID>` 停止。

### 终端 5：一次性测试 / SQLite 排查 / Git 检查

作用：运行编译、单测、评测、真实联调脚本、SQLite 查询和提交前检查。

是否长期运行：否。命令执行完就结束。

常用入口：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests
git status --short
```

## 4. 每次改代码后的最小测试流程

这组是“默认必须跑”的最小质量闸口，适合大多数后端或 Agent 改动：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
```

编译检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
```

全量单元测试：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests
```

Agent 轨迹质量门禁：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95
```

如果改了前端，再跑：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm run build
```

如果改了 Console API，再跑：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/console_api.py \
  scripts/meetflow_console_server.py \
  tests/test_console_api.py

/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
```

注意：前端检查需要本机已安装 Node.js 和 npm。如果 `node -v` 或 `npm -v` 不可用，需要先安装 Node.js 后再执行 `npm install`、`npm run build` 和 `npm run dev`。

## 5. 前端启动流程

前端目录：

```text
/home/tanyd/ye/workhard/feishuAgent-main/frontend
```

首次安装依赖：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm install
```

构建检查：

```bash
npm run build
```

开发启动：

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

访问地址：

```text
http://127.0.0.1:5173
```

前端和后端关系：

```text
前端 Vite 服务：127.0.0.1:5173
Console API 后端：127.0.0.1:8787
Vite 代理：/api -> http://127.0.0.1:8787
SDK 回调服务：独立运行，不直接服务前端页面
Worker：独立消费后台队列，前端通过 Console API 查看 Jobs 状态
```

前端 UI/UX 回归检查：

```text
Dashboard 首屏应能看到系统名称、运行状态、安全提示、M3/真实联调/评测/Jobs 核心功能卡片。
M3 会前页面应展示“配置参数 -> 连接飞书 -> Dry-run/真实发卡 -> 查看结果”的步骤引导。
M3 默认不真实发卡；勾选“允许真实发卡”后必须出现二次确认弹窗。
真实联调页面应展示服务控制、M4 妙记解析/发卡、M5 任务风险提醒、最近业务状态和命令结果面板。
真实联调页面中 M4/M5 真实飞书写入必须勾选 allow_write，并出现二次确认弹窗。
Agent 评测页面应能显示 score、safety、case 结果和空状态说明。
Jobs / Health 页面应能显示 migration、workflow_jobs、worker dry-run 状态说明。
浏览器宽度缩到窄屏时，侧边导航、功能卡片、表单和结果面板不应相互遮挡。
```

## 6. 后端基础检查

Python 环境约定：

```text
主业务环境：/home/tanyd/anaconda3/envs/meetflow/bin/python
飞书 SDK 隔离环境：/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python
```

主业务环境用于 `core/`、`adapters/`、`scripts/meetflow_worker.py`、HTTP fallback、Console API 和所有单元测试。飞书 SDK 隔离环境只用于 `scripts/feishu_event_sdk_server.py`，它单独安装 `lark-oapi` 和 `protobuf<4`，避免污染主环境。

注意：不要用系统 `python3` 创建 `.venv-lark-oapi`。如果系统 Python 是 3.8，会触发 `dataclass(slots=True)` 兼容性错误；必须用主 `meetflow` 环境的 Python 3.10 创建或重建。

基础编译：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
```

全量单测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests
```

重点模块回归：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_assistant_memory \
  tests.test_feishu_callback_dispatcher \
  tests.test_post_meeting_card_callback \
  tests.test_risk_scan \
  tests.test_risk_scan_card \
  tests.test_risk_scan_workflow
```

数据库 migration：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --status
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations
```

多轮会话记忆 / pending action 恢复：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_assistant_memory
```

这组命令重点检查：

```text
AgentPolicy 返回 needs_confirmation 时是否落库 pending_actions
clarification_questions 是否记录需要用户补充的字段
用户补充负责人 / 截止时间后是否把 pending action 标记为 ready_to_resume
恢复后的工具调用描述是否仍准备重新进入 AgentPolicy，而不是绕过策略直接写飞书
```

Job queue / worker：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_jobs
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
```

离线 E2E 评测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0
```

写入 E2E 评测报告：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py \
  --all \
  --fail-under 1.0 \
  --write-report
```

Agent 轨迹与智能度评测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_assistant_memory \
  tests.test_eval_trace \
  tests.test_eval_metrics \
  tests.test_agent_eval_suite
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95
```

只评测单个 Agent 轨迹 case：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --case-id m3_evidence_first_plan \
  --provider scripted_debug \
  --fail-under 0.95
```

写入 Agent 轨迹评测报告：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

报告输出位置：

```text
storage/reports/evaluation/agent_trajectory_<timestamp>.json
storage/reports/evaluation/agent_trajectory_latest.json
```

当前内置 Agent 轨迹 case：

```text
m3_evidence_first_plan
m4_owner_missing_needs_confirmation
policy_blocks_unconfirmed_write
```

评测输出重点字段：

```text
score                 总分，所有 case 的平均分。常规门槛为 >= 0.95。
safety_score          敏感信息泄露扫描。必须为 1.0。
total_cases           本次评测 case 总数。
passed_cases          通过的 case 数量。
results[].score       单个 case 的聚合分。
results[].passed      单个 case 是否通过所有指标阈值。
results[].metrics[]   单个 case 的细项指标。
```

细项指标含义：

```text
tool_call_f1            工具调用集合是否符合期望，综合 precision / recall。
forbidden_tools_absent  是否没有调用禁止工具。
tool_order_score        工具调用顺序是否满足约束，例如先读会议再检索知识再发卡。
policy_compliance       写操作是否留下 AgentPolicy 决策轨迹。
allow_write_gate        未开启 allow_write 时，写操作是否被阻止或进入确认。
idempotency_key_rate    写操作 Policy 决策是否具备幂等键。
```

当前基线结果：

```text
provider: scripted_debug
total_cases: 3
passed_cases: 3
score: 1.0
safety_score: 1.0
```

## 7. SDK / HTTP 回调服务启动

准备或修复 SDK 隔离环境：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
```

如果之前执行过 `python3 scripts/setup_lark_oapi_venv.py`，或遇到 `.venv-lark-oapi/bin/python: No such file or directory`、Python 3.8 下的 `dataclass(slots=True)` 兼容性错误，用主环境重建：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate
```

确认 SDK 隔离环境 Python 版本：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -V
```

SDK import：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"
```

SDK 回调 dry-run：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --dry-run \
  --log-level debug
```

SDK 回调入队模式：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --enqueue-agent \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level info
```

HTTP fallback dry-run 启动：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/feishu_event_server.py \
  --host 0.0.0.0 \
  --port 8765
```

HTTP fallback 入队模式：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/feishu_event_server.py \
  --host 0.0.0.0 \
  --port 8765 \
  --enqueue-agent \
  --agent-provider dry-run
```

Console API 后端检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/console_api.py \
  scripts/meetflow_console_server.py \
  tests/test_console_api.py
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
```

启动本地 Console API：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

另开终端验证 HTTP API：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
curl --noproxy '*' -sS http://127.0.0.1:8787/api/dashboard
curl --noproxy '*' -sS \
  -X POST http://127.0.0.1:8787/api/evaluation/run \
  -H 'Content-Type: application/json' \
  -d '{"suite":"agent_trajectory","provider":"scripted_debug","fail_under":0.95,"write_report":true}'
```

## 8. Worker / Daemon 启动

启动长期 worker：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

daemon 只预览：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py \
  --enable-m3 \
  --enable-m4 \
  --enable-rag \
  --enqueue \
  --once \
  --dry-run
```

daemon 长期入队：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py \
  --enable-m3 \
  --enable-m4 \
  --enable-rag \
  --enqueue \
  --poll-seconds 60
```

查看 worker 进程：

```bash
ps -ef | grep meetflow_worker.py
```

停止指定 worker：

```bash
kill <PID>
```

## 9. OAuth / 飞书基础读检查

重新扫码授权：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/oauth_device_login.py
```

验证日历 user 身份：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/calendar_live_test.py \
  --identity user \
  --calendar-id primary \
  --debug-calendar
```

验证妙记读取：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/minutes_live_test.py \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae"
```

## 10. M3 会前卡片真实测试

目的：验证会前会议定位、知识检索、报告生成和飞书卡片发送链路。

飞书里先创建测试日程：

```text
标题：MeetFlow 测试会议
时间：明天 10:00 - 10:30
参与人：添加你自己
描述：这是 MeetFlow M3 会前卡片测试会议
```

注意：`--date tomorrow` 查询的是运行命令当天的“明天”本地整天。例如在 2026-05-06 执行时，它会查询 2026-05-07 00:00:00 到 2026-05-08 00:00:00。如果这个窗口里没有标题包含 `MeetFlow 测试会议` 的日程，会报“给定时间窗口内没有可用于测试的会议”。此时应先创建对应日期的测试日程，或把 `--date` 改成真实有会议的日期。

先打印下游命令并确认实际查询窗口。注意：`--dry-run` 只打印命令，不会真实查询飞书：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-check" \
  --write-report \
  --dry-run
```

如果会议其实在今天：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

如果测试会议在固定日期，直接写绝对日期：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date 2026-05-07 \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

真实发送 M3：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

只打印下游命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-test" \
  --write-report \
  --dry-run
```

前端也可以触发 M3：启动第 2 节的 Console API 和前端后，打开 `http://127.0.0.1:5173`，进入 `M3 会前` 页面。默认是 dry-run；勾选“允许真实发卡”后必须二次确认。

## 11. M4 会后总结真实测试

目的：验证妙记读取、会后总结卡、待确认任务卡和按钮确认闭环。

只读验证：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae" \
  --read-only \
  --show-card-json \
  --content-limit 800
```

真实发送 M4：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae" \
  --show-card-json
```

如果没有默认群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcnf14z4qh9i2o846jy56ae" \
  --chat-id oc_xxx \
  --show-card-json
```

群里检查：

```text
会后总结卡
待确认任务卡
确认创建 / 拒绝创建 按钮
```

M4 按钮确认闭环回归：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_card_actions \
  tests.test_post_meeting_card_callback
```

这组命令重点检查：

```text
confirm_create_task / reject_create_task 是否被 CardActionRouter 识别
输入框补充字段后点击确认是否能复用表单中的负责人和截止时间
review_session_id 是否进入幂等键和 SQLite review_sessions 审计
重复发卡后旧卡是否被拦截，新卡是否可重新确认
```

## 12. M5 任务风险提醒真实测试

目的：验证从任务映射中发现风险、生成风险卡片、发送提醒和降噪窗口。

直接执行并允许发送：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant
```

只入队：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant \
  --enqueue
```

手动消费一次：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues risk_scan \
  --once
```

如果测试环境需要临时清掉降噪窗口：

```bash
sqlite3 storage/meetflow.sqlite \
  "UPDATE risk_notifications SET suppressed_until = 0 WHERE status = 'notified';"
```

## 13. SQLite 排查命令

查看 job queue：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
sqlite3 storage/meetflow.sqlite \
  "SELECT job_id,queue_name,job_type,status,attempts,last_error,created_at,updated_at FROM workflow_jobs ORDER BY created_at DESC LIMIT 20;"
```

查看 M4 -> M5 任务映射：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT item_id,task_id,meeting_id,minute_token,title,updated_at FROM task_mappings ORDER BY updated_at DESC LIMIT 10;"
```

查看风险提醒历史：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT risk_key,task_id,risk_type,status,notified_at,suppressed_until FROM risk_notifications ORDER BY created_at DESC LIMIT 20;"
```

查看 migration：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT version,name,applied_at FROM schema_migrations ORDER BY version;"
```

查看最近 assistant session：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT session_id,user_id,actor,current_workflow,workflow_type,current_project_id FROM assistant_sessions ORDER BY updated_at DESC LIMIT 5;"
```

## 14. 提交前检查

确认没有把本地密钥和运行产物加入暂存区：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
git status --short
git check-ignore -v config/settings.local.json .venv-lark-oapi storage/reports storage/meetflow.sqlite storage/workflow_events.jsonl
```

建议提交前跑：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py

/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95
```

如果本次包含前端改动：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm run build
```

如果本次包含 Console API 改动：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
```

## 15. 按改动类型选择测试范围

```text
只改纯函数/模型：
  跑 py_compile + 对应 unittest + 全量 unittest

改 storage/migration/jobs：
  跑 tests.test_migrations tests.test_jobs + storage_migrate --verify + worker --dry-run

改前端页面 / 样式 / 交互：
  跑 npm run build
  启动 Console API + npm run dev
  浏览器检查 Dashboard / M3 / Agent 评测 / Jobs Health

改 Console API：
  跑 tests.test_console_api
  启动 scripts/meetflow_console_server.py
  curl /api/health /api/dashboard /api/evaluation/run

改 M3：
  跑 M3 相关单测 + e2e_replay m3_pre_meeting_basic + M3 dry-run
  需要真实验收时跑 M3 真实发卡

改 M4：
  跑 tests.test_post_meeting_card_callback tests.test_post_meeting_rag_query
  跑 e2e_replay m4_post_meeting_with_tasks
  跑 M4 read-only + 真实发卡 + 群按钮确认

改 M5：
  跑 tests.test_risk_scan* + e2e_replay m5_risk_from_m4_mapping
  跑 risk_scan_demo local/feishu

改 SDK/HTTP 回调：
  跑 tests.test_feishu_callback_dispatcher
  跑 SDK import + SDK dry-run
  必要时真实群里点按钮

改真实 LLM provider：
  先跑 scripted_debug
  再小样本真实 provider
  不允许把真实 API key 写入命令或文档

改 Agent prompt / tool schema / Policy / AgentLoop：
  跑 tests.test_eval_trace tests.test_eval_metrics tests.test_agent_eval_suite
  跑 scripts/agent_eval_suite.py --suite agent_trajectory --provider scripted_debug --fail-under 0.95
  再跑全量 unittest 和 e2e_replay
```

## 16. 常见问题排查

### npm 或 node 命令不存在

现象：

```text
Command 'npm' not found
Command 'node' not found
```

处理：

```text
前端需要本机安装 Node.js 和 npm。
安装完成后重新进入 frontend/，执行 npm install、npm run build、npm run dev。
```

### 前端页面打开了但数据加载失败

优先检查 Console API 是否启动：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
```

如果失败，回到终端 2 启动：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

### 5173 或 8787 端口冲突

前端端口冲突：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

后端端口冲突：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8788
```

如果后端改成 `8788`，需要同步修改 `frontend/vite.config.ts` 中 `/api` proxy 的 target。

### .venv-lark-oapi/bin/python 不存在

用主 meetflow 环境创建或重建 SDK 隔离环境：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate
```

再验证：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"
```

### M3 提示没有可用于测试的会议

先确认 `--date` 对应的绝对日期窗口。例如 2026-05-06 执行 `--date tomorrow` 查询的是 2026-05-07 本地整天。

处理顺序：

```text
1. 在飞书日历创建对应日期的 MeetFlow 测试会议。
2. 如果会议在今天，改用 --date today。
3. 如果会议在固定日期，改用 --date YYYY-MM-DD。
4. 如果有 event_id，优先用 event_id 精确定位。
```

### worker 没有消费任务

查看任务状态：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT job_id,queue_name,job_type,status,attempts,last_error FROM workflow_jobs ORDER BY created_at DESC LIMIT 20;"
```

检查 worker 是否监听了对应队列：

```bash
ps -ef | grep meetflow_worker.py
```

如果只是想验证 worker 入口：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
```

### 飞书真实 API 权限或 token 失败

先重新授权：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/oauth_device_login.py
```

再跑只读验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/calendar_live_test.py \
  --identity user \
  --calendar-id primary \
  --debug-calendar
```

日志和文档里只能记录 provider、scope、错误码、request_id/log_id 等排查字段，不能记录完整 access token、refresh token、app secret 或 API key。
