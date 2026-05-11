# D3：会后总结卡优化详细设计方案

## 1. 任务定位

D3 面向 OpenClaw / 答辩演示中的会后复盘场景，目标不是新增一条会后工作流，
而是在现有 M4 `post_meeting_followup` 主链路上增强结构化复盘能力：

> 把“会议总结成一段话”升级为“结论、问题、任务、风险、争议、建议和证据可追踪的会议复盘卡”。

当前问题是：会后总结卡如果只包含摘要和行动项，会显得像普通纪要压缩结果，无法体现
MeetFlow 的垂直 Agent 价值。D3 的验收重点应放在“复盘结构化”和“可继续推进”上：

- 摘要要说明会议价值，而不只是复述会议内容。
- 结论、开放问题、行动项、风险和争议要分区呈现，便于会后追踪。
- 关键判断要尽量关联妙记片段或历史资料，避免无来源的总结。
- 后续建议要来自开放问题、风险和任务上下文，体现 Agent 的推进能力。
- 快捷按钮要把会后复盘自然连接到任务卡、风险巡检和完整报告。

当前 M4 已具备妙记读取、纪要清洗、决策/开放问题/行动项抽取、待确认任务卡、
人工确认创建任务、相关背景资料召回和真实发卡能力。D3 应复用这些能力，优先增强
`core/post_meeting.py` 的结构化产物、`cards/post_meeting.py` 的卡片布局，以及
`scripts/post_meeting_live_test.py` 的演示报告。

## 2. 当前代码基线

| 能力 | 当前实现 | D3 复用/增强方式 |
|---|---|---|
| 会后工作流 | `core/workflows.py::PostMeetingFollowupWorkflow` | 继续在 `prepare_context()` 生成确定性 artifacts |
| 结构化产物 | `core/post_meeting.py::PostMeetingArtifacts` | 增加 D3 复盘字段，不破坏旧字段 |
| 会议总结 | `core.models.MeetingSummary` | 保留 `decisions/open_questions/action_items/risks/evidence_refs`，新增 D3 子对象放在 artifacts/extra |
| 决策抽取 | `extract_decisions()`、`build_fallback_decisions()` | 强化“关键结论”质量和 evidence 展示 |
| 开放问题 | `extract_open_questions()` | 增强为“开放问题/待确认事项”分区 |
| 行动项 | `extract_action_items()`、`mark_action_item_confirmation_state()` | 增加按人/优先级/截止时间聚合视图 |
| 相关背景 | `enrich_post_meeting_related_resources()` | 作为 Evidence Pack / 历史依据补充来源 |
| 总结卡 | `cards/post_meeting.py::build_post_meeting_summary_card()` | 增加风险、争议、后续建议、Evidence Pack、完整报告入口 |
| 任务卡 | `build_pending_action_items_card()`、单任务确认卡 | 保持人工确认闭环，不在总结卡里直接创建任务 |
| 真实联调 | `scripts/post_meeting_live_test.py` | 增加 D3 字段统计、完整报告链接和演示样例 |

## 3. 目标卡片结构

D3 会后总结卡建议分为 8 个区域：

| 区域 | 数据来源 | 展示目标 |
|---|---|---|
| 会议复盘摘要 | `MeetingSummary` + cleaned transcript | 说明本次会议价值、范围和结论密度 |
| 关键结论 | `ExtractedDecision[]` | 展示已经达成一致的决策，带证据片段 |
| 开放问题 | `ExtractedOpenQuestion[]` | 展示仍需确认的问题和阻塞点 |
| 行动项概览 | `ActionItem[]` | 按负责人分组，显示数量、截止时间、置信度、待确认状态 |
| 风险提示 | 新增 `PostMeetingRisk[]` 或 `summary.risks` | 从妙记风险/阻塞/延期信号中提炼风险 |
| 争议点 / 分歧点 | 新增 `PostMeetingDisagreement[]` | 抽取“不同观点、未达成一致、方案 A/B”等信号 |
| 后续建议 | 新增 `FollowUpSuggestion[]` | Agent/规则基于问题、风险、任务给出下一步推进建议 |
| Evidence Pack | 决策/问题/任务/风险 evidence_refs + related hits | 展示妙记片段、来源链接、相关背景资料 |

### 3.1 内容模块对齐

本节对应 OpenClaw 智能化演示增强方案中的 D3 内容要求，作为后续实现和验收的固定口径。

| 内容模块 | 说明 | 首版落点 |
|---|---|---|
| 会议摘要 | 概括本次会议核心内容，并说明会议价值 | `build_post_meeting_review_summary()` 与卡片顶部摘要 |
| 关键结论 | 已达成一致的决策 | `ExtractedDecision[]` + Evidence Pack |
| 开放问题 | 尚未解决的问题 | `ExtractedOpenQuestion[]` 与待跟进区块 |
| 行动项概览 | 按人、按优先级、按截止时间整理 | `group_action_items_by_owner()` 与待确认任务状态 |
| 风险提示 | 本次会议中暴露的风险 | `PostMeetingRisk[]` 与卡片风险区块 |
| 争议点 / 分歧点 | 如果妙记中存在不同观点，可提炼出来 | `PostMeetingDisagreement[]`，无证据时不展示 |
| 后续建议 | Agent 给出的推进建议 | `FollowUpSuggestion[]`，由结构化事实触发 |
| Evidence Pack | 关键结论对应的妙记片段或历史依据 | `build_post_meeting_evidence_pack()` |
| 快捷按钮 | 查看任务卡、执行风险巡检、查看完整报告 | `view_pending_tasks`、`start_risk_scan`、`view_post_meeting_report` |

快捷按钮建议：

| 按钮 | action | 说明 |
|---|---|---|
| 查看任务卡 | `view_pending_tasks` | 点击后在当前会话发送对应的聚合待确认任务卡 |
| 执行风险巡检 | `start_risk_scan` | 复用 M5 风险巡检入口 |
| 查看完整报告 | `view_post_meeting_report` | 打开 Markdown/飞书文档报告链接，P1 |
| 发送给我 | `send_summary_to_me` | 保留现有私发能力 |

## 4. 数据模型设计

首版建议不直接修改 `MeetingSummary`，避免影响 M4/M5 既有测试；在
`core/post_meeting.py` 中新增 D3 专用 dataclass，并挂到 `PostMeetingArtifacts.extra`
或新增字段。

建议新增：

```python
@dataclass(slots=True)
class PostMeetingRisk(BaseModel):
    risk_id: str
    content: str
    severity: str = "medium"
    reason: str = ""
    suggestion: str = ""
    confidence: float = 0.0
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_line: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PostMeetingDisagreement(BaseModel):
    disagreement_id: str
    topic: str
    viewpoints: list[str] = field(default_factory=list)
    status: str = "unresolved"
    confidence: float = 0.0
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    source_line: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FollowUpSuggestion(BaseModel):
    suggestion_id: str
    content: str
    priority: str = "medium"
    reason: str = ""
    related_item_ids: list[str] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
```

`PostMeetingArtifacts` 建议新增字段：

```python
risks: list[PostMeetingRisk] = field(default_factory=list)
disagreements: list[PostMeetingDisagreement] = field(default_factory=list)
follow_up_suggestions: list[FollowUpSuggestion] = field(default_factory=list)
evidence_pack: dict[str, Any] = field(default_factory=dict)
```

兼容策略：

- `meeting_summary.risks` 保留为字符串列表，供旧代码继续使用。
- 新版 `artifacts.risks` 保存结构化风险。
- 卡片优先读取新版字段，字段为空时降级显示旧字段或“暂无”。
- 写任务逻辑不读取新版建议字段，避免建议被误创建为任务。

## 5. 核心函数拆分

建议在 `core/post_meeting.py` 新增或增强以下函数：

| 函数 | 职责 |
|---|---|
| `build_post_meeting_review_summary(artifacts)` | 生成更像复盘的摘要，突出会议价值和产出 |
| `extract_post_meeting_risks(cleaned_transcript, meeting_id, source_url)` | 从“风险/阻塞/延期/不稳定/不足”等信号抽取风险 |
| `extract_disagreements(cleaned_transcript, meeting_id, source_url)` | 从“争议/分歧/不同意见/未达成一致/A 或 B”抽取争议点 |
| `group_action_items_by_owner(action_items)` | 生成按负责人分组的行动项概览 |
| `generate_follow_up_suggestions(artifacts)` | 基于开放问题、风险、低置信任务生成后续建议 |
| `build_post_meeting_evidence_pack(artifacts)` | 汇总决策、问题、任务、风险、相关知识的证据来源 |
| `merge_d3_review_fields(artifacts)` | 把 D3 字段合并进 artifacts 和 card payload |

建议执行顺序：

```text
build_post_meeting_artifacts_from_input()
  -> clean_meeting_transcript()
  -> extract_decisions()
  -> extract_open_questions()
  -> extract_action_items()
  -> extract_post_meeting_risks()
  -> extract_disagreements()
  -> generate_follow_up_suggestions()
  -> build_post_meeting_evidence_pack()
  -> build_post_meeting_summary_card()
  -> build_pending_action_items_card()
```

## 6. 抽取规则设计

### 6.1 风险提示

新增风险信号词：

```python
"risk": (
    "风险", "阻塞", "延期", "不稳定", "不足", "来不及", "依赖",
    "卡住", "失败", "回滚", "兜底", "需要关注", "可能影响"
)
```

抽取策略：

- 优先读取标题包含“风险 / 阻塞 / 问题 / 待关注”的章节。
- 其次读取带风险信号词的 signal lines。
- 风险必须带 `evidence_ref`。
- severity 规则首版可确定性判断：
  - `high`：包含“阻塞、无法、失败、延期、发布风险、演示失败”
  - `medium`：包含“不稳定、不足、依赖、待确认”
  - `low`：一般提醒或轻微不确定

### 6.2 争议点 / 分歧点

新增争议信号词：

```python
"disagreement": (
    "争议", "分歧", "不同意见", "未达成一致", "暂未统一",
    "方案A", "方案B", "两种方案", "倾向于", "但是"
)
```

首版不追求复杂辩论图谱，只提炼：

- 争议主题
- 观点片段列表
- 当前状态：`unresolved` / `partially_resolved` / `resolved`
- evidence_refs

### 6.3 后续建议

建议不让 LLM 直接自由发挥，而是基于结构化事实生成：

| 触发条件 | 建议模板 |
|---|---|
| 有开放问题 | “下次会议前明确 X 的判断标准/负责人” |
| 有 high 风险 | “优先处理 X，并准备兜底方案” |
| 有待确认任务 | “会后先确认负责人和截止时间，再创建任务” |
| 行动项多人分散 | “按负责人同步任务清单，避免漏跟进” |
| Evidence Pack 过少 | “补充妙记片段或历史资料，避免复盘结论无证据” |

后续如果接入真实 LLM，可把这些结构化字段作为上下文，让豆包润色建议，但卡片渲染仍只显示带来源或明确规则原因的建议。

## 7. 卡片布局设计

`cards/post_meeting.py::build_post_meeting_summary_card()` 建议从当前线性区域升级为固定层级：

```text
标题：MeetFlow 会后复盘：{topic}

1. 会议复盘摘要
2. 关键结论
3. 开放问题
4. 行动项概览
   - 按人分组
   - 待确认任务单独标记
5. 风险提示
6. 争议点 / 分歧点
7. 后续建议
8. Evidence Pack / 原始资料
9. 快捷按钮
```

卡片渲染细节：

- 每个区块最多展示 3 条，完整内容进入 Markdown 报告。
- 行动项按负责人分组时，每人最多 2 条，避免卡片过长。
- 风险高亮 severity：`high` 用红色标题或 `高风险` 文案，`medium` 用橙色。
- Evidence Pack 只展示来源标题、片段摘要、链接或 `ref_id`。
- 如果某区块没有内容，显示“暂无明确 xxx”，避免用户误解为漏跑。

## 8. 报告与可观测性

`scripts/post_meeting_live_test.py --report-dir` 当前已有 Markdown 报告。D3 建议新增：

```text
## 5.1 D3 结构化复盘字段
- risks_count
- disagreements_count
- follow_up_suggestions_count
- evidence_pack_reason

## 5.2 Evidence Pack
完整 JSON：决策/问题/任务/风险/相关知识来源

## 6. 卡片 Payload 草案
summary_card / pending_card / optional report link
```

控制台 compact summary 增加：

```json
{
  "risk_count": 2,
  "disagreement_count": 1,
  "suggestion_count": 3,
  "evidence_ref_count": 8
}
```

## 9. 分阶段落地计划

### Phase 1：结构化字段与确定性抽取

优先完成 D3-01、D3-02、D3-03、D3-05。

- 新增 `PostMeetingRisk`、`PostMeetingDisagreement`、`FollowUpSuggestion`。
- 实现 `extract_post_meeting_risks()`。
- 实现 `extract_disagreements()`。
- 强化 `build_post_meeting_artifacts_from_input()` 的 D3 字段填充。
- 保留旧 `MeetingSummary` 字段兼容。

验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/post_meeting.py cards/post_meeting.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_rag_query tests.test_post_meeting_card_callback
```

### Phase 2：行动项概览和后续建议

优先完成 D3-04、D3-06。

- 实现 `group_action_items_by_owner()`。
- 实现 `generate_follow_up_suggestions()`。
- 卡片中新增“行动项概览”和“后续建议”区域。
- 待确认任务继续通过待确认任务卡处理，不在总结卡里执行写操作。
- 会后总结卡默认先发送；待确认任务卡不再随总结卡自动发送，用户点击“查看任务卡”后由
  `core/card_callback.py::send_pending_tasks_card_from_summary_callback()` 从 pending registry 恢复同一确认批次 /
  同一妙记会话的任务，并通过 `im.send_card` 受 AgentPolicy 检查后发送聚合任务卡。

验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --read-only \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

### Phase 3：Evidence Pack 与完整报告入口

优先完成 D3-07、D3-08。

- 实现 `build_post_meeting_evidence_pack()`。
- 报告中记录 evidence pack 完整 JSON。
- 卡片中展示最多 5 条关键证据来源。
- 如果能生成稳定报告 URL，可加入“查看完整报告”按钮；本地报告路径则只在报告和控制台展示。

验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --read-only \
  --related-top-n 5 \
  --report-dir storage/reports/m4/d3
```

### Phase 4：真实发卡与演示样例

优先完成 D3-09、D3-10。

- 准备一份真实或脱敏妙记，包含：
  - 明确结论
  - 开放问题
  - 多负责人行动项
  - 至少一条风险
  - 至少一条争议/分歧
- 使用 `--send-card --allow-write` 发送真实群聊卡片。
- 保存截图、报告路径和复现命令。

真实发送命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --identity user \
  --allow-write \
  --send-card \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

## 10. 测试矩阵

| 层级 | 用例/命令 | 覆盖内容 |
|---|---|---|
| 单元测试 | `tests/test_post_meeting_d3_review_card.py` | 风险、争议、建议、行动项分组 |
| 回归测试 | `tests.test_post_meeting_card_callback` | 待确认任务卡和按钮状态机不回归 |
| RAG 测试 | `tests.test_post_meeting_rag_query` | 会后相关背景 query 不被噪声带偏 |
| Demo | `scripts/post_meeting_demo.py` | 本地脱敏样例卡片 JSON |
| 只读真实联调 | `scripts/post_meeting_live_test.py --read-only --report-dir ...` | 真实妙记读取和 D3 报告字段 |
| 真实发卡 | `scripts/post_meeting_live_test.py --allow-write --send-card` | 飞书群聊会后复盘卡 |
| 闭环验证 | M4 发卡 -> 确认任务 -> M5 风险巡检 | D3 与 D4/D5 不冲突 |

## 11. 风险与控制

| 风险 | 控制方式 |
|---|---|
| 把风险/建议误当任务创建 | 总结卡只展示；任务创建仍只走待确认卡和 `AgentPolicy` |
| 争议点抽取误判 | 首版只展示带明显争议信号和 evidence 的内容，低置信显示“可能存在” |
| 卡片过长 | 每区最多 3 条，完整内容进入 Markdown 报告 |
| LLM 编造复盘结论 | 首版优先确定性规则；真实 LLM 只能润色，不新增无 evidence 的事实 |
| 旧 M4 流程回归 | 保留 `MeetingSummary` 旧字段；新增字段为空时卡片降级显示 |
| 真实妙记权限失败 | 先跑 `--read-only`，确认 OAuth/scope 后再 `--allow-write` |

## 12. 验收标准映射

| 编号 | 任务 | 优先级 | 设计落点 | 验收标准 |
|---|---|---|---|---|
| D3-01 | 优化摘要质量 | P0 | `build_post_meeting_review_summary()` | 摘要说明会议价值和产出，不只是复述标题 |
| D3-02 | 强化关键结论提取 | P0 | `extract_decisions()` 强化 + Evidence Pack | 结论清晰可读，能说明会议达成了什么 |
| D3-03 | 强化开放问题提取 | P0 | `extract_open_questions()` 强化 | 问题可继续跟进，能说明还没有解决什么 |
| D3-04 | 按人整理行动项 | P0 | `group_action_items_by_owner()` | 卡片能看到谁负责什么，优先级和截止时间可读 |
| D3-05 | 增加风险提示模块 | P0 | `extract_post_meeting_risks()` | 会后卡直接展示风险，不需要另找 |
| D3-06 | 增加后续建议模块 | P0 | `generate_follow_up_suggestions()` | 建议来自风险/问题/任务上下文，体现 Agent 推进能力 |
| D3-07 | 增加证据来源模块 | P1 | `build_post_meeting_evidence_pack()` | 关键内容有关联妙记片段或资料来源 |
| D3-08 | 增加完整报告入口 | P1 | report path / report URL | 卡片或报告中可查看完整复盘 |
| D3-09 | 优化卡片视觉层级 | P0 | `cards/post_meeting.py` 布局升级 | 摘要、任务、风险、证据分区明显，一眼可读 |
| D3-10 | 准备会后总结卡演示样例 | P0 | demo fixture + live report | 有真实或脱敏妙记稳定演示，可重复生成卡片和报告 |

## 13. 答辩口径

可以这样描述 D3：

> 会后卡不是把妙记压缩成一段摘要，而是把会议自动结构化成“结论、开放问题、行动项、风险、争议和后续建议”。每个关键判断都保留妙记片段或相关资料作为 Evidence Pack，任务创建继续走人工确认和 Policy 审核，保证复盘可信、可追踪、可落地。

演示重点应明确突出：

> 系统不是把会议“总结成一段话”，而是把会议结构化为结论、问题、任务、风险和建议。

建议演示时按以下顺序讲：

1. 先展示妙记或脱敏纪要中真实存在的结论、问题、任务和风险信号。
2. 再展示会后复盘卡如何分区呈现，而不是生成一段泛化摘要。
3. 展示行动项按负责人聚合，待确认任务仍需要用户确认，不会绕过 `AgentPolicy`。
4. 展示 Evidence Pack，让评委看到关键结论和风险有来源。
5. 最后点击或说明“查看任务卡 / 执行风险巡检 / 查看完整报告”，把 D3 和 D4、D5 串成闭环。

## 14. 演示样例要求

D3-10 的演示样例建议放在 `scripts/post_meeting_demo.py` 或独立 fixture 中，样例内容必须脱敏且稳定。
样例妙记至少包含：

- 会议摘要可以提炼出明确业务价值，例如“确认上线范围、暴露演示风险、形成负责人分工”。
- 2 条以上关键结论，至少 1 条带明确证据片段。
- 2 条以上开放问题，能在后续会议或任务中继续跟进。
- 3 条以上行动项，覆盖至少 2 个负责人，并包含优先级或截止时间。
- 1 条以上风险提示，最好包含“阻塞、延期、依赖、兜底”等明显信号。
- 1 条可选争议点或分歧点；如果样例没有分歧，应在卡片中显示“暂无明确分歧”。
- 2 条以上后续建议，且建议能说明触发原因。

演示命令建议：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --read-only \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

真实发卡仍必须显式加 `--allow-write --send-card`，并使用测试群或配置中的测试接收方。

## 15. 本轮补充记录

2026-05-10 根据 D3 会后总结卡优化任务方案补充本文档：

- 补充当前问题与 D3 目标：会后卡要升级为结构化、可追踪、带证据、带后续建议的复盘卡。
- 补充内容模块对齐表，覆盖会议摘要、关键结论、开放问题、行动项概览、风险提示、争议点、后续建议、Evidence Pack 和快捷按钮。
- 扩展 D3-01 到 D3-10 的任务清单，明确优先级、设计落点和验收标准。
- 补充答辩演示重点和 D3-10 演示样例要求。
- 本次为文档补充，未修改业务运行代码；验证方式为 Markdown 内容检查。

## 16. 2026-05-10 首轮代码接入记录

本轮按本文档完成 D3 会后总结卡优化的首轮代码接入，仍然复用 M4
`post_meeting_followup` 主链路，不新增绕过 `ToolRegistry` 或 `AgentPolicy` 的写操作。

### 16.1 修改文件

- `core/post_meeting.py`
- `cards/post_meeting.py`
- `core/card_actions.py`
- `core/__init__.py`
- `scripts/post_meeting_demo.py`
- `scripts/post_meeting_live_test.py`
- `tests/test_post_meeting_d3_review_card.py`

### 16.2 核心改动

- 新增 `PostMeetingRisk`、`PostMeetingDisagreement`、`FollowUpSuggestion`，
  并扩展 `PostMeetingArtifacts`，保存结构化风险、分歧、后续建议和 Evidence Pack。
- 新增 `extract_post_meeting_risks()`、`extract_disagreements()`、
  `group_action_items_by_owner()`、`generate_follow_up_suggestions()`、
  `build_post_meeting_evidence_pack()` 和 `merge_d3_review_fields()`。
- `build_post_meeting_artifacts_from_input()` 在原有决策、开放问题、行动项基础上补齐
  D3 复盘字段，并保留 `meeting_summary.risks` 兼容旧逻辑。
- `build_post_meeting_summary_card()` 升级为会后复盘卡，展示会议复盘摘要、关键结论、
  开放问题、按人行动项概览、风险提示、争议点、后续建议、Evidence Pack 和快捷入口。
- `CardActionRouter` 增加 `view_pending_tasks`、`start_risk_scan`、
  `view_post_meeting_report` 三个受控快捷动作，其中风险巡检只转换为受控
  `AgentInput`，不直接执行写操作。
- `scripts/post_meeting_live_test.py` 的只读 JSON、紧凑控制台摘要和 Markdown 报告
  增加 D3 指标、风险/分歧/建议和 Evidence Pack。
- `scripts/post_meeting_demo.py` 增加 `d3_review` 脱敏样例，可稳定演示“结论、问题、
  任务、风险、争议、建议和证据”的结构化复盘。
- 顺手修复按人分组依赖的负责人抽取边界，避免“李四周五前 / 王五下周三前”这类
  妙记句式把日期并进负责人姓名。

### 16.3 验证命令与结果

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile \
  core/post_meeting.py cards/post_meeting.py core/card_actions.py core/__init__.py \
  scripts/post_meeting_demo.py scripts/post_meeting_live_test.py \
  tests/test_post_meeting_d3_review_card.py

/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest \
  tests.test_post_meeting_d3_review_card \
  tests.test_post_meeting_rag_query \
  tests.test_card_actions \
  tests.test_post_meeting_card_callback

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_demo.py --sample d3_review
```

验证结果：

- `py_compile` 通过。
- 相关单测 34 条通过。
- 本地 D3 demo 通过，输出包含 `review_summary`、`risks`、`disagreements`、
  `follow_up_suggestions`、`evidence_pack` 和 `action_item_owner_groups`。

### 16.4 飞书真实联调命令

只读验证，不执行写操作：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --identity user \
  --read-only \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

带相关背景资料召回的只读验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --identity user \
  --read-only \
  --related-top-n 5 \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

真实测试群发卡，必须确认 `config/settings.local.json` 中测试群 `default_chat_id`
或命令行 `--chat-id` 指向测试群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --identity user \
  --allow-write \
  --send-card \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

如需指定测试群：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/post_meeting_live_test.py \
  --minute "你的飞书妙记URL或minute token" \
  --identity user \
  --allow-write \
  --send-card \
  --chat-id "你的测试群chat_id" \
  --receive-id-type chat_id \
  --show-card-json \
  --report-dir storage/reports/m4/d3
```

真实写操作仍由 `AgentPolicy` 审核；`--send-card` 只先发送 D3 复盘卡并保存待确认任务上下文。
用户点击“查看任务卡”后，才会在当前会话发送 D4 聚合待确认任务卡；任务创建仍需在待确认任务卡中由用户确认。

### 16.5 当前风险

- “查看完整报告”在本地报告路径场景下只能在报告和控制台中稳定追踪；如果要让飞书卡片按钮
  直接打开完整报告，需要后续把 Markdown 报告同步生成飞书云文档或可访问 URL。
- 风险和分歧抽取首版采用确定性关键词规则，适合稳定演示和可审计输出；后续可在 Evidence Pack
  约束下接入真实 LLM 润色，但不能让 LLM 新增无证据事实。
