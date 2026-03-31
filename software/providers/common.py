"""问卷平台识别与元数据补全。"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

SURVEY_PROVIDER_WJX = "wjx"
SURVEY_PROVIDER_QQ = "qq"
SUPPORTED_SURVEY_PROVIDERS = {SURVEY_PROVIDER_WJX, SURVEY_PROVIDER_QQ}

_WJX_ALLOWED_HOSTS = ("wjx.top", "wjx.cn", "wjx.com")
_WJX_SURVEY_HOSTS = ("v.wjx.cn", "www.wjx.cn")
_QQ_ALLOWED_HOST = "wj.qq.com"
_QQ_SURVEY_PATH_RE = re.compile(r"^/s\d+/\d+/[A-Za-z0-9_-]+/?$", re.IGNORECASE)


def normalize_survey_provider(value: Any, default: str = SURVEY_PROVIDER_WJX) -> str:
    try:
        provider = str(value or "").strip().lower()
    except Exception:
        provider = ""
    return provider if provider in SUPPORTED_SURVEY_PROVIDERS else str(default or SURVEY_PROVIDER_WJX)


def _parse_url_host(url_value: str) -> tuple[str, str]:
    text = str(url_value or "").strip()
    if not text:
        return "", ""
    candidate = text if "://" in text else f"https://{text}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return "", ""
    host = (parsed.netloc or "").split(":", 1)[0].lower()
    path = str(parsed.path or "").strip()
    return host, path


def is_wjx_domain(url_value: str) -> bool:
    host, _ = _parse_url_host(url_value)
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in _WJX_ALLOWED_HOSTS)


def is_wjx_survey_url(url_value: str) -> bool:
    host, _ = _parse_url_host(url_value)
    if not host:
        return False
    return host in _WJX_SURVEY_HOSTS or host.endswith(".v.wjx.cn")


def is_qq_survey_url(url_value: str) -> bool:
    host, path = _parse_url_host(url_value)
    if host != _QQ_ALLOWED_HOST:
        return False
    return bool(_QQ_SURVEY_PATH_RE.match(path))


def detect_survey_provider(url_value: str, default: str = SURVEY_PROVIDER_WJX) -> str:
    if is_qq_survey_url(url_value):
        return SURVEY_PROVIDER_QQ
    if is_wjx_domain(url_value):
        return SURVEY_PROVIDER_WJX
    return normalize_survey_provider(default)


def is_supported_survey_url(url_value: str) -> bool:
    return is_qq_survey_url(url_value) or is_wjx_domain(url_value)


def ensure_question_provider_fields(
    item: Dict[str, Any],
    *,
    default_provider: str = SURVEY_PROVIDER_WJX,
) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    normalized = dict(item)
    provider = normalize_survey_provider(normalized.get("provider"), default=default_provider)
    normalized["provider"] = provider
    normalized["provider_question_id"] = str(normalized.get("provider_question_id") or "").strip()
    normalized["provider_page_id"] = str(normalized.get("provider_page_id") or "").strip()
    normalized["provider_type"] = str(normalized.get("provider_type") or "").strip()
    normalized["provider_page_raw"] = normalized.get("provider_page_raw")
    normalized["unsupported"] = bool(normalized.get("unsupported", False))
    normalized["unsupported_reason"] = str(normalized.get("unsupported_reason") or "").strip()
    return normalized


def ensure_questions_provider_fields(
    items: Iterable[Dict[str, Any]],
    *,
    default_provider: str = SURVEY_PROVIDER_WJX,
) -> List[Dict[str, Any]]:
    normalized_items: List[Dict[str, Any]] = []
    for item in items or []:
        normalized = ensure_question_provider_fields(item, default_provider=default_provider)
        if normalized:
            normalized_items.append(normalized)
    return normalized_items


__all__ = [
    "SURVEY_PROVIDER_WJX",
    "SURVEY_PROVIDER_QQ",
    "SUPPORTED_SURVEY_PROVIDERS",
    "normalize_survey_provider",
    "is_wjx_domain",
    "is_wjx_survey_url",
    "is_qq_survey_url",
    "detect_survey_provider",
    "is_supported_survey_url",
    "ensure_question_provider_fields",
    "ensure_questions_provider_fields",
]
