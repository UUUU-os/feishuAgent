# MeetFlow 开发任务索引

本文档是 MeetFlow 任务拆解的入口索引。详细任务、实现记录和验证结果已按里程碑拆分到 `docs/tasks/`，避免单个 `tasks.md` 过长难以维护。

## 文档目标

这些任务文档用于将 `MeetFlow - 飞书会议知识闭环 Agent` 的 PRD 和架构方案拆解为可执行的开发任务清单，方便团队按阶段推进开发、联调、验证和答辩准备。

任务文档强调四件事：

- 先做什么，后做什么
- 每个模块需要完成哪些任务
- 每项任务完成的验收标准是什么
- 哪些任务是 Demo 必做，哪些是增强项

## 开发原则

- 优先跑通主链路，不先追求大而全
- 优先实现“会前 - 会后 - 巡检”闭环
- 优先保证结构化输出和证据链
- 优先保证任务可演示、可验收、可回放

## 优先级说明

- `P0`：必须完成，缺失会导致 Demo 主链路无法成立
- `P1`：重要增强，影响稳定性、可解释性和答辩效果
- `P2`：可选增强，适合有余力时补充

## 里程碑文档

- [M1：项目骨架与基础设施](docs/tasks/m1-foundation.md)
- [M2：飞书接入与数据读取](docs/tasks/m2-feishu-integration.md)
- [M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md)
- [M3：会前知识卡片工作流](docs/tasks/m3-pre-meeting.md)
- [M4：会后总结与任务落地工作流](docs/tasks/m4-post-meeting.md)
- [M5：风险巡检与提醒工作流](docs/tasks/m5-risk-scan.md)
- [M6：评估、答辩材料与演示脚本](docs/tasks/m6-evaluation-demo.md)
- [技术拆分、依赖关系、开发顺序与验收总表](docs/tasks/planning-and-acceptance.md)

## 当前重点

当前开发重点已切到 [M4：会后总结与任务落地工作流](docs/tasks/m4-post-meeting.md) 的 Agent 化收口。

M4 的当前核心边界是让 `minute.ready` 回到 MeetFlow 主 Agent 链路，而不是由会后脚本直接串联所有逻辑：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

当前 M4 Agent 化重点：

- `PostMeetingFollowupWorkflow.prepare_context()` 暴露 M4 结构化上下文
- 注册 `post_meeting.*` 工具给 Agent Loop 使用
- 用 `scripted_debug` 验证读妙记、构造 artifacts、RAG、人员解析、任务参数准备、发卡和待确认 registry 保存
- 所有写操作继续经过 `AgentPolicy`

最近进展：

- 2026-05-04：新增 `scripts/live_environment_watch.py` 作为真实环境观察台。脚本会启动 `lark-cli event +subscribe` 长连接，默认监听 `calendar.calendar.event.changed_v4`、`drive.file.edit_v1`、`drive.file.title_updated_v1`、`drive.file.bitable_record_changed_v1`、`drive.file.bitable_field_changed_v1`，并把收到的事件、匹配到的文档 token/日程实例、RAG 索引任务状态、M3/M4 发卡触发意图逐步打印出来。支持 `--doc` 首次接入并订阅云文档，默认真实刷新本地 RAG 索引但不真实发 M3/M4 卡片；需要发卡时显式传 `--allow-card-send`。针对本地 `lark_oapi` 与 `chromadb/sentence_transformers` 分属不同环境的问题，脚本新增 `--python-bin` 和 `--lark-cli-bin`，并会在启用 RAG 时自动重启到包含 RAG 依赖的 Python。验证通过：`python3 -m py_compile scripts/live_environment_watch.py`；`python3 scripts/live_environment_watch.py --help`；`.venv-lark-oapi/bin/python scripts/live_environment_watch.py --help`。
- 2026-05-04：修正真实环境观察台的 RAG 事件可观察性噪声。用户手动编辑云文档后，观察台启动阶段的兜底扫描会处理历史遗留 pending job，导致 `workflow_demo_m3_rag`、`knowledge_tool_doc`、`knowledge_demo_minute` 等 demo token 被误拿去请求飞书并报 400。已调整 `scripts/live_environment_watch.py`：默认只处理本次启动后由长连接事件写入的 `reason=event` 任务，历史 pending job 只统计跳过；如需清理历史任务再显式传 `--process-existing-rag-jobs`。同时调整 `core/knowledge.py` 的 `get_event_subscription()`，支持用飞书事件里的底层 `file_token` 反查首次接入时保存的 wiki/doc 订阅记录。验证通过：`python3 -m py_compile core/knowledge.py scripts/live_environment_watch.py`；`python3 -m unittest tests.test_post_meeting_rag_query tests.test_post_meeting_card_callback`。
- 2026-05-04：增强 `scripts/live_environment_watch.py` 的长连接错误诊断。`lark-cli event +subscribe` 退出时，脚本现在会继续读取并打印剩余 stdout/stderr，避免只显示第一行 `{` 而看不到真正错误；新增 `--force-subscribe`，用于确认没有其他监听进程时绕过 `lark-cli` 单实例锁或上次异常退出留下的锁。验证通过：`python3 -m py_compile scripts/live_environment_watch.py`；`python3 scripts/live_environment_watch.py --help`。
- 2026-05-04：补齐日程长连接事件订阅前置步骤。飞书 `calendar.calendar.event.changed_v4` 要求先以用户身份调用 `POST /calendar/v4/calendars/{calendar_id}/events/subscription` 对具体日历建立订阅关系；否则新增/修改日程只能被 `poll-seconds` 兜底扫描发现。`adapters/feishu_client.py` 新增 `subscribe_calendar_event_changes()`，`scripts/live_environment_watch.py` 启用 M3/M4 时会自动订阅日程变更，并提供 `--skip-calendar-subscribe` 跳过；`scripts/meetflow_daemon.py` 启动时也会确保订阅，失败则记录 warning 并继续依赖扫描兜底。验证通过：`python3 -m py_compile adapters/feishu_client.py scripts/live_environment_watch.py scripts/meetflow_daemon.py`；`python3 -m unittest tests.test_post_meeting_rag_query tests.test_post_meeting_card_callback`。
- 2026-05-04：定位长连接仍收不到事件的根因：`FeishuClient` 使用项目配置 `settings.feishu.app_id=cli_a96606adf978dbc4` 建立云文档/日历订阅，而 `lark-cli event +subscribe` 读取的是全局配置 `cli_a966c79ea3b89bd4`，两者不是同一个飞书应用，所以事件被投递到订阅所属应用，观察台连在另一个应用上自然收不到。新增 `scripts/sync_lark_cli_config.py`，可由用户本机执行 `python3 scripts/sync_lark_cli_config.py --yes` 将 lark-cli 配置同步到项目当前 app；`scripts/live_environment_watch.py` 启动前新增 app_id 一致性检查，不一致时直接退出并给出修复命令，可用 `--skip-lark-cli-app-check` 跳过。验证通过：`python3 -m py_compile scripts/live_environment_watch.py scripts/sync_lark_cli_config.py`；`python3 scripts/sync_lark_cli_config.py`；`python3 scripts/live_environment_watch.py --no-rag --duration-seconds 1` 能正确拦截 app_id 不一致。
- 2026-05-04：实现 RAG“首次手动添加文档后自动监听更新”的长连接主路径。`adapters/feishu_client.py` 新增 `subscribe_drive_file()` 和文档 file_type 推断；`core/knowledge.py` 新增 `knowledge_event_subscriptions` 表和订阅状态读写接口；`scripts/rag_add_document_live.py` 新增首次接入入口，读取文档、建立索引并调用 `drive/v1/files/{file_token}/subscribe`；`scripts/pre_meeting_live_test.py` 在 M3 手动传 `--doc` 并索引成功后也会自动订阅云文档事件。`scripts/meetflow_daemon.py` 现在收到 `drive.file.*` / `bitable.*` 事件会优先为对应 file_token 写入 `index_jobs(reason=event)` 并处理 pending 刷新任务；定时扫描保留为兜底。验证通过：`python3 -m py_compile adapters/feishu_client.py core/knowledge.py scripts/pre_meeting_live_test.py scripts/meetflow_daemon.py scripts/rag_add_document_live.py`；`python3 scripts/rag_add_document_live.py --help`；`lark-cli event +subscribe --event-types drive.file.edit_v1,drive.file.title_updated_v1,drive.file.bitable_record_changed_v1 --compact --quiet --as bot --dry-run`。
- 2026-05-04：解决 M3/M4/RAG 后台监控服务的首版落地问题。新增 `scripts/meetflow_daemon.py`，采用“飞书事件长连接唤醒 + 定时扫描兜底”架构：M3 扫描主日历并在会议开始前 `m3_minutes_before` 窗口触发 `card_send_live.py m3`；M4 扫描已结束会议，等待 `m4_delay_minutes` 后通过 `lark-cli vc +recording --calendar-event-ids` 查询 `minute_token`，再触发 `card_send_live.py m4`；RAG 定时调用 `enqueue_recent_document_refresh_jobs()` 并重新拉取最近索引过的文档/妙记执行增量刷新。脚本支持 `--event-stdin` 从 `lark-cli event +subscribe` 接收 NDJSON 事件唤醒，支持 `--dry-run` 和 `--once`。同步更新 [架构说明](architecture.md)。验证通过：`python3 -m py_compile scripts/meetflow_daemon.py`；`python3 scripts/meetflow_daemon.py --help`。
- 2026-05-04：修复 M3 真实联调脚本查不到当天新建会议时诊断不足的问题。`scripts/pre_meeting_live_test.py` 新增 `--date today|tomorrow|YYYY-MM-DD`，按本地整天窗口查询日程；空结果和标题未匹配错误现在会打印 `calendar_id`、`identity` 和格式化后的查询窗口，并提示个人日历优先使用 `--identity user`。`scripts/card_send_live.py m3` 同步透传 `--date`。验证通过：`python3 -m py_compile scripts/pre_meeting_live_test.py scripts/card_send_live.py`；`python3 scripts/pre_meeting_live_test.py --help`；`python3 scripts/card_send_live.py m3 --event-title '飞书比赛' --date today --identity user --idempotency-suffix feishu-game-20260504 --dry-run`。已用只读真实探针确认今天的 `飞书比赛` 日程可被选中，event_id=`575d52fb-b58e-495f-a6c0-35fd50274157_0`。
- 2026-05-04：新增 `scripts/card_send_live.py`，作为 M3/M4 真实发卡统一入口。`m3` 子命令封装 `pre_meeting_live_test.py --allow-write --enable-idempotency`，默认使用 `scripted_debug` 避免真实 LLM 接收飞书内容；`m4` 子命令封装 `post_meeting_live_test.py --allow-write --send-card`；`m4-callback` 子命令封装按钮回调长连接。验证通过：`python3 -m py_compile scripts/card_send_live.py`；`python3 scripts/card_send_live.py --help`；`python3 scripts/card_send_live.py m3 --help`；`python3 scripts/card_send_live.py m4 --help`；`python3 scripts/card_send_live.py m4-callback --help`；并用 `--dry-run/--print-only` 确认会展开为正确底层真实发送命令。
- 2026-05-04：新增 `scripts/card_preview_demo.py`，作为 M3/M4 卡片效果统一本地预览入口。脚本默认同时生成 M3 会前卡、M4 会后总结卡、M4 待确认总卡和 M4 单任务按钮卡；支持 `--workflow m3|m4|both`、`--print-json` 和 `--output-dir`，全程不读取飞书、不发送消息、不创建任务，适合检查卡片 JSON 结构和做前后 diff。
- 2026-05-04：完成 M3/M4 卡片基础格式收口与 M4 RAG query 优化。新增 `cards/layout.py` 固定 MeetFlow 卡片外壳，`cards/pre_meeting.py`、`cards/post_meeting.py` 改为复用统一 header/config/body 骨架；新增 `RelatedKnowledgeQueryPlan` 与 `build_post_meeting_related_resource_query_plan()`，M4 会后相关知识召回从长句拼接改为按来源加权提取业务关键词，并把 `query_plan` 写入工具返回和 artifacts 审计字段。同步更新 [M3 任务文档](docs/tasks/m3-pre-meeting.md) 和 [M4 任务文档](docs/tasks/m4-post-meeting.md)。验证命令：`python3 -m py_compile cards/layout.py cards/pre_meeting.py cards/post_meeting.py core/post_meeting.py core/post_meeting_tools.py core/__init__.py tests/test_post_meeting_rag_query.py tests/test_post_meeting_card_callback.py`；`python3 -m unittest tests.test_post_meeting_rag_query tests.test_post_meeting_card_callback`。
- 2026-05-02：修复 M4 待确认卡片按钮重复/交叉点击问题。修改 `core/confirmation_commands.py`，新增 `claim_pending_action_status()`；修改 `core/card_callback.py`，确认创建前进入 `creating`、拒绝前进入 `rejecting`，并由 `guard_pending_action_transition()` 拦截 `created` / `reject_create_task` / `creating` / `rejecting` 状态下的旧按钮点击。补充 `tests/test_post_meeting_card_callback.py` 用例，验证创建处理中再次点击拒绝不会改写状态，且回写卡片不再包含拒绝按钮。同步更新 [M4 任务文档](docs/tasks/m4-post-meeting.md) 和 [架构说明](architecture.md)。验证通过：`python3 -m py_compile core/card_callback.py core/confirmation_commands.py tests/test_post_meeting_card_callback.py`；`python3 -m unittest tests.test_post_meeting_card_callback`（11 个用例通过）。

M3 的核心边界是“轻量 RAG + 结构化元数据 + 增量更新”，并继续作为 M4 相关背景资料召回能力复用：

RAGFlow 代码阅读中可借鉴的 RAG 设计已整理到 [RAGFlow 代码阅读笔记](docs/ragflow-design-notes.md)，作为后续增强 M3 检索、chunk 元数据、rerank 和索引任务的参考。

- T3.1：定义 `pre_meeting_brief` 工作流输入输出
- T3.2：实现会议主题识别
- T3.3：实现关联资源召回
- T3.4：实现轻量知识索引与文档清洗
- T3.5：实现证据排序与摘要生成
- T3.6：实现知识检索 Agent 工具
- T3.7：实现会前卡片模板
- T3.8：接入会前定时触发
- T3.9：增加手动兜底入口
- T3.10：预留知识变更更新机制
- T3.11：知识域与 embedding 模型一致性治理
- T3.12：扩展 chunk schema 与结构化位置元数据
- T3.13：实现可配置混合检索和可解释分数
- T3.14：接入可选 reranker 阶段
- T3.15：支持 TOC 增强与父子 chunk 展开
- T3.16：实现 evidence pack token budget 与稳定引用格式

关于 T3.10 的关键设计结论已经记录在 M3 文档中：`updated_at + checksum` 只能判断“检查后是否需要重建”，不能让系统第一时间知道文档变化；实时变化感知需要飞书事件订阅、Webhook 或 WebSocket，将变更写入 `index_jobs` 后由后台 worker 异步刷新索引。

## 维护约定

- 完成某个任务后，更新对应里程碑文档中的任务条目。
- 如果新增、删除或调整里程碑文档，更新本索引。
- 如果实现改变架构边界、Agent 流程或安全策略，同步更新 `architecture.md`。
- 如果实现改变用户场景、验收方式或产品目标，同步更新 `prd.md`。
