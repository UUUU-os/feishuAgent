from __future__ import annotations

import unittest

from adapters.feishu_tools import create_feishu_tool_registry


class FakeMinuteClient:
    """记录妙记读取身份，避免 Agent 误把用户资源切到应用身份。"""

    def __init__(self) -> None:
        self.minute_identity = ""

    def fetch_minute_resource(self, minute: str, include_artifacts: bool = True, identity: str = "user") -> dict[str, object]:
        self.minute_identity = identity
        return {"minute": minute, "include_artifacts": include_artifacts, "identity": identity}


class FeishuToolsTest(unittest.TestCase):
    """锁定飞书工具对关键资源的身份选择。"""

    def test_minutes_fetch_resource_forces_user_identity(self) -> None:
        client = FakeMinuteClient()
        registry = create_feishu_tool_registry(client)  # type: ignore[arg-type]
        tool = registry.get("minutes.fetch_resource")

        result = tool.execute({"minute": "obcn_demo", "include_artifacts": True, "identity": "tenant"})

        self.assertEqual(client.minute_identity, "user")
        self.assertEqual(result["identity"], "user")


if __name__ == "__main__":
    unittest.main()
