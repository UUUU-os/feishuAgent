# MeetFlow 从零启动到真实飞书群完整联调 Runbook

本文档用于从干净状态开始，完整启动 MeetFlow Console、后台服务和真实飞书群联调流程，覆盖：

```text
基础质量检查
Console API 启动
前端启动
飞书 OAuth / 配置检查
SDK 或 M4 按钮回调服务
Worker 后台消费
M3 会前卡片
M4 会后总结卡 + 待确认任务卡
群内确认任务按钮
M5 任务风险提醒卡
Jobs / SQLite / 报告检查
```

当前日期按 2026-05-06 记录。若使用 `--date tomorrow`，查询窗口是 2026-05-07 本地整天。

## 1. 准备项

开始前确认这些信息已经准备好：

```text
1. 本地配置：config/settings.local.json
2. 飞书应用 app_id / app_secret 已配置
3. 飞书测试群 chat_id 已配置到 feishu.default_chat_id，或稍后在前端手动填写
4. 已完成 OAuth user 授权，或准备重新扫码
5. 飞书测试日历中存在测试会议
6. 有一个真实飞书妙记链接，用于 M4 会后总结
7. 前端机器已安装 Node.js / npm
8. .venv-lark-oapi 已存在并可导入 lark_oapi
```

建议测试会议：

```text
标题：MeetFlow 测试会议
时间：2026-05-07 10:00 - 10:30
参与人：添加你自己
描述：这是 MeetFlow M3 会前卡片测试会议
```

如果你的会议不在 2026-05-07，请在前端 M3 页面把日期改成真实日期，或直接填写 event_id。

## 2. 推荐终端分工

第一阶段推荐只手动打开两个长期终端：

```text
终端 1：Console API 后端
终端 2：前端 Vite 服务
浏览器：执行大多数联调操作
```

Worker、SDK 回调、M4 按钮回调可以在前端 `真实联调` 页面里启动和停止。

如果前端服务控制不可用，再使用第 8 节中的手动备用终端命令。

## 3. 终端 0：一次性基础检查

进入项目根目录：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
```

运行基础编译：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
```

运行后端单测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests
```

运行 Console API 重点测试：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api
```

检查 migration：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --status
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
```

检查 SDK 隔离环境：

```bash
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"
```

如果 `.venv-lark-oapi` 不存在或 import 失败：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate
```

## 4. 如需重新 OAuth 授权

如果飞书 user token 失效，先执行：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/oauth_device_login.py
```

按终端提示完成扫码或设备码授权。

授权后验证日历读取：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/calendar_live_test.py \
  --identity user \
  --calendar-id primary \
  --debug-calendar
```

验证妙记读取，把链接替换成你的真实妙记：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/minutes_live_test.py \
  --minute "https://你的飞书域名.feishu.cn/minutes/你的妙记token"
```

## 5. 终端 1：启动 Console API 后端

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py \
  --host 127.0.0.1 \
  --port 8787
```

启动成功后，终端会显示：

```text
MeetFlow Console API 已启动：http://127.0.0.1:8787
API 健康检查：/api/health
```

另开一个临时命令检查：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
curl --noproxy '*' -sS http://127.0.0.1:8787/api/dashboard
curl --noproxy '*' -sS http://127.0.0.1:8787/api/services
```

这个终端全程保持运行。

## 6. 终端 2：启动前端 Vite 服务

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main/frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器访问：

```text
http://127.0.0.1:5173
```

如果 `npm` 不存在，需要先安装 Node.js / npm。没有 npm 时只能使用 Console API 和命令行，无法打开前端开发服务。

如果端口 5173 被占用：

```bash
npm run dev -- --host 127.0.0.1 --port 5174
```

## 7. 前端操作总流程

### 7.1 Dashboard

打开前端后先看 `Dashboard`：

检查：

```text
1. 系统状态是否为可运行
2. migration 是否 OK
3. 最近 jobs 是否有 failed / dead_letter
4. 最新 evaluation score 是否 >= 0.95，safety_score 是否为 1.0
```

如果 Dashboard 加载失败，优先确认终端 1 的 Console API 是否还在运行。

### 7.2 Jobs / Health

进入 `Jobs / Health` 页面：

点击：

```text
刷新
Worker Dry-run
```

期望：

```text
Worker Dry-run 返回成功
workflow_jobs 表可以正常展示
migration pending_count = 0
```

### 7.3 真实联调：启动后台服务

进入 `真实联调` 页面。

在 `服务控制` 区域点击：

```text
Worker -> 启动
```

如果你希望统一承接飞书卡片动作，点击：

```text
SDK 回调 -> 启动
```

如果你只想专测 M4 待确认任务按钮，点击：

```text
M4 按钮回调 -> 启动
```

注意：`SDK 回调` 和 `M4 按钮回调` 都可能监听 card.action.trigger。真实群里点按钮时建议二选一，不要同时启动两个回调监听，避免重复处理。

推荐选择：

```text
完整 M3/M4 卡片动作统一联调：启动 SDK 回调
只验证 M4 确认创建任务按钮：启动 M4 按钮回调
```

启动后点击：

```text
查看日志
刷新
```

期望状态：

```text
status = running
pid 有值
log_path 指向 storage/runtime/logs/*.log
```

### 7.4 M3 会前卡片

进入 `M3 会前` 页面。

命令行联调会前背景卡时，统一使用 `scripts/card_send_live.py m3` 入口。
这个脚本会自动转调 `scripts/pre_meeting_live_test.py`，并补上真实发卡需要的
`--allow-write` 和幂等开关。不要在 runbook 中直接把
`scripts/pre_meeting_live_test.py` 当作首选入口，避免演示命令和前端/CLI 入口不一致。

填写：

```text
日期窗口：tomorrow
会议标题：MeetFlow 测试会议
Event ID：可空；如果知道 event_id，建议填写
LLM Provider：scripted_debug
Project ID：meetflow
写入报告：勾选
重建索引：按需勾选
允许真实发卡：先不要勾选
```

先点击：

```text
运行 Dry-run
```

期望：

```text
返回 ok
stdout 中能看到将执行的下游命令
没有真实发送飞书卡片
```

确认无误后，勾选：

```text
允许真实发卡
```

点击：

```text
确认并发卡
```

弹窗确认后，去飞书测试群检查：

```text
收到 M3 会前背景卡
卡片内容包含会议背景、相关资料、下一步建议等信息
```

前端结果区检查：

```text
returncode = 0
status = success
trace_id 有值
report_json 或 report_markdown 有路径
```

如果提示找不到会议：

```text
1. 确认 2026-05-07 是否真的有 MeetFlow 测试会议
2. 如果会议在今天，改 date=today
3. 如果会议在固定日期，改成 YYYY-MM-DD
4. 如果知道 event_id，直接填写 event_id
```

### 7.5 M4 会后总结与待确认任务卡

进入 `真实联调` 页面。

在 `M4 会后总结` 区域填写：

```text
飞书妙记链接：https://你的飞书域名.feishu.cn/minutes/你的妙记token
Chat ID：可空；不填使用配置里的 feishu.default_chat_id
Identity：user
Content Limit：300
Related Top N：5
Timeout：180
跳过相关知识召回：默认不勾选
展示卡片 JSON：按需
允许真实发送 M4 卡片：先不要勾选
```

先点击：

```text
只读解析妙记
```

期望：

```text
returncode = 0
parsed 中能看到 minute_token / meeting_id / report_path 等摘要
stdout 中没有鉴权失败或接口错误
```

再点击：

```text
M4 Dry-run
```

期望：

```text
只打印将执行命令
不发送飞书卡片
```

确认无误后，勾选：

```text
允许真实发送 M4 卡片
```

点击：

```text
真实发送 M4
```

弹窗确认后，去飞书测试群检查：

```text
1. 收到会后总结卡
2. 收到待确认任务卡
3. 待确认任务卡包含确认创建 / 拒绝创建按钮
```

### 7.6 群内点击待确认任务按钮

确认回调服务已运行。推荐在 `真实联调` 页服务控制区确认：

```text
SDK 回调 running
或 M4 按钮回调 running
```

在飞书测试群中操作：

```text
1. 点击待确认任务卡上的确认创建
2. 如果提示缺少负责人或截止时间，在输入框补充后直接点击确认创建
```

回到前端 `真实联调` 页面点击：

```text
刷新状态
```

检查 `最近业务状态`：

```text
Review Sessions 有记录
Task Mappings 有记录
如果任务创建成功，应能看到 task_id
```

同时可以在 `Jobs / Health` 页面查看是否有 callback 或 agent 相关 job。

### 7.7 M5 任务风险提醒

这里的 M5 扫描真实飞书任务或本地任务样本，关注逾期、临期、长期未更新、缺负责人等任务状态风险。
会后总结卡中的“行动项风险预检”是另一条入口，只预检当前会议待确认行动项。

仍在 `真实联调` 页面。

先做本地样本 dry-run：

```text
Backend：local
Mode：direct
Completed：未完成
展示风险卡片 JSON：勾选
允许真实发送任务风险提醒：不勾选
```

点击：

```text
运行 M5
```

期望：

```text
returncode = 0
stdout 中有风险扫描结果和风险卡 JSON
没有发送飞书消息
```

再做真实飞书任务 dry-run：

```text
Backend：feishu
Mode：direct
Identity：user
Send Identity：tenant
Chat ID：可空；不填使用默认测试群
允许真实发送任务风险提醒：不勾选
```

点击：

```text
运行 M5
```

期望：

```text
真实读取飞书任务
stdout 中显示风险决策
没有发送飞书消息
```

最后真实发送任务风险提醒：

```text
允许真实发送任务风险提醒：勾选
```

点击：

```text
真实执行 M5
```

弹窗确认后，去飞书测试群检查：

```text
收到 M5 任务风险提醒卡
```

回到前端刷新，检查：

```text
Risk Notifications 有记录
Jobs / Health 无异常 failed job
```

如果不希望同步等待，可选择：

```text
Mode：enqueue
```

然后确保 Worker 服务 running，再到 `Jobs / Health` 查看 `risk_scan.run` job 状态。

## 8. 手动备用终端命令

如果前端服务控制不可用，可以手动启动这些长期服务。

### 8.1 Worker

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

### 8.2 SDK 统一回调服务

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --enqueue-agent \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level info
```

这是统一 SDK WebSocket 回调入口，可以承接 M3/M4 卡片动作。

### 8.3 M4 按钮回调专用服务

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4-callback \
  --log-level info
```

如果只想打印按钮回调、不真正创建任务：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4-callback \
  --log-level info \
  --dry-run
```

注意：SDK 统一回调和 M4 按钮回调专用服务建议二选一。

### 8.4 M3 命令行真实发送

2026-05-12 真实 LLM + 当前文档/妙记的会前背景卡推荐命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/card_send_live.py m3 \
  --date today \
  --event-title "你的会议标题关键词" \
  --llm-provider settings \
  --idempotency-suffix "m3-live-llm-20260512-01" \
  --write-report \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/YGY5dOFrMoVu5Ox7DJnc7AaSnyb" \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

说明：

```text
1. 会前背景卡必须使用 card_send_live.py m3 入口。
2. --event-title 替换成日历中真实会议标题的关键词。
3. --llm-provider settings 会读取本地 settings.local.json 中配置的真实 LLM。
4. 重复真实发送同一会议时，必须换一个新的 --idempotency-suffix。
5. --doc 和 --minute 会纳入本次会前 RAG/Evidence Pack，用于生成核心背景知识和原始链接。
```

旧版 scripted_debug 快速冒烟命令：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

### 8.5 M4 命令行只读和真实发送

只读：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "https://你的飞书域名.feishu.cn/minutes/你的妙记token" \
  --read-only \
  --show-card-json \
  --content-limit 800
```

真实发送：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "https://你的飞书域名.feishu.cn/minutes/你的妙记token" \
  --show-card-json
```

如果没有默认群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "https://你的飞书域名.feishu.cn/minutes/你的妙记token" \
  --chat-id oc_xxx \
  --show-card-json
```

### 8.6 M5 命令行真实巡检

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

## 9. 完整验收结果记录

完成一次全链路后，建议记录：

```text
1. Console API 是否启动成功
2. 前端是否可访问
3. Worker 是否 running
4. 回调服务选择：SDK 回调 / M4 按钮回调
5. M3 trace_id
6. M3 report path
7. M4 minute link
8. M4 report path
9. M4 review_session_id
10. 飞书 task_id
11. M5 是否发送风险卡
12. M5 risk notification 记录
13. 是否存在 failed / dead_letter job
```

可以查看 SQLite：

```bash
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

## 10. 常见失败处理

### 前端打不开

检查：

```text
1. npm 是否存在
2. Vite 是否启动
3. 浏览器访问端口是否正确
```

### 前端页面加载失败

检查 Console API：

```bash
curl --noproxy '*' -sS http://127.0.0.1:8787/api/health
```

### M3 找不到会议

处理：

```text
1. 确认日期窗口
2. 改用 today 或 YYYY-MM-DD
3. 改用 event_id
4. 确认 OAuth user 身份能读取日历
```

### M4 妙记读取失败

处理：

```text
1. 确认妙记链接可访问
2. 重新 OAuth 授权
3. 确认应用权限已发布
4. 查看 stdout 中 request_id/log_id
```

### 群里点击按钮没有反应

处理：

```text
1. 确认只启动了一个回调服务
2. 查看 SDK 回调或 M4 回调日志
3. 确认飞书应用事件订阅和机器人能力已开启
4. 确认 Worker running，如果回调选择了 enqueue
```

### M5 没有发送风险卡

可能原因：

```text
1. 没有发现风险
2. 触发了降噪窗口
3. 没有 allow_write
4. chat_id 缺失
5. send_identity 或机器人权限不正确
```

如需临时清掉降噪窗口：

```bash
sqlite3 storage/meetflow.sqlite \
  "UPDATE risk_notifications SET suppressed_until = 0 WHERE status = 'notified';"
```

## 11. 收尾

完成测试后，在前端 `真实联调` 页面停止：

```text
Worker
SDK 回调 或 M4 按钮回调
```

终端中停止：

```text
终端 1：Ctrl+C 停止 Console API
终端 2：Ctrl+C 停止 Vite
```

最后检查工作区：

```bash
git status --short
git check-ignore -v config/settings.local.json .venv-lark-oapi storage/reports storage/meetflow.sqlite storage/workflow_events.jsonl
```

不要提交：

```text
config/settings.local.json
真实 token
真实 app secret
storage/meetflow.sqlite
storage/runtime/**
storage/reports/**
```
