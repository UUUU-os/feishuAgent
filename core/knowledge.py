from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import EmbeddingSettings, StorageSettings
from core.logging import get_logger
from core.models import BaseModel, Resource
from core.pre_meeting import RetrievedResource
from core.tools import AgentTool, ToolParameterError, ToolRegistry


DEFAULT_EVIDENCE_TOKEN_BUDGET = 600
DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET = 120
MAX_EVIDENCE_TOKEN_BUDGET = 2000
MAX_EVIDENCE_SNIPPET_TOKEN_BUDGET = 300


@dataclass(slots=True)
class KnowledgeDocument(BaseModel):
    """轻量 RAG 的文档级元数据。

    这里不只保存 embedding 入口，而是保留原始资源 token、标题、URL、
    更新时间、checksum 和索引状态，确保会前卡片里的证据可以追溯。
    """

    document_id: str
    source_type: str
    title: str
    source_url: str = ""
    owner_id: str = ""
    updated_at: str = ""
    permission_scope: str = ""
    checksum: str = ""
    index_status: str = "pending"
    last_indexed_at: int = 0
    chunk_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeChunk(BaseModel):
    """轻量 RAG 的可检索片段。"""

    chunk_id: str
    document_id: str
    chunk_type: str
    text: str
    source_locator: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding_ref: str = ""
    checksum: str = ""
    created_at: int = 0
    updated_at: int = 0


@dataclass(slots=True)
class KnowledgeIndexResult(BaseModel):
    """一次资源索引的结果。"""

    document: KnowledgeDocument
    chunks: list[KnowledgeChunk] = field(default_factory=list)
    status: str = "indexed"
    skipped: bool = False
    reason: str = ""


class OpenAICompatibleEmbeddingFunction:
    """通过真实 OpenAI-compatible `/embeddings` 接口生成向量。"""

    def __init__(self, settings: EmbeddingSettings) -> None:
        self.settings = settings

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - ChromaDB 约定参数名为 input。
        """生成 ChromaDB 可消费的向量。"""

        return self.embed_documents(input)

    def embed_documents(self, texts: list[str] | None = None, **kwargs: Any) -> list[list[float]]:
        """兼容 ChromaDB 新版 embedding function 接口。"""

        final_texts = texts if texts is not None else kwargs.get("input", [])
        return self._request_embeddings([str(item) for item in final_texts])

    def embed_query(self, query: str | None = None, **kwargs: Any) -> list[float] | list[list[float]]:
        """兼容 ChromaDB 查询 embedding 接口。"""

        final_query = query if query is not None else kwargs.get("input", "")
        if isinstance(final_query, list):
            return self._request_embeddings([str(item) for item in final_query])
        return self._request_embeddings([str(final_query)])[0]

    def name(self) -> str:
        """返回 embedding 函数名称，便于 ChromaDB 记录元信息。"""

        return f"meetflow-openai-compatible-{self.settings.model}"

    def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        """调用真实 embedding 服务。"""

        self._validate_config()
        endpoint = join_url(self.settings.api_base, "embeddings")
        payload = {
            "model": self.settings.model,
            "input": texts,
        }
        if self.settings.dimensions > 0:
            payload["dimensions"] = self.settings.dimensions
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Embedding HTTP 错误 status={error.code} endpoint={endpoint} body={error_body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Embedding 网络错误 endpoint={endpoint} error={error}") from error

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Embedding 响应不是合法 JSON endpoint={endpoint} body={body[:500]}") from error
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, list):
            raise RuntimeError(f"Embedding 响应缺少 data 列表 endpoint={endpoint}")
        embeddings: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list):
                raise RuntimeError(f"Embedding 响应条目缺少 embedding endpoint={endpoint}")
            embeddings.append([float(value) for value in embedding])
        if len(embeddings) != len(texts):
            raise RuntimeError(f"Embedding 返回数量不匹配 expected={len(texts)} actual={len(embeddings)}")
        return embeddings

    def _validate_config(self) -> None:
        """检查真实 embedding 服务配置。"""

        if self.settings.provider not in {"openai-compatible", "openai_compatible", "openai"}:
            raise RuntimeError(f"暂不支持的 embedding provider：{self.settings.provider}")
        if not self.settings.api_base:
            raise RuntimeError("Embedding api_base 为空，请设置 MEETFLOW_EMBEDDING_API_BASE")
        if not self.settings.api_key or self.settings.api_key == "replace-with-env-or-local-file":
            raise RuntimeError("Embedding api_key 未配置，请设置 MEETFLOW_EMBEDDING_API_KEY 或 settings.local.json")
        if not self.settings.model:
            raise RuntimeError("Embedding model 为空，请设置 MEETFLOW_EMBEDDING_MODEL")


class SentenceTransformersEmbeddingFunction:
    """使用本地 sentence-transformers 开源模型生成真实向量。"""

    def __init__(self, settings: EmbeddingSettings) -> None:
        self.settings = settings
        self._model: Any | None = None

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - ChromaDB 约定参数名为 input。
        """生成 ChromaDB 可消费的向量。"""

        return self.embed_documents(input)

    def embed_documents(self, texts: list[str] | None = None, **kwargs: Any) -> list[list[float]]:
        """兼容 ChromaDB 新版 embedding function 接口。"""

        final_texts = texts if texts is not None else kwargs.get("input", [])
        return self._encode([str(item) for item in final_texts])

    def embed_query(self, query: str | None = None, **kwargs: Any) -> list[float] | list[list[float]]:
        """兼容 ChromaDB 查询 embedding 接口。"""

        final_query = query if query is not None else kwargs.get("input", "")
        if isinstance(final_query, list):
            return self._encode([str(item) for item in final_query])
        return self._encode([str(final_query)])[0]

    def name(self) -> str:
        """返回 embedding 函数名称，便于 ChromaDB 记录元信息。"""

        return f"meetflow-sentence-transformers-{self.settings.model}"

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """调用本地开源 embedding 模型。"""

        model = self._load_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in embedding] for embedding in embeddings]

    def _load_model(self) -> Any:
        """延迟加载 sentence-transformers 模型。"""

        if self._model is not None:
            return self._model
        if not self.settings.model:
            raise RuntimeError("Embedding model 为空，请设置 MEETFLOW_EMBEDDING_MODEL")
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as error:
            raise RuntimeError(
                "未安装 sentence-transformers。开发阶段可执行：pip install sentence-transformers，"
                "或改用 openai-compatible embedding provider。"
            ) from error
        self._model = SentenceTransformer(self.settings.model)
        return self._model


def build_embedding_function(settings: EmbeddingSettings) -> Any:
    """根据配置创建真实 embedding 函数。"""

    provider = settings.provider.strip().lower()
    if provider in {"openai-compatible", "openai_compatible", "openai"}:
        return OpenAICompatibleEmbeddingFunction(settings)
    if provider in {"sentence-transformers", "sentence_transformers", "local-sentence-transformers"}:
        return SentenceTransformersEmbeddingFunction(settings)
    raise RuntimeError(f"暂不支持的 embedding provider：{settings.provider}")


class ChromaKnowledgeVectorIndex:
    """ChromaDB 向量索引适配器。

    SQLite 仍然保存权威元数据和 chunk 文本；ChromaDB 只负责向量召回。
    """

    def __init__(self, persist_path: Path, collection_name: str, embedding_settings: EmbeddingSettings) -> None:
        self.persist_path = persist_path
        self.collection_name = collection_name
        self.embedding_function = build_embedding_function(embedding_settings)
        self._collection: Any | None = None
        self._available: bool | None = None

    def is_available(self) -> bool:
        """判断 ChromaDB 是否可用。"""

        if self._available is not None:
            return self._available
        try:
            os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
            import chromadb  # noqa: PLC0415 - ChromaDB 是可选运行时依赖。
            from chromadb.config import Settings as ChromaSettings  # noqa: PLC0415

            self.persist_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(self.persist_path),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
        except Exception:
            self._available = False
        return bool(self._available)

    def upsert_document(self, document: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> dict[str, Any]:
        """把一个文档的 chunk 写入 ChromaDB。"""

        if not chunks:
            return {"ok": True, "count": 0}
        try:
            collection = self._get_collection()
            existing = collection.get(where={"document_id": document.document_id})
            existing_ids = existing.get("ids") or []
            if existing_ids:
                collection.delete(ids=existing_ids)
            collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                documents=[chunk.text for chunk in chunks],
                metadatas=[build_chroma_metadata(document, chunk) for chunk in chunks],
            )
            return {"ok": True, "count": len(chunks)}
        except Exception as error:  # noqa: BLE001 - 向量库失败时允许 SQLite 检索回退。
            return {"ok": False, "error": str(error)}

    def search(
        self,
        query: str,
        query_terms: list[str],
        resource_types: list[str],
        top_k: int,
    ) -> dict[str, Any]:
        """通过 ChromaDB 查询相似 chunk。"""

        try:
            collection = self._get_collection()
            n_results = max(1, min(top_k * 4, 40))
            result = collection.query(
                query_texts=[query or " ".join(query_terms)],
                n_results=n_results,
                include=["distances", "metadatas"],
            )
            ids = list((result.get("ids") or [[]])[0])
            distances = list((result.get("distances") or [[]])[0])
            metadatas = list((result.get("metadatas") or [[]])[0])
            filtered_ids: list[str] = []
            filtered_distances: list[float] = []
            normalized_types = {normalize_source_type(item) for item in resource_types if item}
            for index, chunk_id in enumerate(ids):
                metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
                source_type = normalize_source_type(str(metadata.get("source_type") or ""))
                if normalized_types and source_type not in normalized_types:
                    continue
                filtered_ids.append(str(chunk_id))
                filtered_distances.append(float(distances[index] if index < len(distances) else 1.0))
            return {
                "ok": True,
                "chunk_ids": filtered_ids,
                "distances": filtered_distances,
                "total_candidates": len(ids),
            }
        except Exception as error:  # noqa: BLE001 - 向量库失败时允许 SQLite 检索回退。
            return {"ok": False, "error": str(error)}

    def _get_collection(self) -> Any:
        """获取 Chroma collection，不可用时抛错给调用方回退。"""

        if not self.is_available() or self._collection is None:
            raise RuntimeError("ChromaDB 不可用，无法执行向量检索。")
        return self._collection


@dataclass(slots=True)
class KnowledgeSearchHit(BaseModel):
    """知识检索返回给 Agent 的压缩证据片段。"""

    ref_id: str
    chunk_id: str
    document_id: str
    source_type: str
    title: str
    snippet: str
    reason: str
    score: float
    source_url: str = ""
    source_locator: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeSearchResult(BaseModel):
    """`knowledge.search` 的结构化返回值。"""

    query: str
    hits: list[KnowledgeSearchHit] = field(default_factory=list)
    omitted_count: int = 0
    token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET
    used_tokens: int = 0
    low_confidence: bool = False
    reason: str = ""


@dataclass(slots=True)
class KnowledgeChunkFetchResult(BaseModel):
    """`knowledge.fetch_chunk` 的结构化返回值。"""

    ref_id: str
    chunk_id: str
    document_id: str
    source_type: str
    title: str
    text: str
    source_url: str = ""
    source_locator: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeIndexStore:
    """保存 M3 轻量知识索引的本地 SQLite 存储。

    当前采用项目内单独的 `storage/knowledge/knowledge.sqlite`，避免和已有
    workflow 运行结果表混在一起。后续如果引入向量库，也可以继续让这里
    保存元数据和回链信息。
    """

    def __init__(
        self,
        settings: StorageSettings,
        db_path: str | Path | None = None,
        embedding_settings: EmbeddingSettings | None = None,
    ) -> None:
        self.settings = settings
        self.db_path = Path(db_path) if db_path else Path(settings.db_path).parent / "knowledge" / "knowledge.sqlite"
        self.vector_path = self.db_path.parent / "chroma"
        if embedding_settings is None:
            embedding_settings = build_embedding_settings_from_env()
        self.embedding_settings = embedding_settings
        model_digest = hashlib.sha1(f"{embedding_settings.model}:{embedding_settings.dimensions}".encode("utf-8")).hexdigest()[:8]
        self.vector_collection_name = f"meetflow_knowledge_chunks_{model_digest}"
        self.vector_index = ChromaKnowledgeVectorIndex(
            persist_path=self.vector_path,
            collection_name=self.vector_collection_name,
            embedding_settings=embedding_settings,
        )
        self.logger = get_logger("meetflow.knowledge")

    def initialize(self) -> None:
        """初始化知识索引表。"""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    permission_scope TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    index_status TEXT NOT NULL,
                    last_indexed_at INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source_locator TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_ref TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(document_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks(document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_documents_source_type ON knowledge_documents(source_type)")
            conn.commit()
        self.logger.info("知识索引存储初始化完成 db_path=%s", self.db_path)

    def index_resource(self, resource: Resource | RetrievedResource, force: bool = False) -> KnowledgeIndexResult:
        """清洗并索引一个资源。

        当 `updated_at + checksum` 未变化时，默认跳过重建，满足 T3.4 的增量
        更新边界。传入 `force=True` 可以强制重建。
        """

        document, chunks = build_knowledge_index(resource)
        existing = self.get_document(document.document_id)
        if (
            existing
            and not force
            and existing.get("updated_at") == document.updated_at
            and existing.get("checksum") == document.checksum
        ):
            document.index_status = existing.get("index_status", "succeeded")
            document.last_indexed_at = int(existing.get("last_indexed_at", 0) or 0)
            document.chunk_count = int(existing.get("chunk_count", 0) or 0)
            return KnowledgeIndexResult(
                document=document,
                chunks=[],
                status="skipped",
                skipped=True,
                reason="资源 updated_at + checksum 未变化，跳过重复索引。",
            )

        now = int(time.time())
        document.index_status = "succeeded"
        document.last_indexed_at = now
        document.chunk_count = len(chunks)
        for chunk in chunks:
            if not chunk.created_at:
                chunk.created_at = now
            chunk.updated_at = now
            chunk.embedding_ref = f"chroma:{self.vector_collection_name}:{chunk.chunk_id}"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document.document_id,))
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_documents (
                    document_id,
                    source_type,
                    title,
                    source_url,
                    owner_id,
                    updated_at,
                    permission_scope,
                    checksum,
                    index_status,
                    last_indexed_at,
                    chunk_count,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.source_type,
                    document.title,
                    document.source_url,
                    document.owner_id,
                    document.updated_at,
                    document.permission_scope,
                    document.checksum,
                    document.index_status,
                    document.last_indexed_at,
                    document.chunk_count,
                    json.dumps(document.metadata, ensure_ascii=False),
                ),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO knowledge_chunks (
                    chunk_id,
                    document_id,
                    chunk_type,
                    text,
                    source_locator,
                    metadata_json,
                    embedding_ref,
                    checksum,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.chunk_type,
                        chunk.text,
                        chunk.source_locator,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        chunk.embedding_ref,
                        chunk.checksum,
                        chunk.created_at,
                        chunk.updated_at,
                    )
                    for chunk in chunks
                ],
            )
            conn.commit()

        vector_result = self.vector_index.upsert_document(document, chunks)
        if not vector_result.get("ok"):
            raise RuntimeError(f"ChromaDB 向量索引写入失败 document_id={document.document_id} error={vector_result.get('error')}")

        return KnowledgeIndexResult(
            document=document,
            chunks=chunks,
            status="indexed",
            skipped=False,
            reason=f"资源已清洗为 {len(chunks)} 个 chunk 并写入知识索引。",
        )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        """读取文档元数据。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM knowledge_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def list_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """读取某个文档的 chunk 列表。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE document_id = ? ORDER BY chunk_id",
                (document_id,),
            ).fetchall()
        chunks: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
            chunks.append(data)
        return chunks

    def search_chunks(
        self,
        query: str,
        meeting_id: str = "",
        project_id: str = "",
        resource_types: list[str] | None = None,
        time_window: str = "recent_90_days",
        top_k: int = 5,
        evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
        max_snippet_tokens: int = DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET,
    ) -> KnowledgeSearchResult:
        """在本地知识 chunk 中做轻量 RAG 召回。

        当前通过 ChromaDB 向量索引召回候选 chunk，再结合结构化元数据、
        更新时间和关键词命中生成压缩 evidence pack，避免把全文直接塞回 LLM。
        """

        self.initialize()
        normalized_types = {normalize_source_type(item) for item in resource_types or [] if item}
        query_terms = extract_query_terms(query, project_id=project_id, meeting_id=meeting_id)
        final_top_k = max(1, min(int(top_k or 5), 10))
        final_token_budget = clamp_int(
            evidence_token_budget,
            minimum=120,
            maximum=MAX_EVIDENCE_TOKEN_BUDGET,
            default=DEFAULT_EVIDENCE_TOKEN_BUDGET,
        )
        final_snippet_budget = clamp_int(
            max_snippet_tokens,
            minimum=40,
            maximum=MAX_EVIDENCE_SNIPPET_TOKEN_BUDGET,
            default=DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET,
        )
        vector_result = self.vector_index.search(
            query=query,
            query_terms=query_terms,
            resource_types=list(normalized_types),
            top_k=final_top_k,
        )
        if vector_result.get("ok") and vector_result.get("chunk_ids"):
            hits = self._build_vector_hits(
                chunk_ids=list(vector_result.get("chunk_ids") or []),
                distances=list(vector_result.get("distances") or []),
                query_terms=query_terms,
                query=query,
                time_window=time_window,
                top_k=final_top_k,
            )
            packed_hits, budget_omitted, used_tokens = build_evidence_pack(
                hits,
                token_budget=final_token_budget,
                max_snippet_tokens=final_snippet_budget,
            )
            candidate_omitted = max(int(vector_result.get("total_candidates", len(hits))) - len(hits), 0)
            return KnowledgeSearchResult(
                query=query,
                hits=packed_hits,
                omitted_count=candidate_omitted + budget_omitted,
                token_budget=final_token_budget,
                used_tokens=used_tokens,
                low_confidence=not packed_hits or packed_hits[0].score < 0.35,
                reason=(
                    f"通过 ChromaDB 向量索引召回 {len(hits)} 条知识片段，"
                    f"按 evidence token budget 返回 {len(packed_hits)} 条。"
                ),
            )
        if not vector_result.get("ok"):
            raise RuntimeError(f"ChromaDB 向量检索失败 error={vector_result.get('error')}")
        return KnowledgeSearchResult(
            query=query,
            hits=[],
            omitted_count=0,
            token_budget=final_token_budget,
            used_tokens=0,
            low_confidence=True,
            reason="ChromaDB 向量索引未召回到知识片段，请确认资源是否已索引或放宽查询条件。",
        )

    def _build_vector_hits(
        self,
        chunk_ids: list[str],
        distances: list[float],
        query_terms: list[str],
        query: str,
        time_window: str,
        top_k: int,
    ) -> list[KnowledgeSearchHit]:
        """把 ChromaDB 返回的 chunk_id 转回权威元数据和 evidence pack。"""

        if not chunk_ids:
            return []
        placeholders = ", ".join("?" for _ in chunk_ids)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT
                    chunks.chunk_id,
                    chunks.document_id,
                    chunks.chunk_type,
                    chunks.text,
                    chunks.source_locator,
                    chunks.metadata_json AS chunk_metadata_json,
                    chunks.updated_at AS chunk_updated_at,
                    documents.source_type,
                    documents.title,
                    documents.source_url,
                    documents.updated_at AS document_updated_at,
                    documents.metadata_json AS document_metadata_json
                FROM knowledge_chunks AS chunks
                JOIN knowledge_documents AS documents
                    ON documents.document_id = chunks.document_id
                WHERE chunks.chunk_id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()
        row_by_id = {str(row["chunk_id"]): row for row in rows}
        scored: list[KnowledgeSearchHit] = []
        for index, chunk_id in enumerate(chunk_ids):
            row = row_by_id.get(chunk_id)
            if row is None:
                continue
            hit = score_chunk_row(row, query_terms=query_terms, query=query, time_window=time_window)
            vector_score = distance_to_similarity(distances[index] if index < len(distances) else 1.0)
            hit.score = round(min((hit.score * 0.35) + (vector_score * 0.65), 0.99), 3)
            hit.reason = f"ChromaDB 向量召回:{vector_score:.2f}；{hit.reason}"
            scored.append(hit)
        scored.sort(key=lambda item: (item.score, item.updated_at, item.title), reverse=True)
        return scored[: max(1, min(int(top_k or 5), 10))]

    def fetch_chunk(self, chunk_id: str = "", ref_id: str = "") -> KnowledgeChunkFetchResult:
        """按 chunk_id 或 ref_id 读取更完整证据。"""

        self.initialize()
        final_chunk_id = chunk_id.strip()
        final_ref_id = ref_id.strip()
        if not final_chunk_id and not final_ref_id:
            raise ToolParameterError("knowledge.fetch_chunk 需要传入 chunk_id 或 ref_id")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if final_chunk_id:
                row = conn.execute(
                    """
                    SELECT
                        chunks.chunk_id,
                        chunks.document_id,
                        chunks.text,
                        chunks.source_locator,
                        chunks.metadata_json AS chunk_metadata_json,
                        documents.source_type,
                        documents.title,
                        documents.source_url,
                        documents.updated_at AS document_updated_at,
                        documents.metadata_json AS document_metadata_json
                    FROM knowledge_chunks AS chunks
                    JOIN knowledge_documents AS documents
                        ON documents.document_id = chunks.document_id
                    WHERE chunks.chunk_id = ?
                    """,
                    (final_chunk_id,),
                ).fetchone()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        chunks.chunk_id,
                        chunks.document_id,
                        chunks.text,
                        chunks.source_locator,
                        chunks.metadata_json AS chunk_metadata_json,
                        documents.source_type,
                        documents.title,
                        documents.source_url,
                        documents.updated_at AS document_updated_at,
                        documents.metadata_json AS document_metadata_json
                    FROM knowledge_chunks AS chunks
                    JOIN knowledge_documents AS documents
                        ON documents.document_id = chunks.document_id
                    """
                ).fetchall()
                row = next(
                    (
                        item
                        for item in rows
                        if stable_evidence_ref_id(str(item["document_id"]), str(item["chunk_id"])) == final_ref_id
                    ),
                    None,
                )
        if row is None:
            raise ToolParameterError(f"未找到知识 chunk：{final_chunk_id or final_ref_id}")
        chunk_metadata = json.loads(row["chunk_metadata_json"] or "{}")
        document_metadata = json.loads(row["document_metadata_json"] or "{}")
        return KnowledgeChunkFetchResult(
            ref_id=stable_evidence_ref_id(str(row["document_id"]), str(row["chunk_id"])),
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            source_type=normalize_source_type(str(row["source_type"] or "")),
            title=str(row["title"] or row["document_id"]),
            text=str(row["text"] or ""),
            source_url=str(row["source_url"] or ""),
            source_locator=str(row["source_locator"] or ""),
            updated_at=str(row["document_updated_at"] or ""),
            metadata={**document_metadata, **chunk_metadata},
        )


def build_knowledge_index(resource: Resource | RetrievedResource) -> tuple[KnowledgeDocument, list[KnowledgeChunk]]:
    """把统一资源清洗成 `KnowledgeDocument + KnowledgeChunk[]`。"""

    normalized = normalize_resource_for_index(resource)
    text = normalized["content"]
    checksum = sha256_text(text)
    document = KnowledgeDocument(
        document_id=normalized["document_id"],
        source_type=normalized["source_type"],
        title=normalized["title"],
        source_url=normalized["source_url"],
        owner_id=normalized["owner_id"],
        updated_at=normalized["updated_at"],
        permission_scope=normalized["permission_scope"],
        checksum=checksum,
        index_status="pending",
        metadata=normalized["metadata"],
    )
    chunks = chunk_resource_text(
        document_id=document.document_id,
        source_type=document.source_type,
        text=text,
        base_locator=normalized["source_locator"],
        metadata={
            "title": document.title,
            "source_url": document.source_url,
            "source_type": document.source_type,
        },
    )
    return document, chunks


def normalize_resource_for_index(resource: Resource | RetrievedResource) -> dict[str, Any]:
    """把不同资源模型归一为索引输入。"""

    if isinstance(resource, Resource):
        source_meta = dict(resource.source_meta)
        return {
            "document_id": resource.resource_id,
            "source_type": normalize_source_type(resource.resource_type),
            "title": resource.title or resource.resource_id,
            "content": resource.content or resource.title,
            "source_url": resource.source_url,
            "updated_at": resource.updated_at,
            "owner_id": str(source_meta.get("owner_id") or source_meta.get("owner") or ""),
            "permission_scope": str(source_meta.get("permission_scope") or ""),
            "source_locator": str(
                source_meta.get("source_locator")
                or source_meta.get("block_id")
                or source_meta.get("segment_id")
                or source_meta.get("range")
                or source_meta.get("sheet")
                or ""
            ),
            "metadata": source_meta,
        }

    metadata = dict(resource.metadata)
    return {
        "document_id": resource.resource_id,
        "source_type": normalize_source_type(resource.resource_type),
        "title": resource.title or resource.resource_id,
        "content": resource.summary or resource.title,
        "source_url": resource.source_url,
        "updated_at": resource.updated_at,
        "owner_id": str(metadata.get("owner_id") or metadata.get("owner") or ""),
        "permission_scope": str(metadata.get("permission_scope") or ""),
        "source_locator": resource.source_locator,
        "metadata": metadata,
    }


def chunk_resource_text(
    document_id: str,
    source_type: str,
    text: str,
    base_locator: str = "",
    metadata: dict[str, Any] | None = None,
) -> list[KnowledgeChunk]:
    """按资源类型清洗并切分文本。"""

    if source_type == "sheet":
        raw_chunks = chunk_sheet_text(text)
    elif source_type == "minute":
        raw_chunks = chunk_minute_text(text)
    else:
        raw_chunks = chunk_document_text(text)

    chunks: list[KnowledgeChunk] = []
    for index, item in enumerate(raw_chunks, start=1):
        chunk_text = item["text"].strip()
        if not chunk_text:
            continue
        locator = item.get("source_locator") or f"{base_locator or source_type}:chunk:{index}"
        chunk_checksum = sha256_text(chunk_text)
        chunks.append(
            KnowledgeChunk(
                chunk_id=stable_chunk_id(document_id, index, chunk_checksum),
                document_id=document_id,
                chunk_type=item.get("chunk_type", "paragraph"),
                text=chunk_text,
                source_locator=locator,
                metadata={**(metadata or {}), **item.get("metadata", {})},
                checksum=chunk_checksum,
            )
        )
    return chunks


def chunk_document_text(text: str) -> list[dict[str, Any]]:
    """按标题、段落和列表切分文档文本。"""

    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    current_heading = ""

    def flush_buffer() -> None:
        if not buffer:
            return
        chunks.append(
            {
                "chunk_type": "paragraph",
                "text": "\n".join(buffer),
                "metadata": {"heading": current_heading},
            }
        )
        buffer.clear()

    for line in lines:
        if not line:
            flush_buffer()
            continue
        if is_heading_line(line):
            flush_buffer()
            current_heading = line.lstrip("#").strip()
            chunks.append(
                {
                    "chunk_type": "heading",
                    "text": current_heading,
                    "metadata": {"heading": current_heading},
                }
            )
            continue
        if looks_like_table_row(line):
            flush_buffer()
            chunks.append(
                {
                    "chunk_type": "table",
                    "text": line,
                    "metadata": {"heading": current_heading},
                }
            )
            continue
        buffer.append(line)
        if sum(len(item) for item in buffer) >= 500:
            flush_buffer()
    flush_buffer()
    return chunks or [{"chunk_type": "paragraph", "text": text}]


def chunk_sheet_text(text: str) -> list[dict[str, Any]]:
    """把表格/CSV 风格文本切成行级结构化 chunk。"""

    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return []
    header = lines[0]
    chunks = [
        {
            "chunk_type": "table",
            "text": header,
            "source_locator": "sheet:header",
            "metadata": {"row_index": 0},
        }
    ]
    for index, line in enumerate(lines[1:], start=1):
        chunks.append(
            {
                "chunk_type": "row",
                "text": f"{header}\n{line}",
                "source_locator": f"sheet:row:{index}",
                "metadata": {"row_index": index, "header": header},
            }
        )
    return chunks


def chunk_minute_text(text: str) -> list[dict[str, Any]]:
    """按章节或时间戳切分妙记文本。"""

    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    current_section = ""

    def flush_buffer() -> None:
        if not buffer:
            return
        chunks.append(
            {
                "chunk_type": "minute_section",
                "text": "\n".join(buffer),
                "metadata": {"section": current_section},
            }
        )
        buffer.clear()

    for line in lines:
        if not line:
            flush_buffer()
            continue
        if is_heading_line(line) or re.match(r"^\[?\d{1,2}:\d{2}", line):
            flush_buffer()
            current_section = line.lstrip("#").strip()
            buffer.append(line)
            continue
        buffer.append(line)
        if sum(len(item) for item in buffer) >= 600:
            flush_buffer()
    flush_buffer()
    return chunks or [{"chunk_type": "minute_section", "text": text}]


def is_heading_line(line: str) -> bool:
    """判断一行是否像标题。"""

    stripped = line.strip()
    return stripped.startswith("#") or stripped.startswith(("一、", "二、", "三、", "四、", "1.", "2.", "3."))


def looks_like_table_row(line: str) -> bool:
    """判断一行是否像表格行。"""

    return "|" in line and line.count("|") >= 2


def normalize_source_type(value: str) -> str:
    """归一知识资源类型。"""

    normalized = value.strip().lower()
    mapping = {
        "feishu_document": "doc",
        "document": "doc",
        "documents": "doc",
        "docs": "doc",
        "docx": "doc",
        "attachment": "doc",
        "sheet": "sheet",
        "sheets": "sheet",
        "bitable": "sheet",
        "minute": "minute",
        "minutes": "minute",
        "meeting_minutes": "minute",
        "task": "task",
        "tasks": "task",
    }
    return mapping.get(normalized, normalized or "unknown")


def build_chroma_metadata(document: KnowledgeDocument, chunk: KnowledgeChunk) -> dict[str, str | int | float | bool]:
    """构造 ChromaDB 只接受基础类型的 metadata。"""

    metadata = {
        "document_id": document.document_id,
        "source_type": document.source_type,
        "title": document.title,
        "source_url": document.source_url,
        "updated_at": document.updated_at,
        "source_locator": chunk.source_locator,
        "chunk_type": chunk.chunk_type,
        "checksum": chunk.checksum,
        "metadata_json": json.dumps({**document.metadata, **chunk.metadata}, ensure_ascii=False),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def build_embedding_settings_from_env() -> EmbeddingSettings:
    """从环境变量构造真实 embedding 配置。

    这个兜底只用于调用方仍然只传 `StorageSettings` 的旧路径；正式入口会从
    `load_settings().embedding` 传入完整配置。
    """

    return EmbeddingSettings(
        provider=os.getenv("MEETFLOW_EMBEDDING_PROVIDER", "openai-compatible"),
        model=os.getenv("MEETFLOW_EMBEDDING_MODEL", "text-embedding-3-small"),
        api_base=os.getenv("MEETFLOW_EMBEDDING_API_BASE", ""),
        api_key=os.getenv("MEETFLOW_EMBEDDING_API_KEY", ""),
        dimensions=int(os.getenv("MEETFLOW_EMBEDDING_DIMENSIONS", "1536")),
        timeout_seconds=int(os.getenv("MEETFLOW_EMBEDDING_TIMEOUT_SECONDS", "30")),
    )


def join_url(base_url: str, suffix: str) -> str:
    """拼接 OpenAI-compatible API URL。"""

    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def distance_to_similarity(distance: float) -> float:
    """把 ChromaDB 距离值转换为 0-1 相似度。"""

    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, 1.0 - value)), 3)


def extract_query_terms(query: str, project_id: str = "", meeting_id: str = "") -> list[str]:
    """从工具查询参数中提取轻量检索词。"""

    raw_terms: list[str] = []
    for value in (query, project_id, meeting_id):
        normalized = str(value or "").replace("/", " ").replace("|", " ")
        raw_terms.extend(re.split(r"[\s,，;；:：]+", normalized))
    terms: list[str] = []
    for term in raw_terms:
        clean = term.strip().lower()
        if not clean or len(clean) <= 1:
            continue
        if clean in {"the", "and", "for", "with", "会议", "同步", "讨论"}:
            continue
        terms.append(clean)
    return unique_strings(terms)


def score_chunk_row(
    row: sqlite3.Row,
    query_terms: list[str],
    query: str,
    time_window: str,
) -> KnowledgeSearchHit:
    """给单个 chunk 行计算轻量混合召回分。"""

    chunk_metadata = json.loads(row["chunk_metadata_json"] or "{}")
    document_metadata = json.loads(row["document_metadata_json"] or "{}")
    title = str(row["title"] or row["document_id"])
    text = str(row["text"] or "")
    source_type = normalize_source_type(str(row["source_type"] or ""))
    combined = " ".join(
        [
            title,
            text,
            source_type,
            str(row["source_locator"] or ""),
            json.dumps({**document_metadata, **chunk_metadata}, ensure_ascii=False),
        ]
    ).lower()
    score = 0.0
    reasons: list[str] = []
    for term in query_terms:
        if term in combined:
            score += 0.22 if term in text.lower() else 0.14
            reasons.append(f"命中查询词:{term}")
    if query and query.lower() in combined:
        score += 0.18
        reasons.append("命中完整查询")
    if row["source_locator"]:
        score += 0.04
        reasons.append("包含回链定位")
    if row["source_url"]:
        score += 0.03
        reasons.append("包含来源链接")
    freshness = estimate_document_freshness(str(row["document_updated_at"] or ""), time_window=time_window)
    if freshness:
        score += freshness
        reasons.append("资源更新时间符合窗口")

    snippet = build_snippet(text, query_terms)
    return KnowledgeSearchHit(
        ref_id=stable_evidence_ref_id(str(row["document_id"]), str(row["chunk_id"])),
        chunk_id=str(row["chunk_id"]),
        document_id=str(row["document_id"]),
        source_type=source_type,
        title=title,
        snippet=snippet,
        reason="；".join(unique_strings(reasons[:5])) or "知识片段候选",
        score=round(min(score, 0.99), 3),
        source_url=str(row["source_url"] or ""),
        source_locator=str(row["source_locator"] or ""),
        updated_at=str(row["document_updated_at"] or ""),
        metadata={**document_metadata, **chunk_metadata},
    )


def build_snippet(text: str, query_terms: list[str], max_length: int = 220) -> str:
    """围绕命中词生成压缩片段。"""

    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_length:
        return compact
    lower_text = compact.lower()
    first_hit = min(
        [index for term in query_terms if (index := lower_text.find(term)) >= 0],
        default=0,
    )
    start = max(first_hit - 60, 0)
    end = min(start + max_length, len(compact))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def build_evidence_pack(
    hits: list[KnowledgeSearchHit],
    token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
    max_snippet_tokens: int = DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET,
) -> tuple[list[KnowledgeSearchHit], int, int]:
    """按预算裁剪 evidence pack，确保工具返回的是压缩证据而不是全文。"""

    packed: list[KnowledgeSearchHit] = []
    used_tokens = 0
    for hit in hits:
        packed_hit = KnowledgeSearchHit(
            ref_id=hit.ref_id,
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            source_type=hit.source_type,
            title=hit.title,
            snippet=truncate_text_by_token_budget(hit.snippet, max_snippet_tokens),
            reason=hit.reason,
            score=hit.score,
            source_url=hit.source_url,
            source_locator=hit.source_locator,
            updated_at=hit.updated_at,
            metadata=hit.metadata,
        )
        item_tokens = estimate_evidence_hit_tokens(packed_hit)
        if packed and used_tokens + item_tokens > token_budget:
            break
        if not packed and item_tokens > token_budget:
            packed_hit.snippet = truncate_text_by_token_budget(
                packed_hit.snippet,
                max(20, token_budget - estimate_evidence_hit_tokens(packed_hit, include_snippet=False)),
            )
            item_tokens = estimate_evidence_hit_tokens(packed_hit)
        packed.append(packed_hit)
        used_tokens += item_tokens

    omitted_count = max(len(hits) - len(packed), 0)
    return packed, omitted_count, used_tokens


def estimate_evidence_hit_tokens(hit: KnowledgeSearchHit, include_snippet: bool = True) -> int:
    """估算单条 evidence 返回给模型时占用的 token 数。"""

    fields = [
        hit.ref_id,
        hit.document_id,
        hit.chunk_id,
        hit.title,
        hit.source_url,
        hit.source_locator,
        f"{hit.score:.3f}",
        hit.reason,
    ]
    if include_snippet:
        fields.append(hit.snippet)
    return estimate_text_tokens(" ".join(fields)) + 16


def truncate_text_by_token_budget(text: str, token_budget: int) -> str:
    """按粗略 token 预算截断文本，保留稳定省略号格式。"""

    budget = max(int(token_budget or 0), 0)
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact or estimate_text_tokens(compact) <= budget:
        return compact
    result: list[str] = []
    used = 0
    for char in compact:
        char_tokens = estimate_text_tokens(char)
        if used + char_tokens > max(budget - 1, 0):
            break
        result.append(char)
        used += char_tokens
    return f"{''.join(result).rstrip()}..."


def estimate_text_tokens(text: str) -> int:
    """用轻量规则估算 token 数，避免为预算控制引入 tokenizer 依赖。"""

    if not text:
        return 0
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    non_cjk = re.sub(r"[\u4e00-\u9fff]", " ", text)
    ascii_chunks = [chunk for chunk in re.split(r"\s+", non_cjk.strip()) if chunk]
    ascii_tokens = sum(max(1, (len(chunk) + 3) // 4) for chunk in ascii_chunks)
    return cjk_count + ascii_tokens


def clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    """把工具参数里的数字收敛到安全范围。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def stable_evidence_ref_id(document_id: str, chunk_id: str) -> str:
    """生成与搜索排序无关、可复现的 evidence 引用 ID。"""

    digest = hashlib.sha1(f"{document_id}:{chunk_id}".encode("utf-8")).hexdigest()[:16]
    return f"kref_{digest}"


def estimate_document_freshness(updated_at: str, time_window: str = "recent_90_days") -> float:
    """根据更新时间给知识片段轻微加权。"""

    timestamp = parse_date_like_timestamp(updated_at)
    if timestamp <= 0:
        return 0.0
    age_days = max((time.time() - timestamp) / 86400, 0)
    window_days = parse_time_window_days(time_window)
    if age_days <= min(window_days, 14):
        return 0.10
    if age_days <= window_days:
        return 0.05
    return 0.0


def parse_time_window_days(time_window: str) -> int:
    """解析 recent_N_days 风格时间窗口。"""

    match = re.search(r"(\d+)", time_window or "")
    if match:
        return max(int(match.group(1)), 1)
    return 90


def parse_date_like_timestamp(value: str) -> float:
    """解析常见日期字符串或秒级时间戳。"""

    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.isdigit():
        number = int(text)
        return number / 1000 if number > 10_000_000_000 else float(number)
    for pattern in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(text[:19], pattern))
        except ValueError:
            continue
    return 0.0


def unique_strings(values: list[str]) -> list[str]:
    """按出现顺序去重字符串。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def build_knowledge_search_tool(store: KnowledgeIndexStore) -> AgentTool:
    """构造 `knowledge.search` 只读工具。"""

    return AgentTool(
        internal_name="knowledge.search",
        description="检索 MeetFlow 本地轻量 RAG 知识索引，返回压缩证据包而不是全文。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词。"},
                "meeting_id": {"type": "string", "description": "可选会议 ID，用于审计和检索增强。"},
                "project_id": {"type": "string", "description": "可选项目 ID，用于检索增强。"},
                "resource_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选资源类型，如 doc、sheet、minute、task。",
                },
                "time_window": {"type": "string", "description": "可选时间窗口，如 recent_90_days。"},
                "top_k": {"type": "integer", "description": "最多返回的证据片段数，最大 10。"},
                "evidence_token_budget": {
                    "type": "integer",
                    "description": "本次 evidence pack 的粗略 token 预算，默认 600，最大 2000。",
                },
                "max_snippet_tokens": {
                    "type": "integer",
                    "description": "单条 snippet 的粗略 token 上限，默认 120，最大 300。",
                },
            },
            "required": ["query"],
        },
        handler=lambda **arguments: store.search_chunks(
            query=str(arguments.get("query") or ""),
            meeting_id=str(arguments.get("meeting_id") or ""),
            project_id=str(arguments.get("project_id") or ""),
            resource_types=list(arguments.get("resource_types") or []),
            time_window=str(arguments.get("time_window") or "recent_90_days"),
            top_k=int(arguments.get("top_k") or 5),
            evidence_token_budget=int(arguments.get("evidence_token_budget") or DEFAULT_EVIDENCE_TOKEN_BUDGET),
            max_snippet_tokens=int(arguments.get("max_snippet_tokens") or DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET),
        ),
        read_only=True,
        metadata={"category": "knowledge", "risk_level": "low"},
    )


def build_knowledge_fetch_chunk_tool(store: KnowledgeIndexStore) -> AgentTool:
    """构造 `knowledge.fetch_chunk` 只读工具。"""

    return AgentTool(
        internal_name="knowledge.fetch_chunk",
        description="按 ref_id 或 chunk_id 展开一条知识片段，返回更完整内容和原文位置。",
        parameters={
            "type": "object",
            "properties": {
                "ref_id": {"type": "string", "description": "knowledge.search 返回的 ref_id。"},
                "chunk_id": {"type": "string", "description": "知识 chunk ID。"},
            },
            "required": [],
        },
        handler=lambda **arguments: store.fetch_chunk(
            chunk_id=str(arguments.get("chunk_id") or ""),
            ref_id=str(arguments.get("ref_id") or ""),
        ),
        read_only=True,
        metadata={"category": "knowledge", "risk_level": "low"},
    )


def register_knowledge_tools(registry: ToolRegistry, store: KnowledgeIndexStore) -> None:
    """把 T3.6 知识检索工具注册到 Agent 工具体系。"""

    registry.register(build_knowledge_search_tool(store))
    registry.register(build_knowledge_fetch_chunk_tool(store))


def stable_chunk_id(document_id: str, index: int, checksum: str) -> str:
    """生成稳定 chunk ID。"""

    digest = hashlib.sha1(f"{document_id}:{index}:{checksum}".encode("utf-8")).hexdigest()[:12]
    return f"{document_id}#chunk_{index}_{digest}"


def sha256_text(text: str) -> str:
    """计算文本 checksum。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
