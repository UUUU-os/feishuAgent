# MeetFlow 比赛演示资料 02：闭环架构与后台运行方式

> 这份文档用于 RAG 检索和 M3 背景卡演示。核心结论：MeetFlow 的价值来自事件驱动、任务队列、Agent Policy 和飞书卡片确认共同形成的闭环，而不是单个脚本串行调用。

## 1. 系统闭环

MeetFlow 的主链路是：

```text
飞书事件 / 日程扫描 / 卡片回调
  -> meetflow_daemon
  -> SQLite job queue
  -> meetflow_worker
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

这条链路保证：

- 事件不会只停留在日志中，而是进入可恢复的任务队列。
- 写操作不会绕过 AgentPolicy。
- 后台 worker 可以重试失败任务。
- 群卡片按钮可以把人工确认带回系统。

## 2. 一键启动入口

比赛演示推荐使用：

```bash
python3 scripts/meetflow_up.py \
  --sync-lark-cli \
  --force-subscribe \
  --allow-write \
  --chat-id oc_xxx \
  --m3-minutes-before 8 \
  --m4-delay-minutes 0 \
  --poll-seconds 10 \
  --risk-scan-seconds 120
```

参数解释：

| 参数 | 演示作用 |
| --- | --- |
| `--sync-lark-cli` | 启动前同步飞书应用配置 |
| `--force-subscribe` | 强制释放长连接单实例锁后重连 |
| `--allow-write` | 允许真实发送 M3/M4/M5 卡片 |
| `--chat-id` | 指定测试群，避免发到生产群 |
| `--m3-minutes-before 8` | 录屏时让 M3 更快触发 |
| `--m4-delay-minutes 0` | 日程结束后尽快扫描妙记 |
| `--risk-scan-seconds 120` | 风险扫描更快出现在录屏中 |

## 3. M3 会前背景卡逻辑

M3 的输入包括：

- 日程标题、描述、开始时间、参会人。
- RAG 中与项目相关的文档。
- 历史妙记中的决策和开放问题。
- 未完成任务和风险记录。

输出包括：

- 会议主题。
- 背景摘要。
- 待读资料。
- 当前需要确认的问题。
- 风险提示。
- 资料链接和刷新按钮。

演示关键词建议包含：`M3 背景卡`、`RAG 更新`、`M4 会后总结`、`任务风险`。

## 4. M4 会后总结卡逻辑

M4 的输入优先来自会议妙记，内容包括：

- 会议决策。
- 待办事项。
- 负责人。
- 截止时间。
- 开放问题。

M4 不直接盲目创建任务，而是生成带按钮的会后卡片：

- 字段完整的待办：可以点击创建任务。
- 缺负责人或截止时间的待办：进入人工补全。
- 明确不是待办的结论：只展示，不创建任务。
- 拒绝的待办：记录状态，避免重复打扰。

## 5. M5 风险巡检逻辑

M5 定期扫描任务快照，识别：

- 已逾期但未完成。
- 即将到期但无人更新。
- 长时间没有进展。

风险卡应包含：

- 风险类型。
- 任务标题。
- 负责人。
- 截止时间。
- 来源会议或妙记链接。
- 建议动作。

## 6. 录屏时可讲的技术亮点

1. 飞书事件进入队列，避免脚本断掉后丢事件。
2. RAG 文档更新能被索引刷新任务捕捉。
3. 所有写操作经过 AgentPolicy 和人工确认。
4. M4 任务能回链到妙记证据，M5 风险能继续使用这条证据链。
5. 系统支持从单点 Demo 走向后台常驻服务。

