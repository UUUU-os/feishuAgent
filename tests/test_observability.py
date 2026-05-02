from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.observability import (
    EventWriterSettings,
    StructuredEventWriter,
    mask_secret,
    sanitize_event,
    summarize_arguments,
    summarize_tool_result,
    truncate_text,
)


class ObservabilityTest(unittest.TestCase):
    """验证结构化事件写入和敏感信息处理。"""

    def test_mask_secret_keeps_only_small_edges(self) -> None:
        self.assertEqual(mask_secret("abcd1234efgh5678"), "abcd...5678")
        self.assertEqual(mask_secret("short"), "****")

    def test_sanitize_event_masks_sensitive_keys_and_ids(self) -> None:
        event = sanitize_event(
            {
                "api_key": "sk-test-1234567890",
                "open_id": "ou_abcdefghijklmnopqrstuvwxyz",
                "message": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            },
            record_sensitive_payload=False,
            max_field_chars=200,
            mask_ids=True,
        )
        self.assertEqual(event["api_key"], "sk-t...7890")
        self.assertEqual(event["open_id"], "ou_abc...wxyz")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", event["message"])

    def test_truncate_text_marks_truncated_content(self) -> None:
        result = truncate_text("abcdef", 3)
        self.assertEqual(result, "abc...（已截断）")

    def test_summarize_arguments_hides_values_by_default(self) -> None:
        summary = summarize_arguments({"query": "secret project", "top_k": 3})
        self.assertEqual(summary, {"argument_keys": ["query", "top_k"]})

    def test_summarize_tool_result_extracts_counts(self) -> None:
        summary = summarize_tool_result(
            {
                "items": [{"id": 1}, {"id": 2}],
                "omitted_count": 5,
                "low_confidence": False,
            }
        )
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["omitted_count"], 5)
        self.assertFalse(summary["low_confidence"])

    def test_structured_event_writer_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            writer = StructuredEventWriter(
                EventWriterSettings(
                    structured_events_enabled=True,
                    structured_event_path=str(path),
                    record_sensitive_payload=False,
                    max_event_chars=16000,
                    max_field_chars=200,
                    mask_ids=True,
                    daily_rotate=False,
                )
            )
            writer.emit(
                "tool_call",
                trace_id="trace_test",
                tool_name="docs.fetch_resource",
                api_key="sk-test-1234567890",
            )
            rows = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 1)
            event = json.loads(rows[0])
            self.assertEqual(event["event_type"], "tool_call")
            self.assertEqual(event["trace_id"], "trace_test")
            self.assertEqual(event["api_key"], "sk-t...7890")


if __name__ == "__main__":
    unittest.main()
