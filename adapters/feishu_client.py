from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any
from typing import Literal

import requests

from config import FeishuSettings
from core.logging import get_logger
from core.models import CalendarAttendee, CalendarEvent, CalendarInfo


class FeishuAPIError(RuntimeError):
    """飞书 API 通用异常。

    当接口返回非预期 HTTP 状态码，或者返回体中的业务 code 不为 0 时，
    都会抛出这个异常，方便上层统一处理。
    """


class FeishuAuthError(FeishuAPIError):
    """飞书鉴权异常。"""


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

    def __init__(self, settings: FeishuSettings) -> None:
        self.settings = settings
        self.logger = get_logger("meetflow.feishu")
        self.session = requests.Session()
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
