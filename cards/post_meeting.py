from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def build_post_meeting_summary_card(artifacts: Any) -> dict[str, Any]:
    """构造会后总结卡片的飞书 interactive card JSON。

    这张卡片用于展示会议产出，而不是触发写操作。任务是否创建、是否待确认，
    都来自 M4 业务层已经标记好的结构，卡片层只负责清晰呈现。
    """

    summary = getattr(artifacts, "meeting_summary", None)
    workflow_input = getattr(artifacts, "workflow_input", None)
    action_items = list(getattr(artifacts, "action_items", []) or [])
    pending_items = list(getattr(artifacts, "pending_action_items", []) or [])
    if not pending_items:
        pending_items = [item for item in action_items if getattr(item, "needs_confirm", False)]
    ready_items = [item for item in action_items if not getattr(item, "needs_confirm", False)]
    decisions = normalize_text_items(getattr(artifacts, "decisions", []) or getattr(summary, "decisions", []))
    open_questions = normalize_text_items(
        getattr(artifacts, "open_questions", []) or getattr(summary, "open_questions", [])
    )
    source_url = safe_text(getattr(workflow_input, "source_url", ""))
    related_resources = collect_related_resources(artifacts)

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": build_summary_overview_markdown(artifacts)},
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_text_section("关键结论", decisions, "暂无明确结论"),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_action_items_markdown("字段完整候选（仍需确认）", ready_items, "暂无字段完整任务"),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_action_items_markdown("待确认任务", pending_items, "暂无待确认任务"),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_text_section("开放问题", open_questions, "暂无开放问题"),
            },
        },
    ]
    elements.extend(render_related_resource_elements(related_resources))
    if source_url:
        elements.append(
            {
                "tag": "markdown",
                "content": f"**原始资料**：{render_link('查看会议纪要', source_url)}",
            }
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": choose_summary_header_template(ready_items, pending_items),
            "title": {
                "tag": "plain_text",
                "content": f"MeetFlow 会后总结：{safe_text(getattr(summary, 'topic', '')) or '待识别会议'}",
            },
        },
        "elements": elements,
    }


def build_pending_action_items_card(artifacts: Any) -> dict[str, Any]:
    """构造待确认任务卡片。

    卡片突出负责人、截止时间等关键字段，并直接提供表单输入 + 按钮交互。
    用户可以在卡片里修改负责人/截止时间，然后点击“修改信息”“确认创建”
    或“拒绝创建”。真正创建任务仍必须由后端回调再次经过 ToolRegistry 和
    AgentPolicy。
    """

    summary = getattr(artifacts, "meeting_summary", None)
    pending_items = list(getattr(artifacts, "pending_action_items", []) or [])
    if not pending_items:
        pending_items = [
            item
            for item in list(getattr(artifacts, "action_items", []) or [])
            if getattr(item, "needs_confirm", False)
        ]
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": f"**会议**：{safe_text(getattr(summary, 'topic', '')) or '待识别会议'}",
        },
        {
            "tag": "markdown",
            "content": f"**待确认任务数**：{len(pending_items)}\n"
            "可直接在卡片中补充负责人/截止时间，然后点击按钮完成处理。",
        },
    ]
    if pending_items:
        elements.extend(render_pending_item_review_elements(pending_items))
    else:
        elements.append({"tag": "markdown", "content": "暂无待确认任务。"})

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
        },
        "header": {
            "template": "orange" if pending_items else "green",
            "title": {"tag": "plain_text", "content": "MeetFlow 待确认任务"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


def build_pending_action_item_reaction_card(artifacts: Any, item: Any) -> dict[str, Any]:
    """构造单个待确认任务的 reaction 确认卡片。

    Reaction 是消息级别的交互，因此一条消息只承载一个 Action Item，
    watcher 才能通过 message_id 准确映射回任务。
    """

    summary = getattr(artifacts, "meeting_summary", None)
    item_id = safe_text(getattr(item, "item_id", ""))
    title = safe_text(getattr(item, "title", "")) or "未命名任务"
    owner = safe_text(getattr(item, "owner", "")) or "待补充"
    due_date = safe_text(getattr(item, "due_date", "")) or "待补充"
    reason = safe_text((getattr(item, "extra", {}) or {}).get("confirm_reason", "")) or "待人工复核"
    snippet = first_evidence_snippet(item)
    lines = [
        f"**会议**：{safe_text(getattr(summary, 'topic', '')) or '待识别会议'}",
        f"**任务**：{title}",
        f"任务 ID：`{item_id}`",
        f"负责人：**{owner}**",
        f"截止时间：**{due_date}**",
        f"待确认原因：{reason}",
    ]
    if snippet:
        lines.append(f"证据：{snippet}")
    lines.extend(
        [
            "",
            "**一键处理**",
            "- 给这条消息点 `✅ / CheckMark / DONE / OK / THUMBSUP`：确认创建",
            "- 给这条消息点 `❌ / CrossMark / No / ThumbsDown`：拒绝创建",
            f"- 需要补字段时回复：`确认创建 {item_id} 负责人=姓名 截止=明天`",
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text", "content": "MeetFlow 待确认任务"},
        },
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }


def build_pending_action_item_button_card(
    artifacts: Any,
    item: Any,
    *,
    mode: str = "review",
    status_message: str = "",
    status_kind: str = "info",
    task_url: str = "",
) -> dict[str, Any]:
    """构造单个待确认任务的新版 schema 2.0 待确认卡。

    `mode` 用于区分三种状态：
    - `review`：默认待确认态，可直接确认/修改/拒绝
    - `edit`：突出展示可编辑输入框，提示用户补齐字段
    - `resolved`：确认创建或拒绝后展示结果态，移除交互按钮

    根据飞书官方 JSON 2.0 表单容器说明，输入框必须放在根级 `form` 容器内，
    按钮交互使用 `behaviors + form_action_type=submit`。之前看不到输入框的根因，
    是把旧版 interactive card 的输入框 / 按钮写法混进了新版卡片。
    """

    summary = getattr(artifacts, "meeting_summary", None)
    extra = getattr(item, "extra", {}) or {}
    item_id = safe_text(getattr(item, "item_id", ""))
    title = safe_text(getattr(item, "title", "")) or "未命名任务"
    owner = safe_text(getattr(item, "owner", ""))
    due_date = safe_text(getattr(item, "due_date", ""))
    priority = safe_text(getattr(item, "priority", "")) or "medium"
    confidence = float(getattr(item, "confidence", 0.0) or 0.0)
    reason = safe_text(extra.get("confirm_reason", "")) or "待人工复核"
    snippet = first_evidence_snippet(item)
    value = build_pending_task_button_value(item)
    owner_field = f"owner_override__{item_id}"
    due_date_field = f"due_date_override__{item_id}"
    mode = safe_text(mode) or "review"
    status_message = safe_text(status_message)
    status_kind = safe_text(status_kind) or "info"

    header_template = "orange"
    if mode == "resolved":
        header_template = "green" if status_kind == "success" else "red" if status_kind == "error" else "blue"
    elif mode == "edit":
        header_template = "wathet"

    detail_lines = [
        f"**会议**：{safe_text(getattr(summary, 'topic', '')) or '待识别会议'}",
        f"**任务**：{title}",
        f"任务 ID：`{item_id}`",
        f"负责人：**{owner or '待补充'}**",
        f"截止时间：**{due_date or '待补充'}**",
        f"优先级：`{priority}`｜置信度：`{confidence:.2f}`",
        f"待确认原因：{reason}",
    ]
    if snippet:
        detail_lines.append(f"证据：{snippet}")
    if status_message:
        detail_lines.append(f"处理结果：{status_message}")
    if task_url:
        detail_lines.append(f"[查看任务详情]({task_url})")

    body_elements: list[dict[str, Any]] = [{"tag": "markdown", "content": "\n".join(detail_lines)}]
    if mode != "resolved":
        body_elements.append(
            build_pending_action_item_schema2_form(
                value=value,
                item_id=item_id,
                owner=owner,
                due_date=due_date,
                owner_field=owner_field,
                due_date_field=due_date_field,
                mode=mode,
            )
        )
    return {
        "schema": "2.0",
        "config": {
            # 允许后端通过消息更新接口刷新整张共享卡片，否则按钮点击后即便后端
            # 收到回调，也可能因为飞书不允许更新共享卡片而导致前端状态不变化。
            "update_multi": True,
        },
        "header": {
            "template": header_template,
            "title": {
                "tag": "plain_text",
                "content": f"{'MeetFlow 任务结果' if mode == 'resolved' else 'MeetFlow 待确认任务'}：{title[:22]}",
            },
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": body_elements,
        },
    }


def build_pending_action_item_schema2_form(
    *,
    value: dict[str, Any],
    item_id: str,
    owner: str,
    due_date: str,
    owner_field: str,
    due_date_field: str,
    mode: str,
) -> dict[str, Any]:
    """构造根级 schema 2.0 表单容器。

    关键约束来自官方说明：
    1. `form` 必须位于卡片根节点下；
    2. 表单内的提交按钮使用 `form_action_type=submit`；
    3. 请求回调动作通过 `behaviors=[{type: callback, value: ...}]` 绑定。
    """

    default_owner = "" if owner == "待补充" else owner
    default_due_date = "" if due_date == "待补充" else due_date
    helper_text = (
        "请填写负责人或截止时间，再点击“保存修改”或“确认创建”。"
        if mode == "edit"
        else "可直接在卡片中补充负责人或截止时间，然后点击按钮提交。"
    )
    return {
        "tag": "form",
        "name": f"pending_form_{item_id}",
        "fallback": {
            "tag": "fallback_text",
            "text": {"tag": "plain_text", "content": "当前飞书客户端版本过低，暂不支持表单编辑。"},
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**修改字段**\n{helper_text}",
            },
            {
                "tag": "input",
                "name": owner_field,
                "input_type": "text",
                "width": "fill",
                "placeholder": {"tag": "plain_text", "content": "负责人，例如：张三 / 我"},
                "default_value": default_owner,
                "fallback": {
                    "tag": "fallback_text",
                    "text": {"tag": "plain_text", "content": "负责人输入框仅支持在较新版本飞书客户端中编辑。"},
                },
            },
            {
                "tag": "input",
                "name": due_date_field,
                "input_type": "text",
                "width": "fill",
                "placeholder": {"tag": "plain_text", "content": "截止时间，例如：明天 / 2026-05-03"},
                "default_value": default_due_date,
                "fallback": {
                    "tag": "fallback_text",
                    "text": {"tag": "plain_text", "content": "截止时间输入框仅支持在较新版本飞书客户端中编辑。"},
                },
            },
            {
                "tag": "column_set",
                "flex_mode": "trisect",
                "horizontal_spacing": "8px",
                "horizontal_align": "left",
                "columns": [
                    build_form_button_column(
                        text="确认创建",
                        button_name=f"confirm_{item_id}",
                        button_type="primary_filled",
                        callback_value={
                            **value,
                            "action": "confirm_create_task",
                            "owner_field": owner_field,
                            "due_date_field": due_date_field,
                        },
                    ),
                    build_form_button_column(
                        text="保存修改" if mode == "edit" else "修改信息",
                        button_name=f"edit_{item_id}",
                        button_type="primary" if mode == "edit" else "default",
                        callback_value={
                            **value,
                            "action": "edit_task_fields",
                            "owner_field": owner_field,
                            "due_date_field": due_date_field,
                        },
                    ),
                    build_form_button_column(
                        text="拒绝创建",
                        button_name=f"reject_{item_id}",
                        button_type="danger",
                        callback_value={
                            **value,
                            "action": "reject_create_task",
                            "owner_field": owner_field,
                            "due_date_field": due_date_field,
                        },
                    ),
                ],
            },
        ],
    }


def build_form_button_column(
    *,
    text: str,
    button_name: str,
    button_type: str,
    callback_value: dict[str, Any],
) -> dict[str, Any]:
    """构造 schema 2.0 表单提交按钮列。"""

    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "elements": [
            {
                "tag": "button",
                "name": button_name,
                "text": {"tag": "plain_text", "content": text},
                "type": button_type,
                "width": "fill",
                "form_action_type": "submit",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": callback_value,
                    }
                ],
            }
        ],
        "padding": "0px 0px 0px 0px",
        "vertical_spacing": "8px",
    }


def build_pending_action_item_callback_card(
    item_value: dict[str, Any],
    *,
    topic: str = "",
    mode: str = "review",
    status_message: str = "",
    status_kind: str = "info",
    task_url: str = "",
) -> dict[str, Any]:
    """根据本地 pending registry 中的按钮 value 重建单条卡片。

    回调处理时通常只拿得到 `item_id + value`，未必能回到完整 artifacts。
    这里把 value 转成最小对象，复用统一卡片模板，保证回调后的卡片和首次发送
    的卡片长相一致，只是状态不同。
    """

    evidence_refs = []
    for ref in list(item_value.get("evidence_refs") or []):
        if not isinstance(ref, dict):
            continue
        evidence_refs.append(
            SimpleNamespace(
                source_type=safe_text(ref.get("source_type", "")),
                source_id=safe_text(ref.get("source_id", "")),
                source_url=safe_text(ref.get("source_url", "")),
                snippet=safe_text(ref.get("snippet", "")),
                updated_at=safe_text(ref.get("updated_at", "")),
            )
        )
    item = SimpleNamespace(
        item_id=safe_text(item_value.get("item_id", "")),
        title=safe_text(item_value.get("title", "")),
        owner=safe_text(item_value.get("owner", "")),
        due_date=safe_text(item_value.get("due_date", "")),
        priority=safe_text(item_value.get("priority", "")) or "medium",
        confidence=float(item_value.get("confidence", 0.0) or 0.0),
        evidence_refs=evidence_refs,
        extra={
            "confirm_reason": safe_text((item_value.get("extra") or {}).get("confirm_reason", "")),
            "meeting_id": safe_text(item_value.get("meeting_id", "")),
            "calendar_event_id": safe_text(item_value.get("calendar_event_id", "")),
            "minute_token": safe_text(item_value.get("minute_token", "")),
            "project_id": safe_text(item_value.get("project_id", "")) or "meetflow",
            "missing_fields": list((item_value.get("extra") or {}).get("missing_fields", []) or []),
        },
    )
    artifacts = SimpleNamespace(meeting_summary=SimpleNamespace(topic=topic))
    return build_pending_action_item_button_card(
        artifacts,
        item,
        mode=mode,
        status_message=status_message,
        status_kind=status_kind,
        task_url=task_url,
    )


def build_pending_action_item_form_element(
    *,
    value: dict[str, Any],
    item_id: str,
    owner: str,
    due_date: str,
    owner_field: str,
    due_date_field: str,
    mode: str,
) -> dict[str, Any]:
    """构造总卡里单条待确认任务的 schema 2.0 表单区。"""

    edit_hint = (
        "**修改字段**\n请先填写负责人或截止时间，再点击“保存修改”或直接“确认创建”。"
        if mode == "edit"
        else "**修改字段**\n留空表示保留当前识别结果；填写后可点击“修改信息”暂存，或直接“确认创建”。"
    )
    return {
        "tag": "form",
        "name": f"pending_form_{item_id}",
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": edit_hint},
                {
                    "tag": "input",
                    "name": owner_field,
                    "input_type": "text",
                    "placeholder": {"tag": "plain_text", "content": "负责人，例如：张三 / 我"},
                    "default_value": "" if owner == "待补充" else owner,
                },
                {
                    "tag": "input",
                    "name": due_date_field,
                    "input_type": "text",
                    "placeholder": {"tag": "plain_text", "content": "截止时间，例如：明天 / 2026-05-03"},
                    "default_value": "" if due_date == "待补充" else due_date,
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "确认创建"},
                            "type": "primary",
                            "form_action_type": "submit",
                            "value": {
                                **value,
                                "action": "confirm_create_task",
                                "owner_field": owner_field,
                                "due_date_field": due_date_field,
                            },
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "保存修改" if mode == "edit" else "修改信息"},
                            "form_action_type": "submit",
                            "value": {
                                **value,
                                "action": "edit_task_fields",
                                "owner_field": owner_field,
                                "due_date_field": due_date_field,
                            },
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "拒绝创建"},
                            "type": "danger",
                            "value": {
                                **value,
                                "action": "reject_create_task",
                                "owner_field": owner_field,
                                "due_date_field": due_date_field,
                            },
                        },
                    ],
                },
            ],
        },
    }


def build_auto_created_tasks_card(artifacts: Any, created_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """构造任务创建后的提示卡片。

    函数名保留兼容旧脚本。M4 当前只在人工确认后创建任务，调用方应只在
    `tasks.create_task` 成功后传入创建结果。
    """

    summary = getattr(artifacts, "meeting_summary", None)
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": f"**会议**：{safe_text(getattr(summary, 'topic', '')) or '待识别会议'}\n"
            f"**已创建任务数**：{len(created_tasks)}",
        }
    ]
    if created_tasks:
        lines = ["**已创建任务**"]
        for index, item in enumerate(created_tasks[:8], start=1):
            task_mapping = item.get("task_mapping", {}) if isinstance(item, dict) else {}
            task_id = safe_text(task_mapping.get("task_id", ""))
            title = safe_text(item.get("title", "")) or safe_text(task_mapping.get("title", "")) or "未命名任务"
            owner = safe_text(task_mapping.get("owner", "")) or "待查看任务详情"
            due_date = safe_text(task_mapping.get("due_date", "")) or "待查看任务详情"
            suffix = f"（task_id：`{task_id}`）" if task_id else ""
            lines.append(f"{index}. **{title}**{suffix}\n   负责人：{owner}｜截止：{due_date}")
        if len(created_tasks) > 8:
            lines.append(f"... 另有 {len(created_tasks) - 8} 条未展示")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})
    else:
        elements.append({"tag": "markdown", "content": "本次没有创建任务。"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green" if created_tasks else "blue",
            "title": {"tag": "plain_text", "content": "MeetFlow 已创建任务提醒"},
        },
        "elements": elements,
    }


def build_summary_overview_markdown(artifacts: Any) -> str:
    """渲染会后总结卡片顶部概览。"""

    summary = getattr(artifacts, "meeting_summary", None)
    workflow_input = getattr(artifacts, "workflow_input", None)
    action_items = list(getattr(artifacts, "action_items", []) or [])
    pending_items = list(getattr(artifacts, "pending_action_items", []) or [])
    if not pending_items:
        pending_items = [item for item in action_items if getattr(item, "needs_confirm", False)]
    ready_count = len([item for item in action_items if not getattr(item, "needs_confirm", False)])
    return "\n".join(
        [
            f"**主题**：{safe_text(getattr(summary, 'topic', '')) or safe_text(getattr(workflow_input, 'topic', '')) or '待识别'}",
            f"**项目**：{safe_text(getattr(summary, 'project_id', '')) or safe_text(getattr(workflow_input, 'project_id', '')) or '未指定'}",
            f"**行动项**：{len(action_items)} 条  |  **字段完整候选**：{ready_count} 条  |  **需人工确认**：{len(pending_items)} 条",
        ]
    )


def render_action_items_markdown(title: str, items: list[Any], empty_text: str) -> str:
    """渲染行动项区块。"""

    lines = [f"**{title}**"]
    if not items:
        lines.append(empty_text)
        return "\n".join(lines)
    for index, item in enumerate(items[:8], start=1):
        lines.append(f"{index}. {render_action_item_markdown(item)}")
    if len(items) > 8:
        lines.append(f"... 另有 {len(items) - 8} 条未展示")
    return "\n".join(lines)


def render_action_item_markdown(action_item: Any) -> str:
    """渲染单条行动项，包含负责人、截止时间、置信度和待确认原因。"""

    title = safe_text(getattr(action_item, "title", "")) or "未命名任务"
    owner = safe_text(getattr(action_item, "owner", "")) or "待确认负责人"
    due_date = safe_text(getattr(action_item, "due_date", "")) or "待确认截止时间"
    confidence = float(getattr(action_item, "confidence", 0.0) or 0.0)
    reason = safe_text(getattr(action_item, "extra", {}).get("confirm_reason", ""))
    status = "待补充确认" if getattr(action_item, "needs_confirm", False) else "字段完整，待人工确认"
    suffix = f"；原因：{reason}" if reason else ""
    return f"**{title}**（{status}，负责人：{owner}，截止：{due_date}，置信度：{confidence:.2f}{suffix}）"


def render_pending_items_detail_markdown(items: list[Any]) -> str:
    """渲染待确认任务详情，突出缺失字段和证据片段。"""

    lines = ["**待确认明细**"]
    for index, item in enumerate(items[:8], start=1):
        extra = getattr(item, "extra", {}) or {}
        missing = "、".join(field_label(str(field)) for field in extra.get("missing_fields", [])) or "待人工复核"
        reason = safe_text(extra.get("confirm_reason", "")) or missing
        snippet = first_evidence_snippet(item)
        evidence = f"\n   证据：{snippet}" if snippet else ""
        lines.append(f"{index}. {safe_text(getattr(item, 'title', '')) or '未命名任务'}\n   缺失/原因：{reason}{evidence}")
    return "\n".join(lines)


def render_pending_item_review_elements(items: list[Any]) -> list[dict[str, Any]]:
    """渲染待确认任务的关键字段复核区和按钮表单。"""

    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": "**待确认明细**"}]
    for index, item in enumerate(items[:8], start=1):
        extra = getattr(item, "extra", {}) or {}
        item_id = safe_text(getattr(item, "item_id", ""))
        title = safe_text(getattr(item, "title", "")) or "未命名任务"
        owner = safe_text(getattr(item, "owner", "")) or "待补充"
        due_date = safe_text(getattr(item, "due_date", "")) or "待补充"
        priority = safe_text(getattr(item, "priority", "")) or "medium"
        confidence = float(getattr(item, "confidence", 0.0) or 0.0)
        missing = "、".join(field_label(str(field)) for field in extra.get("missing_fields", [])) or "待人工复核"
        reason = safe_text(extra.get("confirm_reason", "")) or missing
        snippet = first_evidence_snippet(item)
        detail_lines = [
            f"**{index}. {title}**",
            f"任务 ID：`{item_id}`",
            f"负责人：**{owner}**",
            f"截止时间：**{due_date}**",
            f"优先级：`{priority}`｜置信度：`{confidence:.2f}`",
            f"待确认原因：{reason}",
        ]
        if snippet:
            detail_lines.append(f"证据：{snippet}")
        value = build_pending_task_button_value(item)
        owner_field = f"owner_override__{item_id}"
        due_date_field = f"due_date_override__{item_id}"
        elements.append({"tag": "markdown", "content": "\n".join(detail_lines)})
        elements.append(
            build_pending_action_item_form_element(
                value=value,
                item_id=item_id,
                owner=owner,
                due_date=due_date,
                owner_field=owner_field,
                due_date_field=due_date_field,
                mode="review",
            )
        )
        elements.append({"tag": "hr"})
    if len(items) > 8:
        elements.append({"tag": "markdown", "content": f"... 另有 {len(items) - 8} 条未展示"})
    return elements


def build_pending_task_button_value(item: Any) -> dict[str, Any]:
    """构造按钮回调所需的最小业务上下文。"""

    extra = getattr(item, "extra", {}) or {}
    evidence_refs = []
    for ref in list(getattr(item, "evidence_refs", []) or [])[:3]:
        if hasattr(ref, "to_dict"):
            evidence_refs.append(ref.to_dict())
            continue
        if isinstance(ref, dict):
            evidence_refs.append(dict(ref))
            continue
        evidence_refs.append(
            {
                "source_type": safe_text(getattr(ref, "source_type", "")),
                "source_id": safe_text(getattr(ref, "source_id", "")),
                "source_url": safe_text(getattr(ref, "source_url", "")),
                "snippet": safe_text(getattr(ref, "snippet", "")),
                "updated_at": safe_text(getattr(ref, "updated_at", "")),
            }
        )
    return {
        "item_id": safe_text(getattr(item, "item_id", "")),
        "title": safe_text(getattr(item, "title", "")),
        "owner": safe_text(getattr(item, "owner", "")),
        "due_date": safe_text(getattr(item, "due_date", "")),
        "priority": safe_text(getattr(item, "priority", "")) or "medium",
        "confidence": float(getattr(item, "confidence", 0.0) or 0.0),
        "meeting_id": safe_text(extra.get("meeting_id", "")),
        "calendar_event_id": safe_text(extra.get("calendar_event_id", "")),
        "minute_token": safe_text(extra.get("minute_token", "")),
        "project_id": safe_text(extra.get("project_id", "")) or "meetflow",
        "meeting_topic": safe_text(extra.get("meeting_topic", "")),
        "extra": {
            "confirm_reason": safe_text(extra.get("confirm_reason", "")),
            "missing_fields": list(extra.get("missing_fields", []) or []),
        },
        "evidence_refs": evidence_refs,
    }


def render_text_section(title: str, items: list[Any], empty_text: str) -> str:
    """渲染决策和开放问题等文本区块。"""

    lines = [f"**{title}**"]
    if not items:
        lines.append(empty_text)
        return "\n".join(lines)
    for index, item in enumerate(items[:6], start=1):
        lines.append(f"{index}. {safe_text(getattr(item, 'content', item))}")
    if len(items) > 6:
        lines.append(f"... 另有 {len(items) - 6} 条未展示")
    return "\n".join(lines)


def render_related_resource_elements(resources: list[Any]) -> list[dict[str, Any]]:
    """渲染会后总结相关背景资料区块。"""

    if not resources:
        return []
    return [
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": render_related_resources_markdown(resources),
            },
        },
    ]


def render_related_resources_markdown(resources: list[Any]) -> str:
    """把 M3 RAG 召回结果或上下文资源渲染为卡片中的背景知识链接。"""

    lines = ["**相关背景资料**"]
    for index, resource in enumerate(resources[:6], start=1):
        title = safe_text(getattr(resource, "title", "")) or safe_text(getattr(resource, "resource_id", "")) or f"资料 {index}"
        source_url = safe_text(getattr(resource, "source_url", ""))
        snippet = safe_text(getattr(resource, "snippet", "")) or safe_text(getattr(resource, "content", ""))[:80]
        score = getattr(resource, "score", None)
        score_text = f"｜相关度 `{float(score):.2f}`" if isinstance(score, int | float) else ""
        lines.append(f"{index}. {render_link(title, source_url)}{score_text}")
        if snippet:
            lines.append(f"   {snippet[:120]}")
    if len(resources) > 6:
        lines.append(f"... 另有 {len(resources) - 6} 条未展示")
    return "\n".join(lines)


def render_evidence_markdown(evidence_refs: list[Any]) -> str:
    """渲染证据引用列表。"""

    lines = ["**证据引用**"]
    for index, ref in enumerate(evidence_refs[:8], start=1):
        source_type = safe_text(getattr(ref, "source_type", ""))
        source_id = safe_text(getattr(ref, "source_id", "")) or f"ref_{index}"
        source_url = safe_text(getattr(ref, "source_url", ""))
        snippet = safe_text(getattr(ref, "snippet", ""))[:100]
        lines.append(f"- {render_link(f'`{source_id}`', source_url)} {source_type}：{snippet}")
    return "\n".join(lines)


def collect_evidence_refs(*groups: Any) -> list[Any]:
    """从行动项、决策和开放问题中收集去重后的证据引用。"""

    refs: list[Any] = []
    seen: set[str] = set()
    for group in groups:
        for item in list(group or []):
            for ref in list(getattr(item, "evidence_refs", []) or []):
                key = "|".join(
                    [
                        safe_text(getattr(ref, "source_type", "")),
                        safe_text(getattr(ref, "source_id", "")),
                        safe_text(getattr(ref, "snippet", "")),
                    ]
                )
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
    return refs


def normalize_text_items(items: list[Any]) -> list[Any]:
    """把字符串和结构对象统一成可渲染列表。"""

    return [item for item in items if safe_text(getattr(item, "content", item))]


def collect_related_resources(artifacts: Any) -> list[Any]:
    """收集会后卡片可展示的相关资料。

    优先使用 M3 轻量 RAG 召回写入 `artifacts.extra["related_knowledge_hits"]`
    的结果；没有召回结果时回退到工作流输入中的 `related_resources`。
    """

    extra = getattr(artifacts, "extra", {}) or {}
    hits = list(extra.get("related_knowledge_hits", []) or [])
    if hits:
        return hits
    workflow_input = getattr(artifacts, "workflow_input", None)
    return list(getattr(workflow_input, "related_resources", []) or [])


def first_evidence_snippet(item: Any) -> str:
    """读取行动项第一条证据片段。"""

    evidence_refs = list(getattr(item, "evidence_refs", []) or [])
    if not evidence_refs:
        return ""
    return safe_text(getattr(evidence_refs[0], "snippet", ""))[:100]


def choose_summary_header_template(ready_items: list[Any], pending_items: list[Any]) -> str:
    """根据任务状态选择会后总结卡片颜色。"""

    if pending_items:
        return "orange"
    if ready_items:
        return "green"
    return "blue"


def render_link(label: str, url: str) -> str:
    """在有来源 URL 时渲染飞书 Markdown 链接。"""

    clean_label = safe_text(label)
    clean_url = safe_text(url)
    if not clean_label:
        return ""
    if not clean_url:
        return clean_label
    return f"[{clean_label}]({clean_url})"


def field_label(field_name: str) -> str:
    """把内部字段名转换为卡片上的中文字段名。"""

    labels = {
        "title": "任务标题",
        "owner": "负责人",
        "due_date": "截止时间",
        "evidence_refs": "证据引用",
    }
    return labels.get(field_name, field_name)


def safe_text(value: Any) -> str:
    """清洗卡片文本，避免 None 或异常对象进入飞书卡片 JSON。"""

    return str(value or "").strip()
