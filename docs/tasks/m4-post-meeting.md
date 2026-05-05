## 5.4 M4：会后总结与任务落地工作流

### T4.1 定义 `post_meeting_followup` 工作流

- 优先级：`P0`
- 目标：明确会后流程边界
- 验收标准：
  - 输入为妙记或会议信息
  - 输出为结构化总结、Action Items 和回写结果

#### T4.1 当前实现补强：联系人解析工具边界

- 已更新文件：
  - `core/router.py`
  - `core/workflows.py`
  - `tests/test_router.py`
  - `tasks.md`
- 已实现的核心能力：
  - `minute.ready` 路由现在会显式暴露 `contact.get_current_user`
  - `minute.ready` 路由现在会显式暴露 `contact.search_user`
  - `MANUAL_WORKFLOW_TOOLS["post_meeting_followup"]` 已同步加入这两个工具，确保手动 `message.command -> post_meeting_followup` 和自动事件路由保持一致
  - `PostMeetingFollowupWorkflow` 的工具边界与仓库安全规范重新对齐：当负责人是“我”或具体姓名时，后续 Agent 可以先解析 open_id，而不是编造负责人
- 当前验证方式：
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_router` 验证 `minute.ready` 和手动 `post_meeting_followup` 两条路由都包含联系人解析工具
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type minute.ready --backend local --llm-provider scripted_debug --max-iterations 3` 验证本地会后链路仍能进入 `post_meeting_followup`

#### T4.1 融合实现记录：M4 会后主链路接入完整仓库

- 更新时间：2026-05-04
- 已更新文件：
  - `core/post_meeting.py`
  - `core/post_meeting_tools.py`
  - `core/card_callback.py`
  - `core/confirmation_commands.py`
  - `core/agent.py`
  - `core/router.py`
  - `core/workflows.py`
  - `core/policy.py`
  - `core/storage.py`
  - `adapters/feishu_tools.py`
  - `adapters/feishu_client.py`
  - `cards/post_meeting.py`
  - `cards/layout.py`
  - `scripts/post_meeting_demo.py`
  - `scripts/post_meeting_live_test.py`
  - `scripts/post_meeting_agent_live_test.py`
  - `scripts/post_meeting_button_flow_live_test.py`
  - `scripts/post_meeting_confirmation_watcher.py`
  - `scripts/post_meeting_confirmation_event_watcher.py`
  - `tests/test_post_meeting_card_callback.py`
  - `tests/test_post_meeting_rag_query.py`
- 已实现的核心能力：
  - `PostMeetingFollowupWorkflow.prepare_context()` 会在进入 Agent Loop 前构造确定性会后产物，包括清洗纪要、总结草稿、Action Items、待确认任务、卡片 payload 和相关知识线索
  - `register_post_meeting_tools()` 已接入 `create_meetflow_agent()`，会后流程可以通过 ToolRegistry 暴露 `post_meeting.build_artifacts`、`post_meeting.prepare_task`、`post_meeting.send_summary_card` 等工具
  - 会后主链路不再自动创建飞书任务；所有 Action Item 先进入总结卡或待确认卡，用户确认后再进入 `handle_post_meeting_card_callback()`
  - `AgentPolicy._authorize_create_task()` 增加人工确认检查，任务创建必须具备 `human_confirmation.confirmed=True`，并继续校验负责人、截止时间、置信度和幂等键
  - `task_mappings` 扩展 `meeting_id`、`minute_token`、`title`、`evidence_refs`、`source_url`，用于把 M4 创建的任务和后续 M5 风险巡检证据链关联起来
- 当前验证方式：
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback tests.test_post_meeting_rag_query` 验证 M4 卡片确认状态机、重复点击拦截、截止日期归一和 RAG query 去噪
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests` 验证融合后全量 58 条单测通过

#### T4.1 真实联调稳定性补充：重复发卡确认会话

- 更新时间：2026-05-05
- 问题背景：
  - 同一个妙记重复执行 `scripts/card_send_live.py m4 --minute ...` 时，Action Item 的稳定 `item_id` 不变。
  - 第一轮点击“确认创建”后，本地 `post_meeting_pending_actions.json` 会把该 `item_id` 标记为 `created`；第二轮重新发卡后，如果仍沿用旧状态，点击新卡片会被误判为“该任务已创建”，导致不再创建新飞书任务，后续 M5 也扫不到本轮测试任务。
- 已实现修复：
  - `scripts/post_meeting_live_test.py` 每次真实发待确认卡都会写入新的 `review_session_id`。
  - `cards/post_meeting.py` 将 `review_session_id` 放入按钮 value。
  - `core/confirmation_commands.py` 在新 session 写入同一个 `item_id` 时重置状态为 `pending`。
  - `core/card_callback.py` 将 `review_session_id` 纳入任务创建幂等键，并把 task mapping 的 `item_id` 扩展为 `item_id:review_session_id`，保留重复联调时的多轮映射。
  - 旧卡片点击会被提示“请使用群里最新发送的卡片”，避免旧卡继续改写新 session 状态。
- 当前验证方式：
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback` 验证新 session 会重置 created 状态、旧卡片被拦截、幂等键包含 session。
  - 已通过 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests` 验证全量 66 条测试通过。

### T4.2 实现纪要清洗

- 优先级：`P0`
- 目标：对妙记文本做去噪、切片和结构整理
- 验收标准：
  - 对口语化纪要能产出更清晰的输入文本

### T4.3 实现 Action Item 抽取

- 优先级：`P0`
- 目标：抽取事项、负责人、截止时间、优先级、背景依据
- 验收标准：
  - 至少在 3 份样例纪要中抽出结构化任务列表
  - 能识别字段缺失情况

### T4.4 实现决策与待确认问题抽取

- 优先级：`P1`
- 目标：从纪要中提炼结论与开放问题
- 验收标准：
  - 输出的决策与 Action Items 不混淆

### T4.5 实现低置信度标记策略

- 优先级：`P0`
- 目标：对负责人缺失、时间缺失、语义模糊的任务打 `needs_confirm`
- 验收标准：
  - 模糊任务不会直接自动落地为正式任务

### T4.6 实现会后总结卡片

- 优先级：`P0`
- 目标：生成包含结论、待办、风险、原始链接的卡片
- 验收标准：
  - 卡片清晰展示会议产出
  - 支持快速跳转原始资料

### T4.7 实现任务自动创建

- 优先级：`P0`
- 目标：对高置信度任务直接写入飞书任务
- 验收标准：
  - 至少一条样例任务成功创建
  - 本地记录任务映射关系

### T4.8 实现待确认任务卡片

- 优先级：`P1`
- 目标：将低置信度任务展示为待确认，而不是直接写入
- 验收标准：
  - 卡片能展示缺失字段和待确认原因

### T4.9 接入妙记完成触发

- 优先级：`P0`
- 目标：妙记 ready 后自动启动会后流程
- 验收标准：
  - 可通过事件或模拟事件触发
  - 对未 ready 状态支持重试

---
