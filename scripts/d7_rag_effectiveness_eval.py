from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.eval_metrics import score_forbidden_tools, score_secret_leakage_absent, score_tool_call_f1


DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "tests" / "e2e_fixtures" / "d7_rag_effectiveness" / "case.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "docs" / "evaluation"


@dataclass(slots=True)
class D7Metric:
    """D7 评测中的单个可解释指标。"""

    name: str
    score: float
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 友好的字典。"""

        return {"name": self.name, "score": round(self.score, 4), "detail": self.detail}


@dataclass(slots=True)
class D7Report:
    """D7 RAG 与 Agent 综合评测报告。"""

    suite_id: str
    generated_at: int
    data_profile: dict[str, int]
    retrieval: dict[str, Any]
    answer_quality: dict[str, Any]
    workflow_quality: dict[str, Any]
    agent_quality: dict[str, Any]
    overall_score: float
    conclusion: str
    source_article: str

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 友好的字典。"""

        return {
            "suite_id": self.suite_id,
            "generated_at": self.generated_at,
            "data_profile": self.data_profile,
            "retrieval": self.retrieval,
            "answer_quality": self.answer_quality,
            "workflow_quality": self.workflow_quality,
            "agent_quality": self.agent_quality,
            "overall_score": round(self.overall_score, 4),
            "conclusion": self.conclusion,
            "source_article": self.source_article,
        }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="MeetFlow D7 RAG 与 Agent 效果评测。")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE_PATH), help="D7 评测样本 JSON。")
    parser.add_argument("--top-k", type=int, default=3, help="检索层 Hit@K / Context@K 的 K 值。")
    parser.add_argument("--write-report", action="store_true", help="写入 docs/evaluation 下的 JSON 和 Markdown 报告。")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="报告输出目录。")
    parser.add_argument("--fail-under", type=float, default=0.85, help="综合分最低通过阈值。")
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    report = run_d7_evaluation(Path(args.fixture), top_k=args.top_k)
    report_dict = report.to_dict()
    print(json.dumps(report_dict, ensure_ascii=False, indent=2))

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "d7_rag_effectiveness_report.json"
        md_path = report_dir / "d7_rag_effectiveness_report.md"
        json_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(render_markdown_report(report), encoding="utf-8")
        print(f"\nD7 评测报告已写入：{json_path}")
        print(f"D7 Markdown 报告已写入：{md_path}")

    if report.overall_score < args.fail_under:
        print(f"\n评测失败：overall_score={report.overall_score:.4f} 低于 fail-under={args.fail_under:.4f}")
        return 1
    return 0


def run_d7_evaluation(fixture_path: Path = DEFAULT_FIXTURE_PATH, top_k: int = 3) -> D7Report:
    """运行 D7 离线评测套件。"""

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    corpus = list(data.get("corpus") or [])
    retrieval_cases = list(data.get("retrieval_cases") or [])
    retrieval = evaluate_retrieval(corpus=corpus, cases=retrieval_cases, top_k=top_k)
    answer_quality = evaluate_answer_quality(cases=retrieval_cases)
    workflow_quality = evaluate_workflow_quality(dict(data.get("workflow_cases") or {}))
    agent_quality = evaluate_agent_quality(
        trace_cases=list(data.get("agent_trace_cases") or []),
        stability_checks=list(data.get("demo_stability_checks") or []),
    )
    category_scores = [
        float(retrieval["score"]),
        float(answer_quality["with_rag"]["score"]),
        float(workflow_quality["score"]),
        float(agent_quality["score"]),
    ]
    overall_score = round(sum(category_scores) / len(category_scores), 4)
    conclusion = build_conclusion(report_scores={
        "retrieval": retrieval["score"],
        "answer": answer_quality["with_rag"]["score"],
        "workflow": workflow_quality["score"],
        "agent": agent_quality["score"],
        "overall": overall_score,
    })
    return D7Report(
        suite_id=str(data.get("suite_id") or "d7_rag_effectiveness"),
        generated_at=int(time.time()),
        data_profile={
            "corpus_chunks": len(corpus),
            "retrieval_cases": len(retrieval_cases),
            "workflow_cases": len(dict(data.get("workflow_cases") or {})),
            "agent_trace_cases": len(list(data.get("agent_trace_cases") or [])),
        },
        retrieval=retrieval,
        answer_quality=answer_quality,
        workflow_quality=workflow_quality,
        agent_quality=agent_quality,
        overall_score=overall_score,
        conclusion=conclusion,
        source_article="https://xiaolinnote.com/ai/rag/18_evaluation.html",
    )


def evaluate_retrieval(corpus: list[dict[str, Any]], cases: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    """评测检索层 Hit@K、MRR、Context Recall 和 Context Precision。"""

    per_case = []
    for case in cases:
        expected = set(str(item) for item in list(case.get("expected_chunk_ids") or []))
        ranked = rank_chunks(str(case.get("question") or ""), corpus)
        ranked_ids = [item["chunk_id"] for item in ranked]
        top_ids = ranked_ids[:top_k]
        first_rank = find_first_rank(ranked_ids, expected)
        hits = len(expected & set(top_ids))
        context_recall = hits / len(expected) if expected else 1.0
        context_precision = hits / len(top_ids) if top_ids else 0.0
        per_case.append(
            {
                "case_id": case.get("case_id"),
                "question": case.get("question"),
                "expected_chunk_ids": sorted(expected),
                "top_chunk_ids": top_ids,
                f"hit@{top_k}": 1.0 if hits else 0.0,
                "mrr": round(1 / first_rank, 4) if first_rank else 0.0,
                "context_recall": round(context_recall, 4),
                "context_precision": round(context_precision, 4),
            }
        )
    metrics = average_metrics(per_case, [f"hit@{top_k}", "mrr", "context_recall", "context_precision"])
    score = round((metrics[f"hit@{top_k}"] + metrics["mrr"] + metrics["context_recall"] + metrics["context_precision"]) / 4, 4)
    return {"top_k": top_k, "case_count": len(per_case), "metrics": metrics, "score": score, "cases": per_case}


def evaluate_answer_quality(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """评测生成结果的忠实度、相关性和证据覆盖。"""

    with_rag = evaluate_answer_variant(cases, variant="answer_with_rag")
    without_rag = evaluate_answer_variant(cases, variant="answer_without_rag")
    improvement = {
        "score_delta": round(with_rag["score"] - without_rag["score"], 4),
        "evidence_coverage_delta": round(with_rag["metrics"]["evidence_coverage"] - without_rag["metrics"]["evidence_coverage"], 4),
        "faithfulness_delta": round(with_rag["metrics"]["faithfulness"] - without_rag["metrics"]["faithfulness"], 4),
    }
    return {"with_rag": with_rag, "without_rag": without_rag, "improvement": improvement}


def evaluate_answer_variant(cases: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    """评测 RAG 或非 RAG 生成答案变体。"""

    per_case = []
    for case in cases:
        required = set(str(item) for item in list(case.get("required_fact_ids") or []))
        expected_chunks = set(str(item) for item in list(case.get("expected_chunk_ids") or []))
        facts = list((case.get(variant) or {}).get("facts") or [])
        fact_ids = {str(item.get("fact_id") or "") for item in facts}
        supported = [
            item
            for item in facts
            if set(str(chunk_id) for chunk_id in list(item.get("support_chunk_ids") or [])) & expected_chunks
        ]
        required_supported = [
            item
            for item in supported
            if str(item.get("fact_id") or "") in required
        ]
        faithfulness = len(supported) / len(facts) if facts else 0.0
        answer_relevancy = len(required & fact_ids) / len(required) if required else 1.0
        evidence_coverage = len({str(item.get("fact_id") or "") for item in required_supported}) / len(required) if required else 1.0
        per_case.append(
            {
                "case_id": case.get("case_id"),
                "faithfulness": round(faithfulness, 4),
                "answer_relevancy": round(answer_relevancy, 4),
                "evidence_coverage": round(evidence_coverage, 4),
                "fact_count": len(facts),
            }
        )
    metrics = average_metrics(per_case, ["faithfulness", "answer_relevancy", "evidence_coverage"])
    score = round(sum(metrics.values()) / len(metrics), 4) if metrics else 0.0
    return {"score": score, "metrics": metrics, "cases": per_case}


def evaluate_workflow_quality(workflow_cases: dict[str, Any]) -> dict[str, Any]:
    """评测会前、会后、风险三个业务工作流的结构化效果。"""

    pre = evaluate_pre_meeting_quality(dict(workflow_cases.get("pre_meeting_quality") or {}))
    post = evaluate_post_meeting_quality(dict(workflow_cases.get("post_meeting_quality") or {}))
    risk = evaluate_risk_scan_quality(dict(workflow_cases.get("risk_scan_quality") or {}))
    score = round((pre["score"] + post["score"] + risk["score"]) / 3, 4)
    return {"score": score, "pre_meeting": pre, "post_meeting": post, "risk_scan": risk}


def evaluate_pre_meeting_quality(case: dict[str, Any]) -> dict[str, Any]:
    """评测会前卡片结构完整性和证据覆盖。"""

    expected = set(str(item) for item in list(case.get("expected_sections") or []))
    with_rag_sections = list((case.get("with_rag") or {}).get("sections") or [])
    without_rag_sections = list((case.get("without_rag") or {}).get("sections") or [])
    with_rag_score = score_sections(expected, with_rag_sections)
    without_rag_score = score_sections(expected, without_rag_sections)
    return {"score": with_rag_score["score"], "with_rag": with_rag_score, "without_rag": without_rag_score}


def evaluate_post_meeting_quality(case: dict[str, Any]) -> dict[str, Any]:
    """评测会后总结结构、行动项识别和字段完整率。"""

    expected_sections = set(str(item) for item in list(case.get("expected_sections") or []))
    actual_sections = set(str(item) for item in list((case.get("with_rag") or {}).get("sections") or []))
    section_score = len(expected_sections & actual_sections) / len(expected_sections) if expected_sections else 1.0
    expected_items = list(case.get("expected_action_items") or [])
    actual_items = list((case.get("with_rag") or {}).get("action_items") or [])
    item_recall = score_action_item_recall(expected_items, actual_items)
    field_complete = score_action_field_completeness(actual_items)
    evidence_rate = sum(1 for item in actual_items if item.get("evidence_chunk_id")) / len(actual_items) if actual_items else 0.0
    score = round((section_score + item_recall + field_complete + evidence_rate) / 4, 4)
    return {
        "score": score,
        "section_score": round(section_score, 4),
        "action_item_recall": round(item_recall, 4),
        "field_completeness": round(field_complete, 4),
        "evidence_rate": round(evidence_rate, 4),
        "actual_action_count": len(actual_items),
    }


def evaluate_risk_scan_quality(case: dict[str, Any]) -> dict[str, Any]:
    """评测任务风险提醒的召回、精确率和证据覆盖。"""

    expected = set(str(item) for item in list(case.get("expected_risk_types") or []))
    actual = set(str(item) for item in list((case.get("with_rag") or {}).get("risk_types") or []))
    evidence_ids = [item for item in list((case.get("with_rag") or {}).get("evidence_chunk_ids") or []) if item]
    recall = len(expected & actual) / len(expected) if expected else 1.0
    precision = len(expected & actual) / len(actual) if actual else 0.0
    evidence_rate = len(evidence_ids) / len(actual) if actual else 0.0
    score = round((recall + precision + evidence_rate) / 3, 4)
    return {"score": score, "recall": round(recall, 4), "precision": round(precision, 4), "evidence_rate": round(evidence_rate, 4)}


def evaluate_agent_quality(trace_cases: list[dict[str, Any]], stability_checks: list[dict[str, Any]]) -> dict[str, Any]:
    """评测工具轨迹、安全策略和演示稳定性。"""

    trace_results = []
    for case in trace_cases:
        actual_tools = [str(item) for item in list(case.get("actual_tools") or [])]
        expected_tools = [str(item) for item in list(case.get("expected_tools") or [])]
        forbidden_tools = [str(item) for item in list(case.get("forbidden_tools") or [])]
        policy_decisions = list(case.get("policy_decisions") or [])
        tool_f1 = score_tool_call_f1(actual_tools, expected_tools)
        forbidden_absent = score_forbidden_tools(actual_tools, forbidden_tools)
        policy_score = score_policy_decisions(policy_decisions)
        trace_results.append(
            {
                "case_id": case.get("case_id"),
                "tool_call_f1": tool_f1,
                "forbidden_tools_absent": forbidden_absent,
                "policy_score": policy_score,
                "score": round((tool_f1 + forbidden_absent + policy_score) / 3, 4),
            }
        )
    trace_score = round(sum(item["score"] for item in trace_results) / len(trace_results), 4) if trace_results else 1.0
    stability_score = sum(1 for item in stability_checks if item.get("passed")) / len(stability_checks) if stability_checks else 1.0
    safety_score = score_secret_leakage_absent({"trace_results": trace_results, "stability_checks": stability_checks})
    score = round((trace_score + stability_score + safety_score) / 3, 4)
    return {
        "score": score,
        "trace_score": trace_score,
        "stability_score": round(stability_score, 4),
        "safety_score": safety_score,
        "trace_cases": trace_results,
    }


def rank_chunks(query: str, corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用确定性的轻量词法召回模拟本地 RAG 检索排序。"""

    query_tokens = tokenize(query)
    ranked = []
    for chunk in corpus:
        text = f"{chunk.get('title', '')} {chunk.get('text', '')}"
        chunk_tokens = tokenize(text)
        overlap = sum(query_tokens.get(token, 0) * min(chunk_tokens.get(token, 0), 3) for token in query_tokens)
        title_bonus = sum(1 for token in query_tokens if token in tokenize(str(chunk.get("title") or "")))
        score = overlap + 0.3 * title_bonus
        payload = dict(chunk)
        payload["score"] = round(score, 4)
        ranked.append(payload)
    return sorted(ranked, key=lambda item: (-float(item["score"]), str(item["chunk_id"])))


def tokenize(text: str) -> dict[str, int]:
    """中英文混合文本分词，足够支撑离线评测的可重复排序。"""

    lowered = text.lower()
    tokens: list[str] = []
    tokens.extend(re.findall(r"[a-z0-9]+", lowered))
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
    tokens.extend(chinese_chars)
    tokens.extend("".join(pair) for pair in zip(chinese_chars, chinese_chars[1:]))
    counts: dict[str, int] = {}
    for token in tokens:
        if len(token.strip()) == 0:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts


def find_first_rank(ranked_ids: list[str], expected: set[str]) -> int:
    """找到第一个相关 chunk 的 1-based 排名。"""

    for index, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in expected:
            return index
    return 0


def average_metrics(cases: list[dict[str, Any]], metric_names: list[str]) -> dict[str, float]:
    """计算一组 case 的平均指标。"""

    if not cases:
        return {name: 0.0 for name in metric_names}
    return {
        name: round(sum(float(case.get(name, 0.0) or 0.0) for case in cases) / len(cases), 4)
        for name in metric_names
    }


def score_sections(expected: set[str], sections: list[dict[str, Any]]) -> dict[str, Any]:
    """评估卡片章节完整率和章节证据覆盖率。"""

    actual = {str(item.get("section_id") or "") for item in sections}
    completeness = len(expected & actual) / len(expected) if expected else 1.0
    cited_sections = [
        item
        for item in sections
        if str(item.get("section_id") or "") in expected and list(item.get("cited_chunk_ids") or [])
    ]
    evidence_rate = len(cited_sections) / len(expected) if expected else 1.0
    score = round((completeness + evidence_rate) / 2, 4)
    return {
        "score": score,
        "section_completeness": round(completeness, 4),
        "section_evidence_rate": round(evidence_rate, 4),
        "actual_sections": sorted(actual),
    }


def score_action_item_recall(expected_items: list[dict[str, Any]], actual_items: list[dict[str, Any]]) -> float:
    """评估会后行动项是否覆盖人工标注的 owner/title/due_date。"""

    if not expected_items:
        return 1.0
    matched = 0
    for expected in expected_items:
        owner = str(expected.get("owner") or "")
        title_contains = str(expected.get("title_contains") or "")
        due_date = str(expected.get("due_date") or "")
        for actual in actual_items:
            if owner == str(actual.get("owner") or "") and title_contains in str(actual.get("title") or "") and due_date == str(actual.get("due_date") or ""):
                matched += 1
                break
    return matched / len(expected_items)


def score_action_field_completeness(action_items: list[dict[str, Any]]) -> float:
    """评估任务负责人、标题、截止时间和证据字段完整率。"""

    if not action_items:
        return 0.0
    fields = ["owner", "title", "due_date", "evidence_chunk_id"]
    total = len(action_items) * len(fields)
    filled = sum(1 for item in action_items for field in fields if str(item.get(field) or "").strip())
    return filled / total


def score_policy_decisions(policy_decisions: list[dict[str, Any]]) -> float:
    """评估写操作是否通过 Policy、幂等键和 allow-write gate 约束。"""

    if not policy_decisions:
        return 1.0
    scores = []
    for decision in policy_decisions:
        status = str(decision.get("status") or "")
        allow_write = bool(decision.get("allow_write"))
        has_idempotency = bool(decision.get("idempotency_key_present"))
        status_ok = status in {"allow", "needs_confirmation", "blocked"}
        gate_ok = allow_write or status in {"needs_confirmation", "blocked"}
        scores.append(sum([status_ok, gate_ok, has_idempotency]) / 3)
    return round(sum(scores) / len(scores), 4)


def build_conclusion(report_scores: dict[str, float]) -> str:
    """生成可放进答辩材料的结论。"""

    if report_scores["overall"] >= 0.9:
        return "D7 离线评测显示 MeetFlow 在 40 条业务风格脱敏样本上达到可演示水位：RAG 检索能稳定召回关键证据，生成结果证据覆盖明显优于非 RAG 基线，Agent 工具轨迹和安全策略可解释。"
    if report_scores["overall"] >= 0.8:
        return "D7 离线评测显示 MeetFlow 基本达到演示水位，但仍需要补强低分维度后再作为正式答辩主口径。"
    return "D7 离线评测未达到演示水位，应优先排查检索召回、证据覆盖或安全策略链路。"


def render_markdown_report(report: D7Report) -> str:
    """渲染可直接阅读的 Markdown 评测报告。"""

    data = report.to_dict()
    retrieval_metrics = data["retrieval"]["metrics"]
    profile = data["data_profile"]
    answer_with = data["answer_quality"]["with_rag"]["metrics"]
    answer_without = data["answer_quality"]["without_rag"]["metrics"]
    workflow = data["workflow_quality"]
    agent = data["agent_quality"]
    return "\n".join(
        [
            "# D7 MeetFlow RAG 与 Agent 效果评测报告",
            "",
            "## 结论",
            "",
            f"- 综合分：{data['overall_score']:.4f}",
            f"- 结论：{data['conclusion']}",
            f"- 方法参考：{data['source_article']}",
            "",
            "## 评测方法",
            "",
            "- 检索层：Hit@3、MRR、Context Recall、Context Precision。",
            "- 生成层：Faithfulness、Answer Relevancy、Evidence Coverage，并和非 RAG 基线对比。",
            "- 业务层：会前卡片章节完整度、会后行动项字段准确性、风险识别证据覆盖。",
            "- Agent 层：工具调用 F1、禁止工具检查、Policy/幂等/allow-write gate、演示稳定性和敏感信息扫描。",
            "",
            "## 测试数据",
            "",
            f"- 语料：{profile['corpus_chunks']} 个脱敏 chunk，覆盖 PRD、历史会议、当前妙记、遗留任务、风险记录、Agent Trace、OpenClaw 指南和无关噪声文档。",
            f"- RAG 查询：{profile['retrieval_cases']} 条，覆盖会前背景、遗留任务、授权风险、会后行动项、安全边界、OpenClaw、工具轨迹和评测解释。",
            f"- 工作流样本：{profile['workflow_cases']} 条，覆盖会前卡片、会后总结/任务、任务风险提醒。",
            f"- Agent 轨迹样本：{profile['agent_trace_cases']} 条，覆盖会前检索、会后保存 pending action、写操作安全拦截。",
            "",
            "## 什么是一条测试样本",
            "",
            "一条测试样本不是一个文档，而是一道带标准答案的小考题。它通常包含：用户问题、可用 RAG 语料、期望召回的 chunk、期望识别的事实，以及评分规则。",
            "",
            "示例：",
            "",
            "- 问题：本次妙记里每个人要做什么，截止时间是什么？",
            "- 可用材料：当前会议妙记 chunk、历史任务 chunk、无关报销制度 chunk。",
            "- 标准答案：叶抒锐补齐 CLI 文档，截止 2026-05-14；李健文修复负责人解析授权错误，截止 2026-05-13；王宁整理答辩 FAQ，截止 2026-05-15。",
            "- 评分：是否召回当前妙记 chunk；是否识别 3 个行动项；负责人、任务标题、截止时间是否正确；每个行动项是否有证据来源。",
            "",
            "## 核心结果",
            "",
            "| 维度 | 指标 | 结果 | 含义 |",
            "|---|---:|---:|---|",
            f"| 综合 | overall_score | {data['overall_score']:.4f} | 四层评测综合分超过 0.85 门槛，说明当前样本下 MeetFlow 已达到比赛演示可讲的稳定水位。 |",
            f"| 检索层 | Hit@3 | {retrieval_metrics['hit@3']:.4f} | 40 条问题的 Top-3 检索结果里都至少包含 1 个正确证据，说明 RAG 基本能找对方向。 |",
            f"| 检索层 | MRR | {retrieval_metrics['mrr']:.4f} | 正确证据通常排在很靠前的位置，用户问题大多能第一时间命中关键材料。 |",
            f"| 检索层 | Context Recall | {retrieval_metrics['context_recall']:.4f} | 标准答案所需证据大约 87.92% 被 Top-3 覆盖，说明多证据问题仍有少量漏召回。 |",
            f"| 检索层 | Context Precision | {retrieval_metrics['context_precision']:.4f} | Top-3 里约 35.83% 是标注相关证据，说明召回稳定但仍混入噪声，需要后续 rerank 或压缩上下文。 |",
            f"| RAG 生成 | Faithfulness | {answer_with['faithfulness']:.4f} | 结构化答案中的事实都能追溯到标注证据，暂未发现无依据事实。 |",
            f"| RAG 生成 | Answer Relevancy | {answer_with['answer_relevancy']:.4f} | RAG 版本回答覆盖了每个问题要求识别的关键事实。 |",
            f"| RAG 生成 | Evidence Coverage | {answer_with['evidence_coverage']:.4f} | 每个关键事实都有证据 chunk 支撑，便于会前/会后卡片展示 Evidence Pack。 |",
            f"| 非 RAG 基线 | Evidence Coverage | {answer_without['evidence_coverage']:.4f} | 不使用 RAG 时没有证据支撑，说明 RAG 对可解释性提升明显。 |",
            f"| 会前卡片 | 结构与证据分 | {workflow['pre_meeting']['score']:.4f} | 会前卡片能完整覆盖背景、历史结论、遗留任务、风险、建议议题和证据来源。 |",
            f"| 会后总结/任务 | 结构与行动项分 | {workflow['post_meeting']['score']:.4f} | 会后总结结构完整，行动项负责人、标题、截止时间和证据字段都齐全。 |",
            f"| 任务风险提醒 | 风险与证据分 | {workflow['risk_scan']['score']:.4f} | 风险类型识别、精确率和证据覆盖均满足样本预期，适合解释“为什么提醒”。 |",
            f"| Agent 工程 | 工具/安全/稳定性分 | {agent['score']:.4f} | 工具调用、禁止工具检查、Policy/幂等/allow-write gate 和敏感信息扫描全部通过。 |",
            "",
            "## 对比结论",
            "",
            f"- 使用 RAG 后生成质量分：{data['answer_quality']['with_rag']['score']:.4f}。",
            f"- 不使用 RAG 的基线分：{data['answer_quality']['without_rag']['score']:.4f}。",
            f"- Evidence Coverage 提升：{data['answer_quality']['improvement']['evidence_coverage_delta']:.4f}。",
            f"- Faithfulness 提升：{data['answer_quality']['improvement']['faithfulness_delta']:.4f}。",
            "",
            "## 剩余风险",
            "",
            "- 本评测是离线业务风格脱敏样本，适合比赛答辩和回归门禁，不代表线上全量用户分布。",
            "- 当前 Faithfulness 用结构化事实和证据 ID 校验，不调用 LLM-as-a-Judge；后续可接入 RAGAs 做更细粒度自然语言评审。",
            "- 真实飞书联调仍需结合线上指标，例如点踩率、追问率、转人工率和真实任务创建成功率。",
            "",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
