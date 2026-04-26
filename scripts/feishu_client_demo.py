from __future__ import annotations

import sys
from pathlib import Path

# 允许直接从 scripts 目录执行演示脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuClient
from config import load_settings
from core import configure_logging, get_logger


def main() -> None:
    """演示飞书客户端的初始化和请求构造逻辑。

    这个脚本默认不发真实网络请求，主要用于帮助理解：
    - 客户端如何读取配置
    - 如何拼接接口 URL
    - 如何组织后续 GET / POST 请求
    """

    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.feishu.demo")

    client = FeishuClient(settings.feishu)

    sample_auth_url = client._build_url("auth/v3/tenant_access_token/internal")
    sample_doc_url = client._build_url("docx/v1/documents/demo_document")

    logger.info("飞书客户端已初始化 base_url=%s", settings.feishu.base_url)
    logger.info("鉴权接口 URL=%s", sample_auth_url)
    logger.info("示例文档接口 URL=%s", sample_doc_url)
    logger.info(
        "当前配置 timeout=%s max_retries=%s",
        settings.feishu.request_timeout_seconds,
        settings.feishu.max_retries,
    )


if __name__ == "__main__":
    main()
