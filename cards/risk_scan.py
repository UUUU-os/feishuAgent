from __future__ import annotations

import time
from typing import Any

from core.risk_scan import RiskNotificationDecision, RiskRuleResult, RiskScanResult


def build_risk_scan_card(
    decision: RiskNotificationDecision,
    scan_result: RiskScanResult,
) -> dict[str, Any]:
    """构造风险巡检飞书 interactive card。

    风险提醒需要低噪声，所以卡片采用聚合展示：一次巡检最多发一张卡，
    卡内列出本次真正需要提醒的风险，同时展示被降噪跳过的数量。
    """

    risks = decision.notify_risks or scan_result.risks[:3]
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": render_risk_summary(decision, scan_result),
        },
        {"tag": "hr"},
    ]

    if risks:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": render_risk_items_markdown(risks),
                },
            }
        )
    else:
        elements.append(
            {
                "tag": "markdown",
                "content": "本次巡检没有需要推送的任务风险。",
            }
        )

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": choose_header_template(decision, scan_result),
            "title": {
                "tag": "plain_text",
                "content": "MeetFlow 风险巡检提醒",
            },
        },
        "elements": elements,
    }


def render_risk_summary(decision: RiskNotificationDecision, scan_result: RiskScanResult) -> str:
    """生成卡片顶部概览文本。"""

    generated_at = format_timestamp(scan_result.generated_at)
    return "\n".join(
        [
            f"**巡检时间**：{generated_at}",
            f"**扫描任务数**：{scan_result.scanned_count}",
            f"**命中风险数**：{scan_result.risk_count}",
            f"**本次提醒**：{len(decision.notify_risks)} 条",
            f"**降噪跳过**：{len(decision.suppressed_risks)} 条",
            f"**决策说明**：{safe_text(decision.reason)}",
        ]
    )


def render_risk_items_markdown(risks: list[RiskRuleResult]) -> str:
    """把风险列表渲染为飞书 Markdown。"""

    lines = ["**风险任务**"]
    for index, risk in enumerate(risks[:5], start=1):
        lines.extend(render_risk_item_lines(index, risk))
    return "\n".join(lines)


def render_risk_item_lines(index: int, risk: RiskRuleResult) -> list[str]:
    """渲染单条风险，保留任务、原因、负责人和建议动作。"""

    task = risk.task
    title = render_link(safe_text(task.title) or "未命名任务", task.url)
    owner = safe_text(task.owner) or "未明确"
    due_text = format_timestamp(task.due_timestamp) if task.due_timestamp else "未设置"
    lines = [
        f"{index}. {title}",
        f"   - 风险：{risk_type_label(risk.risk_type)} / {severity_label(risk.severity)}",
        f"   - 原因：{safe_text(risk.reason)}",
        f"   - 负责人：{owner}  |  截止时间：{due_text}",
        f"   - 建议：{safe_text(risk.suggestion)}",
    ]
    source_lines = render_m4_source_lines(risk)
    if source_lines:
        lines.extend(source_lines)
    return lines


def render_m4_source_lines(risk: RiskRuleResult) -> list[str]:
    """渲染 M4 任务来源，体现“会后生成任务 -> 风险巡检跟踪”的闭环。"""

    source = extract_m4_task_mapping(risk)
    if not source:
        return []

    meeting_label = safe_text(source.get("title")) or safe_text(source.get("meeting_id")) or "会后行动项"
    source_url = safe_text(source.get("source_url"))
    minute_token = safe_text(source.get("minute_token"))
    evidence_refs = source.get("evidence_refs") if isinstance(source.get("evidence_refs"), list) else []
    lines = [
        f"   - 来源：{render_link(meeting_label, source_url)}",
    ]
    if minute_token:
        lines.append(f"   - 妙记：`{minute_token}`")
    evidence_line = render_first_evidence_line(evidence_refs)
    if evidence_line:
        lines.append(f"   - 证据：{evidence_line}")
    return lines


def extract_m4_task_mapping(risk: RiskRuleResult) -> dict[str, Any]:
    """从风险 evidence 或 task.raw_payload 中取出 M4 映射。"""

    evidence_source = risk.evidence.get("m4_task_mapping") if isinstance(risk.evidence, dict) else None
    if isinstance(evidence_source, dict):
        return evidence_source
    raw_payload = risk.task.raw_payload if isinstance(risk.task.raw_payload, dict) else {}
    raw_source = raw_payload.get("m4_task_mapping")
    return raw_source if isinstance(raw_source, dict) else {}


def render_first_evidence_line(evidence_refs: list[Any]) -> str:
    """渲染第一条可读证据，避免风险卡片过长。"""

    for item in evidence_refs:
        if not isinstance(item, dict):
            continue
        snippet = safe_text(item.get("snippet"))
        source_id = safe_text(item.get("source_id")) or "原始证据"
        source_url = safe_text(item.get("source_url"))
        label = render_link(source_id, source_url)
        if snippet:
            return f"{label}：{snippet[:80]}"
        return label
    return ""


def choose_header_template(decision: RiskNotificationDecision, scan_result: RiskScanResult) -> str:
    """根据风险严重程度选择卡片颜色。"""

    if not decision.should_notify and not scan_result.risks:
        return "green"
    risks = decision.notify_risks or scan_result.risks
    if any(risk.severity == "high" for risk in risks):
        return "red"
    if risks:
        return "orange"
    return "blue"


def risk_type_label(risk_type: str) -> str:
    """把内部风险类型转换成用户可读名称。"""

    labels = {
        "overdue": "已逾期",
        "due_soon": "即将截止",
        "stale_update": "长期未更新",
        "missing_owner": "缺少负责人",
    }
    return labels.get(risk_type, risk_type)


def severity_label(severity: str) -> str:
    """把内部严重程度转换成用户可读名称。"""

    labels = {
        "high": "高风险",
        "medium": "中风险",
        "low": "低风险",
    }
    return labels.get(severity, severity)


def render_link(label: str, url: str) -> str:
    """在有任务链接时渲染飞书 Markdown 链接。"""

    clean_label = safe_text(label)
    clean_url = safe_text(url)
    if not clean_label:
        return ""
    if not clean_url:
        return clean_label
    return f"[{clean_label}]({clean_url})"


def format_timestamp(timestamp: int) -> str:
    """把秒级时间戳格式化为卡片可读时间。"""

    if not timestamp:
        return "未知"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def safe_text(value: Any) -> str:
    """清洗卡片文本，避免 None 或异常对象进入飞书卡片 JSON。"""

    return str(value or "").strip()
