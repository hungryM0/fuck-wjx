"""随机 IP 鉴权与会话管理。"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSettings

import wjx.network.http_client as http_client
from wjx.utils.app.config import (
    AUTH_BONUS_CLAIM_ENDPOINT,
    AUTH_REFRESH_ENDPOINT,
    AUTH_TRIAL_ENDPOINT,
    DEFAULT_HTTP_HEADERS,
    IP_EXTRACT_ENDPOINT,
)
from wjx.utils.logging.log_utils import log_suppressed_exception
from wjx.utils.system.secure_store import delete_secret, get_secret, set_secret

_SETTINGS_ORG = "FuckWjx"
_SETTINGS_APP = "Settings"
_SESSION_PREFIX = "random_ip_auth/"
_DEVICE_SECRET_KEY = "random_ip/device_id"
_REFRESH_SECRET_KEY = "random_ip/refresh_token"
_TOKEN_EARLY_REFRESH_SECONDS = 60
_LOG_BODY_PREVIEW_LIMIT = 320
_REFRESH_PERSIST_FAILED_DETAIL = "refresh_token_persist_failed"
_SENSITIVE_PREVIEW_PATTERNS = (
    (re.compile(r'("?(?:access_token|refresh_token|account|password)"?\s*:\s*")[^"]*(")', re.IGNORECASE), r"\1***\2"),
    (re.compile(r"(Authorization\s*:\s*Bearer\s+)[^\s]+", re.IGNORECASE), r"\1***"),
)
_QUOTA_SETTING_KEYS = ("remaining_quota", "total_quota")


class RandomIPAuthError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 0, retry_after_seconds: int = 0):
        self.detail = str(detail or "unknown_error")
        self.status_code = int(status_code or 0)
        self.retry_after_seconds = max(0, int(retry_after_seconds or 0))
        super().__init__(self.detail)


@dataclass(frozen=True)
class RandomIPSession:
    device_id: str = ""
    user_id: int = 0
    access_token: str = ""
    refresh_token: str = ""
    expires_at: Optional[datetime] = None
    refresh_expires_at: Optional[datetime] = None
    remaining_quota: int = 0
    total_quota: int = 0

    @property
    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token and self.refresh_expires_at and self.refresh_expires_at > _utc_now())

    @property
    def has_access_token(self) -> bool:
        return bool(self.access_token and self.expires_at and self.expires_at > _utc_now())


_session_lock = threading.RLock()
_session_loaded = False
_session = RandomIPSession()
_refresh_singleflight_lock = threading.Lock()
_refresh_singleflight_cond = threading.Condition(_refresh_singleflight_lock)
_refresh_in_flight = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _settings_key(name: str) -> str:
    return f"{_SESSION_PREFIX}{name}"


def _clear_persisted_quota_settings(settings: Optional[QSettings] = None) -> None:
    target = settings or _get_settings()
    for key in _QUOTA_SETTING_KEYS:
        target.remove(_settings_key(key))
    target.sync()


def _parse_datetime(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(0, int(default))
    return max(0, parsed)


def _ensure_loaded() -> None:
    global _session_loaded, _session
    with _session_lock:
        if _session_loaded:
            return
        settings = _get_settings()
        device_id = get_secret(_DEVICE_SECRET_KEY).strip()
        if not device_id:
            device_id = str(settings.value(_settings_key("device_id")) or "").strip()
        if not device_id:
            device_id = uuid.uuid4().hex
            set_secret(_DEVICE_SECRET_KEY, device_id)
        refresh_token = get_secret(_REFRESH_SECRET_KEY).strip()
        refresh_expires_at = _parse_datetime(settings.value(_settings_key("refresh_expires_at")))
        if refresh_token and refresh_expires_at and refresh_expires_at <= _utc_now():
            refresh_token = ""
            refresh_expires_at = None
            delete_secret(_REFRESH_SECRET_KEY)
        _clear_persisted_quota_settings(settings)
        _session = RandomIPSession(
            device_id=device_id,
            user_id=_to_non_negative_int(settings.value(_settings_key("user_id")), 0),
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
            remaining_quota=0,
            total_quota=0,
        )
        _session_loaded = True


def _persist_session_locked() -> None:
    settings = _get_settings()
    settings.setValue(_settings_key("device_id"), str(_session.device_id or "").strip())
    settings.setValue(_settings_key("user_id"), int(_session.user_id or 0))
    settings.setValue(_settings_key("refresh_expires_at"), _serialize_datetime(_session.refresh_expires_at))
    for key in _QUOTA_SETTING_KEYS:
        settings.remove(_settings_key(key))
    settings.sync()
    set_secret(_DEVICE_SECRET_KEY, _session.device_id)
    set_secret(_REFRESH_SECRET_KEY, _session.refresh_token)


def _verify_persisted_session(session: RandomIPSession) -> None:
    settings = _get_settings()
    failures: List[str] = []
    expected_device_id = str(session.device_id or "").strip()
    expected_user_id = int(session.user_id or 0)
    expected_refresh_expires_at = _serialize_datetime(session.refresh_expires_at)
    expected_refresh_token = str(session.refresh_token or "").strip()

    persisted_device_id = str(settings.value(_settings_key("device_id")) or "").strip()
    if persisted_device_id != expected_device_id:
        failures.append("settings.device_id")

    persisted_user_id = _to_non_negative_int(settings.value(_settings_key("user_id")), -1)
    if persisted_user_id != expected_user_id:
        failures.append("settings.user_id")

    persisted_refresh_expires_at = _serialize_datetime(_parse_datetime(settings.value(_settings_key("refresh_expires_at"))))
    if persisted_refresh_expires_at != expected_refresh_expires_at:
        failures.append("settings.refresh_expires_at")

    if get_secret(_DEVICE_SECRET_KEY).strip() != expected_device_id:
        failures.append("secure_store.device_id")

    if get_secret(_REFRESH_SECRET_KEY).strip() != expected_refresh_token:
        failures.append("secure_store.refresh_token")

    if failures:
        logging.error("随机IP会话持久化校验失败：%s", ", ".join(failures))
        raise RandomIPAuthError(f"{_REFRESH_PERSIST_FAILED_DETAIL}:{','.join(failures)}")


def _set_session(new_session: RandomIPSession, *, verify_auth_persistence: bool = False) -> RandomIPSession:
    global _session
    with _session_lock:
        _ensure_loaded()
        previous_session = _session
        candidate = replace(
            new_session,
            total_quota=max(int(new_session.total_quota or 0), int(new_session.remaining_quota or 0)),
            remaining_quota=max(0, int(new_session.remaining_quota or 0)),
        )
        _session = candidate
        try:
            _persist_session_locked()
            if verify_auth_persistence:
                _verify_persisted_session(candidate)
            return _session
        except Exception:
            _session = previous_session
            raise


def _read_session() -> RandomIPSession:
    _ensure_loaded()
    with _session_lock:
        return replace(_session)


def _update_quota(remaining_quota: int, total_hint: Optional[int] = None) -> RandomIPSession:
    global _session
    with _session_lock:
        _ensure_loaded()
        total_quota = int(_session.total_quota or 0)
        if total_hint is not None:
            total_quota = max(total_quota, int(total_hint))
        total_quota = max(total_quota, int(remaining_quota))
        session = replace(
            _session,
            remaining_quota=max(0, int(remaining_quota)),
            total_quota=total_quota,
        )
        _session = session
        _persist_session_locked()
        return replace(session)


def get_device_id() -> str:
    return _read_session().device_id


def clear_session() -> None:
    global _session
    with _session_lock:
        _ensure_loaded()
        _session = RandomIPSession(device_id=_session.device_id)
        delete_secret(_REFRESH_SECRET_KEY)
        settings = _get_settings()
        settings.remove(_settings_key("user_id"))
        settings.remove(_settings_key("refresh_expires_at"))
        for key in _QUOTA_SETTING_KEYS:
            settings.remove(_settings_key(key))
        settings.sync()


def has_authenticated_session() -> bool:
    session = _read_session()
    return bool(session.has_refresh_token or session.has_access_token)


def get_session_snapshot() -> Dict[str, Any]:
    session = _read_session()
    return {
        "authenticated": bool(session.has_refresh_token or session.has_access_token),
        "device_id": session.device_id,
        "user_id": int(session.user_id or 0),
        "remaining_quota": int(session.remaining_quota),
        "total_quota": int(session.total_quota),
        "has_access_token": bool(session.has_access_token),
        "has_refresh_token": bool(session.has_refresh_token),
    }


def _build_quota_snapshot(session: RandomIPSession) -> Dict[str, int]:
    total_quota = max(0, int(session.total_quota or 0))
    remaining_quota = max(0, int(session.remaining_quota or 0))
    used_quota = max(0, total_quota - remaining_quota)
    return {
        "used_quota": used_quota,
        "total_quota": total_quota,
        "remaining_quota": remaining_quota,
    }


def format_random_ip_error(exc: BaseException) -> str:
    if not isinstance(exc, RandomIPAuthError):
        return str(exc or "请求失败，请稍后重试")
    detail = exc.detail
    if detail in {"bonus_already_claimed", "easter_egg_already_claimed"}:
        return "彩蛋已触发，无需重复领取"
    if detail in {"bonus_claim_not_available", "easter_egg_not_available"}:
        return "当前暂时无法领取彩蛋奖励，请稍后再试"
    if detail == "device_id_required":
        return "设备标识缺失，请重启软件后重试"
    if detail == "invalid_request_body":
        return "请求格式不正确，请更新客户端后重试"
    if detail in {"trial_already_claimed", "trial_already_used", "device_trial_already_claimed"}:
        return "当前设备已领取过免费试用，请前往申请随机IP额度"
    if detail == "trial_rate_limited":
        if exc.retry_after_seconds > 0:
            return f"领取试用过于频繁，请 {exc.retry_after_seconds} 秒后再试"
        return "领取试用过于频繁，请稍后再试"
    if detail == "invalid_refresh_token":
        return "登录状态已失效，请重新领取试用或申请随机IP额度"
    if detail.startswith(_REFRESH_PERSIST_FAILED_DETAIL):
        return "登录状态刷新后未能安全保存到本机，已停止继续使用随机IP，请重新领取试用或申请随机IP额度"
    if detail == "device_banned":
        return "当前设备已被封禁，请联系开发者"
    if detail == "user_banned":
        return "当前账号已被封禁，请联系开发者"
    if detail == "unauthorized":
        return "随机IP登录状态失效，请重新领取试用或申请随机IP额度"
    if detail == "minute_not_allowed":
        return "代理时长参数不被后端接受，请更新客户端"
    if detail == "pool_not_allowed":
        return "代理池参数不被后端接受，请更新客户端"
    if detail == "area_not_allowed":
        return "地区参数不被后端接受，请更新客户端或检查地区配置"
    if detail == "invalid_area":
        return "指定地区无效，请重新选择地区后再试"
    if detail == "insufficient_quota":
        return "随机IP额度不足，请先补充额度"
    if detail == "token_rate_limited":
        return "当前账号请求过于频繁，请稍后再试"
    if detail == "device_rate_limited":
        return "当前设备请求过于频繁，请稍后再试"
    if detail == "ip_rate_limited":
        return "当前网络请求过于频繁，请稍后再试"
    if detail == "user_daily_limit_exceeded":
        return "今日随机IP额度已达到上限"
    if detail == "site_daily_limit_exceeded":
        return "服务端今日额度已达上限，请稍后再试"
    if detail == "upstream_surplus_exhausted":
        return "上游代理余额不足，请稍后再试"
    if detail == "upstream_rejected":
        return "上游代理服务拒绝了请求，请稍后重试"
    if detail == "not_authenticated":
        return "请先领取免费试用或提交额度申请后再使用随机IP"
    if detail.startswith("network_error:"):
        return f"网络请求失败：{detail.split(':', 1)[1].strip()}"
    if detail.startswith("invalid_response"):
        return "服务端返回格式异常，请稍后重试"
    if detail.startswith("http_"):
        return f"服务端暂时不可用（{detail[5:]}）"
    return detail or "请求失败，请稍后重试"


def _build_headers(*, authorized: bool = False, access_token: str = "") -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Device-ID": get_device_id(),
        **DEFAULT_HTTP_HEADERS,
    }
    if authorized and access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _preview_text(value: Any, *, limit: int = _LOG_BODY_PREVIEW_LIMIT) -> str:
    text = str(value or "").strip()
    if not text:
        return "<empty>"
    for pattern, replacement in _SENSITIVE_PREVIEW_PATTERNS:
        text = pattern.sub(replacement, text)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > limit:
        return f"{text[:limit]}...(truncated)"
    return text


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    return str(headers.get("Content-Type") or headers.get("content-type") or "").strip()


def _response_header_value(response: Any, header_name: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    return str(headers.get(header_name) or headers.get(str(header_name).lower()) or "").strip()


def _response_body_preview(response: Any) -> str:
    try:
        return _preview_text(getattr(response, "text", ""))
    except Exception as exc:
        return f"<unavailable:{exc}>"


def _log_extract_proxy_issue(
    message: str,
    *,
    request_body: Dict[str, Any],
    attempt: int,
    response: Any = None,
    error: Optional[BaseException] = None,
) -> None:
    status_code = int(getattr(response, "status_code", 0) or 0) if response is not None else 0
    detail = ""
    if isinstance(error, RandomIPAuthError):
        detail = error.detail
    elif error is not None:
        detail = str(error)
    logging.warning(
        "%s attempt=%s status=%s detail=%s minute=%s pool=%s area=%s num=%s cf_ray=%s content_type=%s response=%s",
        message,
        int(attempt),
        status_code,
        detail,
        request_body.get("minute"),
        request_body.get("pool"),
        request_body.get("area", ""),
        request_body.get("num", 1),
        _response_header_value(response, "CF-RAY") if response is not None else "",
        _response_content_type(response) if response is not None else "",
        _response_body_preview(response) if response is not None else "<no-response>",
    )


def _extract_error_payload(response: Any) -> RandomIPAuthError:
    retry_after = 0
    headers = getattr(response, "headers", {}) or {}
    try:
        retry_after = int(headers.get("Retry-After") or 0)
    except Exception:
        retry_after = 0
    detail = ""
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = str(payload.get("detail") or "").strip()
        retry_after = max(retry_after, _to_non_negative_int(payload.get("retry_after_seconds"), retry_after))
    if not detail:
        detail = f"http_{getattr(response, 'status_code', 0) or 0}"
    return RandomIPAuthError(detail, status_code=int(getattr(response, "status_code", 0) or 0), retry_after_seconds=retry_after)


def _post_json(url: str, *, json_body: Dict[str, Any], authorized: bool = False, access_token: str = "") -> Any:
    try:
        return http_client.post(
            url,
            json=json_body,
            headers=_build_headers(authorized=authorized, access_token=access_token),
            timeout=10,
            proxies={},
        )
    except Exception as exc:
        raise RandomIPAuthError(f"network_error:{exc}") from exc


def _parse_session_payload(
    data: Dict[str, Any],
    *,
    device_id: str,
    fallback_session: Optional[RandomIPSession] = None,
) -> RandomIPSession:
    fallback = fallback_session or RandomIPSession(device_id=device_id)
    if "user_id" not in data:
        raise RandomIPAuthError("invalid_response:user_id_missing")
    session = RandomIPSession(
        device_id=device_id,
        user_id=_to_non_negative_int(data.get("user_id"), 0),
        access_token=str(data.get("access_token") or "").strip(),
        refresh_token=str(data.get("refresh_token") or "").strip(),
        expires_at=_parse_datetime(data.get("expires_at")),
        refresh_expires_at=_parse_datetime(data.get("refresh_expires_at")),
        remaining_quota=_to_non_negative_int(data.get("remaining_quota"), fallback.remaining_quota),
        total_quota=max(
            _to_non_negative_int(data.get("total_quota"), fallback.total_quota),
            _to_non_negative_int(data.get("remaining_quota"), fallback.remaining_quota),
        ),
    )
    if not session.refresh_token:
        raise RandomIPAuthError("invalid_response")
    return session


def _parse_session_response(response: Any, *, fallback_session: Optional[RandomIPSession] = None) -> RandomIPSession:
    try:
        data = response.json()
    except Exception as exc:
        raise RandomIPAuthError(f"invalid_response:{exc}") from exc
    if not isinstance(data, dict):
        raise RandomIPAuthError("invalid_response")
    device_id = fallback_session.device_id if fallback_session is not None else get_device_id()
    return _parse_session_payload(data, device_id=device_id, fallback_session=fallback_session)


def activate_trial() -> RandomIPSession:
    response = _post_json(AUTH_TRIAL_ENDPOINT, json_body={})
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise _extract_error_payload(response)
    session = _parse_session_response(response)
    try:
        return _set_session(session, verify_auth_persistence=True)
    except RandomIPAuthError as exc:
        if exc.detail.startswith(_REFRESH_PERSIST_FAILED_DETAIL):
            clear_session()
        raise


def _should_refresh(session: RandomIPSession, *, force: bool = False) -> bool:
    if force or not session.access_token or session.expires_at is None:
        return True
    return session.expires_at <= (_utc_now() + timedelta(seconds=_TOKEN_EARLY_REFRESH_SECONDS))


def _session_refresh_marker(session: RandomIPSession) -> tuple[str, str, str, str]:
    return (
        str(session.refresh_token or ""),
        str(session.access_token or ""),
        _serialize_datetime(session.expires_at),
        _serialize_datetime(session.refresh_expires_at),
    )


def refresh_session(*, force: bool = False) -> RandomIPSession:
    global _refresh_in_flight

    while True:
        session = _read_session()
        if not session.has_refresh_token:
            raise RandomIPAuthError("not_authenticated")
        if not _should_refresh(session, force=force):
            return session

        refresh_marker = _session_refresh_marker(session)
        became_refresher = False

        with _refresh_singleflight_cond:
            while _refresh_in_flight:
                _refresh_singleflight_cond.wait()
                latest = _read_session()
                if _session_refresh_marker(latest) != refresh_marker:
                    if latest.has_refresh_token:
                        return latest
                    raise RandomIPAuthError("not_authenticated")

            latest = _read_session()
            if _session_refresh_marker(latest) != refresh_marker:
                if latest.has_refresh_token:
                    return latest
                raise RandomIPAuthError("not_authenticated")

            _refresh_in_flight = True
            became_refresher = True

        if not became_refresher:
            continue

        try:
            response = _post_json(
                AUTH_REFRESH_ENDPOINT,
                json_body={"refresh_token": session.refresh_token},
                authorized=False,
            )
            if int(getattr(response, "status_code", 0) or 0) != 200:
                error = _extract_error_payload(response)
                if error.detail == "invalid_refresh_token":
                    clear_session()
                raise error
            refreshed = _parse_session_response(response, fallback_session=session)
            try:
                return _set_session(refreshed, verify_auth_persistence=True)
            except RandomIPAuthError as exc:
                if exc.detail.startswith(_REFRESH_PERSIST_FAILED_DETAIL):
                    clear_session()
                raise
        finally:
            with _refresh_singleflight_cond:
                _refresh_in_flight = False
                _refresh_singleflight_cond.notify_all()


def ensure_access_token() -> str:
    session = refresh_session(force=False)
    if session.has_access_token:
        return session.access_token
    refreshed = refresh_session(force=True)
    if not refreshed.access_token:
        raise RandomIPAuthError("unauthorized")
    return refreshed.access_token


def update_remaining_quota(remaining_quota: int, *, total_hint: Optional[int] = None) -> RandomIPSession:
    return _update_quota(max(0, int(remaining_quota or 0)), total_hint=total_hint)


def _extract_proxy_item(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    host = str(data.get("host") or "").strip()
    port = _to_non_negative_int(data.get("port"), 0)
    account = str(data.get("account") or "").strip()
    password = str(data.get("password") or "").strip()
    if not host or port <= 0 or not account or not password:
        return None
    return {
        "host": host,
        "port": port,
        "account": account,
        "password": password,
        "expire_at": str(data.get("expire_at") or "").strip(),
    }


def _parse_single_extract_payload(
    data: Dict[str, Any],
    *,
    request_body: Dict[str, Any],
    attempt: int,
    response: Any,
) -> Dict[str, Any]:
    item = _extract_proxy_item(data)
    if item is None:
        _log_extract_proxy_issue("随机IP提取响应缺少 host/port/account/password", request_body=request_body, attempt=attempt, response=response)
        raise RandomIPAuthError("invalid_response")
    remaining_quota = _to_non_negative_int(data.get("remaining_quota"), 0)
    quota_cost = _to_non_negative_int(data.get("quota_cost"), 0)
    total_quota = _to_non_negative_int(data.get("total_quota"), remaining_quota + quota_cost)
    update_remaining_quota(remaining_quota, total_hint=total_quota)
    item.update(
        {
            "quota_cost": quota_cost,
            "remaining_quota": remaining_quota,
            "total_quota": total_quota,
        }
    )
    return item


def _parse_batch_extract_payload(
    data: Dict[str, Any],
    *,
    request_body: Dict[str, Any],
    attempt: int,
    response: Any,
) -> Dict[str, Any]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        _log_extract_proxy_issue("随机IP批量提取响应缺少 items", request_body=request_body, attempt=attempt, response=response)
        raise RandomIPAuthError("invalid_response")

    items: List[Dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = _extract_proxy_item(raw)
        if item is not None:
            items.append(item)
    if not items:
        _log_extract_proxy_issue("随机IP批量提取响应中无有效 IP", request_body=request_body, attempt=attempt, response=response)
        raise RandomIPAuthError("invalid_response")

    returned_count = max(1, _to_non_negative_int(data.get("returned_count"), len(items)))
    requested_count = max(1, _to_non_negative_int(data.get("requested_count"), request_body.get("num", 1)))
    quota_cost_total = _to_non_negative_int(data.get("quota_cost_total"), 0)
    remaining_quota = _to_non_negative_int(data.get("remaining_quota"), 0)
    total_quota = _to_non_negative_int(data.get("total_quota"), remaining_quota + quota_cost_total)
    update_remaining_quota(remaining_quota, total_hint=total_quota)
    return {
        "items": items,
        "requested_count": requested_count,
        "returned_count": min(returned_count, len(items)),
        "remaining_quota": remaining_quota,
        "total_quota": total_quota,
        "quota_cost_total": quota_cost_total,
    }


def extract_proxy(*, minute: int, pool: str, area: Optional[str], num: int = 1) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "minute": int(minute),
        "pool": str(pool or "").strip(),
    }
    request_num = max(1, int(num or 1))
    if request_num > 1:
        body["num"] = request_num
    area_code = str(area or "").strip()
    if area_code:
        body["area"] = area_code

    last_error: Optional[RandomIPAuthError] = None
    for attempt in range(2):
        access_token = ensure_access_token()
        try:
            response = _post_json(
                IP_EXTRACT_ENDPOINT,
                json_body=body,
                authorized=True,
                access_token=access_token,
            )
        except RandomIPAuthError as exc:
            _log_extract_proxy_issue("随机IP提取请求异常", request_body=body, attempt=attempt + 1, error=exc)
            raise
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 200:
            try:
                data = response.json()
            except Exception as exc:
                _log_extract_proxy_issue("随机IP提取响应解析失败", request_body=body, attempt=attempt + 1, response=response, error=exc)
                raise RandomIPAuthError(f"invalid_response:{exc}") from exc
            if not isinstance(data, dict):
                _log_extract_proxy_issue("随机IP提取响应结构异常", request_body=body, attempt=attempt + 1, response=response)
                raise RandomIPAuthError("invalid_response")
            if request_num > 1 and isinstance(data.get("items"), list):
                return _parse_batch_extract_payload(
                    data,
                    request_body=body,
                    attempt=attempt + 1,
                    response=response,
                )
            return _parse_single_extract_payload(
                data,
                request_body=body,
                attempt=attempt + 1,
                response=response,
            )
        error = _extract_error_payload(response)
        last_error = error
        _log_extract_proxy_issue("随机IP提取失败", request_body=body, attempt=attempt + 1, response=response, error=error)
        if error.detail == "unauthorized" and attempt == 0:
            refresh_session(force=True)
            continue
        raise error
    raise last_error or RandomIPAuthError("unauthorized")


def get_quota_snapshot() -> Dict[str, int]:
    return _build_quota_snapshot(_read_session())


def get_fresh_quota_snapshot() -> Dict[str, int]:
    return _build_quota_snapshot(refresh_session(force=True))


def _apply_quota_payload(data: Dict[str, Any]) -> RandomIPSession:
    session = _read_session()
    remaining_quota = _to_non_negative_int(data.get("remaining_quota"), session.remaining_quota)
    total_quota = _to_non_negative_int(data.get("total_quota"), session.total_quota)
    updated = replace(
        session,
        remaining_quota=remaining_quota,
        total_quota=max(total_quota, remaining_quota),
    )
    return _set_session(updated)


def claim_easter_egg_bonus() -> Dict[str, Any]:
    access_token = ensure_access_token()
    response = _post_json(
        AUTH_BONUS_CLAIM_ENDPOINT,
        json_body={"bonus_code": "fuck-you-hacker"},
        authorized=True,
        access_token=access_token,
    )
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise _extract_error_payload(response)
    try:
        data = response.json()
    except Exception as exc:
        raise RandomIPAuthError(f"invalid_response:{exc}") from exc
    if not isinstance(data, dict):
        raise RandomIPAuthError("invalid_response")

    session = _apply_quota_payload(data)
    claimed = bool(data.get("claimed", False))
    bonus_quota = _to_non_negative_int(data.get("bonus_quota"), 0)
    detail = str(data.get("detail") or "").strip()
    return {
        "claimed": claimed,
        "bonus_quota": bonus_quota,
        "detail": detail,
        "remaining_quota": int(session.remaining_quota),
        "total_quota": int(session.total_quota),
    }


def load_session_for_startup() -> None:
    try:
        _ensure_loaded()
    except Exception as exc:
        log_suppressed_exception("auth.load_session_for_startup", exc, level=logging.WARNING)
