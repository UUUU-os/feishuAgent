from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接通过 `python3 scripts/message_live_test.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import FeishuAPIError, FeishuAuthError, FeishuClient
from config import load_settings
from core import configure_logging, get_logger


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="真实调用飞书 Python 客户端，测试文本消息和卡片消息发送能力。",
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--chat-id",
        default="",
        help="群聊 ID，形如 oc_xxx；不传且配置了 default_chat_id 时，会使用配置值。",
    )
    target_group.add_argument(
        "--user-id",
        default="",
        help="用户 open_id，形如 ou_xxx；用于私聊发送。",
    )
    parser.add_argument(
        "--identity",
        default="",
        choices=["tenant", "user"],
        help="请求所使用的飞书身份；不传时默认读取 feishu.default_identity。",
    )
    parser.add_argument(
        "--message-type",
        default="text",
        choices=["text", "card"],
        help="发送类型：text=纯文本，card=交互卡片。",
    )
    parser.add_argument(
        "--text",
        default="MeetFlow 测试消息：飞书消息发送链路已接通。",
        help="纯文本消息内容，或卡片正文摘要。",
    )
    parser.add_argument(
        "--title",
        default="MeetFlow 通知",
        help="卡片标题。",
    )
    parser.add_argument(
        "--fact",
        action="append",
        default=[],
        help="卡片要点，可传多次，例如 --fact '会议：周会' --fact '风险：缺少负责人'。",
    )
    parser.add_argument(
        "--action-text",
        default="查看详情",
        help="卡片按钮文案；需要和 --action-url 同时使用。",
    )
    parser.add_argument(
        "--action-url",
        default="",
        help="卡片按钮跳转链接。",
    )
    parser.add_argument(
        "--idempotency-key",
        default="",
        help="幂等键；同一个键 1 小时内只会发送一次。",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="真正发送消息。不传时只打印将要发送的 payload。",
    )
    return parser.parse_args()


def _resolve_target(args: argparse.Namespace, default_chat_id: str) -> tuple[str, str]:
    """解析接收者 ID 和 receive_id_type。"""

    if args.user_id:
        return args.user_id, "open_id"
    if args.chat_id:
        return args.chat_id, "chat_id"
    if default_chat_id:
        return default_chat_id, "chat_id"
    raise FeishuAPIError("请传入 --chat-id / --user-id，或在配置中设置 feishu.default_chat_id")


def _build_preview_payload(
    receive_id: str,
    receive_id_type: str,
    message_type: str,
    content: dict[str, object],
    idempotency_key: str,
) -> dict[str, object]:
    """构造 dry-run 预览 payload，便于发送前检查。"""

    payload: dict[str, object] = {
        "receive_id_type": receive_id_type,
        "body": {
            "receive_id": receive_id,
            "msg_type": "interactive" if message_type == "card" else "text",
            "content": json.dumps(content, ensure_ascii=False),
        },
    }
    if idempotency_key:
        body = payload["body"]
        if isinstance(body, dict):
            body["uuid"] = idempotency_key
    return payload


def main() -> int:
    """真实测试飞书消息发送接口。"""

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.message.live_test")
    # 如果命令行没有显式指定身份，就回退到配置中的默认身份。
    identity = args.identity or settings.feishu.default_identity

    client = FeishuClient(settings.feishu)
    try:
        receive_id, receive_id_type = _resolve_target(args, settings.feishu.default_chat_id)
        if args.message_type == "card":
            content = client.build_meetflow_card(
                title=args.title,
                summary=args.text,
                facts=args.fact,
                action_text=args.action_text,
                action_url=args.action_url,
            )
        else:
            content = {"text": args.text}

        preview_payload = _build_preview_payload(
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            message_type=args.message_type,
            content=content,
            idempotency_key=args.idempotency_key,
        )

        print("\n即将发送的飞书消息 payload：")
        print(json.dumps(preview_payload, ensure_ascii=False, indent=2))

        if not args.send:
            print("\n当前是 dry-run，没有真正发送。确认无误后加上 --send 才会发出。")
            return 0

        logger.info(
            "准备真实发送飞书消息 receive_id_type=%s message_type=%s identity=%s",
            receive_id_type,
            args.message_type,
            identity,
        )
        if args.message_type == "card":
            response = client.send_card_message(
                receive_id=receive_id,
                receive_id_type=receive_id_type,
                card=content,
                idempotency_key=args.idempotency_key,
                identity=identity,
            )
        else:
            response = client.send_text_message(
                receive_id=receive_id,
                receive_id_type=receive_id_type,
                text=args.text,
                idempotency_key=args.idempotency_key,
                identity=identity,
            )
    except FeishuAuthError as error:
        logger.error("飞书鉴权失败：%s", error)
        print(
            "\n鉴权失败。请先检查以下配置是否正确：\n"
            "1. config/settings.local.json 中的 feishu.app_id / feishu.app_secret\n"
            "2. 若使用 user 身份，请先执行 python3 scripts/oauth_device_login.py 完成扫码登录\n"
            "3. 若使用 user 发送，请确认已开通 im:message.send_as_user 和 im:message\n"
            "4. 若使用 bot 发送，请确认已开通 im:message:send_as_bot，且机器人在目标群里\n"
        )
        return 2
    except FeishuAPIError as error:
        logger.error("飞书消息接口调用失败：%s", error)
        print(f"\n接口调用失败：{error}\n")
        return 3
    except Exception as error:  # pragma: no cover - 这里作为真实联调脚本兜底
        logger.exception("未知异常")
        print(f"\n发生未知异常：{error}\n")
        return 4

    print("\n消息发送成功：")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
