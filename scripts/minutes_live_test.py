from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/minutes_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import load_settings
from core import Resource, configure_logging, get_logger


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实调用飞书 Python 客户端，测试妙记元数据和 AI 产物读取能力。",
    )
    parser.add_argument(
        "--minute",
        required=True,
        help="飞书妙记 URL 或 minute token，URL 形如 https://xxx.feishu.cn/minutes/<token>。",
    )
    parser.add_argument(
        "--identity",
        default="",
        choices=["tenant", "user"],
        help="请求所使用的飞书身份；不传时默认读取 feishu.default_identity。",
    )
    parser.add_argument(
        "--user-id-type",
        default="",
        help="可选：用户 ID 类型，如 user_id / union_id / open_id。",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="只读取妙记基础信息，不尝试读取 AI 总结、待办、章节。",
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
    """按易读方式打印妙记资源摘要。"""

    print("\n妙记读取完成，已转换为 Resource。\n")
    print("=" * 80)
    print(f"resource_id: {resource.resource_id}")
    print(f"resource_type: {resource.resource_type}")
    print(f"title: {resource.title}")
    print(f"source_url: {resource.source_url}")
    print(f"updated_at/create_time: {resource.updated_at}")
    print(f"duration: {resource.source_meta.get('duration')}")
    print(f"owner_id: {resource.source_meta.get('owner_id')}")
    print(f"has_artifacts: {resource.source_meta.get('has_artifacts')}")
    if resource.source_meta.get("artifacts_error"):
        print(f"artifacts_error: {resource.source_meta.get('artifacts_error')}")
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
    """真实测试飞书妙记接口。"""

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.minutes.live_test")
    # 如果命令行没有显式指定身份，就回退到配置中的默认身份。
    identity = args.identity or settings.feishu.default_identity

    logger.info(
        "准备真实调用飞书妙记接口 minute=%s identity=%s metadata_only=%s",
        args.minute,
        identity,
        args.metadata_only,
    )

    client = FeishuClient(settings.feishu)
    try:
        resource = client.fetch_minute_resource(
            minute=args.minute,
            include_artifacts=not args.metadata_only,
            user_id_type=args.user_id_type or None,
            identity=identity,
        )
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查以下配置是否正确：\n"
            "1. config/settings.local.json 中的 feishu.app_id / feishu.app_secret\n"
            "2. 若使用 user 身份，请先执行 python3 scripts/oauth_device_login.py 完成扫码登录\n"
            "3. 确认应用已开通妙记读取相关用户权限，并重新授权\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书妙记接口调用失败：%s", error)
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
