# D4：妙记 Agent 分析与任务卡片生成落地记录

## 1. 任务定位

D4 面向 OpenClaw / 答辩演示中的“会后任务分配”环节，目标是让 MeetFlow 不只总结妙记，
而是把妙记里的协作意图拆成可确认、可追踪、可创建的任务卡片：

```text
飞书妙记
  -> Agent / M4 工具链读取并清洗
  -> 抽取 ActionItem
  -> 按负责人聚合
  -> 标记缺失字段、优先级、状态和证据来源
  -> 生成任务卡片
  -> 用户确认后再经过 AgentPolicy 创建飞书任务
```

D4 不新增一条独立工作流，而是在现有 M4 `post_meeting_followup` 主链路上增强任务卡片产物。

## 2. 当前代码基线

| 能力 | 当前实现 | D4 判断 |
|---|---|---|
| 妙记读取 | `minutes.fetch_resource`、`FeishuClient.fetch_minute_resource()` | 已具备；Agent 链路固定 user 身份读取妙记 |
| 行动项抽取 | `core/post_meeting.py::extract_action_items()` | 已具备负责人、截止时间、优先级和证据片段抽取 |
| 缺字段标记 | `mark_action_item_confirmation_state()` | 已具备 `missing_fields`、`confirm_reason` 和置信度 |
| 按人聚合 | `group_action_items_by_owner()` | D3 已用于总结卡；D4 需要更稳定的任务卡分析包 |
| 待确认任务卡 | `build_pending_action_items_card()`、`build_pending_action_item_button_card()` | 已具备按钮、表单和回调 value |
| 状态流转 | `core/card_callback.py`、`core/confirmation_commands.py` | 已具备确认、修改、拒绝、旧卡拦截和审计 |
| 任务创建安全 | `AgentPolicy._authorize_create_task()` | 已要求人工确认、负责人、截止时间、置信度和幂等键 |

## 3. 本轮完成内容

本轮完成 D4 首轮代码接入，重点是把已有 M4 能力整理成稳定的“任务卡分析包”，供飞书卡片、报告、
Console 和 OpenClaw 后续复用。

### 3.1 新增 D4 任务卡分析包

新增 `core/post_meeting.py::build_task_card_analysis()`，并在 `merge_d3_review_fields()` 中写入：

```python
artifacts.extra["task_card_analysis"]
artifacts.extra["d4_metrics"]
```

分析包包含：

- `cards`：每条任务的标题、负责人、参与人、截止时间、优先级、状态、缺失字段、来源片段和 Agent 建议。
- `owner_groups`：按负责人聚合任务，包含待补字段数量、字段完整数量和高优任务数量。
- `duplicate_hints`：同轮妙记内的轻量合并/去重提示，只提示不自动合并。
- `summary`：任务数、待确认数、负责人分组数、去重提示数。

负责人和截止时间展示规则：

- 妙记中抽取出的负责人文本只是 `owner_candidate`，不等于飞书组织中的真实用户。
- 只有后续链路能提供 `owner_open_id`、`owner_user_id` 或 `owner_resolution_status=resolved/verified` 时，任务卡才展示为负责人；否则统一显示“待补充”。
- “周四 / 星期四 / 明天 / 2026-05-12”等时间词不能作为负责人。
- 截止时间在展示层统一为 `YYYY-MM-DD`；无法可靠解析时显示“待补充”，原始文本保存在 `due_date_raw` 便于人工核对。

### 3.2 增强任务卡片展示

更新 `cards/post_meeting.py`：

- 单条待确认任务卡展示 `Agent 建议`。
- 缺字段任务展示 `缺失字段`。
- 聚合待确认任务卡在缺少完整 artifacts 时也能基于 `ActionItem.extra` 生成一致建议。

### 3.3 保持安全边界

D4 仍然不绕过主链路：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

所有任务创建仍必须由用户在任务卡片中确认，并重新经过 `AgentPolicy`。

### 3.4 补充负责人真实解析逻辑

本轮补充了 D4 任务卡发卡前的通讯录解析逻辑，避免只在按钮确认阶段才解析负责人：

- `core/post_meeting_tools.py::resolve_task_owner_candidates_for_artifacts()` 会在
  `post_meeting.send_summary_card` 和 `post_meeting.save_pending_actions` 执行前运行。
- 解析来源为飞书通讯录：`我 / 本人 / 自己` 使用 `FeishuClient.get_current_user_info()`；
  具体姓名使用 `FeishuClient.search_users(..., identity="user")`。
- 只有唯一可信候选才写入 `owner_open_id`、`owner_user_id`、`owner_display_name` 和
  `owner_resolution_status=resolved`，并重建 `task_card_analysis` 与卡片 payload。
- 查不到、多候选不唯一、群体称呼、时间词或接口失败时，任务卡继续展示“待补充”，
  原始候选保存在 `owner_candidate`，不会把“星期四 / 周四 / 明天”等词展示成负责人。
- `cards/post_meeting.py::build_pending_task_button_value()` 会把已解析的
  `owner_open_id_override` 写入按钮 value，后续确认创建任务时可直接复用，减少二次搜索歧义。

### 3.5 负责人待补充问题定位与修复

真实发卡中出现“负责人全部待补充”后，定位结果如下：

- 不是通讯录权限的单一问题。`storage/workflow_events.jsonl` 中已有 `contact.search_user`
  成功记录，飞书接口 HTTP 200 / code 0，说明至少当前用户身份可以调用通讯录搜索。
- 直接运行 `scripts/post_meeting_live_test.py --send-card` 时，脚本历史上直接用
  `im.send_card` 发送 `artifacts.card_payloads`，没有经过 `post_meeting.send_summary_card`，
  因此会绕过 D4 发卡前负责人解析逻辑。
- 妙记中常见的 `**李健文**：周四前...`、`完成时间：李健文周四前...` 格式，旧抽取规则会误抽成
  `周四前` 或 `文周四前`，导致即使通讯录可用也无法解析成真实人员。

本轮修复：

- `scripts/post_meeting_live_test.py::resolve_live_test_task_owners()` 在真实发卡脚本中复用
  `resolve_task_owner_candidates_for_artifacts()`，确保确定性 live test 与 Agent 工具路径一致。
- `core/post_meeting.py::OWNER_PATTERNS` 支持加粗姓名冒号格式、姓名冒号格式和
  `完成时间：姓名周四前...` 格式，同时继续过滤 `周四前 / 星期四前` 等时间词。
- 真实联调报告新增 `d4_task_cards.owner_resolution_summary`，每条 Action Item 记录
  `owner_resolution_status`、`owner_resolution_source`、`owner_resolution_candidate_count`，
  便于区分“没抽到负责人”和“通讯录查不到/多候选/权限失败”。

### 3.6 任务卡发卡体验优化

为避免同一会议一次发送多张任务卡造成群内刷屏，本轮把真实发卡体验调整为：

- `scripts/post_meeting_live_test.py --send-card` 先只发送一张会后总结卡，并保存待确认任务 registry。
- 用户点击会后总结卡中的“查看任务卡”按钮后，`core/card_callback.py` 再按当前确认批次 / 妙记会话
  发送一张聚合待确认任务卡；不再为每条待确认任务循环发送单独卡片，也不在总结卡发出时立即发送任务卡。
- 聚合待确认任务卡中，每条任务仍保留负责人和截止时间输入框。
- 删除“修改信息 / 保存修改”按钮，用户补充字段后直接点击“确认创建”；不创建时点击“拒绝创建”。
- `--send-reaction-cards` 仍作为旧消息确认模式的显式兜底入口，不作为默认任务卡体验。

真实联调中曾出现聚合任务卡只显示标题和摘要的问题，原因是完整卡片被飞书拒绝后
`im.send_card` 回退到了最小 fallback 卡。飞书错误先后指向两个 schema 问题：

- `form` 元素不能使用 `body.elements`，必须直接使用 `elements`。
- `form.elements` 内不支持旧版 `tag: action`，按钮需要使用 schema 2.0 的
  `column_set` + `button.behaviors.callback` 结构。

当前 `build_pending_action_item_form_element()` 已统一为 `form.elements` +
`column_set` 结构，并补充测试确保聚合卡不会再生成非法的 `form.body` / `action` 结构。

### 3.7 固定任务卡字段渲染规则

为提升待确认任务卡可读性，本轮固定字段展示规则：

- 所有 `字段：值` 形式的任务卡明细，统一通过 `cards/post_meeting.py::render_label_value()` 渲染。
- 冒号前的字段名和冒号本身加粗，例如 `**负责人：** 叶抒锐`。
- 飞书富文本要求加粗语法前后留空格；不要写成 `**负责人：**叶抒锐`，否则真实卡片可能把
  `**` 当普通文本展示。
- 冒号后的业务值不加粗、不使用代码样式；任务 ID、负责人、截止时间、证据等都按普通文本展示。
- 该规则适用于聚合待确认任务卡、单条按钮任务卡、reaction 兜底任务卡和已创建任务提醒。
- 多字段明细必须通过 `cards/post_meeting.py::join_card_markdown_lines()` 使用 Markdown 硬换行紧凑连接，
  避免普通单换行在飞书客户端被折叠成空格，同时不能在负责人、截止时间、优先级、证据和处理状态之间出现多余空行。
- 任务标题、负责人、证据、Agent 建议等业务值必须通过 `cards/post_meeting.py::render_value_text()`
  清理妙记原文中的 Markdown 控制符；例如 `**李健文**：周四前...` 在卡片中展示为普通
  `李健文：周四前...`，不能让业务值自带加粗。
- `待确认明细`、`补充字段`、`修改字段` 等非 `字段：值` 标题不加粗，避免误导为字段标签。

对应测试已在 `tests/test_post_meeting_card_callback.py` 中增加断言，防止再次出现
`负责人：**张三**`、``任务 ID：`action_xxx` ``、`**字段：**值`、`标题**任务 ID`、
`**李健文**` 或 `**补充字段**` 这类旧格式。

### 3.8 聚合任务卡按钮状态更新

真实联调发现：同一会议的多个任务聚合到一张消息后，点击其中一条任务的按钮，
后端若仍用单条结果卡调用 `update_card_message()`，会把整张聚合消息替换成单条任务卡，
导致其它任务按钮全部消失。

本轮修复：

- `core/card_callback.py::apply_callback_card_update()` 在更新消息前，会根据
  pending registry 中绑定的 `message_id` 查找同一张聚合卡里的所有任务。
- 若真实回调里的 `message_id / open_message_id` 与发送接口返回的 ID 形态不一致，
  则按同一 `review_session_id` 兜底聚合；仍不够时再按 `minute_token + chat_id` 兜底。
- 如果同一消息绑定了多条任务，则调用 `build_aggregate_card_for_callback_update()` 重建整张聚合卡；
  已创建 / 已拒绝的任务展示处理状态，不再展示按钮，其它 pending 任务继续保留负责人/截止时间输入框和按钮。
- 单条任务卡、reaction 卡或只有一个任务绑定到当前消息时，继续沿用原来的单条结果卡更新逻辑。
- `tests/test_post_meeting_card_callback.py::test_aggregate_card_update_keeps_other_task_buttons`
  覆盖“点击第一条任务后第二条任务按钮仍保留”的回归场景。
- 回调日志会写入 `aggregate_card_update_selected` 或 `single_card_update_selected`，
  用于判断真实环境到底走了聚合卡重建还是单条卡回退。

真实联调继续发现：点击单个任务后，虽然其它任务不再消失，但被点击任务所在区域没有立即刷新，
按钮仍停留在客户端画面上。根因是仅依赖后端主动 `PATCH /im/v1/messages/{message_id}` 更新消息时，
飞书客户端可能不会立刻展示更新后的局部状态；而回调响应如果携带单条任务卡，又会触发整卡替换。

补充修复：

- `core/card_callback.py::apply_callback_card_update()` 返回实际重建后的整张聚合卡。
- `core/card_callback.py::CardCallbackResult.to_feishu_response()` 在 3 秒回调响应中携带这张聚合卡。
- 回调响应中的 `card.data` 必须是完整聚合任务卡，不是单条任务结果卡。
- 已处理任务在重建后的聚合卡中只展示处理状态和任务详情链接，不再展示确认 / 拒绝按钮。
- 其它 pending 任务继续保留输入框和确认 / 拒绝按钮。
- `tests/test_post_meeting_card_callback.py` 已断言回调响应的 `card.data` 等于重建后的聚合卡，
  避免后续再次退回单条任务卡全量替换。

真实联调还发现：点击按钮后重建聚合卡时，负责人和截止时间可能重新显示为抽取层原始值，
例如 `筛选组合 / 列表页 / 周四前`。根因是首次发卡使用完整 artifacts，可通过
`task_card_analysis` 执行“负责人必须通讯录可解析、截止时间必须标准日期”的展示限制；
但回调重建卡片时只从 pending registry 还原 ActionItem，拿不到完整 `task_card_analysis`，
于是卡片层回退展示了原始 `item.owner` / `item.due_date`。

补充修复：

- `cards/post_meeting.py::render_verified_owner_for_card()` 在没有完整 `task_card_analysis` 时，
  仍会检查 `owner_open_id / owner_user_id / owner_resolution_status`；未解析为真实用户则展示“待补充”。
- `cards/post_meeting.py::render_standard_due_date_for_card()` 在没有完整 `task_card_analysis` 时，
  只展示 `YYYY-MM-DD` 标准日期；`明天 / 周四前` 等相对时间统一展示“待补充”。
- `tests/test_post_meeting_card_callback.py::test_aggregate_card_update_keeps_other_task_buttons`
  覆盖回调重建聚合卡时不再泄漏原始负责人和相对截止时间。

任务卡排版补充：

- `cards/post_meeting.py::join_card_markdown_lines()` 已由空行分隔改为 Markdown 硬换行分隔。
- 聚合待确认任务卡、单条按钮卡和 reaction 兜底卡的字段之间不再插入空白行。
- `tests/test_post_meeting_card_callback.py` 已补充断言，防止 `任务 ID / 负责人 / 截止时间`
  等字段之间再次出现 `\n\n` 空行。

## 4. 涉及文件

| 文件 | 改动 |
|---|---|
| `AGENTS.md` | 固化“保存 docs/tasks 里程碑文件 + tasks.md 精简记录”的协作流程 |
| `core/post_meeting.py` | 新增 D4 任务卡分析包、按负责人任务卡分组、去重提示和 D4 指标 |
| `core/post_meeting_tools.py` | 发卡/保存待确认任务前解析负责人候选，唯一匹配真实飞书用户后再展示 |
| `cards/post_meeting.py` | 待确认任务卡展示 Agent 建议和缺失字段，固定任务字段“标签加粗、值普通”的渲染规则，并支持聚合卡中已处理任务只展示状态 |
| `core/card_callback.py` | 聚合卡按钮回调后重建整张聚合卡，避免单条结果卡替换整条消息 |
| `scripts/post_meeting_live_test.py` | 真实发卡脚本发卡前复用 D4 负责人解析，并在报告中输出解析摘要 |
| `tests/test_post_meeting_d4_task_cards.py` | 新增 D4 任务分析与卡片渲染测试 |
| `tests/test_post_meeting_card_callback.py` | 覆盖任务卡 schema 2.0 表单、按钮回调和字段渲染规则 |
| `docs/tasks/d4-minute-agent-task-card-plan.md` | 新增 D4 里程碑记录 |
| `tasks.md` | 增加 D4 里程碑入口与精简完成摘要 |

## 5. 验证结果

已通过：

```bash
python3 -m py_compile core/post_meeting.py cards/post_meeting.py tests/test_post_meeting_d4_task_cards.py
python3 -m py_compile core/post_meeting.py core/post_meeting_tools.py scripts/post_meeting_live_test.py tests/test_post_meeting_d4_task_cards.py
python3 -m py_compile core/card_callback.py tests/test_post_meeting_card_callback.py
python3 -m unittest tests.test_post_meeting_d4_task_cards
python3 -m unittest tests.test_post_meeting_d3_review_card tests.test_post_meeting_card_callback
python3 -m unittest tests.test_post_meeting_card_callback tests.test_risk_scan_card
```

## 6. 真实发卡测试

D4 真实发卡复用 M4 会后 Agent 化链路。测试前需确认：

- `config/settings.local.json` 中 `feishu.default_chat_id` 指向测试群。
- 当前用户已完成 OAuth 登录，并具备妙记读取、消息发送和任务相关权限。
- 妙记链接能由当前用户访问。
- 真实发卡只在测试群验证，不默认发送到生产群。

推荐命令：

```bash
python3 scripts/post_meeting_agent_live_test.py \
  --minute-token "https://bytedance.larkoffice.com/minutes/<minute_token>" \
  --llm-provider settings \
  --max-iterations 8
```

如果需要绕过旧的幂等记录，可先删除对应 `idempotency_keys` 记录，或使用新的妙记 / 新的测试窗口。

成功时应在测试群看到：

- 会后总结卡：包含“查看任务卡 / 执行风险巡检 / 查看完整报告”等入口。
- 点击“查看任务卡”后发送待确认任务卡：同一会议的所有待确认任务聚合在一条消息中；每条任务包含任务标题、负责人、截止时间、优先级、缺失字段、Agent 建议、来源证据和按钮。
- 按钮：`确认创建`、`拒绝创建`。负责人或截止时间可在输入框内补充后直接点击确认创建，不再提供单独的“修改信息”按钮。

终端或 `--show-full` 输出中应看到工具链调用：

```text
minutes.fetch_resource
post_meeting.build_artifacts
post_meeting.enrich_related_knowledge
post_meeting.send_summary_card
post_meeting.save_pending_actions
```

验收重点：

- 若负责人没有被解析为唯一可信的真实飞书用户，卡片显示“待补充”，不能显示随意猜出的姓名或时间词。
- 若负责人能被飞书通讯录唯一解析，卡片可展示真实姓名，按钮 value 中应包含 `owner_open_id_override`。
- 截止时间以 `YYYY-MM-DD` 展示，不使用“明天 / 周四前”等相对表述。
- 点击确认创建后仍必须经过 `AgentPolicy`，缺负责人、缺截止时间或无法解析负责人时应继续要求补充，不应直接创建任务。

## 7. D4 任务覆盖情况

| 编号 | 状态 | 说明 |
|---|---|---|
| D4-01 | 已完成 | `extract_action_items()` 从妙记文本中抽取行动项 |
| D4-02 | 已完成 | `task_card_analysis.owner_groups` 按负责人聚合任务 |
| D4-03 | 已完成 | `extract_due_date_candidate()` 识别截止时间文本 |
| D4-04 | 已完成 | `missing_fields` 标记负责人、截止时间、证据等缺失 |
| D4-05 | 已完成 | 待确认任务卡和单任务卡展示完整任务信息 |
| D4-06 | 已完成 | 每条任务保留妙记来源片段和 source 信息 |
| D4-06A | 已完成 | 发卡前通过飞书通讯录解析负责人候选；不唯一或不可解析则保持“待补充” |
| D4-07 | 已完成首版 | `infer_priority()` 基于紧急、高优、今天/明天等信号判断优先级 |
| D4-08 | 已完成首版 | `duplicate_hints` 提供轻量去重提示，不自动合并 |
| D4-09 | 已完成 | 确认、修改、拒绝、已创建等状态由回调链路维护 |
| D4-10 | 已完成 | 默认通过待确认卡展示计划，不直接写飞书任务 |
| D4-11 | 已具备 | `--allow-write` + 人工确认后可真实创建任务 |
| D4-12 | 已完成首版 | 新增 D4 脱敏单测样例，真实演示可复用 M4 live test |

## 8. 剩余风险

- 当前行动项抽取仍以规则为主，复杂口语、多负责人协作和隐含截止时间可能需要 LLM 辅助增强。
- 去重提示首版只比较同轮妙记任务标题，尚未跨 `task_mappings` 和项目记忆做历史相似任务提示。
- 真实飞书任务创建依赖卡片回调、用户 token、任务权限和测试群配置，需要真实环境继续灰度验证。
