# D4 任务卡负责人解析 OAuth 失败修复合并说明

## 1. 背景

真实联调中，用户在 M4/D4 会后待确认任务卡里填写了负责人和截止时间，例如：

```text
负责人：李健文
截止时间：2026-05-13
```

点击“确认创建”后，后端日志出现：

```text
[meetflow.tool_registry] Agent 工具执行失败
tool=contact_search_user
call_id=callback_resolve_owner:李健文
error=飞书接口 HTTP 错误 method=POST
url=https://open.feishu.cn/open-apis/authen/v2/oauth/token
detail=http_status=400 code=20064
```

旧逻辑的问题是：`contact.search_user` 因 OAuth token / refresh_token 失败而没有拿到负责人
`open_id`，但回调链路把它当作“通讯录没查到人”，继续调用 `tasks.create_task`。随后
`AgentPolicy` 因 `assignee_ids` 为空拦截任务创建，最终提示“缺少负责人”。

这个提示是误导性的：用户已经填写负责人，真正失败点是用户身份 token 已失效，无法通过飞书通讯录解析
负责人 `open_id`。

## 2. 修复目标

- 保留“任务创建必须有真实 `open_id` 负责人”的安全边界。
- 区分两类情况：
  - 通讯录正常返回，但没有匹配用户：继续按缺负责人处理。
  - 通讯录工具本身失败，例如 `code=20064`：不再继续创建任务，直接提示 OAuth 授权问题。
- 用户填写的负责人和截止时间仍保存到 pending registry，重新授权后可继续确认。
- 不在日志、文档或 toast 中暴露 token、refresh token、app secret。

## 3. 需要合并的文件

核心代码：

- `core/card_callback.py`

回归测试：

- `tests/test_post_meeting_card_callback.py`

任务记录：

- `docs/tasks/d4-minute-agent-task-card-plan.md`
- `tasks.md`

本说明文档：

- `docs/tasks/d4-owner-resolution-auth-error-merge-note.md`

## 4. 核心代码改动

### 4.1 新增负责人解析结果模型

文件：`core/card_callback.py`

新增在 `CardCallbackResult` 后：

```python
@dataclass(slots=True)
class OwnerResolutionResult:
    """卡片确认时负责人解析结果。

    区分“通讯录没有匹配用户”和“通讯录工具本身失败”很重要：前者可以继续
    交给 Policy 按缺负责人处理，后者通常是 OAuth/token/权限问题，应该把
    真实原因反馈给用户，避免误导为用户没填写负责人。
    """

    open_ids: list[str] = field(default_factory=list)
    error_message: str = ""
```

合并注意：`field` 已经在文件顶部从 `dataclasses` 导入，当前文件已有：

```python
from dataclasses import dataclass, field
```

### 4.2 修改确认创建时的负责人解析分支

文件：`core/card_callback.py`

函数：`confirm_create_task_from_card()`

旧逻辑：

```python
if owner_open_id:
    assignee_ids = [owner_open_id]
else:
    assignee_ids = resolve_owner_open_ids_for_callback(registry, action_item.owner)
```

新逻辑：

```python
if owner_open_id:
    assignee_ids = [owner_open_id]
else:
    owner_resolution = resolve_owner_open_ids_for_callback(registry, action_item.owner)
    if owner_resolution.error_message:
        reason = owner_resolution.error_message
        response_card = build_card_from_callback_value(
            action_item_to_callback_value(action_item, context=context, action_value=merged_action_value),
            mode="edit",
            status_message=reason[:180],
            status_kind="error",
        )
        mark_pending_action_status(
            settings,
            action_item.item_id,
            status="pending",
            result={"status": "error", "message": reason, "owner": action_item.owner},
        )
        append_card_callback_log(
            settings,
            payload=payload,
            action_value=action_value,
            status="owner_resolution_failed",
            result={"reason": reason, "owner": action_item.owner},
        )
        updated_card = apply_callback_card_update(
            client=client,
            settings=settings,
            payload=payload,
            action_value=action_value,
            card=response_card,
        )
        if updated_card:
            response_card = updated_card
        return CardCallbackResult(status="error", message=reason[:180], response_card=response_card)
    assignee_ids = owner_resolution.open_ids
```

行为变化：

- `contact.search_user` 失败时，不再继续进入 `build_task_create_arguments()` 和 `tasks.create_task`。
- pending action 状态保持为 `pending`。
- `storage/card_callbacks.jsonl` 会记录 `owner_resolution_failed`，方便排障。
- 用户看到的提示会指向 OAuth/token 问题，而不是“缺少负责人”。

### 4.3 修改负责人解析函数返回值

文件：`core/card_callback.py`

函数：`resolve_owner_open_ids_for_callback()`

旧签名：

```python
def resolve_owner_open_ids_for_callback(registry: Any, owner: str) -> list[str]:
```

新签名：

```python
def resolve_owner_open_ids_for_callback(registry: Any, owner: str) -> OwnerResolutionResult:
```

关键改动：

```python
owner_text = owner.strip()
if not owner_text or is_group_owner_candidate(owner_text):
    return OwnerResolutionResult()
if owner_text in {"我", "本人", "自己"}:
    result = registry.execute(AgentToolCall(call_id="callback_resolve_current_user", tool_name="contact_get_current_user", arguments={}))
    if not result.is_success():
        return OwnerResolutionResult(error_message=build_owner_resolution_error_message(owner_text, result))
    open_id = str(result.data.get("open_id") or result.data.get("user_id") or "")
    return OwnerResolutionResult(open_ids=[open_id] if open_id else [])

result = registry.execute(
    AgentToolCall(
        call_id=f"callback_resolve_owner:{owner_text}",
        tool_name="contact_search_user",
        arguments={"query": owner_text, "page_size": 5, "identity": "user"},
    )
)
if not result.is_success():
    return OwnerResolutionResult(error_message=build_owner_resolution_error_message(owner_text, result))
items = result.data.get("items") or result.data.get("users") or []
if isinstance(items, list):
    for item in items:
        if not isinstance(item, dict):
            continue
        open_id = str(item.get("open_id") or item.get("user_id") or item.get("id") or "")
        if open_id:
            return OwnerResolutionResult(open_ids=[open_id])
return OwnerResolutionResult()
```

合并注意：当前仓库里只有 `confirm_create_task_from_card()` 调用
`resolve_owner_open_ids_for_callback()`。如果协作者分支里还有其它调用点，需要同步改为读取
`.open_ids` / `.error_message`。

### 4.4 新增错误消息构造函数

文件：`core/card_callback.py`

新增函数：

```python
def build_owner_resolution_error_message(owner: str, result: Any) -> str:
    """构造负责人解析失败提示，保留飞书排障信息但不泄露 token。"""

    detail = str(getattr(result, "error_message", "") or getattr(result, "content", "") or "未知错误").strip()
    if "20064" in detail or "refresh token" in detail.lower() or "oauth/token" in detail:
        return (
            f"负责人“{owner}”已填写，但当前用户 OAuth token 已失效或 refresh_token 不可用，"
            "无法通过飞书通讯录解析 open_id。请重新执行用户授权后再点击确认创建。"
        )
    return f"负责人“{owner}”已填写，但飞书通讯录解析失败：{detail}"
```

这里没有输出任何 token 值，只根据错误文本中的 `20064`、`refresh token` 或 `oauth/token`
判断是否提示重新授权。

## 5. 回归测试改动

文件：`tests/test_post_meeting_card_callback.py`

### 5.1 新增失败通讯录 registry

新增在 `FakeRegistry` 后：

```python
class FakeFailingContactRegistry(FakeRegistry):
    """模拟通讯录搜索失败，但任务创建工具本身没有执行。"""

    def execute(self, tool_call):  # noqa: ANN001 - 与项目现有 ToolRegistry 接口保持一致
        if tool_call.tool_name == "contact_search_user":
            return AgentToolResult(
                call_id=tool_call.call_id,
                tool_name="contact.search_user",
                status="error",
                content="工具 contact_search_user 执行失败",
                error_message=(
                    "飞书接口 HTTP 错误 method=POST "
                    "url=https://open.feishu.cn/open-apis/authen/v2/oauth/token "
                    "detail=http_status=400 code=20064"
                ),
            )
        if tool_call.tool_name == "tasks_create_task":
            raise AssertionError("通讯录解析失败时不应继续创建任务")
        return super().execute(tool_call)
```

### 5.2 新增测试用例

新增在 `PostMeetingCardCallbackTest` 中：

```python
def test_owner_resolution_failure_reports_auth_error_instead_of_missing_owner(self) -> None:
    """负责人已填写但通讯录 token 失效时，应提示授权问题而不是误报缺负责人。"""

    client = FakeFeishuClient()
    payload = {
        "event": {
            "context": {"open_message_id": "om_test_auth_failed"},
            "action": {
                "value": {
                    "action": "confirm_create_task",
                    "item_id": "action_test_001",
                    "title": "整理答辩材料",
                    "owner_field": "owner_override__action_test_001",
                    "due_date_field": "due_date_override__action_test_001",
                    "meeting_id": "meeting_test_001",
                    "minute_token": "minute_test_001",
                    "project_id": "meetflow",
                },
                "form_value": {
                    "pending_form_action_test_001": {
                        "owner_override__action_test_001": "李健文",
                        "due_date_override__action_test_001": "2026-05-13",
                    }
                },
            },
        }
    }

    with patch("adapters.create_feishu_tool_registry", return_value=FakeFailingContactRegistry()):
        result = handle_post_meeting_card_callback(
            payload=payload,
            settings=self.settings,
            client=client,
            storage=self.storage,
            policy=AgentPolicy(),
        )

    self.assertEqual(result.status, "error")
    self.assertIn("OAuth token 已失效", result.message)
    self.assertNotIn("缺少负责人", result.message)
    records = load_pending_action_records(self.settings)
    self.assertEqual(records["action_test_001"]["status"], "pending")
    self.assertEqual(records["action_test_001"]["value"]["owner"], "李健文")
    self.assertEqual(records["action_test_001"]["value"]["due_date"], "2026-05-13")
```

这个测试验证三件事：

- 已填写的负责人和截止时间能被回调解析出来并保存。
- 通讯录 token 失败时不再误报“缺少负责人”。
- 不会继续调用 `tasks.create_task`。

## 6. 验证命令

合并后建议至少运行：

```bash
python3 -m py_compile core/card_callback.py tests/test_post_meeting_card_callback.py
python3 -m unittest tests.test_post_meeting_card_callback
```

本分支验证结果：

```text
python3 -m py_compile core/card_callback.py tests/test_post_meeting_card_callback.py
通过

python3 -m unittest tests.test_post_meeting_card_callback
Ran 25 tests in 8.659s
OK
```

## 7. 运行期注意事项

这次代码修复的是“错误分支提示”和“避免继续误创建”的问题，不会自动修复飞书 token。

如果真实环境再次出现 `code=20064`，仍需要重新执行用户 OAuth：

```bash
python3 scripts/oauth_device_login.py
```

授权完成后要重启正在运行的 M4 回调长连接服务：

```bash
python3 scripts/card_send_live.py m4-callback --log-level info
```

原因：回调服务启动时会读取 `config/settings.local.json` 并创建 `FeishuClient`。如果旧进程已经持有过期
refresh token，即使本地配置后来被新授权写入，旧进程也不一定会自动使用最新 token。

也建议检查是否有旧环境变量覆盖本地配置：

```bash
env | grep MEETFLOW_FEISHU_USER
```

如果存在旧的 `MEETFLOW_FEISHU_USER_ACCESS_TOKEN` 或
`MEETFLOW_FEISHU_USER_REFRESH_TOKEN`，需要清理后重新启动服务。

## 8. 合并检查清单

- 已合并 `OwnerResolutionResult`。
- 已修改 `confirm_create_task_from_card()` 中负责人解析失败分支。
- 已修改 `resolve_owner_open_ids_for_callback()` 返回 `OwnerResolutionResult`。
- 已新增 `build_owner_resolution_error_message()`。
- 已新增 `FakeFailingContactRegistry` 和
  `test_owner_resolution_failure_reports_auth_error_instead_of_missing_owner()`。
- 已运行 `py_compile` 和 `tests.test_post_meeting_card_callback`。
- 已确认真实写操作仍需经过 `AgentPolicy`，没有绕过任务创建安全边界。

## 9. 同步到风险巡检解耦分支记录

2026-05-13 已将本修复同步到本地 `feature/risk-scan-decoupling-20260512`，
并关联远端 `origin/feature/risk-scan-decoupling-20260512`。

本次同步以 `8eb1a0dc` 的负责人解析修复为来源，未合并整个
`d3-post-meeting-card-enhancement-plan` 分支，避免覆盖风险巡检解耦分支已有逻辑。
冲突处理时保留了目标分支已经具备的两项能力：

- 负责人填写“我 / 本人 / 自己”时优先使用卡片操作人 `open_id`。
- 普通姓名解析继续使用 `identity="tenant"` 的通讯录兜底路径。

同步后的关键文件：

- `.gitignore`
- `core/card_callback.py`
- `tests/test_post_meeting_card_callback.py`
- `docs/tasks/d4-minute-agent-task-card-plan.md`
- `docs/tasks/d4-owner-resolution-auth-error-merge-note.md`
- `tasks.md`

验证结果：

```bash
python3 -m py_compile core/card_callback.py tests/test_post_meeting_card_callback.py
python3 -m unittest tests.test_post_meeting_card_callback
git diff --check
```

结果：均通过；当前 `tests.test_post_meeting_card_callback` 共 32 条测试通过。

剩余风险：本次只做本地分支同步和回归测试，未执行真实飞书回调联调；真实环境仍依赖当前用户重新授权、
回调服务重启和飞书开放平台回调配置。
