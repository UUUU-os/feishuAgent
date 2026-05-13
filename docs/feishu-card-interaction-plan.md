# 飞书群聊卡片按钮交互实施方案

本文档说明 MeetFlow 要支持“用户在飞书群聊中点击卡片按钮后触发对应功能”需要完成的工作。

当前项目已经具备向飞书群聊发送文本和交互卡片的能力，但还缺少接收并处理卡片按钮回调的服务端链路。

## 1. 目标

让 MeetFlow 可以在飞书群聊中完成如下交互：

1. Agent 发送一张会前背景卡、任务确认卡或风险提醒卡到群里。
2. 用户点击卡片上的按钮。
3. 飞书把按钮点击事件回调给 MeetFlow 服务端。
4. MeetFlow 校验回调、解析动作、执行安全策略。
5. MeetFlow 根据按钮动作调用 Agent、工具或飞书 API。
6. MeetFlow 返回 toast、更新卡片，或发送新的群消息。

这条链路不是简单的消息发送，而是一个完整的“群聊交互入口”。

## 2. 当前项目已有能力

当前已有的相关代码：

- `adapters/feishu_client.py`
  - `send_text_message()`：发送文本消息。
  - `send_card_message()`：发送飞书 interactive card。
  - `build_meetflow_card()`：构造基础 MeetFlow 卡片。
- `adapters/feishu_tools.py`
  - `im.send_text`：Agent 可用的文本发送工具。
  - `im.send_card`：Agent 可用的卡片发送工具。
- `cards/pre_meeting.py`
  - `build_pre_meeting_card()`：会前背景卡片模板。
- `core/policy.py`
  - `AgentPolicy`：控制写操作、幂等、关键字段和确认逻辑。
- `core/observability.py`
  - 结构化日志，可用于记录卡片点击、路由和处理结果。

当前缺口：

- 没有 HTTP/WebSocket 回调服务入口。
- 卡片按钮还没有稳定的 action value 协议。
- 没有 `card.action.trigger` 事件解析。
- 没有按钮动作到内部 Agent/工具的路由。
- 没有卡片点击的幂等、审计和权限检查。
- 没有原卡片更新或按钮点击后的群消息回复能力。

## 3. 推荐首批交互场景

建议先做 3 个按钮，不要一开始做泛化聊天机器人。

### 3.1 刷新会前卡片

按钮文案：

```text
刷新背景
```

动作：

```text
refresh_pre_meeting_brief
```

效果：

- 重新运行 `pre_meeting_brief` 工作流。
- 重新检索会议相关文档、任务和妙记。
- 生成新的会前卡片。
- MVP 阶段可以发送一条新卡片；后续再更新原卡片。

安全级别：

- 只读为主。
- 可以自动执行。

### 3.2 生成待办草案

按钮文案：

```text
生成待办草案
```

动作：

```text
create_task_draft
```

效果：

- 从会议背景、妙记或上下文中提取 action item。
- 生成待办草案。
- 如果要真正创建飞书任务，必须经过确认。

安全级别：

- 草案生成是只读/无副作用。
- 真正创建任务是写操作，必须经过 `AgentPolicy`。

### 3.3 发送给我

按钮文案：

```text
发给我
```

动作：

```text
send_summary_to_me
```

效果：

- 把当前卡片摘要私聊发送给点击人。
- 适合用户不想在群里展开细节时使用。

安全级别：

- 写操作，因为会发送私聊消息。
- 需要确认接收者就是按钮点击人。

## 4. 卡片按钮协议

卡片按钮不能只做 URL 跳转，需要携带 `value`，让后端知道用户点了什么。

建议 value 结构：

```json
{
  "action": "refresh_pre_meeting_brief",
  "workflow_type": "pre_meeting_brief",
  "meeting_id": "calendar_event_id_or_meeting_id",
  "calendar_event_id": "calendar_event_id",
  "source_card": "pre_meeting_brief",
  "idempotency_key": "card:pre_meeting_brief:calendar_event_id:refresh"
}
```

字段说明：

- `action`：按钮动作名，必须稳定。
- `workflow_type`：关联的 MeetFlow 工作流。
- `meeting_id`：业务会议 ID。
- `calendar_event_id`：飞书日历事件 ID。
- `source_card`：来源卡片类型。
- `idempotency_key`：按钮动作幂等键，防止重复点击或飞书重试导致重复执行。

建议内部动作名使用小写下划线：

```text
refresh_pre_meeting_brief
create_task_draft
send_summary_to_me
confirm_create_task
cancel_action
```

## 5. 服务端回调入口

建议新增文件：

```text
scripts/feishu_event_server.py
adapters/feishu_event_handler.py
```

MVP 阶段可以先提供一个 HTTP 服务：

```text
POST /feishu/events
POST /feishu/card/actions
```

需要处理：

- 飞书 URL verification / challenge。
- verification token 校验。
- 如果开启了加密，需要处理 encrypt payload 解密。
- 解析卡片按钮事件。
- 提取点击人、群 ID、消息 ID、按钮 value。
- 快速返回飞书需要的响应。

后续如果要更稳定，可以再评估飞书长连接 SDK 或 WebSocket 方案。

## 6. CardActionRouter

建议新增核心模块：

```text
core/card_actions.py
```

建议定义：

```text
CardActionInput
CardActionResult
CardActionRouter
```

职责：

- 把飞书原始回调转成内部结构。
- 根据 `value.action` 路由到对应处理器。
- 构造 `AgentInput`。
- 调用已有 Agent 主链路。
- 返回卡片回调响应建议。

内部仍应遵循 MeetFlow 主链路：

```text
AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
  -> FeishuClient / Storage
```

不要在回调入口里直接绕过 `AgentPolicy` 调飞书写接口。

## 7. 回调处理流程

推荐流程：

```text
飞书卡片按钮点击
  -> feishu_event_server 接收 HTTP 请求
  -> feishu_event_handler 校验 token / 解密 / 解析
  -> CardActionRouter 识别 action
  -> AgentPolicy 判断是否允许
  -> 幂等检查
  -> 执行轻动作或投递后台任务
  -> 立即返回 toast / card update / keep
  -> Agent 后台完成后发送群消息或更新卡片
```

关键点：

- 回调入口必须快速响应，不要在 HTTP 请求内长时间阻塞。
- 读操作可以同步完成，但也要控制耗时。
- 生成摘要、检索文档、调用 LLM 这类重动作建议异步执行。
- 写操作必须经过策略和幂等检查。

## 8. Policy 安全要求

卡片点击会带来真实群聊副作用，因此必须接入 `AgentPolicy`。

需要重点检查：

- 点击人是谁：`operator.open_id`。
- 点击发生在哪个群：`chat_id`。
- 点击来自哪条消息：`open_message_id`。
- 动作是否是写操作。
- 是否具备关键字段。
- 是否需要二次确认。
- 是否存在幂等键。
- 是否重复点击。

建议策略：

- `refresh_pre_meeting_brief`：只读动作，可直接允许。
- `create_task_draft`：生成草案可允许，真正创建任务必须确认。
- `send_summary_to_me`：只允许发送给按钮点击人。
- `confirm_create_task`：必须检查草案 ID、负责人、截止时间和幂等键。

## 9. 幂等与审计

飞书可能重试回调，用户也可能重复点击按钮。

建议保存卡片动作记录：

```text
card_action_events
```

建议字段：

```text
id
event_id
trace_id
action
operator_open_id
chat_id
open_message_id
idempotency_key
status
result_summary
created_at
finished_at
```

建议扩展：

- `core/storage.py`
- `core/audit.py`

处理原则：

- 同一个 `event_id` 重复到达，应直接返回已处理结果。
- 同一个 `idempotency_key` 重复点击，应避免重复发消息、重复建任务。
- 所有写操作都应留下审计记录。

## 10. 响应方式

MVP 推荐两种响应：

### 10.1 Toast

用户点击后立即看到提示，例如：

```text
已收到，正在刷新会前背景。
```

适合所有异步动作。

### 10.2 发新消息

后台处理完成后，在群里发一条新消息或新卡片。

MVP 阶段优先使用这种方式，因为当前项目已有 `im.send_text` 和 `im.send_card`。

### 10.3 更新原卡片

后续增强：

- 点击后把按钮改成“处理中”。
- 完成后更新原卡片内容。
- 失败时在原卡片上展示错误摘要。

这需要给 `FeishuClient` 增加消息卡片更新能力。

## 11. 结构化日志要求

建议新增事件：

```text
card_action_received
card_action_routed
card_action_policy_decision
card_action_finished
card_action_failed
```

关键字段：

- `trace_id`
- `event_id`
- `action`
- `workflow_type`
- `operator_open_id`
- `chat_id`
- `open_message_id`
- `idempotency_key`
- `status`
- `duration_ms`
- `error_message`

注意：

- `operator_open_id`、`chat_id` 需要脱敏。
- 不记录完整 access token、refresh token、app secret、api key。

## 12. 飞书后台配置

需要在飞书开发者后台完成：

1. 开启机器人能力。
2. 确认机器人已加入测试群。
3. 开启交互式卡片能力。
4. 订阅卡片动作事件，例如 `card.action.trigger`。
5. 配置卡片请求 URL 或事件回调 URL。
6. 如果本地开发，需要使用公网 HTTPS 隧道，例如 ngrok、frp 或 cloudflared。
7. 确认权限已经发布生效。

常见问题：

- 卡片可以发送，但按钮点击报错，通常是没有订阅 `card.action.trigger`、没有开启交互式卡片能力，或者没有配置卡片请求 URL。
- 机器人发不出群消息，通常是机器人未进群、使用了错误身份，或权限未发布。
- 回调没有进入本地服务，通常是公网 URL、HTTPS、端口、防火墙或飞书后台配置问题。

## 13. 推荐开发顺序

### 阶段 1：最小回调闭环

新增：

- `scripts/feishu_event_server.py`
- `adapters/feishu_event_handler.py`

目标：

- 能接收飞书 challenge。
- 能接收模拟卡片点击 payload。
- 能返回合法响应。

### 阶段 2：按钮协议和本地模拟

新增：

- `core/card_actions.py`
- `scripts/card_action_demo.py`

修改：

- `cards/pre_meeting.py`

目标：

- 会前卡片上出现 2-3 个按钮。
- 按钮 value 使用稳定协议。
- 本地模拟点击可以路由到对应 action。

### 阶段 3：真实飞书回调联调

目标：

- 使用公网 HTTPS 隧道暴露本地服务。
- 飞书后台配置回调 URL。
- 用户点击测试群里的按钮后，本地服务能收到事件。
- 日志中出现 `card_action_received`。

### 阶段 4：接入 Agent 主链路

目标：

- `refresh_pre_meeting_brief` 能重新运行会前工作流。
- 处理完成后发一条群消息或新卡片。
- 所有写动作经过 `AgentPolicy`。

### 阶段 5：增强体验

目标：

- 支持更新原卡片。
- 支持按钮禁用或状态变化。
- 支持失败提示和重试。
- 支持更完整的幂等、审计和结构化日志分析。

## 14. 测试方法

### 14.1 本地模拟测试

构造模拟 payload：

```json
{
  "event": {
    "operator": {
      "open_id": "ou_xxx"
    },
    "context": {
      "open_message_id": "om_xxx",
      "open_chat_id": "oc_xxx"
    },
    "action": {
      "value": {
        "action": "refresh_pre_meeting_brief",
        "workflow_type": "pre_meeting_brief",
        "meeting_id": "meeting_demo",
        "calendar_event_id": "event_demo",
        "idempotency_key": "card:pre_meeting_brief:event_demo:refresh"
      }
    }
  }
}
```

预期：

- 能解析出 action。
- 能生成 `CardActionInput`。
- 能路由到正确处理器。
- 能写入结构化日志。

### 14.2 飞书后台 challenge 测试

预期：

- 飞书后台配置 URL 时，服务能返回 challenge。
- 控制台验证通过。

### 14.3 真实按钮点击测试

流程：

1. 发送一张测试卡片到测试群。
2. 点击 `刷新背景`。
3. 服务端收到 `card.action.trigger`。
4. 返回 toast。
5. 后台发送一条“已刷新”消息或新卡片。
6. 查看 `storage/workflow_events.jsonl`。

预期日志：

```text
card_action_received
card_action_routed
policy_decision
workflow_started
workflow_finished
card_action_finished
```

## 15. 本阶段不建议做的事

- 不建议一开始做完整多轮群聊机器人。
- 不建议让按钮直接绕过 `AgentPolicy` 执行写操作。
- 不建议把所有逻辑写在 HTTP handler 里。
- 不建议把真实 open_id、chat_id、token 写入日志或文档。
- 不建议一开始强依赖更新原卡片，MVP 可先发新消息。

## 16. 参考资料

- 飞书 Aily 回调请求地址说明：`https://www.feishu.cn/content/73uw5rsa`
- Hermes Agent 飞书适配文档：`https://www.majiabin.com/hermes/user-guide/messaging/feishu/`

以上资料用于确认卡片交互回调、快速响应、`card.action.trigger` 订阅和交互式卡片能力配置等关键要求。具体接口字段以飞书开放平台当前文档和真实回调 payload 为准。
