from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 允许直接通过 `python3 scripts/oauth_device_login.py` 启动脚本。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters import DeviceAuthorizationBundle, FeishuAuthError, FeishuClient, OAuthTokenBundle
from config import load_settings
from core import configure_logging, get_logger


LOCAL_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.local.json"


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="使用飞书 OAuth Device Flow 登录用户身份，并自动保存 user_access_token。",
    )
    parser.add_argument(
        "--scope",
        default="",
        help="本次登录请求的 scope，使用空格分隔；不传则读取配置中的 feishu.user_oauth_scope。",
    )
    parser.add_argument(
        "--add-scope",
        action="append",
        default=[],
        help="在配置的 feishu.user_oauth_scope 基础上追加一个 scope；可重复传入。",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="只打印 token 结果，不写入 settings.local.json。",
    )
    return parser.parse_args()


def _load_local_config() -> dict[str, Any]:
    """读取本地配置文件；如果不存在则返回空字典。"""

    if not LOCAL_CONFIG_PATH.exists():
        return {}
    with LOCAL_CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置字典。"""

    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _save_token_bundle(settings: Any, bundle: OAuthTokenBundle, scope: str) -> None:
    """把用户 OAuth 结果写入 `settings.local.json`。"""

    current = _load_local_config()
    patch = {
        "feishu": {
            "redirect_uri": settings.feishu.redirect_uri,
            "user_oauth_scope": scope,
            "user_access_token": bundle.access_token,
            "user_access_token_expires_at": bundle.access_token_expires_at,
            "user_refresh_token": bundle.refresh_token,
            "user_refresh_token_expires_at": bundle.refresh_token_expires_at,
        }
    }
    merged = _deep_merge(current, patch)
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_CONFIG_PATH.open("w", encoding="utf-8") as file:
        json.dump(merged, file, ensure_ascii=False, indent=2)


def _print_device_info(bundle: DeviceAuthorizationBundle) -> None:
    """打印 Device Flow 的关键信息。"""

    print("请完成飞书用户授权。")
    print()
    print("方式一：直接在浏览器中打开下面的链接")
    print(bundle.verification_uri_complete)
    print()
    print("方式二：如果该页面展示二维码，请直接使用飞书 App 扫码授权")
    print()
    print(f"user_code: {bundle.user_code}")
    print(f"expires_in: {bundle.expires_in} 秒")
    print("脚本会继续等待，无需手动复制 code。")


def _print_token_summary(bundle: OAuthTokenBundle, user_info: dict[str, Any]) -> None:
    """按易读方式打印 token 与当前用户信息。"""

    print()
    print("OAuth 登录成功，已拿到用户身份令牌：")
    print(f"- open_id: {user_info.get('open_id', '')}")
    print(f"- name: {user_info.get('name', '')}")
    print(f"- access_token 长度: {len(bundle.access_token)}")
    print(f"- access_token_expires_at: {bundle.access_token_expires_at}")
    print(f"- refresh_token 是否存在: {'是' if bool(bundle.refresh_token) else '否'}")
    print(f"- refresh_token_expires_at: {bundle.refresh_token_expires_at}")
    print(f"- scope: {bundle.scope}")


def main() -> int:
    """执行 Device Flow 登录。"""

    args = _parse_args()
    settings = load_settings()
    configure_logging(settings.logging)
    logger = get_logger("meetflow.oauth.device_login")

    client = FeishuClient(settings.feishu)
    scope = build_oauth_scope(
        base_scope=args.scope.strip() or settings.feishu.user_oauth_scope.strip(),
        additional_scopes=args.add_scope,
    )

    try:
        device = client.request_device_authorization(scope=scope)
    except FeishuAuthError as error:
        logger.error("申请 device_code 失败：%s", error)
        print(f"\n申请 device_code 失败：{error}\n")
        return 2

    _print_device_info(device)

    try:
        bundle = client.poll_device_token(
            device_code=device.device_code,
            interval=device.interval,
            expires_in=device.expires_in,
        )
        user_info = client.get_current_user_info(bundle.access_token)
    except FeishuAuthError as error:
        logger.error("Device Flow 登录失败：%s", error)
        print(f"\nDevice Flow 登录失败：{error}\n")
        return 3

    _print_token_summary(bundle, user_info)

    if not args.no_save:
        _save_token_bundle(settings, bundle, scope)
        print(f"\n已写入本地配置：{LOCAL_CONFIG_PATH}")

    print()
    print("下一步你可以直接运行：")
    print("python3 scripts/calendar_live_test.py --identity user --calendar-id primary --debug-calendar")
    return 0


def build_oauth_scope(base_scope: str, additional_scopes: list[str]) -> str:
    """合并 OAuth scope。

    `--scope` 适合完全覆盖；`--add-scope` 适合临时补权限，避免用户手写一长串
    scope 时把中文说明或逗号传给飞书导致 invalid_scope。
    """

    scopes: list[str] = []
    seen: set[str] = set()
    for raw_scope in [base_scope, *additional_scopes, "offline_access"]:
        for item in str(raw_scope or "").split():
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            scopes.append(item)
    return " ".join(scopes)


if __name__ == "__main__":
    raise SystemExit(main())
