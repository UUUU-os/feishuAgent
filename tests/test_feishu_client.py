from __future__ import annotations

import unittest
from typing import Any

from adapters.feishu_client import FeishuClient


class RecordingFeishuClient(FeishuClient):
    """记录底层请求参数，避免单测触达真实飞书。"""

    def __init__(self) -> None:
        self.last_request: dict[str, Any] = {}

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        with_auth: bool = True,
        use_full_url: bool = False,
        identity: str | None = None,
    ) -> dict[str, Any]:
        self.last_request = {
            "method": method,
            "path": path,
            "params": params,
            "payload": payload,
            "with_auth": with_auth,
            "use_full_url": use_full_url,
            "identity": identity,
        }
        return {"code": 0, "data": {"ok": True}}


class FeishuClientTest(unittest.TestCase):
    """覆盖飞书客户端公共请求封装。"""

    def test_post_forwards_query_params_for_drive_subscription(self) -> None:
        client = RecordingFeishuClient()

        result = client.subscribe_drive_file(
            file_token="doc_token_demo",
            file_type="docx",
            identity="user",
        )

        self.assertEqual(result["code"], 0)
        self.assertEqual(client.last_request["method"], "POST")
        self.assertEqual(client.last_request["path"], "drive/v1/files/doc_token_demo/subscribe")
        self.assertEqual(client.last_request["params"], {"file_type": "docx"})
        self.assertEqual(client.last_request["payload"], {})
        self.assertEqual(client.last_request["identity"], "user")


if __name__ == "__main__":
    unittest.main()
