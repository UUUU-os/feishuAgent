# D2：会前卡片智能准备增强具体改造方案

本文档承接 `docs/tasks/openclaw-demo-enhancement.md` 中的 D2 任务，并结合当前代码实现，给出一份可直接进入开发的改造方案。

目标不是重做 M3，而是在现有 `pre_meeting_brief` 主链路上，把会前卡片从“背景提醒卡”增强为“智能准备卡”：

```text
飞书日历会议
  -> 主题识别与 query 增强
  -> 历史会议 / 历史行动项 / 历史风险 / 轻量 RAG 证据汇聚
  -> MeetingBrief 结构化准备报告
  -> 会前智能准备卡
  -> Console / CLI / OpenClaw / 飞书群可复现演示
```

## 1. 当前代码基线

当前 M3 已有较完整的会前链路，D2 应优先复用，不要另起一条平行工作流。

| 能力 | 当前实现 | D2 复用方式 |
|---|---|---|
| 会前工作流入口 | `core/workflows.py::PreMeetingBriefWorkflow` | 继续在 `prepare_context()` 阶段生成确定性 artifacts |
| 会前业务对象 | `core/pre_meeting.py::PreMeetingBriefInput`、`RetrievalQuery`、`MeetingBrief`、`PreMeetingCardPayload` | 扩展 `MeetingBrief` 字段或新增子对象，不破坏旧字段 |
| 主题识别 | `identify_meeting_topic()` | 用于历史会议、行动项、风险和知识检索的统一 query 信号 |
| 资源召回 | `recall_related_resources()`、`RetrievedResource`、`RetrievalResult` | 继续承接 payload、附件、项目记忆中的资源级候选 |
| 轻量 RAG | `core/knowledge.py::KnowledgeIndexStore`、`knowledge.search`、`knowledge.fetch_chunk` | 作为 Evidence Pack 的 chunk 级证据来源 |
| 真实 LLM | `core.llm.DoubaoArkProvider`、`config/settings.local.json` | 用项目本地 settings 中配置的豆包/火山方舟在证据基础上生成背景摘要、建议议题和 checklist |
| 会前卡片模板 | `cards/pre_meeting.py::build_pre_meeting_card()` | 增加分区和按钮，不改发送工具协议 |
| 历史行动项 | `core/storage.py::task_mappings`、`find_task_mappings_by_meeting()` | 新增按项目/主题/时间查询接口后用于遗留行动项 |
| 历史风险 | `core/risk_scan.py::RiskRuleResult`、`risk_notifications` | 新增风险历史读取/归档入口，用于会前持续风险 |
| 真实联调 | `scripts/pre_meeting_live_test.py`、`scripts/card_send_live.py m3`、Console M3 页面 | 增加 D2 demo fixture 和报告字段 |

## 2. 改造原则

1. 继续遵守主链路：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> PreMeetingBriefWorkflow
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

2. 历史数据读取全部是只读能力。会前卡片发送仍必须经过 `im.send_card` 和 `AgentPolicy`。
3. LLM 只负责在受控证据基础上组织表达，不允许凭空生成历史结论、行动项、风险或来源。
4. Evidence Pack 是 D2 的核心交付：每个关键结论要么有 `evidence_refs`，要么明确标注“证据不足”。
5. D2 首版优先服务演示闭环：可靠、可解释、可回放，暂不追求全量企业知识库。

## 2.1 豆包接入后的新版智能化边界

项目已接入豆包/火山方舟 OpenAI-compatible provider：

- Provider 类：`core.llm.DoubaoArkProvider`
- 支持 provider 名：`doubao-ark`、`doubao`、`volcengine-ark`、`volcengine`、`ark`
- 默认 API Base：`https://ark.cn-beijing.volces.com/api/v3`
- `model` 可填写火山方舟控制台的 `ep-...` 推理接入点 ID
- Console M3 页面已允许选择 `doubao`

因此 D2 新版方案中，RAG 和大模型的职责应明确分开：

| 层次 | 是否依赖豆包 | 职责 |
|---|---|---|
| 本地历史汇聚 | 否 | 从 `workflow_results`、`task_mappings`、`risk_notifications`、项目记忆中取历史事实 |
| RAG 检索 | 不直接依赖聊天大模型 | 通过 BM25/RRF、ChromaDB、`knowledge.search`、`knowledge.fetch_chunk` 找证据 |
| D2 智能生成 | 是，建议用豆包 | 基于 Evidence Pack 生成背景摘要、建议议题、checklist 和低置信提示 |
| 飞书写入 | 否，由 policy 控制 | 只在 `allow_write` 后通过 `im.send_card` 发送卡片 |

新版目标不是让豆包“自己查资料”，而是让豆包在 MeetFlow 已经检索出的证据包内完成整理和表达：

```text
确定性代码构造 RetrievalQuery / Evidence Pack
  -> Agent Loop 调用 knowledge_search / knowledge_fetch_chunk
  -> 豆包基于工具结果生成 MeetingBrief 草案
  -> Validator 检查 evidence / uncertainty / card length
  -> cards/pre_meeting.py 渲染稳定卡片
```

配置建议：

```json
"llm": {
  "provider": "doubao-ark",
  "model": "ep-替换为你的推理接入点ID",
  "api_base": "https://ark.cn-beijing.volces.com/api/v3",
  "api_key": "替换为你的火山方舟 API Key",
  "temperature": 0.2,
  "max_tokens": 4000,
  "reasoning_effort": ""
}
```

真实 key 只写入当前项目用户自己的 `config/settings.local.json`，禁止写入示例配置、README、任务文档和提交记录。

## 3. 目标产物

### 3.1 新版会前卡片内容

| 模块 | 数据来源 | 目标展示 |
|---|---|---|
| 会议基本信息 | 飞书日历 event payload | 标题、时间、组织者、参会人、会议来源 |
| 会议背景摘要 | 历史会议 + RAG Evidence Pack + 项目记忆 | 2-3 句说明本次会为什么开、和历史上下文的关系 |
| 上次会议结论 | 历史 M4 `MeetingSummary.decisions`、历史妙记 chunk | 关键决策，带来源 |
| 遗留行动项 | `task_mappings` + 飞书任务状态 + M4 ActionItem | 未完成任务、负责人、截止时间、来源会议 |
| 历史风险 | M5 风险扫描结果、`risk_notifications`、任务映射证据 | 持续风险、风险原因、建议动作 |
| 本次建议议题 | 基于背景、开放问题、遗留行动项、风险生成 | 建议本次优先讨论什么 |
| 会前 Checklist | 基于待读资料、任务、风险生成 | 谁需要准备什么材料、要确认什么 |
| Evidence Pack | `knowledge.search`、历史会议、任务映射、风险记录 | 展示来源类型、标题、snippet、链接或 ref_id |
| 快捷操作按钮 | 飞书卡片 action value | 刷新背景、查看历史、生成复盘草案、发给我 |

### 3.2 新增结构建议

在 `core/pre_meeting.py` 中新增轻量业务对象，先不引入新依赖：

```python
@dataclass(slots=True)
class PreMeetingEvidencePack(BaseModel):
    """会前准备报告使用的压缩证据集合。"""

    historical_meetings: list[MeetingBriefItem] = field(default_factory=list)
    open_action_items: list[MeetingBriefItem] = field(default_factory=list)
    historical_risks: list[MeetingBriefItem] = field(default_factory=list)
    knowledge_hits: list[MeetingBriefItem] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    omitted_count: int = 0
    confidence: float = 0.0
    reason: str = ""
```

扩展 `MeetingBrief`：

```python
meeting_basic_info: dict[str, Any] = field(default_factory=dict)
historical_meetings: list[MeetingBriefItem] = field(default_factory=list)
open_action_items: list[MeetingBriefItem] = field(default_factory=list)
suggested_agenda: list[MeetingBriefItem] = field(default_factory=list)
pre_meeting_checklist: list[MeetingBriefItem] = field(default_factory=list)
evidence_pack: dict[str, Any] = field(default_factory=dict)
```

兼容策略：旧字段 `last_decisions/current_questions/must_read_resources/risks/possible_related_resources` 继续保留；新版字段用于卡片增强和报告展示。

## 4. 模块级改造方案

### 4.1 `core/pre_meeting.py`

新增确定性函数：

| 函数 | 职责 |
|---|---|
| `build_meeting_basic_info(workflow_input)` | 从日历 payload 汇总标题、时间、组织者、参会人、来源 |
| `build_pre_meeting_evidence_pack(workflow_input, retrieval_query, storage, knowledge_store)` | 汇聚历史会议、行动项、风险和 RAG hits |
| `retrieve_historical_meetings(...)` | 从 `workflow_results`、项目记忆、历史妙记资源中找同项目/同主题会议 |
| `retrieve_open_action_items(...)` | 从 `task_mappings` 和可选 `tasks.list_my_tasks` 结果中提取未完成行动项 |
| `retrieve_historical_risks(...)` | 从 `risk_notifications`、M5 结果或 task mapping evidence 中提取持续风险 |
| `generate_suggested_agenda(brief, evidence_pack)` | 基于开放问题、遗留行动项和风险生成建议议题 |
| `generate_pre_meeting_checklist(brief, evidence_pack)` | 生成会前材料、负责人、风险确认 checklist |
| `merge_evidence_pack_into_brief(brief, evidence_pack)` | 把 D2 证据汇入 `MeetingBrief` |

`build_pre_meeting_brief_artifacts()` 的新顺序建议：

```text
1. hydrate_pre_meeting_brief_input()
2. identify_meeting_topic()
3. build_retrieval_query()
4. recall_related_resources()
5. build_pre_meeting_evidence_pack()
6. build_initial_meeting_brief()
7. merge_evidence_pack_into_brief()
8. render_pre_meeting_card_payload()
```

注意：`knowledge.search` 仍由 Agent Loop 主动调用；确定性阶段只做本地历史汇聚和 payload 中已知资源整理。真实 chunk 级 evidence 可通过 Agent 工具结果进入最终回答与报告。

### 4.2 `core/storage.py`

当前已有按会议读取任务映射的接口，但 D2 需要按项目、主题和最近时间查询历史。

建议新增只读接口：

| 接口 | 说明 |
|---|---|
| `find_recent_workflow_results(workflow_name, project_id="", meeting_id="", limit=20)` | 读取历史 M3/M4/M5 artifacts |
| `find_task_mappings(project_id="", meeting_id="", title_query="", statuses=None, limit=20)` | 查询历史行动项，支持排除完成状态 |
| `find_recent_risk_notifications(project_id="", task_ids=None, statuses=None, limit=20)` | 查询最近风险提醒和降噪记录 |
| `load_project_memory(project_id)` | 已有，继续用于项目记忆 |

如果当前表没有 `project_id`，首版可以从 `payload_json.context.project_id` 或 task mapping evidence 中解析；后续再通过 migration 增补显式列。

### 4.3 `core/knowledge.py`

现有 `KnowledgeIndexStore.search_chunks()` 已具备 BM25/RRF、metadata filter、token budget 和稳定 `kref_` 引用。D2 只需要明确调用策略：

- 会前默认 query：`RetrievalQuery.search_queries` 中置信最高的 1-3 条。
- 硬过滤优先级：`filter_project_id` > `filter_meeting_id` > 本次补充资源 `document_id/source_url`。
- Evidence Pack 预算：卡片内 `top_n=5`、`evidence_token_budget=500`；报告内可保留更多调试字段。
- 低置信结果：不进入“上次结论/历史风险”的确定性区块，只进入“可能相关资料”。

### 4.4 `cards/pre_meeting.py`

建议把当前分区升级为以下顺序：

1. 顶部概览：主题、时间、参会人、状态、置信度。
2. 背景摘要：本次会议背景，突出“基于历史会议和项目记忆”。
3. 上次结论：最多 3 条。
4. 遗留行动项：最多 4 条，展示负责人、截止时间、状态。
5. 历史风险：最多 3 条，展示严重度、原因、建议。
6. 本次建议议题：最多 3 条。
7. 会前 Checklist：最多 5 条。
8. Evidence Pack：最多 5 条，显示来源类型、标题或 `ref_id`、链接。
9. 快捷按钮：刷新背景、查看历史、生成复盘草案、发给我。

按钮建议：

| 按钮 | action | 首版行为 |
|---|---|---|
| 刷新背景 | `refresh_pre_meeting_brief` | 保留现有能力 |
| 查看历史 | `view_pre_meeting_history` | P1，可先 toast 或回传历史摘要 |
| 生成复盘草案 | `start_post_meeting_followup` | P1，跳转/触发 M4 草案入口 |
| 发给我 | `send_summary_to_me` | 保留现有能力 |

### 4.5 `core/workflows.py`

`PreMeetingBriefWorkflow.build_workflow_goal()` 需要补充 D2 约束：

- 必须优先使用历史会议、任务、风险和 RAG evidence。
- 建议议题和 checklist 必须能解释依据。
- 没有证据时使用“建议确认/可能相关”，不能输出确定性说法。
- 输出中要体现“智能准备报告”，而不是普通会议提醒。

`WorkflowSpec.allowed_tools` 首版可继续使用现有列表：

```text
calendar.list_events
knowledge.search
knowledge.fetch_chunk
docs.fetch_resource
minutes.fetch_resource
tasks.list_my_tasks
im.send_card
```

如果新增历史只读工具，应命名为 `memory.search_meetings`、`memory.list_open_actions`、`risk.list_recent`，LLM 可见名对应 `memory_search_meetings` 等，保持 OpenAI/DeepSeek 工具名兼容。

### 4.6 `scripts/` 与 Console

建议新增或扩展：

| 文件 | 改造 |
|---|---|
| `scripts/pre_meeting_card_demo.py` | 构造 D2 完整样例，输出增强卡片 JSON |
| `scripts/pre_meeting_summary_demo.py` | 输出历史会议、行动项、风险、建议议题和 checklist |
| `scripts/pre_meeting_live_test.py` | `--write-report` 中增加 `d2_evidence_pack`、`open_action_items`、`historical_risks` |
| `frontend/src/pages/M3ConsolePage.tsx` | 结果区展示 D2 关键字段：历史会议数、行动项数、风险数、Evidence refs |

## 5. D2 任务拆分

| 编号 | 开发任务 | 主要文件 | 验收标准 |
|---|---|---|---|
| D2-01 | 接入历史会议信息 | `core/pre_meeting.py`、`core/storage.py` | 同项目/同主题历史会议能进入 `historical_meetings` |
| D2-02 | 接入历史行动项 | `core/storage.py`、`core/pre_meeting.py` | 未完成行动项显示负责人、截止时间、来源会议 |
| D2-03 | 接入历史风险 | `core/storage.py`、`core/risk_scan.py`、`core/pre_meeting.py` | 会前卡片显示持续风险和建议动作 |
| D2-04 | 引入轻量 RAG / Evidence Pack | `core/knowledge.py`、`core/pre_meeting.py` | Evidence Pack 有 `ref_id/snippet/source_url/omitted_count` |
| D2-05 | 生成会议背景摘要 | `core/pre_meeting.py`、`core/workflows.py`、`core/llm.py` | scripted_debug 可稳定生成；豆包真实模型能基于 evidence 生成非空泛摘要 |
| D2-06 | 生成建议议题 | `core/pre_meeting.py`、`core/workflows.py` | 豆包输出的议题能由历史结论、开放问题、风险推导，并带依据 |
| D2-07 | 生成会前 Checklist | `core/pre_meeting.py`、`core/workflows.py` | checklist 包含材料、负责人、风险确认和目标；每条来自 evidence 或明确标注待确认 |
| D2-08 | 优化会前卡片布局 | `cards/pre_meeting.py` | 飞书卡片分区清晰，一眼区分背景/行动项/风险/证据 |
| D2-09 | 增加证据来源区域 | `cards/pre_meeting.py` | 卡片展示最多 5 条 evidence，支持链接或 `ref_id` |
| D2-10 | 准备会前卡片演示样例 | `scripts/pre_meeting_card_demo.py`、`tests/e2e_fixtures/**` | 本地命令可复现完整 D2 卡片 |

## 6. 分阶段落地计划

### Phase 1：确定性历史上下文汇聚

优先完成 D2-01、D2-02、D2-03。

- 新增 `PreMeetingEvidencePack`。
- 新增 storage 只读查询接口。
- 用项目记忆、历史 workflow result、`task_mappings` 和 `risk_notifications` 构造本地可复现样例。
- 不接真实写入，不改飞书发送逻辑。

建议验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/pre_meeting.py core/storage.py core/risk_scan.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/pre_meeting_summary_demo.py
```

### Phase 2：MeetingBrief 与卡片布局增强

优先完成 D2-05、D2-06、D2-07、D2-08、D2-09。

- 扩展 `MeetingBrief`，保留旧字段兼容。
- `cards/pre_meeting.py` 增加遗留行动项、建议议题、checklist 和 Evidence Pack 分区。
- `render_pre_meeting_card_payload()` 输出新版 `sections/card`。

建议验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile cards/pre_meeting.py core/pre_meeting.py scripts/pre_meeting_card_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/pre_meeting_card_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_pre_meeting_summary tests.test_pre_meeting_retrieval tests.test_pre_meeting_topic
```

### Phase 3：RAG Evidence Pack 与 Agent 输出约束

优先完成 D2-04。

- 明确 `knowledge.search` 参数预算和项目过滤策略。
- 在 `PreMeetingBriefWorkflow.build_workflow_goal()` 加入 D2 输出约束。
- 报告中记录 knowledge hits、历史 evidence、低置信原因。
- 使用 `scripted_debug` 做稳定链路基线，再使用 `settings.local.json` 中配置的真实模型做小样本验证。
- 豆包提示词必须强调“只基于工具证据生成，不编造历史结论/任务/风险”。

建议验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/knowledge_tools_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/workflow_runner_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider settings --max-iterations 5
```

豆包真实模型验证通过标准：

- 至少出现一次 `knowledge_search` 工具调用，必要时出现 `knowledge_fetch_chunk`。
- 最终回答包含会前背景摘要、建议议题或 checklist。
- 回答中没有把无证据内容写成确定性历史事实。
- 如果证据不足，明确输出“需要确认”或“可能相关资料”。

### Phase 4：演示样例与真实联调

优先完成 D2-10。

- 新增 D2 fixture：历史会议、历史任务、历史风险、项目文档混合输入。
- `pre_meeting_live_test.py --write-report` 输出 D2 核心字段。
- Console M3 运行结果展示 D2 统计摘要。

建议验证：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --llm-provider scripted_debug \
  --idempotency-suffix "d2-demo" \
  --write-report \
  --dry-run

/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 \
  --date today \
  --event-title "MeetFlow 测试会议" \
  --llm-provider settings \
  --idempotency-suffix "d2-settings-readonly" \
  --write-report \
  --dry-run
```

真实飞书写入仍需显式 `--allow-write` 或前端二次确认。

## 7. 测试与验收矩阵

| 层级 | 命令/用例 | 覆盖内容 |
|---|---|---|
| 语法检查 | `python -m py_compile core/pre_meeting.py cards/pre_meeting.py core/storage.py` | 基础可运行 |
| 单元测试 | `tests.test_pre_meeting_summary` | 背景摘要、分区选择、证据引用 |
| 单元测试 | 新增 `tests/test_pre_meeting_d2_evidence_pack.py` | 历史会议/行动项/风险汇聚 |
| Demo | `scripts/pre_meeting_card_demo.py` | 完整卡片 JSON |
| Demo | `scripts/pre_meeting_summary_demo.py` | 历史上下文和 checklist |
| E2E 回放 | 新增 `tests/e2e_fixtures/d2_pre_meeting_intelligent_card/case.json` | 可回放 D2 样例 |
| 真实只读 | `scripts/pre_meeting_live_test.py --llm-provider scripted_debug --write-report` | 真实日历 + 知识索引 + 报告 |
| 真实 LLM 小样本 | `scripts/pre_meeting_live_test.py --llm-provider settings --write-report` | `settings.local.json` 中配置的真实模型基于 Evidence Pack 生成摘要、议题和 checklist |
| 真实写入 | `scripts/card_send_live.py m3 ... --allow-write` | 飞书测试群卡片发送，必须显式允许 |

## 8. 风险与控制

| 风险 | 控制方式 |
|---|---|
| 历史资料污染本次会议 | 优先使用 `project_id/meeting_id/source_url` 硬过滤；低分只进“可能相关资料” |
| LLM 编造历史结论 | workflow goal 强制“有证据或标注不足”；卡片只渲染带 evidence 的确定性历史项 |
| 豆包真实模型接收敏感会议内容 | 真实模型验证前先脱敏；默认用 `scripted_debug`；确认风险后才传 `--llm-provider settings` |
| 豆包 key 泄露 | 只放 `settings.local.json` 或环境变量；文档、日志、报告和提交记录不得出现真实 key |
| 行动项状态不准 | 首版标注“来自上次任务映射/待核对”，真实任务状态通过 `tasks.list_my_tasks` 补充 |
| 风险重复提醒感太强 | 会前只展示风险，不执行提醒写操作；M5 降噪仍归 M5 管 |
| 卡片过长 | 每个分区限制 3-5 条；Evidence Pack 使用 token budget 和 `omitted_count` |
| 真实写入误发 | 继续沿用 `allow_write`、二次确认、幂等后缀和测试群 |
| 本地运行数据误提交 | 不提交 `storage/` 报告、SQLite、真实 token 和运行产物 |

## 9. 建议提交边界

建议拆成 3 个 PR 或 3 轮本地改动：

1. `feat(pre-meeting): add D2 evidence pack and history recall`
   - `core/pre_meeting.py`
   - `core/storage.py`
   - `tests/test_pre_meeting_d2_evidence_pack.py`

2. `feat(cards): enhance pre-meeting preparation card`
   - `cards/pre_meeting.py`
   - `scripts/pre_meeting_card_demo.py`
   - `tests/test_pre_meeting_summary.py`

3. `docs/demo: add D2 pre-meeting demo fixture and runbook`
   - `tests/e2e_fixtures/d2_pre_meeting_intelligent_card/case.json`
   - `docs/overall-test-commands.md`
   - `frontend/src/pages/M3ConsolePage.tsx`（如需要展示 D2 统计）

## 10. 完成定义

D2 可以认为完成，当且仅当满足：

- 会前卡片能显示历史会议摘要、上次结论、遗留行动项、历史风险、建议议题、checklist 和 Evidence Pack。
- 每个确定性结论都有来源，或明确标注证据不足。
- 本地 demo 能稳定生成完整卡片 JSON。
- `scripted_debug` 下能跑通 M3 会前工作流并输出 D2 报告字段。
- `doubao` 下至少完成 1 条脱敏真实模型只读验证，证明豆包能基于 Evidence Pack 生成背景摘要、建议议题和 checklist。
- 真实写入路径仍默认关闭，开启后必须显式确认并保留幂等键。
- `tasks.md` 或对应任务文档记录本轮改动、验证命令、结果和剩余风险。

答辩口径：

> D2 后的会前卡片不是会议提醒，而是 MeetFlow Agent 基于飞书日历、历史会议、任务闭环、风险巡检和轻量 RAG 主动生成的会前智能准备报告。

## 11. 本轮代码实现记录

2026-05-10 已完成 D2 首轮代码接入，保持现有 `pre_meeting_brief` 主链路不变。

核心改动：

- `core/pre_meeting.py`：新增 `PreMeetingEvidencePack`，在 `build_pre_meeting_brief_artifacts()` 中汇聚历史会议、遗留行动项、历史风险和知识证据；扩展 `MeetingBrief`，新增 `meeting_basic_info`、`historical_meetings`、`open_action_items`、`historical_risks`、`suggested_agenda`、`pre_meeting_checklist`、`evidence_pack`。
- `core/storage.py`：新增只读查询接口 `find_recent_workflow_results()`、`find_task_mappings()`、`find_recent_risk_notifications()`，用于 D2 会前读取历史事实，不触发外部副作用。
- `cards/pre_meeting.py`：会前卡片新增会议基本信息、遗留行动项、历史风险、建议议题、会前 Checklist 和 Evidence Pack 分区，并增加“查看历史”按钮。
- `scripts/pre_meeting_live_test.py`：`--write-report` 报告新增 D2 智能准备字段，便于真实联调检查历史会议、行动项、风险、议题、checklist 和 Evidence Pack。
- `scripts/pre_meeting_card_demo.py`：演示样例补齐 D2 完整卡片数据。
- `tests/test_pre_meeting_d2_evidence_pack.py`：新增 D2 回归测试，覆盖 storage 历史行动项、风险提醒、项目记忆历史会议和卡片分区。
- `docs/current-version-test-commands.md`：补充 D2 飞书真实联调步骤，包括 `scripted_debug`、`doubao` 只读和真实发送命令。

验证记录：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/pre_meeting.py core/storage.py core/workflows.py cards/pre_meeting.py scripts/pre_meeting_card_demo.py scripts/pre_meeting_live_test.py tests/test_pre_meeting_d2_evidence_pack.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_pre_meeting_d2_evidence_pack tests.test_pre_meeting_summary tests.test_pre_meeting_retrieval tests.test_pre_meeting_topic
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/pre_meeting_card_demo.py
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 5
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 --date today --event-title "MeetFlow 测试会议" --llm-provider scripted_debug --idempotency-suffix "d2-check" --write-report --dry-run
```

结果：

- 语法检查通过。
- D2/M3 会前相关单测 7 条通过。
- 会前卡片 demo 可生成包含 D2 分区的完整 card JSON。
- 本地 Agent demo 可跑通 `pre_meeting_brief`。
- M3 真实联调 dry-run 可正确拼接下游命令。

已知限制：

- `scripts/workflow_runner_demo.py` 当前在本机失败，原因是 ChromaDB 向量索引不可用，报错为“ChromaDB 不可用，无法执行向量检索”。该问题与 D2 历史证据聚合无直接关系，后续需要在知识索引环境恢复后补跑。
- 豆包真实模型只读联调尚未执行；需要确认本地 `settings.local.json` 或环境变量中已配置方舟 `ep-...` 和 API key 后再运行。

2026-05-10 补充豆包 401 配置防呆。

真实联调出现 `AuthenticationError: The API key format is incorrect` 后，已在 `core/llm.py`
增强本地校验：自动去掉误填的 `Bearer ` 前缀；识别 `replace-with...` 占位符；
如果把 `ep-...` 推理接入点 ID 填到 `api_key`，或 `api_key` 与 `model` 完全相同，会在本地直接报出
中文配置错误，不再等远端 HTTP 401。同步更新 `config/README.md`，明确 `model` 放 `ep-...`，
`api_key` 放火山方舟 API Key 本体。验证命令：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/llm.py tests/test_doubao_llm_provider.py
/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_doubao_llm_provider
```

2026-05-10 补充 ChromaDB 不可用时的前置知识降级路径。

真实联调用 `--doc` 注入飞书文档时，文档读取已经成功，但本地 ChromaDB 不可用会导致
向量索引写入失败。为保证 D2 演示不被向量库环境阻塞，`KnowledgeIndexStore.index_resource()`
现在会在 ChromaDB 写入失败时保留 SQLite/FTS5/BM25 关键词索引，并返回
`indexed_keyword_only`。这种状态下 `knowledge.search` 仍可通过关键词/BM25/RRF 召回
前置知识，只是 `vector_rank` 为空、`vector_similarity=0`，Evidence Pack 的 reason
会体现 BM25 召回。

已用真实飞书文档《会议协作流程优化说明》复测：

```bash
/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/pre_meeting_live_test.py \
  --identity user \
  --event-title "MeetFlow 测试会议" \
  --lookahead-hours 24 \
  --project-id meetflow \
  --doc "https://jcneyh7qlo8i.feishu.cn/docx/NmzrdrymVovok2xTKorcfqT4nqb" \
  --llm-provider settings \
  --force-index \
  --write-report
```

结果：Agent `status=success`，报告写入
`storage/reports/m3/pre_meeting_live_75a40fbc76b2.md`；索引摘要中该文档
`status=indexed_keyword_only`、`chunk_count=6`。卡片草案引用了该文档中的项目目标、
开发进展、待落地任务和风险信息。
