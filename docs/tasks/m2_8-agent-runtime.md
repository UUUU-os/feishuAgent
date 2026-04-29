## 5.2.8 M2.8：业务侧垂直 Agent Runtime

### M2.8 设计目标

M2 已经打通了飞书工具能力，但这些能力目前仍然主要以客户端方法和测试脚本存在。为了让项目成为一个业务侧垂直 Agent，而不是一组工作流脚本，需要在 M3 之前补上 Agent Runtime。

这个 Runtime 的职责是：

- 统一接收事件、定时触发和人工命令
- 识别当前业务意图和触发场景
- 构建会议 / 项目 / 妙记 / 任务上下文
- 路由到正确的业务工作流
- 封装 LLM Agent Loop，让 LLM 在受控工具集内决定下一步调用哪些工具
- 通过 Tool Registry 执行飞书工具和知识处理工具
- 管理幂等键、执行状态、失败降级和审计日志
- 控制自动化边界，例如低置信度任务不直接创建

设计上参考 nanobot 的 `ContextBuilder + LLMProvider + AgentRunner + ToolRegistry` 模式，但 MeetFlow 不做通用 Agent，而是收敛成会议知识闭环垂直 Agent。

M2.8 的 Agent Runtime 采用“确定性工作流骨架 + LLM 工具编排槽位”的模式。也就是说，`WorkflowRouter`、`WorkflowContextBuilder`、Workflow Runner、Validator、`AgentPolicy` 负责确定性边界；`MeetFlowAgentLoop` 只在工作流允许的槽位中运行，负责在限定工具集内多轮检索、抽取、判断和总结。这样可以避免两种极端：一是把所有流程交给 LLM 自由发挥，导致不可控；二是把所有能力写死成 if/else，导致缺少垂直 Agent 的弹性。

推荐执行骨架：

```text
WorkflowRunner
  -> prepare_context
  -> build_plan_or_query
  -> agent_loop
  -> validate_output
  -> apply_side_effects
  -> persist_and_audit
```

其中 `agent_loop` 是 LLM 槽位，其他阶段优先保持确定性、可测试和可审计。

### T2.8 定义 Agent Runtime 数据模型

- 优先级：`P0`
- 目标：定义 Agent 输入、决策、上下文、运行结果、工具调用轮次等核心数据结构
- 建议新增模型：
  - `AgentInput`：承接 event / schedule / command 三类触发
  - `AgentDecision`：描述路由到哪个工作流、为什么、需要哪些工具
  - `WorkflowContext`：承接会议、项目、参与人、资源、记忆和 trace_id
  - `AgentMessage`：记录一次 LLM loop 中的 system / user / assistant / tool 消息
  - `AgentToolCall`：记录 LLM 想调用的工具名、参数和调用 id
  - `AgentToolResult`：记录工具执行状态、结构化结果、错误和证据来源
  - `AgentLoopState`：记录当前 loop 轮数、消息列表、工具结果和停止原因
  - `AgentRunResult`：记录 Agent 执行状态、产物、副作用和下一步动作
- 验收标准：
  - M3-M5 工作流可以统一接收 `WorkflowContext`
  - 每次 Agent 执行都有统一 `trace_id`
  - 每次 LLM 工具调用都能被审计和回放
  - 结果可以保存到现有 `WorkflowResult`

#### T2.8 当前实现细节

- 已更新文件：
  - `core/models.py`
  - `core/__init__.py`
- 已创建文件：
  - `scripts/agent_models_demo.py`
- 已实现的核心类：
  - `AgentInput`：Agent 统一输入模型，承接飞书事件、定时触发和人工命令
  - `AgentDecision`：路由决策模型，记录目标工作流、置信度、原因、允许工具和幂等键
  - `WorkflowContext`：工作流上下文模型，聚合会议、日历事件、妙记、任务、项目记忆和相关资源
  - `AgentToolCall`：LLM 请求调用工具时的统一内部结构，后续由 `LLMProvider` 生成
  - `AgentToolResult`：工具执行结果模型，保留给 LLM 看的内容、结构化数据、错误信息和证据引用
  - `AgentMessage`：Agent Loop 消息模型，统一表示 system / user / assistant / tool 消息
  - `AgentLoopState`：LLM 多轮工具调用状态，记录轮数、消息列表、待执行工具、工具结果和停止原因
  - `AgentRunResult`：Agent 一次完整运行结果，记录最终回答、产物、副作用、下一步动作和 loop 状态
- 已实现的辅助方法：
  - `AgentToolResult.is_success()`：判断工具调用是否成功，便于后续 Agent Loop 做分支处理
  - `AgentLoopState.append_message()`：追加一条 loop 消息，避免调用方直接操作内部列表
  - `AgentLoopState.append_tool_result()`：追加工具结果，并自动生成对应的 `tool` 消息
  - `AgentRunResult.to_workflow_result()`：把 Agent 运行结果转换成现有 `WorkflowResult`，复用当前存储层
- 运行逻辑说明：
  - 第一步，外部触发源先被封装为 `AgentInput`
  - 第二步，后续 `WorkflowRouter` 会把 `AgentInput` 转换为 `AgentDecision`
  - 第三步，`WorkflowContextBuilder` 会基于事件和飞书资源构建 `WorkflowContext`
  - 第四步，`MeetFlowAgentLoop` 会用 `AgentMessage`、`AgentToolCall`、`AgentToolResult` 记录 LLM 多轮工具调用过程
  - 第五步，整次运行结束后封装为 `AgentRunResult`
  - 第六步，需要落盘时，`AgentRunResult.to_workflow_result()` 会转换成当前存储层已经支持的 `WorkflowResult`
- 当前演示脚本逻辑：
  - `scripts/agent_models_demo.py` 构造一条 `meeting.soon` 输入
  - 模拟路由到 `pre_meeting_brief`
  - 构造一个相关飞书文档 `Resource`
  - 模拟一次 `LLM -> docs.fetch_resource -> tool result` 的 loop 状态
  - 最后打印完整 `AgentRunResult` 和转换后的 `WorkflowResult`
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/models.py core/__init__.py scripts/agent_models_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_models_demo.py` 验证模型可实例化、可递归序列化、可转换为 `WorkflowResult`
- 这一步对后续任务的意义：
  - T2.9 可以直接基于 `AgentToolCall` 和 `AgentMessage` 封装 LLM Provider
  - T2.10 可以直接基于 `AgentToolCall` 和 `AgentToolResult` 实现 Tool Registry
  - T2.13 可以直接基于 `AgentLoopState` 实现真正的 LLM Agent Loop

### T2.9 封装 LLM Provider 与 Tool Calling 协议

- 优先级：`P0`
- 目标：把模型调用从业务工作流中独立出来，为 Agent Loop 提供统一的 LLM 接口
- 建议实现：
  - `LLMProvider`：统一封装模型调用、温度、最大 token、超时和重试
  - `LLMResponse`：统一解析模型文本、结构化输出、tool_calls 和 finish_reason
  - `ToolCallRequest`：把不同模型返回的工具调用格式转成内部统一格式
  - `GenerationSettings`：从配置读取模型名、temperature、max_tokens、reasoning_effort 等参数
- 运行逻辑：
  - 第一步，`MeetFlowAgentLoop` 把当前消息列表和工具 schema 交给 `LLMProvider`
  - 第二步，`LLMProvider` 调用具体模型服务
  - 第三步，如果模型返回 `tool_calls`，转换成内部 `AgentToolCall`
  - 第四步，如果模型返回最终内容，转换成 Agent 的结构化结果草稿
- 验收标准：
  - 可以在不接飞书工具的情况下完成一次纯 LLM 调用
  - 可以解析模型返回的工具调用请求
  - 模型调用失败时返回可解释错误，不让工作流静默失败

#### T2.9 当前实现细节

- 已创建文件：
  - `core/llm.py`
  - `scripts/llm_provider_demo.py`
  - `scripts/deepseek_llm_live_test.py`
- 已更新文件：
  - `core/__init__.py`
  - `config/loader.py`
  - `config/settings.example.json`
  - `config/README.md`
- 已实现的核心类：
  - `GenerationSettings`：单次模型生成参数，包含模型名、temperature、max_tokens、reasoning_effort 和超时时间
  - `ToolDefinition`：提供给 LLM 的工具定义，可校验工具名并转换为 OpenAI-compatible tool schema
  - `LLMResponse`：模型响应统一结构，包含文本内容、工具调用、finish_reason、usage 和原始响应
  - `LLMProvider`：模型 Provider 抽象基类，后续 Agent Loop 只依赖这个统一接口
  - `OpenAICompatibleProvider`：基于 `/chat/completions` 协议的真实模型调用实现
  - `DryRunLLMProvider`：不访问网络的本地 provider，用于无 API Key 时验证 Agent 数据流
  - `LLMConfigError`：配置缺失或 provider 不支持时抛出的错误
  - `LLMAPIError`：HTTP、网络、JSON 解析等模型调用异常的统一错误
- 已实现的核心函数：
  - `create_llm_provider()`：根据配置创建 `OpenAICompatibleProvider` 或 `DryRunLLMProvider`
  - `settings_from_config()`：把 `LLMSettings` 转换成单次 `GenerationSettings`
  - `ToolDefinition.validate_name()`：提前校验工具名是否符合 OpenAI-compatible / DeepSeek 函数命名规则
  - `_agent_message_to_openai()`：把内部 `AgentMessage` 转成 OpenAI-compatible message
  - `_agent_tool_call_to_openai()`：把内部 `AgentToolCall` 转成 OpenAI-compatible tool call
  - `_parse_openai_response()`：解析 OpenAI-compatible 响应并生成 `LLMResponse`
  - `_parse_openai_tool_call()`：解析模型返回的单个 tool call，并转换为 `AgentToolCall`
- 配置变化：
  - `LLMSettings` 新增 `reasoning_effort`
  - `settings.example.json` 新增 `llm.reasoning_effort`
  - 环境变量新增 `MEETFLOW_LLM_REASONING_EFFORT`
  - `config/README.md` 补充了 LLM 相关环境变量
- 运行逻辑说明：
  - 第一步，业务代码调用 `create_llm_provider(settings.llm)` 创建 provider
  - 第二步，`MeetFlowAgentLoop` 后续会把 `AgentMessage[]` 和 `ToolDefinition[]` 传给 `provider.chat()`
  - 第三步，`OpenAICompatibleProvider` 会将内部消息和工具定义转换为 OpenAI-compatible 请求体
  - 第四步，模型返回后，provider 将响应统一转换为 `LLMResponse`
  - 第五步，如果 `LLMResponse.should_execute_tools` 为 true，后续 T2.10 / T2.13 会进入工具执行阶段
  - 第六步，如果没有工具调用，Agent Loop 可以直接把 `content` 当作最终文本或结构化结果草稿
- 当前演示脚本逻辑：
  - `scripts/llm_provider_demo.py --provider dry-run --mode tool` 会模拟模型请求调用 `docs.fetch_resource`
  - `scripts/llm_provider_demo.py --provider dry-run --mode text` 会模拟模型直接返回文本
  - `--provider configured` 会使用配置中的真实模型服务，但需要先配置 `MEETFLOW_LLM_API_BASE` 和 `MEETFLOW_LLM_API_KEY`
  - `scripts/deepseek_llm_live_test.py` 会真实调用 DeepSeek API，默认读取 `DEEPSEEK_API_KEY`
- 当前验证方式：
  - 已通过 `python3 -m py_compile config/loader.py core/llm.py core/__init__.py scripts/llm_provider_demo.py` 验证语法正确
  - 已通过 `python3 scripts/llm_provider_demo.py --provider dry-run --mode tool` 验证工具调用响应结构
  - 已通过 `python3 scripts/llm_provider_demo.py --provider dry-run --mode text --prompt 测试普通回复` 验证普通文本响应结构
  - 已通过本地 OpenAI-compatible 样例响应验证 `_parse_openai_response()` 能正确解析 tool call
  - 已根据 DeepSeek 真实报错修复工具名兼容性：LLM 暴露工具名必须使用 `calendar_list_events` 这类格式，不能使用 `calendar.list_events`
- 这一步对后续任务的意义：
  - T2.10 的 Tool Registry 可以直接使用 `ToolDefinition` 暴露工具 schema
  - T2.10 需要负责维护内部工具名和 LLM 工具名之间的映射，例如内部 `calendar.list_events` 映射到 LLM 可见的 `calendar_list_events`
  - T2.13 的 MeetFlowAgentLoop 可以直接调用 `LLMProvider.chat()` 完成每轮 LLM 推理
  - 真实模型和 dry-run 模型使用同一个接口，后续本地测试和线上调用不会分叉

### T2.10 实现 Tool Registry

- 优先级：`P0`
- 目标：把 M2 已完成的飞书能力注册成 Agent 可调用工具，而不是让工作流直接散落调用 `FeishuClient`
- 首批工具建议：
  - `calendar.list_events`
  - `docs.fetch_resource`
  - `minutes.fetch_resource`
  - `tasks.list_my_tasks`
  - `tasks.create_task`
  - `im.send_text`
  - `im.send_card`
- 验收标准：
  - 可以通过工具名调用具体方法
  - 可以向 LLM 暴露工具名称、描述和 JSON Schema 参数
  - 工具有统一入参、出参和错误包装
  - 工具调用可记录日志和 trace_id

#### T2.10 当前实现细节

- 已创建文件：
  - `core/tools.py`
  - `adapters/feishu_tools.py`
  - `scripts/tool_registry_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `adapters/__init__.py`
- 已实现的核心类：
  - `AgentTool`：单个 Agent 工具定义，包含内部工具名、LLM 工具名、描述、参数 schema、处理函数、是否只读和副作用类型
  - `ToolRegistry`：工具注册器，负责注册工具、查询工具、生成 LLM tool definitions、执行 `AgentToolCall`
  - `ToolRegistryError`：工具注册器通用异常
  - `ToolNotFoundError`：LLM 请求未注册工具时的异常
  - `ToolParameterError`：工具参数缺失或不合法时的异常
- 已实现的核心函数：
  - `make_llm_tool_name()`：把内部工具名转换成 DeepSeek / OpenAI-compatible 兼容工具名，例如 `calendar.list_events` -> `calendar_list_events`
  - `validate_llm_tool_name()`：校验 LLM 工具名是否只包含字母、数字、下划线和连字符
  - `serialize_tool_result()`：把工具返回的 `BaseModel`、列表、字典等转换成可 JSON 序列化的数据
  - `build_tool_result_content()`：生成喂回 LLM 的简短工具结果摘要
  - `create_feishu_tool_registry()`：创建首批飞书工具注册器
- 当前已注册的飞书工具：
  - `calendar.list_events` -> LLM 可见名 `calendar_list_events`
  - `docs.fetch_resource` -> LLM 可见名 `docs_fetch_resource`
  - `minutes.fetch_resource` -> LLM 可见名 `minutes_fetch_resource`
  - `tasks.list_my_tasks` -> LLM 可见名 `tasks_list_my_tasks`
  - `tasks.create_task` -> LLM 可见名 `tasks_create_task`
  - `im.send_text` -> LLM 可见名 `im_send_text`
  - `im.send_card` -> LLM 可见名 `im_send_card`
- 运行逻辑说明：
  - 第一步，业务启动时调用 `create_feishu_tool_registry(client, default_chat_id)`
  - 第二步，注册器把飞书客户端方法包装成 `AgentTool`
  - 第三步，`ToolRegistry.get_definitions()` 生成可传给 `LLMProvider.chat()` 的 `ToolDefinition[]`
  - 第四步，LLM 返回 `AgentToolCall` 后，`ToolRegistry.execute()` 根据 `tool_name` 找到对应工具
  - 第五步，工具先做 required 参数校验，再调用真实 handler
  - 第六步，工具结果统一包装为 `AgentToolResult`，成功时包含结构化 `data`，失败时包含 `error_message`
- 当前演示脚本逻辑：
  - `scripts/tool_registry_demo.py --mode list-feishu` 会列出所有飞书工具和暴露给 LLM 的 tool definitions，不调用飞书 API
  - `scripts/tool_registry_demo.py --mode execute-demo` 会执行本地 `demo_echo` 工具，验证 `AgentToolCall -> AgentToolResult` 链路
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/tools.py core/__init__.py adapters/feishu_tools.py adapters/__init__.py scripts/tool_registry_demo.py` 验证语法正确
  - 已通过 `python3 scripts/tool_registry_demo.py --mode execute-demo --message 测试工具注册器` 验证本地工具执行成功
  - 已通过 `python3 scripts/tool_registry_demo.py --mode list-feishu` 验证首批飞书工具 schema 可正常生成，且 LLM 工具名不含点号
- 这一步对后续任务的意义：
  - T2.11 的 `WorkflowRouter` 可以在 `AgentDecision.required_tools` 中使用内部工具名，例如 `calendar.list_events`
  - T2.13 的 `MeetFlowAgentLoop` 可以把 `ToolRegistry.get_definitions(required_tools)` 交给 LLM，再把 LLM 返回的 `AgentToolCall` 交给 `ToolRegistry.execute()`
  - T2.15 的 `AgentPolicy` 可以根据 `AgentTool.read_only` 和 `side_effect` 决定写操作是否需要确认

### T2.11 实现 Workflow Router

- 优先级：`P0`
- 目标：根据事件类型或人工命令选择业务工作流
- 路由规则：
  - `meeting.soon` -> `pre_meeting_brief`
  - `minute.ready` -> `post_meeting_followup`
  - `risk.scan.tick` -> `risk_scan`
  - `message.command` -> `manual_command`
- 验收标准：
  - 输入 `AgentInput` 能稳定输出 `AgentDecision`
  - 未知事件能返回明确的 `unsupported` 决策
  - 决策结果包含原因和幂等键
  - 决策结果包含本次业务场景允许暴露给 LLM 的工具名单

#### T2.11 当前实现细节

- 已创建文件：
  - `core/router.py`
  - `scripts/workflow_router_demo.py`
- 已更新文件：
  - `core/__init__.py`
- 已实现的核心类：
  - `RouteRule`：单条路由规则，描述事件类型、目标工作流、原因、允许工具、置信度和状态
  - `WorkflowRouter`：工作流路由器，把 `AgentInput` 转换成 `AgentDecision`
  - `WorkflowRouterError`：路由器通用异常，预留给后续复杂路由校验使用
- 已实现的核心函数：
  - `build_default_route_rules()`：构建首版默认路由规则
  - `build_idempotency_key()`：根据 workflow_type、事件 ID、会议 ID、妙记 token、任务 ID 或 payload hash 生成稳定幂等键
  - `build_agent_input()`：构造 `AgentInput`，方便脚本和后续测试复用
- 当前默认路由规则：
  - `meeting.soon` -> `pre_meeting_brief`
  - `minute.ready` -> `post_meeting_followup`
  - `risk.scan.tick` -> `risk_scan`
  - `message.command` -> `manual_qa`，也可以通过 payload 指定 `workflow_type`
- 当前工具集约束：
  - `pre_meeting_brief` 默认允许 `calendar.list_events`、`docs.fetch_resource`、`minutes.fetch_resource`、`tasks.list_my_tasks`、`im.send_card`
  - `post_meeting_followup` 默认允许 `minutes.fetch_resource`、`docs.fetch_resource`、`tasks.create_task`、`im.send_card`
  - `risk_scan` 默认允许 `tasks.list_my_tasks`、`calendar.list_events`、`im.send_card`
  - `manual_qa` 默认允许 `calendar.list_events`、`docs.fetch_resource`、`minutes.fetch_resource`、`tasks.list_my_tasks`
- 运行逻辑说明：
  - 第一步，触发源先构造 `AgentInput`
  - 第二步，`WorkflowRouter.route()` 根据 `event_type` 查找 `RouteRule`
  - 第三步，如果是 `message.command`，允许 payload 覆盖目标 `workflow_type`
  - 第四步，路由器解析本次允许暴露给 LLM 的内部工具名列表
  - 第五步，路由器生成稳定 `idempotency_key`
  - 第六步，输出 `AgentDecision`
  - 第七步，如果事件未知，不抛异常，而是返回 `workflow_type=unsupported`、`status=unsupported`
- 当前演示脚本逻辑：
  - `scripts/workflow_router_demo.py --event-type meeting.soon --meeting-id meeting_001` 模拟会前路由
  - `scripts/workflow_router_demo.py --event-type minute.ready --minute-token minute_001` 模拟会后路由
  - `scripts/workflow_router_demo.py --event-type risk.scan.tick --trigger-type schedule` 模拟定时风险巡检
  - `scripts/workflow_router_demo.py --event-type message.command --workflow-type risk_scan` 模拟人工命令指定工作流
  - `scripts/workflow_router_demo.py --event-type unknown.event` 模拟未知事件降级
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/router.py core/__init__.py scripts/workflow_router_demo.py` 验证语法正确
  - 已验证 `meeting.soon` 能路由到 `pre_meeting_brief` 并生成会前工具集
  - 已验证 `minute.ready` 能路由到 `post_meeting_followup` 并生成会后工具集
  - 已验证 `risk.scan.tick` 能路由到 `risk_scan` 并生成风险巡检工具集
  - 已验证 `message.command` 可以指定 `workflow_type=risk_scan`
  - 已验证未知事件会返回 `unsupported` 决策而不是中断程序
- 这一步对后续任务的意义：
  - T2.12 可以基于 `AgentDecision.workflow_type` 构建对应 `WorkflowContext`
  - T2.13 可以把 `AgentDecision.required_tools` 传给 `ToolRegistry.get_definitions()`，从而限制 LLM 可见工具范围
  - T2.15 可以基于 `AgentDecision.status` 和 `workflow_type` 决定是否允许继续执行写操作

### T2.12 实现 Workflow Context Builder

- 优先级：`P0`
- 目标：根据事件构建工作流上下文，避免每个工作流重复解析 payload
- 核心能力：
  - 从会议事件中解析 `meeting_id`、`calendar_event_id`、参与人和时间窗口
  - 从妙记事件中解析 `minute_token`
  - 从任务事件中解析 `task_id`
  - 从配置或项目记忆中解析 `project_id`
  - 聚合可用的飞书资源和本地记忆快照
- 验收标准：
  - M3-M5 只依赖 `WorkflowContext`，不直接依赖原始事件 payload
  - 上下文中保留原始事件，便于调试和回放
  - 上下文可以被转换成 LLM runtime context，不需要模型理解原始飞书响应体

#### T2.12 当前实现细节

- 已创建文件：
  - `core/context.py`
  - `scripts/workflow_context_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `core/router.py`
- 已实现的核心类：
  - `WorkflowContextBuilder`：工作流上下文构建器，把 `AgentInput + AgentDecision` 转换成统一 `WorkflowContext`
  - `WorkflowContextError`：上下文构建异常，预留给后续严格校验使用
- 已实现的核心函数：
  - `build_event_from_agent_input()`：把 `AgentInput` 转换成统一 `Event`
  - `extract_meeting_id()`：从 payload 中解析会议 ID
  - `extract_calendar_event_id()`：从 payload 中解析日历事件 ID
  - `extract_minute_token()`：从 payload 中解析妙记 token
  - `extract_task_id()`：从 payload 中解析任务 ID
  - `extract_project_id()`：从 payload 中解析项目 ID，没有则使用默认项目
  - `extract_participants()`：从 payload 中解析参与人列表
  - `extract_related_resources()`：从 payload 中解析已有资源线索并转换为 `Resource`
  - `resource_from_payload()`：把资源字典转换成统一 `Resource`
  - `first_string()`：按多个候选字段读取第一个非空字符串
- 当前上下文构建边界：
  - `WorkflowContextBuilder` 只解析已有 payload 和本地项目记忆
  - 不主动调用飞书 API
  - 不主动做文档、妙记或任务召回
  - 真正的资源读取留给后续 `ToolRegistry + MeetFlowAgentLoop`
- 运行逻辑说明：
  - 第一步，外部触发源构造 `AgentInput`
  - 第二步，`WorkflowRouter` 输出 `AgentDecision`
  - 第三步，`WorkflowContextBuilder.build()` 读取 payload 中的会议、日历事件、妙记、任务和项目字段
  - 第四步，构造标准 `Event`，保存在 `WorkflowContext.event`
  - 第五步，解析参与人和已有资源线索
  - 第六步，如果配置了 `MeetFlowStorage`，则读取 `storage/projects/{project_id}.json` 作为 `memory_snapshot`
  - 第七步，把 `agent_input`、`decision` 和原始 payload 放入 `raw_context`，方便调试和回放
- 当前演示脚本逻辑：
  - `scripts/workflow_context_demo.py --event-type meeting.soon --meeting-id meeting_001 --calendar-event-id event_001 --with-memory` 模拟会前上下文，并写入/读取项目记忆
  - `scripts/workflow_context_demo.py --event-type minute.ready --minute-token minute_001 --project-id meetflow` 模拟会后上下文
  - `scripts/workflow_context_demo.py --event-type risk.scan.tick --task-id task_001 --project-id meetflow` 模拟风险巡检上下文
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/router.py core/context.py core/__init__.py scripts/workflow_context_demo.py` 验证语法正确
  - 已验证会前场景可解析 `meeting_id`、`calendar_event_id`、参与人、相关资源和项目记忆
  - 已验证会后场景可解析 `minute_token`，并生成 `post_meeting_followup:minute_001` 幂等键
  - 已验证风险场景可解析 `task_id`，并生成 `risk_scan:task_001` 幂等键
- 这一步对后续任务的意义：
  - T2.13 可以直接把 `WorkflowContext` 转成 LLM runtime context
  - M3-M5 工作流不需要再解析原始 payload，只依赖 `WorkflowContext`
  - 后续事件订阅接入时，只需要把飞书事件 payload 填进 `AgentInput.payload`

### T2.13 实现 MeetFlowAgentLoop 主循环

- 优先级：`P0`
- 目标：实现真正的 Agent Loop，让 LLM 基于上下文选择工具、读取工具结果并产出最终结构化结果
- 设计边界：
  - `MeetFlowAgentLoop` 是工作流中的 LLM 槽位，不负责完整业务流程从头到尾的所有步骤
  - loop 输入必须由上游 `WorkflowContextBuilder` 和 Workflow Runner 准备，不能要求模型直接解析原始飞书 payload
  - loop 输出是结构化结果草稿或最终回答，后续仍需经过确定性 validator 和 `AgentPolicy`
- 主流程：
  - 接收 `WorkflowContext`、允许工具集和工作流目标
  - 组装 system prompt、runtime context 和历史消息
  - 调用 `LLMProvider`
  - 如果模型返回工具调用，则通过 `ToolRegistry` 执行工具
  - 将 `AgentToolResult` 追加为 tool 消息
  - 继续下一轮 LLM 调用
  - 模型输出最终结果、达到最大轮数或触发策略拦截时结束
- 验收标准：
  - 能完成至少一次“LLM -> 工具 -> LLM -> 最终结果”的循环
  - 支持最大轮数限制，避免无限循环
  - 每轮模型调用和工具调用都能落审计日志
  - 工具执行失败时，LLM 可以收到错误摘要并尝试降级

#### T2.13 当前实现细节

- 已创建文件：
  - `core/agent_loop.py`
  - `scripts/agent_loop_demo.py`
- 已更新文件：
  - `core/__init__.py`
  - `core/llm.py`
- 已实现的核心类：
  - `MeetFlowAgentLoop`：MeetFlow 垂直 Agent 的主循环，负责把上下文交给 LLM、执行模型选择的工具、再把工具结果反馈给 LLM
  - `AgentLoopError`：Agent Loop 预留异常类型，方便后续扩展策略拦截、工具异常升级等场景
- 已实现的核心函数：
  - `MeetFlowAgentLoop.run()`：执行完整 loop，直到模型给出最终答案、达到最大轮数或发生异常
  - `MeetFlowAgentLoop._build_initial_state()`：构造 `AgentLoopState`，并追加 system / user 初始消息
  - `MeetFlowAgentLoop._handle_tool_calls()`：执行 LLM 返回的工具调用，并把 `AgentToolResult` 追加为 tool 消息
  - `MeetFlowAgentLoop._build_run_result()`：把 loop 状态转换为统一 `AgentRunResult`
  - `build_system_prompt()`：生成垂直 Agent 系统提示词，约束它必须基于工具和上下文回答
  - `build_runtime_context_message()`：把 `WorkflowContext` 压缩成 LLM 可读的 JSON 上下文
  - `collect_side_effects()`：收集本次 loop 中已经执行过的写操作工具，便于后续审计和策略检查
  - `build_result_summary()`：生成 `AgentRunResult.summary`
- 已更新的 LLM dry-run 行为：
  - `DryRunLLMProvider.chat()` 如果还没有工具结果，会模拟模型请求第一个工具
  - 如果消息里已经出现 tool 结果，会模拟模型产出最终回答
  - 这样可以在没有真实模型 API Key 的情况下验证完整 “LLM -> 工具 -> LLM” 链路
- 当前 Agent Loop 运行逻辑：
  - 第一步，外部传入 `WorkflowContext`、本次允许工具列表和工作流目标
  - 第二步，`MeetFlowAgentLoop` 创建 `AgentLoopState`，写入 `trace_id`、`workflow_type`、最大轮数和初始消息
  - 第三步，通过 `ToolRegistry.get_definitions(required_tools)` 只把本次工作流允许的工具暴露给 LLM
  - 第四步，调用 `LLMProvider.chat()`，让 LLM 基于上下文决定是否调用工具
  - 第五步，如果 LLM 返回 `tool_calls`，则通过 `ToolRegistry.execute()` 执行工具
  - 第六步，工具执行结果会以 `AgentToolResult` 的形式进入 `AgentLoopState.tool_results`，同时被追加为 tool 消息
  - 第七步，下一轮 LLM 可以读取 tool 消息，继续调用工具或输出最终答案
  - 第八步，如果 LLM 输出最终文本，loop 返回 `status=success` 的 `AgentRunResult`
  - 第九步，如果超过 `max_iterations` 仍没有最终答案，loop 返回 `status=max_iterations`，避免无限循环
  - 第十步，如果中途异常，loop 返回 `status=failed`，并把错误类型与错误信息放入 payload，方便排查
- 当前日志与可观测性：
  - 每轮 loop 开始都会记录 `trace_id`、`workflow_type`、`iteration`
  - 工具调用本身沿用 T2.10 `ToolRegistry` 的工具执行日志
  - 最终结果中保留完整 `loop_state`，可以回放消息、工具调用和工具结果
- 当前演示脚本逻辑：
  - `scripts/agent_loop_demo.py` 构造一个 `meeting.soon` 事件
  - 先经过 `WorkflowRouter` 生成 `AgentDecision`
  - 再经过 `WorkflowContextBuilder` 生成 `WorkflowContext`
  - 然后创建一个本地 demo 工具 `demo.fetch_context`
  - 最后使用 `DryRunLLMProvider + ToolRegistry + MeetFlowAgentLoop` 跑完整循环
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/agent_loop.py core/llm.py core/__init__.py scripts/agent_loop_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_loop_demo.py --event-type meeting.soon --meeting-id meeting_loop_demo` 验证完整 “LLM -> 工具 -> LLM -> 最终结果” 链路
  - 已通过 `python3 scripts/agent_loop_demo.py --event-type meeting.soon --meeting-id meeting_loop_demo --max-iterations 1` 验证最大轮数保护生效
- 这一步对后续任务的意义：
  - T2.14 可以把 `WorkflowRouter`、`WorkflowContextBuilder`、`MeetFlowAgentLoop` 串成真正的业务 Agent 主入口
  - M3 会前卡片、M4 会后任务、M5 风险巡检都可以复用同一个 Agent Loop
  - 后续只需要替换真实 LLM Provider 和真实飞书工具注册器，就能从 dry-run demo 迁移到真实业务执行

### T2.14 实现 MeetFlowAgent 主入口

- 优先级：`P0`
- 目标：实现业务侧垂直 Agent 的统一入口，把路由、上下文、LLM loop、策略和结果保存串起来
- 设计边界：
  - `MeetFlowAgent` 负责串联路由、上下文、工作流骨架和 Agent Loop，不把所有业务细节都写进主入口
  - M3-M5 应逐步引入具体 Workflow Runner，例如 `PreMeetingBriefWorkflow`、`PostMeetingFollowupWorkflow`、`RiskScanWorkflow`
  - 每个 Workflow Runner 固定流程阶段、允许工具、输出校验和副作用处理方式
- 主流程：
  - 接收 `AgentInput`
  - 生成并绑定 `trace_id`
  - 调用 `WorkflowRouter` 生成决策
  - 通过 `WorkflowContextBuilder` 构建上下文
  - 调用 `MeetFlowAgentLoop` 执行受控工具推理
  - 调用对应工作流处理器完成卡片渲染、任务写入等业务封装
  - 保存 `AgentRunResult` 和 `WorkflowResult`
  - 对失败场景记录错误并返回可解释结果
- 验收标准：
  - 可以用脚本模拟一次 `meeting.soon` 事件并完成路由
  - 可以用脚本模拟一次 `minute.ready` 事件并完成路由
  - 失败时不会静默吞错，有明确状态和错误原因

#### T2.14 当前实现细节

- 已创建文件：
  - `core/agent.py`
  - `scripts/meetflow_agent_live_test.py`
- 已更新文件：
  - `core/__init__.py`
  - `adapters/feishu_client.py`
  - `adapters/feishu_tools.py`
  - `core/tools.py`
  - `tasks.md`
- 已实现的核心类：
  - `MeetFlowAgent`：业务侧垂直 Agent 主入口，统一串联路由、上下文、LLM Loop、工具注册器和本地存储
  - `MeetFlowAgentError`：Agent 主入口异常类型，预留给后续更严格的错误分层
  - `ScriptedCalendarProvider`：live test 脚本里的脚本化 Provider，用于不依赖真实 LLM 时稳定触发一次日历工具调用
- 已实现的核心函数：
  - `MeetFlowAgent.run()`：执行一次完整 Agent 运行，从 `AgentInput` 到 `AgentRunResult`
  - `MeetFlowAgent._filter_required_tools()`：按 `allow_write` 过滤工具，默认不把发消息、建任务等写工具暴露给 LLM
  - `MeetFlowAgent._is_duplicate()`：检查幂等键是否已处理，避免真实事件重复执行
  - `MeetFlowAgent._mark_idempotency()`：在成功或达到最大轮数时记录幂等键
  - `MeetFlowAgent._save_result()`：把 `AgentRunResult` 转成 `WorkflowResult` 并保存
  - `create_meetflow_agent()`：根据系统配置装配 `FeishuClient`、`ToolRegistry`、`LLMProvider`、`WorkflowRouter`、`WorkflowContextBuilder` 和 `MeetFlowAgentLoop`
  - `scripts/meetflow_agent_live_test.py::build_payload()`：为真实测试构造包含日历窗口、项目 ID、工具名单的 payload
  - `scripts/meetflow_agent_live_test.py::build_llm_settings()`：从 `llm_providers.local.json`、环境变量或默认配置中读取模型配置，但不会打印 API Key
  - `scripts/meetflow_agent_live_test.py::print_result()`：默认只打印摘要、最终回答和工具结果，避免输出过多敏感上下文
  - `scripts/meetflow_agent_live_test.py::save_token_bundle()`：当飞书用户 token 被自动刷新时，把新的 access_token / refresh_token 回写到本地配置
- 已补充的飞书 token 持久化能力：
  - `FeishuClient` 新增 `user_token_callback`
  - `refresh_user_access_token()` 自动刷新成功后会触发回调
  - `poll_device_token()` 登录成功后也会触发回调
  - live test 脚本通过该回调写入 `config/settings.local.json`
  - 这样可以避免飞书一次性 refresh_token 被使用后没有保存新 token，导致下一次调用报 `20064 refresh token revoked`
- 已修复的工具结果可读性问题：
  - 问题现象：真实 DeepSeek 调用了 `calendar.list_events`，飞书也返回了 1 条会议，但第二轮 LLM 只能看到“返回 1 条记录”，看不到会议标题、时间和参与人
  - 根因：`ToolRegistry` 把结构化数据保存在 `AgentToolResult.data`，但喂回 LLM 的 tool message `content` 只包含简短摘要
  - 修复：`core/tools.py::build_tool_result_content()` 现在会返回“简短摘要 + 结构化数据 JSON”
  - 效果：LLM 第二轮推理可以直接读取 `items[].summary`、`start_time`、`end_time`、`attendees` 等字段并生成准确总结
- 当前 Agent 主入口运行逻辑：
  - 第一步，调用 `bind_trace_id()` 生成并绑定本次运行的 `trace_id`
  - 第二步，`WorkflowRouter.route()` 根据 `AgentInput.event_type` 生成 `AgentDecision`
  - 第三步，如果路由结果不是 ready，则直接返回 unsupported / skipped 等终态结果
  - 第四步，如果开启幂等，先用 `MeetFlowStorage.is_idempotency_key_processed()` 判断是否重复
  - 第五步，通过 `WorkflowContextBuilder.build()` 构造统一 `WorkflowContext`
  - 第六步，按 `allow_write` 过滤工具，默认只保留只读工具
  - 第七步，根据 `workflow_type` 选择 `WorkflowRunner`，进入确定性工作流骨架
  - 第八步，`WorkflowRunner` 执行 `prepare_context -> build_plan_or_query -> agent_loop -> validate_output -> persist_and_audit`，其中 `agent_loop` 阶段调用 `MeetFlowAgentLoop.run()`
  - 第九步，把 `AgentDecision`、最终生效工具列表和 `workflow_runner` 骨架信息写入 `AgentRunResult.payload`
  - 第十步，如果启用幂等且执行成功，记录幂等键
  - 第十一步，把结果保存到本地 `workflow_results`
  - 第十二步，无论成功失败，最后调用 `reset_trace_id()` 清理上下文，避免日志串号
- 已补充的确定性工作流骨架能力：
  - 新增 `core/workflows.py`
  - `WorkflowSpec`：描述工作流类型、允许工具、目标、输出 schema、写操作开关和校验规则
  - `WorkflowValidationResult`：记录确定性校验结果
  - `WorkflowRunner`：通用工作流骨架，固定准备上下文、调用 Agent Loop、校验输出和写入审计 payload
  - `PreMeetingBriefWorkflow`：会前工作流骨架，当前会构造 `retrieval_query_draft`，并把“证据不足时不能写成确定事实”等约束追加到 Agent 目标中
  - `PostMeetingFollowupWorkflow`：会后工作流骨架，当前会构造 `post_meeting_plan`，固定“读取妙记/纪要 -> 清洗 -> 抽取 Action Items -> 校验字段和证据 -> Policy 决定创建任务或待确认”的阶段边界
  - `RiskScanWorkflow`：风险巡检工作流骨架，当前会构造 `risk_scan_plan`，固定“读取任务状态 -> 风险规则预筛 -> Agent 生成提醒草案 -> 去重/降噪 -> Policy 决定是否推送”的阶段边界
  - `build_default_workflow_runners()`：提供默认 Runner 注册表，`pre_meeting_brief`、`post_meeting_followup`、`risk_scan` 都使用专用 Runner，其他工作流先使用通用 Runner
- 当前边界与待补事项：
  - 当前三个专用 Runner 仍然是骨架级代码，不等于 M3/M4/M5 业务功能已经完成
  - `PostMeetingFollowupWorkflow` 还没有实现真实纪要清洗、严格 `MeetingSummary` / `ActionItem` schema 解析和会后卡片渲染，这些仍属于 M4
  - `RiskScanWorkflow` 还没有实现真实风险规则、历史提醒降噪和风险卡片渲染，这些仍属于 M5
  - 写操作仍必须经过 `AgentPolicy`，专用 Runner 只负责固定阶段和校验边界，不直接绕过策略执行副作用
- 已补充验证脚本：
  - `scripts/workflow_runner_demo.py`
  - 脚本使用本地工具和 `ScriptedDebugProvider`，不访问真实飞书和真实 LLM
  - 能验证 `MeetFlowAgent -> PreMeetingBriefWorkflow -> MeetFlowAgentLoop -> ToolRegistry` 的完整链路
  - 输出会包含 `workflow_runner.stages`、`retrieval_query_draft`、`tool_results` 和最终回答
- 当前新增验证方式：
  - 已通过 `python3 -m py_compile core/*.py scripts/workflow_runner_demo.py scripts/agent_demo.py scripts/meetflow_agent_live_test.py` 验证语法正确
  - 已通过 `python3 scripts/workflow_runner_demo.py` 验证会前工作流骨架、检索计划草案和本地工具调用成功
  - 已通过 `python3 scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 3 --show-full` 验证原有手动调试入口仍可运行，并能在 payload 中看到 `workflow_runner` 和 `retrieval_query_draft`
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario missing_task_fields` 验证写操作仍会经过 `AgentPolicy` 拦截
- 当前真实测试脚本能力：
  - 默认 `--llm-provider scripted_calendar`：不调用真实 LLM，但会走完整 Agent Loop，并真实调用飞书日历 API
  - 可切换 `--llm-provider deepseek`：使用 DeepSeek 等 OpenAI-compatible 模型进行真实 tool calling
  - 默认只开放 `calendar.list_events`
  - 可通过多个 `--tool` 显式开放更多工具
  - 默认不开放写工具
  - 只有传入 `--allow-write` 时，LLM 才能看到并调用 `im.send_card`、`tasks.create_task` 这类写工具
  - 默认不启用幂等，方便本地反复测试
  - 传入 `--enable-idempotency` 后，会记录并检查幂等键，更接近真实事件订阅模式
- 当前推荐测试命令：
  - 快速验证 Agent 主入口和真实飞书日历链路：
    `python3 scripts/meetflow_agent_live_test.py --llm-provider scripted_calendar --max-iterations 3`
  - 指定时间窗口查询日历：
    `python3 scripts/meetflow_agent_live_test.py --llm-provider scripted_calendar --start-time 1777132800 --end-time 1777219200`
  - 使用真实 DeepSeek 模型驱动工具选择：
    `DEEPSEEK_API_KEY=你的key python3 scripts/meetflow_agent_live_test.py --llm-provider deepseek --tool calendar.list_events --prompt "请查询我今天的会议安排，并总结时间、标题和参与人。"`
  - 测试写工具前需要显式开放：
    `python3 scripts/meetflow_agent_live_test.py --llm-provider deepseek --tool im.send_card --allow-write --prompt "向测试群发送一张 MeetFlow 连通性测试卡片。"`
- 当前验证结果：
  - 已通过 `python3 -m py_compile core/agent.py core/__init__.py adapters/feishu_tools.py scripts/meetflow_agent_live_test.py` 验证语法正确
  - 已通过 `python3 scripts/meetflow_agent_live_test.py --llm-provider dry_run --max-iterations 2` 验证主入口错误降级链路
  - 已通过 `python3 scripts/meetflow_agent_live_test.py --llm-provider scripted_calendar --max-iterations 3` 真实调用飞书日历 API，接口返回成功，当前时间窗返回 0 条日程
  - 在重复真实测试时发现旧 refresh_token 已失效的问题，并已补齐后续自动刷新后的 token 回写逻辑
  - 已通过本地样例验证 `build_tool_result_content()` 会把日历事件详情写入 tool message，而不是只返回记录数
- 这一步对后续任务的意义：
  - 后续 M3-M5 不再只是“工作流脚本”，而是可以挂在同一个 `MeetFlowAgent` 主入口下运行
  - 真实事件订阅、定时任务、本地 CLI 都可以统一构造 `AgentInput` 调用 `MeetFlowAgent.run()`
  - LLM 的自主工具选择被限制在 `AgentDecision.required_tools` 和 `allow_write` 双重边界内，兼顾 Agent 能力与安全控制

### T2.15 实现 Agent Policy 与自动化边界

- 优先级：`P1`
- 目标：让 Agent 不只是执行流程，还能控制“哪些动作允许自动做，哪些需要确认”
- 首批策略：
  - 低置信度 Action Item 不直接创建任务
  - 缺少负责人或截止时间的任务进入待确认卡片
  - 同一会议同一时间窗口不重复发送会前卡片
  - 同一任务同一风险当天不重复提醒
  - 写操作必须支持 dry-run 或幂等键
- 验收标准：
  - M4 自动创建任务前会检查置信度和字段完整性
  - M5 风险提醒前会检查降噪窗口
  - LLM 不能直接绕过 Policy 执行写操作

#### T2.15 当前实现细节

- 已创建文件：
  - `core/policy.py`
  - `scripts/agent_policy_demo.py`
- 已更新文件：
  - `core/agent_loop.py`
  - `core/agent.py`
  - `core/__init__.py`
  - `adapters/feishu_tools.py`
  - `tasks.md`
- 已实现的核心类：
  - `AgentPolicy`：Agent 自动化边界判断器，在工具真正执行前判断是否允许自动执行
  - `AgentPolicyConfig`：策略阈值配置，包括行动项最低置信度、是否要求负责人、是否要求截止时间、写操作是否必须带幂等键
  - `PolicyDecision`：单次策略判断结果，状态包括 `allow`、`blocked`、`needs_confirmation`
  - `AgentPolicyError`：策略层异常类型，预留给后续更严格的策略错误处理
- 已实现的核心函数：
  - `AgentPolicy.authorize_tool_call()`：工具执行前的统一策略入口
  - `AgentPolicy._authorize_create_task()`：检查创建任务是否满足自动化条件
  - `AgentPolicy._authorize_risk_reminder()`：检查风险提醒是否具备幂等键和降噪基础
  - `AgentPolicy._resolve_idempotency_key()`：从工具参数或 `WorkflowContext.raw_context.decision.idempotency_key` 派生写操作幂等键
  - `AgentPolicy._is_duplicate_side_effect()`：基于本地存储检查写操作是否重复
- 已接入 Agent Loop 的位置：
  - `MeetFlowAgentLoop` 新增 `policy`、`storage`、`allow_write`
  - 每次 LLM 返回 `tool_calls` 后，执行真实工具前先调用 `AgentPolicy.authorize_tool_call()`
  - 如果策略返回 `blocked` 或 `needs_confirmation`，不会调用真实工具 handler
  - 被拦截的结果会以 `AgentToolResult` 形式喂回 LLM，让模型能解释为什么没有执行
  - 如果策略返回 `allow`，会使用 `PolicyDecision.patched_arguments` 继续执行工具
- 当前首批策略：
  - 只读工具默认允许自动执行
  - 写工具默认必须显式开启 `allow_write`
  - 写操作必须具备幂等键；如果 LLM 没传，会从工作流幂等键派生
  - 创建任务时，低于 `min_action_item_confidence` 的行动项进入待确认
  - 创建任务时，缺少 `assignee_ids` 或 `due_timestamp_ms` 的行动项进入待确认
  - 风险提醒必须带幂等键，后续才能做同一风险当天不重复提醒
  - 如果本地存储中已经存在同一幂等键，写操作会被阻止
- 已更新的飞书工具：
  - 新增 `contact.get_current_user`：读取当前登录用户信息，让 LLM 能把“我/本人/自己”解析为当前用户 open_id
  - 新增 `contact.search_user`：按姓名、邮箱或手机号搜索飞书用户，让 LLM 能把其他人的名字解析为 open_id
  - `im.send_text` 新增 `idempotency_key` 参数，并传给飞书消息接口
  - `im.send_card` 新增 `idempotency_key` 参数，并传给飞书消息接口
  - 这样消息发送也具备幂等能力，不再只是任务创建具备幂等键
- 已补充的人员解析能力：
  - `FeishuClient.search_users()` 封装 `GET /open-apis/search/v1/user`
  - `meetflow_agent_live_test.py` 中只要开放 `tasks.create_task`，就会自动补充 `contact.get_current_user` 和 `contact.search_user`
  - live test 的工作流目标会明确提示 LLM：负责人为“我”时先调用 `contact_get_current_user`；负责人为具体姓名时先调用 `contact_search_user`
  - LLM 不应把自然语言姓名直接写入 `assignee_ids`，必须使用通讯录工具返回的 open_id
- 当前演示脚本逻辑：
  - `scripts/agent_policy_demo.py --scenario missing_task_fields`：模拟 LLM 想创建缺少负责人和截止时间的任务，Policy 返回 `needs_confirmation`
  - `scripts/agent_policy_demo.py --scenario valid_task`：模拟字段完整、置信度足够的任务创建，Policy 放行，工具 handler 执行
  - `scripts/agent_policy_demo.py --scenario write_disabled`：模拟 LLM 想发送卡片但未开启写权限，Policy 返回 `blocked`
- 当前验证方式：
  - 已通过 `python3 -m py_compile core/policy.py core/agent_loop.py core/agent.py core/__init__.py adapters/feishu_tools.py scripts/agent_policy_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario missing_task_fields` 验证缺字段任务进入待确认，真实 handler 未执行
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario valid_task` 验证字段完整任务可被自动执行，并自动补齐幂等键
  - 已通过 `python3 scripts/agent_policy_demo.py --scenario write_disabled` 验证未开启写权限时，LLM 不能绕过 Policy 发送消息
- 这一步对后续任务的意义：
  - M4 会后任务创建可以先让 LLM 抽取候选行动项，再由 `AgentPolicy` 判断自动创建还是进入确认卡
  - M5 风险巡检可以用幂等键和本地存储做降噪，避免同一风险一天内重复提醒
  - 后续 `AgentPolicyConfig` 可以从配置文件读取，让比赛 Demo 和真实使用采用不同自动化强度

### T2.16 实现 Agent 手动调试入口

- 优先级：`P0`
- 目标：提供一个命令行入口，方便本地模拟不同事件，验证 Agent 决策和上下文构建
- 建议脚本：
  - `scripts/agent_demo.py`
- 示例：
  - `python3 scripts/agent_demo.py --event-type meeting.soon --calendar-id primary`
  - `python3 scripts/agent_demo.py --event-type minute.ready --minute-token xxx`
  - `python3 scripts/agent_demo.py --event-type risk.scan.tick`
- 验收标准：
  - 能打印 `AgentDecision`
  - 能打印 `WorkflowContext`
  - 能看到 LLM loop 每一轮选择了哪些工具
  - 能选择 dry-run，不产生真实副作用

#### T2.16 当前实现细节

- 已创建文件：
  - `scripts/agent_demo.py`
- 已实现的核心类：
  - `ScriptedDebugProvider`：脚本化调试 Provider，不访问真实模型，但能稳定模拟多轮工具调用
- 已实现的核心函数：
  - `parse_args()`：解析事件类型、后端、模型、工具、时间窗口和写权限等调试参数
  - `build_payload()`：根据命令行参数构造 `AgentInput.payload`
  - `default_tools_for_event()`：为 `meeting.soon`、`minute.ready`、`risk.scan.tick` 等事件提供安全默认工具集
  - `build_agent()`：根据 `--backend local/feishu` 和 `--llm-provider` 装配调试 Agent
  - `build_local_registry()`：构造不访问飞书的本地模拟工具注册器
  - `print_section()`：打印 `AgentInput`、`AgentDecision`、`WorkflowContext`
  - `print_loop_summary()`：打印 Agent Loop 摘要，包括最终回答、轮数、工具结果和副作用
- 当前调试模式：
  - `--backend local`：只使用本地模拟工具，不访问飞书，适合验证路由、上下文、Policy 和 Agent Loop
  - `--backend feishu`：使用真实飞书工具注册器，可以真实读取日历、通讯录、任务、文档和妙记
  - `--llm-provider scripted_debug`：不调用真实模型，稳定触发工具调用，适合快速验证链路
  - `--llm-provider dry-run`：使用 T2.9 的 dry-run provider，验证基础协议
  - `--llm-provider deepseek`：使用真实 DeepSeek 模型驱动工具选择
  - `--plan-only`：只打印 `AgentInput / AgentDecision / WorkflowContext`，不运行 LLM Loop，也不调用任何工具
- 当前本地模拟工具：
  - `calendar.list_events`：返回一条模拟会议
  - `contact.get_current_user`：返回模拟当前用户 open_id
  - `contact.search_user`：按 query 返回模拟用户候选
  - `tasks.list_my_tasks`：返回模拟待办
  - `tasks.create_task`：模拟创建任务，受 AgentPolicy 控制
  - `im.send_card`：模拟发送卡片，受 AgentPolicy 控制
  - `docs.fetch_resource`：返回模拟文档资源
  - `minutes.fetch_resource`：返回模拟妙记资源
- 当前推荐命令：
  - 只看路由和上下文，不执行工具：
    `python3 scripts/agent_demo.py --event-type meeting.soon --plan-only`
  - 本地模拟会前链路：
    `python3 scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug`
  - 本地模拟“我 -> open_id -> 创建任务”的多轮链路：
    `python3 scripts/agent_demo.py --event-type message.command --workflow-type manual_qa --tool tasks.create_task --backend local --llm-provider scripted_debug --allow-write --prompt "请创建一个任务：整理会议纪要，负责人为我，截止时间为两个小时后。"`
  - 真实飞书读取日历：
    `python3 scripts/agent_demo.py --event-type meeting.soon --backend feishu --llm-provider scripted_debug --max-iterations 3`
  - 真实 DeepSeek + 真实飞书：
    `python3 scripts/agent_demo.py --event-type message.command --backend feishu --llm-provider deepseek --tool calendar.list_events --prompt "请查询我今天的会议安排，并总结时间、标题和参与人。"`
- 当前验证方式：
  - 已通过 `python3 -m py_compile scripts/agent_demo.py` 验证语法正确
  - 已通过 `python3 scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 3` 验证会前调试链路
  - 已通过 `python3 scripts/agent_demo.py --event-type message.command --workflow-type manual_qa --tool tasks.create_task --backend local --llm-provider scripted_debug --allow-write --max-iterations 4 --prompt "请创建一个任务：整理会议纪要，负责人为我，截止时间为两个小时后。"` 验证多轮工具调用和 Policy 放行
  - 已通过 `python3 scripts/agent_demo.py --event-type meeting.soon --backend feishu --llm-provider scripted_debug --max-iterations 3` 真实调用飞书日历接口，验证真实后端可用
- 这一步对后续任务的意义：
  - 后续 M3-M5 的每个工作流都可以先通过 `agent_demo.py --backend local` 调试路由和上下文
  - 真正接飞书前可以先用 `--plan-only` 和 `--backend local` 做安全演练
  - 需要真实演示时，只需切换为 `--backend feishu --llm-provider deepseek`

---

