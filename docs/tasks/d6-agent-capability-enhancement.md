# D6：Agent 能力扩充落地记录

## 1. 任务定位

D6 面向 OpenClaw / CLI / Console 演示中的“Agent 内部机制说明”环节，目标是让 MeetFlow 不只展示
飞书卡片结果，还能解释 Agent 如何理解上下文、选择工具、接受安全策略约束并留下可评测轨迹。

```text
OpenClaw / CLI / Console / Feishu Event
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> WorkflowRunner
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Knowledge / Storage
  -> AgentTrace / Evaluation
```

本轮 D6 不新增绕过主链路的执行入口，而是把现有 Agent Runtime 能力整理为结构化“能力报告”，供
Console、OpenClaw 工具说明、评测中心和答辩材料复用。

## 2. 当前代码基线

| 能力 | 当前实现 | D6 判断 |
|---|---|---|
| 工作流路由 | `core/router.py::WorkflowRouter` | 已能区分会前、会后、M5 任务风险提醒和手动问答 |
| 上下文构建 | `core/context.py::WorkflowContextBuilder` | 已统一抽取会议、妙记、任务、参与人和项目记忆 |
| 工作流骨架 | `core/workflows.py::WorkflowRunner` | 已固定 prepare、Agent Loop、后处理和校验阶段 |
| 工具注册 | `core/tools.py::ToolRegistry` | 已区分内部工具名、LLM 工具名、读写属性和副作用 |
| 安全策略 | `core/policy.py::AgentPolicy` | 已覆盖 allow-write、幂等、任务字段完整性和风险提醒降噪 |
| Trace | `core/eval_trace.py` + `core/agent_loop.py` | 已记录 assistant plan、tool calls、policy decisions 和 intelligence signals |

## 3. 本轮完成内容

### 3.1 新增 Agent 能力报告

新增 `core/agent_capabilities.py`：

- `AgentCapabilityReport`：统一承载 D6 能力报告。
- `build_agent_capability_report()`：只读取本地工作流、工具注册表和 Policy 配置，不执行任何飞书 API 或写操作。
- `build_workflow_section()`：输出每个工作流的目标、允许工具、上下文输入、证据来源、校验规则和阶段。
- `build_tool_section()`：输出工具内部名、LLM 可见名、读写属性、副作用类型和关联工作流。
- `build_policy_section()`：输出 allow-write 默认关闭、写操作幂等、任务创建人工确认、负责人/截止时间要求等安全规则。
- `build_trace_section()`：输出 AgentTrace 和 intelligence signals 的展示字段。
- `build_agent_flow_diagram()`：生成可直接放入文档或答辩材料的 Mermaid 流程图。

### 3.2 新增 D6 报告脚本

新增 `scripts/agent_capability_report.py`：

```bash
python3 scripts/agent_capability_report.py --pretty
python3 scripts/agent_capability_report.py --diagram-only
```

脚本只读取本地 Python 定义，不访问飞书、不读取真实密钥、不执行外部副作用。

### 3.3 导出 core 能力

`core/__init__.py` 新增导出：

- `AgentCapabilityReport`
- `build_agent_capability_report`

后续 Console / CLI / OpenClaw 入口可以直接复用该报告，而不需要重复拼装 Agent 说明。

### 3.4 补充测试

新增 `tests/test_agent_capabilities.py`，覆盖：

- 报告包含 `pre_meeting_brief`、`post_meeting_followup`、`risk_scan` 三条核心业务工作流。
- 报告包含 `tasks.list_my_tasks`、`im.send_card` 等关键工具边界。
- Policy 报告明确 `allow_write_default=false` 和写操作幂等要求。
- Trace 报告包含 `tool_calls` 和 `policy_decisions`。
- 传入真实 `ToolRegistry` 时，报告使用工具真实 `llm_name`、`read_only`、`side_effect` 和 required 字段。

## 4. 涉及文件

| 文件 | 改动 |
|---|---|
| `core/agent_capabilities.py` | 新增 D6 Agent 能力报告生成逻辑 |
| `core/__init__.py` | 导出 D6 报告模型和构建函数 |
| `scripts/agent_capability_report.py` | 新增本地报告输出脚本 |
| `tests/test_agent_capabilities.py` | 新增 D6 能力报告单测 |
| `docs/tasks/d6-agent-capability-enhancement.md` | 新增 D6 里程碑记录 |
| `tasks.md` | 增加 D6 里程碑入口与精简完成摘要 |

## 5. 验证结果

已通过：

```bash
python3 -m py_compile core/agent_capabilities.py core/__init__.py scripts/agent_capability_report.py tests/test_agent_capabilities.py
python3 -m unittest tests.test_agent_capabilities tests.test_eval_trace tests.test_agent_loop_allow_write
python3 scripts/agent_capability_report.py --pretty
```

验证结果：

- D6/Trace/AgentLoop 相关单测共 7 个通过。
- 报告脚本输出包含工作流、工具、Policy、Trace 和 Mermaid 流程图。
- 本轮未访问飞书 API，未执行任何真实写操作。

## 6. 演示命令

输出结构化 Agent 能力报告：

```bash
python3 scripts/agent_capability_report.py --pretty
```

只输出 Agent 流程图：

```bash
python3 scripts/agent_capability_report.py --diagram-only
```

## 7. 剩余风险

- 当前报告脚本默认基于工作流声明推断工具属性；如果要展示运行时真实工具 schema，应由 Console / CLI 在已注册完整 `ToolRegistry` 后调用 `build_agent_capability_report(tool_registry=registry)`。
- 本轮只增强 Agent 能力表达和诊断报告，没有新增多步骤自动编排能力；D8 CLI / OpenClaw 接入时可复用该报告作为工具说明和健康检查输出。
- D6 与 D7 有天然衔接：本轮报告中的 `trace_fields` 和 `intelligence_signals` 后续应进入评测报告展示。

## 8. 2026-05-13 群 @ RAG 总结入口

### 8.1 评估结论

在临近提交、避免引入新 bug 的约束下，本轮不扩展通用聊天机器人，也不新增自由 LLM 编排入口。
可接受的最小实现是：只处理飞书群里 @ 机器人后的文本消息，把用户文本门禁为“基于 RAG 总结主题”，
其余创建任务、查日程、发消息、闲聊或泛问答意图直接拒绝。

### 8.2 完成内容

- 新增 `core/message_dialogue.py`，负责解析 `im.message.receive_v1` 群消息、去除 @ mention、识别总结主题、拒绝非总结意图，并用 `KnowledgeIndexStore.search_chunks()` 生成证据驱动的简短总结。
- 主动回复不绕过安全策略：通过 `im.send_text` 工具发送，先调用 `AgentPolicy.authorize_tool_call()`，仍要求服务启动时显式 `--allow-write`，并记录回复幂等键。
- `core/feishu_callback_dispatcher.py` 同时支持 HTTP 与 SDK 长连接消息事件分发；HTTP 路径复用现有 verification token 校验，卡片按钮分发逻辑保持不变。
- `scripts/feishu_event_sdk_server.py` 在现有 `card.action.trigger` 长连接处理器上追加注册 `im.message.receive_v1`；`scripts/feishu_event_server.py` 保留 HTTP 兜底路径。两者都将 `--allow-write` 传入 dispatcher，避免默认开启写回复。
- 新增 `tests/test_message_dialogue.py`，并扩展 `tests/test_feishu_callback_dispatcher.py`，覆盖 @ 消息解析、意图拒绝、RAG 总结回复、未开启写权限时拦截发送，以及 HTTP dispatcher 分流。

### 8.3 验证结果

已通过：

```bash
python3 -m py_compile adapters/feishu_event_handler.py core/message_dialogue.py core/feishu_callback_dispatcher.py scripts/feishu_event_server.py scripts/feishu_event_sdk_server.py tests/test_message_dialogue.py tests/test_feishu_callback_dispatcher.py
python3 -m unittest tests.test_message_dialogue tests.test_feishu_callback_dispatcher
python3 -m unittest tests.test_feishu_event_handler tests.test_feishu_callback_dispatcher tests.test_message_dialogue tests.test_knowledge_tools
git diff --check
```

### 8.4 剩余风险

- 本轮已接入 SDK 长连接 `im.message.receive_v1` 注册；本地通过编译和 dispatcher 单测验证，真实群聊仍需开放平台订阅消息事件后联调。
- 总结为确定性抽取式总结，不引入新 LLM 调用；优点是稳定、低风险，缺点是语言润色弱于模型生成。
- 真实群聊回复需要飞书事件订阅到 `im.message.receive_v1`，且启动回调服务时传 `--allow-write`；否则只会生成受控处理结果，不会发送群消息。

### 8.5 2026-05-13 长连接隔离环境启动修复

真实启动 `python3 scripts/feishu_event_sdk_server.py --allow-write` 时，主业务环境里的
`lark-oapi` WebSocket protobuf 代码与 protobuf 4.x/5.x 不兼容，会在导入阶段报
`TypeError: Descriptors cannot be created directly`。项目既有约定是把 `lark-oapi==1.4.0`
和 `protobuf==3.20.3` 放在 `.venv-lark-oapi` 隔离环境中运行长连接，避免污染主业务环境。
本轮撤回主环境 protobuf 环境变量兜底，改为在误用主环境启动时报出明确提示，引导使用
`.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --allow-write`。

验证：

```bash
python3 -m py_compile scripts/feishu_event_sdk_server.py
.venv-lark-oapi/bin/python -c "import google.protobuf; import lark_oapi; import scripts.feishu_event_sdk_server; print('sdk server import ok', google.protobuf.__version__)"
.venv-lark-oapi/bin/python scripts/feishu_event_sdk_server.py --help
```

### 8.6 2026-05-13 主动对话 RAG 配置修复

真实群聊测试发现主动对话入口返回 `openai-compatible:text-embedding-3-small:1536` namespace，
但本地 `config/settings.local.json` 实际配置为 `sentence-transformers / BAAI/bge-small-zh-v1.5 / 512`。
根因是 `core/message_dialogue.py` 创建 `KnowledgeIndexStore(settings.storage)` 时漏传
`settings.embedding`、`settings.reranker` 和 `settings.knowledge_search`，导致走了
`KnowledgeIndexStore` 的默认环境配置。本轮已改为显式传入完整 settings，与
`agent_demo.py`、`rag_add_document_live.py`、`meetflow_worker.py` 等入口保持一致。

验证：

```bash
python3 -m py_compile core/message_dialogue.py tests/test_message_dialogue.py
python3 -m unittest tests.test_message_dialogue tests.test_feishu_callback_dispatcher
```

本地模拟 `@机器人 总结 M3 会前知识卡片` 已命中旧索引对应的
`sentence_transformers_baai_bge_small_zh_v1_5_512_137933ce` namespace，并返回真实证据摘要。

### 8.7 2026-05-13 RAG 总结文本质量修复

真实群聊测试发现回复要点里出现 `上次结论 / 当前问题 / 风险` 这类目录标题，并且证据区重复列出同一个文档。
根因是主动对话入口采用确定性抽取式摘要，旧逻辑每个 hit 只取一个候选句，遇到短标题会误当作要点；
证据列表也按 chunk 逐条展示，导致同一文档多个片段重复刷屏。本轮修改
`core/message_dialogue.py`：

- 从每个 snippet 拆出多个候选句，过滤过短标题、目录词和字段名。
- 优先选择命中主题词且信息量足够的句子。
- 证据区按 `source_type + title + source_url/ref_id` 合并，重复文档显示 `命中 N 个片段`。

验证：

```bash
python3 -m py_compile core/message_dialogue.py tests/test_message_dialogue.py
python3 -m unittest tests.test_message_dialogue tests.test_feishu_callback_dispatcher
```

### 8.8 2026-05-13 主动对话 LLM 证据内润色

为提升群聊 @ 机器人后的回复可读性，本轮在 `core/message_dialogue.py` 增加受约束的 LLM 润色阶段：

- 仅在 RAG 已命中证据时调用 `create_llm_provider(settings.llm)`；未命中证据时继续直接说明证据不足。
- LLM 不接收任何工具，也不能决定来源；提示词要求只基于检索片段输出结论、要点和待确认项。
- 证据列表仍由本地代码按命中文档确定性追加，避免模型编造引用。
- LLM 配置缺失、provider 为 dry-run/mock、接口失败或输出为空时，自动回退到 8.7 的抽取式总结。
- `tests/test_message_dialogue.py` 新增 LLM 成功润色与失败 fallback 回归测试。

验证：

```bash
python3 -m py_compile core/message_dialogue.py tests/test_message_dialogue.py
python3 -m unittest tests.test_message_dialogue
python3 -m unittest tests.test_feishu_callback_dispatcher tests.test_message_dialogue tests.test_knowledge_tools
```

剩余风险：`.venv-lark-oapi` 长连接环境仍需要能访问主业务依赖和 LLM 配置；若真实群聊中 LLM 调用超时或配置错误，当前会降级为抽取式总结，不会阻断回复。
