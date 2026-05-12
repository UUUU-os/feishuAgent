# MeetFlow 当前代码改造思路

## 1. 文档目的

这份文档用于把当前仓库里已经观察到的几个高价值问题，整理成一份可执行的代码修改思路。目标不是一次性重构全部模块，而是优先修复会影响真实联调、真实点击交互和后续迭代稳定性的边界问题。

本次改造思路优先围绕以下原则展开：

- 先修真实链路会踩坑的点，再做工程洁癖式优化
- 保持 `Router -> Context -> WorkflowRunner -> AgentLoop -> Policy -> Storage` 的主骨架不散
- 尽量复用现有 `core/`、`adapters/`、`cards/` 里的实现，不引入大范围目录迁移
- 每一项修改都要有明确的验证命令或最小测试入口

---

## 2. 当前最值得处理的问题

### 2.1 会前卡片“刷新背景”幂等键过于固定

当前问题：

- 会前卡片按钮在渲染阶段直接写死 `idempotency_key`
- 回调后 `CardActionRouter` 会把该键原样带进 `AgentInput`
- `WorkflowRouter` 会直接复用该显式幂等键
- `MeetFlowAgent` 在主入口检查到同键后会直接跳过执行

这会导致“同一张卡片上的第二次刷新”很容易被视为永久重复请求，而不是一次新的用户操作。

影响：

- 群里真实点击“刷新背景”可能只能成功一次
- 用户会误以为回调失效
- 后续做“重新生成会前卡片”时很难区分“去抖”和“真正重试”

---

### 2.2 会后链路暴露给 LLM 的工具集和 Policy 规范不一致

当前问题：

- `minute.ready` 和手动 `post_meeting_followup` 路由没有开放 `contact.get_current_user`
- 也没有开放 `contact.search_user`
- 但 `PostMeetingFollowupWorkflow` 的 spec 已经把这两个工具列为工作流允许工具
- 仓库规范也明确要求：用户说“我”或直接说姓名时，必须先解析身份，不能编造负责人 ID

影响：

- M4 一旦继续落地真实任务创建，就会卡在负责人解析这一步
- Agent 即使知道要补全负责人，也拿不到必要工具

---

### 2.3 会前刷新场景的确定性上下文过薄

当前问题：

- `WorkflowContextBuilder` 当前只解析 payload 和本地 memory，不主动补全会议详情
- 卡片回调 payload 里主要是 `meeting_id`、`calendar_event_id`、`chat_id`、`open_message_id`
- `PreMeetingBriefWorkflow.prepare_context()` 随后直接基于这些有限字段生成会前输入、主题识别和召回查询

这意味着“从卡片反向刷新会前背景”时，确定性阶段很可能拿不到会议标题、描述、参与人、附件等高价值信息。

影响：

- `prepare_context -> build_retrieval_query` 的确定性价值下降
- M3 会前链路在卡片刷新场景下更依赖 LLM 临场补救
- 真实数据不足时，容易退化成“空上下文 + 候选资料”

---

### 2.4 M3 核心模块测试覆盖不足

当前问题：

- 当前测试主要覆盖 M5 任务风险提醒、卡片动作、飞书回调处理、结构化日志
- `core/pre_meeting.py` 和 `core/knowledge.py` 这两个最复杂、最容易在真实数据上抖动的模块，目前主要依赖 demo 脚本验证

影响：

- M3 后续继续增强 topic / retrieval / evidence pack 时，回归风险较高
- 后续多人协作时，改动容易靠“脚本跑过就算”

---

### 2.5 `allow_write` 使用共享可变状态，后续接真实服务有串请求风险

当前问题：

- `MeetFlowAgent.run()` 会把 `allow_write` 写到共享的 `self.loop.allow_write`
- `MeetFlowAgentLoop` 再在 `_handle_tool_calls()` 中读取该实例字段

当前在 demo/单进程串行脚本里问题不明显，但只要后续接 HTTP 回调或并发调度，这种写法就可能让一个请求的写权限泄露到另一个请求。

影响：

- 后续真实事件服务化后存在权限串线风险
- 很难通过日志快速判断到底是哪一次请求打开了写权限

---

### 2.6 目录职责与实际实现存在漂移

当前问题：

- README 和目录规范中写了 `workflows/`、`tools/` 应该承载主逻辑
- 但当前真实实现几乎都在 `core/`
- `workflows/` 和 `tools/` 目前基本还是占位目录

影响：

- 新协作者按文档找实现时容易迷路
- 后续如果继续扩展，很容易形成“文档说一套，代码落一套”

这项优先级低于前五项，但最好尽快统一口径。

---

## 3. 推荐改造顺序

建议按下面顺序推进：

1. 修复卡片刷新幂等键设计
2. 补齐会后链路联系人解析工具
3. 为会前刷新增加确定性上下文补全
4. 给 M3 补单测
5. 去掉 `MeetFlowAgentLoop.allow_write` 的共享可变状态
6. 统一目录职责与文档口径

原因：

- 前三项会直接影响真实交互和后续主链路落地
- 第四、五项决定后续迭代是否稳
- 第六项更偏工程整洁，但应该在主链路稳定后收尾

---

## 4. 分项改造思路

## 4.1 P0：修复会前卡片刷新幂等键

### 目标

让“刷新背景”支持多次真实点击，同时仍然具备同一次回调的去重能力。

### 建议改法

第一步，调整卡片按钮 value 协议：

- 不再在卡片渲染阶段写入永久固定的 workflow 幂等键
- 按钮里保留 `action`、`source_card`、`meeting_id`、`calendar_event_id`
- 如需保留去重线索，只保留“生成幂等键所需字段”，不要直接放最终键

第二步，在回调层生成“本次点击级”幂等键：

- 优先使用飞书回调里的 `event_id`
- 如果回调缺少稳定 `event_id`，则退化为 `source_card + calendar_event_id + action + time_bucket`
- 该键只服务“同一次点击回调重放去重”，不要服务“整个会议生命周期永久去重”

第三步，区分两类幂等：

- 工作流请求幂等：避免同一次点击被重复处理
- 写操作幂等：继续由 `AgentPolicy` 或写工具参数控制，例如发卡、建任务、发消息

### 建议修改文件

- `cards/pre_meeting.py`
- `core/card_actions.py`
- `core/router.py`
- `core/agent.py`
- `tests/test_card_actions.py`
- `tests/test_feishu_event_handler.py`

### 验收标准

- 同一张卡片连续点击两次“刷新背景”，两次都能进入 Agent 主链路
- 同一条飞书回调重放时仍会被幂等拦截
- 不影响现有写操作幂等逻辑

---

## 4.2 P0：补齐会后链路联系人解析工具

### 目标

让 `post_meeting_followup` 在真实任务创建前，具备解析“我”和具体姓名的能力。

### 建议改法

第一步，补路由工具集：

- `minute.ready` 路由增加 `contact.get_current_user`
- `minute.ready` 路由增加 `contact.search_user`

第二步，补手动触发工具集：

- `MANUAL_WORKFLOW_TOOLS["post_meeting_followup"]` 同步加入这两个工具

第三步，补 demo 和测试入口：

- `scripts/agent_demo.py` 的本地 registry 已经有这两个模拟工具，主要需要确保默认工具集和 workflow 行为对齐
- 增加一个路由层或 workflow 层测试，防止以后又把工具删掉

### 建议修改文件

- `core/router.py`
- `scripts/agent_demo.py`
- 新增或补充 `tests/test_router.py` / `tests/test_agent_runtime.py`

### 验收标准

- `minute.ready` 路由结果里能看到联系人解析工具
- `message.command` 指定 `post_meeting_followup` 时也能暴露联系人解析工具
- 后续 M4 做负责人补全时无需再回头拆路由

---

## 4.3 P1：为会前刷新增加确定性上下文补全

### 目标

让卡片刷新会前背景时，确定性阶段先拿到更完整的会议信息，而不是直接在薄 payload 上生成召回查询。

### 设计原则

不建议简单把 `WorkflowContextBuilder` 改成“内部偷偷调飞书 API”的大杂烩，因为当前设计已经明确它应避免隐式工具执行。

更稳妥的做法是引入一个显式的、只读的上下文补全阶段。

### 建议改法

方案 A，推荐：

- 在 `PreMeetingBriefWorkflow.prepare_context()` 中增加“上下文补全”阶段
- 该阶段只做确定性只读加载，例如：
  - 根据 `calendar_event_id` 补会议标题、描述、时间
  - 根据 payload 或 memory 补附件、参与人
  - 必要时读取本地已缓存的项目记忆和历史资源

方案 B，可选：

- 新增 `PreMeetingContextHydrator` 或 `WorkflowContextHydrator`
- 由 `MeetFlowAgent` 在 `context_builder.build()` 之后、`runner.run()` 之前显式调用

### 为什么不建议直接改成“ContextBuilder 内部调工具”

- 会模糊“构建上下文”和“执行外部读取”的边界
- 会让调试和审计难以判断到底哪一步开始访问飞书
- 不利于后续复用到 M4/M5

### 建议修改文件

- `core/workflows.py`
- `core/pre_meeting.py`
- `core/context.py`
- 视实现方式可能新增：
  - `core/context_hydrator.py`
  - 或 `adapters/feishu_context_loader.py`

### 验收标准

- 卡片刷新场景下，`meeting_title`、`participants`、`attachments` 的填充率明显高于当前版本
- `PreMeetingBriefArtifacts` 在卡片刷新场景下不再主要依赖空 payload
- 不绕过 `ToolRegistry` 去做写操作，也不在上下文补全阶段产生副作用

---

## 4.4 P1：为 M3 补系统化单测

### 目标

让会前链路的关键确定性逻辑从“主要靠 demo 脚本”升级为“有稳定单测保护”。

### 建议优先补的测试点

第一组：主题识别

- 标题清晰样例
- 标题很弱但附件/项目记忆足够样例
- 缺上下文时进入 `needs_confirmation`

第二组：资源召回

- 候选池去重
- 召回原因解释
- 新鲜度和业务实体命中排序

第三组：会前摘要

- `last_decisions`
- `current_questions`
- `must_read_resources`
- `risks`

第四组：知识检索工具

- `knowledge.search` 返回 evidence pack 时包含 `ref_id`、`snippet`、`reason`、`source_url`
- `knowledge.fetch_chunk` 能正确展开 chunk

### 建议新增文件

- `tests/test_pre_meeting_topic.py`
- `tests/test_pre_meeting_retrieval.py`
- `tests/test_pre_meeting_summary.py`
- `tests/test_knowledge_tools.py`

### 验收标准

- M3 关键逻辑不再只依赖 demo 脚本
- 后续改排序规则或 query enrichment 时能快速发现回归

---

## 4.5 P1：移除 `allow_write` 的共享可变状态

### 目标

把写权限从“挂在共享 loop 实例上的状态”改成“一次 run 调用的显式参数”。

### 建议改法

第一步，修改 `MeetFlowAgentLoop.run()` 签名：

- 增加 `allow_write: bool = False`

第二步，向 `_handle_tool_calls()` 显式传递 `allow_write`

第三步，删除 `MeetFlowAgentLoop` 实例上的 `allow_write` 字段，避免跨请求污染

第四步，`MeetFlowAgent.run()` 不再写 `self.loop.allow_write = allow_write`

### 建议修改文件

- `core/agent_loop.py`
- `core/agent.py`
- 如有必要补一个简单测试，验证两次 run 可传不同写权限且互不影响

### 验收标准

- 同一个 `MeetFlowAgent` 实例连续执行两次请求时，写权限不串线
- 结构化日志里仍能正确记录每次请求的 `allow_write`

---

## 4.6 P2：统一目录职责与文档口径

### 目标

减少“文档中的目录职责”和“当前代码真实分布”之间的偏差。

### 两种可选方向

方案 A，调整文档口径，承认当前实现以 `core/` 为主：

- README、architecture、AGENTS 中补充说明：
  - 当前阶段 `workflows/`、`tools/` 仍在预留
  - 主逻辑暂时集中在 `core/`

方案 B，逐步迁移代码：

- 把 `core/workflows.py` 中具体工作流 runner 拆到 `workflows/`
- 把知识工具、飞书工具封装进一步靠近 `tools/`

### 当前建议

先走方案 A。

原因：

- 当前仓库已经在 M3/M5 过程中形成稳定调用关系
- 此时做目录迁移，收益低于成本
- 先把真实问题修掉，再做结构整理更稳

### 建议修改文件

- `README.md`
- `architecture.md`
- `AGENTS.md`
- 如后续迁移代码，再补充 `tasks.md` 和里程碑文档

---

## 5. 具体施工顺序建议

建议分三批提交：

### 第一批：主链路修复

- 卡片刷新幂等键
- 会后联系人工具补齐

这批完成后，真实点击交互和 M4 继续开发的阻塞会明显下降。

### 第二批：稳定性增强

- 会前刷新确定性上下文补全
- `allow_write` 去共享状态

这批完成后，主运行时的边界会更清楚。

### 第三批：回归保护与文档对齐

- M3 单测补齐
- README / architecture / AGENTS 口径对齐

---

## 6. 建议验证命令

本轮改造建议至少覆盖以下验证：

```bash
python3 -m py_compile core/*.py adapters/*.py cards/*.py scripts/*.py tests/*.py
python3 -m unittest tests.test_card_actions tests.test_feishu_event_handler
python3 -m unittest tests.test_risk_scan_workflow tests.test_observability
python3 scripts/agent_demo.py --event-type meeting.soon --backend local --llm-provider scripted_debug --max-iterations 3
python3 scripts/agent_demo.py --event-type minute.ready --backend local --llm-provider scripted_debug --max-iterations 3
python3 scripts/agent_demo.py --event-type risk.scan.tick --backend local --llm-provider scripted_debug --max-iterations 3
```

如果第二阶段补了 M3 单测，再补：

```bash
python3 -m unittest tests.test_pre_meeting_topic tests.test_pre_meeting_retrieval tests.test_pre_meeting_summary tests.test_knowledge_tools
```

---

## 7. 最终建议

如果当前只能先做一件事，优先修卡片刷新幂等键，因为这是最容易在真实飞书点击时直接暴露出来的问题。

如果当前准备继续推进 M4，则第二优先级是补齐联系人解析工具，否则后面做负责人落地时一定还要回头返工。

其余几项都值得做，但前两项最接近“现在就会影响使用”的问题。
