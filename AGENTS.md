# AGENTS.md

本文件记录 MeetFlow 项目开发过程中所有 Agent、协作者和后续自动化脚本必须遵循的规范。它的目标不是束缚开发，而是让项目在快速迭代时依然保持可理解、可测试、可恢复。

## 1. 项目定位

MeetFlow 是一个面向飞书办公场景的垂直业务 Agent，不只是 API 工作流集合。它需要围绕“会议前后知识服务”主动理解上下文、选择工具、调用飞书能力，并在安全策略约束下完成查询、总结、任务创建和消息推送。

核心链路应保持为：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

LLM 负责推理和选择工具，但不能绕过 `AgentPolicy`、`ToolRegistry` 或飞书客户端封装直接执行外部副作用。

## 2. 目录职责

- `config/`：配置加载、示例配置、LLM 厂商配置模板。本地密钥文件只放在 `*.local.json`。
- `core/`：Agent 运行时、模型、路由、上下文、工具注册、策略、日志、存储等核心能力。
- `adapters/`：飞书、LLM、外部系统适配层。外部 API 细节优先封装在这里。
- `workflows/`：可复用业务流程，不能替代 Agent Loop。
- `tools/`：面向 Agent 的工具定义或辅助工具。
- `scripts/`：本地 Demo、真实 API 测试、调试入口。脚本必须适合阅读和复现。
- `storage/`：本地 SQLite、JSONL、审计记录等运行数据。不要提交敏感运行数据。
- `cards/`：飞书卡片模板与示例。
- `tests/`：单元测试和集成测试。

## 3. 文档同步规范

- 每完成一个 `tasks.md` 中的任务，必须同步更新该任务条目。
- `tasks.md` 至少要补充：创建或修改了哪些文件、核心类/函数、运行的业务逻辑、验证命令和结果。
- 如果实现改变了架构边界、Agent 流程或安全策略，需要同步更新 `architecture.md`。
- 如果实现改变了用户场景、验收方式或产品目标，需要同步更新 `prd.md`。
- 文档要帮助人真正读懂代码，不能只写“已完成”。

## 4. 代码风格

- 新增代码必须写中文注释或中文 docstring，尤其是业务逻辑、飞书 API、Agent 决策和安全策略相关代码。
- 注释要解释“为什么这样做”和“业务含义”，不要写无价值的逐行翻译。
- Python 代码优先保持简单直接，标准库优先；只有确有必要时再引入依赖。
- 数据结构优先沿用项目现有风格，例如 `dataclass`、明确类型标注、清晰的模型边界。
- 不要在业务代码中散落飞书 URL、权限名、token 字段解析逻辑，优先集中在 adapter 或配置层。
- 不要吞掉异常。外部 API 错误应保留 HTTP 状态、飞书错误码、request_id/log_id 等排查信息，但必须隐藏 token、secret、API key。

## 5. Agent 设计规范

- MeetFlow 必须体现垂直 Agent 能力：理解业务意图、构建上下文、选择工具、根据工具结果继续推理、产出可执行结论。
- 不要把所有能力退化成固定 if/else 工作流。固定流程可以作为 fallback，但核心路径应支持 LLM tool calling。
- `WorkflowRouter` 负责根据事件类型和输入文本判断业务场景。
- `WorkflowContextBuilder` 负责收集当前时间、用户、会议、任务、历史状态等上下文。
- `MeetFlowAgentLoop` 负责多轮 LLM 推理和工具调用。
- `ToolRegistry` 负责暴露工具 schema、执行工具、映射内部工具名和 LLM 工具名。
- `AgentPolicy` 负责写操作安全、幂等、字段完整性、置信度和权限检查。
- 所有写操作必须经过 policy，不能在脚本或工具里绕过。

## 6. LLM 与工具调用规范

- 内部工具名可以使用点号，例如 `calendar.list_events`。
- LLM 可见工具名必须兼容 OpenAI/DeepSeek 规则，只能包含字母、数字、下划线和短横线，例如 `calendar_list_events`。
- 工具返回给 LLM 的内容必须包含结构化 JSON 或足够详细的字段，不能只返回“成功，返回 N 条记录”。
- Agent 测试优先使用 `scripted_debug` 或 `dry-run`，确认工具链和策略正确后再接入真实 LLM。
- DeepSeek 等 OpenAI-compatible provider 的 API key 必须来自本地配置或环境变量，不能硬编码。
- 如果 LLM 声称“工具没有返回详情”，优先检查 `ToolResult.content` 是否包含了真实结构化结果。

## 7. 飞书集成规范

- 个人日历、个人任务、个人云文档等用户资源默认使用 `user` 身份。
- 应用机器人发送群消息时可以使用 `tenant` 身份，但必须确认机器人能力已开启、机器人已进群、应用具备对应权限。
- 涉及飞书 API 不确定时，优先参考本地 lark skills 和 `lark-cli schema`，不要凭记忆猜接口。
- OAuth Device Flow 是当前推荐的本地授权方式。授权成功后应持久化 `user_access_token`、`refresh_token` 和过期时间。
- `refresh_token` 通常只能使用一次。刷新成功后必须写回新的 refresh token。
- 严禁在日志、异常、文档、提交记录中打印完整 access token、refresh token、app secret 或 API key。
- 真实写操作测试必须显式使用 `--allow-write` 或同等开关。
- 群消息测试优先使用配置中的测试群，不要默认发送到生产群。

## 8. Policy 安全规范

- 所有写工具，例如 `tasks.create_task`、`im.send_text`、`im.send_card`，必须经过 `AgentPolicy.authorize_tool_call()`。
- 创建任务必须具备明确负责人、截止时间和足够置信度。
- 用户说“我”时，应优先调用 `contact.get_current_user` 解析当前用户 open_id。
- 用户说具体姓名时，应优先调用 `contact.search_user` 搜索候选人，不能让 LLM 编造 open_id。
- 写操作必须带幂等键。重复提醒、重复建任务、重复推送要能被拦截或识别。
- 缺少关键字段时，策略应返回 `needs_confirmation`，由 Agent 向用户澄清，而不是盲目执行。

## 9. 配置与密钥安全

- `config/settings.local.json` 和 `config/llm_providers.local.json` 只能保存在本地，不能提交。
- 示例配置只能写占位符，例如 `replace-with-your-api-key`。
- 不要把真实密钥写入 README、tasks、日志、issue、commit message 或截图说明。
- 如果密钥疑似泄露，第一步是去对应平台轮换或删除密钥；第二步才是清理仓库历史。
- 需要排查配置时，只能打印字段是否存在、provider 名称、模型名、过期时间等非敏感信息。

## 10. 测试与验证

常规验证优先从无副作用到真实副作用逐步推进：

```bash
python3 -m py_compile core/*.py adapters/*.py scripts/*.py
python3 scripts/agent_demo.py --event-type meeting.soon --plan-only
python3 scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug
python3 scripts/agent_demo.py --event-type meeting.soon --backend feishu --llm-provider scripted_debug --max-iterations 3
python3 scripts/meetflow_agent_live_test.py --llm-provider deepseek --tool calendar.list_events --prompt "请查询我今天的会议安排。"
python3 scripts/agent_policy_demo.py --scenario missing_task_fields
```

- 真实飞书读操作可以直接运行，但要确认当前身份和时间窗口。
- 真实飞书写操作必须显式加写入开关，并在测试群或测试任务中验证。
- 每次修复一个真实 API 问题，都要在 `tasks.md` 记录失败原因、修复方式和成功命令。
- 如果网络、代理或沙箱导致真实 API 请求失败，应明确说明失败原因，不要伪造成功结果。

## 11. Git 与工作区规范

- 遵循 `git-instruction.md` 中的项目 Git 约定。
- 不要主动提交、推送或改写历史，除非用户明确要求。
- 不要使用 `git reset --hard`、`git checkout --` 等破坏性命令回滚用户改动。
- 发现非自己造成的改动时，不要随意覆盖；如果会影响当前任务，需要先向用户说明。
- 编辑文件优先使用补丁方式，保持 diff 可读。

## 12. 已知易错点

- 飞书主日历 `primary` 不是最终事件查询 ID，通常需要先解析成真实 `calendar_id`。
- `tenant_access_token` 不能替代用户权限接口所需的 `user_access_token`。
- 飞书 `refresh_token` 刷新后旧值会失效，必须立即持久化新值。
- DeepSeek 工具名不允许包含点号。
- 如果 Agent 查询日程成功但回答没有详情，通常是工具结果没有把结构化事件详情传回 LLM。
- 如果创建任务时“负责人为我”被拦截，通常是还没有调用 `contact.get_current_user` 解析当前用户。
- 如果机器人消息没有以机器人身份发送，检查是否使用了 `tenant` 身份、机器人是否入群、权限是否发布生效。

## 13. 协作口径

- 面向用户解释时，优先说明“现在能做什么、怎么测、风险在哪里”。
- 遇到失败要记录真实原因。失败记录是项目资产，不是噪音。
- 每个 Demo 脚本都应让后来者能独立复现，不要依赖口头记忆。
- 本项目的成功标准不是“接口能调通”，而是 Agent 能在飞书真实业务场景中安全、准确、可解释地完成工作。
