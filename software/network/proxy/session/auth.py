"""代理会话与随机 IP 账号管理。"""
from __future__ import annotations

import logging
import threading
import uuid
from urllib.parse import urlsplit
from dataclasses import replace
from typing import Any, Dict, List, Optional

from software.app.config import AUTH_BONUS_CLAIM_ENDPOINT, AUTH_TRIAL_ENDPOINT, IP_EXTRACT_ENDPOINT
from software.app.settings_store import app_settings
from software.logging.log_utils import log_suppressed_exception
from software.system.secure_store import read_secret, set_secret

from .client import (
    _extract_error_payload,
    _log_extract_proxy_issue,
    _parse_batch_extract_payload,
    _parse_single_extract_payload,
    _post_json,
)
from .models import RandomIPAuthError, RandomIPSession
from .normalize import (
    _build_quota_snapshot,
    _is_valid_user_id,
    _normalize_quota_known,
    _normalize_quota_state,
    _quota_equals,
    _require_valid_user_id,
    _resolve_quota_from_payload,
    _session_log_fields,
    _session_state_name,
    _to_non_negative_int,
    _to_non_negative_quota,
    _to_optional_bool,
    format_quota_value,
)

_SESSION_PREFIX = "random_ip_auth/"

_DEVICE_SECRET_KEY = "random_ip/device_id"

_SESSION_PERSIST_FAILED_DETAIL = "session_persist_failed"

_session_lock = threading.RLock()

_session_loaded = False

_session = RandomIPSession()


def _get_settings() -> Any:
    return app_settings()

def _settings_key(name: str) -> str:
    return f"{_SESSION_PREFIX}{name}"

def _has_complete_session(session: RandomIPSession) -> bool:
    return _is_valid_user_id(session.user_id)

def _log_session_event(level: int, message: str, session: Optional[RandomIPSession] = None, **fields: Any) -> None:
    parts = [message]
    if session is not None:
        parts.append(_session_log_fields(session))
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    logging.log(level, "随机IP会话：%s", " | ".join(parts))

def _endpoint_name(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    host = str(parsed.netloc or "").strip() or "-"
    path = str(parsed.path or "").strip() or "/"
    return f"{host}{path}"

def _ensure_loaded() -> None:
    global _session_loaded, _session
    with _session_lock:
        if _session_loaded:
            return
        settings = _get_settings()
        device_secret = read_secret(_DEVICE_SECRET_KEY)
        device_id = device_secret.value.strip()
        device_from = "secure_store"
        if not device_id:
            device_id = str(settings.value(_settings_key("device_id")) or "").strip()
            device_from = "settings" if device_id else "generated"
        if not device_id:
            device_id = uuid.uuid4().hex
            set_secret(_DEVICE_SECRET_KEY, device_id)
        loaded_user_id = _to_non_negative_int(settings.value(_settings_key("user_id")), 0)
        loaded_remaining_quota = _to_non_negative_quota(settings.value(_settings_key("remaining_quota")), 0.0)
        loaded_total_quota = _to_non_negative_quota(settings.value(_settings_key("total_quota")), loaded_remaining_quota)
        loaded_used_quota = _to_non_negative_quota(
            settings.value(_settings_key("used_quota")),
            max(0.0, loaded_total_quota - loaded_remaining_quota),
        )
        loaded_quota_known = _to_optional_bool(settings.value(_settings_key("quota_known")))
        normalized_remaining, normalized_total, normalized_used = _normalize_quota_state(
            remaining_quota=loaded_remaining_quota,
            total_quota=loaded_total_quota,
            used_quota=loaded_used_quota,
        )
        loaded_session = RandomIPSession(
            device_id=device_id,
            user_id=loaded_user_id,
            remaining_quota=normalized_remaining,
            total_quota=normalized_total,
            used_quota=normalized_used,
            quota_known=_normalize_quota_known(
                user_id=loaded_user_id,
                total_quota=normalized_total,
                used_quota=normalized_used,
                quota_known=loaded_quota_known,
            ),
        )
        _session = loaded_session
        _session_loaded = True
        log_level = logging.INFO
        if device_secret.status not in {"ok", "not_found"}:
            log_level = logging.WARNING
        _log_session_event(
            log_level,
            "启动加载完成",
            loaded_session,
            device_secret=device_secret.status,
            device_from=device_from,
            settings_user_id=loaded_user_id,
        )

def _persist_session_locked() -> None:
    settings = _get_settings()
    settings.setValue(_settings_key("device_id"), str(_session.device_id or "").strip())
    settings.setValue(_settings_key("user_id"), int(_session.user_id or 0))
    settings.setValue(_settings_key("remaining_quota"), format_quota_value(_session.remaining_quota))
    settings.setValue(_settings_key("total_quota"), format_quota_value(_session.total_quota))
    settings.setValue(_settings_key("used_quota"), format_quota_value(_session.used_quota))
    settings.setValue(_settings_key("quota_known"), bool(_session.quota_known))
    settings.sync()
    set_secret(_DEVICE_SECRET_KEY, _session.device_id)

def _verify_persisted_session(session: RandomIPSession) -> None:
    settings = _get_settings()
    failures: List[str] = []
    expected_device_id = str(session.device_id or "").strip()
    expected_user_id = int(session.user_id or 0)
    expected_remaining_quota = _to_non_negative_quota(session.remaining_quota, 0.0)
    expected_total_quota = _to_non_negative_quota(session.total_quota, 0.0)
    expected_used_quota = _to_non_negative_quota(session.used_quota, 0.0)
    expected_quota_known = bool(session.quota_known)

    persisted_device_id = str(settings.value(_settings_key("device_id")) or "").strip()
    if persisted_device_id != expected_device_id:
        failures.append("settings.device_id")

    persisted_user_id = _to_non_negative_int(settings.value(_settings_key("user_id")), -1)
    if persisted_user_id != expected_user_id:
        failures.append("settings.user_id")

    persisted_remaining_quota = _to_non_negative_quota(settings.value(_settings_key("remaining_quota")), -1.0)
    if not _quota_equals(persisted_remaining_quota, expected_remaining_quota):
        failures.append("settings.remaining_quota")

    persisted_total_quota = _to_non_negative_quota(settings.value(_settings_key("total_quota")), -1.0)
    if not _quota_equals(persisted_total_quota, expected_total_quota):
        failures.append("settings.total_quota")

    persisted_used_quota = _to_non_negative_quota(settings.value(_settings_key("used_quota")), -1.0)
    if not _quota_equals(persisted_used_quota, expected_used_quota):
        failures.append("settings.used_quota")

    persisted_quota_known = _to_optional_bool(settings.value(_settings_key("quota_known")))
    if persisted_quota_known is None or bool(persisted_quota_known) != expected_quota_known:
        failures.append("settings.quota_known")

    persisted_device_secret = read_secret(_DEVICE_SECRET_KEY)
    if persisted_device_secret.value.strip() != expected_device_id:
        failures.append(f"secure_store.device_id[{persisted_device_secret.status}]")

    if failures:
        logging.error("随机IP会话持久化校验失败：%s", ", ".join(failures))
        raise RandomIPAuthError(f"{_SESSION_PERSIST_FAILED_DETAIL}:{','.join(failures)}")

def _set_session(new_session: RandomIPSession, *, verify_auth_persistence: bool = False) -> RandomIPSession:
    global _session
    with _session_lock:
        _ensure_loaded()
        previous_session = _session
        normalized_remaining, normalized_total, normalized_used = _normalize_quota_state(
            remaining_quota=new_session.remaining_quota,
            total_quota=new_session.total_quota,
            used_quota=new_session.used_quota,
        )
        candidate = replace(
            new_session,
            remaining_quota=normalized_remaining,
            total_quota=normalized_total,
            used_quota=normalized_used,
            quota_known=_normalize_quota_known(
                user_id=new_session.user_id,
                total_quota=normalized_total,
                used_quota=normalized_used,
                quota_known=new_session.quota_known,
            ),
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

def get_device_id() -> str:
    return _read_session().device_id

def clear_session(*, reason: str = "unspecified") -> None:
    global _session
    with _session_lock:
        _ensure_loaded()
        previous_session = _session
        _session = RandomIPSession(device_id=_session.device_id)
        settings = _get_settings()
        settings.remove(_settings_key("user_id"))
        settings.remove(_settings_key("remaining_quota"))
        settings.remove(_settings_key("total_quota"))
        settings.remove(_settings_key("used_quota"))
        settings.remove(_settings_key("quota_known"))
        settings.sync()
        _log_session_event(logging.WARNING, "本地会话已清空", previous_session, reason=reason)

def has_authenticated_session() -> bool:
    session = _read_session()
    return _has_complete_session(session)

def get_session_snapshot() -> Dict[str, Any]:
    session = _read_session()
    quota = _build_quota_snapshot(session)
    return {
        "authenticated": _has_complete_session(session),
        "device_id": session.device_id,
        "user_id": int(session.user_id or 0),
        "remaining_quota": quota["remaining_quota"],
        "total_quota": quota["total_quota"],
        "used_quota": quota["used_quota"],
        "quota_known": bool(quota.get("quota_known")),
        "has_access_token": False,
        "has_refresh_token": False,
        "has_valid_user_id": _is_valid_user_id(session.user_id),
        "session_state": _session_state_name(session),
    }

def has_unknown_local_quota(snapshot: Optional[Dict[str, Any]] = None) -> bool:
    """判断本地已用/总额度缓存是否处于明显异常的未知状态。"""
    payload = snapshot if isinstance(snapshot, dict) else get_session_snapshot()
    if not bool(payload.get("authenticated")):
        return False
    if "quota_known" in payload:
        return not bool(payload.get("quota_known"))
    user_id = _to_non_negative_int(payload.get("user_id"), 0)
    total_quota = _to_non_negative_quota(payload.get("total_quota"), 0.0)
    used_quota = _to_non_negative_quota(payload.get("used_quota"), 0.0)
    return user_id > 0 and total_quota <= 0 and used_quota <= 0

def is_quota_exhausted(snapshot: Optional[Dict[str, Any]] = None) -> bool:
    payload = snapshot if isinstance(snapshot, dict) else get_session_snapshot()
    if not bool(payload.get("authenticated")):
        return False
    if "quota_known" in payload and not bool(payload.get("quota_known")):
        return False
    total_quota = _to_non_negative_quota(payload.get("total_quota"), 0.0)
    used_quota = _to_non_negative_quota(payload.get("used_quota"), 0.0)
    return total_quota > 0 and used_quota >= total_quota

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
    if detail == "trial_ip_rate_limited":
        return "当前网络领取试用过于频繁，请稍后再试"
    if detail == "trial_activate_failed":
        return "服务端创建试用账号失败，请稍后再试"
    if detail == "trial_rate_limited":
        if exc.retry_after_seconds > 0:
            return f"领取试用过于频繁，请 {exc.retry_after_seconds} 秒后再试"
        return "领取试用过于频繁，请稍后再试"
    if detail.startswith(_SESSION_PERSIST_FAILED_DETAIL):
        return "随机IP账号信息没能安全保存到本机，当前会话已停止使用。请重新领取试用或联系开发者。"
    if detail == "device_banned":
        return "当前设备已被封禁，请联系开发者"
    if detail == "user_banned":
        return "当前账号已被封禁，请联系开发者"
    if detail == "user_expired":
        return "随机IP账号已过期，请联系开发者补额度或重新开通"
    if detail == "device_owned_by_other_user":
        return "当前设备绑定的随机IP账号与本机记录不一致，请联系开发者处理"
    if detail == "user_id_required":
        return "本机缺少随机IP用户ID，请重新领取试用后再试"
    if detail == "invalid_user_id":
        return "本机保存的随机IP用户ID无效，请重新领取试用或联系开发者"
    if detail == "unauthorized":
        return "随机IP账号校验失败，请重新领取试用或联系开发者"
    if detail == "minute_not_allowed":
        return "代理时长参数不被后端接受，请更新客户端"
    if detail == "pool_not_allowed":
        return "代理池参数不被后端接受，请更新客户端"
    if detail == "area_not_allowed":
        return "地区参数不被后端接受，请更新客户端或检查地区配置"
    if detail == "invalid_area":
        return "指定地区无效，请重新选择地区后再试"
    if detail == "invalid_upstream":
        return "代理上游参数不被后端接受，请更新客户端"
    if detail == "minute_not_supported_for_idiot":
        return "限时福利代理源只支持 1 分钟代理，请切回默认代理源或缩短作答时长"
    if detail == "invalid_area_for_idiot":
        return "限时福利代理源的地区格式不正确，请重新选择具体城市后再试"
    if detail == "insufficient_quota":
        return "随机IP已用额度已达到上限，请先补充额度"
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
    if detail == "invalid_response:user_id_invalid":
        return "服务端返回了无效的随机IP用户ID，请稍后重试"
    if detail.startswith("invalid_response"):
        return "服务端返回格式异常，请稍后重试"
    if detail.startswith("http_"):
        return f"服务端暂时不可用（{detail[5:]}）"
    return detail or "请求失败，请稍后重试"

def _parse_session_payload(
    data: Dict[str, Any],
    *,
    device_id: str,
    fallback_session: Optional[RandomIPSession] = None,
) -> RandomIPSession:
    fallback = fallback_session or RandomIPSession(device_id=device_id)
    if "user_id" not in data:
        logging.warning("随机IP会话响应缺少 user_id：keys=%s", ",".join(sorted(str(k) for k in data.keys())))
        raise RandomIPAuthError("invalid_response:user_id_missing")
    raw_user_id = data.get("user_id")
    if not _is_valid_user_id(raw_user_id):
        logging.warning(
            "随机IP会话响应中的 user_id 无效：value=%r type=%s keys=%s",
            raw_user_id,
            type(raw_user_id).__name__,
            ",".join(sorted(str(k) for k in data.keys())),
        )
        raise RandomIPAuthError("invalid_response:user_id_invalid")
    normalized_remaining, normalized_total, normalized_used, quota_known = _resolve_quota_from_payload(
        data,
        fallback_session=fallback,
        log_context="随机IP会话响应",
    )
    session = RandomIPSession(
        device_id=device_id,
        user_id=_require_valid_user_id(raw_user_id),
        remaining_quota=normalized_remaining,
        total_quota=normalized_total,
        used_quota=normalized_used,
        quota_known=quota_known,
    )
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
    logging.info("随机IP试用领取开始：endpoint=%s", _endpoint_name(AUTH_TRIAL_ENDPOINT))
    response = _post_json(AUTH_TRIAL_ENDPOINT, json_body={})
    if int(getattr(response, "status_code", 0) or 0) != 200:
        error = _extract_error_payload(response)
        logging.warning(
            "随机IP试用领取失败：endpoint=%s status=%s detail=%s",
            _endpoint_name(AUTH_TRIAL_ENDPOINT),
            int(getattr(response, "status_code", 0) or 0),
            error.detail,
        )
        raise error
    session = _parse_session_response(response)
    try:
        persisted = _set_session(session, verify_auth_persistence=True)
        _log_session_event(logging.INFO, "试用领取成功并已保存", persisted)
        return persisted
    except RandomIPAuthError as exc:
        if exc.detail.startswith(_SESSION_PERSIST_FAILED_DETAIL):
            clear_session(reason="trial_persist_failed")
        logging.warning("随机IP试用领取后保存失败：detail=%s", exc.detail)
        raise

def _require_authenticated_session() -> RandomIPSession:
    session = _read_session()
    if _has_complete_session(session):
        return session
    raise RandomIPAuthError("not_authenticated")

def extract_proxy(*, minute: int, pool: str, area: Optional[str], num: int = 1, upstream: str = "default") -> Dict[str, Any]:
    session = _require_authenticated_session()
    body: Dict[str, Any] = {
        "user_id": int(session.user_id),
        "minute": int(minute),
        "pool": str(pool or "").strip(),
    }
    upstream_value = str(upstream or "").strip().lower()
    if upstream_value:
        body["upstream"] = upstream_value
    request_num = max(1, int(num or 1))
    if request_num > 1:
        body["num"] = request_num
    area_code = str(area or "").strip()
    if area_code:
        body["area"] = area_code

    try:
        response = _post_json(IP_EXTRACT_ENDPOINT, json_body=body)
    except RandomIPAuthError as exc:
        _log_extract_proxy_issue("随机IP提取请求异常", request_body=body, attempt=1, error=exc)
        raise
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 200:
        try:
            data = response.json()
        except Exception as exc:
            _log_extract_proxy_issue("随机IP提取响应解析失败", request_body=body, attempt=1, response=response, error=exc)
            raise RandomIPAuthError(f"invalid_response:{exc}") from exc
        if not isinstance(data, dict):
            _log_extract_proxy_issue("随机IP提取响应结构异常", request_body=body, attempt=1, response=response)
            raise RandomIPAuthError("invalid_response")
        if request_num > 1 and isinstance(data.get("items"), list):
            return _parse_batch_extract_payload(
                data,
                request_body=body,
                attempt=1,
                response=response,
            )
        return _parse_single_extract_payload(
            data,
            request_body=body,
            attempt=1,
            response=response,
        )
    error = _extract_error_payload(response)
    _log_extract_proxy_issue("随机IP提取失败", request_body=body, attempt=1, response=response, error=error)
    raise error

def get_quota_snapshot() -> Dict[str, Any]:
    return _build_quota_snapshot(_read_session())

def get_fresh_quota_snapshot() -> Dict[str, Any]:
    return _build_quota_snapshot(_require_authenticated_session())

def sync_quota_snapshot_from_server(*, emit_logs: bool = True) -> Dict[str, Any]:
    session = _require_authenticated_session()
    if emit_logs:
        logging.info(
            "随机IP额度服务端同步开始：endpoint=%s user_id=%s",
            _endpoint_name(AUTH_TRIAL_ENDPOINT),
            int(session.user_id or 0),
        )
    response = _post_json(AUTH_TRIAL_ENDPOINT, json_body={})
    if int(getattr(response, "status_code", 0) or 0) != 200:
        error = _extract_error_payload(response)
        if emit_logs:
            logging.warning(
                "随机IP额度服务端同步失败：endpoint=%s status=%s detail=%s",
                _endpoint_name(AUTH_TRIAL_ENDPOINT),
                int(getattr(response, "status_code", 0) or 0),
                error.detail,
            )
        raise error
    refreshed = _parse_session_response(response, fallback_session=session)
    persisted = _set_session(refreshed, verify_auth_persistence=True)
    if emit_logs:
        _log_session_event(logging.INFO, "随机IP额度已与服务端同步", persisted)
    return _build_quota_snapshot(persisted)

def _apply_quota_payload(data: Dict[str, Any], *, log_context: str = "随机IP额度响应") -> RandomIPSession:
    session = _read_session()
    normalized_remaining, normalized_total, normalized_used, quota_known = _resolve_quota_from_payload(
        data,
        fallback_session=session,
        log_context=log_context,
    )
    updated = replace(
        session,
        remaining_quota=normalized_remaining,
        total_quota=normalized_total,
        used_quota=normalized_used,
        quota_known=quota_known,
    )
    return _set_session(updated)

def claim_easter_egg_bonus() -> Dict[str, Any]:
    session = _require_authenticated_session()
    response = _post_json(
        AUTH_BONUS_CLAIM_ENDPOINT,
        json_body={
            "user_id": int(session.user_id),
            "bonus_code": "fuck-you-hacker",
        },
    )
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise _extract_error_payload(response)
    try:
        data = response.json()
    except Exception as exc:
        raise RandomIPAuthError(f"invalid_response:{exc}") from exc
    if not isinstance(data, dict):
        raise RandomIPAuthError("invalid_response")

    session = _apply_quota_payload(data, log_context="随机IP彩蛋额度响应")
    claimed = bool(data.get("claimed", False))
    bonus_quota = _to_non_negative_quota(data.get("bonus_quota"), 0.0)
    detail = str(data.get("detail") or "").strip()
    return {
        "claimed": claimed,
        "bonus_quota": bonus_quota,
        "detail": detail,
        "used_quota": session.used_quota,
        "remaining_quota": session.remaining_quota,
        "total_quota": session.total_quota,
    }

def load_session_for_startup() -> None:
    try:
        _ensure_loaded()
    except Exception as exc:
        log_suppressed_exception("auth.load_session_for_startup", exc, level=logging.WARNING)
