from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/docs_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import load_settings
from core import Resource, configure_logging, get_logger


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实调用飞书 Python 客户端，测试文档读取与 Resource 转换能力。",
    )
    parser.add_argument(
        "--doc",
        required=True,
        help="飞书文档 URL 或 document token，支持 /docx/、/doc/、/wiki/ 链接。",
    )
    parser.add_argument(
        "--identity",
        default="",
        choices=["tenant", "user"],
        help="请求所使用的飞书身份；不传时默认读取 feishu.default_identity。",
    )
    parser.add_argument(
        "--doc-format",
        default="xml",
        choices=["xml", "markdown", "text"],
        help="文档正文导出格式，默认 xml。",
    )
    parser.add_argument(
        "--detail",
        default="simple",
        choices=["simple", "with-ids", "full"],
        help="导出详细度：simple 适合阅读，with-ids/full 适合定位或编辑。",
    )
    parser.add_argument(
        "--scope",
        default="full",
        choices=["full", "outline", "range", "keyword", "section"],
        help="读取范围：full 为整篇，outline/range/keyword/section 为局部读取。",
    )
    parser.add_argument(
        "--start-block-id",
        default="",
        help="range/section 模式的起始 block id。",
    )
    parser.add_argument(
        "--end-block-id",
        default="",
        help="range 模式的结束 block id；传 -1 表示读到文档末尾。",
    )
    parser.add_argument(
        "--keyword",
        default="",
        help="keyword 模式的关键词，多个关键词可用 | 分隔。",
    )
    parser.add_argument(
        "--context-before",
        type=int,
        default=0,
        help="局部读取时，命中块之前额外带出的兄弟块数量。",
    )
    parser.add_argument(
        "--context-after",
        type=int,
        default=0,
        help="局部读取时，命中块之后额外带出的兄弟块数量。",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=-1,
        help="outline 模式表示标题层级上限，其它局部模式表示子树深度。",
    )
    parser.add_argument(
        "--content-limit",
        type=int,
        default=2000,
        help="控制台最多打印多少字符的正文预览，默认 2000。",
    )
    parser.add_argument(
        "--show-resource-json",
        action="store_true",
        help="是否打印完整 Resource JSON，便于调试字段映射。",
    )
    return parser.parse_args()


def _print_resource_summary(resource: Resource, content_limit: int, show_resource_json: bool) -> None:
    """按易读方式打印文档资源摘要。"""

    print("\n文档读取成功，已转换为 Resource。\n")
    print("=" * 80)
    print(f"resource_id: {resource.resource_id}")
    print(f"resource_type: {resource.resource_type}")
    print(f"title: {resource.title}")
    print(f"source_url: {resource.source_url}")
    print(f"updated_at/revision_id: {resource.updated_at}")
    print(f"content_length: {resource.source_meta.get('content_length')}")
    print(f"content_excerpt: {resource.source_meta.get('content_excerpt')}")

    print("\n正文预览:")
    print("-" * 80)
    print(resource.content[:content_limit])
    if len(resource.content) > content_limit:
        print(f"\n... 已截断，仅展示前 {content_limit} 字符")

    if show_resource_json:
        print("\n完整 Resource JSON:")
        print(json.dumps(resource.to_dict(), ensure_ascii=False, indent=2))


def main() -> int:
    """真实测试飞书文档读取接口。"""

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.docs.live_test")
    # 如果命令行没有显式指定身份，就回退到配置中的默认身份。
    identity = args.identity or settings.feishu.default_identity

    logger.info(
        "准备真实调用飞书文档接口 doc=%s identity=%s scope=%s format=%s",
        args.doc,
        identity,
        args.scope,
        args.doc_format,
    )

    client = FeishuClient(settings.feishu)
    try:
        resource = client.fetch_document_resource(
            document=args.doc,
            doc_format=args.doc_format,
            detail=args.detail,
            scope=args.scope,
            start_block_id=args.start_block_id,
            end_block_id=args.end_block_id,
            keyword=args.keyword,
            context_before=args.context_before,
            context_after=args.context_after,
            max_depth=args.max_depth,
            identity=identity,
        )
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查以下配置是否正确：\n"
            "1. config/settings.local.json 中的 feishu.app_id / feishu.app_secret\n"
            "2. 若使用 user 身份，请先执行 python3 scripts/oauth_device_login.py 完成扫码登录\n"
            "3. 确认应用已开通文档读取相关用户权限，并重新授权\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书文档接口调用失败：%s", error)
        print(f"\n接口调用失败：{error}\n")
        return 3
    except Exception as error:  # pragma: no cover - 这里作为真实联调脚本兜底
        logger.exception("未知异常")
        print(f"\n发生未知异常：{error}\n")
        return 4

    _print_resource_summary(
        resource=resource,
        content_limit=args.content_limit,
        show_resource_json=args.show_resource_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
