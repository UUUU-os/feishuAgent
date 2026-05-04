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
- 2026-05-01：复核 T4.1 范围与任务边界，确认交接文档链接存在，T4.2-T4.12 均具备目标、产物、不做范围、验收标准和验证方式；本次仍不新增业务代码。

### T4.2 定义会后业务结构和产物契约

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：新增 `core/post_meeting.py`，定义 M4 内部输入和产物契约；核心结构包括 `PostMeetingInput`、`TranscriptSection`、`CleanedTranscript`、`ExtractedDecision`、`ExtractedOpenQuestion`、`PostMeetingArtifacts`；核心函数包括 `build_post_meeting_input_from_context()`、`build_empty_post_meeting_artifacts()`、`first_content_resource()`、`first_non_empty()`。本阶段只做字段归一化和契约壳，不读取真实妙记、不创建飞书任务、不修改公共模型。验证通过：`python3 -m py_compile core/post_meeting.py`；mock `WorkflowContext` 构造 `PostMeetingInput` 和 `PostMeetingArtifacts` 的契约冒烟测试通过。

### T4.3 实现纪要清洗纯函数

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：在 `core/post_meeting.py` 实现纪要清洗纯函数：`clean_meeting_transcript()`、`normalize_transcript_line()`、`split_transcript_sections()`，并补充 `build_signal_lines()`、`detect_signal_tags()`、`extract_section_title()`、`build_transcript_section()`、`is_low_value_duplicate()`、`unique_non_empty()` 等辅助函数。当前逻辑只做去空行、去常见系统噪声、规范化列表符号、章节切分和强信号行标记，不调用 LLM、不抽取 Action Item、不创建任务。验证通过：`python3 -m py_compile core/post_meeting.py`；本地 mock 纪要冒烟测试确认系统噪声被移除、章节可切分、`action_item` / `owner` / `due_date` / `decision` / `open_question` 信号可识别。

### T4.4 实现 Action Item 规则抽取

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：在 `core/post_meeting.py` 实现 Action Item 规则抽取：`extract_action_items()`、`build_action_item_from_line()`、`build_evidence_ref()`，并补充 `should_extract_action_item()`、`normalize_action_title()`、`extract_owner_candidate()`、`extract_due_date_candidate()`、`infer_priority()`、`stable_id()`、`field_label()`、`strip_action_prefix()` 等辅助函数。首版只从强信号行生成任务草案，负责人保留为纪要文本候选，不解析或编造 open_id；缺负责人或截止时间时设置 `needs_confirm=True` 并写入 `extra["missing_fields"]` / `extra["confirm_reason"]`。验证通过：`python3 -m py_compile core/post_meeting.py`；本地 mock 纪要覆盖字段完整、缺负责人/截止时间、`负责人 + 截止` 格式三类样例。

### T4.5 实现决策和开放问题抽取

- 优先级：`P1`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：在 `core/post_meeting.py` 实现 `extract_decisions()` 和 `extract_open_questions()`，并补充 `normalize_decision_content()`、`normalize_open_question_content()`。规则上只从对应信号行抽取决策和开放问题，并显式跳过会被识别为 Action Item 的行，避免把“决定采用某方案”或“是否接入某能力”误创建为任务。验证通过：本地 mock 纪要中 1 条决策、1 条开放问题、3 条 Action Items 分别进入不同结果集合，且每条决策 / 开放问题均保留 `EvidenceRef`。

### T4.6 实现低置信度与待确认策略

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：在 `core/post_meeting.py` 实现低置信度与待确认策略：`evaluate_action_item_confidence()`、`mark_action_item_confirmation_state()`、`build_confirmation_reason()`，并补充 `build_missing_action_item_fields()`、`build_confirmation_reasons()`、`is_semantically_ambiguous_title()`。当前规则会对缺任务标题、缺负责人候选、缺截止时间、缺证据引用、语义模糊和低于 `0.75` 置信度的 Action Item 标记 `needs_confirm=True`，同时写入 `extra["missing_fields"]`、`extra["confirm_reason"]`、`extra["confidence_threshold"]` 和 `extra["auto_create_candidate"]`。本阶段只做业务侧预判，不替代 `AgentPolicy`，不调用写工具。验证通过：`python3 -m py_compile core/post_meeting.py`；本地 mock 覆盖完整任务、缺字段任务、语义模糊任务和无证据任务；`python3 scripts/agent_policy_demo.py --scenario missing_task_fields` 确认策略层仍会把缺负责人 / 截止时间的 `tasks.create_task` 拦截为 `needs_confirmation`。

### T4.7 实现会后总结与待确认卡片模板

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：新增 `cards/post_meeting.py` 并更新 `cards/__init__.py` 导出会后卡片模板。核心函数包括 `build_post_meeting_summary_card()`、`build_pending_action_items_card()`、`render_action_item_markdown()`、`render_evidence_markdown()`，并补充行动项区块、决策 / 开放问题区块、证据引用、原始资料链接和待确认明细渲染。当前只生成飞书 interactive card payload，不发送卡片，也不实现交互按钮回调。验证通过：`python3 -m py_compile cards/post_meeting.py cards/__init__.py`；本地构造 `PostMeetingArtifacts` 冒烟测试确认会后总结卡和待确认任务卡均可 JSON 序列化，能展示原始纪要链接、关键结论、开放问题、待确认原因和证据引用。
- 2026-05-01：按 M4 优化需求增强会后卡片：`build_pending_action_items_card()` 现在为每条待确认任务单独展示任务 ID、负责人、截止时间、优先级、置信度、待确认原因和证据片段，并增加 `确认创建` / `修改信息` / `拒绝创建` 三个按钮的 action value；新增 `build_auto_created_tasks_card()`，用于高置信任务真实创建后回告用户。会后总结卡增加 `相关背景资料` 区块，优先展示 M3 轻量 RAG 召回结果，其次回退到上下文 `related_resources`。验证通过：`python3 -m py_compile core/post_meeting.py cards/post_meeting.py cards/__init__.py scripts/post_meeting_demo.py scripts/post_meeting_live_test.py`；`python3 scripts/post_meeting_demo.py --backend local --sample missing_owner --show-card-json` 确认待确认卡片包含关键字段复核区和按钮。
- 2026-05-01：根据真实群消息反馈继续收敛卡片体验：业务卡片不再展示底部 `证据引用` 区块，证据引用保留在 Markdown report 中供开发和审计查看；在飞书卡片回调服务接入前，待确认任务卡片曾短暂改为 `确认创建 <item_id>` / `修改任务 <item_id> 负责人=姓名 截止=日期` / `拒绝创建 <item_id>` 操作口令，避免业务侧点击按钮报错。后续真正接入卡片回调时，回调入口仍必须重新经过 `ToolRegistry` 和 `AgentPolicy`。
- 2026-05-02：继续修复真实卡片回调的状态刷新问题。`scripts/post_meeting_live_test.py` 发送单条待确认按钮卡后，会立即把飞书返回的 `message_id` 绑定回本地 pending registry；`core/card_callback.py` 更新卡片时新增 `resolve_callback_message_id()`，优先使用 registry 中的真实 `message_id`，仅在缺少绑定时才回退到回调 payload 里的 `message_id/open_message_id`，避免把 `open_message_id` 误用于消息 PATCH 接口，导致卡片状态未刷新但 toast 已返回成功。同时把卡片里填写的截止时间归一化为 `YYYY-MM-DD`，兼容 `2025/5/3`、`2025/05/03`、`2025-05-03` 等常见输入格式。验证通过：`python3 -m py_compile core/card_callback.py core/post_meeting.py scripts/post_meeting_live_test.py tests/test_post_meeting_card_callback.py`；`python3 -m unittest tests/test_post_meeting_card_callback.py`（10 条用例全部通过，覆盖修改字段、确认创建、拒绝创建、重复点击拦截、消息 ID 优先级和截止时间格式兼容）。

### T4.8 新增本地 mock Demo

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：新增 `scripts/post_meeting_demo.py`，串联本地 M4 链路：`clean_meeting_transcript()` -> `extract_decisions()` / `extract_open_questions()` / `extract_action_items()` -> `build_post_meeting_summary_card()` / `build_pending_action_items_card()`。脚本默认运行 3 份内置 mock 纪要，覆盖完整任务、缺负责人、缺截止时间、语义模糊、决策句和开放问题；支持 `--sample` 选择样例、`--transcript-file` 读取本地纪要文本、`--show-card-json` 打印完整卡片 JSON。当前只使用 `--backend local`，不读取本地密钥、不访问飞书、不创建任务、不发送群消息。验证通过：`python3 -m py_compile core/post_meeting.py cards/post_meeting.py scripts/post_meeting_demo.py`；`python3 scripts/post_meeting_demo.py --backend local`；`python3 scripts/post_meeting_demo.py --backend local --sample complete --show-card-json`。本阶段同时修正清洗规则：`结论：xxx` / `待办：xxx` 不再被误切为章节标题；`决策：xxx` 能被识别为决策；含“待确认”字样的决策句不会再被开放问题重复抽取。

### T4.9 接入 `PostMeetingFollowupWorkflow` 本地上下文

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：在 `core/post_meeting.py` 新增 `build_post_meeting_artifacts()`、`build_post_meeting_artifacts_from_input()`、`collect_artifact_evidence()`，并在 `core/workflows.py` 的 `PostMeetingFollowupWorkflow.prepare_context()` 中写入 `post_meeting_artifacts`、`post_meeting_input`、`cleaned_transcript`、`meeting_summary_draft`、`post_meeting_card_payloads`。同步更新 `core/__init__.py` 导出 M4 结构和函数。验证通过：`python3 scripts/agent_demo.py --event-type minute.ready --minute-token minute_demo_001 --backend local --llm-provider scripted_debug --max-iterations 3`；本地构造 `WorkflowContext` 调用 `PostMeetingFollowupWorkflow.prepare_context()`，确认上下文包含 Action Items 和会后卡片 payload。
- 2026-05-02：继续把 M4 接回 Agent 主路径。在 `PostMeetingFollowupWorkflow.prepare_context()` 中补齐 `pending_action_items`、`auto_create_candidates`、`related_knowledge`，并让 `MeetFlowAgentLoop` 的运行时消息包含 `WorkflowContext.raw_context`，保证 LLM 能看到会后 artifacts、卡片 payload 和待确认状态。新增 `core/post_meeting_tools.py` 注册 `post_meeting.build_artifacts`、`post_meeting.enrich_related_knowledge`、`post_meeting.prepare_task`、`post_meeting.send_summary_card`、`post_meeting.save_pending_actions`；更新 `core/router.py`、`core/workflows.py`、`core/agent.py` 和 `scripts/agent_demo.py`，让 `minute.ready` 默认暴露 M4 工具、通讯录工具、RAG 工具和受控写工具。`scripted_debug` 已能按 Agent Loop 顺序执行：读取妙记 -> 构造 artifacts -> RAG -> `contact.search_user` 解析负责人 -> `post_meeting.prepare_task` 生成任务参数 -> `tasks.create_task` -> `post_meeting.send_summary_card` dry-run -> `post_meeting.save_pending_actions`。验证通过：`python3 -m py_compile core/*.py adapters/*.py scripts/*.py`；`python3 scripts/agent_demo.py --event-type minute.ready --minute-token obcn7xk3bg1olx8lb811fq4i --backend local --llm-provider scripted_debug --max-iterations 10 --allow-write` 成功产生 3 个受控副作用（本地模拟创建任务、会后卡片 dry-run、保存 pending registry）；`python3 scripts/agent_demo.py --event-type minute.ready --minute-token obcn7xk3bg1olx8lb811fq4i --backend local --llm-provider scripted_debug --max-iterations 6` 在未开启 `--allow-write` 时过滤写工具，最终只完成只读构造、RAG、人员解析和任务参数草案，无副作用。RAG 过程中沙箱禁止访问 HuggingFace HEAD 请求，知识检索按现有逻辑降级到关键词召回，并在结果中记录真实原因。

### T4.10 实现高置信任务创建请求与映射记录

- 优先级：`P0`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：在 `core/post_meeting.py` 新增 `build_task_create_arguments()`、`build_task_mapping_payload()`、`build_task_idempotency_key()`、`build_task_description()`、`parse_due_date_to_timestamp_ms()`、`next_weekday()`、`first_evidence_source_url()`。任务创建参数只生成受控 `tasks.create_task` 工具参数，不直接调用飞书；负责人 open_id 必须由后续通讯录工具解析后作为 `assignee_ids` 传入。扩展 `core/storage.py` 的 `task_mappings` 表和 `MeetFlowStorage.save_task_mapping()`，新增 `meeting_id`、`minute_token`、`title`、`evidence_refs_json`、`source_url` 字段，并通过 `_ensure_task_mapping_columns()` 兼容旧库。验证通过：本地构造 ActionItem 生成 `summary`、`assignee_ids`、`due_timestamp_ms`、`confidence`、`evidence_refs`、`idempotency_key`；临时 SQLite 存储写入并读取扩展后的 `task_mappings`；`python3 scripts/agent_policy_demo.py --scenario missing_task_fields` 已在 T4.6 验证策略层仍会拦截缺字段任务。

### T4.11 真实妙记只读联调

- 优先级：`P1`
- 当前状态：`已完成`
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

#### 实现记录

- 2026-05-01：新增 `scripts/post_meeting_live_test.py`，支持 `--minute` 读取真实妙记并转换为 M4 `PostMeetingArtifacts`，输出清洗摘要、决策、开放问题、Action Items、待确认任务和卡片摘要；`--read-only` 模式不创建任务、不发卡片。脚本会加载本地配置但不会打印 token、secret、API key。验证通过：`python3 scripts/post_meeting_live_test.py --help`；`python3 -m py_compile scripts/post_meeting_live_test.py`。未在本次自测中调用真实飞书妙记，因为需要用户提供真实妙记 URL/token 和已授权账号。
- 2026-05-01：`scripts/post_meeting_live_test.py` 增加 M3 RAG 复用入口，默认通过 `KnowledgeIndexStore` 对会议主题、关键结论、任务和开放问题构造查询，并把召回到的背景资料写入会后总结卡片；可用 `--skip-related-knowledge` 跳过，`--related-top-n` 控制数量。若本地 embedding / RAG 配置不可用，脚本记录 `related_knowledge_error` 并继续普通会后链路，不阻断只读验证或写入策略。验证通过：`python3 scripts/post_meeting_live_test.py --help`。
- 2026-05-01：修复真实妙记中“问题：存在全量预加载代价高...”被误判为开放问题的问题。开放问题抽取不再把所有 `问题：` / `风险：` / `阻塞：` 前缀都当成待澄清项，必须包含 `是否`、`能否`、`需要确认`、`谁`、`何时` 等确认意图。M4 RAG 查询也不再拼入开放问题内容，降低不相关文本污染召回的概率；相关背景资料按 document/source_url/title 去重，避免同一文档多个 chunk 在业务卡片中重复出现。

### T4.12 真实写入灰度验证

- 优先级：`P1`
- 当前状态：`已完成`
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
  - `python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --allow-write --send-card`
  - `python3 scripts/agent_demo.py --event-type minute.ready --minute-token '<真实 token>' --backend feishu --llm-provider scripted_debug --max-iterations 3 --allow-write`

#### 实现记录

- 2026-05-01：在 `scripts/post_meeting_live_test.py` 实现灰度写入路径：高置信且非待确认的 Action Item 会先通过 `contact.get_current_user` / `contact.search_user` 解析负责人 open_id，再构造 `tasks.create_task` 工具调用，并通过 `AgentPolicy.authorize_tool_call()` 审核后交给 `ToolRegistry.execute()`；创建成功后调用 `MeetFlowStorage.save_task_mapping()` 保存 M4/M5 稳定映射字段。若传入 `--send-card`，脚本会用同一套 `im.send_card` 工具发送会后总结卡和待确认卡，仍必须先有 `--allow-write`。验证通过：`python3 -m py_compile core/*.py cards/*.py scripts/post_meeting_demo.py scripts/post_meeting_live_test.py`；`python3 scripts/post_meeting_live_test.py --help`；本地任务参数与 `task_mappings` 冒烟测试。真实创建任务和真实群发卡片未在本次自测中执行，需用户提供真实妙记、测试群和 `--allow-write --send-card`。
- 2026-05-01：灰度写入链路补充自动建任务提示：只要高置信任务通过 `tasks.create_task` 成功创建，脚本会发送 `auto_created_tasks_card` 回告用户，即使本次没有额外传 `--send-card` 发送总结卡 / 待确认卡；该卡片同样走 `im.send_card`、`ToolRegistry` 和 `AgentPolicy`。`--report-dir` 模式下默认只落一份 Markdown report，控制台改为紧凑摘要，避免同一次测试同时生成/输出多份大报告；需要完整 JSON 时可显式加 `--print-report-json`。验证通过：`python3 -m py_compile core/post_meeting.py cards/post_meeting.py cards/__init__.py core/__init__.py scripts/post_meeting_demo.py scripts/post_meeting_live_test.py`。

## 真实链路运行记录

### 2026-05-01 M4 真实妙记到卡片/任务联调

- 目标：使用用户提供的 3 条真实妙记链接跑通 M4 全链路，包含真实读取妙记、清洗抽取、生成会后总结卡/待确认卡、通过 `ToolRegistry` + `AgentPolicy` 创建高置信任务并保存 `task_mappings`。
- 输入链接：
  - `https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11`
  - `https://jcneyh7qlo8i.feishu.cn/minutes/obcn9xr813z8jcz9en81cyqc`
  - `https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i`
- 执行过的只读命令：
  - `python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcnb2q4nap98l5ny5as2n11' --read-only --content-limit 800`
- 只读结果：
  - 沙箱内首次请求飞书开放平台失败，原因是网络/代理访问 `open.feishu.cn` 被限制；随后在用户授权的外部网络权限下重试。
  - 第一条妙记曾以 `user` 身份读取成功，标题为“飞书 AI 校园竞赛-主题分享直播-产品专场”，并进入 M4 清洗、决策、开放问题、Action Items 和卡片预览链路。
  - 当时发现真实 AI 摘要中大量普通编号段落被误抽取为 Action Item，随后已收紧 `core/post_meeting.py` 的候选行规则：优先从显式待办章节、任务前缀、负责人/截止时间信号中抽取，避免把普通议程和背景描述误建任务。
- 后续阻塞：
  - 再次以 `user` 身份访问飞书时，OAuth 刷新接口返回 HTTP 400，飞书错误码 `20064`，表现为本地 `refresh_token` 已失效或已被使用。原因判断：第一次成功读取时触发了 token refresh，但旧版本脚本没有把新的 refresh token 写回本地配置。
  - 以 `tenant` 身份读取妙记时，飞书返回 `99991672` 权限不足，提示应用缺少 `minutes:minutes` / `minutes:minutes:readonly` / `minutes:minutes.basic:read` 之一。说明当前应用机器人身份不能读取这几条妙记。
  - 尝试执行 `python3 scripts/oauth_device_login.py` 恢复用户 OAuth 时，命令停在“正在向飞书申请 device_code”，没有拿到可展示给用户的授权 URL 或 code；已终止该挂起进程，避免留下后台任务。
- 已做修复：
  - `scripts/post_meeting_live_test.py` 创建 `FeishuClient` 时已接入 `user_token_callback=lambda bundle: save_token_bundle(settings, bundle)`，后续只要重新完成用户授权，刷新到的新 token 会写回本地配置，避免再次因为刷新后未持久化而失效。
  - `scripts/post_meeting_live_test.py` 的只读输出已改为摘要化展示 `workflow_input`，不再把真实妙记正文整段打印到终端。
  - `core/post_meeting.py` 已修正真实摘要下的误抽取问题，降低把背景、议程、章节说明误判为任务的风险。
- 当前结论：
  - M4 代码链路已具备真实读、真实发卡、真实建任务的执行入口和策略保护；本次真实全链路没有完成到“群里收到卡片/飞书任务创建成功”，真实阻塞点是飞书授权状态和应用 scope，而不是本地语法或 M4 业务代码。
  - 还没有对上述 3 条链接执行真实 `--allow-write --send-card`；因此本次没有真实发送卡片，也没有真实创建任务。
- 2026-05-01 继续联调结果：
  - 用户完成 OAuth Device Flow 授权后，3 条真实妙记均已通过 `scripts/post_meeting_live_test.py --identity user --read-only` 读取成功。
  - 3 条真实妙记均已执行 `--allow-write --send-card`。共发送 5 张飞书 interactive card：第一条 summary/pending 各 1 张，第二条 summary 1 张，第三条 summary/pending 各 1 张。
  - 本轮没有创建飞书任务，也没有新增真实 `task_mappings`，原因是抽取出的 Action Items 均缺负责人、缺截止时间或置信度低于 0.75，被 M4 业务层和 `AgentPolicy` 前置为待确认。这符合“字段不完整就待确认，不盲目写任务”的安全规则。
  - 完整运行报告已保存到 `storage/reports/m4/post_meeting_live_chain_2026-05-01.md`，包含命令、读取结果、卡片 message_id、跳过建任务原因和写入后检查结果。
- 2026-05-01 修复后重测：
  - 修复 `core/post_meeting.py` 中负责人、截止时间、标题清洗和开放问题过滤规则：支持 `@姓名`、`@所有参赛同学`、`今天或最晚明天`、`今天到明天` 等真实妙记表达；群体负责人会展示为候选但标记“缺少可解析负责人”，不自动创建任务；章节标题不再误判为开放问题。
  - `scripts/post_meeting_live_test.py` 新增 `--report-dir`，每次真实联调可生成 M3 风格 Markdown 报告，展示妙记输入、工作流阶段、Action Items、证据、卡片和写入结果。
  - 已重新对 3 条真实妙记执行只读复验和 `--allow-write --send-card`。第三条妙记的待确认任务已能识别负责人候选和复合截止时间：`所有参赛同学 / 今天或最晚明天`、`所有参赛同学 / 今天到明天`、`王恂 / 缺截止时间`；开放问题从旧版 6 条噪声收敛为 1 条真实问题。
  - 重测报告保存到 `storage/reports/m4/rerun_2026-05-01/`，语法检查 `python3 -m py_compile core/*.py adapters/*.py config/*.py cards/*.py scripts/*.py` 通过。
- 2026-05-01 M4 优化：
  - 待确认任务卡片已增加负责人、截止时间、优先级、置信度、待确认原因和证据片段的复核区，并预留确认创建 / 修改信息 / 拒绝创建按钮 action value。
  - 会后总结卡片的关键结论区增加兜底抽取：如果真实妙记没有显式“关键结论 / 决策”段落，会从会议总结正文中选取保守摘要行，避免关键结论区为空。
  - 会后总结卡片新增相关背景资料区块，复用 M3 `KnowledgeIndexStore.search_chunks()` 的轻量 RAG 召回结果。
  - 自动创建任务成功后会发送 `MeetFlow 已创建任务提醒` 卡片；报告输出在 `--report-dir` 下默认仅生成一份 Markdown 文件，控制台只打印紧凑摘要。
- 2026-05-01 群消息反馈修复：
  - 开放问题误抽取来源：真实妙记 AI 总结中的 `问题：存在全量预加载代价高...` 被旧规则按 `问题：` 前缀误判；已收紧为必须有明确待确认语气。
  - 相关背景资料重复来源：M3 RAG 返回同一文档的多个 chunk；已按文档维度去重。
  - 证据引用区块改为仅保留在 report，不再进入业务群卡片。
  - 按钮报错来源：项目尚未接入飞书卡片回调服务，点击 button 会触发飞书回调但无人处理；待确认卡先改为操作口令，避免业务侧点击报错。
- 2026-05-01 卡片回调服务：
  - 新增 `core/card_callback.py`，负责解析飞书 interactive card 回调 payload，处理 `confirm_create_task`、`edit_task_fields`、`reject_create_task` 三类动作，并将处理结果写入 `storage/card_callbacks.jsonl` 审计日志。
  - 新增 `scripts/post_meeting_card_callback_server.py`，提供 `POST /feishu/card/callback` 和 `GET /healthz`；支持飞书 URL challenge，按钮点击后返回 toast 响应。
  - `confirm_create_task` 会从按钮 value 还原 `ActionItem` 和 `WorkflowContext`，再通过 `ToolRegistry` 执行 `tasks.create_task`，写操作仍由 `AgentPolicy.authorize_tool_call()` 重新校验；创建成功后写入 `task_mappings`，供 M5 风险巡检复用。
  - `cards/post_meeting.py` 恢复待确认任务的确认创建 / 修改信息 / 拒绝创建按钮，并在 value 中携带任务标题、负责人、截止时间、优先级、置信度、会议 ID、妙记 token 和证据片段，避免回调服务依赖卡片展示文本做脆弱解析。
  - 本地验证通过：`python3 -m py_compile core/card_callback.py core/post_meeting.py cards/post_meeting.py core/__init__.py scripts/post_meeting_card_callback_server.py scripts/post_meeting_demo.py scripts/post_meeting_live_test.py`；`curl -X POST http://127.0.0.1:8787/feishu/card/callback -d '{"challenge":"meetflow-check"}'` 返回 challenge；模拟拒绝按钮返回成功 toast；模拟确认按钮进入策略校验并按负责人不可解析返回业务错误 toast，而非服务报错。
- 2026-05-01 本地群消息确认模式：
  - 为避免比赛演示阶段配置公网 HTTPS 回调地址，待确认卡片改为展示群消息操作口令：`确认创建 action_xxx`、`确认创建 action_xxx 负责人=姓名 截止=明天`、`修改任务 action_xxx 负责人=姓名 截止=明天`、`拒绝创建 action_xxx`。这样卡片内不再出现会触发飞书回调报错的按钮。
  - 新增 `core/confirmation_commands.py`，负责解析确认口令、提取负责人 / 截止时间覆盖字段，并用 `storage/post_meeting_pending_actions.json` 保存每个待确认任务的完整上下文。
  - `scripts/post_meeting_live_test.py --send-card` 发送待确认卡片前会自动保存 pending action registry，后续监听器只需要从群消息拿到 `item_id` 即可找回任务标题、证据、会议 ID 和妙记 token。
  - 新增 `scripts/post_meeting_confirmation_watcher.py`，轮询群消息并处理确认口令；确认创建仍复用 `handle_post_meeting_card_callback()`，因此任务创建继续经过 `ToolRegistry`、`AgentPolicy` 和 `task_mappings` 记录。处理结果通过 `im.send_text` 回到群里。
  - 真实读取群消息自测结果：当前应用缺少消息读取 scope。`--identity user` 缺 `im:message.group_msg:get_as_user`，`--identity tenant` 缺 `im:message.group_msg`。监听器已将该错误转换为明确提示；补齐 scope 并重新授权后可执行 `python3 scripts/post_meeting_confirmation_watcher.py --since-minutes 30` 启动本地轮询。
- 2026-05-01 Reaction 一键确认模式：
  - 新增 `FeishuClient.list_message_reactions()`，支持读取某条消息上的 reaction 记录。
  - 新增 `scripts/post_meeting_live_test.py --send-reaction-cards`：在总卡之外，为每个待确认任务额外发送一条普通文本确认消息。原因是飞书 reaction 只绑定到整条 `message_id`，不能定位到同一张卡片里的第 N 个任务；interactive card 在当前飞书客户端里也没有可点击表情入口，因此 reaction 载体必须使用普通消息。普通消息发送成功后会保存 `message_id -> action_id` 到 `storage/post_meeting_pending_actions.json`。
  - `scripts/post_meeting_confirmation_watcher.py --watch-reactions` 会轮询这些 message_id 的 reaction：`CheckMark` / `DONE` / `OK` / `THUMBSUP` / `Yes` / `LGTM` 表示确认创建，`CrossMark` / `No` / `ThumbsDown` / `ERROR` 表示拒绝创建；确认创建仍复用 `handle_post_meeting_card_callback()` 和 `AgentPolicy`。
  - 已完成真实发送自测：`python3 scripts/post_meeting_live_test.py --identity user --minute 'https://bytedance.larkoffice.com/minutes/obcn7xk3bg1olx8lb811fq4i' --allow-write --send-card --send-reaction-cards --content-limit 300 --report-dir storage/reports/m4/full_chain_2026-05-01`，本次发送 5 张卡片（summary 1、pending 总卡 1、单任务 reaction 卡 3），报告保存到 `storage/reports/m4/full_chain_2026-05-01/post_meeting_live_obcn7xk3bg1olx8lb811fq4i_write_20260501_152327.md`。
  - 已完成 watcher 自测：`python3 scripts/post_meeting_confirmation_watcher.py --once --dry-run --watch-reactions --since-minutes 10` 能读取三条单任务卡的 reaction 接口，当前未处理任务是因为尚未有人点确认/拒绝表情。
  - 根据真实客户端反馈，interactive card 无法点表情后已切换为普通文本确认消息，并完成重测：`post_meeting_live_obcn7xk3bg1olx8lb811fq4i_write_20260501_152710.md` 发送 summary card 1、pending card 1、pending reaction message 3；watcher 能读取三条普通消息的 reaction 接口，当前未处理任务是因为尚未有人点确认/拒绝表情。
  - 根据进一步真实反馈，当前群里普通机器人文本消息也无法点击 reaction。已改为“回复这条消息”模式：普通确认消息提示用户直接回复 `确认` / `拒绝`，watcher 会从回复消息的 `parent_id` / `root_id` / `thread_id` 等引用字段反查 `message_id -> action_id`，不再要求复制 action_id。保底仍支持 `确认创建 action_xxx 负责人=姓名 截止=明天`。
- 2026-05-02 M4 Agent 主路径真实发卡测试：
  - 执行目标：验证 `minute.ready -> WorkflowRouter -> WorkflowContextBuilder -> MeetFlowAgentLoop -> ToolRegistry -> AgentPolicy -> FeishuClient / Storage` 的真实飞书读写路径，允许向默认测试群发送会后卡片，但本次不开放 `tasks.create_task`，避免真实创建任务。
  - 初次沙箱内执行 `python3 scripts/agent_demo.py --event-type minute.ready --minute-token obcn7xk3bg1olx8lb811fq4i --backend feishu --llm-provider scripted_debug --max-iterations 8 --allow-write --tool minutes.fetch_resource --tool post_meeting.build_artifacts --tool post_meeting.enrich_related_knowledge --tool post_meeting.send_summary_card --tool post_meeting.save_pending_actions` 失败，原因是沙箱无法连接本地代理 `127.0.0.1:7890`，飞书 OAuth token 请求被 `Operation not permitted` 拦截；随后按工具审批机制使用外部网络权限重跑。
  - 第一次外部网络重跑读取真实妙记成功，并向测试群发送一张卡片，message_id=`om_x100b506c73e554a4b397a49b1f33f73`。该卡片暴露出 `scripted_debug` 从截断 tool content 反解析 artifacts 的问题，导致卡片内容退化为“待识别会议 / 行动项 0 条”。
  - 修复方式：在 `core/models.py` 的 `AgentLoopState.append_tool_result()` 中把结构化 `AgentToolResult.data` 放入 tool message metadata；在 `scripts/agent_demo.py` 的 `extract_tool_data()` 中优先读取 metadata data，再回退解析文本。这样 Agent 调试链路不再依赖被截断的 JSON 文本。
  - 修复后验证通过：`python3 -m py_compile core/*.py scripts/agent_demo.py`。
  - 修复后重跑命令：`python3 scripts/agent_demo.py --event-type minute.ready --minute-token obcn7xk3bg1olx8lb811fq4i --backend feishu --llm-provider scripted_debug --max-iterations 8 --allow-write --calendar-id m4-agent-real-2 --tool minutes.fetch_resource --tool post_meeting.build_artifacts --tool post_meeting.enrich_related_knowledge --tool post_meeting.send_summary_card --tool post_meeting.save_pending_actions`。
  - 结果：真实读取妙记《飞书 AI 校园挑战赛-开赛仪式（线上直播）》成功；M4 artifacts 抽取出 3 条待确认 Action Items，均未自动创建任务；M3 RAG 返回相关背景资料；向测试群 `oc_3e432398cc43063fda2b2d322bb6dead` 发送会后 summary card 成功，message_id=`om_x100b506c0e471ca0b4a05fa593e005f`；`post_meeting.save_pending_actions` 保存 3 条待确认 registry：`action_8300b9d673db`、`action_67134048d3a5`、`action_0411a220a418`。
  - 安全边界：本次只开放 `post_meeting.send_summary_card` 和 `post_meeting.save_pending_actions` 两个写工具，并显式使用 `--allow-write` 让 `AgentPolicy` 审核；未开放 `tasks.create_task`，没有创建真实飞书任务。
- 2026-05-02 长连接卡片回调脚本兼容性修复：
  - 用户执行 `./.venv-lark-oapi/bin/python scripts/post_meeting_card_callback_ws.py --dry-run --log-level debug` 时，在 `resolve_lark_log_level()` 阶段抛出 `AttributeError: WARN`，导致脚本在真正建立 WebSocket 前就退出。
  - 根因是 `lark-oapi==1.4.0` 的 `LogLevel` 枚举成员名为 `WARNING`，而不是 `WARN`；旧实现又在构造整张映射表时提前访问所有成员，即使传入的是 `debug` 也会先触发 `WARN` 异常。
  - 修复方式：更新 `scripts/post_meeting_card_callback_ws.py`，改为先解析输入字符串，再按成员名延迟 `getattr()`；同时兼容 `warn` / `warning` -> `WARNING`，并补充 `critical`。
  - 验证结果：`python3 -m py_compile scripts/post_meeting_card_callback_ws.py` 通过；`./.venv-lark-oapi/bin/python scripts/post_meeting_card_callback_ws.py --help` 可正常输出帮助，不再在日志级别解析阶段崩溃。
- 2026-05-02 按钮探针订阅锁恢复：
  - 用户执行 `python3 scripts/post_meeting_card_button_ws_probe.py --chat-id oc_3e432398cc43063fda2b2d322bb6dead --listen-seconds 180` 时，`lark-cli event +subscribe` 直接退出，错误为 `another event +subscribe instance is already running ... Use --force to bypass this check`。
  - 根因是上一次长连接异常关闭后，`lark-cli` 仍认为该 app 的订阅实例占用中；这是 CLI 的单实例保护，不是 MeetFlow 发卡逻辑故障。
  - 修复方式：为 `scripts/post_meeting_card_button_ws_probe.py` 新增 `--force-subscribe`，内部给 `lark-cli event +subscribe` 追加 `--force`，便于本地恢复测试。
  - 使用说明：恢复测试时可运行 `python3 scripts/post_meeting_card_button_ws_probe.py --chat-id <oc_xxx> --listen-seconds 180 --force-subscribe`。注意 `--force` 会绕过单实例保护；若同时有多个订阅端在线，飞书会把事件随机分流到不同连接。
- 2026-05-02 待确认任务从“回复消息”迁回“卡片按钮”：
  - 前提变化：`card.action.trigger` 长连接回调已在真实环境中打通，待确认卡片按钮点击可以稳定收到回调事件。
  - 业务调整：`cards/post_meeting.py` 的 `pending_card` 从“展示操作口令”改成直接渲染按钮表单。每条待确认任务现在都会展示两个输入框（负责人、截止时间）以及 `确认创建`、`修改信息`、`拒绝创建` 三个按钮；用户不再需要先回复消息或手输 `确认创建 action_xxx`。
  - 回调调整：`core/card_callback.py` 现在会把 `action.form_value` 合并进按钮上下文，支持从卡片表单读取 `owner_override` / `due_date_override`；`edit_task_fields` 会直接更新本地 pending registry，`confirm_create_task` 会先持久化最新字段，再通过 `ToolRegistry + AgentPolicy` 创建任务，并把 pending 状态更新为 `created` / `pending` / `reject_create_task`。
  - 兼容策略：旧的 `scripts/post_meeting_confirmation_watcher.py`、`scripts/post_meeting_confirmation_event_watcher.py` 和 reply/reaction 确认模式保留为兜底，不再作为 M4 默认主路径；`core/post_meeting_tools.py` 的 pending registry 描述和 `scripts/post_meeting_agent_live_test.py` 的提示也同步改为“按钮优先，watcher 兜底”。
  - 新增统一入口：`scripts/post_meeting_button_flow_live_test.py`。其中 `callback` 子命令用于启动 `card.action.trigger` 长连接回调，`send` 子命令用于读取真实妙记并向测试群发送待确认按钮卡，减少真实联调时手工拼多条命令的成本。
  - 自测结果：
    - `python3 -m py_compile core/card_callback.py cards/post_meeting.py scripts/post_meeting_live_test.py tests/test_post_meeting_card_callback.py`
    - `python3 -m unittest tests/test_post_meeting_card_callback.py`
    - `python3 -m py_compile scripts/post_meeting_button_flow_live_test.py`
    - `python3 scripts/post_meeting_button_flow_live_test.py --help`
    - 4 个用例全部通过，覆盖：
      1. 待确认卡片输出 `schema=2.0` 表单与三类按钮；
      2. `修改信息` 按钮把表单字段写回 pending registry；
      3. `确认创建` 按钮带表单字段走 `ToolRegistry + AgentPolicy` 并把状态更新为 `created`；
      4. `拒绝创建` 按钮把状态更新为 `reject_create_task`。
- 2026-05-02 按钮交互体验修复：
  - 用户反馈的 3 个问题本质上都出在两个兼容点：一是回调里用 `user` 身份去更新机器人发送的卡片消息，导致 `update_card_message` 抛异常；二是待确认卡仍混用了旧版 interactive card DSL，群聊里无法稳定显示输入框。
  - 现已把 `cards/post_meeting.py` 的单任务待确认卡统一改成新版 `schema=2.0` 表单卡，并修正 form 结构：`form` 组件直接使用 `direction/horizontal_spacing/vertical_spacing/elements`，不再使用旧版 `body/actions` 壳子。这样群聊里会直接显示负责人/截止时间输入框，不需要点击按钮后再赌前端弹出编辑层。
  - `core/card_callback.py` 现在不再依赖回调响应体里的 `card` 替换，而是收到按钮事件后显式调用 `FeishuClient.update_card_message()` 更新原消息；同时把身份修正为 `tenant`，并吞掉消息更新异常，避免飞书前端把整个按钮点击显示成红色叉号失败提示。
  - `reject_create_task` 现在会把群里卡片更新为“已拒绝创建，MeetFlow 不会再自动落地这条任务”，同时 toast 为成功态；`confirm_create_task` 成功后会把卡片更新为“已创建任务”，并在任务结果里携带任务跳转链接；创建失败时会切回编辑态卡片，直接展示失败原因，便于继续补字段。
  - `scripts/post_meeting_button_flow_live_test.py` 新增解释器自动探测：`send` 会自动寻找包含 `chromadb + sentence_transformers` 的 Python，`callback` 会自动寻找包含 `lark_oapi` 的 Python，避免同时激活 Conda 和 venv 时裸 `python3` 指到错误环境。
  - `core/knowledge.py` 为 Chroma 向量索引补充了 `_last_error` 诊断信息；后续如果再次出现“ChromaDB 不可用，无法执行向量检索”，`reason` 中会带上更具体的初始化异常，而不再只有笼统提示。
  - 自测结果：
    - `python3 -m py_compile core/card_callback.py cards/post_meeting.py scripts/post_meeting_button_flow_live_test.py core/knowledge.py tests/test_post_meeting_card_callback.py`
    - `python3 -m unittest tests/test_post_meeting_card_callback.py`
    - `python3 scripts/post_meeting_button_flow_live_test.py --help`
    - 5 个用例通过，新增覆盖：
      1. `修改信息` 回调会更新 pending registry，并通过消息更新接口切换到编辑态/暂存态卡片；
      2. `拒绝创建` 会把 toast 保持为成功态，并更新原卡片为已拒绝状态；
      3. `确认创建` 会更新原卡片为已创建状态；
      4. 入口脚本帮助页可正常输出；
      5. 单任务待确认卡会生成 `schema=2.0` + `form` 的可编辑卡片 JSON。
- 2026-05-02 对齐官方新版卡片表单容器结构：
  - 用户继续反馈“群里有按钮但没有输入框”。结合飞书官方《卡片搭建说明》，确认群聊里可编辑输入框依赖新版卡片的**表单容器**，其关键约束是：`form` 必须位于卡片根级节点下；输入框位于 `form.elements` 中；提交按钮使用 `form_action_type=submit`，并通过 `behaviors=[{type: callback, value: ...}]` 绑定卡片回调。
  - 修复方式：`cards/post_meeting.py` 的单任务待确认卡重新改为符合官方结构的 `schema=2.0` 卡片：`body.elements = [markdown, form]`，表单容器内放置两个输入框和三枚按钮；不再把旧版 interactive card 的 `value + action` DSL 直接套到新版卡片上。
  - 同时保留 `adapters/feishu_tools.py` 中的 fallback 透出：如果飞书再次拒绝新版卡片，会在返回结果中写明 `card_delivery=fallback_card` 和 `fallback_reason`，便于区分“业务卡发送成功”和“被飞书回退成摘要卡”的差别。
  - 自测结果：
    - `python3 -m py_compile cards/post_meeting.py tests/test_post_meeting_card_callback.py`
    - `python3 -m unittest tests/test_post_meeting_card_callback.py`
    - 6 个用例通过，新增验证单任务待确认卡会生成 `schema=2.0 + body.elements[1].tag=form + behaviors callback + form_action_type=submit` 的 JSON。
- 2026-05-02 卡片状态刷新与重复点击幂等修复：
  - 用户反馈：卡片已能显示输入框并创建任务，但点击 `确认创建 / 拒绝创建` 后卡片状态没有刷新，旧卡仍可继续点击，导致“已创建任务又能被拒绝”。
  - 根因一：`scripts/post_meeting_live_test.py` 在发送单任务待确认卡后，没有把飞书返回的 `message_id` 绑定回 `storage/post_meeting_pending_actions.json`。这样回调侧更新卡片时只能赌 payload 里是否自带可用 `message_id`，成功率不稳定。
  - 根因二：`core/card_callback.py` 之前缺少“已创建 / 已拒绝”的状态守卫。即使卡片刷新失败，只要旧消息按钮还能点，就可能再次进入业务逻辑。
  - 修复方式：
    - `scripts/post_meeting_live_test.py` 发送每张 `pending_button_card` 成功后，立即调用 `bind_pending_action_message()` 保存 `item_id -> message_id` 绑定。
    - `core/card_callback.py` 的 `apply_callback_card_update()` 增加 fallback：优先从回调 payload 提取 `message_id`，提取不到时回退到本地 pending registry 里已绑定的 `message_id`。
    - `core/card_callback.py` 新增 `guard_pending_action_transition()`：当任务状态已是 `created` 或 `reject_create_task` 时，重复点击不会再改写状态，只返回成功提示，并尝试把卡片刷新回已处理态。
  - 自测结果：
    - `python3 -m py_compile core/card_callback.py scripts/post_meeting_live_test.py tests/test_post_meeting_card_callback.py`
    - `python3 -m unittest tests/test_post_meeting_card_callback.py`
    - 7 个用例通过，新增覆盖“任务已创建后再次点击拒绝会被拦截，并沿用绑定的 `message_id` 刷新原卡片”。
- 2026-05-02 卡片按钮交叉点击竞态修复：
  - 用户反馈：希望点击 `确认创建 / 拒绝创建` 后，对应按钮立即消失或不能再按，避免同一条待确认任务被先创建、再拒绝，或快速重复点击触发多次创建。
  - 修复方式：
    - `core/confirmation_commands.py` 新增 `claim_pending_action_status()`，在真实写接口执行前先把 pending registry 中的任务抢占到 `creating` / `rejecting` 状态。
    - `core/card_callback.py` 在 `confirm_create_task` 调用飞书任务创建前先进入 `creating`；创建失败时退回 `pending`，创建成功后进入 `created`。`reject_create_task` 先进入 `rejecting`，随后落为 `reject_create_task`。
    - `guard_pending_action_transition()` 新增对 `creating` / `rejecting` 的拦截：如果旧卡按钮尚未刷新消失，后续点击只会返回“正在处理”的提示，并尝试把卡片刷新为无按钮结果态，不再进入创建或拒绝副作用。
    - `tests/test_post_meeting_card_callback.py` 新增“创建处理中再次点击拒绝会被拦截”的用例，确保状态保持为 `creating`，且回写卡片中不再包含 `拒绝创建` 按钮。
  - 自测结果：
    - `python3 -m py_compile core/card_callback.py core/confirmation_commands.py tests/test_post_meeting_card_callback.py`
    - `python3 -m unittest tests.test_post_meeting_card_callback`
    - 11 个用例通过，覆盖修改字段、确认创建、拒绝创建、已处理重复点击、处理中交叉点击、消息 ID 绑定优先级和截止时间格式兼容。
- 2026-05-04 M4 会后卡片与 RAG query 优化：
  - 新增 `cards/layout.py`，沉淀 MeetFlow 卡片统一外壳：旧版 interactive card 统一 `config.wide_screen_mode + header + elements`，新版按钮表单卡统一 `schema=2.0 + config.update_multi + body.padding`。`cards/post_meeting.py` 的会后总结卡、待确认总卡、单任务按钮卡和 reaction 兜底卡均改为复用该骨架，避免 M3/M4 后续各自手写 header/config 造成格式漂移。
  - 新增 `RelatedKnowledgeQueryPlan` 和 `build_post_meeting_related_resource_query_plan()`。M4 相关背景资料召回不再直接拼接“主题 + project_id + 前 4 条决策 + 前 4 条行动项标题”，而是按来源加权提取业务关键词：`topic` / `project_id` 权重最高，`decision` 次之，`action_item` 只保留任务对象名，`open_question` 和 `related_resource` 低权重补充。
  - Query 生成会过滤负责人、截止时间、日期、URL、@人名、待办动词等执行噪声，并把 `query`、`terms`、`term_sources`、`dropped_terms`、`source_weights` 写入 `artifacts.extra["related_knowledge_query_plan"]`；`post_meeting.enrich_related_knowledge` 工具返回中也新增 `query_plan`，便于联调报告解释“为什么搜这些词”。
  - 自测结果：
    - `python3 -m py_compile cards/layout.py cards/pre_meeting.py cards/post_meeting.py core/post_meeting.py core/post_meeting_tools.py core/__init__.py tests/test_post_meeting_rag_query.py tests/test_post_meeting_card_callback.py`
    - `python3 -m unittest tests.test_post_meeting_rag_query tests.test_post_meeting_card_callback`
- 2026-05-04 新增卡片效果预览脚本：
  - 新增 `scripts/card_preview_demo.py`，默认同时生成 M3/M4 预览；M4 部分会输出 `summary_card`、`pending_card`、`pending_button_card` 和 `query_plan`，全程不访问飞书、不触发写操作。
  - 推荐命令：`python3 scripts/card_preview_demo.py --workflow m4 --print-json`；或 `python3 scripts/card_preview_demo.py --workflow both --output-dir storage/reports/card_preview` 将每张卡片写成独立 JSON 文件，便于对比统一卡片骨架是否生效。
- 2026-05-04 新增 M4 后台常驻入口：
  - 新增 `scripts/meetflow_daemon.py`。M4 不假设飞书一定提供“妙记 ready”直推事件，而是扫描最近已结束会议，等待 `--m4-delay-minutes` 后通过 `lark-cli vc +recording --calendar-event-ids <event_id>` 查询 `minute_token`；拿到妙记后调用 `card_send_live.py m4` 发会后总结卡和待确认卡。
  - 该模式可以由日历变更事件 `calendar.calendar.event.changed_v4` 实时唤醒，也会按 `--poll-seconds` 定时兜底，避免事件漏投或妙记延迟生成导致 M4 不触发。
  - 验证通过：`python3 -m py_compile scripts/meetflow_daemon.py`；`python3 scripts/meetflow_daemon.py --help`。
- 2026-05-04 新增真实环境观察台：
  - 新增 `scripts/live_environment_watch.py`。脚本会启动 `lark-cli event +subscribe` 长连接，打印收到的日历事件和云文档事件，并复用 `meetflow_daemon.py` 的触发函数展示 M3/M4 发卡意图、RAG 索引任务变化。
  - 默认 `--allow-card-send` 未开启时，M3/M4 只打印将执行的发卡命令，不真实发送；RAG 默认会真实刷新本地索引，方便用户手动编辑云文档后立即看到 `index_jobs` 状态变化。
  - 针对本地 `lark_oapi` 与 RAG 依赖分环境安装的问题，脚本新增 `--python-bin` 和 `--lark-cli-bin`；启用 RAG 时会自动寻找包含 `chromadb/sentence_transformers` 的解释器并重启主进程，长连接仍由 `lark-cli` 子进程承担。
  - 验证通过：`python3 -m py_compile scripts/live_environment_watch.py`；`python3 scripts/live_environment_watch.py --help`；`.venv-lark-oapi/bin/python scripts/live_environment_watch.py --help`。
- 恢复后继续验证命令：
  - 先重新完成用户 OAuth 授权，或在飞书开发者后台给应用补齐妙记读取 scope 后重新发布/授权。
  - 授权恢复后先逐条只读验证：`python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --read-only --content-limit 300`
  - 只读结果确认后再做灰度写入：`python3 scripts/post_meeting_live_test.py --identity user --minute '<真实妙记 URL>' --allow-write --send-card --content-limit 300`
  - 写入成功后检查本地 `task_mappings` 和审计日志，确认 `item_id`、`task_id`、`meeting_id`、`minute_token`、`title`、`owner`、`due_date`、`evidence_refs`、`source_url` 已留存，供 M5 风险巡检消费。

## 推荐执行顺序

1. 先完成 T4.1，锁定任务拆分。
2. 再按 T4.2-T4.8 完成本地纯函数、卡片和 mock demo。
3. 然后做 T4.9，把本地产物接入 Agent 工作流上下文。
4. T4.10 只在本地和 Policy 层稳定后再做。
5. T4.11 做真实只读验证。
6. T4.12 最后做真实写入灰度验证。

---
