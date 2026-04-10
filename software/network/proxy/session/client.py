"""随机 IP 会话 HTTP 与代理提取辅助。"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS
from .models import RandomIPAuthError
from .normalize import _to_non_negative_int, _to_non_negative_quota


_LOG_BODY_PREVIEW_LIMIT = 320

_SENSITIVE_PREVIEW_PATTERNS = (
    (re.compile(r'("?(?:access_token|refresh_token|account|password)"?\s*:\s*")[^"]*(")', re.IGNORECASE), r"\1***\2"),
    (re.compile(r"(Authorization\s*:\s*Bearer\s+)[^\s]+", re.IGNORECASE), r"\1***"),
)


def _build_headers() -> Dict[str, str]:
    from .auth import get_device_id

    return {
        "Content-Type": "application/json",
        "X-Device-ID": get_device_id(),
        **DEFAULT_HTTP_HEADERS,
    }

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
        "%s attempt=%s status=%s detail=%s minute=%s pool=%s area=%s upstream=%s num=%s cf_ray=%s content_type=%s response=%s",
        message,
        int(attempt),
        status_code,
        detail,
        request_body.get("minute"),
        request_body.get("pool"),
        request_body.get("area", ""),
        request_body.get("upstream", ""),
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

def _post_json(url: str, *, json_body: Dict[str, Any]) -> Any:
    from .auth import _endpoint_name

    try:
        return http_client.post(
            url,
            json=json_body,
            headers=_build_headers(),
            timeout=10,
            proxies={},
        )
    except Exception as exc:
        logging.warning(
            "随机IP请求失败：endpoint=%s error=%s",
            _endpoint_name(url),
            exc,
        )
        raise RandomIPAuthError(f"network_error:{exc}") from exc

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

def _normalize_extract_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if provider in {"default", "idiot"}:
        return provider
    return ""

def _parse_single_extract_payload(
    data: Dict[str, Any],
    *,
    request_body: Dict[str, Any],
    attempt: int,
    response: Any,
) -> Dict[str, Any]:
    from .auth import _apply_quota_payload

    item = _extract_proxy_item(data)
    if item is None:
        _log_extract_proxy_issue("随机IP提取响应缺少 host/port/account/password", request_body=request_body, attempt=attempt, response=response)
        raise RandomIPAuthError("invalid_response")
    quota_cost = _to_non_negative_quota(data.get("quota_cost"), 0.0)
    session = _apply_quota_payload(data, log_context="随机IP提取响应")
    item.update(
        {
            "quota_cost": quota_cost,
            "remaining_quota": session.remaining_quota,
            "total_quota": session.total_quota,
            "used_quota": session.used_quota,
            "provider": _normalize_extract_provider(data.get("provider")),
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
    from .auth import _apply_quota_payload

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
    quota_cost_total = _to_non_negative_quota(data.get("quota_cost_total"), 0.0)
    session = _apply_quota_payload(data, log_context="随机IP批量提取响应")
    return {
        "items": items,
        "requested_count": requested_count,
        "returned_count": min(returned_count, len(items)),
        "remaining_quota": session.remaining_quota,
        "total_quota": session.total_quota,
        "used_quota": session.used_quota,
        "quota_cost_total": quota_cost_total,
        "provider": _normalize_extract_provider(data.get("provider")),
    }
