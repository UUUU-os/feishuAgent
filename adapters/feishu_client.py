from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Literal

import requests

from config import FeishuSettings
from core.logging import get_logger
from core.models import ActionItem, CalendarAttendee, CalendarEvent, CalendarInfo, Resource


class FeishuAPIError(RuntimeError):
    """飞书 API 通用异常。

    当接口返回非预期 HTTP 状态码，或者返回体中的业务 code 不为 0 时，
    都会抛出这个异常，方便上层统一处理。
    """


class FeishuAuthError(FeishuAPIError):
    """飞书鉴权异常。"""


def normalize_feishu_message_uuid(idempotency_key: str) -> str:
    """把内部幂等键转换成飞书 IM 接口可接受的 uuid。

    MeetFlow 内部幂等键为了可读性会包含冒号、业务前缀和较长会议 ID；
    飞书消息接口的 `uuid` 字段更适合短的字母数字串。这里用稳定 hash
    保留去重语义，同时避免把内部键原样交给外部接口导致字段校验失败。
    """

    digest = hashlib.sha1(str(idempotency_key or "").encode("utf-8")).hexdigest()
    return f"mf_{digest[:24]}"


def partition_card_facts(facts: list[str]) -> tuple[list[str], list[str]]:
    """把卡片事实分为核心背景和原始链接两组。

    LLM 传入 facts 时可能把链接和背景混在一起。这里在客户端模板层强制
    “先背景、后链接”，让真实群卡片保持稳定阅读顺序。
    """

    background: list[str] = []
    links: list[str] = []
    for fact in facts:
        text = str(fact or "").strip()
        if not text:
            continue
        if "http://" in text or "https://" in text or "链接" in text:
            links.append(text)
        else:
            background.append(text)
    return background, links


@dataclass(slots=True)
class TokenCache:
    """租户访问令牌缓存。

    飞书的 tenant_access_token 有有效期，这里做一个轻量缓存，
    避免每次请求都重新换 token。
    """

    token: str = ""
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        """判断当前 token 是否还在有效期内。

        这里预留 60 秒安全窗口，避免 token 刚好在请求中途过期。
        """

        return bool(self.token) and time.time() < self.expires_at - 60


@dataclass(slots=True)
class OAuthTokenBundle:
    """用户身份 OAuth 令牌结果。

    这个数据结构统一承接：
    - 授权码换取 token
    - refresh_token 刷新 token
    两种返回结果，便于脚本保存和客户端缓存。
    """

    access_token: str
    expires_in: int
    access_token_expires_at: int
    refresh_token: str
    refresh_token_expires_in: int
    refresh_token_expires_at: int
    scope: str
    token_type: str
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class DeviceAuthorizationBundle:
    """设备授权阶段返回的信息。"""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int
    raw_payload: dict[str, Any]


IdentityMode = Literal["tenant", "user"]


class FeishuClient:
    """飞书开放平台客户端。

    当前封装的能力包括：
    - tenant_access_token 鉴权
    - GET / POST 请求封装
    - 统一错误处理
    - 简单重试机制
    """

    def __init__(
        self,
        settings: FeishuSettings,
        user_token_callback: Callable[[OAuthTokenBundle], None] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = get_logger("meetflow.feishu")
        self.session = requests.Session()
        # 自动刷新 user_access_token 后，调用方可以通过回调把新 token 持久化。
        self.user_token_callback = user_token_callback
        # 分别缓存应用身份 token 和用户身份 token，避免两种身份串用。
        self.tenant_token_cache = TokenCache()
        self.user_token_cache = TokenCache(
            token=settings.user_access_token,
            expires_at=float(settings.user_access_token_expires_at or 0),
        )
        # 用户 refresh_token 也放在实例里维护，便于运行期刷新后直接复用。
        self.user_refresh_token = settings.user_refresh_token
        self.user_refresh_token_expires_at = int(settings.user_refresh_token_expires_at or 0)

    def _build_url(self, path: str) -> str:
        """将接口路径拼成完整 URL。"""

        normalized_base = self.settings.base_url.rstrip("/")
        normalized_path = path.lstrip("/")
        return f"{normalized_base}/{normalized_path}"

    def _build_headers(
        self,
        with_auth: bool = True,
        identity: IdentityMode | None = None,
    ) -> dict[str, str]:
        """构建请求头。

        默认会自动带上租户访问令牌；如果某些接口本身就是鉴权接口，
        可以传 `with_auth=False` 跳过 token 注入。
        """

        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        if with_auth:
            auth_token = self.get_access_token(identity=identity or self.settings.default_identity)
            headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def get_tenant_access_token(self, force_refresh: bool = False) -> str:
        """获取 tenant_access_token，并做本地缓存。"""

        if not force_refresh and self.tenant_token_cache.is_valid():
            return self.tenant_token_cache.token

        url = self._build_url("auth/v3/tenant_access_token/internal")
        payload = {
            "app_id": self.settings.app_id,
            "app_secret": self.settings.app_secret,
        }

        self.logger.info("正在向飞书申请 tenant_access_token")
        response_json = self._request(
            method="POST",
            path=url,
            payload=payload,
            with_auth=False,
            use_full_url=True,
        )

        token = response_json.get("tenant_access_token", "")
        expire = response_json.get("expire", 0)
        if not token:
            raise FeishuAuthError("飞书 tenant_access_token 获取失败，返回结果中缺少 token")

        self.tenant_token_cache = TokenCache(
            token=token,
            expires_at=time.time() + int(expire),
        )
        return self.tenant_token_cache.token

    def get_user_access_token(self, force_refresh: bool = False) -> str:
        """获取 user_access_token。

        优先级如下：
        1. 内存缓存中的 user_access_token 仍有效时直接返回
        2. 配置里已有有效的 user_access_token 时装载进缓存
        3. 如果 access_token 已失效但 refresh_token 还有效，则自动刷新
        4. 都不满足时，提示用户重新走 OAuth 授权流程
        """

        if not force_refresh and self.user_token_cache.is_valid():
            return self.user_token_cache.token

        if (
            self.settings.user_access_token
            and int(self.settings.user_access_token_expires_at or 0) > int(time.time()) + 60
            and not force_refresh
        ):
            self.user_token_cache = TokenCache(
                token=self.settings.user_access_token,
                expires_at=float(self.settings.user_access_token_expires_at),
            )
            return self.user_token_cache.token

        refresh_token = self.user_refresh_token or self.settings.user_refresh_token
        refresh_expires_at = self.user_refresh_token_expires_at or int(
            self.settings.user_refresh_token_expires_at or 0
        )
        if refresh_token and refresh_expires_at > int(time.time()) + 60:
            bundle = self.refresh_user_access_token(refresh_token=refresh_token)
            return bundle.access_token

        raise FeishuAuthError(
            "当前请求需要 user_access_token，但本地没有可用的用户令牌。"
            "请先执行 Device Flow 授权流程，或使用 scripts/oauth_device_login.py 获取并保存用户令牌。"
        )

    def get_access_token(self, identity: IdentityMode = "tenant", force_refresh: bool = False) -> str:
        """按身份模式获取访问令牌。"""

        if identity == "tenant":
            return self.get_tenant_access_token(force_refresh=force_refresh)
        if identity == "user":
            return self.get_user_access_token(force_refresh=force_refresh)
        raise FeishuAuthError(f"不支持的飞书身份模式：{identity}")

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """发送 GET 请求。"""

        return self._request(
            method="GET",
            path=path,
            params=params,
            identity=identity,
        )

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """发送 POST 请求。"""

        return self._request(
            method="POST",
            path=path,
            payload=payload,
            identity=identity,
        )

    def request_device_authorization(self, scope: str | None = None) -> DeviceAuthorizationBundle:
        """发起 OAuth Device Flow，获取 device_code 和验证链接。

        这条链路和 `lark-cli auth login` 的思路一致：
        - 先拿到 device_code
        - 再让用户访问 verification_uri_complete 完成扫码或授权
        - 最后轮询 token 接口获取 user_access_token
        """

        final_scope = (scope or self.settings.user_oauth_scope).strip()
        if "offline_access" not in final_scope.split():
            final_scope = (final_scope + " offline_access").strip()

        endpoint = "https://accounts.feishu.cn/oauth/v1/device_authorization"
        basic_auth = base64.b64encode(
            f"{self.settings.app_id}:{self.settings.app_secret}".encode("utf-8")
        ).decode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth}",
        }
        form_data = {
            "client_id": self.settings.app_id,
            "scope": final_scope,
        }

        self.logger.info("正在向飞书申请 device_code")
        response = self.session.post(
            endpoint,
            headers=headers,
            data=form_data,
            timeout=self.settings.request_timeout_seconds,
        )
        payload = self._parse_response_payload(response, endpoint, "POST")

        error_name = payload.get("error", "")
        if error_name:
            raise FeishuAuthError(
                "设备授权申请失败 "
                f"error={error_name} "
                f"error_description={payload.get('error_description', '')}"
            )

        verification_uri = str(payload.get("verification_uri", "") or "")
        verification_uri_complete = str(payload.get("verification_uri_complete", "") or verification_uri)
        device_code = str(payload.get("device_code", "") or "")
        if not device_code or not verification_uri_complete:
            raise FeishuAuthError("设备授权响应缺少 device_code 或 verification_uri_complete")

        return DeviceAuthorizationBundle(
            device_code=device_code,
            user_code=str(payload.get("user_code", "") or ""),
            verification_uri=verification_uri,
            verification_uri_complete=verification_uri_complete,
            expires_in=int(payload.get("expires_in", 240) or 240),
            interval=int(payload.get("interval", 5) or 5),
            raw_payload=payload,
        )

    def refresh_user_access_token(
        self,
        refresh_token: str | None = None,
        scope: str | None = None,
    ) -> OAuthTokenBundle:
        """使用 refresh_token 刷新 user_access_token。"""

        effective_refresh_token = refresh_token or self.user_refresh_token or self.settings.user_refresh_token
        if not effective_refresh_token:
            raise FeishuAuthError(
                "当前没有可用的 user_refresh_token，无法自动刷新。请重新走用户授权流程。"
            )

        payload: dict[str, Any] = {
            "grant_type": "refresh_token",
            "client_id": self.settings.app_id,
            "client_secret": self.settings.app_secret,
            "refresh_token": effective_refresh_token,
        }
        if scope:
            payload["scope"] = scope

        response_json = self._request(
            method="POST",
            path=self._build_url("authen/v2/oauth/token"),
            payload=payload,
            with_auth=False,
            use_full_url=True,
        )
        bundle = self._parse_oauth_token_bundle(response_json)
        self._apply_user_oauth_bundle(bundle)
        self._notify_user_oauth_bundle(bundle)
        return bundle

    def poll_device_token(
        self,
        device_code: str,
        interval: int,
        expires_in: int,
    ) -> OAuthTokenBundle:
        """轮询 token 接口，直到用户授权完成或超时。"""

        deadline = time.time() + expires_in
        current_interval = max(interval, 1)
        endpoint = self._build_url("authen/v2/oauth/token")

        while time.time() < deadline:
            time.sleep(current_interval)
            form_data = {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": self.settings.app_id,
                "client_secret": self.settings.app_secret,
            }
            response = self.session.post(
                endpoint,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=form_data,
                timeout=self.settings.request_timeout_seconds,
            )
            # Device Flow 轮询是一个特例：
            # 在用户尚未完成授权时，飞书会返回 HTTP 400，但响应体里的
            # `authorization_pending` / `slow_down` 其实是协议中的正常状态，
            # 不能像普通 API 一样直接按 HTTP 错误抛出。
            payload = self._parse_response_payload(
                response=response,
                url=endpoint,
                method="POST",
                allow_http_error_payload=True,
            )

            error_name = str(payload.get("error", "") or "")
            if not error_name and payload.get("access_token"):
                bundle = self._parse_oauth_token_bundle(payload)
                self._apply_user_oauth_bundle(bundle)
                self._notify_user_oauth_bundle(bundle)
                return bundle

            if error_name == "authorization_pending":
                continue
            if error_name == "slow_down":
                current_interval = min(current_interval + 5, 60)
                continue
            if error_name in {"access_denied", "expired_token", "invalid_grant"}:
                raise FeishuAuthError(
                    "Device Flow 授权失败 "
                    f"error={error_name} "
                    f"error_description={payload.get('error_description', '')}"
                )

            raise FeishuAuthError(
                "Device Flow 轮询失败 "
                f"error={error_name} "
                f"error_description={payload.get('error_description', '')}"
            )

        raise FeishuAuthError("Device Flow 授权超时，请重新发起登录")

    def get_current_user_info(self, access_token: str | None = None) -> dict[str, Any]:
        """使用用户 token 读取当前登录用户信息。"""

        token = access_token or self.get_user_access_token()
        response = self.session.get(
            self._build_url("authen/v1/user_info"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
            timeout=self.settings.request_timeout_seconds,
        )
        payload = self._parse_response_payload(
            response=response,
            url=self._build_url("authen/v1/user_info"),
            method="GET",
        )
        code = int(payload.get("code", 0) or 0)
        if code != 0:
            raise FeishuAuthError(
                "获取当前用户信息失败 "
                f"code={code} "
                f"msg={payload.get('msg', '')}"
            )
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    def search_users(
        self,
        query: str,
        page_size: int = 20,
        page_token: str = "",
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """通过关键词搜索飞书用户。

        对应 lark-cli `contact +search-user` 的底层接口：
        GET /open-apis/search/v1/user
        """

        if not query.strip():
            raise FeishuAPIError("搜索用户时 query 不能为空")

        params: dict[str, Any] = {
            "query": query.strip(),
            "page_size": page_size,
        }
        if page_token:
            params["page_token"] = page_token

        response_json = self.get(
            path="search/v1/user",
            params=params,
            identity=identity or "user",
        )
        data = response_json.get("data", {})
        return data if isinstance(data, dict) else {}

    def get_primary_calendars(self, identity: IdentityMode | None = None) -> list[CalendarInfo]:
        """获取主日历列表，并解析出真实日历信息。

        根据你提供的官方文档与响应示例：
        - 请求方式：POST
        - 请求路径：/open-apis/calendar/v4/calendars/primary
        """

        response_json = self.post(
            path="calendar/v4/calendars/primary",
            payload={},
            identity=identity,
        )
        calendars = response_json.get("data", {}).get("calendars", [])
        return [self.to_calendar_info(item) for item in calendars]

    def get_calendar(self, calendar_id: str, identity: IdentityMode | None = None) -> CalendarInfo:
        """获取单个日历的详细信息。

        对应接口：
        GET /open-apis/calendar/v4/calendars/{calendar_id}
        """

        response_json = self.get(
            path=f"calendar/v4/calendars/{calendar_id}",
            identity=identity,
        )
        return self.to_calendar_info({"calendar": response_json.get("data", {})})

    def resolve_calendar_id(self, calendar_id: str, identity: IdentityMode | None = None) -> str:
        """把业务层传入的日历标识解析成真实 `calendar_id`。

        当传入的是 `primary` 时，需要先调用“获取主日历”接口，
        再从返回结果里取出真实可用的 `calendar_id`。
        """

        if calendar_id != "primary":
            return calendar_id

        calendars = self.get_primary_calendars(identity=identity)
        if not calendars:
            raise FeishuAPIError("获取主日历成功，但返回的 calendars 为空")

        # 当前优先取第一个未删除且带有真实 calendar_id 的主日历。
        for calendar in calendars:
            if calendar.calendar_id and not calendar.is_deleted:
                return calendar.calendar_id

        raise FeishuAPIError("主日历列表中没有可用的真实 calendar_id")

    def list_calendar_event_instances(
        self,
        calendar_id: str,
        start_time: str,
        end_time: str,
        user_id_type: str | None = None,
        identity: IdentityMode | None = None,
    ) -> list[CalendarEvent]:
        """读取指定时间窗口内的日程视图。

        这里对应飞书接口：
        GET /open-apis/calendar/v4/calendars/{calendar_id}/events/instance_view
        """

        # 如果业务层传入的是 `primary`，先解析成真实 calendar_id。
        resolved_calendar_id = self.resolve_calendar_id(calendar_id, identity=identity)

        # 注意：
        # calendar_id 已经放在 URL path 中，
        # 这里不应该再把它作为 query 参数重复传递，否则部分接口会返回 400。
        params: dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
        }
        if user_id_type:
            params["user_id_type"] = user_id_type

        response_json = self.get(
            path=f"calendar/v4/calendars/{resolved_calendar_id}/events/instance_view",
            params=params,
            identity=identity,
        )
        items = response_json.get("data", {}).get("items", [])
        return [self.to_calendar_event(item) for item in items]

    def to_calendar_info(self, item: dict[str, Any]) -> CalendarInfo:
        """将飞书日历基础信息对象转换为统一 `CalendarInfo` 模型。"""

        calendar = item.get("calendar", {})
        return CalendarInfo(
            calendar_id=calendar.get("calendar_id", ""),
            summary=calendar.get("summary", ""),
            description=calendar.get("description", ""),
            permissions=calendar.get("permissions", ""),
            color=int(calendar.get("color", -1)),
            calendar_type=calendar.get("type", ""),
            summary_alias=calendar.get("summary_alias", ""),
            is_deleted=bool(calendar.get("is_deleted", False)),
            is_third_party=bool(calendar.get("is_third_party", False)),
            role=calendar.get("role", ""),
            user_id=item.get("user_id", ""),
            raw_payload=item,
        )

    def to_calendar_event(self, item: dict[str, Any]) -> CalendarEvent:
        """将飞书日历接口返回的原始对象转换为统一日历模型。"""

        attendees = [
            CalendarAttendee(
                attendee_id=attendee.get("attendee_id", ""),
                display_name=attendee.get("display_name", ""),
                attendee_type=attendee.get("type", ""),
                rsvp_status=attendee.get("rsvp_status", ""),
                is_optional=bool(attendee.get("is_optional", False)),
                is_organizer=bool(attendee.get("is_organizer", False)),
            )
            for attendee in item.get("attendees", [])
        ]

        start_time = self._extract_event_time(item.get("start_time", {}))
        end_time = self._extract_event_time(item.get("end_time", {}))
        organizer = item.get("event_organizer", {})

        return CalendarEvent(
            event_id=item.get("event_id", ""),
            summary=item.get("summary", ""),
            description=item.get("description", ""),
            start_time=start_time,
            end_time=end_time,
            timezone=item.get("start_time", {}).get("timezone", ""),
            organizer_name=organizer.get("display_name", ""),
            organizer_id=organizer.get("user_id", ""),
            status=item.get("status", ""),
            app_link=item.get("app_link", ""),
            attendees=attendees,
            raw_payload=item,
        )

    def _extract_event_time(self, time_info: dict[str, Any]) -> str:
        """从飞书时间对象中提取更适合业务层使用的时间值。

        飞书日历接口里，时间可能是：
        - timestamp：秒级时间戳，常规会议最常见
        - date：全天事件
        这里统一优先取 timestamp，其次取 date。
        """

        return str(time_info.get("timestamp") or time_info.get("date") or "")

    @staticmethod
    def extract_document_token(document: str) -> str:
        """从飞书文档 URL 或裸 token 中提取 document_id。

        这里参考 `lark-cli docs +fetch --api-version v2` 的解析方式，
        支持以下输入：
        - https://xxx.feishu.cn/docx/<token>
        - https://xxx.feishu.cn/doc/<token>
        - https://xxx.feishu.cn/wiki/<token>
        - <token>
        """

        raw_document = document.strip()
        if not raw_document:
            raise FeishuAPIError("文档标识不能为空，请传入飞书文档 URL 或 document token")

        for marker in ("/wiki/", "/docx/", "/doc/"):
            marker_index = raw_document.find(marker)
            if marker_index < 0:
                continue

            token = raw_document[marker_index + len(marker) :]
            token = re.split(r"[/\\?#]", token, maxsplit=1)[0].strip()
            if token:
                return token

        # 如果输入已经是 URL，但没有命中支持的路径，说明它可能不是可读取的新版文档。
        if "://" in raw_document:
            raise FeishuAPIError(
                "暂不支持该文档 URL，请确认它是 /docx/、/doc/ 或 /wiki/ 类型的飞书文档链接"
            )

        if re.search(r"[/\\?#]", raw_document):
            raise FeishuAPIError("文档 token 中不应包含路径、查询参数或片段标识")

        return raw_document

    def fetch_document_resource(
        self,
        document: str,
        doc_format: str = "xml",
        detail: str = "simple",
        scope: str = "full",
        start_block_id: str = "",
        end_block_id: str = "",
        keyword: str = "",
        context_before: int = 0,
        context_after: int = 0,
        max_depth: int = -1,
        identity: IdentityMode | None = None,
    ) -> Resource:
        """读取飞书文档，并转换成内部统一 `Resource` 模型。

        这里使用飞书 `docs_ai` 文档读取接口：
        POST /open-apis/docs_ai/v1/documents/{document_id}/fetch

        返回 `Resource` 后，后续召回、摘要、证据引用都可以基于统一资源结构处理。
        """

        document_id = self.extract_document_token(document)
        response_json = self.fetch_document(
            document_id=document_id,
            doc_format=doc_format,
            detail=detail,
            scope=scope,
            start_block_id=start_block_id,
            end_block_id=end_block_id,
            keyword=keyword,
            context_before=context_before,
            context_after=context_after,
            max_depth=max_depth,
            identity=identity,
        )
        document_data = response_json.get("data", {}).get("document", {})
        if not isinstance(document_data, dict):
            raise FeishuAPIError("飞书文档读取成功，但返回体中缺少 document 对象")

        return self.to_document_resource(
            document_id=document_id,
            document_data=document_data,
            source_url=document if "://" in document else "",
            doc_format=doc_format,
            detail=detail,
            scope=scope,
        )

    def fetch_document(
        self,
        document_id: str,
        doc_format: str = "xml",
        detail: str = "simple",
        scope: str = "full",
        start_block_id: str = "",
        end_block_id: str = "",
        keyword: str = "",
        context_before: int = 0,
        context_after: int = 0,
        max_depth: int = -1,
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """调用飞书 docs_ai 接口读取文档原始内容。

        这个方法保留原始响应，适合调试；业务层通常应使用
        `fetch_document_resource()`，直接拿统一的 `Resource` 对象。
        """

        payload = self._build_document_fetch_payload(
            doc_format=doc_format,
            detail=detail,
            scope=scope,
            start_block_id=start_block_id,
            end_block_id=end_block_id,
            keyword=keyword,
            context_before=context_before,
            context_after=context_after,
            max_depth=max_depth,
        )
        return self.post(
            path=f"docs_ai/v1/documents/{document_id}/fetch",
            payload=payload,
            identity=identity,
        )

    def to_document_resource(
        self,
        document_id: str,
        document_data: dict[str, Any],
        source_url: str,
        doc_format: str,
        detail: str,
        scope: str,
    ) -> Resource:
        """将飞书文档读取结果转换为统一 `Resource` 模型。"""

        content = str(document_data.get("content", "") or "")
        title = str(document_data.get("title", "") or "").strip()
        if not title:
            title = self._extract_document_title(content) or document_id

        revision_id = document_data.get("revision_id", "")
        # source_meta 保留检索和调试需要的轻量元信息，避免重复塞入完整正文。
        source_meta = {
            "document_id": document_data.get("document_id", document_id),
            "revision_id": revision_id,
            "doc_format": doc_format,
            "detail": detail,
            "scope": scope,
            "content_length": len(content),
            "content_excerpt": self._build_text_excerpt(content),
        }

        return Resource(
            resource_id=document_id,
            resource_type="feishu_document",
            title=title,
            content=content,
            source_url=source_url,
            source_meta=source_meta,
            updated_at=str(revision_id or ""),
        )

    def _build_document_fetch_payload(
        self,
        doc_format: str,
        detail: str,
        scope: str,
        start_block_id: str,
        end_block_id: str,
        keyword: str,
        context_before: int,
        context_after: int,
        max_depth: int,
    ) -> dict[str, Any]:
        """构造 docs_ai 文档读取接口请求体。"""

        if doc_format not in {"xml", "markdown", "text"}:
            raise FeishuAPIError("doc_format 仅支持 xml、markdown 或 text")
        if detail not in {"simple", "with-ids", "full"}:
            raise FeishuAPIError("detail 仅支持 simple、with-ids 或 full")
        if doc_format != "xml" and detail in {"with-ids", "full"}:
            raise FeishuAPIError("with-ids/full 只适用于 xml 格式文档读取")

        payload: dict[str, Any] = {
            "format": doc_format,
            "export_option": self._build_document_export_option(detail),
        }

        read_option = self._build_document_read_option(
            scope=scope,
            start_block_id=start_block_id,
            end_block_id=end_block_id,
            keyword=keyword,
            context_before=context_before,
            context_after=context_after,
            max_depth=max_depth,
        )
        if read_option:
            payload["read_option"] = read_option
        return payload

    def _build_document_export_option(self, detail: str) -> dict[str, bool]:
        """根据 detail 级别构造导出选项。"""

        if detail == "simple":
            return {
                "export_block_id": False,
                "export_style_attrs": False,
                "export_cite_extra_data": False,
            }
        if detail == "with-ids":
            return {
                "export_block_id": True,
                "export_style_attrs": False,
                "export_cite_extra_data": False,
            }
        return {
            "export_block_id": True,
            "export_style_attrs": True,
            "export_cite_extra_data": True,
        }

    def _build_document_read_option(
        self,
        scope: str,
        start_block_id: str,
        end_block_id: str,
        keyword: str,
        context_before: int,
        context_after: int,
        max_depth: int,
    ) -> dict[str, str] | None:
        """根据 scope 构造局部读取参数。

        `full` 表示读取整篇文档，不需要给服务端传 read_option。
        其余模式与 `lark-cli docs +fetch --api-version v2` 保持一致。
        """

        normalized_scope = (scope or "full").strip()
        if normalized_scope == "full":
            return None
        if normalized_scope not in {"outline", "range", "keyword", "section"}:
            raise FeishuAPIError("scope 仅支持 full、outline、range、keyword 或 section")

        if context_before < 0 or context_after < 0:
            raise FeishuAPIError("context_before/context_after 不能为负数")
        if max_depth < -1:
            raise FeishuAPIError("max_depth 不能小于 -1")
        if normalized_scope == "range" and not start_block_id and not end_block_id:
            raise FeishuAPIError("range 模式需要 start_block_id 或 end_block_id")
        if normalized_scope == "keyword" and not keyword:
            raise FeishuAPIError("keyword 模式需要 keyword")
        if normalized_scope == "section" and not start_block_id:
            raise FeishuAPIError("section 模式需要 start_block_id")

        read_option: dict[str, str] = {"read_mode": normalized_scope}
        if start_block_id:
            read_option["start_block_id"] = start_block_id
        if end_block_id:
            read_option["end_block_id"] = end_block_id
        if keyword:
            read_option["keyword"] = keyword
        if context_before > 0:
            read_option["context_before"] = str(context_before)
        if context_after > 0:
            read_option["context_after"] = str(context_after)
        if max_depth >= 0:
            read_option["max_depth"] = str(max_depth)
        return read_option

    def _extract_document_title(self, content: str) -> str:
        """从 XML/Markdown 文本中尽量提取标题。"""

        title_match = re.search(r"<title[^>]*>(.*?)</title>", content, flags=re.DOTALL)
        if title_match:
            return self._strip_markup(title_match.group(1)).strip()

        for line in content.splitlines():
            stripped_line = self._strip_markup(line).strip().lstrip("#").strip()
            if stripped_line:
                return stripped_line
        return ""

    def _build_text_excerpt(self, content: str, limit: int = 500) -> str:
        """把文档内容压缩成便于日志和卡片展示的短摘要。"""

        plain_text = self._strip_markup(content)
        plain_text = re.sub(r"\s+", " ", plain_text).strip()
        if len(plain_text) <= limit:
            return plain_text
        return plain_text[:limit].rstrip() + "..."

    def _strip_markup(self, content: str) -> str:
        """移除 XML/HTML 标签，生成更接近自然语言的纯文本。"""

        without_tags = re.sub(r"<[^>]+>", " ", content)
        return (
            without_tags.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&apos;", "'")
        )

    @staticmethod
    def extract_minute_token(minute: str) -> str:
        """从飞书妙记 URL 或裸 token 中提取 minute_token。

        飞书妙记链接通常形如：
        https://xxx.feishu.cn/minutes/<minute_token>
        """

        raw_minute = minute.strip()
        if not raw_minute:
            raise FeishuAPIError("妙记标识不能为空，请传入妙记 URL 或 minute token")

        marker = "/minutes/"
        marker_index = raw_minute.find(marker)
        if marker_index >= 0:
            token = raw_minute[marker_index + len(marker) :]
            token = re.split(r"[/\\?#]", token, maxsplit=1)[0].strip()
            if token:
                return token

        if "://" in raw_minute:
            raise FeishuAPIError("暂不支持该妙记 URL，请确认链接路径中包含 /minutes/<token>")

        if re.search(r"[/\\?#]", raw_minute):
            raise FeishuAPIError("妙记 token 中不应包含路径、查询参数或片段标识")

        return raw_minute

    def fetch_minute_resource(
        self,
        minute: str,
        include_artifacts: bool = True,
        user_id_type: str | None = None,
        identity: IdentityMode | None = None,
    ) -> Resource:
        """读取飞书妙记，并转换为内部统一 `Resource` 模型。

        当前主链路：
        - 读取妙记基础信息
        - 尝试读取 AI 产物：summary / todos / chapters
        - 无 AI 产物时退化为仅包含元数据的 Resource
        """

        minute_token = self.extract_minute_token(minute)
        minute_response = self.get_minute(
            minute_token=minute_token,
            user_id_type=user_id_type,
            identity=identity,
        )
        minute_data = minute_response.get("data", {}).get("minute", {})
        if not isinstance(minute_data, dict):
            raise FeishuAPIError("飞书妙记读取成功，但返回体中缺少 minute 对象")

        artifacts_data: dict[str, Any] = {}
        artifacts_error = ""
        if include_artifacts:
            try:
                artifacts_response = self.get_minute_artifacts(
                    minute_token=minute_token,
                    identity=identity,
                )
                artifacts_data = artifacts_response.get("data", {})
            except FeishuAPIError as error:
                # AI 产物不是 T2.4 的硬依赖；失败时保留错误，资源仍可用作元数据。
                artifacts_error = str(error)

        return self.to_minute_resource(
            minute_token=minute_token,
            minute_data=minute_data,
            artifacts_data=artifacts_data,
            artifacts_error=artifacts_error,
            fallback_source_url=minute if "://" in minute else "",
        )

    def get_minute(
        self,
        minute_token: str,
        user_id_type: str | None = None,
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """读取妙记基础信息。

        对应接口：
        GET /open-apis/minutes/v1/minutes/{minute_token}
        """

        params: dict[str, Any] = {}
        if user_id_type:
            params["user_id_type"] = user_id_type

        return self.get(
            path=f"minutes/v1/minutes/{minute_token}",
            params=params or None,
            identity=identity,
        )

    def get_minute_artifacts(
        self,
        minute_token: str,
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """读取妙记 AI 产物。

        对应接口：
        GET /open-apis/minutes/v1/minutes/{minute_token}/artifacts

        常见返回字段包括：
        - summary：妙记总结
        - minute_todos：待办
        - minute_chapters：章节
        """

        return self.get(
            path=f"minutes/v1/minutes/{minute_token}/artifacts",
            identity=identity,
        )

    def to_minute_resource(
        self,
        minute_token: str,
        minute_data: dict[str, Any],
        artifacts_data: dict[str, Any],
        artifacts_error: str,
        fallback_source_url: str,
    ) -> Resource:
        """将妙记元数据和 AI 产物转换为统一 `Resource` 模型。"""

        title = str(minute_data.get("title", "") or minute_token)
        source_url = str(minute_data.get("url", "") or fallback_source_url)
        content = self._build_minute_content(minute_data, artifacts_data, artifacts_error)
        source_meta = {
            "minute_token": minute_data.get("token", minute_token),
            "owner_id": minute_data.get("owner_id", ""),
            "cover": minute_data.get("cover", ""),
            "duration": minute_data.get("duration", ""),
            "create_time": minute_data.get("create_time", ""),
            "has_artifacts": bool(artifacts_data),
            "artifacts_error": artifacts_error,
            "content_length": len(content),
            "content_excerpt": self._build_text_excerpt(content),
        }

        return Resource(
            resource_id=minute_token,
            resource_type="feishu_minute",
            title=title,
            content=content,
            source_url=source_url,
            source_meta=source_meta,
            updated_at=str(minute_data.get("create_time", "") or ""),
        )

    def _build_minute_content(
        self,
        minute_data: dict[str, Any],
        artifacts_data: dict[str, Any],
        artifacts_error: str,
    ) -> str:
        """把妙记元数据和 AI 产物拼成可被召回/摘要使用的正文。"""

        lines = [
            f"# {minute_data.get('title', '未命名妙记')}",
            "",
            "## 基础信息",
            f"- 妙记链接：{minute_data.get('url', '')}",
            f"- 创建时间：{minute_data.get('create_time', '')}",
            f"- 时长毫秒：{minute_data.get('duration', '')}",
            f"- 所有者：{minute_data.get('owner_id', '')}",
        ]

        summary = str(artifacts_data.get("summary", "") or "").strip()
        if summary:
            lines.extend(["", "## AI 总结", summary])

        todos = artifacts_data.get("minute_todos", [])
        if isinstance(todos, list) and todos:
            lines.extend(["", "## 待办"])
            for index, todo in enumerate(todos, start=1):
                lines.append(f"{index}. {self._format_minute_artifact_item(todo)}")

        chapters = artifacts_data.get("minute_chapters", [])
        if isinstance(chapters, list) and chapters:
            lines.extend(["", "## 章节"])
            for index, chapter in enumerate(chapters, start=1):
                lines.append(f"{index}. {self._format_minute_artifact_item(chapter)}")

        if artifacts_error:
            lines.extend(
                [
                    "",
                    "## AI 产物状态",
                    "当前仅成功读取妙记元数据，AI 总结/待办/章节暂不可用。",
                    f"错误信息：{artifacts_error}",
                ]
            )
        elif not artifacts_data:
            lines.extend(["", "## AI 产物状态", "当前没有返回 AI 总结、待办或章节。"])

        return "\n".join(lines).strip()

    def _format_minute_artifact_item(self, item: Any) -> str:
        """把妙记待办/章节条目格式化为易读文本。"""

        if isinstance(item, str):
            return item
        if not isinstance(item, dict):
            return str(item)

        for key in ("content", "text", "title", "summary", "description"):
            value = item.get(key)
            if value:
                return str(value)
        return json.dumps(item, ensure_ascii=False)

    def list_my_tasks(
        self,
        completed: bool | None = False,
        page_size: int = 50,
        page_limit: int = 20,
        page_token: str = "",
        user_id_type: str = "open_id",
        identity: IdentityMode | None = None,
    ) -> list[ActionItem]:
        """读取当前用户负责的任务，并转换为内部 `ActionItem`。

        对应飞书接口：
        GET /open-apis/task/v2/tasks

        注意：任务列表接口只能使用 user 身份，`type=my_tasks`
        表示“我负责的任务”。
        """

        task_items = self.list_my_task_items(
            completed=completed,
            page_size=page_size,
            page_limit=page_limit,
            page_token=page_token,
            user_id_type=user_id_type,
            identity=identity,
        )
        return [self.to_action_item(task_item) for task_item in task_items]

    def list_my_task_items(
        self,
        completed: bool | None = False,
        page_size: int = 50,
        page_limit: int = 20,
        page_token: str = "",
        user_id_type: str = "open_id",
        identity: IdentityMode | None = None,
    ) -> list[dict[str, Any]]:
        """读取当前用户负责的任务原始列表。

        这个方法保留飞书原始任务 JSON，适合调试；业务层通常使用
        `list_my_tasks()` 直接拿内部 `ActionItem`。
        """

        if page_size < 1 or page_size > 100:
            raise FeishuAPIError("page_size 必须在 1 到 100 之间")
        if page_limit < 1:
            raise FeishuAPIError("page_limit 必须大于等于 1")

        params: dict[str, Any] = {
            "type": "my_tasks",
            "page_size": page_size,
            "user_id_type": user_id_type,
        }
        if completed is not None:
            params["completed"] = completed
        if page_token:
            params["page_token"] = page_token

        all_items: list[dict[str, Any]] = []
        current_page = 0
        while current_page < page_limit:
            current_page += 1
            response_json = self.get(
                path="task/v2/tasks",
                params=params,
                identity=identity or "user",
            )
            data = response_json.get("data", {})
            items = data.get("items", [])
            if isinstance(items, list):
                all_items.extend(item for item in items if isinstance(item, dict))

            if not data.get("has_more"):
                break

            next_page_token = str(data.get("page_token", "") or "")
            if not next_page_token:
                break
            params["page_token"] = next_page_token

        return all_items

    def to_action_item(self, item: dict[str, Any]) -> ActionItem:
        """将飞书任务对象转换为内部 `ActionItem` 模型。"""

        due = item.get("due", {})
        due_timestamp = ""
        if isinstance(due, dict):
            due_timestamp = str(due.get("timestamp", "") or "")

        task_guid = str(item.get("guid", "") or item.get("task_id", "") or "")
        status = str(item.get("status", "") or "todo")
        owner = self._extract_task_owner(item)

        return ActionItem(
            item_id=task_guid,
            title=str(item.get("summary", "") or "未命名任务"),
            owner=owner,
            due_date=due_timestamp,
            status=status,
            confidence=1.0,
            needs_confirm=False,
            extra={
                "task_id": item.get("task_id", ""),
                "guid": item.get("guid", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "completed_at": item.get("completed_at", ""),
                "start": item.get("start", {}),
                "due": item.get("due", {}),
                "creator": item.get("creator", {}),
                "members": item.get("members", []),
                "tasklists": item.get("tasklists", []),
                "raw_payload": item,
            },
        )

    def create_task(
        self,
        summary: str,
        description: str = "",
        assignee_ids: list[str] | None = None,
        due_timestamp_ms: str = "",
        due_is_all_day: bool = False,
        tasklist_guid: str = "",
        idempotency_key: str = "",
        user_id_type: str = "open_id",
        identity: IdentityMode | None = None,
    ) -> ActionItem:
        """创建飞书任务，并转换为内部 `ActionItem`。

        对应接口：
        POST /open-apis/task/v2/tasks
        """

        payload = self.build_create_task_payload(
            summary=summary,
            description=description,
            assignee_ids=assignee_ids or [],
            due_timestamp_ms=due_timestamp_ms,
            due_is_all_day=due_is_all_day,
            tasklist_guid=tasklist_guid,
            idempotency_key=idempotency_key,
        )
        response_json = self._request(
            method="POST",
            path="task/v2/tasks",
            params={"user_id_type": user_id_type},
            payload=payload,
            identity=identity,
        )
        task_data = response_json.get("data", {}).get("task", {})
        if not isinstance(task_data, dict):
            raise FeishuAPIError("飞书任务创建成功，但返回体中缺少 task 对象")
        return self.to_action_item(task_data)

    def create_task_from_action_item(
        self,
        action_item: ActionItem,
        assignee_ids: list[str] | None = None,
        due_is_all_day: bool = False,
        tasklist_guid: str = "",
        idempotency_key: str = "",
        user_id_type: str = "open_id",
        identity: IdentityMode | None = None,
    ) -> ActionItem:
        """根据内部 `ActionItem` 创建飞书任务。

        这个方法服务于后续“会议 Action Item 自动落任务”的主链路。
        """

        description = str(action_item.extra.get("description", "") or "")
        return self.create_task(
            summary=action_item.title,
            description=description,
            assignee_ids=assignee_ids or [],
            due_timestamp_ms=action_item.due_date,
            due_is_all_day=due_is_all_day,
            tasklist_guid=tasklist_guid,
            idempotency_key=idempotency_key,
            user_id_type=user_id_type,
            identity=identity,
        )

    def build_create_task_payload(
        self,
        summary: str,
        description: str = "",
        assignee_ids: list[str] | None = None,
        due_timestamp_ms: str = "",
        due_is_all_day: bool = False,
        tasklist_guid: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """构造创建任务接口的请求体，供 dry-run 和真实创建复用。"""

        normalized_summary = summary.strip()
        if not normalized_summary:
            raise FeishuAPIError("任务标题 summary 不能为空")

        payload: dict[str, Any] = {
            "summary": normalized_summary,
        }
        if description:
            payload["description"] = description
        if idempotency_key:
            payload["client_token"] = idempotency_key
        if due_timestamp_ms:
            payload["due"] = {
                "timestamp": due_timestamp_ms,
                "is_all_day": due_is_all_day,
            }
        if tasklist_guid:
            payload["tasklists"] = [
                {
                    "tasklist_guid": tasklist_guid,
                }
            ]

        members = [
            {
                "id": assignee_id,
                "role": "assignee",
                "type": "user",
            }
            for assignee_id in (assignee_ids or [])
            if assignee_id
        ]
        if members:
            payload["members"] = members

        return payload

    def _extract_task_owner(self, item: dict[str, Any]) -> str:
        """从飞书任务成员里提取负责人名称。"""

        members = item.get("members", [])
        owners: list[str] = []
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, dict):
                    continue
                role = str(member.get("role", "") or "")
                # assignee 是负责人；某些任务只返回 editor，也作为备选负责人展示。
                if role not in {"assignee", "editor"}:
                    continue
                display_name = str(member.get("name", "") or member.get("id", "") or "")
                if display_name:
                    owners.append(display_name)

        if owners:
            return ", ".join(dict.fromkeys(owners))

        assignee_related = item.get("assignee_related", [])
        if isinstance(assignee_related, list):
            fallback_owners = [
                str(assignee.get("id", ""))
                for assignee in assignee_related
                if isinstance(assignee, dict) and assignee.get("id")
            ]
            if fallback_owners:
                return ", ".join(dict.fromkeys(fallback_owners))

        return ""

    def send_text_message(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
        idempotency_key: str = "",
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """发送飞书纯文本消息。

        对应接口：
        POST /open-apis/im/v1/messages?receive_id_type=...
        """

        content = {"text": text}
        return self.send_message(
            receive_id=receive_id,
            msg_type="text",
            content=content,
            receive_id_type=receive_id_type,
            idempotency_key=idempotency_key,
            identity=identity,
        )

    def send_card_message(
        self,
        receive_id: str,
        card: dict[str, Any],
        receive_id_type: str = "chat_id",
        idempotency_key: str = "",
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """发送飞书交互卡片消息。"""

        return self.send_message(
            receive_id=receive_id,
            msg_type="interactive",
            content=card,
            receive_id_type=receive_id_type,
            idempotency_key=idempotency_key,
            identity=identity,
        )

    def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: dict[str, Any],
        receive_id_type: str = "chat_id",
        idempotency_key: str = "",
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """发送飞书消息的底层封装。

        飞书消息接口要求 `content` 是 JSON 字符串，
        因此这里先由 Python 字典序列化，再交给 `_request()` 发送。
        """

        if receive_id_type not in {"chat_id", "open_id", "user_id", "union_id", "email"}:
            raise FeishuAPIError("receive_id_type 不合法，请使用 chat_id/open_id/user_id/union_id/email")
        if not receive_id:
            raise FeishuAPIError("receive_id 不能为空")
        if msg_type not in {
            "text",
            "post",
            "image",
            "file",
            "audio",
            "media",
            "interactive",
            "share_chat",
            "share_user",
        }:
            raise FeishuAPIError("msg_type 不合法")

        payload: dict[str, Any] = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        }
        if idempotency_key:
            payload["uuid"] = normalize_feishu_message_uuid(idempotency_key)

        # 注意：receive_id_type 是飞书消息接口的 query 参数，
        # 不是 body 字段；如果漏传，接口会返回 field validation failed。
        response_json = self._request(
            method="POST",
            path="im/v1/messages",
            params={"receive_id_type": receive_id_type},
            payload=payload,
            identity=identity,
        )
        return response_json.get("data", {})

    def build_meetflow_card(
        self,
        title: str,
        summary: str,
        facts: list[str] | None = None,
        action_text: str = "",
        action_url: str = "",
    ) -> dict[str, Any]:
        """构造一个 MeetFlow 通知卡片。

        当前模板用于 T2.6 测试和后续会前/风险卡片的雏形。
        后续如果需要更复杂的样式，可以迁移到 `cards/` 模板文件。
        """

        elements: list[dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": summary,
            }
        ]
        if facts:
            background_facts, link_facts = partition_card_facts(facts)
            if background_facts:
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**核心背景知识**\n" + "\n".join(f"- {fact}" for fact in background_facts),
                        },
                    }
                )
            if link_facts:
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**原始链接**\n" + "\n".join(f"- {fact}" for fact in link_facts),
                        },
                    }
                )

        if action_text and action_url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": action_text,
                            },
                            "type": "primary",
                            "url": action_url,
                        }
                    ],
                }
            )

        return {
            "config": {
                "wide_screen_mode": True,
            },
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": title,
                },
            },
            "elements": elements,
        }

    def _parse_oauth_token_bundle(self, response_json: dict[str, Any]) -> OAuthTokenBundle:
        """把 OAuth token 接口响应转换为统一结构。"""

        access_token = response_json.get("access_token", "")
        expires_in = int(response_json.get("expires_in", 0) or 0)
        refresh_token = response_json.get("refresh_token", "")
        refresh_token_expires_in = int(response_json.get("refresh_token_expires_in", 0) or 0)
        if not access_token or expires_in <= 0:
            raise FeishuAuthError("OAuth token 响应缺少 access_token 或 expires_in")

        now = int(time.time())
        return OAuthTokenBundle(
            access_token=access_token,
            expires_in=expires_in,
            access_token_expires_at=now + expires_in,
            refresh_token=refresh_token,
            refresh_token_expires_in=refresh_token_expires_in,
            refresh_token_expires_at=now + refresh_token_expires_in if refresh_token else 0,
            scope=response_json.get("scope", ""),
            token_type=response_json.get("token_type", ""),
            raw_payload=response_json,
        )

    def _apply_user_oauth_bundle(self, bundle: OAuthTokenBundle) -> None:
        """把最新的 OAuth token 结果应用到客户端实例上。"""

        self.user_token_cache = TokenCache(
            token=bundle.access_token,
            expires_at=float(bundle.access_token_expires_at),
        )
        self.user_refresh_token = bundle.refresh_token
        self.user_refresh_token_expires_at = bundle.refresh_token_expires_at

    def _notify_user_oauth_bundle(self, bundle: OAuthTokenBundle) -> None:
        """通知调用方 OAuth token 已更新。"""

        if not self.user_token_callback:
            return
        self.user_token_callback(bundle)

    def _parse_response_payload(
        self,
        response: requests.Response,
        url: str,
        method: str,
        allow_http_error_payload: bool = False,
    ) -> dict[str, Any]:
        """统一解析非 JSON API Helper 的原始 HTTP 响应。"""

        try:
            payload = response.json()
        except ValueError as error:
            raise FeishuAPIError(
                f"飞书接口返回了无法解析的 JSON method={method} url={url}"
            ) from error

        if not isinstance(payload, dict):
            raise FeishuAPIError(f"飞书接口返回结构异常 method={method} url={url}")

        if response.status_code >= 400 and not allow_http_error_payload:
            raise FeishuAPIError(
                "飞书接口 HTTP 错误 "
                f"method={method} "
                f"url={url} "
                f"http_status={response.status_code} "
                f"payload={payload}"
            )

        return payload

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        with_auth: bool = True,
        use_full_url: bool = False,
        identity: IdentityMode | None = None,
    ) -> dict[str, Any]:
        """底层请求入口。

        这里统一处理：
        - URL 拼接
        - 请求头
        - 网络错误重试
        - HTTP 状态码检查
        - 飞书业务 code 检查
        """

        url = path if use_full_url else self._build_url(path)
        headers = self._build_headers(with_auth=with_auth, identity=identity)

        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                self.logger.info(
                    "飞书请求开始 method=%s url=%s attempt=%s",
                    method,
                    url,
                    attempt + 1,
                )
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=payload,
                    headers=headers,
                    timeout=self.settings.request_timeout_seconds,
                )

                # 对限流和 5xx 错误做简单重试。
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.settings.max_retries:
                    self.logger.warning(
                        "飞书请求命中可重试状态码 status=%s attempt=%s",
                        response.status_code,
                        attempt + 1,
                    )
                    time.sleep(2**attempt)
                    continue

                # 先尽量解析 JSON，便于即使请求失败时也能拿到飞书返回的业务错误信息。
                try:
                    response_json = response.json()
                except ValueError:
                    response_json = None

                if response.status_code >= 400:
                    error_message = response.text
                    if isinstance(response_json, dict):
                        error_message = (
                            f"http_status={response.status_code} "
                            f"code={response_json.get('code')} "
                            f"msg={response_json.get('msg')} "
                            f"request_id={response_json.get('request_id')}"
                        )
                    raise FeishuAPIError(
                        f"飞书接口 HTTP 错误 method={method} url={url} detail={error_message}"
                    )

                if not isinstance(response_json, dict):
                    raise FeishuAPIError("飞书接口返回了非 JSON 对象，无法继续解析")

                code = response_json.get("code", 0)
                if code != 0:
                    message = response_json.get("msg", "unknown error")
                    error_description = response_json.get("error_description", "")
                    raise FeishuAPIError(
                        "飞书接口业务错误 "
                        f"code={code} "
                        f"msg={message} "
                        f"error_description={error_description}"
                    )

                return response_json
            except requests.RequestException as error:
                last_error = error
                if attempt >= self.settings.max_retries:
                    break
                self.logger.warning(
                    "飞书请求异常，准备重试 method=%s url=%s attempt=%s error=%s",
                    method,
                    url,
                    attempt + 1,
                    error,
                )
                time.sleep(2**attempt)
            except FeishuAPIError as error:
                last_error = error
                # 4xx 一般是参数问题、权限问题或数据问题，继续重试没有意义。
                raise
            except ValueError as error:
                # JSON 解析失败通常说明接口返回体异常，这类问题不适合重试太多次。
                raise FeishuAPIError(f"飞书接口返回了无法解析的 JSON: {error}") from error

        raise FeishuAPIError(f"飞书请求失败 method={method} url={url} error={last_error}") from last_error
