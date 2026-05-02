# M4 会后总结与任务落地工作流交接文档

这份文档用于继续开发 M4。目标是让后续开发者能快速理解当前基础、M4 要完成什么、推荐怎么一步步做，以及如何和并行开发的 M5 风险巡检保持解耦。

## 1. 当前项目状态

M1-M3 已经完成并通过收口验证：

- M1：项目骨架、配置、日志、审计、本地存储、公共模型。
- M2：飞书日历、文档、妙记、任务、消息、通讯录等基础工具能力。
- M2.8：Agent Runtime、ToolRegistry、AgentPolicy、WorkflowRouter、WorkflowRunner。
- M3：会前知识卡片，包含 ChromaDB 向量检索、SQLite FTS5/BM25、RRF 融合、可选 reranker、真实 DeepSeek + allow-write 发卡验证。

M4 当前已有“工作流骨架”，但还没有完整业务实现：

- `WorkflowRouter` 已支持 `minute.ready -> post_meeting_followup`。
- `PostMeetingFollowupWorkflow` 已存在于 `core/workflows.py`。
- `build_post_meeting_plan_draft()` 已能生成会后阶段草案。
- `post_meeting_followup` 默认允许工具：`minutes.fetch_resource`、`docs.fetch_resource`、`tasks.create_task`、`contact.get_current_user`、`contact.search_user`、`im.send_card`。
- `AgentPolicy` 已能拦截缺少负责人或截止时间的任务创建。

当前 M4 骨架阶段：

```text
fetch_minutes_or_summary
-> clean_transcript
-> extract_decisions_and_action_items
-> validate_owner_due_date_evidence
-> create_task_or_request_confirmation
```

## 2. M4 的目标

M4 要完成的是“会后总结与任务落地”：

```text
飞书妙记 / 会议纪要
-> 清洗整理
-> 抽取决策、开放问题、Action Items
-> 校验负责人 / 截止时间 / 证据
-> 高置信任务自动创建
-> 低置信任务生成待确认卡片
-> 记录 task_mappings
```

一句话理解：

```text
M4 = 把会议内容变成结构化总结和可执行任务
```

M4 首版不要追求“把所有纪要都完美理解”，而是要保证：

- 有证据才输出结论。
- 任务字段不完整就待确认。
- 写飞书任务必须经过 `AgentPolicy`。
- 任务创建后要留下本地映射，方便 M5 后续风险巡检。

## 3. M4 与 M5 的关系

M4 和 M5 是上下游关系，但应并行开发、低耦合对接。

M4 负责生产：

```text
MeetingSummary
ActionItem
飞书 task_id
task_mappings
会议/妙记证据链接
```

M5 负责消费：

```text
飞书任务状态
task_mappings
历史提醒记录
-> RiskAlert
```

因此 M4 不需要实现风险巡检，M5 也不需要理解 M4 的纪要抽取细节。双方只通过稳定数据边界对接：

- `ActionItem.item_id`
- 飞书 `task_id`
- `meeting_id`
- `minute_token`
- `evidence_refs`
- 原始会议或妙记链接

M4 完成任务创建后，应写入 `task_mappings`。M5 未来读取这个映射，就能知道某个风险任务来自哪次会议和哪个 Action Item。

## 4. 推荐新增文件

为了减少和 M5 并行开发冲突，M4 优先新增或修改这些文件：

- `core/post_meeting.py`：M4 业务核心逻辑。
- `cards/post_meeting.py`：会后总结卡片和待确认任务卡片。
- `scripts/post_meeting_demo.py`：本地 mock 纪要验证入口。
- `scripts/post_meeting_live_test.py`：后续真实妙记联调入口，可等本地链路稳定后再做。
- `docs/tasks/m4-post-meeting.md`：持续记录实现细节和验证结果。

尽量不要改 M5 文件：

- `core/risk_scan.py`
- `cards/risk_scan.py`
- `scripts/risk_scan_demo.py`
- `docs/tasks/m5-risk-scan*.md`

谨慎修改公共文件，必要时先做最小改动：

- `core/models.py`
- `core/workflows.py`
- `core/router.py`
- `core/storage.py`
- `adapters/feishu_tools.py`
- `core/policy.py`

## 5. 推荐实现顺序

### Step 1：定义 M4 业务结构

优先在 `core/post_meeting.py` 中定义 M4 专属中间结构。已有 `core.models.ActionItem` 和 `core.models.MeetingSummary`，应优先复用。

建议新增：

- `PostMeetingInput`：一次会后流程的输入。
- `CleanedTranscript`：清洗后的纪要文本和章节。
- `ExtractedDecision`：结构化决策。
- `ExtractedOpenQuestion`：待确认问题。
- `PostMeetingArtifacts`：M4 最终产物集合。

注意：如果只是 M4 内部中间结构，先放 `core/post_meeting.py`，不要一开始就改 `core/models.py`。

### Step 2：实现纪要清洗

输入可能来自：

- `minutes.fetch_resource`
- `docs.fetch_resource`
- 手动传入的纪要文本

首版清洗目标：

- 去掉空行和重复噪声。
- 保留说话人、时间戳、章节标题。
- 识别“待办 / Action Item / TODO / 负责人 / 截止时间”等强信号。
- 输出可给规则或 LLM 使用的结构化文本。

建议先实现纯函数：

```text
clean_meeting_transcript(raw_text) -> CleanedTranscript
```

### Step 3：实现 Action Item 抽取

首版可以先做规则抽取，再接 LLM 辅助：

- 识别“谁 在什么时候前 做什么”。
- 识别负责人。
- 识别截止时间。
- 保留原句作为 evidence。
- 缺字段则 `needs_confirm=True`。

输出优先转成已有 `ActionItem`：

- `title`
- `owner`
- `due_date`
- `priority`
- `confidence`
- `needs_confirm`
- `evidence_refs`
- `extra`

负责人不要编造 open_id。若任务要真实创建：

- “我 / 本人 / 自己”必须先调用 `contact.get_current_user`。
- 具体姓名必须先调用 `contact.search_user`。
- 得到 open_id 后才能填入 `assignee_ids`。

### Step 4：实现决策与开放问题抽取

决策和 Action Item 要分开：

- 决策：已经达成的结论，例如“本周采用 BM25/RRF 方案”。
- 开放问题：还需要确认的问题，例如“是否接入真实 reranker provider”。
- Action Item：需要人执行的任务，例如“张三周五前完成 demo”。

首版验收：不要把“结论”误创建成任务。

### Step 5：实现低置信度策略

任务自动创建必须满足：

- 有明确任务标题。
- 有负责人 open_id。
- 有截止时间。
- 有足够置信度。
- 有证据引用或原始纪要来源。

否则进入待确认：

```text
needs_confirm=True
confirm_reason=缺少负责人 / 缺少截止时间 / 语义不明确 / 证据不足
```

这一步必须和 `AgentPolicy` 保持一致：M4 可以先做业务侧预判，但最终写操作仍由 `AgentPolicy.authorize_tool_call()` 决定。

### Step 6：实现会后总结卡片

建议新增 `cards/post_meeting.py`。

会后总结卡片应包含：

- 会议主题
- 关键结论
- Action Items
- 待确认任务
- 开放问题
- 风险或阻塞
- 原始妙记 / 文档链接

卡片要区分：

- 已创建任务
- 待确认任务
- 只作为纪要信息展示的结论

### Step 7：实现任务自动创建

高置信 Action Item 才能创建飞书任务。

推荐流程：

```text
ActionItem
-> resolve assignee open_id
-> tasks.create_task tool call
-> AgentPolicy 审核
-> FeishuClient.create_task
-> LocalStorage.save_task_mapping
```

不要在 M4 业务代码里直接调用飞书任务 API。真实写操作必须通过工具和策略层。

### Step 8：实现待确认任务卡片

低置信任务不创建真实任务，而是生成待确认卡片：

- 哪些字段缺失。
- 原始纪要证据是什么。
- 建议用户补充什么。
- 后续可以再由人工确认后创建任务。

首版可以只生成卡片 payload，不一定实现交互按钮。

### Step 9：接入妙记完成触发

当前路由已支持 `minute.ready`。M4 后续要做的是让这个事件真正带上：

- `minute_token`
- `meeting_id`
- `calendar_event_id`
- `project_id`
- 触发幂等键

验证入口：

```bash
python3 scripts/agent_demo.py --event-type minute.ready --minute-token minute_demo_001 --backend local --llm-provider scripted_debug --max-iterations 3
```

真实妙记读取后置验证：

```bash
python3 scripts/minutes_live_test.py --identity user --minute '<妙记 URL 或 token>'
```

## 6. 建议 Demo 分层

先本地、再真实只读、最后真实写入。

### 本地 mock

```bash
python3 scripts/post_meeting_demo.py --backend local
```

目标：

- 输入一段 mock 纪要。
- 输出清洗结果、决策、开放问题、Action Items。
- 生成会后总结卡片 payload。
- 默认不创建真实任务。

### Agent 本地链路

```bash
python3 scripts/agent_demo.py --event-type minute.ready --minute-token minute_demo_001 --backend local --llm-provider scripted_debug --max-iterations 3
```

目标：

- 确认 `minute.ready` 能进入 `post_meeting_followup`。
- 确认写工具在 `allow_write=False` 时被移除。
- 确认上下文里有 `post_meeting_plan`。

### 真实只读

```bash
python3 scripts/minutes_live_test.py --identity user --minute '<真实妙记 URL>'
```

目标：

- 确认能读取真实妙记基础信息和 AI 产物。
- 不创建任务，不发消息。

### 真实写入

真实创建任务或发卡必须显式加 `--allow-write`，并使用测试任务或测试群。

目标：

- 高置信任务创建成功。
- 缺字段任务被 `AgentPolicy` 拦截或进入待确认。
- 本地 `task_mappings` 有记录。

## 7. M4 验收标准

M4 第一版完成时，应满足：

- 能读取或接收一份纪要文本。
- 能输出清洗后的纪要结构。
- 能抽取至少 2 条 Action Item。
- 能区分决策、开放问题和任务。
- 缺负责人或截止时间的任务不会自动创建。
- 高置信任务能通过工具请求创建飞书任务。
- 任务创建必须经过 `AgentPolicy`。
- 创建成功后能写入 `task_mappings`。
- 能生成会后总结卡片和待确认任务卡片。
- 有本地 demo 和至少一个真实只读验证入口。
- 所有实现和验证结果同步写入 `docs/tasks/m4-post-meeting.md`。

## 8. 与 M5 并行时的接口承诺

M4 应尽量向 M5 提供这些稳定字段：

- `item_id`
- `task_id`
- `meeting_id`
- `minute_token`
- `title`
- `owner`
- `due_date`
- `status`
- `evidence_refs`
- `source_url`

M5 不需要知道 M4 如何抽取 Action Item，只需要读取 `task_mappings` 和飞书任务状态。

如果 M4 需要扩展 `task_mappings` 字段，应先记录在 `docs/tasks/m4-post-meeting.md`，避免 M5 按旧字段开发后对不上。

## 9. 第一批建议任务

1. 新增 `core/post_meeting.py`，实现纪要清洗和 Action Item 规则抽取。
2. 新增 `scripts/post_meeting_demo.py`，用 mock 纪要跑通本地流程。
3. 新增 `cards/post_meeting.py`，生成会后总结卡片和待确认任务卡片。
4. 接入 `PostMeetingFollowupWorkflow` 的本地路径。
5. 验证 `AgentPolicy` 对缺字段任务的拦截。
6. 更新 `docs/tasks/m4-post-meeting.md`，记录文件、类/函数、业务流程和验证命令。

第一批不要急着真实创建任务。先把“抽取准确、字段完整、低置信待确认、卡片可读”做稳定，再接真实写入。
