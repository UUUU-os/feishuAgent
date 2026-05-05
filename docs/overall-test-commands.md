# MeetFlow 整体测试命令总表

本文档是 MeetFlow 后续每次代码改动后的测试入口。目标是让项目从“能跑 demo”变成“有固定质量闸口”。

每次修改代码后都要先判断：本文件里的命令是否仍覆盖新增/修改的行为。如果新增脚本、配置、队列、回调、评测 case 或真实联调路径，必须同步更新本文档。

LLM Agent 评测体系的指标、报告 schema 和落地计划见
[MeetFlow LLM Agent 评测系统方案](llm-agent-evaluation-system-plan.md)。

## 0. 维护规则

需要更新本文档的情况：

```text
新增或删除 scripts/*.py 入口
新增或删除 config/settings.example.json 配置项
新增数据库表、字段、migration 或队列 job_type
新增飞书权限 scope、OAuth 行为或回调路径
新增 M3/M4/M5 工作流能力或卡片按钮
新增评测 fixture、LLM provider、fallback 或部署方式
修改真实测试命令的参数名、默认值或安全开关
```

不需要更新本文档的情况：

```text
纯内部重构，所有命令仍完全相同
只改注释或文档措辞
只修复测试断言但不改变运行入口
```

## 1. 基础无副作用检查

```bash
cd /home/tanyd/ye/workhard/feishuAgent-main
```

Python 环境约定：

```text
主业务环境：/home/tanyd/anaconda3/envs/meetflow/bin/python
飞书 SDK 隔离环境：/home/tanyd/ye/workhard/feishuAgent-main/.venv-lark-oapi/bin/python
```

主业务环境用于 `core/`、`adapters/`、`scripts/meetflow_worker.py`、HTTP fallback
和所有单元测试。飞书 SDK 隔离环境只用于 `scripts/feishu_event_sdk_server.py`，
它单独安装 `lark-oapi` 和 `protobuf<4`，避免污染主环境。

注意：不要用系统 `python3` 创建 `.venv-lark-oapi`。如果系统 Python 是 3.8，
会触发 `dataclass(slots=True)` 兼容性错误；必须用主 `meetflow` 环境的
Python 3.10 创建或重建。

编译检查：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py
```

全量单元测试：

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

## 2. 工业化基础设施检查

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

写入评测报告：

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

写入 Agent 轨迹评测报告：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_eval_suite.py \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

这组命令重点检查：

```text
Agent 是否按预期调用工具
是否满足先读后写、先解析负责人再建任务等顺序约束
写操作是否有 Policy 轨迹
未授权写操作是否被阻止
评测报告中是否没有 token / secret / API key
```

## 3. SDK / 回调入口检查

准备或修复 SDK 隔离环境：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py
```

如果之前执行过 `python3 scripts/setup_lark_oapi_venv.py`，或遇到
`.venv-lark-oapi/bin/python: No such file or directory`、Python 3.8 下的
`dataclass(slots=True)` 兼容性错误，用主环境重建：

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

## 4. Worker / Daemon 检查

启动长期 worker：

```bash
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

## 5. OAuth / 飞书基础读检查

重新扫码授权：

```bash
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

## 6. M3 会前卡片真实测试

飞书里先创建测试日程：

```text
标题：MeetFlow 测试会议
时间：明天 10:00 - 10:30
参与人：添加你自己
描述：这是 MeetFlow M3 会前卡片测试会议
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

## 7. M4 会后总结与待确认任务测试

只读验证：

```bash
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
确认创建 / 保存修改 / 拒绝创建 按钮
```

M4 按钮确认闭环回归：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_card_actions \
  tests.test_post_meeting_card_callback
```

这组命令重点检查：

```text
confirm_create_task / edit_task_fields / reject_create_task 是否被 CardActionRouter 识别
保存修改后点击确认是否能复用 registry 中已补字段
review_session_id 是否进入幂等键和 SQLite review_sessions 审计
重复发卡后旧卡是否被拦截，新卡是否可重新确认
```

## 8. M5 风险巡检测试

直接执行并允许发送：

```bash
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

## 9. SQLite 排查命令

查看 job queue：

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

查看 migration：

```bash
sqlite3 storage/meetflow.sqlite \
  "SELECT version,name,applied_at FROM schema_migrations ORDER BY version;"
```

## 10. 提交前检查

确认没有把本地密钥和运行产物加入暂存区：

```bash
git status --short
git check-ignore -v config/settings.local.json .venv-lark-oapi storage/reports storage/meetflow.sqlite storage/workflow_events.jsonl
```

建议提交前跑：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py

/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0
```

## 11. 改动类型到测试范围

```text
只改纯函数/模型：
  跑 py_compile + 对应 unittest + 全量 unittest

改 storage/migration/jobs：
  跑 tests.test_migrations tests.test_jobs + storage_migrate --verify + worker --dry-run

改 M3：
  跑 M3 相关单测 + e2e_replay m3_pre_meeting_basic + M3 真实发卡

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
