from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
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

from config import EmbeddingSettings, KnowledgeSearchSettings, RerankerSettings, StorageSettings
from core.logging import get_logger
from core.models import BaseModel, Resource
from core.pre_meeting import RetrievedResource
from core.tools import AgentTool, ToolParameterError, ToolRegistry


DEFAULT_EVIDENCE_TOKEN_BUDGET = 600
DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET = 120
MAX_EVIDENCE_TOKEN_BUDGET = 2000
MAX_EVIDENCE_SNIPPET_TOKEN_BUDGET = 300
DEFAULT_VECTOR_WEIGHT = 0.65
DEFAULT_KEYWORD_WEIGHT = 0.30
DEFAULT_FRESHNESS_WEIGHT = 0.05
DEFAULT_SIMILARITY_THRESHOLD = 0.20
DEFAULT_RERANKER_TOP_K = 32
DEFAULT_RERANKER_WEIGHT = 0.25
DEFAULT_FUSION_STRATEGY = "rrf"
DEFAULT_RRF_K = 60
DOC_CHILD_CHUNK_TARGET_TOKENS = 420
DOC_CHILD_CHUNK_MAX_TOKENS = 680


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
    chunk_order: int = 0
    parent_chunk_id: str = ""
    doc_type: str = ""
    content_tokens: int = 0
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


@dataclass(slots=True)
class IndexJob(BaseModel):
    """知识索引刷新任务。

    T3.10 先落地本地队列表结构和手动刷新入口；飞书事件订阅后续只需要
    把资源变化写入这个模型，后台 worker 再负责拉取最新内容并重建索引。
    """

    job_id: str
    resource_id: str
    resource_type: str
    reason: str = "manual"
    status: str = "pending"
    source_url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    chunk_count: int = 0
    content_tokens: int = 0
    last_error: str = ""
    created_at: int = 0
    updated_at: int = 0


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
        self._last_error: str = ""

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
            self._last_error = ""
        except Exception as error:
            self._available = False
            self._last_error = f"{type(error).__name__}: {error}"
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
            detail = f" 原因：{self._last_error}" if self._last_error else ""
            raise RuntimeError(f"ChromaDB 不可用，无法执行向量检索。{detail}")
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
    vector_similarity: float = 0.0
    term_similarity: float = 0.0
    bm25_score: float = 0.0
    vector_rank: int = 0
    keyword_rank: int = 0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0
    source_url: str = ""
    source_locator: str = ""
    parent_chunk_id: str = ""
    toc_path: list[str] = field(default_factory=list)
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
    knowledge_namespace: str = ""
    vector_collection_name: str = ""
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 0
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
    parent_chunk_id: str = ""
    parent_text: str = ""
    context_chunks: list[dict[str, Any]] = field(default_factory=list)
    toc_path: list[str] = field(default_factory=list)
    positions: dict[str, Any] = field(default_factory=dict)
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
        reranker_settings: RerankerSettings | None = None,
        search_settings: KnowledgeSearchSettings | None = None,
    ) -> None:
        self.settings = settings
        self.db_path = Path(db_path) if db_path else Path(settings.db_path).parent / "knowledge" / "knowledge.sqlite"
        self.vector_path = self.db_path.parent / "chroma"
        if embedding_settings is None:
            embedding_settings = build_embedding_settings_from_env()
        if reranker_settings is None:
            reranker_settings = build_reranker_settings_from_env()
        self.embedding_settings = embedding_settings
        self.reranker_settings = reranker_settings
        self.search_settings = search_settings or build_knowledge_search_settings_from_env()
        self.embedding_fingerprint = build_embedding_fingerprint(embedding_settings)
        self.knowledge_namespace = build_knowledge_namespace(embedding_settings)
        model_digest = hashlib.sha1(self.embedding_fingerprint.encode("utf-8")).hexdigest()[:8]
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
                    chunk_order INTEGER NOT NULL DEFAULT 0,
                    parent_chunk_id TEXT NOT NULL DEFAULT '',
                    doc_type TEXT NOT NULL DEFAULT '',
                    content_tokens INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL,
                    embedding_ref TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(document_id)
                )
                """
            )
            ensure_knowledge_chunk_schema(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks(document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc_type ON knowledge_chunks(doc_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_documents_source_type ON knowledge_documents(source_type)")
            self._ensure_fts_index(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_jobs (
                    job_id TEXT PRIMARY KEY,
                    resource_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    content_tokens INTEGER NOT NULL,
                    last_error TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_index_jobs_status ON index_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_index_jobs_resource_id ON index_jobs(resource_id)")
            conn.commit()
        self.logger.info("知识索引存储初始化完成 db_path=%s", self.db_path)

    def _ensure_fts_index(self, conn: sqlite3.Connection) -> bool:
        """创建 SQLite FTS5/BM25 关键词索引，不可用时保留旧关键词兜底。

        FTS 表只是 `knowledge_chunks` 的检索索引副本，不承载业务主数据；
        命中后仍然回表读取标题、来源、metadata 和完整证据。
        """

        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                USING fts5(
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    title,
                    text,
                    keywords,
                    tokenize='unicode61'
                )
                """
            )
            return True
        except sqlite3.OperationalError as error:
            self.logger.warning("SQLite FTS5 不可用，BM25 将回退到旧关键词扫描 error=%s", error)
            return False

    def index_resource(self, resource: Resource | RetrievedResource, force: bool = False) -> KnowledgeIndexResult:
        """清洗并索引一个资源。

        当 `updated_at + checksum` 未变化时，默认跳过重建，满足 T3.4 的增量
        更新边界。传入 `force=True` 可以强制重建。
        """

        document, chunks = build_knowledge_index(resource)
        embedding_metadata = self.build_embedding_metadata()
        document.metadata = {**document.metadata, **embedding_metadata}
        existing = self.get_document(document.document_id)
        existing_embedding_fingerprint = str((existing or {}).get("metadata", {}).get("embedding_fingerprint") or "")
        if (
            existing
            and not force
            and existing.get("updated_at") == document.updated_at
            and existing.get("checksum") == document.checksum
            and existing_embedding_fingerprint == self.embedding_fingerprint
        ):
            with sqlite3.connect(self.db_path) as conn:
                # 资源本身未变化时不重写向量库；但 FTS5/BM25 是后增索引，
                # 老文档可能还没有全文索引记录，因此这里做一次轻量回填。
                self._ensure_fts_index(conn)
                if self._fts_index_exists(conn):
                    conn.execute("DELETE FROM knowledge_chunks_fts WHERE document_id = ?", (document.document_id,))
                    self._sync_fts_chunks(conn, document=document, chunks=chunks)
                    conn.commit()
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
            chunk.metadata = {**chunk.metadata, **embedding_metadata}

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document.document_id,))
            if self._fts_index_exists(conn):
                conn.execute("DELETE FROM knowledge_chunks_fts WHERE document_id = ?", (document.document_id,))
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
                    chunk_order,
                    parent_chunk_id,
                    doc_type,
                    content_tokens,
                    metadata_json,
                    embedding_ref,
                    checksum,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.chunk_type,
                        chunk.text,
                        chunk.source_locator,
                        chunk.chunk_order,
                        chunk.parent_chunk_id,
                        chunk.doc_type,
                        chunk.content_tokens,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        chunk.embedding_ref,
                        chunk.checksum,
                        chunk.created_at,
                        chunk.updated_at,
                    )
                    for chunk in chunks
                ],
            )
            self._sync_fts_chunks(conn, document=document, chunks=chunks)
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

    def _sync_fts_chunks(self, conn: sqlite3.Connection, document: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> None:
        """把可检索子 chunk 同步到 FTS5 表，供 BM25 使用。

        父级 `parent_section` 通常是长段落合集，只用于证据展开；不进入 BM25
        精准召回，避免长父 chunk 因包含更多词而压过具体子 chunk。
        """

        if not self._fts_index_exists(conn):
            return
        rows: list[tuple[str, str, str, str, str]] = []
        for chunk in chunks:
            if chunk.chunk_type == "parent_section":
                continue
            keywords = chunk.metadata.get("keywords") or []
            rows.append(
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    document.title,
                    chunk.text,
                    " ".join(str(item) for item in keywords),
                )
            )
        if rows:
            conn.executemany(
                """
                INSERT INTO knowledge_chunks_fts (
                    chunk_id,
                    document_id,
                    title,
                    text,
                    keywords
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _fts_index_exists(self, conn: sqlite3.Connection) -> bool:
        """确认当前 SQLite 连接中是否存在可用 FTS5 表。"""

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_chunks_fts'"
        ).fetchone()
        return row is not None

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
                "SELECT * FROM knowledge_chunks WHERE document_id = ? ORDER BY chunk_order, chunk_id",
                (document_id,),
            ).fetchall()
        chunks: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
            chunks.append(data)
        return chunks

    def enqueue_index_job(
        self,
        resource_id: str,
        resource_type: str,
        reason: str = "manual",
        source_url: str = "",
        payload: dict[str, Any] | None = None,
    ) -> IndexJob:
        """写入一条索引刷新任务，供手动刷新、定时校验或事件订阅复用。"""

        self.initialize()
        now = int(time.time())
        job_id = stable_index_job_id(resource_id=resource_id, resource_type=resource_type, reason=reason, source_url=source_url)
        job = IndexJob(
            job_id=job_id,
            resource_id=resource_id,
            resource_type=normalize_source_type(resource_type),
            reason=reason,
            status="pending",
            source_url=source_url,
            payload=dict(payload or {}),
            created_at=now,
            updated_at=now,
        )
        self._save_index_job(job)
        return job

    def refresh_resource(
        self,
        resource: Resource | RetrievedResource,
        reason: str = "manual",
        force: bool = True,
    ) -> dict[str, Any]:
        """手动执行资源刷新任务，并记录任务状态、chunk 数和失败原因。"""

        resource_id = resource.resource_id
        resource_type = normalize_source_type(resource.resource_type)
        source_url = resource.source_url
        job = self.enqueue_index_job(
            resource_id=resource_id,
            resource_type=resource_type,
            reason=reason,
            source_url=source_url,
            payload={"title": resource.title, "updated_at": resource.updated_at},
        )
        self._update_index_job_status(job.job_id, status="running")
        try:
            index_result = self.index_resource(resource, force=force)
        except Exception as error:  # noqa: BLE001 - 刷新任务必须把失败原因落库。
            self._update_index_job_status(job.job_id, status="failed", last_error=str(error))
            raise
        content_tokens = sum(chunk.content_tokens for chunk in index_result.chunks)
        self._update_index_job_status(
            job.job_id,
            status="succeeded" if not index_result.skipped else "skipped",
            chunk_count=index_result.document.chunk_count,
            content_tokens=content_tokens,
        )
        return {
            "job": self.get_index_job(job.job_id),
            "index_result": index_result.to_dict(),
        }

    def enqueue_recent_document_refresh_jobs(self, limit: int = 20) -> list[IndexJob]:
        """为最近被索引或引用过的文档创建定时校验任务。"""

        self.initialize()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT document_id, source_type, source_url, title, updated_at
                FROM knowledge_documents
                ORDER BY last_indexed_at DESC
                LIMIT ?
                """,
                (max(1, int(limit or 20)),),
            ).fetchall()
        jobs: list[IndexJob] = []
        for row in rows:
            jobs.append(
                self.enqueue_index_job(
                    resource_id=str(row["document_id"]),
                    resource_type=str(row["source_type"]),
                    reason="scheduled",
                    source_url=str(row["source_url"] or ""),
                    payload={"title": str(row["title"] or ""), "updated_at": str(row["updated_at"] or "")},
                )
            )
        return jobs

    def list_index_jobs(self, status: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """读取索引刷新任务列表。"""

        self.initialize()
        sql = "SELECT * FROM index_jobs"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit or 20)))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [index_job_row_to_dict(row) for row in rows]

    def get_index_job(self, job_id: str) -> dict[str, Any] | None:
        """按 job_id 读取索引刷新任务。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM index_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return index_job_row_to_dict(row) if row else None

    def _save_index_job(self, job: IndexJob) -> None:
        """保存索引任务。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO index_jobs (
                    job_id, resource_id, resource_type, reason, status, source_url,
                    payload_json, chunk_count, content_tokens, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.resource_id,
                    job.resource_type,
                    job.reason,
                    job.status,
                    job.source_url,
                    json.dumps(job.payload, ensure_ascii=False),
                    job.chunk_count,
                    job.content_tokens,
                    job.last_error,
                    job.created_at,
                    job.updated_at,
                ),
            )
            conn.commit()

    def _update_index_job_status(
        self,
        job_id: str,
        status: str,
        chunk_count: int = 0,
        content_tokens: int = 0,
        last_error: str = "",
    ) -> None:
        """更新索引任务状态。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE index_jobs
                SET status = ?,
                    chunk_count = COALESCE(NULLIF(?, 0), chunk_count),
                    content_tokens = COALESCE(NULLIF(?, 0), content_tokens),
                    last_error = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (status, chunk_count, content_tokens, last_error, int(time.time()), job_id),
            )
            conn.commit()

    def build_embedding_metadata(self) -> dict[str, Any]:
        """构造写入文档和 chunk 的 embedding 治理元数据。"""

        return {
            "embedding_provider": self.embedding_settings.provider,
            "embedding_model": self.embedding_settings.model,
            "embedding_dimensions": self.embedding_settings.dimensions,
            "embedding_fingerprint": self.embedding_fingerprint,
            "knowledge_namespace": self.knowledge_namespace,
            "vector_collection_name": self.vector_collection_name,
        }

    def get_embedding_domain_status(
        self,
        resource_types: set[str] | None = None,
        metadata_filter: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """统计当前检索范围内 embedding 指纹是否和当前配置一致。"""

        self.initialize()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    chunks.chunk_id,
                    chunks.document_id,
                    chunks.chunk_type,
                    chunks.text,
                    chunks.source_locator,
                    chunks.parent_chunk_id,
                    chunks.metadata_json AS chunk_metadata_json,
                    chunks.updated_at AS chunk_updated_at,
                    documents.source_type,
                    documents.title,
                    documents.source_url,
                    documents.owner_id,
                    documents.permission_scope,
                    documents.updated_at AS document_updated_at,
                    documents.metadata_json AS document_metadata_json
                FROM knowledge_chunks AS chunks
                JOIN knowledge_documents AS documents
                    ON documents.document_id = chunks.document_id
                WHERE chunks.chunk_type != 'parent_section'
                """
            ).fetchall()
        compatible: set[str] = set()
        incompatible: set[str] = set()
        unknown: set[str] = set()
        for row in rows:
            source_type = normalize_source_type(str(row["source_type"] or ""))
            if resource_types and source_type not in resource_types:
                continue
            if not row_matches_metadata_filter(row, metadata_filter or {}):
                continue
            if row_matches_embedding_namespace(row, self.embedding_fingerprint):
                compatible.add(str(row["document_id"]))
                continue
            document_metadata = json.loads(row["document_metadata_json"] or "{}")
            if document_metadata.get("embedding_fingerprint"):
                incompatible.add(str(row["document_id"]))
            else:
                unknown.add(str(row["document_id"]))
        return {
            "compatible_count": len(compatible),
            "incompatible_count": len(incompatible),
            "unknown_count": len(unknown),
            "incompatible_document_ids": sorted(incompatible)[:10],
            "unknown_document_ids": sorted(unknown)[:10],
        }

    def search_chunks(
        self,
        query: str,
        meeting_id: str = "",
        project_id: str = "",
        resource_types: list[str] | None = None,
        time_window: str = "recent_90_days",
        top_k: int = 5,
        top_n: int = 0,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
        fusion_strategy: str = "",
        rrf_k: int = 0,
        reranker_enabled: bool | None = None,
        reranker_provider: str = "",
        reranker_model: str = "",
        reranker_top_k: int = 0,
        reranker_weight: float = DEFAULT_RERANKER_WEIGHT,
        filter_project_id: str = "",
        filter_meeting_id: str = "",
        document_id: str = "",
        source_url: str = "",
        owner_id: str = "",
        updated_after: str = "",
        permission_scope: str = "",
        evidence_token_budget: int = DEFAULT_EVIDENCE_TOKEN_BUDGET,
        max_snippet_tokens: int = DEFAULT_EVIDENCE_SNIPPET_TOKEN_BUDGET,
    ) -> KnowledgeSearchResult:
        """在本地知识 chunk 中做轻量 RAG 召回。

        当前通过 ChromaDB 向量索引召回候选 chunk，通过 SQLite FTS5/BM25
        召回关键词候选，再用 RRF 融合排名，避免直接比较不同检索器的原始分数。
        """

        self.initialize()
        normalized_types = {normalize_source_type(item) for item in resource_types or [] if item}
        query_terms = extract_query_terms(query, project_id=project_id, meeting_id=meeting_id)
        metadata_filter = build_search_metadata_filter(
            project_id=filter_project_id,
            meeting_id=filter_meeting_id,
            document_id=document_id,
            source_url=source_url,
            owner_id=owner_id,
            updated_after=updated_after,
            permission_scope=permission_scope,
        )
        domain_status = self.get_embedding_domain_status(
            resource_types=normalized_types,
            metadata_filter=metadata_filter,
        )
        if (
            domain_status["compatible_count"] == 0
            and (domain_status["incompatible_count"] > 0 or domain_status["unknown_count"] > 0)
        ):
            return KnowledgeSearchResult(
                query=query,
                hits=[],
                omitted_count=domain_status["incompatible_count"] + domain_status["unknown_count"],
                token_budget=DEFAULT_EVIDENCE_TOKEN_BUDGET,
                used_tokens=0,
                knowledge_namespace=self.knowledge_namespace,
                vector_collection_name=self.vector_collection_name,
                embedding_provider=self.embedding_settings.provider,
                embedding_model=self.embedding_settings.model,
                embedding_dimensions=self.embedding_settings.dimensions,
                low_confidence=True,
                reason=(
                    "当前检索范围只有 embedding 指纹不一致或缺少指纹的旧索引，已拒绝混合检索；"
                    f"当前 namespace={self.knowledge_namespace} collection={self.vector_collection_name}；"
                    f"incompatible={domain_status['incompatible_count']} unknown={domain_status['unknown_count']}。"
                ),
            )
        final_top_k = max(1, min(int(top_k or 20), 50))
        final_top_n = max(1, min(int(top_n or top_k or 5), 10))
        final_threshold = clamp_float(
            similarity_threshold,
            minimum=0.0,
            maximum=0.95,
            default=DEFAULT_SIMILARITY_THRESHOLD,
        )
        final_vector_weight = clamp_float(
            vector_weight,
            minimum=0.0,
            maximum=1.0,
            default=DEFAULT_VECTOR_WEIGHT,
        )
        final_keyword_weight = clamp_float(
            keyword_weight,
            minimum=0.0,
            maximum=1.0,
            default=DEFAULT_KEYWORD_WEIGHT,
        )
        final_fusion_strategy = normalize_fusion_strategy(fusion_strategy or self.search_settings.fusion_strategy)
        final_rrf_k = clamp_int(
            rrf_k or self.search_settings.rrf_k,
            minimum=1,
            maximum=200,
            default=DEFAULT_RRF_K,
        )
        final_reranker_enabled = self.reranker_settings.enabled if reranker_enabled is None else bool(reranker_enabled)
        final_reranker_provider = (reranker_provider or self.reranker_settings.provider or "local-rule").strip()
        final_reranker_model = (reranker_model or self.reranker_settings.model or "").strip()
        final_reranker_top_k = clamp_int(
            reranker_top_k or self.reranker_settings.top_k,
            minimum=1,
            maximum=64,
            default=DEFAULT_RERANKER_TOP_K,
        )
        final_reranker_weight = clamp_float(
            reranker_weight,
            minimum=0.0,
            maximum=1.0,
            default=DEFAULT_RERANKER_WEIGHT,
        )
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
        vector_hits: list[KnowledgeSearchHit] = []
        vector_error = ""
        if vector_result.get("ok") and vector_result.get("chunk_ids"):
            vector_hits = self._build_vector_hits(
                chunk_ids=list(vector_result.get("chunk_ids") or []),
                distances=list(vector_result.get("distances") or []),
                query_terms=query_terms,
                query=query,
                time_window=time_window,
                top_k=final_top_k,
                metadata_filter=metadata_filter,
            )
        elif not vector_result.get("ok"):
            vector_error = str(vector_result.get("error") or "")

        keyword_hits, keyword_backend = self._build_bm25_hits(
            query_terms=query_terms,
            query=query,
            time_window=time_window,
            resource_types=normalized_types,
            metadata_filter=metadata_filter,
            top_k=final_top_k,
        )
        if final_fusion_strategy == "rrf":
            merged_hits = merge_hybrid_hits_rrf(
                vector_hits=vector_hits,
                keyword_hits=keyword_hits,
                rrf_k=final_rrf_k,
                similarity_threshold=final_threshold,
                threshold_relaxed=bool(document_id or source_url),
            )
        else:
            merged_hits = merge_hybrid_hits(
                vector_hits=vector_hits,
                keyword_hits=keyword_hits,
                vector_weight=final_vector_weight,
                keyword_weight=final_keyword_weight,
                freshness_weight=DEFAULT_FRESHNESS_WEIGHT,
                similarity_threshold=final_threshold,
                threshold_relaxed=bool(document_id or source_url),
            )
        reranker_result = apply_optional_reranker(
            query=query,
            query_terms=query_terms,
            hits=merged_hits,
            enabled=final_reranker_enabled,
            provider=final_reranker_provider,
            model=final_reranker_model,
            top_k=final_reranker_top_k,
            reranker_weight=final_reranker_weight,
        )
        ranked_hits = reranker_result["hits"]
        final_hits = ranked_hits[:final_top_n]
        packed_hits, budget_omitted, used_tokens = build_evidence_pack(
            final_hits,
            token_budget=final_token_budget,
            max_snippet_tokens=final_snippet_budget,
        )
        candidate_count = len(ranked_hits)
        candidate_omitted = max(candidate_count - len(final_hits), 0)
        if packed_hits:
            reason_parts = [
                f"混合检索候选 {candidate_count} 条",
                f"向量命中 {len(vector_hits)} 条",
                f"{keyword_backend} 命中 {len(keyword_hits)} 条",
                f"融合策略 {final_fusion_strategy}",
                f"最终返回 {len(packed_hits)} 条",
            ]
            if final_fusion_strategy == "rrf":
                reason_parts.append(f"rrf_k={final_rrf_k}")
            if reranker_result["enabled"]:
                reason_parts.append(f"reranker:{reranker_result['provider']} 重排 {reranker_result['reranked_count']} 条")
            if domain_status["incompatible_count"] or domain_status["unknown_count"]:
                reason_parts.append(
                    f"已过滤 embedding 不兼容文档 {domain_status['incompatible_count']} 个、缺少指纹旧文档 {domain_status['unknown_count']} 个"
                )
            reason_parts.append(f"namespace={self.knowledge_namespace}")
            reason_parts.append(f"collection={self.vector_collection_name}")
            if vector_error:
                reason_parts.append(f"向量检索失败后使用关键词回退:{vector_error}")
            return KnowledgeSearchResult(
                query=query,
                hits=packed_hits,
                omitted_count=candidate_omitted + budget_omitted,
                token_budget=final_token_budget,
                used_tokens=used_tokens,
                knowledge_namespace=self.knowledge_namespace,
                vector_collection_name=self.vector_collection_name,
                embedding_provider=self.embedding_settings.provider,
                embedding_model=self.embedding_settings.model,
                embedding_dimensions=self.embedding_settings.dimensions,
                low_confidence=packed_hits[0].final_score < max(final_threshold, 0.35),
                reason="；".join(reason_parts),
            )
        return KnowledgeSearchResult(
            query=query,
            hits=[],
            omitted_count=0,
            token_budget=final_token_budget,
            used_tokens=0,
            knowledge_namespace=self.knowledge_namespace,
            vector_collection_name=self.vector_collection_name,
            embedding_provider=self.embedding_settings.provider,
            embedding_model=self.embedding_settings.model,
            embedding_dimensions=self.embedding_settings.dimensions,
            low_confidence=True,
            reason=(
                "混合检索未召回到满足阈值的知识片段，请确认资源是否已索引或放宽查询条件；"
                f"namespace={self.knowledge_namespace} collection={self.vector_collection_name}。"
            ),
        )

    def _build_vector_hits(
        self,
        chunk_ids: list[str],
        distances: list[float],
        query_terms: list[str],
        query: str,
        time_window: str,
        top_k: int,
        metadata_filter: dict[str, str] | None = None,
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
                    chunks.parent_chunk_id,
                    chunks.metadata_json AS chunk_metadata_json,
                    chunks.updated_at AS chunk_updated_at,
                    documents.source_type,
                    documents.title,
                    documents.source_url,
                    documents.owner_id,
                    documents.permission_scope,
                    documents.updated_at AS document_updated_at,
                    documents.metadata_json AS document_metadata_json
                FROM knowledge_chunks AS chunks
                JOIN knowledge_documents AS documents
                    ON documents.document_id = chunks.document_id
                WHERE chunks.chunk_id IN ({placeholders})
                    AND chunks.chunk_type != 'parent_section'
                """,
                chunk_ids,
            ).fetchall()
        row_by_id = {str(row["chunk_id"]): row for row in rows}
        scored: list[KnowledgeSearchHit] = []
        for index, chunk_id in enumerate(chunk_ids):
            row = row_by_id.get(chunk_id)
            if row is None:
                continue
            if not row_matches_metadata_filter(row, metadata_filter or {}):
                continue
            if not row_matches_embedding_namespace(row, self.embedding_fingerprint):
                continue
            hit = score_chunk_row(row, query_terms=query_terms, query=query, time_window=time_window)
            vector_score = distance_to_similarity(distances[index] if index < len(distances) else 1.0)
            hit.vector_similarity = vector_score
            hit.vector_rank = index + 1
            hit.reason = f"向量召回:{vector_score:.2f}；{hit.reason}"
            scored.append(hit)
        scored.sort(key=lambda item: (item.vector_similarity, item.term_similarity, item.updated_at), reverse=True)
        for rank, hit in enumerate(scored, start=1):
            hit.vector_rank = rank
        return scored[: max(1, min(int(top_k or 20), 50))]

    def _build_bm25_hits(
        self,
        query_terms: list[str],
        query: str,
        time_window: str,
        resource_types: set[str],
        metadata_filter: dict[str, str],
        top_k: int,
    ) -> tuple[list[KnowledgeSearchHit], str]:
        """优先通过 SQLite FTS5 BM25 做关键词召回，不可用时回退旧扫描。"""

        match_query = build_fts_match_query(query_terms=query_terms, query=query)
        if not match_query:
            return self._build_keyword_hits(
                query_terms=query_terms,
                query=query,
                time_window=time_window,
                resource_types=resource_types,
                metadata_filter=metadata_filter,
                top_k=top_k,
            ), "关键词回退"
        limit = max(1, min(int(top_k or 20) * 4, 100))
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not self._fts_index_exists(conn):
                    raise sqlite3.OperationalError("knowledge_chunks_fts 不存在")
                rows = conn.execute(
                    """
                    SELECT
                        chunks.chunk_id,
                        chunks.document_id,
                        chunks.chunk_type,
                        chunks.text,
                        chunks.source_locator,
                        chunks.parent_chunk_id,
                        chunks.metadata_json AS chunk_metadata_json,
                        chunks.updated_at AS chunk_updated_at,
                        documents.source_type,
                        documents.title,
                        documents.source_url,
                        documents.owner_id,
                        documents.permission_scope,
                        documents.updated_at AS document_updated_at,
                        documents.metadata_json AS document_metadata_json,
                        bm25(knowledge_chunks_fts) AS bm25_score
                    FROM knowledge_chunks_fts
                    JOIN knowledge_chunks AS chunks
                        ON chunks.chunk_id = knowledge_chunks_fts.chunk_id
                    JOIN knowledge_documents AS documents
                        ON documents.document_id = chunks.document_id
                    WHERE knowledge_chunks_fts MATCH ?
                        AND chunks.chunk_type != 'parent_section'
                    ORDER BY bm25_score ASC
                    LIMIT ?
                    """,
                    (match_query, limit),
                ).fetchall()
        except sqlite3.OperationalError as error:
            self.logger.warning("BM25 检索不可用，回退旧关键词扫描 error=%s", error)
            return self._build_keyword_hits(
                query_terms=query_terms,
                query=query,
                time_window=time_window,
                resource_types=resource_types,
                metadata_filter=metadata_filter,
                top_k=top_k,
            ), "关键词回退"

        hits: list[KnowledgeSearchHit] = []
        for row in rows:
            source_type = normalize_source_type(str(row["source_type"] or ""))
            if resource_types and source_type not in resource_types:
                continue
            if not row_matches_metadata_filter(row, metadata_filter):
                continue
            if not row_matches_embedding_namespace(row, self.embedding_fingerprint):
                continue
            hit = score_chunk_row(row, query_terms=query_terms, query=query, time_window=time_window)
            raw_bm25 = float(row["bm25_score"] or 0.0)
            hit.bm25_score = round(raw_bm25, 6)
            hit.term_similarity = bm25_rank_to_similarity(len(hits) + 1)
            hit.keyword_rank = len(hits) + 1
            hit.reason = f"BM25召回 rank:{hit.keyword_rank} bm25:{raw_bm25:.4f}；{hit.reason}"
            hits.append(hit)
            if len(hits) >= max(1, min(int(top_k or 20), 50)):
                break
        return hits, "BM25"

    def _build_keyword_hits(
        self,
        query_terms: list[str],
        query: str,
        time_window: str,
        resource_types: set[str],
        metadata_filter: dict[str, str],
        top_k: int,
    ) -> list[KnowledgeSearchHit]:
        """从 SQLite 权威元数据做关键词召回，作为向量召回的互补和回退。"""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    chunks.chunk_id,
                    chunks.document_id,
                    chunks.chunk_type,
                    chunks.text,
                    chunks.source_locator,
                    chunks.parent_chunk_id,
                    chunks.metadata_json AS chunk_metadata_json,
                    chunks.updated_at AS chunk_updated_at,
                    documents.source_type,
                    documents.title,
                    documents.source_url,
                    documents.owner_id,
                    documents.permission_scope,
                    documents.updated_at AS document_updated_at,
                    documents.metadata_json AS document_metadata_json
                FROM knowledge_chunks AS chunks
                JOIN knowledge_documents AS documents
                    ON documents.document_id = chunks.document_id
                WHERE chunks.chunk_type != 'parent_section'
                """
            ).fetchall()
        hits: list[KnowledgeSearchHit] = []
        for row in rows:
            source_type = normalize_source_type(str(row["source_type"] or ""))
            if resource_types and source_type not in resource_types:
                continue
            if not row_matches_metadata_filter(row, metadata_filter):
                continue
            if not row_matches_embedding_namespace(row, self.embedding_fingerprint):
                continue
            hit = score_chunk_row(row, query_terms=query_terms, query=query, time_window=time_window)
            if hit.term_similarity <= 0 and query_terms:
                continue
            hit.keyword_rank = len(hits) + 1
            hit.reason = f"关键词召回:{hit.term_similarity:.2f}；{hit.reason}"
            hits.append(hit)
        hits.sort(key=lambda item: (item.term_similarity, item.updated_at, item.title), reverse=True)
        final_hits = hits[: max(1, min(int(top_k or 20), 50))]
        for rank, hit in enumerate(final_hits, start=1):
            hit.keyword_rank = rank
        return final_hits

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
                        chunks.chunk_type,
                        chunks.text,
                        chunks.source_locator,
                        chunks.parent_chunk_id,
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
                        chunks.chunk_type,
                        chunks.text,
                        chunks.source_locator,
                        chunks.parent_chunk_id,
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
        parent_context = self._fetch_parent_context(row)
        return KnowledgeChunkFetchResult(
            ref_id=stable_evidence_ref_id(str(row["document_id"]), str(row["chunk_id"])),
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            source_type=normalize_source_type(str(row["source_type"] or "")),
            title=str(row["title"] or row["document_id"]),
            text=str(row["text"] or ""),
            source_url=str(row["source_url"] or ""),
            source_locator=str(row["source_locator"] or ""),
            parent_chunk_id=str(row["parent_chunk_id"] or ""),
            parent_text=parent_context["parent_text"],
            context_chunks=parent_context["context_chunks"],
            toc_path=list(chunk_metadata.get("toc_path") or []),
            positions=dict(chunk_metadata.get("positions") or {}),
            updated_at=str(row["document_updated_at"] or ""),
            metadata={**document_metadata, **chunk_metadata},
        )

    def _fetch_parent_context(self, row: sqlite3.Row) -> dict[str, Any]:
        """按 parent_chunk_id 展开同章节上下文，保留具体命中 chunk 的引用。"""

        parent_chunk_id = str(row["parent_chunk_id"] or "")
        if not parent_chunk_id:
            return {"parent_text": "", "context_chunks": []}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            parent_row = conn.execute(
                "SELECT text FROM knowledge_chunks WHERE chunk_id = ?",
                (parent_chunk_id,),
            ).fetchone()
            sibling_rows = conn.execute(
                """
                SELECT chunk_id, chunk_type, text, source_locator, metadata_json, chunk_order
                FROM knowledge_chunks
                WHERE parent_chunk_id = ?
                    AND chunk_type != 'parent_section'
                ORDER BY chunk_order, chunk_id
                """,
                (parent_chunk_id,),
            ).fetchall()
        context_chunks = []
        for sibling in sibling_rows:
            sibling_metadata = json.loads(sibling["metadata_json"] or "{}")
            context_chunks.append(
                {
                    "ref_id": stable_evidence_ref_id(str(row["document_id"]), str(sibling["chunk_id"])),
                    "chunk_id": str(sibling["chunk_id"]),
                    "chunk_type": str(sibling["chunk_type"] or ""),
                    "source_locator": str(sibling["source_locator"] or ""),
                    "chunk_order": int(sibling["chunk_order"] or 0),
                    "snippet": build_snippet(str(sibling["text"] or ""), []),
                    "positions": dict(sibling_metadata.get("positions") or {}),
                    "toc_path": list(sibling_metadata.get("toc_path") or []),
                    "is_hit": str(sibling["chunk_id"]) == str(row["chunk_id"]),
                }
            )
        return {
            "parent_text": str(parent_row["text"] or "") if parent_row else "",
            "context_chunks": context_chunks,
        }


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

    child_chunks: list[KnowledgeChunk] = []
    for index, item in enumerate(raw_chunks, start=1):
        chunk_text = item["text"].strip()
        if not chunk_text:
            continue
        locator = item.get("source_locator") or f"{base_locator or source_type}:chunk:{index}"
        chunk_checksum = sha256_text(chunk_text)
        child_chunks.append(
            KnowledgeChunk(
                chunk_id=stable_chunk_id(document_id, index, chunk_checksum),
                document_id=document_id,
                chunk_type=item.get("chunk_type", "paragraph"),
                text=chunk_text,
                source_locator=locator,
                chunk_order=index,
                parent_chunk_id=str(item.get("parent_chunk_id") or ""),
                doc_type=source_type,
                content_tokens=estimate_text_tokens(chunk_text),
                metadata=build_chunk_metadata(
                    base_metadata=metadata or {},
                    item_metadata=item.get("metadata", {}),
                    source_type=source_type,
                    source_locator=locator,
                    text=chunk_text,
                    chunk_order=index,
                ),
                checksum=chunk_checksum,
            )
        )
    return attach_parent_chunks(document_id=document_id, source_type=source_type, chunks=child_chunks)


def chunk_document_text(text: str) -> list[dict[str, Any]]:
    """按飞书 DocxXML/HTML 结构切分文档文本。

    飞书文档导出的 XML 往往是一整行 HTML-like 内容，如果继续按换行切分，
    整篇文档会退化成一个超长 chunk。这里先解析标题、段落、列表、表格、
    引用、图片和文档引用等结构块，再按标题路径与 token 预算合并成适合
    embedding 的子 chunk。
    """

    if looks_like_feishu_xml(text):
        blocks = parse_feishu_doc_blocks(text)
        chunks = merge_doc_blocks_into_chunks(blocks)
        if chunks:
            return chunks

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
                "metadata": {"heading": current_heading, "positions": {"heading": current_heading}},
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
                    "metadata": {"heading": current_heading, "positions": {"heading": current_heading}},
                }
            )
            continue
        if looks_like_table_row(line):
            flush_buffer()
            chunks.append(
                {
                    "chunk_type": "table",
                    "text": line,
                    "metadata": {"heading": current_heading, "positions": {"heading": current_heading}},
                }
            )
            continue
        buffer.append(line)
        if sum(len(item) for item in buffer) >= 500:
            flush_buffer()
    flush_buffer()
    return chunks or [{"chunk_type": "paragraph", "text": text}]


def looks_like_feishu_xml(text: str) -> bool:
    """判断内容是否像飞书导出的 XML/HTML 片段。"""

    return bool(re.search(r"</?(title|h[1-6]|p|ul|ol|li|table|tr|td|blockquote|callout|img|cite)\b", text or "", re.I))


class FeishuDocBlockParser(HTMLParser):
    """把飞书 DocxXML/HTML-like 内容解析成有标题归属的结构块。"""

    BLOCK_TAGS = {"p", "li", "td", "th"}
    INLINE_TEXT_TAGS = {"cite"}
    STRUCTURAL_BREAK_TAGS = {"p", "ul", "ol", "li", "table", "tr", "td", "th", "blockquote", "callout", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self.title = ""
        self.heading_stack: list[tuple[int, str]] = []
        self.heading_level = 0
        self.heading_parts: list[str] = []
        self.capture_tag = ""
        self.capture_parts: list[str] = []
        self.capture_depth = 0
        self.capture_attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """处理开始标签，块级标签会先结束不完整标题。"""

        tag = tag.lower()
        attr_map = {key: value or "" for key, value in attrs}
        if self.heading_level and tag in self.STRUCTURAL_BREAK_TAGS:
            self._finish_heading()

        if tag == "title":
            self._start_capture("title", attr_map)
            return
        heading_match = re.fullmatch(r"h([1-6])", tag)
        if heading_match:
            self._finish_capture()
            self.heading_level = int(heading_match.group(1))
            self.heading_parts = []
            return
        if tag in self.BLOCK_TAGS:
            self._finish_capture()
            self._start_capture(tag, attr_map)
            return
        if tag in self.INLINE_TEXT_TAGS and not self.capture_tag:
            self._start_capture(tag, attr_map)
            return
        if tag == "img":
            self._append_media_block(attr_map)
            return
        if self.capture_tag:
            self.capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        """处理结束标签。"""

        tag = tag.lower()
        if tag == "title" and self.capture_tag == "title":
            self.title = clean_doc_text(" ".join(self.capture_parts))
            self._finish_capture(as_block=False)
            return
        if self.heading_level and tag == f"h{self.heading_level}":
            self._finish_heading()
            return
        if self.capture_tag == tag:
            self._finish_capture()
            return
        if self.capture_tag and self.capture_depth > 0:
            self.capture_depth -= 1

    def handle_data(self, data: str) -> None:
        """收集标签内文本。"""

        if self.heading_level:
            self.heading_parts.append(data)
        elif self.capture_tag:
            self.capture_parts.append(data)

    def close(self) -> None:
        """解析结束时补齐未关闭标签。"""

        super().close()
        self._finish_heading()
        self._finish_capture()

    def _start_capture(self, tag: str, attrs: dict[str, str]) -> None:
        self.capture_tag = tag
        self.capture_parts = []
        self.capture_depth = 0
        self.capture_attrs = attrs

    def _finish_capture(self, as_block: bool = True) -> None:
        if not self.capture_tag:
            return
        tag = self.capture_tag
        text = clean_doc_text(" ".join(self.capture_parts))
        attrs = dict(self.capture_attrs)
        self.capture_tag = ""
        self.capture_parts = []
        self.capture_depth = 0
        self.capture_attrs = {}
        if not as_block or not text:
            return
        chunk_type = "table" if tag in {"td", "th"} else "list_item" if tag == "li" else "paragraph"
        if tag == "cite":
            chunk_type = "reference"
            title = attrs.get("title") or text
            token = attrs.get("token") or attrs.get("doc-id") or ""
            text = f"引用文档：{title}" + (f"（token: {token}）" if token else "")
        self.blocks.append(self._build_block(chunk_type=chunk_type, text=text))

    def _finish_heading(self) -> None:
        if not self.heading_level:
            return
        heading = clean_doc_text(" ".join(self.heading_parts))
        level = self.heading_level
        self.heading_level = 0
        self.heading_parts = []
        if not heading:
            return
        self.heading_stack = [(item_level, item_text) for item_level, item_text in self.heading_stack if item_level < level]
        self.heading_stack.append((level, heading))
        self.blocks.append(self._build_block(chunk_type="heading", text=heading, heading=heading, heading_level=level))

    def _append_media_block(self, attrs: dict[str, str]) -> None:
        name = attrs.get("name") or attrs.get("alt") or "图片"
        src = attrs.get("src") or ""
        text = f"图片：{name}" + (f"（src: {src}）" if src else "")
        self.blocks.append(self._build_block(chunk_type="image", text=text))

    def _build_block(
        self,
        chunk_type: str,
        text: str,
        heading: str = "",
        heading_level: int = 0,
    ) -> dict[str, Any]:
        toc_path = [item_text for _, item_text in self.heading_stack]
        current_heading = heading or (toc_path[-1] if toc_path else self.title)
        return {
            "chunk_type": chunk_type,
            "text": text,
            "metadata": {
                "heading": current_heading,
                "heading_level": heading_level,
                "toc_path": toc_path or ([self.title] if self.title else []),
                "positions": {
                    "heading": current_heading,
                    "heading_level": heading_level,
                    "block_type": chunk_type,
                },
            },
        }


def parse_feishu_doc_blocks(text: str) -> list[dict[str, Any]]:
    """解析飞书 XML/HTML-like 文档，返回结构块。"""

    parser = FeishuDocBlockParser()
    parser.feed(text)
    parser.close()
    return parser.blocks


def merge_doc_blocks_into_chunks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把飞书结构块合并成适合检索的子 chunk。"""

    chunks: list[dict[str, Any]] = []
    buffer: list[dict[str, Any]] = []
    buffer_tokens = 0
    current_group = ""

    def flush_buffer() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        text = "\n".join(str(item.get("text") or "").strip() for item in buffer if str(item.get("text") or "").strip())
        if not text:
            buffer = []
            buffer_tokens = 0
            return
        first_meta = dict(buffer[0].get("metadata") or {})
        last_meta = dict(buffer[-1].get("metadata") or {})
        block_types = [str(item.get("chunk_type") or "paragraph") for item in buffer]
        toc_path = list(last_meta.get("toc_path") or first_meta.get("toc_path") or [])
        heading = str(last_meta.get("heading") or first_meta.get("heading") or "")
        chunks.append(
            {
                "chunk_type": "section" if len(buffer) > 1 else block_types[0],
                "text": text,
                "metadata": {
                    "heading": heading,
                    "toc_path": toc_path,
                    "block_types": block_types,
                    "positions": {
                        "heading": heading,
                        "toc_path": toc_path,
                        "block_types": block_types,
                        "block_count": len(buffer),
                    },
                },
            }
        )
        buffer = []
        buffer_tokens = 0

    def buffer_only_contains_headings() -> bool:
        return bool(buffer) and all(str(item.get("chunk_type") or "") == "heading" for item in buffer)

    for block in blocks:
        block_text = str(block.get("text") or "").strip()
        if not block_text:
            continue
        metadata = dict(block.get("metadata") or {})
        toc_path = list(metadata.get("toc_path") or [])
        group_key = "/".join(toc_path) or str(metadata.get("heading") or "doc")
        block_tokens = estimate_text_tokens(block_text)
        if block.get("chunk_type") == "heading":
            if buffer and group_key != current_group and not buffer_only_contains_headings():
                flush_buffer()
            buffer.append(block)
            buffer_tokens += block_tokens
            current_group = group_key
            continue
        should_flush = bool(buffer) and (
            group_key != current_group
            or buffer_tokens + block_tokens > DOC_CHILD_CHUNK_MAX_TOKENS
            or (buffer_tokens >= DOC_CHILD_CHUNK_TARGET_TOKENS and block_tokens > 80)
        )
        if should_flush:
            flush_buffer()
        buffer.append(block)
        buffer_tokens += block_tokens
        current_group = group_key
    flush_buffer()
    return chunks


def clean_doc_text(text: str) -> str:
    """清洗飞书块文本，保留人可读内容而不是 XML 标签。"""

    clean = html.unescape(str(text or ""))
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


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
            "metadata": {"row_index": 0, "fields": split_sheet_fields(header), "positions": {"sheet": "default", "row_index": 0}},
        }
    ]
    for index, line in enumerate(lines[1:], start=1):
        chunks.append(
            {
                "chunk_type": "row",
                "text": f"{header}\n{line}",
                "source_locator": f"sheet:row:{index}",
                "metadata": {
                    "row_index": index,
                    "header": header,
                    "fields": split_sheet_fields(header),
                    "positions": {"sheet": "default", "row_index": index},
                },
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
                "metadata": {
                    "section": current_section,
                    "positions": build_minute_positions(current_section),
                },
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
        "chunk_order": chunk.chunk_order,
        "parent_chunk_id": chunk.parent_chunk_id,
        "doc_type": chunk.doc_type,
        "content_tokens": chunk.content_tokens,
        "chunk_type": chunk.chunk_type,
        "checksum": chunk.checksum,
        "embedding_provider": str(document.metadata.get("embedding_provider") or ""),
        "embedding_model": str(document.metadata.get("embedding_model") or ""),
        "embedding_dimensions": int(document.metadata.get("embedding_dimensions") or 0),
        "embedding_fingerprint": str(document.metadata.get("embedding_fingerprint") or ""),
        "knowledge_namespace": str(document.metadata.get("knowledge_namespace") or ""),
        "metadata_json": json.dumps({**document.metadata, **chunk.metadata}, ensure_ascii=False),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def ensure_knowledge_chunk_schema(conn: sqlite3.Connection) -> None:
    """为旧版 SQLite 知识库补齐 T3.12 新增 chunk 字段。"""

    migrations = {
        "chunk_order": "ALTER TABLE knowledge_chunks ADD COLUMN chunk_order INTEGER NOT NULL DEFAULT 0",
        "parent_chunk_id": "ALTER TABLE knowledge_chunks ADD COLUMN parent_chunk_id TEXT NOT NULL DEFAULT ''",
        "doc_type": "ALTER TABLE knowledge_chunks ADD COLUMN doc_type TEXT NOT NULL DEFAULT ''",
        "content_tokens": "ALTER TABLE knowledge_chunks ADD COLUMN content_tokens INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in migrations.items():
        existing_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(knowledge_chunks)").fetchall()
        }
        if column not in existing_columns:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as error:
                # 兼容旧库在上次迁移中部分成功、部分失败的情况，保证初始化可重复执行。
                if "duplicate column name" not in str(error).lower():
                    raise


def build_chunk_metadata(
    base_metadata: dict[str, Any],
    item_metadata: dict[str, Any],
    source_type: str,
    source_locator: str,
    text: str,
    chunk_order: int,
) -> dict[str, Any]:
    """补齐 chunk 的结构化位置、关键词和问题字段，便于解释和回链。"""

    metadata = {**base_metadata, **item_metadata}
    positions = dict(metadata.get("positions") or {})
    positions.setdefault("source_type", source_type)
    positions.setdefault("source_locator", source_locator)
    positions.setdefault("chunk_order", chunk_order)
    metadata["positions"] = positions
    metadata["toc_path"] = build_toc_path(metadata, source_type)
    metadata.setdefault("keywords", extract_chunk_keywords(text, metadata))
    metadata.setdefault("questions", extract_chunk_questions(text))
    metadata.setdefault("doc_type", source_type)
    return metadata


def build_toc_path(metadata: dict[str, Any], source_type: str) -> list[str]:
    """从标题、章节或表格位置生成轻量 TOC 路径。"""

    existing_toc_path = metadata.get("toc_path")
    if isinstance(existing_toc_path, list) and existing_toc_path:
        return unique_strings([str(item) for item in existing_toc_path if str(item).strip()])
    if source_type == "sheet":
        positions = dict(metadata.get("positions") or {})
        return unique_strings(["sheet", str(positions.get("sheet") or "default")])
    if source_type == "minute":
        section = str(metadata.get("section") or "")
        return unique_strings(["minute", section])
    heading = str(metadata.get("heading") or "")
    return unique_strings(["doc", heading])


def attach_parent_chunks(document_id: str, source_type: str, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
    """按 TOC 路径聚合同章节子 chunk，并创建用于展开上下文的 parent chunk。"""

    if not chunks:
        return []
    grouped: dict[str, list[KnowledgeChunk]] = {}
    for chunk in chunks:
        group_key = build_parent_group_key(chunk)
        grouped.setdefault(group_key, []).append(chunk)

    parent_chunks: list[KnowledgeChunk] = []
    for group_index, (group_key, group_chunks) in enumerate(grouped.items(), start=1):
        if len(group_chunks) == 1:
            # 单个子 chunk 已经包含完整章节内容，不额外复制一份 parent_section。
            # 只有同一章节被拆成多个子 chunk 时，才创建父级上下文用于 fetch 展开。
            continue
        parent_text = "\n\n".join(item.text for item in group_chunks if item.text)
        parent_checksum = sha256_text(parent_text)
        parent_chunk_id = stable_parent_chunk_id(document_id, group_key, parent_checksum)
        toc_path = list(group_chunks[0].metadata.get("toc_path") or [])
        first_order = min(item.chunk_order for item in group_chunks)
        for child in group_chunks:
            child.parent_chunk_id = parent_chunk_id
            child.metadata["parent_chunk_id"] = parent_chunk_id
            child.metadata.setdefault("toc_path", toc_path)
        parent_chunks.append(
            KnowledgeChunk(
                chunk_id=parent_chunk_id,
                document_id=document_id,
                chunk_type="parent_section",
                text=parent_text,
                source_locator=str(group_chunks[0].source_locator or ""),
                chunk_order=max(first_order - 1, 0),
                parent_chunk_id="",
                doc_type=source_type,
                content_tokens=estimate_text_tokens(parent_text),
                metadata={
                    "doc_type": source_type,
                    "toc_path": toc_path,
                    "positions": {
                        "source_type": source_type,
                        "source_locator": str(group_chunks[0].source_locator or ""),
                        "chunk_order": max(first_order - 1, 0),
                        "parent_group": group_key,
                    },
                    "child_chunk_ids": [item.chunk_id for item in group_chunks],
                    "keywords": extract_chunk_keywords(parent_text, {"toc_path": " ".join(toc_path)}),
                    "questions": extract_chunk_questions(parent_text),
                },
                checksum=parent_checksum,
            )
        )

    return sorted([*parent_chunks, *chunks], key=lambda item: (item.chunk_order, item.chunk_type, item.chunk_id))


def build_parent_group_key(chunk: KnowledgeChunk) -> str:
    """按文档结构确定 parent chunk 边界。"""

    toc_path = [item for item in list(chunk.metadata.get("toc_path") or []) if item]
    if toc_path:
        return "/".join(toc_path)
    positions = dict(chunk.metadata.get("positions") or {})
    return str(
        positions.get("heading")
        or positions.get("section")
        or positions.get("sheet")
        or chunk.doc_type
        or "root"
    )


def extract_chunk_keywords(text: str, metadata: dict[str, Any]) -> list[str]:
    """从 chunk 文本和标题元数据中提取轻量关键词，服务关键词召回和审计。"""

    values = [
        str(metadata.get("title") or ""),
        str(metadata.get("heading") or ""),
        str(metadata.get("section") or ""),
        text,
    ]
    raw_terms: list[str] = []
    for value in values:
        raw_terms.extend(re.split(r"[\s,，;；:：|/()（）\[\]【】]+", value))
    keywords: list[str] = []
    for term in raw_terms:
        clean = term.strip("#：:,.。").lower()
        if len(clean) <= 1 or clean in {"the", "and", "for", "with", "会议", "同步", "讨论"}:
            continue
        keywords.append(clean)
    return unique_strings(keywords)[:12]


def extract_chunk_questions(text: str) -> list[str]:
    """提取 chunk 中显式的问题句，供后续 query 改写和会前问题识别使用。"""

    questions: list[str] = []
    for sentence in re.split(r"(?<=[?？])\s*|[\n。；;]+", text):
        clean = sentence.strip()
        if not clean:
            continue
        if clean.endswith(("?", "？")) or any(marker in clean for marker in ("是否", "如何", "为什么", "待确认", "问题")):
            questions.append(clean[:120])
    return unique_strings(questions)[:5]


def split_sheet_fields(header: str) -> list[str]:
    """从表头行中提取字段名，兼容 CSV 和 Markdown 表格。"""

    separator = "|" if "|" in header else ","
    return [item.strip() for item in header.strip("|").split(separator) if item.strip()]


def build_minute_positions(section: str) -> dict[str, Any]:
    """从妙记章节标题中提取时间片段等结构化位置。"""

    positions: dict[str, Any] = {"section": section}
    match = re.search(r"\[?(\d{1,2}:\d{2}(?::\d{2})?)", section or "")
    if match:
        positions["timestamp"] = match.group(1)
    return positions


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


def build_reranker_settings_from_env() -> RerankerSettings:
    """从环境变量构造 reranker 配置，默认关闭以避免开发阶段额外成本。"""

    return RerankerSettings(
        enabled=os.getenv("MEETFLOW_RERANKER_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        provider=os.getenv("MEETFLOW_RERANKER_PROVIDER", "local-rule"),
        model=os.getenv("MEETFLOW_RERANKER_MODEL", ""),
        top_k=int(os.getenv("MEETFLOW_RERANKER_TOP_K", str(DEFAULT_RERANKER_TOP_K))),
        timeout_seconds=int(os.getenv("MEETFLOW_RERANKER_TIMEOUT_SECONDS", "30")),
    )


def build_knowledge_search_settings_from_env() -> KnowledgeSearchSettings:
    """从环境变量构造知识检索融合配置。"""

    return KnowledgeSearchSettings(
        fusion_strategy=normalize_fusion_strategy(os.getenv("MEETFLOW_KNOWLEDGE_FUSION_STRATEGY", DEFAULT_FUSION_STRATEGY)),
        rrf_k=int(os.getenv("MEETFLOW_KNOWLEDGE_RRF_K", str(DEFAULT_RRF_K))),
    )


def build_embedding_fingerprint(settings: EmbeddingSettings) -> str:
    """生成 embedding 向量空间指纹，防止不同模型或维度混检。"""

    provider = settings.provider.strip().lower()
    model = settings.model.strip()
    dimensions = int(settings.dimensions or 0)
    return f"{provider}:{model}:{dimensions}"


def build_knowledge_namespace(settings: EmbeddingSettings) -> str:
    """生成知识索引命名空间，作为日志和检索解释中的人类可读标识。"""

    digest = hashlib.sha1(build_embedding_fingerprint(settings).encode("utf-8")).hexdigest()[:8]
    safe_provider = re.sub(r"[^a-zA-Z0-9]+", "_", settings.provider.strip().lower()).strip("_") or "unknown"
    safe_model = re.sub(r"[^a-zA-Z0-9]+", "_", settings.model.strip().lower()).strip("_") or "unknown"
    return f"{safe_provider}_{safe_model}_{settings.dimensions}_{digest}"


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


def normalize_fusion_strategy(value: str) -> str:
    """规范化混合检索融合策略，未知值回退到 RRF。"""

    strategy = str(value or "").strip().lower()
    if strategy in {"weighted", "rrf"}:
        return strategy
    return DEFAULT_FUSION_STRATEGY


def build_fts_match_query(query_terms: list[str], query: str) -> str:
    """把用户查询转成保守的 FTS5 MATCH 表达式。"""

    candidates = unique_strings([*query_terms, query])
    phrases: list[str] = []
    for item in candidates:
        clean = re.sub(r"\s+", " ", str(item or "").strip())
        clean = clean.replace('"', '""')
        if clean:
            phrases.append(f'"{clean}"')
    return " OR ".join(phrases[:12])


def bm25_rank_to_similarity(rank: int) -> float:
    """把 BM25 排名映射为 0-1 解释分，避免比较不同检索器原始分。"""

    safe_rank = max(1, int(rank or 1))
    return round(1.0 / (1.0 + ((safe_rank - 1) * 0.15)), 3)


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
    term_score = 0.0
    reasons: list[str] = []
    matched_terms: set[str] = set()
    for term in query_terms:
        if term in combined:
            term_score += 0.22 if term in text.lower() else 0.14
            matched_terms.add(term)
            reasons.append(f"命中查询词:{term}")
    if query and query.lower() in combined:
        term_score += 0.18
        reasons.append("命中完整查询")
    if query_terms:
        coverage = len(matched_terms) / max(len(query_terms), 1)
        term_similarity = round(min((term_score * 0.55) + (coverage * 0.45), 1.0), 3)
    else:
        term_similarity = 0.0
    metadata_score = 0.0
    if row["source_locator"]:
        metadata_score += 0.04
        reasons.append("包含回链定位")
    if row["source_url"]:
        metadata_score += 0.03
        reasons.append("包含来源链接")
    freshness = estimate_document_freshness(str(row["document_updated_at"] or ""), time_window=time_window)
    if freshness:
        reasons.append("资源更新时间符合窗口")

    snippet = build_snippet(text, query_terms)
    score = round(min(term_similarity + metadata_score + freshness, 0.99), 3)
    return KnowledgeSearchHit(
        ref_id=stable_evidence_ref_id(str(row["document_id"]), str(row["chunk_id"])),
        chunk_id=str(row["chunk_id"]),
        document_id=str(row["document_id"]),
        source_type=source_type,
        title=title,
        snippet=snippet,
        reason="；".join(unique_strings(reasons[:5])) or "知识片段候选",
        score=score,
        term_similarity=term_similarity,
        final_score=score,
        source_url=str(row["source_url"] or ""),
        source_locator=str(row["source_locator"] or ""),
        parent_chunk_id=str(row["parent_chunk_id"] or ""),
        toc_path=list(chunk_metadata.get("toc_path") or []),
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


def merge_hybrid_hits(
    vector_hits: list[KnowledgeSearchHit],
    keyword_hits: list[KnowledgeSearchHit],
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    freshness_weight: float = DEFAULT_FRESHNESS_WEIGHT,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    threshold_relaxed: bool = False,
) -> list[KnowledgeSearchHit]:
    """融合向量召回和关键词召回，并把最终分数拆开写回 evidence。"""

    merged: dict[str, KnowledgeSearchHit] = {}
    for hit in [*vector_hits, *keyword_hits]:
        existing = merged.get(hit.chunk_id)
        if existing is None:
            merged[hit.chunk_id] = hit
            continue
        existing.vector_similarity = max(existing.vector_similarity, hit.vector_similarity)
        existing.term_similarity = max(existing.term_similarity, hit.term_similarity)
        existing.reason = "；".join(unique_strings([existing.reason, hit.reason]))

    final_hits: list[KnowledgeSearchHit] = []
    for hit in merged.values():
        freshness = estimate_document_freshness(hit.updated_at)
        final_score = round(
            min(
                (hit.vector_similarity * vector_weight)
                + (hit.term_similarity * keyword_weight)
                + (freshness * freshness_weight),
                0.99,
            ),
            3,
        )
        hit.final_score = final_score
        hit.score = final_score
        if hit.vector_similarity > 0 and hit.term_similarity > 0:
            hit.reason = f"混合命中 final_score:{final_score:.3f}；{hit.reason}"
        elif hit.vector_similarity > 0:
            hit.reason = f"向量命中 final_score:{final_score:.3f}；{hit.reason}"
        else:
            hit.reason = f"关键词命中 final_score:{final_score:.3f}；{hit.reason}"
        if threshold_relaxed:
            hit.reason = f"显式资源过滤放宽阈值；{hit.reason}"
        elif final_score < similarity_threshold:
            continue
        final_hits.append(hit)

    final_hits.sort(key=lambda item: (item.final_score, item.updated_at, item.title), reverse=True)
    return final_hits


def merge_hybrid_hits_rrf(
    vector_hits: list[KnowledgeSearchHit],
    keyword_hits: list[KnowledgeSearchHit],
    rrf_k: int = DEFAULT_RRF_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    threshold_relaxed: bool = False,
) -> list[KnowledgeSearchHit]:
    """用 RRF 融合向量召回和 BM25 召回的排名。

    RRF 只依赖各检索器内部排名，不直接比较 vector similarity 与 BM25
    原始分数，更适合解释“语义召回 + 关键词召回”的混合检索。
    """

    merged: dict[str, KnowledgeSearchHit] = {}
    vector_rank_by_id: dict[str, int] = {}
    keyword_rank_by_id: dict[str, int] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        vector_rank_by_id[hit.chunk_id] = hit.vector_rank or rank
        merged.setdefault(hit.chunk_id, hit)
    for rank, hit in enumerate(keyword_hits, start=1):
        keyword_rank_by_id[hit.chunk_id] = hit.keyword_rank or rank
        existing = merged.get(hit.chunk_id)
        if existing is None:
            merged[hit.chunk_id] = hit
            continue
        existing.vector_similarity = max(existing.vector_similarity, hit.vector_similarity)
        existing.term_similarity = max(existing.term_similarity, hit.term_similarity)
        existing.bm25_score = hit.bm25_score or existing.bm25_score
        existing.reason = "；".join(unique_strings([existing.reason, hit.reason]))

    final_hits: list[KnowledgeSearchHit] = []
    safe_k = max(1, int(rrf_k or DEFAULT_RRF_K))
    max_rrf = (1.0 / (safe_k + 1)) * 2
    for chunk_id, hit in merged.items():
        vector_rank = vector_rank_by_id.get(chunk_id, 0)
        keyword_rank = keyword_rank_by_id.get(chunk_id, 0)
        rrf_score = 0.0
        if vector_rank:
            rrf_score += 1.0 / (safe_k + vector_rank)
        if keyword_rank:
            rrf_score += 1.0 / (safe_k + keyword_rank)
        normalized_score = round(min(rrf_score / max_rrf, 0.99), 3) if max_rrf else 0.0
        hit.vector_rank = vector_rank
        hit.keyword_rank = keyword_rank
        hit.rrf_score = round(rrf_score, 6)
        hit.final_score = normalized_score
        hit.score = normalized_score
        rank_reason = f"RRF融合 rrf_score:{hit.rrf_score:.6f} vector_rank:{vector_rank or '-'} keyword_rank:{keyword_rank or '-'}"
        if threshold_relaxed:
            hit.reason = f"显式资源过滤放宽阈值；{rank_reason}；{hit.reason}"
        else:
            hit.reason = f"{rank_reason}；{hit.reason}"
        if not threshold_relaxed and normalized_score < similarity_threshold:
            continue
        final_hits.append(hit)

    final_hits.sort(key=lambda item: (item.final_score, item.rrf_score, item.updated_at, item.title), reverse=True)
    return final_hits


def apply_optional_reranker(
    query: str,
    query_terms: list[str],
    hits: list[KnowledgeSearchHit],
    enabled: bool,
    provider: str,
    model: str,
    top_k: int,
    reranker_weight: float,
) -> dict[str, Any]:
    """在混合检索之后执行可选重排，默认使用本地轻量规则 provider。"""

    if not enabled or not hits:
        return {"enabled": False, "provider": provider or "disabled", "reranked_count": 0, "hits": hits}
    provider_name = (provider or "local-rule").strip().lower()
    candidate_limit = max(1, min(int(top_k or DEFAULT_RERANKER_TOP_K), 64))
    candidates = hits[:candidate_limit]
    remaining = hits[candidate_limit:]
    if provider_name not in {"local-rule", "local", "rule", "disabled"}:
        raise RuntimeError(f"暂不支持的 reranker provider：{provider}")
    reranked = rerank_hits_locally(
        query=query,
        query_terms=query_terms,
        hits=candidates,
        provider=provider_name,
        model=model,
        reranker_weight=reranker_weight,
    )
    return {
        "enabled": True,
        "provider": provider_name,
        "reranked_count": len(reranked),
        "hits": [*reranked, *remaining],
    }


def rerank_hits_locally(
    query: str,
    query_terms: list[str],
    hits: list[KnowledgeSearchHit],
    provider: str,
    model: str,
    reranker_weight: float,
) -> list[KnowledgeSearchHit]:
    """本地轻量 reranker，用 query 覆盖率、标题命中和问题命中微调排序。"""

    for hit in hits:
        rerank_score = calculate_local_rerank_score(query=query, query_terms=query_terms, hit=hit)
        base_score = hit.final_score or hit.score
        hit.rerank_score = rerank_score
        hit.final_score = round(min((base_score * (1.0 - reranker_weight)) + (rerank_score * reranker_weight), 0.99), 3)
        hit.score = hit.final_score
        provider_label = provider if not model else f"{provider}:{model}"
        hit.reason = f"reranker:{provider_label} score:{rerank_score:.3f}；{hit.reason}"
    hits.sort(key=lambda item: (item.final_score, item.rerank_score, item.updated_at), reverse=True)
    return hits


def calculate_local_rerank_score(query: str, query_terms: list[str], hit: KnowledgeSearchHit) -> float:
    """计算本地重排分，强调 query 与标题、snippet、TOC 和问题字段的贴合度。"""

    metadata = dict(hit.metadata)
    combined = " ".join(
        [
            hit.title,
            hit.snippet,
            " ".join(hit.toc_path),
            " ".join(str(item) for item in metadata.get("keywords") or []),
            " ".join(str(item) for item in metadata.get("questions") or []),
        ]
    ).lower()
    matched_terms = [term for term in query_terms if term and term in combined]
    coverage = len(set(matched_terms)) / max(len(query_terms), 1) if query_terms else 0.0
    title_bonus = 0.15 if any(term in hit.title.lower() for term in query_terms) else 0.0
    question_bonus = 0.10 if metadata.get("questions") and any(term in " ".join(metadata.get("questions") or []) for term in query_terms) else 0.0
    exact_bonus = 0.12 if query and query.lower() in combined else 0.0
    return round(min((coverage * 0.63) + title_bonus + question_bonus + exact_bonus, 1.0), 3)


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
            vector_similarity=hit.vector_similarity,
            term_similarity=hit.term_similarity,
            bm25_score=hit.bm25_score,
            vector_rank=hit.vector_rank,
            keyword_rank=hit.keyword_rank,
            rrf_score=hit.rrf_score,
            rerank_score=hit.rerank_score,
            final_score=hit.final_score,
            source_url=hit.source_url,
            source_locator=hit.source_locator,
            parent_chunk_id=hit.parent_chunk_id,
            toc_path=hit.toc_path,
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


def clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    """把工具参数里的浮点数收敛到安全范围。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def build_search_metadata_filter(
    project_id: str = "",
    meeting_id: str = "",
    document_id: str = "",
    source_url: str = "",
    owner_id: str = "",
    updated_after: str = "",
    permission_scope: str = "",
) -> dict[str, str]:
    """整理检索 metadata filter，空值不参与过滤。"""

    return {
        key: value
        for key, value in {
            "project_id": project_id,
            "meeting_id": meeting_id,
            "document_id": document_id,
            "source_url": source_url,
            "owner_id": owner_id,
            "updated_after": updated_after,
            "permission_scope": permission_scope,
        }.items()
        if str(value or "").strip()
    }


def row_matches_metadata_filter(row: sqlite3.Row, metadata_filter: dict[str, str]) -> bool:
    """判断 SQLite chunk 行是否满足结构化 metadata filter。"""

    if not metadata_filter:
        return True
    chunk_metadata = json.loads(row["chunk_metadata_json"] or "{}")
    document_metadata = json.loads(row["document_metadata_json"] or "{}")
    metadata = {**document_metadata, **chunk_metadata}
    document_id = str(row["document_id"] or "")
    source_url = str(row["source_url"] or "")
    owner_id = str(row["owner_id"] or metadata.get("owner_id") or metadata.get("owner") or "")
    permission_scope = str(row["permission_scope"] or metadata.get("permission_scope") or "")

    if metadata_filter.get("document_id") and metadata_filter["document_id"] != document_id:
        return False
    if metadata_filter.get("source_url") and metadata_filter["source_url"] not in source_url:
        return False
    if metadata_filter.get("owner_id") and metadata_filter["owner_id"] != owner_id:
        return False
    if metadata_filter.get("permission_scope") and metadata_filter["permission_scope"] != permission_scope:
        return False
    if metadata_filter.get("updated_after"):
        updated_at = str(row["document_updated_at"] or "")
        if parse_date_like_timestamp(updated_at) < parse_date_like_timestamp(metadata_filter["updated_after"]):
            return False
    for key in ("project_id", "meeting_id"):
        expected = metadata_filter.get(key)
        if expected and str(metadata.get(key) or "") != expected:
            return False
    return True


def row_matches_embedding_namespace(row: sqlite3.Row, current_fingerprint: str) -> bool:
    """判断 chunk 所属文档是否属于当前 embedding 向量空间。"""

    document_metadata = json.loads(row["document_metadata_json"] or "{}")
    chunk_metadata = json.loads(row["chunk_metadata_json"] or "{}")
    document_fingerprint = str(document_metadata.get("embedding_fingerprint") or "")
    chunk_fingerprint = str(chunk_metadata.get("embedding_fingerprint") or "")
    return bool(document_fingerprint) and document_fingerprint == current_fingerprint and (
        not chunk_fingerprint or chunk_fingerprint == current_fingerprint
    )


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
                "top_k": {"type": "integer", "description": "候选召回数量，默认 20，最大 50。"},
                "top_n": {"type": "integer", "description": "最终进入 evidence pack 的片段数，默认等于 top_k，最大 10。"},
                "similarity_threshold": {
                    "type": "number",
                    "description": "最终分数阈值，低于阈值的结果不会进入高置信证据包。",
                },
                "vector_weight": {"type": "number", "description": "向量相似度权重，默认 0.65。"},
                "keyword_weight": {"type": "number", "description": "关键词相似度权重，默认 0.30。"},
                "fusion_strategy": {"type": "string", "description": "混合检索融合策略：rrf 或 weighted，默认 rrf。"},
                "rrf_k": {"type": "integer", "description": "RRF 排名融合常数，默认 60。"},
                "reranker_enabled": {"type": "boolean", "description": "是否开启可选 reranker 重排。"},
                "reranker_provider": {"type": "string", "description": "reranker provider，当前支持 local-rule。"},
                "reranker_model": {"type": "string", "description": "reranker 模型名，local-rule 可为空。"},
                "reranker_top_k": {"type": "integer", "description": "送入 reranker 的候选数量，默认 32，最大 64。"},
                "reranker_weight": {"type": "number", "description": "rerank_score 融入 final_score 的权重，默认 0.25。"},
                "filter_project_id": {"type": "string", "description": "可选 metadata project_id 精确过滤。"},
                "filter_meeting_id": {"type": "string", "description": "可选 metadata meeting_id 精确过滤。"},
                "document_id": {"type": "string", "description": "可选文档 ID 精确过滤。"},
                "source_url": {"type": "string", "description": "可选来源 URL 过滤，支持包含匹配。"},
                "owner_id": {"type": "string", "description": "可选 owner_id 过滤。"},
                "updated_after": {"type": "string", "description": "可选更新时间下限，如 2026-04-01。"},
                "permission_scope": {"type": "string", "description": "可选权限范围过滤。"},
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
            top_k=int(arguments.get("top_k") or 20),
            top_n=int(arguments.get("top_n") or 0),
            similarity_threshold=float(arguments.get("similarity_threshold") or DEFAULT_SIMILARITY_THRESHOLD),
            vector_weight=float(arguments.get("vector_weight") or DEFAULT_VECTOR_WEIGHT),
            keyword_weight=float(arguments.get("keyword_weight") or DEFAULT_KEYWORD_WEIGHT),
            fusion_strategy=str(arguments.get("fusion_strategy") or ""),
            rrf_k=int(arguments.get("rrf_k") or 0),
            reranker_enabled=arguments.get("reranker_enabled") if "reranker_enabled" in arguments else None,
            reranker_provider=str(arguments.get("reranker_provider") or ""),
            reranker_model=str(arguments.get("reranker_model") or ""),
            reranker_top_k=int(arguments.get("reranker_top_k") or 0),
            reranker_weight=float(arguments.get("reranker_weight") or DEFAULT_RERANKER_WEIGHT),
            filter_project_id=str(arguments.get("filter_project_id") or ""),
            filter_meeting_id=str(arguments.get("filter_meeting_id") or ""),
            document_id=str(arguments.get("document_id") or ""),
            source_url=str(arguments.get("source_url") or ""),
            owner_id=str(arguments.get("owner_id") or ""),
            updated_after=str(arguments.get("updated_after") or ""),
            permission_scope=str(arguments.get("permission_scope") or ""),
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


def stable_parent_chunk_id(document_id: str, group_key: str, checksum: str) -> str:
    """生成章节级 parent chunk 的稳定 ID。"""

    digest = hashlib.sha1(f"{document_id}:parent:{group_key}:{checksum}".encode("utf-8")).hexdigest()[:12]
    return f"{document_id}#parent_{digest}"


def stable_index_job_id(resource_id: str, resource_type: str, reason: str, source_url: str = "") -> str:
    """生成稳定索引任务 ID，让同一资源同类刷新任务可幂等覆盖。"""

    digest = hashlib.sha1(f"{resource_type}:{resource_id}:{reason}:{source_url}".encode("utf-8")).hexdigest()[:12]
    return f"index_job_{digest}"


def index_job_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """把 index_jobs SQLite 行转换成普通字典。"""

    data = dict(row)
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    return data


def sha256_text(text: str) -> str:
    """计算文本 checksum。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
