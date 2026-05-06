# MeetFlow 比赛录屏 Runbook

> 目标：用真实飞书云文档、真实飞书会议、真实妙记和真实群卡片展示 MeetFlow Agent 闭环。

## 1. 已创建的真实飞书文档

这些文档已创建在你的飞书云文档中，可作为 RAG 基础数据和录屏展示材料。

| 用途 | 文档 | URL |
| --- | --- | --- |
| 产品目标与验收指标 | MeetFlow 比赛演示资料 01 | https://jcneyh7qlo8i.feishu.cn/docx/WVlhdN0tYoimGaxHtRIcXzQEnMe |
| 闭环架构与后台运行方式 | MeetFlow 比赛演示资料 02 | https://jcneyh7qlo8i.feishu.cn/docx/A8mwd3WSWo7mRQxqtpzcLEU2nWg |
| 测试场景、风险与验收脚本 | MeetFlow 比赛演示资料 03 | https://jcneyh7qlo8i.feishu.cn/docx/ZSsmdnNKtodH1BxSRPxcmRe7n6f |
| 历史会议纪要与待办追踪 | MeetFlow 比赛演示资料 04 | https://jcneyh7qlo8i.feishu.cn/docx/E7uqdyyqfoD9x6xyVh5ch7QMnoe |
| 两人会议录制脚本 | MeetFlow 比赛演示会议脚本 | https://jcneyh7qlo8i.feishu.cn/docx/ZJWIdlcluonex5xy3TpcBh9MnKf |

本地备份在：

```text
storage/demo_materials/meetflow_demo_doc_01_prd.md
storage/demo_materials/meetflow_demo_doc_02_architecture.md
storage/demo_materials/meetflow_demo_doc_03_risks_and_tests.md
storage/demo_materials/meetflow_demo_doc_04_previous_minutes.md
storage/demo_materials/meetflow_demo_meeting_script.md
```

## 2. 一键启动命令

把 `oc_xxx` 替换成你的测试群 chat_id，然后运行：

```bash
python3 scripts/meetflow_up.py \
  --sync-lark-cli \
  --force-subscribe \
  --allow-write \
  --chat-id oc_xxx \
  --m3-minutes-before 8 \
  --m4-delay-minutes 0 \
  --poll-seconds 10 \
  --risk-scan-seconds 120 \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/WVlhdN0tYoimGaxHtRIcXzQEnMe" \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/A8mwd3WSWo7mRQxqtpzcLEU2nWg" \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/ZSsmdnNKtodH1BxSRPxcmRe7n6f" \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/E7uqdyyqfoD9x6xyVh5ch7QMnoe"
```

这条命令会先做 RAG 文档索引和订阅，再启动：

- 飞书长连接事件监听。
- M3/M4/RAG daemon。
- 后台 worker。
- M4 卡片按钮回调。
- M5 风险扫描定时入队。

停止方式：启动终端按 `Ctrl+C`。

## 3. 录屏顺序

### 3.1 展示基础数据

打开 4 份 RAG 文档，说明它们是系统的知识基础：

- 产品目标。
- 架构和后台闭环。
- 测试场景和风险。
- 历史会议纪要。

### 3.2 启动系统

在终端运行“一键启动命令”。录屏时重点展示：

- `M3: 开启`
- `M4: 开启`
- `M5: 开启`
- `RAG: 开启`
- `写操作: 真实执行`
- `启动前索引/订阅文档: 4 篇`

### 3.3 演示 RAG 文档变化

在飞书里打开第三份文档：

```text
https://jcneyh7qlo8i.feishu.cn/docx/ZSsmdnNKtodH1BxSRPxcmRe7n6f
```

追加一句：

```text
录屏测试：RAG 已捕捉到文档变化，并将 M4 触发策略更新为日程结束后立即扫描妙记。
```

回到终端观察文档事件或 RAG pending 任务变化。

可查询：

```bash
sqlite3 storage/knowledge/knowledge.sqlite \
  "SELECT job_id,resource_id,resource_type,reason,status,last_error,datetime(updated_at,'unixepoch','localtime') FROM index_jobs ORDER BY updated_at DESC LIMIT 10;"
```

### 3.4 创建会议并演示 M3

在飞书日历中新建会议：

- 标题：`MeetFlow 比赛演示评审会`
- 开始时间：当前时间后 10 到 12 分钟。
- 时长：15 分钟。
- 描述：`评审 M3 会前背景、M4 会后总结、M5 风险巡检和 RAG 文档更新闭环。`
- 邀请你的同学。

因为启动命令用了 `--m3-minutes-before 8`，理论上会议开始前约 8 分钟会向测试群发送 M3 会前背景卡。

### 3.5 录制真实会议并生成妙记

打开会议脚本文档：

```text
https://jcneyh7qlo8i.feishu.cn/docx/ZJWIdlcluonex5xy3TpcBh9MnKf
```

你和同学按脚本自然对话。建议保持 8 到 12 分钟，必须开启录制和妙记。

会议中要清楚说出三条待办：

- 张三负责整理 M4 效果测试报告，截止明天 18 点前完成。
- 李四负责补充 RAG 文档更新说明，截止本周五前完成。
- 张三负责验证 M4 卡片按钮能真实创建和拒绝任务，截止今天下班前完成。

### 3.6 演示 M4

会议结束后，等日程结束，系统会用 `--m4-delay-minutes 0` 尽快扫描妙记。

M4 卡片应在测试群中展示：

- 决策。
- 开放问题。
- 待办。
- 创建任务 / 拒绝任务按钮。

录屏操作建议：

1. 对第一条待办点击创建任务。
2. 对第二条待办点击创建任务。
3. 对第三条待办点击拒绝，展示系统不会盲目创建所有任务。

### 3.7 演示 M5

M5 需要有任务风险才更明显。可选两种方式：

方案 A：用已有逾期任务演示。

方案 B：创建一个测试任务，截止时间设置为过去时间或很近的时间，然后等待 `--risk-scan-seconds 120` 扫描。

风险卡应展示：

- 风险类型。
- 任务标题。
- 负责人。
- 来源妙记或任务映射证据。

## 4. 妙记生成说明

目前飞书开放接口通常支持查询、下载、读取妙记产物，但不能直接“写入一份官方妙记文本”来伪造真实妙记。

最稳的录屏方式是：

1. 在飞书日历里创建真实会议。
2. 进入会议后开启录制。
3. 两个人按脚本文档对话 8 到 12 分钟。
4. 结束会议。
5. 等待飞书生成妙记。
6. 让 MeetFlow 通过日程和 `vc +recording` 找到对应 `minute_token`。

如果飞书短会只生成文字记录，没有 AI 总结，也仍然可以用于测试；关键是文本里要有明确“负责人 + 截止时间”的待办表达。

## 5. 备用手动 M4 命令

如果自动 M4 因妙记延迟没有及时触发，可以拿到妙记 URL 后手动触发：

```bash
python3 scripts/card_send_live.py m4 \
  --minute "https://jcneyh7qlo8i.feishu.cn/minutes/你的-minute-token" \
  --allow-card-send
```

## 6. 备用 M3 命令

如果 M3 自动触发窗口错过，可以手动指定会议标题和文档：

```bash
python3 scripts/pre_meeting_live_test.py \
  --identity user \
  --event-title "MeetFlow 比赛演示评审会" \
  --project-id meetflow \
  --allow-write \
  --force-index \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/WVlhdN0tYoimGaxHtRIcXzQEnMe" \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/A8mwd3WSWo7mRQxqtpzcLEU2nWg" \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/ZSsmdnNKtodH1BxSRPxcmRe7n6f" \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/E7uqdyyqfoD9x6xyVh5ch7QMnoe"
```

## 7. 录屏讲解词

可以这样解释：

```text
现在我启动的是 MeetFlow 的一键后台服务。它会先把项目云文档加入 RAG 并订阅变更，然后监听飞书日程和文档事件。接下来我只在飞书里操作：修改文档、创建会议、开会生成妙记、点击卡片按钮。系统会自动在会前生成背景卡，会后生成总结和待确认任务，并持续扫描任务风险。整个过程不是单个 API demo，而是一个有事件、有队列、有人工确认、有风险回链的闭环 Agent。
```

