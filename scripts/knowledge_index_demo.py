from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/knowledge_index_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import KnowledgeIndexStore, Resource, configure_logging


def main() -> int:
    """验证 T3.4 轻量知识索引与文档清洗。"""

    settings = load_settings()
    configure_logging(settings.logging)
    store = KnowledgeIndexStore(settings.storage, embedding_settings=settings.embedding)
    store.initialize()

    results = []
    for resource in build_sample_resources():
        first_result = store.index_resource(resource, force=True)
        second_result = store.index_resource(resource)
        chunks = store.list_chunks(resource.resource_id)
        results.append(
            {
                "resource_id": resource.resource_id,
                "first_index": first_result.to_dict(),
                "second_index": second_result.to_dict(),
                "stored_document": store.get_document(resource.resource_id),
                "stored_chunks": chunks,
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def build_sample_resources() -> list[Resource]:
    """构造文档、表格、妙记三类清洗样例。"""

    return [
        Resource(
            resource_id="knowledge_demo_doc",
            resource_type="feishu_document",
            title="MeetFlow M3 轻量 RAG 方案",
            content=(
                "# 背景\n"
                "M3 需要用轻量 RAG 支撑会前知识卡片。\n\n"
                "# 设计\n"
                "- 保存 KnowledgeDocument 元数据。\n"
                "- 保存 KnowledgeChunk，并保留 block 定位。\n"
                "| 字段 | 说明 |\n"
                "| checksum | 判断是否需要重建 |\n"
            ),
            source_url="https://example.feishu.cn/docx/knowledge_demo_doc",
            updated_at="2026-04-26",
            source_meta={"block_id": "block_m3_rag", "owner_id": "ou_demo_owner"},
        ),
        Resource(
            resource_id="knowledge_demo_sheet",
            resource_type="sheet",
            title="M3 待办推进表",
            content=(
                "事项,负责人,状态\n"
                "实现 KnowledgeDocument,研发负责人,进行中\n"
                "实现 checksum 增量更新,研发负责人,待评审\n"
            ),
            source_url="https://example.feishu.cn/sheets/knowledge_demo_sheet",
            updated_at="2026-04-27",
            source_meta={"sheet": "推进表"},
        ),
        Resource(
            resource_id="knowledge_demo_minute",
            resource_type="minute",
            title="上次 M3 评审妙记",
            content=(
                "# 上次结论\n"
                "[00:01] 产品负责人：先实现轻量索引和证据回链。\n"
                "[00:05] 研发负责人：T3.4 先落 SQLite store，后续再接工具。\n\n"
                "# 待确认\n"
                "[00:10] 是否需要首版 embedding 可以推迟到 T3.6。"
            ),
            source_url="https://example.feishu.cn/minutes/knowledge_demo_minute",
            updated_at="2026-04-24",
            source_meta={"segment_id": "seg_m3_review"},
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
