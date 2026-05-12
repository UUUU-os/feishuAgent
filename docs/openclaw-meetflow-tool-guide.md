# MeetFlow CLI / OpenClaw 使用手册

本文档说明如何通过统一 CLI 入口把 MeetFlow 的 M3/M4/M5、评测和服务控制能力交给 OpenClaw 或命令行演示调用。

统一入口：

```bash
python3 scripts/meetflow_cli.py <command> [options]
```

所有命令默认是 dry-run。任何会发送飞书卡片、读取真实飞书任务并发送提醒的操作，都必须显式传入 `--allow-write`。

真实飞书联调前建议先确认：

```bash
python3 scripts/meetflow_cli.py health
python3 scripts/oauth_device_login.py
```

如果 `health` 里 `feishu_config_present=false` 或 OAuth token 失效，先补齐本地
`config/settings.local.json` 并完成用户授权。真实写入请只使用测试群。

## 1. CLI 命令功能总览

| CLI 命令 | 功能 | 典型场景 | 写入说明 |
|---|---|---|---|
| `python3 scripts/meetflow_cli.py health` | 检查配置、storage、migration、服务状态 | 联调前自检 | 无真实写入 |
| `python3 scripts/meetflow_cli.py pre-meeting ...` | 生成/发送 M3 会前背景知识卡 | 会前卡片演示 | 默认 dry-run，真实发卡需 `--allow-write` |
| `python3 scripts/meetflow_cli.py post-meeting ...` | 生成/发送 M4 会后总结卡 | 会后总结演示 | 默认 dry-run，真实发卡需 `--allow-write` |
| `python3 scripts/meetflow_cli.py task-cards ...` | 从妙记生成任务卡视角 | 展示待办识别与任务卡 | 默认 dry-run，真实发卡需 `--allow-write` |
| `python3 scripts/meetflow_cli.py risk-scan ...` | 执行 M5 任务风险提醒 | 任务风险提醒卡、逾期任务扫描 | 默认 dry-run，真实发送需 `--allow-write` |
| `python3 scripts/meetflow_cli.py eval ...` | 运行 Agent 评测 | 验证工具调用、安全边界 | 无真实飞书写入 |
| `python3 scripts/meetflow_cli.py demo-replay ...` | 运行离线 Demo 回放 | 无网络或答辩兜底 | 无真实飞书写入 |
| `python3 scripts/meetflow_cli.py live sdk-callback` | 启动飞书 SDK 回调服务 | D3 点击按钮真实联调终端 1 | 前台长进程，不直接发卡 |
| `python3 scripts/meetflow_cli.py live worker` | 启动 workflow/risk/rag worker | D3 点击按钮真实联调终端 2 | 前台长进程，处理队列任务 |
| `python3 scripts/meetflow_cli.py live d3-card ...` | 重新发送 D3 会后总结卡 | D3 点击按钮真实联调终端 3 | 真实发卡；加 `--dry-run` 只打印命令 |
| `python3 scripts/meetflow_cli.py live watch-callbacks` | 观察卡片回调与工作流日志 | D3 点击按钮真实联调终端 4 | 前台 tail 日志 |
| `python3 scripts/meetflow_cli.py service ...` | 管理白名单后台服务 | 查看、停止、查日志 | 仅允许预定义服务名 |
| `python3 scripts/meetflow_cli.py openclaw-tools` | 输出 OpenClaw 工具清单 | 注册外部工具能力 | 无真实写入 |

优先演示 D3 按钮链路时，直接按下一节四个终端运行即可。

## 2. D3 四终端真实联调快捷命令

如果要复现“发送一张新的 D3 会后总结卡，然后点击三个按钮观察回调”的真实链路，可以按四个终端运行。

注意：SDK 回调和 M4 专用回调只启动一个。下面推荐启动 SDK 回调。

### 终端 1：SDK 回调服务

原始命令等价于：

```bash
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py \
  --enqueue-agent \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level debug
```

CLI 快捷命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_cli.py live sdk-callback
```

可选参数：

```bash
python3 scripts/meetflow_cli.py live sdk-callback \
  --agent-provider dry-run \
  --job-queue workflow \
  --log-level debug
```

### 终端 2：Worker

原始命令等价于：

```bash
python3 scripts/meetflow_worker.py \
  --queues workflow,risk_scan,rag_refresh \
  --poll-seconds 2
```

CLI 快捷命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_cli.py live worker
```

### 终端 3：重新发送 D3 会后总结卡

不指定群，使用配置默认测试群：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_cli.py live d3-card \
  --minute "obcngy8e7x2883b6f9f5x4l9" \
  --show-card-json
```

指定测试群：

```bash
python3 scripts/meetflow_cli.py live d3-card \
  --minute "obcngy8e7x2883b6f9f5x4l9" \
  --chat-id "你的测试群chat_id" \
  --receive-id-type chat_id \
  --show-card-json
```

这个命令固定包装：

```bash
python3 scripts/card_send_live.py m4 \
  --minute "..." \
  --identity user \
  --report-dir storage/reports/m4/d3 \
  --show-card-json
```

如果只想打印下游命令，不发送卡片：

```bash
python3 scripts/meetflow_cli.py live d3-card \
  --minute "obcngy8e7x2883b6f9f5x4l9" \
  --show-card-json \
  --dry-run
```

### 终端 4：观察点击结果

原始命令等价于：

```bash
tail -n 0 -f storage/card_callbacks.jsonl storage/workflow_events.jsonl
```

CLI 快捷命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_cli.py live watch-callbacks
```

点击飞书卡片按钮后，重点观察：

```text
view_pending_tasks_sent
start_action_item_risk_preview_sent
view_post_meeting_report_sent
```

如果点击后没有日志，优先检查终端 1 的 SDK 回调是否仍在运行，以及飞书开放平台回调订阅是否指向当前应用。

## 3. 输出格式

CLI 只输出 JSON，核心字段固定：

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

OpenClaw 可以根据 `status` 判断是否成功，根据 `workflow_type` 区分业务流程，根据 `report_path` 打开报告，根据 `safety_summary` 展示安全边界。

## 4. 环境检查

```bash
python3 scripts/meetflow_cli.py health
```

用途：

- 检查 storage 和 migration。
- 检查服务状态。
- 检查飞书配置是否存在。
- 检查当前 LLM provider 名称。

该命令不访问真实飞书写接口。

## 5. M3 会前背景知识卡

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

真实发卡：

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

真实飞书完整演示命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_cli.py pre-meeting \
  --date today \
  --event-title "你的会议标题关键词" \
  --provider settings \
  --project-id meetflow \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/YGY5dOFrMoVu5Ox7DJnc7AaSnyb" \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --idempotency-suffix "m3-cli-live-20260512-01" \
  --allow-write \
  --write-report
```

如果要直接验证底层真实发卡脚本，可使用等价入口：

```bash
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

- 下游固定走 `scripts/card_send_live.py m3`。
- 未传 `--allow-write` 时会自动向下游追加 `--dry-run`。
- 真实发卡必须带幂等后缀；未传时 CLI 会自动生成。
- `--doc` 和 `--minute` 会进入会前 RAG / Evidence Pack。

## 6. M4 会后总结卡

Dry-run：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

真实发卡：

```bash
python3 scripts/meetflow_cli.py post-meeting \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --chat-id "<测试群 chat_id>" \
  --allow-write
```

真实飞书完整演示命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
python3 scripts/meetflow_cli.py post-meeting \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --identity user \
  --chat-id "<测试群 chat_id>" \
  --content-limit 300 \
  --related-top-n 5 \
  --allow-write
```

等价底层入口：

```bash
python3 scripts/card_send_live.py m4 \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --identity user \
  --chat-id "<测试群 chat_id>" \
  --content-limit 300 \
  --related-top-n 5
```

如果不传 `--chat-id`，底层会尝试使用 `config/settings.local.json` 中的
`feishu.default_chat_id`。演示时建议显式传测试群，避免误发。

说明：

- 下游固定走 `scripts/card_send_live.py m4`。
- 默认只打印将执行的命令。
- 真实发卡时仍由现有 M4 链路处理负责人解析、任务卡和回调 value。

## 7. D4 任务卡视角

```bash
python3 scripts/meetflow_cli.py task-cards \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9"
```

真实发送任务卡和会后总结卡：

```bash
python3 scripts/meetflow_cli.py task-cards \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/obcngy8e7x2883b6f9f5x4l9" \
  --chat-id "<测试群 chat_id>" \
  --allow-write
```

该命令复用 M4 链路，不直接写 `pending_actions` 或任务表。输出会突出 `pending_action_count` 和 `action_item_count`，方便答辩单独展示“从妙记到任务卡”的能力。

## 8. M5 任务风险提醒

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
  --chat-id "<测试群 chat_id>" \
  --allow-write \
  --show-card
```

真实飞书完整演示命令：

```bash
cd /home/good/ye/workhard/feishuAgent-d3-post-meeting-card-enhancement-plan
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

等价底层入口：

```bash
python3 scripts/risk_scan_demo.py \
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

入队模式需要 worker 运行。D3 真实联调时直接使用本文开头“终端 2：Worker”的快捷命令即可。

## 9. Agent 评测

```bash
python3 scripts/meetflow_cli.py eval \
  --suite agent_trajectory \
  --provider scripted_debug \
  --fail-under 0.95 \
  --write-report
```

输出包含 `score`、`safety_score`、`passed_threshold` 和 `report_path`。

## 10. 离线 Demo 回放

```bash
python3 scripts/meetflow_cli.py demo-replay \
  --all \
  --fail-under 1.0 \
  --write-report
```

适合无飞书网络、无 token 或答辩兜底时使用。

## 11. 其他服务控制

列出服务：

```bash
python3 scripts/meetflow_cli.py service list
```

查看日志：

```bash
python3 scripts/meetflow_cli.py service logs worker --tail 100
```

停止服务：

```bash
python3 scripts/meetflow_cli.py service stop worker
```

服务命令只允许 `core/service_manager.py` 中的白名单服务名和 profile，不接受任意命令。

## 12. OpenClaw 工具清单

查看工具清单：

```bash
python3 scripts/meetflow_cli.py openclaw-tools
```

默认读取：

```text
config/openclaw_tools.example.json
```

OpenClaw 可把其中的 `meetflow_health`、`meetflow_pre_meeting`、`meetflow_post_meeting`、`meetflow_task_cards`、`meetflow_risk_scan`、`meetflow_eval`、`meetflow_demo_replay` 注册为外部工具。

## 13. 安全边界

- CLI 默认 dry-run。
- 真实写操作必须显式 `--allow-write`。
- CLI 不直接调用 `FeishuClient.send_*` 或 `FeishuClient.create_*`。
- CLI 不直接写业务 SQLite 表伪造结果。
- CLI 不提供任意 shell 命令或 Python 表达式入口。
- CLI 输出会脱敏 token、secret、refresh token、API key 和 Authorization Bearer。
- 写链路继续走现有 AgentPolicy、幂等和白名单脚本。
