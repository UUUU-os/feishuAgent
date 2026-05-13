from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.loader import EmbeddingSettings, KnowledgeSearchSettings, RerankerSettings, StorageSettings
from core.knowledge import KnowledgeIndexStore, register_knowledge_tools
from core.models import AgentToolCall, Resource
from core.tools import ToolRegistry
from scripts.meetflow_worker import summarize_refresh_result
from scripts.pre_meeting_live_test import ensure_rag_event_subscription


class DummyVectorIndex:
    """测试中关闭真实向量库依赖，只保留 SQLite/FTS 检索。"""

    def upsert_document(self, document, chunks):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": True, "count": len(chunks)}

    def search(self, query, query_terms, resource_types, top_k):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": True, "chunk_ids": [], "distances": [], "total_candidates": 0}


class FailingVectorIndex:
    """模拟 ChromaDB 不可用，验证知识库能降级到 BM25 关键词检索。"""

    def upsert_document(self, document, chunks):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": False, "error": "ChromaDB 不可用，无法执行向量检索。"}

    def search(self, query, query_terms, resource_types, top_k):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": False, "error": "ChromaDB 不可用，无法执行向量检索。"}


class DummySubscriptionClient:
    """记录订阅调用，避免单测触达真实飞书。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def detect_drive_file_type(self, document: str, default: str = "docx") -> str:
        return "wiki" if "/wiki/" in document else default

    def subscribe_drive_file(self, file_token: str, file_type: str, identity: str = "user") -> dict[str, object]:
        self.calls.append({"file_token": file_token, "file_type": file_type, "identity": identity})
        return {"data": {"ok": True}}


class KnowledgeToolsTest(unittest.TestCase):
    """覆盖 `knowledge.search` / `knowledge.fetch_chunk` 的结构化输出。"""

    def test_search_and_fetch_chunk_return_evidence_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
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
                search_settings=KnowledgeSearchSettings(
                    fusion_strategy="rrf",
                    rrf_k=60,
                ),
            )
            store.vector_index = DummyVectorIndex()
            store.initialize()
            store.index_resource(
                Resource(
                    resource_id="doc_demo",
                    resource_type="doc",
                    title="MeetFlow M3 方案评审资料",
                    content=(
                        "MeetFlow M3 方案评审需要确认刷新背景幂等键、"
                        "知识检索 evidence pack 和卡片回调处理。"
                    ),
                    source_url="https://example.feishu.cn/docx/m3",
                    updated_at="2026-05-01T10:00:00",
                )
            )

            registry = ToolRegistry()
            register_knowledge_tools(registry, store)
            search_result = registry.execute(
                AgentToolCall(
                    call_id="call_search",
                    tool_name="knowledge.search",
                    arguments={
                        "query": "MeetFlow M3 刷新背景 幂等键",
                        "resource_types": ["doc"],
                        "top_k": 5,
                    },
                )
            )

            self.assertEqual(search_result.status, "success")
            self.assertTrue(search_result.data["hits"])
            first_hit = search_result.data["hits"][0]
            self.assertTrue(first_hit["ref_id"])
            self.assertTrue(first_hit["snippet"])
            self.assertTrue(first_hit["reason"])
            self.assertEqual(first_hit["source_url"], "https://example.feishu.cn/docx/m3")

            fetch_result = registry.execute(
                AgentToolCall(
                    call_id="call_fetch",
                    tool_name="knowledge.fetch_chunk",
                    arguments={"ref_id": first_hit["ref_id"]},
                )
            )

            self.assertEqual(fetch_result.status, "success")
            self.assertEqual(fetch_result.data["ref_id"], first_hit["ref_id"])
            self.assertTrue(fetch_result.data["chunk_id"])
            self.assertIn("刷新背景幂等键", fetch_result.data["text"])

    def test_index_resource_falls_back_to_keyword_index_when_chromadb_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
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
                search_settings=KnowledgeSearchSettings(
                    fusion_strategy="rrf",
                    rrf_k=60,
                ),
            )
            store.vector_index = FailingVectorIndex()
            store.initialize()

            result = store.index_resource(
                Resource(
                    resource_id="doc_d2_keyword_only",
                    resource_type="doc",
                    title="MeetFlow 测试会议前置资料",
                    content=(
                        "MeetFlow 测试会议需要验证 D2 会前智能准备卡。"
                        "上次会议结论是补齐 Evidence Pack，遗留行动项是整理历史风险。"
                    ),
                    source_url="https://example.feishu.cn/docx/d2",
                    updated_at="2026-05-10T20:00:00",
                ),
                force=True,
            )

            self.assertEqual(result.status, "indexed_keyword_only")
            self.assertIn("SQLite/BM25", result.reason)

            search_result = store.search_chunks(
                query="MeetFlow 测试会议 Evidence Pack 历史风险",
                resource_types=["doc"],
                top_k=3,
            )

            self.assertTrue(search_result.hits)
            self.assertEqual(search_result.hits[0].source_url, "https://example.feishu.cn/docx/d2")
            self.assertIn("BM25", search_result.reason)

    def test_event_subscription_status_and_public_job_update_support_listener_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_settings = StorageSettings(
                db_path=str(Path(tmp_dir) / "meetflow.sqlite"),
                project_memory_dir=str(Path(tmp_dir) / "projects"),
                audit_log_path=str(Path(tmp_dir) / "audit.jsonl"),
            )
            store = KnowledgeIndexStore(settings=storage_settings)
            store.vector_index = DummyVectorIndex()
            store.initialize()

            resource = Resource(
                resource_id="wiki_node_demo",
                resource_type="wiki",
                title="MeetFlow 监听测试文档",
                content="日程变化和文档变化应触发工作流并刷新 RAG。",
                source_url="https://example.feishu.cn/wiki/wiki_node_demo",
                source_meta={"document_id": "doc_file_token", "file_type": "wiki"},
                updated_at="2026-05-13T10:00:00",
            )
            client = DummySubscriptionClient()

            subscription = ensure_rag_event_subscription(
                knowledge_store=store,
                client=client,  # type: ignore[arg-type]
                resource=resource,
                identity="user",
            )

            self.assertEqual(subscription["status"], "succeeded")
            self.assertEqual(client.calls, [{"file_token": "doc_file_token", "file_type": "wiki", "identity": "user"}])
            saved_by_resource = store.get_event_subscription("wiki_node_demo")
            saved_by_file_token = store.get_event_subscription("doc_file_token")
            self.assertIsNotNone(saved_by_resource)
            self.assertEqual(saved_by_file_token, saved_by_resource)
            self.assertEqual(store.list_event_subscriptions()[0]["status"], "succeeded")

            repeated = ensure_rag_event_subscription(
                knowledge_store=store,
                client=client,  # type: ignore[arg-type]
                resource=resource,
                identity="user",
            )
            self.assertEqual(repeated["reason"], "already_subscribed")
            self.assertEqual(len(client.calls), 1)

            job = store.enqueue_index_job(
                resource_id="doc_file_token",
                resource_type="wiki",
                reason="event",
                source_url=resource.source_url,
            )
            store.update_index_job_status(job.job_id, status="succeeded", chunk_count=3, content_tokens=42)
            updated = store.get_index_job(job.job_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated["status"], "succeeded")
            self.assertEqual(updated["chunk_count"], 3)
            self.assertEqual(updated["content_tokens"], 42)

    def test_worker_refresh_result_summary_supports_current_dict_shape(self) -> None:
        result, skipped, chunk_count, content_tokens = summarize_refresh_result(
            {
                "job": {"status": "succeeded"},
                "index_result": {
                    "status": "indexed",
                    "skipped": False,
                    "document": {"chunk_count": 2},
                    "chunks": [{"content_tokens": 10}, {"content_tokens": 15}],
                },
            }
        )

        self.assertEqual(result["status"], "indexed")
        self.assertFalse(skipped)
        self.assertEqual(chunk_count, 2)
        self.assertEqual(content_tokens, 25)


if __name__ == "__main__":
    unittest.main()
