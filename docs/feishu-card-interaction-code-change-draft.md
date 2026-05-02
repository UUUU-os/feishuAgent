# 飞书卡片交互代码改动草案

本文档基于 `docs/feishu-card-interaction-plan.md`，进一步拆成可执行的代码改动草案。

目标是先做一个 MVP：MeetFlow 能接收飞书群聊卡片按钮点击，解析 action，走内部路由和安全策略，最终能返回 toast，并可选择触发已有 Agent 主链路。

## 0. 当前实现状态

当前已完成第一版 MVP：

- 已新增 `core/card_actions.py`，包含 `CardActionInput`、`CardActionResult`、`CardActionRouter`。
- 已新增 `adapters/feishu_event_handler.py`，支持 challenge、verification token 校验、`card.action.trigger` 解析和 toast 响应。
- 已新增 `scripts/card_action_demo.py`，可本地模拟飞书卡片按钮点击。
- 已新增 `scripts/feishu_event_server.py`，提供 `GET /healthz`、`POST /feishu/events`、`POST /feishu/card/actions`。
- 已在 `cards/pre_meeting.py` 给会前卡片增加 `刷新背景`、`生成待办草案`、`发给我` 三个按钮。
- 已在 `core/router.py` 增加 `card.refresh_pre_meeting -> pre_meeting_brief` 路由。
- 已新增 `tests/test_card_actions.py` 和 `tests/test_feishu_event_handler.py`。

当前仍未完成：

- 飞书加密回调解密。
- 更新原卡片。
- 卡片动作 SQLite 幂等审计表。
- 真实飞书测试群按钮点击联调。

## 1. MVP 边界

第一版只做三件事：

1. 能接收并解析飞书卡片按钮回调。
2. 能把按钮点击转换成内部 `CardActionInput`。
3. 能把 `refresh_pre_meeting_brief` 路由成 `AgentInput`，复用现有 Agent 主链路。

第一版暂不强依赖：

- 更新原卡片。
- 长连接 SDK。
- 完整后台任务队列。
- 复杂多轮群聊机器人。

MVP 允许先用“立即返回 toast + 后台发送新消息/新卡片”的方式完成闭环。

## 2. 建议新增文件

```text
core/card_actions.py
adapters/feishu_event_handler.py
scripts/feishu_event_server.py
scripts/card_action_demo.py
tests/test_card_actions.py
tests/test_feishu_event_handler.py
```

后续增强时再考虑：

```text
core/background_jobs.py
tests/test_card_action_storage.py
```

## 3. 建议修改文件

```text
cards/pre_meeting.py
adapters/feishu_client.py
core/storage.py
core/router.py
core/__init__.py
config/loader.py
config/settings.example.json
config/README.md
docs/tasks/m2_8-agent-runtime.md
tasks.md
```

其中第一批最小改动建议只修改：

```text
cards/pre_meeting.py
core/card_actions.py
adapters/feishu_event_handler.py
scripts/card_action_demo.py
tests/test_card_actions.py
```

确认本地模拟跑通后，再加 HTTP server 和真实飞书回调。

## 4. core/card_actions.py

### 4.1 职责

`core/card_actions.py` 负责把卡片点击动作变成 MeetFlow 内部动作。

它不直接处理 HTTP，也不直接写飞书 API。

职责：

- 定义卡片动作输入输出模型。
- 从飞书 action value 中提取业务字段。
- 生成 `AgentInput`。
- 输出回调响应建议。
- 记录结构化日志。

### 4.2 建议数据模型

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.models import AgentInput, BaseModel


@dataclass(slots=True)
class CardActionInput(BaseModel):
    """飞书卡片按钮点击转换后的内部输入。

    这个模型屏蔽飞书原始回调结构，让后续路由只关心业务动作。
    """

    action: str
    trace_id: str
    event_id: str = ""
    operator_open_id: str = ""
    chat_id: str = ""
    open_message_id: str = ""
    workflow_type: str = ""
    meeting_id: str = ""
    calendar_event_id: str = ""
    source_card: str = ""
    idempotency_key: str = ""
    value: dict[str, Any] = field(default_factory=dict)
    raw_event: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass(slots=True)
class CardActionResult(BaseModel):
    """卡片动作处理结果。

    `response_mode` 用于告诉回调层应该返回 toast、保持原卡片，还是更新卡片。
    """

    status: str
    action: str
    message: str
    trace_id: str
    response_mode: str = "toast"
    agent_input: AgentInput | None = None
    response_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 4.3 建议路由器

```python
class CardActionRouter:
    """卡片按钮动作路由器。

    第一版只负责把按钮动作转换为 AgentInput，不在这里直接执行写操作。
    """

    def route(self, action_input: CardActionInput) -> CardActionResult:
        if action_input.action == "refresh_pre_meeting_brief":
            return self._refresh_pre_meeting_brief(action_input)
        if action_input.action == "create_task_draft":
            return self._create_task_draft(action_input)
        if action_input.action == "send_summary_to_me":
            return self._send_summary_to_me(action_input)
        return CardActionResult(
            status="blocked",
            action=action_input.action,
            message=f"暂不支持的卡片动作：{action_input.action}",
            trace_id=action_input.trace_id,
        )
```

### 4.4 refresh_pre_meeting_brief 转换逻辑

```python
def _refresh_pre_meeting_brief(self, action_input: CardActionInput) -> CardActionResult:
    agent_input = AgentInput(
        trigger_type="card_action",
        event_type="card.refresh_pre_meeting",
        source="feishu_card",
        actor=action_input.operator_open_id,
        event_id=action_input.event_id,
        trace_id=action_input.trace_id,
        created_at=action_input.created_at or int(time.time()),
        payload={
            "workflow_type": "pre_meeting_brief",
            "meeting_id": action_input.meeting_id,
            "calendar_event_id": action_input.calendar_event_id,
            "event_id": action_input.calendar_event_id,
            "chat_id": action_input.chat_id,
            "open_message_id": action_input.open_message_id,
            "operator_open_id": action_input.operator_open_id,
            "idempotency_key": action_input.idempotency_key,
            "required_tools": [
                "calendar.list_events",
                "tasks.list_my_tasks",
                "knowledge.search",
            ],
        },
    )
    return CardActionResult(
        status="accepted",
        action=action_input.action,
        message="已收到，正在刷新会前背景。",
        trace_id=action_input.trace_id,
        agent_input=agent_input,
    )
```

### 4.5 结构化日志

在 `CardActionRouter.route()` 前后记录：

```text
card_action_routed
card_action_failed
```

关键字段：

- `trace_id`
- `action`
- `workflow_type`
- `event_id`
- `operator_open_id`
- `chat_id`
- `open_message_id`
- `idempotency_key`
- `status`

注意这些字段会经过 `core/observability.py` 的脱敏逻辑。

## 5. adapters/feishu_event_handler.py

### 5.1 职责

这个模块负责飞书协议层：

- 解析飞书 HTTP payload。
- 处理 challenge。
- 校验 verification token。
- 解析卡片 action value。
- 转换成 `CardActionInput`。
- 把 `CardActionResult` 转换为飞书回调响应。

它不直接跑 Agent。

### 5.2 建议类与函数

```python
class FeishuEventHandlerError(RuntimeError):
    """飞书事件回调处理异常。"""


class FeishuEventHandler:
    """飞书事件回调协议适配器。"""

    def __init__(self, verification_token: str = "", encrypt_key: str = "") -> None:
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理飞书回调 payload，返回飞书需要的响应。"""

    def parse_card_action(self, payload: dict[str, Any]) -> CardActionInput:
        """从 card.action.trigger payload 中解析内部动作。"""

    def build_callback_response(self, result: CardActionResult) -> dict[str, Any]:
        """把内部结果转换为飞书卡片回调响应。"""
```

### 5.3 challenge 处理

飞书后台配置回调 URL 时，会发送 challenge。

建议逻辑：

```python
if payload.get("type") == "url_verification":
    return {"challenge": payload.get("challenge", "")}
```

### 5.4 token 校验

如果 payload 中有 `token` 字段：

```python
if self.verification_token and payload.get("token") != self.verification_token:
    raise FeishuEventHandlerError("飞书回调 verification token 不匹配")
```

错误日志中不能输出真实 token。

### 5.5 卡片 action 解析

需要兼容飞书实际 payload 字段差异。

第一版建议做宽松解析：

```python
event = payload.get("event") or {}
operator = event.get("operator") or {}
context = event.get("context") or {}
action = event.get("action") or {}
value = action.get("value") or {}
```

提取字段：

```text
event_id
operator.open_id
context.open_chat_id / context.chat_id
context.open_message_id
action.value.action
action.value.workflow_type
action.value.meeting_id
action.value.calendar_event_id
action.value.idempotency_key
```

### 5.6 回调响应

MVP 返回 toast：

```python
{
    "toast": {
        "type": "info",
        "content": result.message,
    }
}
```

如果飞书实际要求 `toast` 结构有差异，以真实回调调试结果为准。

## 6. scripts/feishu_event_server.py

### 6.1 职责

提供本地 HTTP 服务，用于飞书后台回调和真实点击测试。

MVP 可以先用 Python 标准库：

```text
python3 scripts/feishu_event_server.py --host 0.0.0.0 --port 8765
```

接口：

```text
POST /feishu/events
POST /feishu/card/actions
GET /healthz
```

### 6.2 建议流程

```text
读取 settings
初始化 logging
初始化 structured events
初始化 FeishuEventHandler
初始化 CardActionRouter
接收 POST
解析 JSON
handler.parse_card_action()
router.route()
立即返回 toast
可选：同步或后台执行 agent.run()
```

### 6.3 MVP 是否执行 Agent

建议提供开关：

```text
--execute-agent
```

默认只解析和路由，不真实跑 Agent。

这样飞书回调联调更稳：

```bash
python3 scripts/feishu_event_server.py --port 8765
```

确认回调能进来以后，再启用：

```bash
python3 scripts/feishu_event_server.py --port 8765 --execute-agent
```

## 7. scripts/card_action_demo.py

### 7.1 职责

不用真实飞书，构造模拟 payload，验证解析和路由。

命令：

```bash
python3 scripts/card_action_demo.py --action refresh_pre_meeting_brief
```

预期输出：

```text
CardActionInput
CardActionResult
AgentInput
```

### 7.2 模拟 payload

```python
def build_demo_payload(action: str) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt_card_demo",
            "event_type": "card.action.trigger",
        },
        "event": {
            "operator": {"open_id": "ou_demo"},
            "context": {
                "open_chat_id": "oc_demo",
                "open_message_id": "om_demo",
            },
            "action": {
                "value": {
                    "action": action,
                    "workflow_type": "pre_meeting_brief",
                    "meeting_id": "meeting_demo",
                    "calendar_event_id": "event_demo",
                    "source_card": "pre_meeting_brief",
                    "idempotency_key": f"card:pre_meeting_brief:event_demo:{action}",
                }
            },
        },
    }
```

## 8. cards/pre_meeting.py

### 8.1 改动目标

给会前卡片增加按钮区：

- 刷新背景
- 生成待办草案
- 发给我

### 8.2 建议新增函数

```python
def build_pre_meeting_card_actions(brief: Any) -> dict[str, Any]:
    """构造会前卡片按钮区。

    按钮 value 使用稳定动作协议，后端可直接解析为 CardActionInput。
    """
```

### 8.3 按钮示例

```python
{
    "tag": "action",
    "actions": [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "刷新背景"},
            "type": "primary",
            "value": {
                "action": "refresh_pre_meeting_brief",
                "workflow_type": "pre_meeting_brief",
                "meeting_id": meeting_id,
                "calendar_event_id": calendar_event_id,
                "source_card": "pre_meeting_brief",
                "idempotency_key": f"card:pre_meeting_brief:{calendar_event_id}:refresh",
            },
        }
    ],
}
```

注意：

- `value` 中不要放 token、secret、完整文档内容。
- `meeting_id` / `calendar_event_id` 为空时，按钮仍可展示，但 action handler 应返回“缺少会议信息”。

## 9. core/router.py

### 9.1 改动目标

让 `WorkflowRouter` 能识别卡片动作事件。

建议新增规则：

```text
card.refresh_pre_meeting -> pre_meeting_brief
card.create_task_draft -> post_meeting_summary 或 action_item_draft
card.send_summary_to_me -> pre_meeting_brief
```

第一版只建议接：

```text
card.refresh_pre_meeting -> pre_meeting_brief
```

### 9.2 required_tools

`refresh_pre_meeting_brief` 推荐工具：

```python
[
    "calendar.list_events",
    "tasks.list_my_tasks",
    "knowledge.search",
    "im.send_card",
]
```

如果 HTTP 回调服务默认 `allow_write=False`，则 `im.send_card` 会被过滤，不会误发消息。

真实发送新卡片时，必须显式开启 `allow_write=True`。

## 10. core/storage.py

### 10.1 改动目标

保存卡片动作幂等和审计记录。

建议新增表：

```sql
CREATE TABLE IF NOT EXISTS card_action_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    action TEXT NOT NULL,
    operator_open_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    open_message_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL
)
```

建议新增方法：

```python
def record_card_action_event(self, data: dict[str, Any]) -> None:
    """记录一次卡片动作处理结果。"""

def get_card_action_event(self, event_id: str) -> dict[str, Any] | None:
    """按飞书 event_id 查询卡片动作处理记录。"""
```

MVP 可以先不入库，只依赖结构化日志；真实联调稳定后再补 SQLite。

## 11. adapters/feishu_client.py

### 11.1 第一版不必改

第一版可以用现有：

- `send_text_message()`
- `send_card_message()`

处理完成后发一条新消息或新卡片。

### 11.2 后续增强

后续再新增：

```python
def update_message_card(self, message_id: str, card: dict[str, Any], identity: IdentityMode | None = None) -> dict[str, Any]:
    """更新已发送的飞书卡片消息。"""

def reply_message(self, message_id: str, content: dict[str, Any], msg_type: str = "text", identity: IdentityMode | None = None) -> dict[str, Any]:
    """回复某条飞书消息。"""
```

这两个接口要等真实飞书回调 payload 中确认 message_id 字段后再实现。

## 12. config 配置

建议在 `FeishuSettings` 中新增：

```python
event_verification_token: str = ""
event_encrypt_key: str = ""
event_server_host: str = "0.0.0.0"
event_server_port: int = 8765
```

对应环境变量：

```text
MEETFLOW_FEISHU_EVENT_VERIFICATION_TOKEN
MEETFLOW_FEISHU_EVENT_ENCRYPT_KEY
MEETFLOW_FEISHU_EVENT_SERVER_HOST
MEETFLOW_FEISHU_EVENT_SERVER_PORT
```

注意：

- `event_verification_token` 和 `event_encrypt_key` 是私密配置，只能放在 `settings.local.json` 或环境变量。
- `settings.example.json` 只能写占位符。

## 13. tests/test_card_actions.py

建议覆盖：

1. 能解析 `refresh_pre_meeting_brief`。
2. 能生成 `AgentInput(event_type="card.refresh_pre_meeting")`。
3. 缺少 action 时返回 blocked。
4. 未知 action 时返回 blocked。
5. 输出结果不包含原始 token/secret。

示例断言：

```python
result = router.route(action_input)
self.assertEqual(result.status, "accepted")
self.assertEqual(result.agent_input.event_type, "card.refresh_pre_meeting")
self.assertEqual(result.agent_input.payload["calendar_event_id"], "event_demo")
```

## 14. tests/test_feishu_event_handler.py

建议覆盖：

1. `url_verification` 能返回 challenge。
2. verification token 不匹配会报错。
3. `card.action.trigger` payload 能转成 `CardActionInput`。
4. 缺少 `action.value.action` 时能给出清晰错误。
5. `build_callback_response()` 能返回 toast。

## 15. 推荐实现顺序

### 第 1 步：本地纯函数链路

实现：

```text
core/card_actions.py
scripts/card_action_demo.py
tests/test_card_actions.py
```

验证：

```bash
python3 -m unittest tests.test_card_actions
python3 scripts/card_action_demo.py --action refresh_pre_meeting_brief
```

### 第 2 步：飞书 payload 解析

实现：

```text
adapters/feishu_event_handler.py
tests/test_feishu_event_handler.py
```

验证：

```bash
python3 -m unittest tests.test_feishu_event_handler
```

### 第 3 步：卡片按钮模板

修改：

```text
cards/pre_meeting.py
```

验证：

```bash
python3 scripts/pre_meeting_card_demo.py
```

检查输出 JSON 中按钮是否包含 `value.action`。

### 第 4 步：HTTP 回调服务

实现：

```text
scripts/feishu_event_server.py
```

验证：

```bash
python3 scripts/feishu_event_server.py --port 8765
curl -X POST http://127.0.0.1:8765/feishu/card/actions \
  -H 'Content-Type: application/json' \
  -d @storage/tmp/card_action_demo_payload.json
```

### 第 5 步：真实飞书联调

准备：

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

或使用 ngrok / frp。

飞书后台配置：

- 开启机器人。
- 开启交互式卡片能力。
- 订阅 `card.action.trigger`。
- 配置回调 URL。

验证：

```bash
tail -n 50 storage/workflow_events.jsonl
```

预期看到：

```text
card_action_received
card_action_routed
```

### 第 6 步：接 Agent 主链路

启动：

```bash
python3 scripts/feishu_event_server.py --port 8765 --execute-agent
```

预期：

- 点击按钮后立即返回 toast。
- 服务端生成 `AgentInput`。
- Agent 进入 `pre_meeting_brief`。
- 结构化日志出现 `workflow_started` 和 `workflow_finished`。

## 16. 风险点

- 飞书实际卡片回调 payload 字段可能和模拟结构不同，需要用真实回调校准。
- 卡片回调响应格式可能需要按飞书开放平台最新文档微调。
- 本地 HTTP 服务如果同步跑 LLM，可能超过飞书回调响应时间要求。
- 写操作如果绕过 `AgentPolicy`，容易重复发消息或误建任务。
- `operator_open_id`、`chat_id`、`open_message_id` 需要脱敏记录。
- 本地公网隧道 URL 改变后，飞书后台需要同步更新。

## 17. 第一批验收标准

第一批完成后应满足：

- 本地 demo 能把模拟飞书卡片点击解析成 `CardActionInput`。
- `refresh_pre_meeting_brief` 能生成正确的 `AgentInput`。
- 单测覆盖 action 解析、路由和异常场景。
- 会前卡片 JSON 中存在可回调按钮 value。
- HTTP server 能通过 challenge。
- 真实飞书测试群点击按钮后，服务端能收到事件并返回 toast。
- 结构化日志能按 `trace_id` 串起卡片点击和后续 Agent 执行。
