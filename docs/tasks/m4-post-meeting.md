## 5.4 M4：会后总结与任务落地工作流

继续开发前请先阅读交接文档：[m4-post-meeting-handoff.md](./m4-post-meeting-handoff.md)。

这份交接文档说明了当前已有骨架、M4 推荐实现顺序、与 M5 的上下游关系、建议新增文件、验证方式和并行开发冲突规避边界。

## 任务拆分

M4 按下面任务逐项推进。每一项完成后都必须在对应条目补充“实现记录”，记录修改文件、核心类/函数、运行逻辑、验证命令和结果。未明确进入当前任务的内容不提前实现，避免一次性把 M4 做成不可审查的大改动。

### T4.1 固化 M4 范围和任务边界

- 优先级：`P0`
- 当前状态：`已完成`
- 目标：明确 M4 的拆分方式、开发顺序、公共文件改动边界和验收口径。
- 主要产物：
  - 更新 `docs/tasks/m4-post-meeting.md`
  - 关联交接文档 `docs/tasks/m4-post-meeting-handoff.md`
- 不做范围：
  - 不新增业务代码
  - 不调用飞书真实 API
  - 不修改 M5 相关文件
- 验收标准：
  - M4 后续任务能按 T4.x 独立领取和验收
  - 文档中写清每个任务的产物、验证方式和安全边界
- 验证方式：
  - `git diff -- docs/tasks/m4-post-meeting.md`

#### 实现记录

- 2026-04-30：将 M4 从粗粒度目标拆成可逐项开发的 T4.1-T4.12 任务；本次只更新文档，不实现代码。

### T4.2 定义会后业务结构和产物契约

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：在不改公共模型的前提下，先定义 M4 内部输入、中间结果和最终产物边界。
- 建议修改文件：
  - `core/post_meeting.py`
- 主要类 / 函数：
  - `PostMeetingInput`
  - `CleanedTranscript`
  - `TranscriptSection`
  - `ExtractedDecision`
  - `ExtractedOpenQuestion`
  - `PostMeetingArtifacts`
  - `build_post_meeting_input_from_context(context)`
- 不做范围：
  - 不接真实妙记 API
  - 不创建飞书任务
  - 不修改 `core.models.ActionItem` 和 `core.models.MeetingSummary`，除非后续任务证明必须扩展
- 验收标准：
  - 结构能承接 `meeting_id`、`minute_token`、`project_id`、`source_url`、原始纪要文本和上下文 payload
  - 最终产物能包含 `MeetingSummary`、`ActionItem[]`、待确认项、卡片 payload 预留字段
  - 所有新增业务结构有中文 docstring，说明业务含义
- 验证方式：
  - `python3 -m py_compile core/post_meeting.py`

### T4.3 实现纪要清洗纯函数

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：把妙记或手工纪要文本清洗成后续抽取可稳定消费的结构。
- 建议修改文件：
  - `core/post_meeting.py`
- 主要类 / 函数：
  - `clean_meeting_transcript(raw_text)`
  - `split_transcript_sections(cleaned_lines)`
  - `normalize_transcript_line(line)`
- 不做范围：
  - 不调用 LLM
  - 不做复杂语义总结
  - 不丢弃说话人、时间戳、章节标题等可作为证据的上下文
- 验收标准：
  - 能去掉空行、重复噪声和明显无意义系统文本
  - 能保留原始证据行，方便后续 `EvidenceRef.snippet` 溯源
  - 能识别“待办 / Action Item / TODO / 负责人 / 截止时间”等强信号所在行
- 验证方式：
  - 后续 `scripts/post_meeting_demo.py --backend local` 覆盖
  - 本任务阶段可先用临时单元输入或 demo 函数打印清洗结果

### T4.4 实现 Action Item 规则抽取

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：从清洗后的纪要中抽取结构化行动项，优先输出已有 `ActionItem` 模型。
- 建议修改文件：
  - `core/post_meeting.py`
- 主要类 / 函数：
  - `extract_action_items(cleaned_transcript, meeting_id, source_url)`
  - `build_action_item_from_line(line, context)`
  - `build_evidence_ref(...)`
- 不做范围：
  - 不编造负责人 open_id
  - 不直接调用 `tasks.create_task`
  - 不把决策句误当成任务创建
- 验收标准：
  - 能抽取任务标题、候选负责人文本、候选截止时间、优先级、证据引用
  - 缺负责人、缺截止时间或证据不足时设置 `needs_confirm=True`
  - 至少覆盖 3 类样例：字段完整、缺负责人、缺截止时间
- 验证方式：
  - `python3 scripts/post_meeting_demo.py --backend local`

### T4.5 实现决策和开放问题抽取

- 优先级：`P1`
- 当前状态：`待开始`
- 目标：把“已经达成的结论”和“还需要确认的问题”从任务中分离出来。
- 建议修改文件：
  - `core/post_meeting.py`
- 主要类 / 函数：
  - `extract_decisions(cleaned_transcript, meeting_id, source_url)`
  - `extract_open_questions(cleaned_transcript, meeting_id, source_url)`
- 不做范围：
  - 不把“决定采用某方案”创建为任务
  - 不为开放问题自动分配负责人
- 验收标准：
  - 决策、开放问题、Action Items 三类输出互不混淆
  - 每条决策或开放问题保留证据文本
- 验证方式：
  - `python3 scripts/post_meeting_demo.py --backend local`

### T4.6 实现低置信度与待确认策略

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：在业务抽取层先标记不能自动落地的任务，和 `AgentPolicy` 的写操作安全边界保持一致。
- 建议修改文件：
  - `core/post_meeting.py`
- 主要类 / 函数：
  - `evaluate_action_item_confidence(action_item)`
  - `mark_action_item_confirmation_state(action_item)`
  - `build_confirmation_reason(action_item)`
- 不做范围：
  - 不替代 `AgentPolicy.authorize_tool_call()`
  - 不绕过工具注册器直接写任务
- 验收标准：
  - 缺负责人、缺截止时间、语义模糊、证据不足时进入待确认
  - 高置信任务必须同时满足标题、负责人候选、截止时间、证据和置信度阈值
  - 待确认原因写入 `ActionItem.extra["confirm_reason"]`
- 验证方式：
  - `python3 scripts/post_meeting_demo.py --backend local`
  - `python3 scripts/agent_policy_demo.py --scenario missing_task_fields`

### T4.7 实现会后总结与待确认卡片模板

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：生成可读的飞书 interactive card payload，用于展示总结、任务和待确认事项。
- 建议修改文件：
  - `cards/post_meeting.py`
  - `cards/__init__.py`
- 主要类 / 函数：
  - `build_post_meeting_summary_card(artifacts)`
  - `build_pending_action_items_card(artifacts)`
  - `render_action_item_markdown(action_item)`
  - `render_evidence_markdown(evidence_refs)`
- 不做范围：
  - 不发送卡片
  - 首版不实现交互按钮回调
- 验收标准：
  - 卡片区分关键结论、已满足自动创建条件的任务、待确认任务、开放问题
  - 卡片展示原始妙记或文档链接
  - 待确认卡片能展示缺失字段和待确认原因
- 验证方式：
  - `python3 scripts/post_meeting_demo.py --backend local --show-card-json`

### T4.8 新增本地 mock Demo

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：用本地 mock 纪要跑通清洗、抽取、低置信标记和卡片生成。
- 建议修改文件：
  - `scripts/post_meeting_demo.py`
- 主要功能：
  - 内置至少 3 份 mock 纪要样例
  - 支持选择样例或读取本地文本文件
  - 默认只打印本地产物，不访问飞书
  - 可选打印卡片 JSON
- 不做范围：
  - 不读取 `config/settings.local.json`
  - 不创建真实飞书任务
  - 不发送真实群消息
- 验收标准：
  - 默认命令能稳定输出清洗结果、决策、开放问题、Action Items、待确认原因和卡片摘要
  - 样例覆盖完整任务、缺负责人任务、缺截止时间任务、决策句和开放问题
- 验证方式：
  - `python3 scripts/post_meeting_demo.py --backend local`
  - `python3 scripts/post_meeting_demo.py --backend local --show-card-json`

### T4.9 接入 `PostMeetingFollowupWorkflow` 本地上下文

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：让 `minute.ready` 本地链路能在 `WorkflowContext.raw_context` 中看到 M4 初始产物或处理计划。
- 建议修改文件：
  - `core/workflows.py`
  - 必要时 `core/__init__.py`
- 主要类 / 函数：
  - `PostMeetingFollowupWorkflow.prepare_context(...)`
  - `build_post_meeting_artifacts(...)`
- 不做范围：
  - 不要求 Agent Loop 自动完成真实任务创建
  - 不改变 `WorkflowRouter` 已有路由规则，除非发现路由字段缺失
- 验收标准：
  - `minute.ready` 能进入 `post_meeting_followup`
  - 上下文包含 `post_meeting_plan`
  - 若存在 mock 纪要或本地输入，上下文可包含 `post_meeting_artifacts`
- 验证方式：
  - `python3 scripts/agent_demo.py --event-type minute.ready --minute-token minute_demo_001 --backend local --llm-provider scripted_debug --max-iterations 3`

### T4.10 实现高置信任务创建请求与映射记录

- 优先级：`P0`
- 当前状态：`待开始`
- 目标：把高置信 Action Item 转成受控 `tasks.create_task` 工具请求，并在创建成功后记录 `task_mappings`。
- 建议修改文件：
  - `core/post_meeting.py`
  - `core/storage.py`
  - 可能涉及 `core/agent_loop.py` 或工具执行结果处理
- 主要类 / 函数：
  - `build_task_create_arguments(action_item, context)`
  - `build_task_mapping_payload(action_item, task_result, context)`
  - `MeetFlowStorage.save_task_mapping(...)` 字段扩展方案
- 不做范围：
  - 不直接调用飞书任务 API
  - 不绕过 `AgentPolicy`
  - 不默认真实写入
- 验收标准：
  - 创建任务参数包含 `summary`、`assignee_ids`、`due_timestamp_ms`、`confidence`、`evidence_refs`、`idempotency_key`
  - `AgentPolicy` 能拦截缺字段或低置信任务
  - 创建成功后能保存 `item_id`、`task_id`、`meeting_id`、`minute_token`、`title`、`owner`、`due_date`、`status`、`evidence_refs`、`source_url`
- 验证方式：
  - 本地 dry-run 或 local registry 验证
  - `python3 scripts/agent_policy_demo.py --scenario missing_task_fields`
  - 真实写入必须后续显式使用 `--allow-write`

### T4.11 真实妙记只读联调

- 优先级：`P1`
- 当前状态：`待开始`
- 目标：读取真实妙记或会议纪要，只做只读解析验证。
- 建议修改文件：
  - `scripts/post_meeting_live_test.py`
  - 必要时复用 `scripts/minutes_live_test.py`
- 不做范围：
  - 不创建任务
  - 不发送卡片
  - 不打印 token、secret、API key
- 验收标准：
  - 能从真实妙记 URL 或 token 获取基础信息、AI 产物或正文
  - 能把真实内容送入 M4 清洗和抽取链路
  - 失败时记录真实错误原因，不伪造成功
- 验证方式：
  - `python3 scripts/minutes_live_test.py --identity user --minute '<真实妙记 URL>'`
  - `python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --read-only`

### T4.12 真实写入灰度验证

- 优先级：`P1`
- 当前状态：`待开始`
- 目标：在测试任务或测试群中验证高置信任务创建、待确认卡片发送和 task_mappings 写入。
- 建议修改文件：
  - `scripts/post_meeting_live_test.py`
  - 可能涉及 `adapters/feishu_tools.py`
- 不做范围：
  - 不默认发送到生产群
  - 不在缺少 `--allow-write` 时执行任何写操作
  - 不绕过 `AgentPolicy`、`ToolRegistry` 或飞书客户端封装
- 验收标准：
  - 高置信任务在显式 `--allow-write` 后创建成功
  - 低置信任务生成待确认卡片，不创建真实任务
  - 本地 `task_mappings` 能被 M5 后续稳定消费
  - 审计记录能看出写操作参数、策略判断和结果，且不包含敏感密钥
- 验证方式：
  - `python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --allow-write`
  - `python3 scripts/agent_demo.py --event-type minute.ready --minute-token '<真实 token>' --backend feishu --llm-provider scripted_debug --max-iterations 3 --allow-write`

## 推荐执行顺序

1. 先完成 T4.1，锁定任务拆分。
2. 再按 T4.2-T4.8 完成本地纯函数、卡片和 mock demo。
3. 然后做 T4.9，把本地产物接入 Agent 工作流上下文。
4. T4.10 只在本地和 Policy 层稳定后再做。
5. T4.11 做真实只读验证。
6. T4.12 最后做真实写入灰度验证。

---
