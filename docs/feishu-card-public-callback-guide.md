# 飞书卡片交互公网回调接入说明

本文档说明当前 MeetFlow 使用公网 HTTPS 隧道接收飞书群聊卡片按钮回调的方式。后续项目会同时兼容另一条由合作者实现的“飞书官方 SDK/长连接接入方式”，两种方式共享同一套内部 `CardActionRouter` 和 Agent 主链路。

## 1. 当前接入方式定位

当前方式是：

```text
飞书群聊卡片按钮
  -> 飞书开放平台回调
  -> 公网 HTTPS 地址
  -> cloudflared / ngrok / frp
  -> 本地 feishu_event_server.py
  -> FeishuEventHandler
  -> CardActionRouter
  -> AgentInput
  -> MeetFlowAgent
```

它适合：

- 本地开发联调。
- 快速验证飞书卡片按钮是否能回调到项目。
- 不部署服务器时做 Demo。
- 排查卡片 value、verification token、事件订阅、按钮回调 payload。

它不适合直接作为生产长期入口，因为免费 quick tunnel 地址不稳定，进程退出后地址会失效。

## 2. 当前项目相关代码

公网回调方式涉及这些文件：

- `scripts/feishu_event_server.py`
  - 本地 HTTP 回调服务。
  - 提供 `GET /healthz`、`POST /feishu/events`、`POST /feishu/card/actions`。
  - 默认只解析按钮并返回 toast。
  - 加 `--execute-agent` 后才会异步触发 Agent。
  - 加 `--allow-write` 后才允许后台 Agent 执行写工具。

- `adapters/feishu_event_handler.py`
  - 处理飞书 challenge。
  - 校验 verification token。
  - 解析 `card.action.trigger` payload。
  - 构造飞书 toast 响应。

- `core/card_actions.py`
  - 定义 `CardActionInput`、`CardActionResult`。
  - 把按钮动作路由成内部 Agent 事件。
  - 当前已支持 `refresh_pre_meeting_brief`、`create_task_draft`、`send_summary_to_me`。

- `cards/pre_meeting.py`
  - 会前卡片模板。
  - 当前卡片包含 `刷新背景`、`生成待办草案`、`发给我` 三个按钮。

- `core/router.py`
  - 已支持 `card.refresh_pre_meeting -> pre_meeting_brief`。

## 3. 本地服务启动

先启动本地回调服务：

```bash
python3 scripts/feishu_event_server.py --host 0.0.0.0 --port 8765
```

本地健康检查：

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

预期返回：

```json
{"status": "ok"}
```

如果 `curl` 被本地代理影响，可以临时关闭代理：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
```

或继续使用：

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

## 4. 公网 HTTPS 隧道

### 4.1 cloudflared

启动：

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

成功后会出现类似：

```text
https://example.trycloudflare.com
```

公网健康检查：

```bash
curl --noproxy '*' https://example.trycloudflare.com/healthz
```

预期返回：

```json
{"status": "ok"}
```

注意：

- cloudflared 终端不能关闭。
- quick tunnel 地址不是固定的。
- 每次重新启动后可能生成新地址。
- 新地址需要同步更新到飞书开发者后台。

### 4.2 ngrok / frp

如果不用 cloudflared，也可以使用：

```bash
ngrok http 8765
```

或自有服务器 + frp / nginx / caddy。

项目只要求飞书能访问一个公网 HTTPS 地址，具体隧道工具不强绑定。

## 5. 飞书开发者后台配置

进入飞书开放平台应用后台：

```text
https://open.feishu.cn/app
```

需要确认：

1. 应用已开启机器人能力。
2. 机器人已加入测试群。
3. 已开启消息卡片/交互式卡片能力。
4. 已订阅卡片回调事件：

```text
card.action.trigger
```

5. 回调请求地址配置为：

```text
https://example.trycloudflare.com/feishu/card/actions
```

如果飞书后台同时要求事件回调地址，也可以配置：

```text
https://example.trycloudflare.com/feishu/events
```

当前 MVP 中这两个路径都由 `scripts/feishu_event_server.py` 接收。

## 6. Verification Token 配置

飞书后台的 `Verification Token` 需要写入本地私密配置：

```text
config/settings.local.json
```

放在 `feishu` 段：

```json
{
  "feishu": {
    "event_verification_token": "飞书后台的 Verification Token",
    "event_encrypt_key": ""
  }
}
```

注意：

- `event_verification_token` 不能提交到 Git。
- `event_encrypt_key` 当前保持空字符串。
- 当前 MVP 尚未实现加密回调解密，所以飞书后台先不要开启加密回调。
- 修改配置后需要重启 `scripts/feishu_event_server.py`。

## 7. 发送测试卡片

可以用如下脚本发送一张带按钮的会前测试卡片：

```bash
python3 - <<'PY'
import json
import time

from adapters import FeishuClient
from cards import build_pre_meeting_card
from config import load_settings
from core import MeetingBrief

settings = load_settings()
client = FeishuClient(settings.feishu)

brief = MeetingBrief(
    meeting_id="manual_card_demo",
    calendar_event_id="manual_card_demo",
    project_id="meetflow",
    topic="MeetFlow 群聊卡片交互测试",
    summary="这是一张用于测试按钮回调的会前卡片。点击“刷新背景”后，应触发 MeetFlow 后端回调。",
    confidence=0.9,
)

card = build_pre_meeting_card(brief)

response = client.send_card_message(
    receive_id=settings.feishu.default_chat_id,
    receive_id_type="chat_id",
    card=card,
    idempotency_key=f"card-interaction-test-{int(time.time())}",
    identity="tenant",
)

print(json.dumps(response, ensure_ascii=False, indent=2))
PY
```

如果 `tenant` 身份发送失败，可以临时改为：

```python
identity="user"
```

但长期机器人群聊卡片建议使用 `tenant` / bot 身份，并确认机器人已经进群、权限已经发布。

## 8. 点击按钮后的观察位置

点击群里卡片按钮后，主要看两个地方。

### 8.1 回调服务终端

也就是运行：

```bash
python3 scripts/feishu_event_server.py --host 0.0.0.0 --port 8765
```

的终端。

如果飞书回调成功打进来，应该看到类似：

```text
POST /feishu/card/actions
```

如果这里没有任何输出，通常说明：

- 飞书后台回调地址没更新。
- cloudflared 地址失效。
- 没订阅 `card.action.trigger`。
- 卡片按钮不是回调按钮，而只是 URL 跳转按钮。

### 8.2 结构化日志

查看：

```bash
tail -n 50 storage/workflow_events.jsonl
```

或只筛选卡片事件：

```bash
grep "card_action" storage/workflow_events.jsonl | tail -n 20
```

预期看到：

```text
card_action_received
card_action_routed
card_action_finished
```

含义：

- `card_action_received`：飞书回调已进入后端并解析成功。
- `card_action_routed`：动作已进入 `CardActionRouter`。
- `card_action_finished`：动作已完成路由并返回 toast。

## 9. 执行 Agent 的方式

默认启动方式只解析卡片动作，不执行 Agent：

```bash
python3 scripts/feishu_event_server.py --host 0.0.0.0 --port 8765
```

确认回调链路稳定后，可以开启后台 Agent：

```bash
python3 scripts/feishu_event_server.py --host 0.0.0.0 --port 8765 --execute-agent
```

如果还要允许后台 Agent 执行写工具，例如发卡片、发消息，需要显式加：

```bash
python3 scripts/feishu_event_server.py --host 0.0.0.0 --port 8765 --execute-agent --allow-write
```

这个设计是安全闸门：

- 按钮点击不应该默认直接造成写副作用。
- 真实写操作仍必须经过 `AgentPolicy`。
- 重复点击需要依赖幂等键和后续审计表进一步增强。

## 10. 常见问题

### 10.1 公网 healthz 返回 Cloudflare 1033

说明 cloudflared 没连到本地服务。

处理：

1. 检查本地服务是否可用：

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

2. 重启 cloudflared。
3. 使用新的 trycloudflare 地址更新飞书后台。

### 10.2 本地 curl 访问 8765，却提示连接 7891

说明 curl 走了本地代理。

处理：

```bash
curl --noproxy '*' http://127.0.0.1:8765/healthz
```

### 10.3 飞书后台验证失败

检查：

- 回调 URL 是否是最新 cloudflared 地址。
- 本地服务是否正在运行。
- `event_verification_token` 是否和飞书后台一致。
- 飞书后台是否开启了加密；当前 MVP 不支持加密解密。

### 10.4 卡片能发送，但按钮点击没反应

检查：

- 卡片 JSON 里的按钮是否有 `value.action`。
- 飞书后台是否订阅 `card.action.trigger`。
- 回调地址是否填到了卡片回调配置。
- 回调服务终端是否收到 `POST /feishu/card/actions`。

## 11. 与官方 SDK/长连接方式的兼容设计

后续合作者会实现“飞书官方 SDK/长连接接入方式”。两种方式建议只在接入层不同，进入项目后的内部模型保持一致。

推荐边界：

```text
公网 HTTP 回调方式
  -> FeishuEventHandler
  -> CardActionInput
  -> CardActionRouter

飞书官方 SDK/长连接方式
  -> FeishuSdkEventAdapter
  -> CardActionInput
  -> CardActionRouter
```

也就是说，官方 SDK 方式不要重新实现业务路由，而是把 SDK 收到的事件也转换成：

```text
CardActionInput
```

然后继续复用：

```text
CardActionRouter
  -> AgentInput
  -> WorkflowRouter
  -> WorkflowContextBuilder
  -> MeetFlowAgentLoop
  -> ToolRegistry
  -> AgentPolicy
```

这样项目可以同时支持：

- 本地公网隧道开发调试。
- 官方 SDK/长连接稳定接入。
- 未来生产部署 HTTP 回调。

## 12. 两种方式的建议分工

### 公网回调方式

负责：

- HTTP challenge。
- verification token。
- cloudflared/ngrok/frp 本地联调。
- 快速验证卡片 payload 和按钮 value。
- Demo 阶段测试群回调。

### 官方 SDK/长连接方式

负责：

- 稳定接收飞书事件。
- 避免公网回调地址频繁变化。
- 减少本地 HTTPS 暴露依赖。
- 更适合长期运行和生产化。

### 共享部分

必须共享：

- `CardActionInput`
- `CardActionResult`
- `CardActionRouter`
- `AgentInput`
- `AgentPolicy`
- 结构化日志事件

不建议各自维护一套按钮业务逻辑，否则后续会出现“公网回调能用，SDK 方式行为不同”的问题。

## 13. 当前建议

当前阶段先用公网回调方式把按钮交互跑通。

当合作者完成官方 SDK 方式后，重点做一件事：

```text
把 SDK 收到的 card.action.trigger 事件转换为 CardActionInput
```

只要这个转换一致，两种接入方式就可以同时存在，并且共享后续所有 Agent 能力。
