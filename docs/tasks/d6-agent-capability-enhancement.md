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
