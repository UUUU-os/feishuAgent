from __future__ import annotations

import argparse
import unittest

from config import LLMSettings
from core.llm import DoubaoArkProvider, LLMConfigError, create_llm_provider
from core.models import AgentMessage
from scripts.meetflow_agent_live_test import build_llm_settings


class DoubaoLLMProviderTest(unittest.TestCase):
    def test_create_provider_accepts_doubao_alias(self) -> None:
        settings = LLMSettings(
            provider="doubao-ark",
            model="ep-test-endpoint",
            api_base="",
            api_key="test-key",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )

        provider = create_llm_provider(settings)

        self.assertIsInstance(provider, DoubaoArkProvider)

    def test_doubao_provider_uses_ark_default_base_and_endpoint_id_model(self) -> None:
        settings = LLMSettings(
            provider="doubao",
            model="ep-test-endpoint",
            api_base="",
            api_key="test-key",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )
        provider = DoubaoArkProvider(settings)
        captured: dict[str, object] = {}

        def fake_post_json(endpoint: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            captured["timeout_seconds"] = timeout_seconds
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "ep-test-endpoint",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "豆包接入成功"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

        provider._post_json = fake_post_json  # type: ignore[method-assign]

        response = provider.chat([AgentMessage(role="user", content="ping")])

        self.assertEqual(response.content, "豆包接入成功")
        self.assertEqual(captured["endpoint"], "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        self.assertEqual(captured["payload"]["model"], "ep-test-endpoint")  # type: ignore[index]

    def test_full_chat_completions_api_base_is_not_duplicated(self) -> None:
        settings = LLMSettings(
            provider="doubao",
            model="ep-test-endpoint",
            api_base="https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            api_key="test-key",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )
        provider = DoubaoArkProvider(settings)
        captured: dict[str, object] = {}

        def fake_post_json(endpoint: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured["endpoint"] = endpoint
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "model": "ep-test-endpoint",
            }

        provider._post_json = fake_post_json  # type: ignore[method-assign]

        provider.chat([AgentMessage(role="user", content="ping")])

        self.assertEqual(captured["endpoint"], "https://ark.cn-beijing.volces.com/api/v3/chat/completions")

    def test_doubao_provider_strips_accidental_bearer_prefix(self) -> None:
        settings = LLMSettings(
            provider="doubao",
            model="ep-test-endpoint",
            api_base="",
            api_key="Bearer ark-real-key",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )
        provider = DoubaoArkProvider(settings)

        def fake_post_json(endpoint: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "model": "ep-test-endpoint",
            }

        provider._post_json = fake_post_json  # type: ignore[method-assign]

        provider.chat([AgentMessage(role="user", content="ping")])

        self.assertEqual(settings.api_key, "ark-real-key")

    def test_doubao_provider_rejects_endpoint_id_as_api_key(self) -> None:
        settings = LLMSettings(
            provider="doubao",
            model="ep-test-endpoint",
            api_base="",
            api_key="ep-test-endpoint",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )
        provider = DoubaoArkProvider(settings)

        with self.assertRaisesRegex(Exception, "api_key 看起来填成了 ep-"):
            provider.chat([AgentMessage(role="user", content="ping")])

    def test_live_script_uses_settings_local_llm_for_matching_provider_alias(self) -> None:
        fallback = LLMSettings(
            provider="doubao-ark",
            model="ep-from-settings-local",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
            api_key="ark-key-from-settings-local",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )
        args = argparse.Namespace(
            llm_provider="doubao",
            model="",
            api_base="",
            api_key_env="",
            temperature=None,
            max_tokens=None,
        )

        settings = build_llm_settings(args, fallback)

        self.assertEqual(settings.provider, "doubao-ark")
        self.assertEqual(settings.model, "ep-from-settings-local")
        self.assertEqual(settings.api_key, "ark-key-from-settings-local")

    def test_live_script_rejects_provider_that_does_not_match_settings_local(self) -> None:
        fallback = LLMSettings(
            provider="doubao-ark",
            model="ep-from-settings-local",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
            api_key="ark-key-from-settings-local",
            temperature=0.2,
            max_tokens=128,
            reasoning_effort="",
        )
        args = argparse.Namespace(
            llm_provider="openai",
            model="",
            api_base="",
            api_key_env="",
            temperature=None,
            max_tokens=None,
        )

        with self.assertRaises(LLMConfigError):
            build_llm_settings(args, fallback)


if __name__ == "__main__":
    unittest.main()
