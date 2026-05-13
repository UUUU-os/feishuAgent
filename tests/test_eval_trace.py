from __future__ import annotations

import unittest

from core.eval_trace import build_assistant_plan, hash_arguments, mask_identifier, sanitize_value


class EvalTraceTest(unittest.TestCase):
    """验证 Agent trace 的计划生成和脱敏能力。"""

    def test_build_assistant_plan_contains_workflow_specific_steps(self) -> None:
        plan = build_assistant_plan(
            workflow_type="post_meeting_followup",
            required_tools=["minutes.fetch_resource", "contact.search_user", "tasks.create_task"],
            workflow_goal="抽取会后任务",
        )

        steps = [item["step"] for item in plan]
        self.assertTrue(any("读取妙记" in step for step in steps))
        self.assertTrue(any("解析负责人" in step for step in steps))
        self.assertTrue(any("最终回答" in step for step in steps))

    def test_sanitize_value_masks_sensitive_fields(self) -> None:
        payload = {
            "access_token": "real-token",
            "open_id": "ou_demo",
            "nested": {"api_key": "real-key", "chat_id": "oc_demo"},
            "title": "测试会议",
        }

        sanitized = sanitize_value(payload)

        self.assertEqual(sanitized["access_token"], "***")
        self.assertEqual(sanitized["nested"]["api_key"], "***")
        self.assertTrue(str(sanitized["open_id"]).startswith("masked_"))
        self.assertTrue(str(sanitized["nested"]["chat_id"]).startswith("masked_"))
        self.assertEqual(sanitized["title"], "测试会议")

    def test_hash_arguments_uses_sanitized_payload(self) -> None:
        first = hash_arguments({"open_id": "ou_demo", "title": "任务"})
        second = hash_arguments({"open_id": "ou_demo", "title": "任务"})

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)

    def test_mask_identifier_is_stable(self) -> None:
        self.assertEqual(mask_identifier("ou_demo"), mask_identifier("ou_demo"))
        self.assertNotEqual(mask_identifier("ou_demo"), mask_identifier("ou_other"))


if __name__ == "__main__":
    unittest.main()
