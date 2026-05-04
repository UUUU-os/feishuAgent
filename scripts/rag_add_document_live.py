from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/rag_add_document_live.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuClient
from config import load_settings
from core import KnowledgeIndexStore, configure_logging
from scripts.meetflow_agent_live_test import save_token_bundle
from scripts.pre_meeting_live_test import ensure_rag_event_subscription


def parse_args() -> argparse.Namespace:
    """解析 RAG 文档首次接入参数。"""

    parser = argparse.ArgumentParser(
        description="把飞书文档首次加入 RAG：读取文档、建立索引，并注册云文档长连接事件订阅。"
    )
    parser.add_argument("--doc", required=True, help="飞书文档 URL 或 token。")
    parser.add_argument("--identity", default="user", choices=["user", "tenant"], help="读取和订阅文档使用的身份。")
    parser.add_argument("--force-index", action="store_true", help="强制重建索引。")
    parser.add_argument("--dry-run-subscribe", action="store_true", help="只索引，不调用飞书订阅接口。")
    return parser.parse_args()


def main() -> int:
    """执行一次 RAG 文档首次接入。"""

    args = parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    client = FeishuClient(settings.feishu, user_token_callback=lambda bundle: save_token_bundle(settings, bundle))
    store = KnowledgeIndexStore(
        settings.storage,
        embedding_settings=settings.embedding,
        reranker_settings=settings.reranker,
        search_settings=settings.knowledge_search,
    )
    store.initialize()

    resource = client.fetch_document_resource(
        document=args.doc,
        doc_format="xml",
        detail="simple",
        scope="full",
        identity=args.identity,  # type: ignore[arg-type]
    )
    index_result = store.index_resource(resource, force=args.force_index)
    if args.dry_run_subscribe:
        subscription = {"status": "skipped", "reason": "dry_run_subscribe"}
    else:
        try:
            subscription = ensure_rag_event_subscription(
                knowledge_store=store,
                client=client,
                resource=resource,
                identity=args.identity,
            )
        except FeishuAPIError as error:
            subscription = {"status": "failed", "error": str(error)}

    print(
        json.dumps(
            {
                "resource": {
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "title": resource.title,
                    "source_url": resource.source_url,
                    "updated_at": resource.updated_at,
                },
                "index": {
                    "status": index_result.status,
                    "skipped": index_result.skipped,
                    "chunk_count": index_result.document.chunk_count,
                    "reason": index_result.reason,
                },
                "event_subscription": subscription,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
