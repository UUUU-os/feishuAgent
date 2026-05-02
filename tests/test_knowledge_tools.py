from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config.loader import EmbeddingSettings, KnowledgeSearchSettings, RerankerSettings, StorageSettings
from core.knowledge import KnowledgeIndexStore, register_knowledge_tools
from core.models import AgentToolCall, Resource
from core.tools import ToolRegistry


class DummyVectorIndex:
    """测试中关闭真实向量库依赖，只保留 SQLite/FTS 检索。"""

    def upsert_document(self, document, chunks):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": True, "count": len(chunks)}

    def search(self, query, query_terms, resource_types, top_k):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": True, "chunk_ids": [], "distances": [], "total_candidates": 0}


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


if __name__ == "__main__":
    unittest.main()
