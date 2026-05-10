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
- 开发前必须确认 [开发约定 0：共享契约和开发护栏](docs/tasks/shared-contracts.md)，并阅读 `AGENTS.md`、`git-instruction.md`、`team-work-division.md`
- 大型代码修改完成后必须记录精简关键改动，重点说明改了什么、如何验证和剩余风险

## 优先级说明

- `P00`：共享契约和开发护栏，优先级高于所有功能开发
- `P0`：必须完成，缺失会导致 Demo 主链路无法成立
- `P1`：重要增强，影响稳定性、可解释性和答辩效果
- `P2`：可选增强，适合有余力时补充

## 里程碑文档

- [开发约定 0：共享契约和开发护栏](docs/tasks/shared-contracts.md)
- [M1：项目骨架与基础设施](docs/tasks/m1-foundation.md)
- [M2：飞书接入与数据读取](docs/tasks/m2-feishu-integration.md)
- [M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md)
- [M3：会前知识卡片工作流](docs/tasks/m3-pre-meeting.md)
- [M4：会后总结与任务落地工作流](docs/tasks/m4-post-meeting.md)
- [M5：风险巡检与提醒工作流](docs/tasks/m5-risk-scan.md)
- [M6：评估、答辩材料与演示脚本](docs/tasks/m6-evaluation-demo.md)
- [D：OpenClaw 智能化演示增强与 CLI/Console 指引](docs/tasks/openclaw-demo-enhancement.md)
- [技术拆分、依赖关系、开发顺序与验收总表](docs/tasks/planning-and-acceptance.md)

## OpenClaw 智能化演示增强正式指引

OpenClaw 智能化演示增强是当前版本提升计划的正式开发方向之一。完整任务方案已沉淀到
[D：OpenClaw 智能化演示增强与 CLI/Console 指引](docs/tasks/openclaw-demo-enhancement.md)，
根目录 `MeetFlow_OpenClaw智能化演示增强任务方案.md` 保留为原始方案稿。
其中 D2 会前卡片增强的代码级拆解与验收计划见
[D2：会前卡片智能准备增强具体改造方案](docs/tasks/d2-pre-meeting-card-enhancement-plan.md)。

该方向不替代既有 M1-M6 研发里程碑，而是作为面向答辩、演示、OpenClaw/CLI 接入和
Console 展示的增强层。为了避免编号冲突，该方向内部统一使用 `D1-D10`：

| 模块编号 | 模块名称 | 核心目标 | 优先级 |
|---|---|---|---|
| `D1` | 演示主线与 OpenClaw 流程设计 | 把项目包装成完整智能化办公流程 | `P0` |
| `D2` | 会前卡片增强 | 引入历史会议和轻量 RAG，生成更完整会前卡片 | `P0` |
| `D3` | 会后总结卡优化 | 让总结卡内容更丰富、更结构化、更适合演示 | `P0` |
| `D4` | 妙记 Agent 分析与任务卡片生成 | 从妙记中识别每个人的任务并生成任务卡片 | `P0` |
| `D5` | 风险巡检卡片扩充 | 让风险巡检结果更清晰、更有证据和建议 | `P0` |
| `D6` | Agent 能力扩充 | 强化工具调用、上下文理解、策略判断和多步骤推理 | `P0` |
| `D7` | 评测体系优化 | 展示 Agent 效果、安全性、工具轨迹和业务价值 | `P0` |
| `D8` | 后端 CLI / OpenClaw 接入 | 通过受控 Agent、Console facade 和白名单脚本形成 CLI 入口 | `P0` |
| `D9` | 前端现代化改造 | 改造 Console 界面，让流程更清楚、更像真实产品 | `P0` |
| `D10` | 演示材料与兜底方案 | 准备脚本、录屏、截图、FAQ 和备用数据 | `P0` |

### OpenClaw / CLI 必须交付

后续开发应至少交付以下内容，避免 OpenClaw 只停留在概念层：

| 交付物 | 建议路径 | 验收标准 |
|---|---|---|
| 统一 CLI 入口 | `scripts/meetflow_cli.py` | 一条命令能触发 health、M3、M4、M5、eval、demo replay |
| OpenClaw 工具说明 | `docs/openclaw-meetflow-tool-guide.md` | 能说明 OpenClaw 如何调用 MeetFlow 能力 |
| OpenClaw 工具清单示例 | `config/openclaw_tools.example.json` 或文档内 JSON 示例 | 工具名称、输入、输出清晰 |
| 演示命令脚本 | `docs/openclaw-demo-commands.md` | 主演示路径和兜底路径可复现 |
| CLI 标准 JSON 输出 | CLI stdout / report | 输出 `trace_id`、`workflow_type`、`status`、`report_path`、`safety_summary` |

### CLI / OpenClaw 安全边界

CLI 和 OpenClaw 接入必须继续遵守 MeetFlow 主链路：

```text
OpenClaw / CLI
  -> scripts/meetflow_cli.py
  -> Console API facade / 现有白名单脚本 / MeetFlowAgent.run()
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

明确要求：

- 默认 `dry-run`。
- 真实飞书写操作必须显式 `--allow-write`。
- 写操作必须有 `idempotency_key`。
- 任务创建、消息发送、卡片发送必须经过 `AgentPolicy`。
- CLI 不允许接收任意 shell 命令、任意 Python 表达式或直接写业务表伪造结果。
- CLI 输出和报告不得包含 token、secret、refresh token、API key。

### P0 必须完成

| 编号 | 任务 | 模块 | 验收标准 |
|---|---|---|---|
| `P0-01` | 固定 OpenClaw / CLI / Console 演示主线 | `D1` | 能完整讲清闭环 |
| `P0-02` | 丰富会前卡片 | `D2` | 有历史会议、Checklist、建议议题 |
| `P0-03` | 优化会后总结卡 | `D3` | 有摘要、结论、问题、行动项、风险 |
| `P0-04` | 生成按人分组任务卡片 | `D4` | 每个人任务清晰展示 |
| `P0-05` | 扩充风险巡检卡 | `D5` | 有风险等级、来源、原因、建议动作 |
| `P0-06` | 强化 Agent 工作流表达 | `D6` | 能讲清 Context、Tool、Policy、Trace |
| `P0-07` | 优化评测报告 | `D7` | 有会后、任务、风险、证据、工具调用评测 |
| `P0-08` | 接入后端 CLI | `D8` | CLI 能调用受控入口且默认 dry-run |
| `P0-09` | 设计 OpenClaw 调度入口 | `D8` | 有工具说明、命令示例和标准 JSON 输出 |
| `P0-10` | 改造前端主界面 | `D9` | 现代化、流程清楚、演示友好 |
| `P0-11` | 准备演示脚本和兜底材料 | `D1 / D9` | 可稳定展示 |

## 当前重点

当前开发重点在 [M3：会前知识卡片工作流](docs/tasks/m3-pre-meeting.md) 与
[D：OpenClaw 智能化演示增强与 CLI/Console 指引](docs/tasks/openclaw-demo-enhancement.md)。

2026-05-10 新增开发约定 0：共享契约和开发护栏。
本轮修改 `AGENTS.md`，新增最高优先级共享契约：默认集成分支为 `main`，开工前必须阅读
`git-instruction.md`、`team-work-division.md`、`tasks.md` 和对应 `docs/tasks/**`；
提交前必须记录检查结果；大型代码修改完成后必须给出精简关键改动记录，避免冗长流水账；
禁止提交本地运行数据、真实密钥、第三方源码包、虚拟环境和运行产物。新增
`team-work-division.md`，明确 Agent Runtime、飞书适配、工具策略、M3/M4/M5、
Console/CLI/OpenClaw、评测与文档演示等开发线边界；新增
`docs/tasks/shared-contracts.md`，记录 `TASK-00-01 确认 Agent 工作规则` 的目标、
验收标准和完成记录。本次为文档更新，未修改业务运行代码，未运行测试。

2026-05-10 新增 D2 会前卡片智能准备增强具体改造方案。
本轮新增 `docs/tasks/d2-pre-meeting-card-enhancement-plan.md`，基于当前
`core/pre_meeting.py`、`cards/pre_meeting.py`、`core/knowledge.py`、`core/storage.py`、
`core/risk_scan.py`、`core/workflows.py` 和 M3 真实联调脚本，拆解 D2 会前卡片增强的
代码级方案。方案明确复用现有 `PreMeetingBriefWorkflow`、`MeetingBrief`、
`KnowledgeIndexStore`、`knowledge.search/fetch_chunk`、`task_mappings` 和
`risk_notifications`，把历史会议、遗留行动项、历史风险、建议议题、会前 checklist
和 Evidence Pack 汇入会前智能准备卡；同时给出分阶段落地、测试矩阵、风险控制和
答辩口径。本次为方案文档更新，未修改业务运行代码，未运行测试。

2026-05-10 接入豆包/火山方舟 LLM provider。
本轮在不读取或写入真实密钥的前提下，新增 `core.llm.DoubaoArkProvider`，复用
OpenAI-compatible Chat Completions 调用方式，支持 `doubao-ark`、`doubao`、
`volcengine-ark`、`volcengine`、`ark` provider 别名；`model` 可填写方舟控制台的
`ep-...` 推理接入点 ID，默认 `api_base` 为 `https://ark.cn-beijing.volces.com/api/v3`，
并兼容用户误填完整 `/chat/completions` 地址时不重复拼接路径。同步更新
`config/llm_providers.example.json`、`config/README.md`、M3 Console provider 白名单与
前端下拉选项，以及 M3/M4/Agent 联调脚本帮助文案。新增
`tests/test_doubao_llm_provider.py`，覆盖 provider 别名、默认方舟 endpoint 和完整 endpoint
兼容。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/llm.py core/__init__.py core/console_api.py scripts/card_send_live.py scripts/meetflow_agent_live_test.py scripts/post_meeting_agent_live_test.py tests/test_doubao_llm_provider.py`
和
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_doubao_llm_provider`
均通过；`git diff --check` 通过。因当前环境 `npm: command not found`，前端 `npm run build`
未能执行，需在安装 Node.js/npm 后补跑。

2026-05-10 修复豆包真实联调 401 配置防呆。
真实联调返回 `AuthenticationError: The API key format is incorrect`，说明请求已到达方舟
Chat Completions endpoint，但认证头中的 key 形态不正确。本轮修改 `core/llm.py`，
统一归一化 API key：去掉误填的 `Bearer ` 前缀，识别 `replace-with...`/`your-...` 占位符；
对豆包 provider 额外拦截 `ep-...` 被填到 `api_key`、`api_key` 与 `model` 完全相同的错配，
改为本地中文配置错误。同步更新 `config/README.md` 和
`docs/tasks/d2-pre-meeting-card-enhancement-plan.md`。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/llm.py tests/test_doubao_llm_provider.py`
和
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_doubao_llm_provider`
均通过。

2026-05-10 统一真实 LLM 配置入口为 settings.local.json。
根据真实联调配置使用要求，本轮将 `scripts/meetflow_agent_live_test.py::build_llm_settings()`
改为只从 `load_settings().llm` 读取真实 LLM 配置；`--llm-provider settings/default/configured`
直接使用 `config/settings.local.json`，`--llm-provider doubao/deepseek/openai` 等真实 provider 名
只作为与当前 settings 中 `llm.provider` 是否匹配的校验别名，不再读取
`config/llm_providers.local.json` 或 `config/llm_providers.example.json`。`agent_demo.py`、
`pre_meeting_live_test.py`、`post_meeting_agent_live_test.py` 的帮助文案同步更新；
`config/README.md`、`config/llm_providers.example.json`、`docs/current-version-test-commands.md` 和
`docs/tasks/d2-pre-meeting-card-enhancement-plan.md` 同步改为“settings.local 是唯一真实运行配置入口”。
新增单测覆盖 `doubao` 别名从 settings.local 配置读取、provider 不匹配时报错。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/llm.py scripts/meetflow_agent_live_test.py scripts/agent_demo.py scripts/pre_meeting_live_test.py scripts/post_meeting_agent_live_test.py scripts/deepseek_llm_live_test.py tests/test_doubao_llm_provider.py`
和
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_doubao_llm_provider`
均通过。另以当前项目 `settings.local.json` 执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/deepseek_llm_live_test.py --prompt "用一句话回答：settings.local 配置已加载。" --max-tokens 128`
验证历史 LLM 连通性脚本也已改为读取 settings.local；输出显示
`provider=doubao-ark model=ep-20260423223203-k4sbx` 并调用成功。

2026-05-10 修复 D2 前置知识注入时 ChromaDB 不可用导致中断。
真实会前卡片联调传入 `--doc` 后，飞书文档读取成功，但 `KnowledgeIndexStore.index_resource()`
在写入 ChromaDB 向量索引失败时直接抛错，导致文档无法进入后续 RAG 测试。本轮修改
`core/knowledge.py`：当 ChromaDB 不可用时保留已写入的 SQLite chunks 和 FTS5/BM25
关键词索引，返回 `indexed_keyword_only`，并在文档 metadata 中标记
`vector_index_status=unavailable`，让 `knowledge.search` 继续通过 BM25/RRF 召回证据。
新增 `tests/test_knowledge_tools.py` 回归测试覆盖向量索引失败时的关键词降级索引和检索。
验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/knowledge.py scripts/pre_meeting_live_test.py tests/test_knowledge_tools.py`
和
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_knowledge_tools`
均通过。使用真实飞书文档
`https://jcneyh7qlo8i.feishu.cn/docx/NmzrdrymVovok2xTKorcfqT4nqb`
重新执行 D2 只读联调成功，报告输出到
`storage/reports/m3/pre_meeting_live_75a40fbc76b2.md` 和 `.json`；索引摘要显示文档
《会议协作流程优化说明》状态为 `indexed_keyword_only`、`chunk_count=6`，Agent 最终
`status=success`。

2026-05-10 更新 D2 会前卡片增强方案以纳入豆包真实模型。
本轮修改 `docs/tasks/d2-pre-meeting-card-enhancement-plan.md`，在当前 D2 方案中补充
豆包/火山方舟接入后的智能化边界：本地历史汇聚和 RAG 检索不依赖聊天大模型，
`DoubaoArkProvider` 负责在 `knowledge.search` / `knowledge.fetch_chunk` 返回的 Evidence Pack
基础上生成会议背景摘要、建议议题和会前 checklist；飞书写入仍由 `im.send_card` 和
`AgentPolicy` 控制。文档同步补充 `settings.local.json` 推荐配置片段、`MEETFLOW_LLM_API_KEY`
环境变量方式、`--llm-provider doubao` 小样本验证命令、真实模型敏感内容风险和完成定义。
本次为方案文档更新，未修改业务运行代码。

2026-05-10 完成 D2 会前智能准备卡首轮代码接入。
本轮在不改变 MeetFlow 主链路的前提下扩展 `pre_meeting_brief`：`core/pre_meeting.py`
新增 `PreMeetingEvidencePack` 和 D2 汇聚逻辑，将历史会议、遗留行动项、历史风险、
建议议题、会前 checklist 和 Evidence Pack 合并进 `MeetingBrief`；`core/storage.py`
新增 `find_recent_workflow_results()`、`find_task_mappings()`、
`find_recent_risk_notifications()` 三个只读查询接口；`cards/pre_meeting.py` 新增会议基本信息、
遗留行动项、历史风险、建议议题、会前 Checklist、Evidence Pack 分区和“查看历史”按钮；
`scripts/pre_meeting_live_test.py` 的 `--write-report` 报告增加 D2 智能准备字段；
`scripts/pre_meeting_card_demo.py` 更新为完整 D2 样例；新增
`tests/test_pre_meeting_d2_evidence_pack.py` 覆盖 D2 证据包、storage 历史行动项/风险和卡片分区；
`docs/current-version-test-commands.md` 补充 D2 飞书真实联调方法。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/pre_meeting.py core/storage.py core/workflows.py cards/pre_meeting.py scripts/pre_meeting_card_demo.py scripts/pre_meeting_live_test.py tests/test_pre_meeting_d2_evidence_pack.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_pre_meeting_d2_evidence_pack tests.test_pre_meeting_summary tests.test_pre_meeting_retrieval tests.test_pre_meeting_topic`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/pre_meeting_card_demo.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 5`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/card_send_live.py m3 --date today --event-title "MeetFlow 测试会议" --llm-provider scripted_debug --idempotency-suffix "d2-check" --write-report --dry-run`
均通过。`scripts/workflow_runner_demo.py` 当前因本机 ChromaDB 向量索引不可用失败，错误为
“ChromaDB 不可用，无法执行向量检索”，与 D2 历史证据聚合无直接关系；豆包真实模型只读联调
尚未执行，需配置方舟 `ep-...` 和 API key 后补跑。

2026-05-10 将 OpenClaw 智能化演示增强方案正式写入任务体系。
本轮新增 `docs/tasks/openclaw-demo-enhancement.md`，将
`MeetFlow_OpenClaw智能化演示增强任务方案.md` 沉淀为 `docs/tasks/` 下的正式任务指引；
同步扩展 `tasks.md`，新增该方向在里程碑文档中的入口、D1-D10 模块总表、
OpenClaw/CLI 必须交付物、CLI 安全边界和 P0 必做清单。后续涉及 OpenClaw、CLI、
Console 演示增强、Agent 可解释展示和评测可视化的开发，应优先同步更新该任务文档。
本次为规划文档更新，未修改业务运行代码。

2026-05-10 收敛 OpenClaw 智能化演示增强任务方案。
本轮修改 `MeetFlow_OpenClaw智能化演示增强任务方案.md`，重点解决三处规划风险：将方案内部
模块编号从 `M1-M10` 调整为 `D1-D10`，避免与项目既有 M1-M6 研发里程碑冲突；补充
OpenClaw 在 MeetFlow 中的具体定位、必须交付物、建议 CLI 命令形态和标准 JSON 输出；
补充 CLI / OpenClaw 接入安全边界，明确 CLI 只能调用受控 Agent、Console facade、
白名单脚本或现有 `MeetFlowAgent.run()` 链路，默认 dry-run，真实写操作必须显式
`--allow-write`、保留幂等键并经过 `AgentPolicy`。本次为规划文档更新，未修改业务运行代码。

2026-05-10 新增 MeetFlow 项目版本提升计划。
本轮基于 `prd.md`、`architecture.md`、`tasks.md`、`docs/llm-agent-evaluation-system-plan.md`、
`docs/intelligent-agent-and-eval-upgrade-design.md`、飞书卡片交互方案、Console 设计文档
以及当前 `core/`、`adapters/`、`cards/`、`scripts/`、`tests/` 主链路实现，新增
`docs/meetflow-version-upgrade-plan.md`。该计划把课题一“办公场景驱动的智能知识助手”
和方向 B“会议与项目的全链路伴侣”映射为 V1.6/V1.7/V1.8/V2.0 四阶段升级路线，覆盖
高密度知识对象、RAG 证据质量、M4 会后智能闭环、主动触发、项目记忆、Console 演示总控台、
Agent 轨迹评测、真实 LLM 小样本和业务价值指标。本次为规划文档更新，未修改业务运行代码。

2026-05-06 修复 M4 飞书待确认任务卡填写后仍提示缺负责人/截止时间的问题。
真实飞书群卡片中，用户在“修改字段”窗口填写负责人和截止时间后，点击“保存修改”或
“确认创建”仍可能返回“任务缺少负责人或截止时间”。根因是飞书 schema 2.0 回调会把
`form_value` 包装在表单名下，例如 `{pending_form_x: {owner_override__item: ...}}`，
旧逻辑只读取顶层字段，导致后端继续拿到空值。本轮修改 `core/card_callback.py`，
新增 `find_form_value_by_key()`、`find_form_value_by_prefix()` 和
`sanitize_callback_text()`，支持递归读取嵌套表单字段，并清理 NUL 等控制字符，避免
卡片输入继续触发 `embedded null byte`。新增
`tests/test_post_meeting_card_callback.py` 回归用例，覆盖嵌套 form_value、负责人
`李健文\u0000` 清理、保存后再用旧空按钮确认创建仍成功的完整路径。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/card_callback.py tests/test_post_meeting_card_callback.py`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback`，
均通过；当前 M4 卡片回调测试 18 条通过。

2026-05-06 修复真实联调页 M4 真实发送时 `embedded null byte` 与布局溢出问题。
用户在前端点击 M4 真实发送后，Console API 返回底层 `embedded null byte`，页面同时出现
局部布局被长内容撑开的现象。根因是 M4/M5 前端输入可能从飞书页面复制时混入不可见控制
字符，后端直接把该字符串放入 `subprocess.run()` 参数时触发 Python 底层 ValueError。
本轮修改 `core/console_api.py`，新增 `clean_text_argument()` 和
`validate_command_arguments()`，在 M3/M4/M5 参数校验和命令执行前拒绝空字符及控制字符，
并返回可读的中文业务错误；新增 `tests/test_console_api.py` 回归用例覆盖 M4 minute 中
混入 `\x00` 的场景。前端修改 `frontend/src/pages/LiveFlowPage.tsx`，在 minute/chat_id
输入时清理控制字符；修改 `frontend/src/styles/app.css`，为真实联调布局、面板、日志和
表格长文本增加 `min-width: 0`、`overflow-wrap` 和 `pre-wrap`，避免错误或 stdout 撑坏页面。
验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/console_api.py tests/test_console_api.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api` 和
`git diff --check -- core/console_api.py tests/test_console_api.py frontend/src/pages/LiveFlowPage.tsx frontend/src/styles/app.css`，
均通过；当前 Console API 测试 11 条通过。

2026-05-06 按完整联调 Runbook 改进真实飞书群演示视频录制稿。
本轮更新 `MeetFlow_真实飞书群联调演示视频录制稿.md`，将视频主线从早期命令行脚本演示
调整为与 `docs/meetflow-full-live-test-runbook.md` 对齐的 Console 版真实联调录制方案。
新增录制窗口布局、终端启动脚本、前端 Dashboard/Jobs/真实联调/M3/M4/M5 操作镜头、
逐镜头解说词、飞书群按钮确认任务录制步骤、M5 风险巡检录制步骤、成片时间轴、失败兜底
素材、项目亮点和录制收尾检查。原智能客服工单会议素材继续保留，作为 M4 妙记内容准备
材料。本次为文档录制方案更新，未修改业务运行代码。

2026-05-06 新增一键真实联调控制台第二阶段设计方案。
本轮新增 `docs/one-click-live-test-console-phase2-design.md`，承接第一阶段真实联调
控制台落地结果，规划第二阶段重点能力：M3/M4/M5 异步入队与 job 轮询、完整
M3 -> M4 -> M5 演示模式、demo session 状态恢复、M4 待确认任务业务视图、M5
风险提醒业务视图，以及 OAuth、默认群、SDK 环境、Worker/回调服务健康检查。文档
包含后端 API、job payload、demo session 表、前端组件、实施顺序、测试计划和完成
标准。本次为设计文档更新，未修改业务运行代码。

2026-05-06 新增 MeetFlow 从零启动到真实飞书群完整联调 Runbook。
本轮新增 `docs/meetflow-full-live-test-runbook.md`，用于指导从基础质量检查、OAuth
授权、Console API、前端 Vite、前端真实联调页面，到 M3 会前卡片、M4 会后总结和待确认
任务卡、群内按钮确认、M5 风险巡检卡的完整运行与验收。文档明确推荐只手动启动
Console API 与前端两个长期终端，其余 Worker、SDK 回调和 M4 按钮回调优先通过前端
`真实联调` 页面启动；同时提供手动备用终端命令，并说明 SDK 统一回调与 M4 按钮回调
监听 card.action.trigger 时应二选一，避免重复处理。本次为文档 runbook 更新，未修改
业务运行代码。

2026-05-06 落地 MeetFlow Console 一键真实联调第一阶段。
本轮按照 `docs/one-click-live-test-console-code-design.md` 开始实现真实联调控制台。新增
`core/service_manager.py`，用白名单 profile 管理 Worker、SDK 回调和 M4 按钮回调等
长期服务，记录 PID、启动命令、日志路径和 `storage/runtime/services.json` 状态；扩展
`core/console_api.py`，新增 `M4ReadMinuteRequest`、`M4SendCardsRequest`、
`M5RiskScanRequest`，提供 `/api/services`、`/api/services/start`、
`/api/services/stop`、`/api/services/logs`、`/api/m4/read-minute`、
`/api/m4/send-cards`、`/api/m5/risk-scan` 以及 M4/M5 运行表查询能力，继续通过
`scripts/post_meeting_live_test.py`、`scripts/card_send_live.py` 和
`scripts/risk_scan_demo.py` 执行真实链路，不允许前端传任意 shell 命令。前端新增
`frontend/src/pages/LiveFlowPage.tsx`、`ServiceControlPanel`、`CommandResultPanel`，
并在 `App.tsx` 增加“真实联调”导航；页面支持服务启动/停止/日志查看、M4 妙记只读解析、
M4 dry-run/真实发卡、M5 local/feishu direct/enqueue 巡检和真实写入二次确认。同步更新
`docs/frontend-system-design.md` 与 `docs/overall-test-commands.md`。已执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/service_manager.py core/console_api.py scripts/meetflow_console_server.py tests/test_console_api.py`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api`，
10 条 Console API 测试通过；`npm run build` 因当前环境 `npm: command not found`
未能执行，需安装 Node.js/npm 后补跑前端构建。

2026-05-06 新增真实飞书群联调演示视频录制稿。
本轮新增 `MeetFlow_真实飞书群联调演示视频录制稿.md`，用于录制 MeetFlow 项目
Demo 视频。文档包含视频录制流程、可直接照念的解说词、终端演示命令、飞书群真实
测试步骤、独立的“大厂项目开发需求评审会”会议内容准备稿、项目整体功能介绍、各模块
演示目的和异常情况处理话术。会议素材覆盖 M4 会后总结、待确认任务和 M5 风险巡检
所需的需求澄清、前后端接口、数据库字段、权限、排期、测试策略和风险点。本次只新增
录制文档，未修改业务代码。

2026-05-06 重写 MeetFlow 整体测试命令文档，补齐前端启动与终端分工。
本轮重写 `docs/overall-test-commands.md`，在不改变原有测试命令含义的前提下，
将文档整理为 16 个执行章节：文档用途、快速启动总览、终端分工、最小测试流程、
前端启动、后端基础检查、SDK/HTTP 回调、Worker/Daemon、OAuth/飞书基础读、
M3/M4/M5 真实测试、SQLite 排查、提交前检查、按改动类型选择测试范围和常见问题
排查。新增 `frontend/` 启动命令、`npm run build` 构建检查、`127.0.0.1:5173`
访问地址，以及 Vite `/api` 代理到 `127.0.0.1:8787` 的说明；同时明确终端 1-5
分别用于前端、Console API/HTTP fallback、SDK 回调、Worker 和一次性测试排查。
已执行 `git diff --check -- docs/overall-test-commands.md` 通过。

2026-05-06 完成 MeetFlow Console 前端 UI/UX 优化。
本轮在不修改后端接口路径、不删除既有功能的前提下，重点优化 `frontend/src/**`
展示层。新增 `PageHeader`、`FeatureCard`、`StepList` 三个通用展示组件，改造
`App.tsx` 侧边导航、Dashboard、M3 会前背景卡、Agent 评测中心和 Jobs/Health 页面，
让首屏具备系统状态、核心能力入口、功能说明、状态标签、空状态提示和操作引导。M3
页面补充“配置参数 -> 连接飞书 -> Dry-run/真实发卡 -> 查看结果”步骤感，真实发卡仍
保留 `allow_write` 与二次确认弹窗；评测和 Jobs 页面补充质量门禁、migration、worker
dry-run 的说明和结果摘要。样式集中更新在 `frontend/src/styles/app.css`，采用更清晰的
SaaS/AI Agent 工作台布局、卡片层级、按钮状态、响应式布局和窄屏适配。已执行
`git diff --check` 通过；当前机器仍未安装 Node.js/npm，`node -v`、`npm -v` 不可用，
因此 `npm run build` 尚未在本机执行。`docs/overall-test-commands.md` 已补充前端
UI/UX 回归检查步骤。

2026-05-06 修正 M3 真实发卡日期窗口排查说明。
用户在 2026-05-06 执行 `scripts/card_send_live.py m3 --date tomorrow --event-title "MeetFlow 测试会议"`
时，实际查询窗口为 2026-05-07 本地整天；飞书日历中该窗口没有匹配会议，因此
`pre_meeting_live_test.py` 返回“给定时间窗口内没有可用于测试的会议”。本轮修改
`scripts/pre_meeting_live_test.py`，在无会议时输出查询窗口的本地绝对时间，并提示
使用 `--date today`、`--date YYYY-MM-DD` 或 `--event-id`；同步更新
`docs/overall-test-commands.md`，说明 `--date tomorrow` 的日期含义、today/绝对日期
替代命令以及 `--dry-run` 只打印下游命令不查询飞书。已执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile scripts/pre_meeting_live_test.py scripts/card_send_live.py`
和 M3 `--dry-run` 命令，均通过。

2026-05-06 完成 MeetFlow Console 第一版代码落地。
本轮新增 `core/console_api.py`、`scripts/meetflow_console_server.py`、
`tests/test_console_api.py` 和 `frontend/` React/Vite 控制台骨架。后端 facade
已提供 `/api/health`、`/api/dashboard`、`/api/jobs`、`/api/reports/latest`、
`/api/migrations/status`、`/api/evaluation/run`、`/api/m3/send-card`、
`/api/worker/run-once`，继续复用现有 `MigrationRunner`、`workflow_jobs`、
`storage/reports/**`、`scripts.agent_eval_suite.run_agent_eval_suite()` 和
`scripts/card_send_live.py m3`，不绕过 `AgentPolicy`、`ToolRegistry` 或
`FeishuClient`。前端第一版包含 Dashboard、M3 会前发卡、Agent 评测中心和
Jobs/Health 页面，所有真实发卡入口保留 `allow_write` 和二次确认。已同步更新
`architecture.md` 和 `docs/overall-test-commands.md`。验证命令包括
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/console_api.py scripts/meetflow_console_server.py tests/test_console_api.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_console_api`，
以及启动 `/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/meetflow_console_server.py --host 127.0.0.1 --port 8787`
后用 `curl --noproxy '*'` 验证 `/api/health`、`/api/dashboard` 和
`/api/evaluation/run`，均通过；`/api/evaluation/run` 返回 `score=1.0`、
`safety_score=1.0`。当前机器未安装 Node.js/npm，前端 `npm install` 和
`npm run build` 尚未执行，测试命令文档已记录该前置条件。

2026-05-06 新增 MeetFlow Console 代码实现设计方案。
本轮新增 `docs/frontend-code-implementation-plan.md`，承接
`docs/frontend-system-design.md`，进一步明确前端控制台落地时的目录结构、
`core/console_api.py`、`scripts/meetflow_console_server.py`、`frontend/src/**`
职责划分、HTTP API、TypeScript DTO、M3 发卡 / Agent 评测 / Jobs Health 的实现
映射、安全副作用控制、分阶段实施顺序和验收命令。已同步更新
`docs/frontend-system-design.md`，加入代码实现方案入口。本次为文档设计更新，
未修改业务运行代码。

2026-05-05 补充 Agent 评测系统使用说明，并新增前端控制台设计方案。
`docs/overall-test-commands.md` 已补齐 `scripts/agent_eval_suite.py` 的单 case 运行、
写报告、报告路径、内置 case、输出字段、细项指标和当前 `scripted_debug` 基线结果；
`docs/tasks/m6-evaluation-demo.md` 已同步当前评测口径、指标解释和新增 case 时的文档
同步要求；新增 `docs/frontend-system-design.md`，提出 `MeetFlow Console` 工作台、
M3 会前发卡、M4 会后确认、M5 风险巡检、Agent 评测中心、Jobs/Health 的页面与 API
设计；`prd.md` 已补充管理控制台作为记忆与效果评估层的产品方向。本次为文档设计更新，
未修改业务运行代码。

2026-05-05 修复 M3 真实发卡时 `assistant_sessions.user_id` NOT NULL 约束失败。
根因是本地 `storage/meetflow.sqlite` 中的 `assistant_sessions` 仍保留早期实验
schema 的 `user_id`、`chat_id`、`current_workflow` 等 NOT NULL 字段，而当前代码
已迁移到 `actor`、`workflow_type`、`memory_json` 字段，`save_assistant_session()`
没有兼容写入旧字段。已修改 `core/storage.py`，保存 assistant session 时按实际表
字段动态生成 INSERT，并为旧字段写入从 `actor` 和 `memory` 推导出的非空值；同时
修改 `core/assistant_memory.py`，把 `project_id` 纳入 session memory；新增
`tests/test_assistant_memory.py` 旧 schema 回归用例。验证命令包括
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/assistant_memory.py core/storage.py scripts/card_send_live.py`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_assistant_memory`、
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_migrations` 和
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/storage_migrate.py --verify`，
均通过。已按用户给出的 `scripts/card_send_live.py m3 --date tomorrow ... --write-report`
真实发卡命令复测成功，trace_id 为 `53fac20460b6`，状态为 `success`。

2026-05-05 修复飞书 SDK 隔离虚拟环境与主 `meetflow` 环境的版本冲突。
根因是 `.venv-lark-oapi` 曾由系统 Python 3.8 创建，既可能缺少 `bin/python`，
又无法导入项目中使用 `dataclass(slots=True)` 的模块；同时主
`/home/tanyd/anaconda3/envs/meetflow/bin/python` 没有安装 `lark-oapi`，
导致 SDK 回调入口落在两个环境之间。已修改 `scripts/setup_lark_oapi_venv.py`，
新增 Python 3.10+ 校验和 `--recreate` 重建开关；已更新
`docs/overall-test-commands.md`，明确主业务环境与 SDK 隔离环境的边界，并要求用
主 `meetflow` Python 创建 `.venv-lark-oapi`。本轮已执行
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/setup_lark_oapi_venv.py --recreate`、
`.venv-lark-oapi/bin/python -V`、`.venv-lark-oapi/bin/python -c "import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok')"`
以及 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile scripts/setup_lark_oapi_venv.py`，
结果均通过；当前 SDK 隔离环境为 Python 3.10.20。

按照 [MeetFlow 当前代码改造思路](docs/current-code-improvement-plan.md) 的这一轮补强已经完成主链路修复：会前卡片按钮 value 不再写死 workflow 幂等键，回调层会按“本次点击”生成幂等键并兼容老卡片；`minute.ready` 和手动 `post_meeting_followup` 已补齐 `contact.get_current_user` / `contact.search_user`；会前刷新场景新增显式的只读上下文补全过程，会从当前 payload、项目记忆和本地历史工作流结果中补回会议标题、参与人、附件与相关资源；`allow_write` 不再挂在共享 loop 实例上，而是通过单次 `run()` 显式透传。对应修改文件包括 `cards/pre_meeting.py`、`core/card_actions.py`、`core/router.py`、`core/agent.py`、`core/agent_loop.py`、`core/workflows.py`、`core/pre_meeting.py`、`core/storage.py` 以及新增的 M3/M4 回归测试文件。本轮使用 `/home/tanyd/anaconda3/envs/meetflow/bin/python` 运行 `py_compile`、24 条针对性 `unittest`、以及 `scripts/agent_demo.py --event-type meeting.soon/minute.ready` 两条本地链路，结果均通过。

2026-05-04 已完成协作者 M3/M4 代码与当前 M5 仓库的融合实现，完整方案见
[MeetFlow 代码仓库融合方案](docs/codebase-fusion-plan.md)。本轮新增或合入
`core/post_meeting.py`、`core/post_meeting_tools.py`、`core/card_callback.py`、
`core/confirmation_commands.py`、`cards/post_meeting.py`、`cards/layout.py`、
M4 demo/live/watcher 脚本以及对应测试；新增统一回调适配层
`adapters/feishu_callback_payloads.py` 和统一业务分发层
`core/feishu_callback_dispatcher.py`；新增 `scripts/feishu_event_sdk_server.py`
作为飞书官方 SDK WebSocket 长连接入口，同时改造 `scripts/feishu_event_server.py`
保留公网 HTTPS fallback。`core/agent.py` 已注册 M4 工具，`core/workflows.py`
已把 `minute.ready` 接入会后 artifact、总结卡、待确认任务和 RAG 计划；
`core/policy.py` 强制会后任务创建必须带人工确认上下文，`core/storage.py`
扩展 `task_mappings` 以衔接 M4 证据链与 M5 风险巡检。验证命令包括
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest discover -s tests`，
结果为 58 条测试全部通过。

同时，基于当前 Agent Runtime 已完成一版结构化日志与观测增强，详细实现记录见
[M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md) 中的
`T2.8-O1 Agent 运行观测与结构化日志增强`。本次新增 `core/observability.py`
和 `tests/test_observability.py`，并接入 `MeetFlowAgent`、`MeetFlowAgentLoop`、
`LLMProvider`、`ToolRegistry`、`AgentPolicy` 判断点以及 `FeishuClient._request()`；
验证命令包括 `py_compile`、`unittest tests.test_observability` 和两条
`scripts/agent_demo.py` 本地链路，结构化事件输出到 `storage/workflow_events.jsonl`。
当前日志设计、新旧日志差异和测试方法已整理到
[MeetFlow 当前日志设计说明](docs/agent-logging-current-design.md)。

2026-05-05 已开始按
[MeetFlow 工业化代码修改方案](docs/industrialization-code-change-plan.md)
落地 P0 工程化能力。本轮新增 `core/migrations.py`、
`scripts/storage_migrate.py` 和 `tests/test_migrations.py`，把
`MeetFlowStorage.initialize()` 改造为“准备目录 -> 执行 migrations -> 校验 schema”，
并新增 `schema_migrations` 与 `workflow_jobs` 表；新增 `core/jobs.py`、
`scripts/meetflow_worker.py` 和 `tests/test_jobs.py`，支持后台任务入队、领取、
重试、失败和死信状态；`scripts/meetflow_daemon.py` 已增加 `--enqueue`，
可把 M3/M4/RAG 机会写入队列；`scripts/feishu_event_sdk_server.py` 和
`scripts/feishu_event_server.py` 已增加 `--enqueue-agent`，保留原有同步/线程执行
路径；`scripts/risk_scan_demo.py` 已增加 `--enqueue`，可让 M5 巡检由 worker 执行。
新增配置 `jobs` 已接入 `config/loader.py` 与 `config/settings.example.json`。
验证命令包括 `py_compile`、`tests.test_migrations tests.test_jobs`、全量
`unittest discover -s tests`、`scripts/storage_migrate.py --status/--verify`、
`scripts/meetflow_worker.py --once --dry-run` 和 SDK server import 检查，当前
76 条单测全部通过。

2026-05-05 修复 M4 待确认任务卡“保存修改后仍提示缺少负责人或截止时间”的问题。
根因是确认创建时会先读取 pending registry，但随后用按钮 callback value 里的空
`owner/due_date` 覆盖了用户刚保存的字段；同时 SDK 长连接归一化没有完整保留
schema 2.0 表单的 `form_value`。本次修改 `core/card_callback.py`，新增
`merge_action_values_preserving_cached()`，确保空字段不覆盖已保存的负责人/截止时间；
修改 `adapters/feishu_callback_payloads.py`，在 `event.action`、`event.operator`
和顶层 payload 间归一化并保留 `form_value/input_value`。新增回归测试覆盖
“保存李四 + 2026-05-01 后点击旧空按钮仍能创建任务”和“SDK operator.form_value
不丢失”。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_post_meeting_card_callback tests.test_feishu_callback_dispatcher`
以及全量 `unittest discover -s tests`，当前 79 条测试全部通过。

2026-05-05 新增第一版项目级离线评测系统，避免项目停留在“真实联调脚本集合”。
本轮新增 `core/evaluation.py`、`scripts/e2e_replay.py`、`tests/test_e2e_replay.py`
和 `tests/e2e_fixtures/**/case.json` 脱敏样本。评测 runner 支持统一读取
fixture、执行 M3 会前卡片确定性产物、M4 会后行动项抽取、M5 风险扫描与
M4 task mapping 来源富化、SQLite job queue 入队/领取/成功路径，并输出
`score`、逐条断言、业务 artifacts 和可写入的 JSON 报告。当前内置 4 个
case：`m3_pre_meeting_basic`、`m4_post_meeting_with_tasks`、
`m5_risk_from_m4_mapping`、`job_queue_recovery`。验证命令：
`/home/tanyd/anaconda3/envs/meetflow/bin/python scripts/e2e_replay.py --all --fail-under 1.0`
和 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_e2e_replay`，
suite score 为 1.0。

2026-05-05 新增长期维护的
[MeetFlow 整体测试命令总表](docs/overall-test-commands.md)。该文档把基础编译、
全量单测、migration/job queue、离线 E2E 评测、SDK/HTTP 回调、daemon/worker、
M3/M4/M5 真实联调、SQLite 排查和提交前检查统一收敛到一个入口，并明确了
“新增脚本、配置、migration、job_type、回调路径、评测 case 或真实联调入口时
必须同步更新测试命令”的维护规则。`docs/current-version-test-commands.md`
已增加指向该总表的说明。

2026-05-05 新增
[MeetFlow LLM Agent 评测系统方案](docs/llm-agent-evaluation-system-plan.md)。
该方案在现有 `core/evaluation.py` 和 `scripts/e2e_replay.py` 的离线确定性评测
基础上，设计了更能体现飞书会议 Agent 特色的指标体系：会议上下文理解、
妙记行动项抽取、工具调用正确性、Policy 安全、证据引用、M4 到 M5 任务风险
闭环、卡片回调交互、真实 LLM provider 稳定性和 fallback。方案同时定义了
case schema、report schema、`core/llm_eval.py`、`scripts/llm_eval_suite.py`、
`core/llm_fallback.py` 的后续改造边界，以及 PR/每日/发布前的质量门禁阈值。
`docs/overall-test-commands.md` 已增加指向该方案的入口说明。

2026-05-05 新增智能会议 Agent 与工业化评测升级第一批代码实现。
基于 [MeetFlow 智能会议 Agent 与工业化评测系统升级方案](docs/intelligent-agent-and-eval-upgrade-design.md)
和 [MeetFlow 智能会议 Agent 与工业化评测代码修改方案](docs/intelligent-agent-and-eval-code-change-plan.md)，
本轮新增 `core/eval_trace.py`、`core/eval_metrics.py`、`scripts/agent_eval_suite.py`
以及 3 条 `tests/e2e_fixtures/agent_trajectory/` 评测样本，并在 `core/agent_loop.py`
和 `core/agent.py` 中接入 `assistant_plan`、`intelligence_signals` 和
`AgentRunResult.payload["agent_trace"]`。这使每次 Agent 运行都能输出可评测的
工具调用轨迹、Policy 决策轨迹、写权限/幂等信号和下一步建议，评测系统也新增了
tool-call F1、工具顺序、禁止工具、Policy 合规、allow-write gate、幂等键覆盖和
敏感信息泄露扫描。对应实现记录见
[M6：评估、答辩材料与演示脚本](docs/tasks/m6-evaluation-demo.md) 的
`T6.3 当前实现补强：Agent 轨迹与智能度评测`，测试命令已同步更新到
[MeetFlow 整体测试命令总表](docs/overall-test-commands.md)。本轮已通过
`py_compile`、新增评测单测、`scripts/agent_eval_suite.py --suite agent_trajectory --provider scripted_debug --fail-under 0.95`、
全量 91 条 `unittest discover -s tests` 和 `scripts/e2e_replay.py --all --fail-under 1.0`。

飞书群聊卡片按钮交互的目标链路、按钮协议、回调服务、CardActionRouter、
Policy/幂等/审计要求和测试步骤已整理到
[飞书群聊卡片按钮交互实施方案](docs/feishu-card-interaction-plan.md)。
对应的文件级代码改动草案、核心类函数签名、实现顺序和验收标准已整理到
[飞书卡片交互代码改动草案](docs/feishu-card-interaction-code-change-draft.md)。
当前已完成飞书卡片按钮交互 MVP：新增 `core/card_actions.py`、
`adapters/feishu_event_handler.py`、`scripts/card_action_demo.py`、
`scripts/feishu_event_server.py` 和对应单测；会前卡片已带 `刷新背景`、
`生成待办草案`、`发给我` 三个按钮，`refresh_pre_meeting_brief` 可转换为
`AgentInput(event_type="card.refresh_pre_meeting")`。实现记录见
[M2.8：业务侧垂直 Agent Runtime](docs/tasks/m2_8-agent-runtime.md) 中的
`T2.17 实现飞书群聊卡片按钮交互 MVP`。
公网 HTTPS 隧道接收飞书卡片回调的联调方法，以及后续与飞书官方 SDK/长连接
方式兼容的边界设计，已整理到
[飞书卡片交互公网回调接入说明](docs/feishu-card-public-callback-guide.md)。

2026-05-05 完成多轮会话记忆、用户补字段后自动恢复 pending action、M4 真实会后任务确认闭环补强。
本轮新增 `core/assistant_memory.py` 和 `tests/test_assistant_memory.py`，并修改
`core/migrations.py`、`core/storage.py`、`core/agent_loop.py`、`core/agent.py`、
`core/card_actions.py`、`core/card_callback.py`、`core/router.py`、
`tests/test_card_actions.py`、`tests/test_post_meeting_card_callback.py`、
`tests/test_migrations.py`、`docs/overall-test-commands.md`。
核心实现包括：
`assistant_sessions`、`pending_actions`、`clarification_questions`、`review_sessions`
四张 SQLite 表；`AgentPolicy` 返回 `needs_confirmation` 时自动保存可恢复动作和澄清问题；
用户下一轮补充负责人 / 截止时间时合并回 pending action，并标记 `ready_to_resume`，
恢复出的工具调用仍准备重新进入 `AgentPolicy`；M4 `confirm_create_task`、
`edit_task_fields`、`reject_create_task` 已进入 `CardActionRouter` 可观测路由；
`core/card_callback.py` 会把真实卡片确认批次写入 `review_sessions` 审计表，继续保留
review_session 旧卡拦截和任务创建幂等键。验证命令已同步更新到
[MeetFlow 整体测试命令总表](docs/overall-test-commands.md)。当前已通过：
`/home/tanyd/anaconda3/envs/meetflow/bin/python -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py config/*.py`
以及 `/home/tanyd/anaconda3/envs/meetflow/bin/python -m unittest tests.test_assistant_memory tests.test_card_actions tests.test_post_meeting_card_callback tests.test_migrations`。

M5 风险巡检与提醒工作流的仓库级详细改造计划已整理到
[M5 风险巡检与提醒工作流详细改造计划](docs/m5-risk-scan-implementation-plan.md)，
建议先实现 `core/risk_scan.py`、`cards/risk_scan.py`、`scripts/risk_scan_demo.py`
和 `tests/test_risk_scan.py`，优先用 mock 任务跑通规则扫描、卡片预览和降噪。
第二版代码施工方案已整理到
[M5 风险巡检第二版代码改造方案](docs/m5-risk-scan-code-change-plan.md)，
按 `core/risk_scan.py`、`cards/risk_scan.py`、`scripts/risk_scan_demo.py`、
`core/storage.py`、`core/workflows.py`、`adapters/feishu_tools.py`、
`core/policy.py` 拆解了具体改造点、数据契约、补丁顺序、测试文件和验收命令。
当前已按该方案完成 M5 第二版核心改造：新增 `core/risk_scan.py`、
`cards/risk_scan.py`、`scripts/risk_scan_demo.py` 以及四组单测；
`RiskScanWorkflow` 已新增 `post_process_result()`，可从 `tasks.list_my_tasks`
工具结果生成 `risk_scan.scan_result`、`notification_decision` 和 `card_payload`；
`core/storage.py` 新增 `risk_notifications` 表，`core/policy.py` 和
`adapters/feishu_tools.py` 已增强风险卡片发送边界。验证命令包括
`py_compile`、M5 单测、本地风险 demo、`agent_demo.py --event-type risk.scan.tick`
和全量 `unittest discover`，结果均通过。

M3 的核心边界是“轻量 RAG + 结构化元数据 + 增量更新”：

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
