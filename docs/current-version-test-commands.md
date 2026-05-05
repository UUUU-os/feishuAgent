# MeetFlow 当前版本保存与完整测试命令

当前建议版本名：

```text
meetflow-m3-m4-m5-closed-loop-20260505
```

本文件记录当前 M3/M4/M5 融合闭环版本的保存命令和测试命令。不要提交
`config/settings.local.json`、`.venv-lark-oapi/`、`storage/reports/` 或任何真实 token。

长期维护的完整测试命令总表见
[MeetFlow 整体测试命令总表](overall-test-commands.md)。后续每次新增脚本、
配置、migration、job_type、回调路径、评测 case 或真实联调入口，都要检查是否
需要同步更新该总表。

## 1. Git 保存当前版本

先检查工作区：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
git status --short
```

确认没有把本地密钥和运行产物加入暂存区：

```bash
git status --short | grep -E 'settings.local.json|llm_providers.local.json|.venv-lark-oapi|storage/reports|storage/.*sqlite|storage/.*jsonl' || true
```

暂存代码和文档：

```bash
git add .gitignore adapters cards config core docs scripts tests tasks.md architecture.md
```

提交当前版本：

```bash
git commit -m "Integrate MeetFlow M3 M4 M5 closed loop"
```

打本地版本标签：

```bash
git tag meetflow-m3-m4-m5-closed-loop-20260505
```

查看提交与标签：

```bash
git log --oneline -1
git tag --list 'meetflow-m3-m4-m5-*'
```

如需推送到远端：

```bash
git push
git push origin meetflow-m3-m4-m5-closed-loop-20260505
```

## 2. 基础本地验证

编译检查：

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py
```

全量单元测试：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests
```

重点回归测试：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_feishu_callback_dispatcher
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback tests.test_post_meeting_rag_query
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_risk_scan tests.test_risk_scan_card tests.test_storage_risk_notifications tests.test_risk_scan_workflow
```

工业化 P0 验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations tests.test_jobs
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --status
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py --once --dry-run
.venv-lark-oapi/bin/python -c "import scripts.feishu_event_sdk_server; print('sdk server import ok')"
```

离线 E2E 业务评测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0
```

写入评测报告：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py \
  --all \
  --fail-under 1.0 \
  --write-report
```

只跑单个评测 case：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py \
  --case m4_post_meeting_with_tasks \
  --fail-under 1.0
```

## 3. 飞书 SDK 长连接准备

安装独立 SDK 环境：

```bash
python3 scripts/setup_lark_oapi_venv.py
```

验证 SDK 可用：

```bash
.venv-lark-oapi/bin/python -c "import lark_oapi; print('lark_oapi ok')"
```

如首次授权、修改过 scope、或遇到权限不足，重新扫码授权：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/oauth_device_login.py
```

## 4. 启动回调服务

先用 dry-run 验证按钮回调，不创建任务：

```bash
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --dry-run --log-level debug
```

正式回调服务：

```bash
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --log-level info
```

如果要让 M3 按钮触发后台 Agent，但仍使用 dry-run LLM：

```bash
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --execute-agent --agent-provider dry-run --log-level info
```

如果要把 M3 按钮触发的后台 Agent 交给 `meetflow_worker.py` 异步执行：

```bash
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --enqueue-agent \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level info
```

另开一个终端启动 worker：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

确认允许真实写入后再使用：

```bash
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --execute-agent --allow-write --agent-provider configured --log-level info
```

## 5. M3 会前卡片测试

飞书里先创建测试日程：

```text
标题：MeetFlow 测试会议
时间：明天 10:00 - 10:30
参与人：添加你自己
描述：这是 MeetFlow M3 会前卡片测试会议
```

发送 M3 会前卡片：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-$(date +%Y%m%d%H%M%S)" \
  --write-report
```

只打印将执行命令，不真实发送：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date tomorrow \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "m3-test" \
  --write-report \
  --dry-run
```

群里检查 M3 卡片按钮：

```text
刷新背景
生成待办草案
发给我
```

## 6. M4 会后总结与待确认任务测试

先准备一条真实妙记。会议中建议明确说出待办：

```text
张三负责整理 MeetFlow 测试报告，明天下午六点前完成。
李四负责检查飞书卡片按钮回调，后天中午前完成。
```

先只读验证妙记是否能读到 AI 总结、待办或章节：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/minutes_live_test.py \
  --minute "你的飞书妙记URL或minute token"
```

只读验证 M4 是否能抽出 `action_items` 和 `pending_action_items`：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --read-only \
  --show-card-json \
  --content-limit 800
```

真实发送 M4 会后总结卡和待确认任务卡：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "你的飞书妙记URL或minute token" \
  --show-card-json
```

如果没有配置 `feishu.default_chat_id`：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m4 \
  --minute "你的飞书妙记URL或minute token" \
  --chat-id oc_xxx \
  --show-card-json
```

群里点击最新一张待确认任务卡：

```text
确认创建
修改信息
拒绝创建
```

不要点击旧卡片。重复发卡时，每次新卡会带新的 `review_session_id`，旧卡会提示使用最新卡片。

## 7. M4 到 M5 闭环检查

确认任务创建后，查看本地 task mapping：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT item_id, task_id, meeting_id, minute_token, title, source_url, updated_at FROM task_mappings ORDER BY updated_at DESC LIMIT 10;"
```

飞书里把刚创建的任务改成风险状态：

```text
1. 保持任务未完成
2. 把截止时间改成昨天，触发 overdue
3. 或把截止时间改成 24 小时内，触发 due_soon
```

运行 M5 风险巡检并发群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant
```

只入队、不立刻执行 M5 巡检：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant \
  --enqueue
```

再由 worker 消费：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues risk_scan \
  --once
```

如果没有配置默认测试群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/risk_scan_demo.py \
  --backend feishu \
  --show-card \
  --allow-write \
  --identity user \
  --send-identity tenant \
  --chat-id oc_xxx
```

群里检查 M5 卡片应包含：

```text
风险类型：已逾期 / 即将截止 / 长期未更新 / 缺少负责人
来源：M4 会后会议或行动项
妙记：minute token
证据：妙记片段
```

## 8. HTTP Fallback 可选测试

SDK 长连接不可用时，用公网 HTTPS fallback：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/feishu_event_server.py --host 0.0.0.0 --port 8765
```

HTTP fallback 也可以把后台 Agent 入队：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/feishu_event_server.py \
  --host 0.0.0.0 \
  --port 8765 \
  --enqueue-agent \
  --agent-provider dry-run
```

飞书后台回调 URL 配置：

```text
https://你的公网域名/feishu/card/actions
```

## 9. Daemon / Worker 工业化入口

只检查 daemon 会发现什么，不执行真实副作用：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py \
  --enable-m3 \
  --enable-m4 \
  --enable-rag \
  --enqueue \
  --once \
  --dry-run
```

长期运行推荐形态：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_daemon.py \
  --enable-m3 \
  --enable-m4 \
  --enable-rag \
  --enqueue \
  --poll-seconds 60
```

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

## 10. 常见问题快速判断

M3 找不到会议：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/calendar_live_test.py \
  --identity user \
  --calendar-id primary \
  --debug-calendar
```

M4 只有总结卡，没有待确认任务卡：

```text
检查 post_meeting_live_test --read-only --show-card-json 输出里是否有 action_items / pending_action_items。
如果飞书返回“当前没有返回 AI 总结、待办或章节”，说明该妙记没有可抽取任务，需要换一条有 AI 待办的妙记。
```

点击确认创建没有生成新任务：

```text
确认 SDK 回调不是 --dry-run。
确认点击的是最新发出的待确认任务卡。
重复执行 M4 发卡时，最新卡应带新的 review_session_id，旧卡点击会被拦截。
```

M5 没扫到风险：

```text
确认任务由 M4 确认创建产生。
确认 task_mappings 中有对应 task_id。
确认飞书任务仍未完成，并且截止时间已设置为过去或 24 小时内。
```
