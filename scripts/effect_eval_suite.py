from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.loader import EmbeddingSettings, KnowledgeSearchSettings, RerankerSettings, StorageSettings
from core.evaluation import EvaluationCase, EvaluationResult, run_evaluation_case
from core.knowledge import KnowledgeIndexStore
from core.models import Resource
from core.post_meeting import PostMeetingInput, build_post_meeting_artifacts_from_input


class DummyVectorIndex:
    """效果评测中关闭真实向量库依赖，只验证本地索引、FTS 和业务规则。"""

    def upsert_document(self, document: Any, chunks: list[Any]) -> dict[str, Any]:
        """模拟向量库写入成功，避免离线评测依赖 ChromaDB 或外部 embedding。"""

        return {"ok": True, "count": len(chunks)}

    def search(self, query: str, query_terms: list[str], resource_types: list[str], top_k: int) -> dict[str, Any]:
        """模拟向量召回为空，让测试主要依赖本地关键词索引。"""

        return {"ok": True, "chunk_ids": [], "distances": [], "total_candidates": 0}


@dataclass(slots=True)
class EffectCaseResult:
    """比赛答辩友好的单场景效果评测结果。"""

    case_id: str
    workflow: str
    scenario: str
    passed: bool
    automation_result: str
    value_summary: str
    manual_minutes: int
    agent_minutes: int
    introduced_operation: str = ""
    manual_steps: list[str] = field(default_factory=list)
    agent_steps: list[str] = field(default_factory=list)
    efficiency_basis: str = ""
    assertions: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def saved_minutes(self) -> int:
        """估算相对人工流程节省的分钟数。"""

        return max(0, self.manual_minutes - self.agent_minutes)

    @property
    def manual_operation_count(self) -> int:
        """人工流程步骤数。"""

        return len(self.manual_steps)

    @property
    def agent_operation_count(self) -> int:
        """引入 Agent 后仍需人工参与的关键步骤数。"""

        return len(self.agent_steps)

    @property
    def operation_reduction(self) -> int:
        """关键操作步骤减少量。"""

        return max(0, self.manual_operation_count - self.agent_operation_count)

    def to_dict(self) -> dict[str, Any]:
        """转换为稳定 JSON，方便比赛材料或 CI 留档。"""

        data = asdict(self)
        data["saved_minutes"] = self.saved_minutes
        data["manual_operation_count"] = self.manual_operation_count
        data["agent_operation_count"] = self.agent_operation_count
        data["operation_reduction"] = self.operation_reduction
        return data


@dataclass(slots=True)
class EffectSuiteReport:
    """效果评测聚合报告。"""

    generated_at: int
    results: list[EffectCaseResult]

    @property
    def total_cases(self) -> int:
        """评测场景总数。"""

        return len(self.results)

    @property
    def passed_cases(self) -> int:
        """通过的评测场景数。"""

        return sum(1 for item in self.results if item.passed)

    @property
    def pass_rate(self) -> float:
        """通过率。"""

        return round(self.passed_cases / self.total_cases, 4) if self.total_cases else 0.0

    @property
    def total_manual_minutes(self) -> int:
        """人工基线总耗时估算。"""

        return sum(item.manual_minutes for item in self.results)

    @property
    def total_agent_minutes(self) -> int:
        """Agent 流程总耗时估算。"""

        return sum(item.agent_minutes for item in self.results)

    @property
    def total_saved_minutes(self) -> int:
        """总节省时间估算。"""

        return sum(item.saved_minutes for item in self.results)

    def to_dict(self) -> dict[str, Any]:
        """转换为报告 JSON。"""

        return {
            "generated_at": self.generated_at,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "pass_rate": self.pass_rate,
            "total_manual_minutes": self.total_manual_minutes,
            "total_agent_minutes": self.total_agent_minutes,
            "total_saved_minutes": self.total_saved_minutes,
            "results": [item.to_dict() for item in self.results],
        }


def run_effect_suite() -> EffectSuiteReport:
    """运行覆盖 M3/M4/M5/RAG/队列的离线效果评测套件。"""

    results = [
        run_m3_rich_context_case(),
        run_m3_low_context_case(),
        run_rag_document_update_case(),
        run_m4_action_items_case(),
        run_m4_no_fake_task_case(),
        run_m4_missing_fields_case(),
        run_m5_risk_case(),
        run_job_queue_case(),
    ]
    attach_comparison_details(results)
    return EffectSuiteReport(generated_at=int(time.time()), results=results)


def run_m3_rich_context_case() -> EffectCaseResult:
    """模拟会前有文档、历史妙记和任务时，M3 能否自动生成背景卡。"""

    case = EvaluationCase(
        case_id="effect_m3_rich_context",
        workflow="m3_pre_meeting",
        description="会前资料充分时生成背景卡。",
        input={
            "meeting_id": "meeting_effect_m3",
            "calendar_event_id": "calendar_effect_m3",
            "project_id": "meetflow",
            "meeting_title": "MeetFlow M3 方案评审",
            "meeting_description": "评审会前背景卡、RAG 召回和按钮刷新链路。",
            "start_time": "2026-05-06 10:00",
            "end_time": "2026-05-06 10:30",
            "timezone": "Asia/Shanghai",
            "organizer": "张三",
            "participants": [{"display_name": "张三"}, {"display_name": "李四"}],
            "memory_snapshot": {"summary": "MeetFlow 已完成 M3/M4/M5 基础闭环，当前需要验证比赛演示效果。"},
            "related_resources": [
                {
                    "resource_id": "doc_effect_m3",
                    "resource_type": "doc",
                    "title": "M3 会前背景卡验收清单",
                    "content": "需要确认真实飞书群能收到背景卡，按钮刷新不能重复触发。",
                    "source_url": "https://example.feishu.cn/docx/doc_effect_m3",
                },
                {
                    "resource_id": "minute_effect_m3",
                    "resource_type": "minute",
                    "title": "上次 M3 评审妙记",
                    "content": "上次决定优先解决知识召回 evidence pack 和卡片回调幂等。",
                    "source_url": "https://example.feishu.cn/minutes/minute_effect_m3",
                },
                {
                    "resource_id": "task_effect_m3",
                    "resource_type": "task",
                    "title": "M3 风险：按钮重复点击",
                    "content": "重复点击刷新按钮可能导致重复生成背景，需要幂等键。",
                    "source_url": "https://example.feishu.cn/task/task_effect_m3",
                },
            ],
        },
        expected={
            "topic_contains": "MeetFlow",
            "min_must_read_resources": 2,
            "min_current_questions": 1,
            "min_risks": 1,
        },
    )
    result = run_evaluation_case(case)
    return effect_from_evaluation(
        result,
        scenario="会前资料充分：文档 + 历史妙记 + 未完成任务",
        automation_result="自动生成会前背景卡，包含待读资料、当前问题和风险提醒。",
        value_summary="减少会前人工翻文档、追历史结论和整理风险的时间。",
        manual_minutes=18,
        agent_minutes=3,
    )


def attach_comparison_details(results: list[EffectCaseResult]) -> None:
    """为每个评测场景补充人工流程和 Agent 流程的对比说明。"""

    details: dict[str, dict[str, Any]] = {
        "effect_m3_rich_context": {
            "introduced_operation": "M3 在会议开始前自动聚合日程、RAG 文档、历史妙记和未完成任务，推送会前背景卡。",
            "manual_steps": [
                "打开日历确认会议主题和参会人。",
                "在云文档中搜索项目资料和验收清单。",
                "打开历史妙记查找上次结论。",
                "打开任务列表确认未完成事项和风险。",
                "手工整理待读资料、当前问题和风险后发到群里。",
            ],
            "agent_steps": [
                "等待 M3 自动发出会前背景卡。",
                "参会人直接点击卡片中的资料链接或刷新按钮。",
            ],
            "efficiency_basis": "人工需要跨日历、文档、妙记、任务四处检索；Agent 把跨应用查找压缩成一次后台召回和一次群卡片推送。",
        },
        "effect_m3_low_context": {
            "introduced_operation": "M3 在低上下文会议中输出低置信度背景卡，不强行编造资料。",
            "manual_steps": [
                "看到临时会议后手工判断是否需要准备资料。",
                "在文档和妙记里尝试搜索相关背景。",
                "没有命中时再提醒组织者补充议题或资料。",
            ],
            "agent_steps": [
                "M3 自动识别资料不足。",
                "群卡片显示上下文不足，提示人工确认。",
            ],
            "efficiency_basis": "节省无效搜索时间，同时把风险从“错误总结”变成“明确提示资料不足”。",
        },
        "effect_rag_document_update": {
            "introduced_operation": "监听到文档变更后刷新本地 RAG 索引，让后续 M3/M4 使用最新版本。",
            "manual_steps": [
                "发现文档被修改。",
                "重新打开文档阅读变化。",
                "把变化复制到会议准备材料或本地知识库。",
                "提醒团队后续会议使用新版本。",
            ],
            "agent_steps": [
                "文档变更事件进入索引刷新任务。",
                "RAG chunk 自动替换为新内容。",
            ],
            "efficiency_basis": "把文档同步从人工复制维护变成事件驱动刷新，减少信息滞后。",
        },
        "effect_m4_action_items": {
            "introduced_operation": "M4 在妙记生成后抽取决策和待办，生成带按钮的会后总结卡。",
            "manual_steps": [
                "打开妙记并阅读完整会议记录。",
                "手工摘出会议决策。",
                "逐条识别待办、负责人和截止时间。",
                "复制内容到飞书任务。",
                "把任务来源和会议链接补到备注中。",
                "把整理后的总结发到群里。",
            ],
            "agent_steps": [
                "等待 M4 自动生成会后总结卡。",
                "在卡片中审核待办并点击创建或拒绝。",
            ],
            "efficiency_basis": "人工最耗时的是阅读妙记和复制任务字段；Agent 自动完成抽取、卡片呈现和证据绑定，只保留审核动作。",
        },
        "effect_m4_no_fake_task": {
            "introduced_operation": "M4 区分决策、开放问题和待办，避免把普通结论误建成任务。",
            "manual_steps": [
                "阅读妙记判断哪些内容只是结论。",
                "确认没有负责人和截止时间的内容不应创建任务。",
                "只把会议结论同步给相关人。",
            ],
            "agent_steps": [
                "M4 自动识别无明确待办。",
                "只展示总结和开放问题，不展示创建任务按钮。",
            ],
            "efficiency_basis": "价值不只来自省时间，也来自减少错误任务带来的后续沟通成本。",
        },
        "effect_m4_missing_fields": {
            "introduced_operation": "M4 对缺负责人或截止时间的待办进入人工补全，不绕过安全策略。",
            "manual_steps": [
                "阅读妙记找到模糊待办。",
                "回忆或询问负责人是谁。",
                "确认截止时间。",
                "补齐字段后再创建任务。",
            ],
            "agent_steps": [
                "M4 自动把模糊待办放入待确认卡片。",
                "用户在卡片里补负责人和截止时间后再创建。",
            ],
            "efficiency_basis": "自动化先完成发现和结构化，人工只处理缺失字段，减少低置信度写操作。",
        },
        "effect_m5_risk": {
            "introduced_operation": "M5 定期扫描任务状态，发现逾期/长时间未更新后回链到 M4 妙记证据。",
            "manual_steps": [
                "打开任务列表逐个检查状态和截止时间。",
                "筛选逾期或长时间未更新任务。",
                "查找任务来自哪次会议。",
                "打开妙记确认原始承诺。",
                "手工提醒负责人。",
            ],
            "agent_steps": [
                "M5 自动扫描任务快照。",
                "风险卡片直接给出风险类型和来源妙记证据。",
            ],
            "efficiency_basis": "把项目跟进从人工巡检变成后台定时巡检，并保留可追溯证据。",
        },
        "effect_job_queue": {
            "introduced_operation": "后台队列承接长连接事件和卡片回调，worker 领取任务并记录状态。",
            "manual_steps": [
                "分别启动 M3、M4、M5、RAG 调试脚本。",
                "人工观察哪个脚本应该处理事件。",
                "失败后手工重跑对应命令。",
            ],
            "agent_steps": [
                "事件统一入队。",
                "worker 自动领取并完成任务，状态可查询。",
            ],
            "efficiency_basis": "把多个零散测试入口收敛为可恢复的后台处理链路，降低比赛演示运维成本。",
        },
    }
    for result in results:
        item = details.get(result.case_id)
        if not item:
            continue
        result.introduced_operation = str(item["introduced_operation"])
        result.manual_steps = [str(step) for step in item["manual_steps"]]
        result.agent_steps = [str(step) for step in item["agent_steps"]]
        result.efficiency_basis = str(item["efficiency_basis"])


def run_m3_low_context_case() -> EffectCaseResult:
    """模拟会前上下文不足时，M3 是否避免假装有结论。"""

    case = EvaluationCase(
        case_id="effect_m3_low_context",
        workflow="m3_pre_meeting",
        description="会前资料不足时仍给出待确认问题。",
        input={
            "meeting_id": "meeting_effect_m3_low",
            "calendar_event_id": "calendar_effect_m3_low",
            "project_id": "meetflow",
            "meeting_title": "临时同步",
            "meeting_description": "",
            "start_time": "2026-05-06 11:00",
            "end_time": "2026-05-06 11:15",
            "timezone": "Asia/Shanghai",
            "organizer": "张三",
            "participants": [{"display_name": "张三"}],
            "memory_snapshot": {},
            "related_resources": [],
        },
        expected={
            "min_must_read_resources": 0,
            "min_current_questions": 0,
            "min_risks": 0,
        },
    )
    result = run_evaluation_case(case)
    return effect_from_evaluation(
        result,
        scenario="会前资料不足：只有日程标题，没有关联文档",
        automation_result="自动降级为待确认问题，不伪造背景资料。",
        value_summary="降低错误背景卡误导参会人的风险。",
        manual_minutes=8,
        agent_minutes=2,
    )


def run_rag_document_update_case() -> EffectCaseResult:
    """模拟飞书文档发生修改后，本地 RAG 索引能刷新到最新内容。"""

    assertions: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = build_temp_knowledge_store(tmp_dir)
            store.index_resource(
                Resource(
                    resource_id="doc_effect_rag",
                    resource_type="doc",
                    title="M3 需求文档",
                    content="旧版本：M3 背景卡需要展示会议标题和参会人。",
                    source_url="https://example.feishu.cn/docx/doc_effect_rag",
                    updated_at="2026-05-06T09:00:00",
                )
            )
            result = store.index_resource(
                Resource(
                    resource_id="doc_effect_rag",
                    resource_type="doc",
                    title="M3 需求文档",
                    content="新版本：M3 背景卡需要展示会议标题、参会人，并新增刷新幂等校验。",
                    source_url="https://example.feishu.cn/docx/doc_effect_rag",
                    updated_at="2026-05-06T09:10:00",
                )
            )
            chunks = store.list_chunks("doc_effect_rag")
            full_text = "\n".join(str(item.get("text") or "") for item in chunks)
            assertions = [
                build_assertion("index_status", result.status == "indexed", "indexed", result.status),
                build_assertion("updated_content_found", "刷新幂等校验" in full_text, "包含刷新幂等校验", full_text),
                build_assertion("old_content_removed", "旧版本" not in full_text, "旧版本被替换", full_text),
            ]
            evidence = {"chunk_count": len(chunks), "snippet": full_text[:120]}
    except Exception as error:  # noqa: BLE001 - 效果报告要保留失败原因继续汇总。
        return EffectCaseResult(
            case_id="effect_rag_document_update",
            workflow="rag_update",
            scenario="已监听文档修改：模拟 drive.file.edit_v1 后刷新索引",
            passed=False,
            automation_result="RAG 索引刷新失败。",
            value_summary="本场景用于验证文档变化能进入后续会前/会后检索。",
            manual_minutes=10,
            agent_minutes=1,
            assertions=[],
            evidence={},
            error=str(error),
        )
    passed = all(item["passed"] for item in assertions)
    return EffectCaseResult(
        case_id="effect_rag_document_update",
        workflow="rag_update",
        scenario="已监听文档修改：模拟 drive.file.edit_v1 后刷新索引",
        passed=passed,
        automation_result="文档新内容进入本地 RAG chunk，旧内容被替换。",
        value_summary="避免人工重新整理资料，后续 M3/M4 能读到最新版本。",
        manual_minutes=10,
        agent_minutes=1,
        assertions=assertions,
        evidence=evidence,
    )


def run_m4_action_items_case() -> EffectCaseResult:
    """模拟妙记包含明确负责人和截止时间时，M4 能抽取待审核任务。"""

    artifacts = build_post_meeting_artifacts_from_input(
        PostMeetingInput(
            meeting_id="meeting_effect_m4",
            calendar_event_id="calendar_effect_m4",
            minute_token="minute_effect_m4",
            project_id="meetflow",
            topic="MeetFlow M4 复盘",
            source_url="https://example.feishu.cn/minutes/minute_effect_m4",
            raw_text="\n".join(
                [
                    "# MeetFlow M4 复盘",
                    "## 决策",
                    "决定本周先上线会后总结卡片，并保留人工审核后创建任务。",
                    "## 待办",
                    "张三负责整理 M4 效果测试报告，截止明天前。",
                    "李四负责补充失败重试说明，截止本周五前。",
                ]
            ),
        )
    )
    titles = [item.title for item in artifacts.action_items]
    owners = [item.owner for item in artifacts.action_items]
    due_dates = [item.due_date for item in artifacts.action_items]
    assertions = [
        build_assertion("action_item_count", len(artifacts.action_items) == 2, 2, len(artifacts.action_items)),
        build_assertion("all_pending_review", len(artifacts.pending_action_items) == 2, 2, len(artifacts.pending_action_items)),
        build_assertion("owner_extracted", owners == ["张三", "李四"], ["张三", "李四"], owners),
        build_assertion("due_date_extracted", all(due_dates), "所有任务都有截止时间", due_dates),
    ]
    return EffectCaseResult(
        case_id="effect_m4_action_items",
        workflow="m4_post_meeting",
        scenario="妙记有明确待办：负责人 + 截止时间齐全",
        passed=all(item["passed"] for item in assertions),
        automation_result="抽取 2 条待审核任务，并保留原始妙记证据。",
        value_summary="减少会后人工整理纪要和复制待办的时间，同时保留人工确认入口。",
        manual_minutes=22,
        agent_minutes=4,
        assertions=assertions,
        evidence={"titles": titles, "owners": owners, "due_dates": due_dates},
    )


def run_m4_no_fake_task_case() -> EffectCaseResult:
    """模拟妙记只有决策和问题时，M4 不应误生成任务。"""

    artifacts = build_post_meeting_artifacts_from_input(
        PostMeetingInput(
            meeting_id="meeting_effect_m4_no_task",
            calendar_event_id="calendar_effect_m4_no_task",
            minute_token="minute_effect_m4_no_task",
            project_id="meetflow",
            topic="MeetFlow 架构讨论",
            raw_text="\n".join(
                [
                    "# MeetFlow 架构讨论",
                    "## 决策",
                    "决定继续使用 SQLite 作为本地队列。",
                    "## 开放问题",
                    "是否需要扩展到非日程会议仍待确认。",
                ]
            ),
        )
    )
    assertions = [
        build_assertion("no_action_items", len(artifacts.action_items) == 0, 0, len(artifacts.action_items)),
        build_assertion("no_pending_items", len(artifacts.pending_action_items) == 0, 0, len(artifacts.pending_action_items)),
    ]
    return EffectCaseResult(
        case_id="effect_m4_no_fake_task",
        workflow="m4_post_meeting",
        scenario="妙记只有决策和开放问题，没有明确待办",
        passed=all(item["passed"] for item in assertions),
        automation_result="没有误抽取任务，也不会触发创建任务按钮。",
        value_summary="降低把讨论结论误建成飞书任务的风险。",
        manual_minutes=12,
        agent_minutes=2,
        assertions=assertions,
        evidence={"decision_count": len(artifacts.decisions), "open_question_count": len(artifacts.open_questions)},
    )


def run_m4_missing_fields_case() -> EffectCaseResult:
    """模拟妙记有待办但缺负责人/截止时间时，M4 要进入人工补全。"""

    artifacts = build_post_meeting_artifacts_from_input(
        PostMeetingInput(
            meeting_id="meeting_effect_m4_missing",
            calendar_event_id="calendar_effect_m4_missing",
            minute_token="minute_effect_m4_missing",
            project_id="meetflow",
            topic="MeetFlow 测试复盘",
            raw_text="\n".join(
                [
                    "# MeetFlow 测试复盘",
                    "## 待办",
                    "整理 M4 效果测试报告。",
                    "补充失败重试说明。",
                ]
            ),
        )
    )
    needs_confirm = [item.needs_confirm for item in artifacts.action_items]
    assertions = [
        build_assertion("action_item_count", len(artifacts.action_items) == 2, 2, len(artifacts.action_items)),
        build_assertion("needs_confirm", all(needs_confirm), "全部需要人工补字段", needs_confirm),
        build_assertion("pending_review", len(artifacts.pending_action_items) == 2, 2, len(artifacts.pending_action_items)),
    ]
    return EffectCaseResult(
        case_id="effect_m4_missing_fields",
        workflow="m4_post_meeting",
        scenario="妙记有待办但缺负责人/截止时间",
        passed=all(item["passed"] for item in assertions),
        automation_result="任务进入待确认卡片，不绕过人工直接写入飞书。",
        value_summary="兼顾自动化效率和写操作安全，避免低置信度任务污染任务系统。",
        manual_minutes=15,
        agent_minutes=3,
        assertions=assertions,
        evidence={"needs_confirm": needs_confirm},
    )


def run_m5_risk_case() -> EffectCaseResult:
    """模拟飞书任务快照出现逾期风险时，M5 能带回 M4 来源证据。"""

    case = EvaluationCase(
        case_id="effect_m5_risk",
        workflow="m5_risk_scan",
        description="任务逾期后识别风险并回链会议证据。",
        input={
            "now": 1777968000,
            "stale_update_days": 3,
            "due_soon_hours": 24,
            "tasks": [
                {
                    "item_id": "task_effect_overdue",
                    "title": "整理 M4 效果测试报告",
                    "owner": "张三",
                    "due_date": "1777593600",
                    "status": "todo",
                    "extra": {"task_id": "task_effect_overdue", "updated_at": "1777600000"},
                }
            ],
            "task_mappings": [
                {
                    "item_id": "action_effect_001",
                    "task_id": "task_effect_overdue",
                    "meeting_id": "meeting_effect_m4",
                    "minute_token": "minute_effect_m4",
                    "title": "整理 M4 效果测试报告",
                    "owner": "张三",
                    "due_date": "2026-05-01",
                    "status": "created",
                    "evidence_refs": [
                        {
                            "source_type": "feishu_minute",
                            "source_id": "minute_effect_m4",
                            "source_url": "https://example.feishu.cn/minutes/minute_effect_m4",
                            "snippet": "张三负责整理 M4 效果测试报告，截止明天前。",
                        }
                    ],
                    "source_url": "https://example.feishu.cn/minutes/minute_effect_m4",
                }
            ],
        },
        expected={"min_risks": 1, "risk_types": ["overdue"], "evidence_source_contains": "minute_effect_m4"},
    )
    result = run_evaluation_case(case)
    return effect_from_evaluation(
        result,
        scenario="任务逾期：从任务快照回链到 M4 妙记证据",
        automation_result="识别逾期风险，并在证据中保留来源妙记链接。",
        value_summary="减少人工巡检任务状态和追溯会议来源的时间。",
        manual_minutes=16,
        agent_minutes=3,
    )


def run_job_queue_case() -> EffectCaseResult:
    """模拟后台队列领取和完成任务，验证闭环系统可恢复运行。"""

    case = EvaluationCase(
        case_id="effect_job_queue",
        workflow="job_queue",
        description="后台队列可以入队、领取和完成任务。",
        input={
            "worker_id": "effect_worker",
            "queues": ["workflow"],
            "mark_succeeded": True,
            "jobs": [
                {
                    "job_type": "m4_post_meeting",
                    "queue_name": "workflow",
                    "payload": {"minute_token": "minute_effect_m4"},
                    "idempotency_key": "effect:m4:minute_effect_m4",
                }
            ],
        },
        expected={"min_enqueued": 1, "claimed_job_type": "m4_post_meeting", "final_status": "succeeded"},
    )
    result = run_evaluation_case(case)
    return effect_from_evaluation(
        result,
        scenario="后台闭环：事件入队后 worker 可领取并完成",
        automation_result="队列任务从 pending 进入 succeeded。",
        value_summary="支撑一键启动后的无人值守处理和失败恢复。",
        manual_minutes=6,
        agent_minutes=1,
    )


def effect_from_evaluation(
    result: EvaluationResult,
    *,
    scenario: str,
    automation_result: str,
    value_summary: str,
    manual_minutes: int,
    agent_minutes: int,
) -> EffectCaseResult:
    """把通用评测结果包装成效果评测结果。"""

    return EffectCaseResult(
        case_id=result.case_id,
        workflow=result.workflow,
        scenario=scenario,
        passed=result.passed,
        automation_result=automation_result if result.passed else "评测未通过，需查看断言和错误。",
        value_summary=value_summary,
        manual_minutes=manual_minutes,
        agent_minutes=agent_minutes,
        assertions=[item.to_dict() for item in result.assertions],
        evidence=result.artifacts,
        error=result.error,
    )


def build_temp_knowledge_store(tmp_dir: str) -> KnowledgeIndexStore:
    """创建只依赖本地 SQLite 的知识库评测实例。"""

    storage_settings = StorageSettings(
        db_path=str(Path(tmp_dir) / "meetflow.sqlite"),
        project_memory_dir=str(Path(tmp_dir) / "projects"),
        audit_log_path=str(Path(tmp_dir) / "audit.jsonl"),
    )
    store = KnowledgeIndexStore(
        settings=storage_settings,
        embedding_settings=EmbeddingSettings(
            provider="sentence-transformers",
            model="dummy-model",
            api_base="",
            api_key="",
            dimensions=8,
            timeout_seconds=5,
        ),
        reranker_settings=RerankerSettings(
            enabled=False,
            provider="disabled",
            model="",
            top_k=8,
            timeout_seconds=5,
        ),
        search_settings=KnowledgeSearchSettings(fusion_strategy="rrf", rrf_k=60),
    )
    store.vector_index = DummyVectorIndex()
    store.initialize()
    return store


def build_assertion(name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
    """构造轻量断言记录。"""

    return {"name": name, "passed": passed, "expected": expected, "actual": actual}


def render_markdown_report(report: EffectSuiteReport) -> str:
    """把效果评测结果渲染为 Markdown 表格。"""

    status = "通过" if report.passed_cases == report.total_cases else "部分通过"
    lines = [
        "# MeetFlow 效果评测报告",
        "",
        f"- 生成时间戳：{report.generated_at}",
        f"- 评测结论：{status}（{report.passed_cases}/{report.total_cases}，通过率 {report.pass_rate:.0%}）",
        f"- 人工基线估算：{report.total_manual_minutes} 分钟",
        f"- Agent 流程估算：{report.total_agent_minutes} 分钟",
        f"- 预计节省：{report.total_saved_minutes} 分钟（约 {saved_ratio(report):.0%}）",
        "",
        "> 说明：本报告使用脱敏离线样本模拟飞书文档、妙记、任务快照和后台队列；耗时为按人工操作步骤估算的基线，不代表线上大样本 A/B 结果。",
        "",
        "## 总览对比",
        "",
        "| 场景 | 引入的操作 | 是否通过 | 人工基线 | Agent 估算 | 节省 | 操作减少 | 效率提升来源 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report.results:
        lines.append(
            "| {scenario} | {introduced} | {passed} | {manual} 分钟 | {agent} 分钟 | {saved} 分钟 | {ops} 步 | {basis} |".format(
                scenario=escape_table_cell(item.scenario),
                introduced=escape_table_cell(item.introduced_operation or item.automation_result),
                passed="通过" if item.passed else "失败",
                manual=item.manual_minutes,
                agent=item.agent_minutes,
                saved=item.saved_minutes,
                ops=item.operation_reduction,
                basis=escape_table_cell(item.efficiency_basis or item.value_summary),
            )
        )
    lines.extend(
        [
            "",
            "## 场景对比明细",
            "",
        ]
    )
    for item in report.results:
        lines.extend(
            [
                f"### {item.scenario}",
                "",
                f"- 覆盖能力：{item.workflow}",
                f"- 验证结果：{'通过' if item.passed else '失败'}；{item.automation_result}",
                f"- 时间对比：人工 {item.manual_minutes} 分钟，Agent {item.agent_minutes} 分钟，节省 {item.saved_minutes} 分钟。",
                f"- 操作对比：人工 {item.manual_operation_count} 步，Agent 后 {item.agent_operation_count} 步，减少 {item.operation_reduction} 步。",
                f"- 价值解释：{item.value_summary}",
                "",
                "人工流程：",
                *[f"{index}. {step}" for index, step in enumerate(item.manual_steps, start=1)],
                "",
                "引入 MeetFlow 后：",
                *[f"{index}. {step}" for index, step in enumerate(item.agent_steps, start=1)],
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def saved_ratio(report: EffectSuiteReport) -> float:
    """计算节省比例。"""

    return report.total_saved_minutes / report.total_manual_minutes if report.total_manual_minutes else 0.0


def escape_table_cell(value: str) -> str:
    """转义 Markdown 表格中的竖线和换行。"""

    return str(value).replace("|", "\\|").replace("\n", " ")


def write_report_files(report: EffectSuiteReport, report_dir: Path) -> tuple[Path, Path]:
    """写入 Markdown 和 JSON 报告文件。"""

    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "effect_eval_latest.md"
    json_path = report_dir / "effect_eval_latest.json"
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path, json_path


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="运行 MeetFlow 脱敏效果评测并输出比赛答辩表格。")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="将 Markdown/JSON 报告写入 storage/reports/evaluation。",
    )
    parser.add_argument(
        "--report-dir",
        default="storage/reports/evaluation",
        help="报告输出目录，默认 storage/reports/evaluation。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="在 stdout 输出 JSON，而不是 Markdown 表格。",
    )
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    report = run_effect_suite()
    if args.write_report:
        markdown_path, json_path = write_report_files(report, Path(args.report_dir))
        print(f"[效果评测] 已写入 Markdown: {markdown_path}")
        print(f"[效果评测] 已写入 JSON: {json_path}")
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_markdown_report(report))
    return 0 if report.passed_cases == report.total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
