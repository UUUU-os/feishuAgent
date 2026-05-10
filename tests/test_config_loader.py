from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from config.loader import DEFAULT_CONFIG_PATH, load_settings


class ConfigLoaderBoundaryTest(unittest.TestCase):
    """Verify AI and Runtime config boundaries stay explicit."""

    def test_default_config_exposes_ai_and_runtime_views(self) -> None:
        settings = load_settings(DEFAULT_CONFIG_PATH)

        self.assertEqual(
            {field.name for field in fields(settings.ai_config)},
            {"llm", "embedding", "reranker", "knowledge_search", "litellm"},
        )
        self.assertEqual(
            {field.name for field in fields(settings.runtime_config)},
            {"storage", "jobs", "observability", "runtime"},
        )
        self.assertEqual(settings.ai_config.litellm.model_alias, "meetflow-default")
        self.assertEqual(settings.runtime_config.runtime.worker_max_concurrency, 1)

    def test_local_config_can_override_litellm_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "litellm": {
                            "enabled": True,
                            "proxy_base_url": "http://127.0.0.1:4000/v1",
                            "model_alias": "meetflow-test",
                        },
                        "runtime": {
                            "worker_max_concurrency": 4,
                            "db_busy_timeout_ms": 8000,
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = load_settings(config_path)

        self.assertTrue(settings.litellm.enabled)
        self.assertEqual(settings.ai_config.litellm.proxy_base_url, "http://127.0.0.1:4000/v1")
        self.assertEqual(settings.ai_config.litellm.model_alias, "meetflow-test")
        self.assertEqual(settings.runtime.worker_max_concurrency, 4)
        self.assertEqual(settings.runtime.db_busy_timeout_ms, 8000)
        self.assertTrue(settings.runtime.db_wal_enabled)


if __name__ == "__main__":
    unittest.main()
