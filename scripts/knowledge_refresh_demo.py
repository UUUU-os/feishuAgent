from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/knowledge_refresh_demo.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core import KnowledgeIndexStore, Resource, configure_logging


class NoopVectorIndex:
    """演示脚本使用的无副作用向量索引，避免下载模型或访问外网。"""

    def upsert_document(self, document: object, chunks: list[object]) -> dict[str, object]:
        return {"ok": True, "count": len(chunks)}

    def search(self, **_: object) -> dict[str, object]:
        return {"ok": True, "chunk_ids": [], "distances": [], "total_candidates": 0}


def main() -> int:
    """演示 T3.10 手动刷新和定时校验任务入口。"""

    settings = load_settings()
    configure_logging(settings.logging)
    demo_db_path = Path(settings.storage.db_path).parent / "knowledge" / "knowledge_refresh_demo.sqlite"
    store = KnowledgeIndexStore(settings.storage, db_path=demo_db_path, embedding_settings=settings.embedding, reranker_settings=settings.reranker)
    store.vector_index = NoopVectorIndex()
    store.initialize()
    resource = Resource(
        resource_id="refresh_demo_doc",
        resource_type="doc",
        title="MeetFlow 知识刷新演示文档",
        content="# 背景\n文档变化后应写入 index_jobs，再由 worker 拉取最新内容并重建索引。",
        source_url="https://example.feishu.cn/docx/refresh_demo_doc",
        updated_at="2026-04-29",
        source_meta={"block_id": "block_refresh_demo"},
    )
    manual_job = store.enqueue_index_job(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        reason="manual",
        source_url=resource.source_url,
        payload={"title": resource.title},
    )
    refresh_result = store.refresh_resource(resource, reason="manual", force=True)
    scheduled_jobs = store.enqueue_recent_document_refresh_jobs(limit=5)
    print(
        json.dumps(
            {
                "manual_job": manual_job.to_dict(),
                "refresh_result": refresh_result,
                "scheduled_jobs": [job.to_dict() for job in scheduled_jobs],
                "jobs": store.list_index_jobs(limit=10),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
