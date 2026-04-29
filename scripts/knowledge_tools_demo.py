from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/knowledge_tools_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import (
    AgentToolCall,
    KnowledgeIndexStore,
    Resource,
    ToolRegistry,
    configure_logging,
    register_knowledge_tools,
)


def main() -> int:
    """验证 T3.6 知识检索 Agent 工具。"""

    settings = load_settings()
    configure_logging(settings.logging)
    demo_db_path = Path(settings.storage.db_path).parent / "knowledge" / "knowledge_tools_demo.sqlite"
    store = KnowledgeIndexStore(settings.storage, db_path=demo_db_path, embedding_settings=settings.embedding)
    store.initialize()
    seed_resources(store)

    registry = ToolRegistry()
    register_knowledge_tools(registry, store)

    search_result = registry.execute(
        AgentToolCall(
            call_id="demo_search",
            tool_name="knowledge_search",
            arguments={
                "query": "MeetFlow M3 会前卡片 上次结论 风险",
                "project_id": "meetflow",
                "resource_types": ["doc", "minute", "task"],
                "top_k": 3,
            },
        )
    )
    first_ref_id = ""
    hits = search_result.data.get("hits") if isinstance(search_result.data, dict) else []
    if hits and isinstance(hits[0], dict):
        first_ref_id = str(hits[0].get("ref_id") or "")

    fetch_result = registry.execute(
        AgentToolCall(
            call_id="demo_fetch",
            tool_name="knowledge_fetch_chunk",
            arguments={"ref_id": first_ref_id},
        )
    )
    print(
        json.dumps(
            {
                "search": search_result.to_dict(),
                "fetch": fetch_result.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if search_result.is_success() and fetch_result.is_success() else 1


def seed_resources(store: KnowledgeIndexStore) -> None:
    """写入 T3.6 工具验证所需的样例知识。"""

    resources = [
        Resource(
            resource_id="knowledge_tool_doc",
            resource_type="doc",
            title="MeetFlow M3 会前卡片设计",
            content=(
                "# 上次结论\n"
                "会前卡片要用 knowledge.search 召回压缩证据包，结论必须带来源。\n\n"
                "# 当前问题\n"
                "T3.6 需要让 Agent 能通过 ref_id 二次展开 chunk。\n\n"
                "# 风险\n"
                "如果只返回全文，长文档会挤占 Agent 上下文。"
            ),
            source_url="https://example.feishu.cn/docx/knowledge_tool_doc",
            updated_at="2026-04-28",
            source_meta={"block_id": "block_knowledge_tool_doc"},
        ),
        Resource(
            resource_id="knowledge_tool_minute",
            resource_type="minute",
            title="上次 M3 评审妙记",
            content="[00:01] 决定先完成本地轻量 RAG 工具，再接飞书真实文档读取。",
            source_url="https://example.feishu.cn/minutes/knowledge_tool_minute",
            updated_at="2026-04-27",
            source_meta={"segment_id": "seg_knowledge_tool_minute"},
        ),
    ]
    for resource in resources:
        store.index_resource(resource, force=True)


if __name__ == "__main__":
    raise SystemExit(main())
