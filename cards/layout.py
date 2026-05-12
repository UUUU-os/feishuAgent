from __future__ import annotations

from typing import Any


CARD_FORMAT_VERSION = "meetflow_card_v1"
DEFAULT_BODY_PADDING = "12px 12px 12px 12px"


def build_interactive_card(
    *,
    title: str,
    template: str,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造 M3/M4 旧版 interactive card 的统一外壳。

    飞书卡片对顶层字段较敏感，因此这里不额外塞自定义 metadata，只把通用
    config/header/元素顺序固定下来，让不同工作流的卡片长相和 JSON 结构稳定。
    """

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": build_header(title=title, template=template),
        "elements": elements,
    }


def build_schema2_card(
    *,
    title: str,
    template: str,
    elements: list[dict[str, Any]],
    update_multi: bool = True,
    padding: str = DEFAULT_BODY_PADDING,
) -> dict[str, Any]:
    """构造 M4 按钮/表单卡片的统一 schema 2.0 外壳。"""

    return {
        "schema": "2.0",
        "config": {
            "update_multi": update_multi,
        },
        "header": build_header(title=title, template=template),
        "body": {
            "direction": "vertical",
            "padding": padding,
            "elements": elements,
        },
    }


def build_header(*, title: str, template: str) -> dict[str, Any]:
    """构造统一卡片头，限制标题长度避免移动端显示抖动。"""

    return {
        "template": normalize_template(template),
        "title": {
            "tag": "plain_text",
            "content": clamp_text(title, 60),
        },
    }


def markdown(content: str) -> dict[str, Any]:
    """构造旧版和新版卡片都可使用的 markdown 元素。"""

    return {"tag": "markdown", "content": safe_text(content)}


def lark_md_div(content: str) -> dict[str, Any]:
    """构造标准 lark_md 文本区块。"""

    return {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": safe_text(content),
        },
    }


def divider() -> dict[str, Any]:
    """构造统一分隔线元素。"""

    return {"tag": "hr"}


def clamp_text(value: Any, max_length: int) -> str:
    """按字符数截断卡片文本，避免 header 和按钮卡状态标题过长。"""

    text = safe_text(value)
    if max_length <= 0 or len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}..."


def normalize_template(template: str) -> str:
    """限制 header 颜色模板到飞书常用值，避免调用方传入不可渲染颜色。"""

    clean = safe_text(template) or "blue"
    allowed = {"blue", "wathet", "turquoise", "green", "yellow", "orange", "red", "carmine", "violet", "purple", "indigo", "grey"}
    return clean if clean in allowed else "blue"


def safe_text(value: Any) -> str:
    """清洗卡片文本，避免 None 或异常对象进入飞书卡片 JSON。"""

    return str(value or "").strip()
