from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config.loader import EmbeddingSettings, KnowledgeSearchSettings, LLMSettings, RerankerSettings, StorageSettings
from core.llm import LLMConfigError, LLMResponse
from core.knowledge import KnowledgeIndexStore
from core.message_dialogue import (
    build_rag_summary_reply,
    classify_summary_intent,
    handle_message_dialogue_event,
    is_message_receive_event,
    parse_message_dialogue_request,
)
from core.models import Resource
from core.policy import AgentPolicy
from core.storage import MeetFlowStorage


class DummyVectorIndex:
    """测试里关闭真实向量库，聚焦 HTTP 消息入口和 SQLite 检索。"""

    def upsert_document(self, document, chunks):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": True, "count": len(chunks)}

    def search(self, query, query_terms, resource_types, top_k):  # noqa: ANN001 - 测试桩保持接口兼容。
        return {"ok": True, "chunk_ids": [], "distances": [], "total_candidates": 0}


class DummyFeishuClient:
    """记录文本消息发送，避免单测触达真实飞书。"""

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    def send_text_message(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
        idempotency_key: str = "",
        identity: str = "tenant",
    ) -> dict[str, str]:
        self.sent_messages.append(
            {
                "receive_id": receive_id,
                "text": text,
                "receive_id_type": receive_id_type,
                "idempotency_key": idempotency_key,
                "identity": identity,
            }
        )
        return {"message_id": "om_reply"}


class DummyPolishProvider:
    """测试用 LLM Provider，返回可预测的润色总结。"""

    def chat(self, messages, tools=None, settings=None):  # noqa: ANN001 - 测试桩保持 Provider 接口兼容。
        return LLMResponse(
            content="结论：D7 评测已经覆盖核心 RAG 指标。\n要点：\n- Hit@3 已达到 1.0。\n- 评测关注证据覆盖和安全策略。\n待确认：继续补充真实群聊样本。",
            finish_reason="stop",
            model="dummy-polish-model",
        )


class FailingPolishProvider:
    """测试用失败 Provider，用来验证 fallback。"""

    def chat(self, messages, tools=None, settings=None):  # noqa: ANN001 - 测试桩保持 Provider 接口兼容。
        raise LLMConfigError("LLM 测试失败")


class MessageDialogueTest(unittest.TestCase):
    """覆盖群 @ 机器人后只允许 RAG 总结的主动对话入口。"""

    def test_parse_message_request_strips_mentions(self) -> None:
        payload = build_message_payload(text="@_user_1 总结 D7 RAG 评测")

        self.assertTrue(is_message_receive_event(payload))
        request = parse_message_dialogue_request(payload)

        self.assertEqual(request.chat_id, "oc_group")
        self.assertEqual(request.sender_open_id, "ou_sender")
        self.assertEqual(request.text, "总结 D7 RAG 评测")

    def test_intent_gate_rejects_non_summary_actions(self) -> None:
        allowed = classify_summary_intent("总结 D7 RAG 评测")
        blocked = classify_summary_intent("总结 D7 并创建任务")
        question = classify_summary_intent("今天有哪些会议？")
        greeting = classify_summary_intent("你好")

        self.assertEqual(allowed["status"], "allowed")
        self.assertEqual(allowed["topic"], "D7 RAG 评测")
        self.assertEqual(blocked["status"], "rejected")
        self.assertEqual(question["status"], "rejected")
        self.assertEqual(greeting["status"], "rejected")

    def test_handle_message_event_summarizes_rag_and_sends_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings, storage = build_settings_and_storage(tmp_dir)
            knowledge_store = build_knowledge_store(settings.storage)
            knowledge_store.index_resource(
                Resource(
                    resource_id="doc_d7",
                    resource_type="doc",
                    title="D7 RAG 效果评测记录",
                    content=(
                        "D7 RAG 评测覆盖 40 条业务样本，Hit@3 达到 1.0。"
                        "评测强调证据覆盖、工具轨迹和安全策略，非 RAG 基线得分明显更低。"
                    ),
                    source_url="https://example.feishu.cn/docx/d7",
                    updated_at="2026-05-13T10:00:00",
                ),
                force=True,
            )
            client = DummyFeishuClient()
            payload = build_message_payload(text="@_user_1 总结 D7 RAG 评测")

            with patch("core.message_dialogue.KnowledgeIndexStore", return_value=knowledge_store):
                result = handle_message_dialogue_event(
                    payload=payload,
                    settings=settings,  # type: ignore[arg-type]
                    storage=storage,
                    feishu_client=client,
                    policy=AgentPolicy(),
                    allow_write=True,
                )

            self.assertEqual(result.status, "answered")
            self.assertTrue(result.sent)
            self.assertEqual(result.topic, "D7 RAG 评测")
            self.assertEqual(client.sent_messages[0]["receive_id"], "oc_group")
            self.assertIn("MeetFlow RAG 总结：D7 RAG 评测", client.sent_messages[0]["text"])
            self.assertIn("D7 RAG 效果评测记录", client.sent_messages[0]["text"])

    def test_handle_message_event_rejects_side_effect_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings, storage = build_settings_and_storage(tmp_dir)
            client = DummyFeishuClient()
            payload = build_message_payload(text="@_user_1 总结 D7 并创建任务")

            result = handle_message_dialogue_event(
                payload=payload,
                settings=settings,  # type: ignore[arg-type]
                storage=storage,
                feishu_client=client,
                policy=AgentPolicy(),
                allow_write=True,
            )

            self.assertEqual(result.status, "rejected")
            self.assertTrue(result.sent)
            self.assertIn("只支持“基于 RAG 总结主题”", client.sent_messages[0]["text"])

    def test_reply_is_blocked_without_allow_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings, storage = build_settings_and_storage(tmp_dir)
            knowledge_store = build_knowledge_store(settings.storage)
            knowledge_store.index_resource(
                Resource(
                    resource_id="doc_d7",
                    resource_type="doc",
                    title="D7 RAG 效果评测记录",
                    content="D7 RAG 评测覆盖 Hit@3、MRR 和证据覆盖。",
                    source_url="https://example.feishu.cn/docx/d7",
                ),
                force=True,
            )
            client = DummyFeishuClient()
            payload = build_message_payload(text="@_user_1 总结 D7 RAG 评测")

            with patch("core.message_dialogue.KnowledgeIndexStore", return_value=knowledge_store):
                result = handle_message_dialogue_event(
                    payload=payload,
                    settings=settings,  # type: ignore[arg-type]
                    storage=storage,
                    feishu_client=client,
                    policy=AgentPolicy(),
                    allow_write=False,
                )

            self.assertEqual(result.status, "send_blocked")
            self.assertFalse(result.sent)
            self.assertEqual(client.sent_messages, [])

    def test_summary_reply_filters_headings_and_dedupes_evidence(self) -> None:
        reply = build_rag_summary_reply(
            topic="M3 会前知识卡片",
            search_result={
                "low_confidence": False,
                "hits": [
                    {
                        "title": "MeetFlow M3 会前知识卡片方案",
                        "source_type": "doc",
                        "source_url": "https://example.feishu.cn/docx/workflow_demo_m3_rag",
                        "ref_id": "ref_1",
                        "snippet": "上次结论。当前问题。风险。如果只依赖日程附件，可能漏掉近期更新的妙记和任务。",
                    },
                    {
                        "title": "MeetFlow M3 会前知识卡片方案",
                        "source_type": "doc",
                        "source_url": "https://example.feishu.cn/docx/workflow_demo_m3_rag",
                        "ref_id": "ref_2",
                        "snippet": "M3 会前卡片需要优先使用轻量 RAG 检索知识 chunk，并保留来源链接。",
                    },
                ],
            },
        )

        self.assertNotIn("- 上次结论", reply)
        self.assertNotIn("- 当前问题", reply)
        self.assertNotIn("- 风险", reply)
        self.assertIn("- 如果只依赖日程附件，可能漏掉近期更新的妙记和任务。", reply)
        self.assertIn("- M3 会前卡片需要优先使用轻量 RAG 检索知识 chunk，并保留来源链接。", reply)
        self.assertEqual(reply.count("MeetFlow M3 会前知识卡片方案"), 1)
        self.assertIn("命中 2 个片段", reply)

    def test_handle_message_event_uses_llm_polish_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings, storage = build_settings_and_storage(tmp_dir)
            settings.llm = LLMSettings(
                provider="openai-compatible",
                model="dummy-polish-model",
                api_base="https://example.invalid/v1",
                api_key="test-key",
                temperature=0.2,
                max_tokens=4000,
                reasoning_effort="",
            )
            knowledge_store = build_knowledge_store(settings.storage)
            knowledge_store.index_resource(
                Resource(
                    resource_id="doc_d7",
                    resource_type="doc",
                    title="D7 RAG 效果评测记录",
                    content=(
                        "D7 RAG 评测覆盖 40 条业务样本，Hit@3 达到 1.0。"
                        "评测强调证据覆盖、工具轨迹和安全策略。"
                    ),
                    source_url="https://example.feishu.cn/docx/d7",
                ),
                force=True,
            )
            client = DummyFeishuClient()
            payload = build_message_payload(text="@_user_1 总结 D7 RAG 评测")

            with (
                patch("core.message_dialogue.KnowledgeIndexStore", return_value=knowledge_store),
                patch("core.message_dialogue.create_llm_provider", return_value=DummyPolishProvider()) as provider_mock,
            ):
                result = handle_message_dialogue_event(
                    payload=payload,
                    settings=settings,  # type: ignore[arg-type]
                    storage=storage,
                    feishu_client=client,
                    policy=AgentPolicy(),
                    allow_write=True,
                )

            self.assertEqual(result.status, "answered")
            provider_mock.assert_called_once()
            self.assertEqual(result.payload["llm_polish"]["status"], "success")
            sent_text = client.sent_messages[0]["text"]
            self.assertIn("结论：D7 评测已经覆盖核心 RAG 指标。", sent_text)
            self.assertIn("证据：", sent_text)
            self.assertIn("正文由 LLM 在证据范围内润色", sent_text)

    def test_llm_polish_failure_falls_back_to_extract_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings, storage = build_settings_and_storage(tmp_dir)
            settings.llm = LLMSettings(
                provider="openai-compatible",
                model="dummy-polish-model",
                api_base="https://example.invalid/v1",
                api_key="test-key",
                temperature=0.2,
                max_tokens=4000,
                reasoning_effort="",
            )
            knowledge_store = build_knowledge_store(settings.storage)
            knowledge_store.index_resource(
                Resource(
                    resource_id="doc_d7",
                    resource_type="doc",
                    title="D7 RAG 效果评测记录",
                    content="D7 RAG 评测覆盖 Hit@3、MRR 和证据覆盖。",
                    source_url="https://example.feishu.cn/docx/d7",
                ),
                force=True,
            )
            client = DummyFeishuClient()
            payload = build_message_payload(text="@_user_1 总结 D7 RAG 评测")

            with (
                patch("core.message_dialogue.KnowledgeIndexStore", return_value=knowledge_store),
                patch("core.message_dialogue.create_llm_provider", return_value=FailingPolishProvider()),
            ):
                result = handle_message_dialogue_event(
                    payload=payload,
                    settings=settings,  # type: ignore[arg-type]
                    storage=storage,
                    feishu_client=client,
                    policy=AgentPolicy(),
                    allow_write=True,
                )

            self.assertEqual(result.status, "answered")
            self.assertEqual(result.payload["llm_polish"]["status"], "fallback")
            sent_text = client.sent_messages[0]["text"]
            self.assertIn("要点：", sent_text)
            self.assertIn("D7 RAG 评测覆盖 Hit@3、MRR 和证据覆盖。", sent_text)
            self.assertNotIn("正文由 LLM 在证据范围内润色", sent_text)


def build_settings_and_storage(tmp_dir: str) -> tuple[SimpleNamespace, MeetFlowStorage]:
    storage_settings = StorageSettings(
        db_path=str(Path(tmp_dir) / "meetflow.sqlite"),
        project_memory_dir=str(Path(tmp_dir) / "projects"),
        audit_log_path=str(Path(tmp_dir) / "audit.jsonl"),
    )
    settings = SimpleNamespace(
        storage=storage_settings,
        feishu=SimpleNamespace(default_chat_id="oc_default"),
        llm=LLMSettings(
            provider="dry-run",
            model="dry-run-model",
            api_base="",
            api_key="",
            temperature=0.2,
            max_tokens=4000,
            reasoning_effort="",
        ),
        embedding=EmbeddingSettings(
            provider="sentence-transformers",
            model="dummy-model",
            api_base="",
            api_key="",
            dimensions=8,
            timeout_seconds=5,
        ),
        reranker=RerankerSettings(
            enabled=False,
            provider="disabled",
            model="",
            top_k=8,
            timeout_seconds=5,
        ),
        knowledge_search=KnowledgeSearchSettings(
            fusion_strategy="rrf",
            rrf_k=60,
        ),
    )
    storage = MeetFlowStorage(storage_settings)
    storage.initialize()
    return settings, storage


def build_knowledge_store(storage_settings: StorageSettings) -> KnowledgeIndexStore:
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
    return store


def build_message_payload(text: str) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "event_id": "evt_msg"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_sender"}, "sender_type": "user"},
            "message": {
                "message_id": "om_msg",
                "chat_id": "oc_group",
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "mentions": [{"key": "@_user_1", "name": "MeetFlow"}],
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
