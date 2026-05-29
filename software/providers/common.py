"""问卷平台识别与元数据补全。"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse, urlsplit, urlunsplit

SURVEY_PROVIDER_WJX = "wjx"
SURVEY_PROVIDER_QQ = "qq"
SURVEY_PROVIDER_CREDAMO = "credamo"
SUPPORTED_SURVEY_PROVIDERS = {SURVEY_PROVIDER_WJX, SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_CREDAMO}

_WJX_ALLOWED_HOSTS = ("wjx.top", "wjx.cn", "wjx.com")
_WJX_SURVEY_HOSTS = ("v.wjx.cn", "www.wjx.cn")
_QQ_ALLOWED_HOST = "wj.qq.com"
_QQ_SURVEY_PATH_RE = re.compile(r"^/s\d+/\d+/[A-Za-z0-9_-]+/?$", re.IGNORECASE)
_CREDAMO_ALLOWED_HOSTS = ("credamo.com", "credamo.cn")
_CREDAMO_SURVEY_PATH_RE = re.compile(r"^/answer\.html", re.IGNORECASE)
_CREDAMO_SHORT_SURVEY_PATH_RE = re.compile(r"^/s/[A-Za-z0-9_-]+/?$", re.IGNORECASE)


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


def is_credamo_survey_url(url_value: str) -> bool:
    host, path = _parse_url_host(url_value)
    if not host:
        return False
    if not any(host == domain or host.endswith(f".{domain}") for domain in _CREDAMO_ALLOWED_HOSTS):
        return False
    return bool(_CREDAMO_SURVEY_PATH_RE.match(path) or _CREDAMO_SHORT_SURVEY_PATH_RE.match(path))


def detect_survey_provider(url_value: str, default: str = SURVEY_PROVIDER_WJX) -> str:
    if is_credamo_survey_url(url_value):
        return SURVEY_PROVIDER_CREDAMO
    if is_qq_survey_url(url_value):
        return SURVEY_PROVIDER_QQ
    if is_wjx_domain(url_value):
        return SURVEY_PROVIDER_WJX
    return normalize_survey_provider(default)


def supports_answer_datetime_window(provider: Any) -> bool:
    return normalize_survey_provider(provider) == SURVEY_PROVIDER_CREDAMO


def is_supported_survey_url(url_value: str) -> bool:
    return is_credamo_survey_url(url_value) or is_qq_survey_url(url_value) or is_wjx_domain(url_value)


def normalize_survey_parse_url(url_value: str) -> str:
    text = str(url_value or "").strip()
    if not text:
        return ""
    candidate = text if "://" in text else f"https://{text}"
    try:
        parsed = urlsplit(candidate)
    except Exception:
        return text
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()
    path = str(parsed.path or "")
    fragment = str(parsed.fragment or "")
    normalized = urlunsplit((scheme, netloc, path, parsed.query or "", fragment))
    if detect_survey_provider(normalized, default="") != SURVEY_PROVIDER_CREDAMO:
        return normalized
    if path.lower().startswith("/s/") and not fragment:
        return urlunsplit((scheme, netloc, "/answer.html", parsed.query or "", path))
    return normalized


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


def make_provider_question_key(
    provider: Any,
    provider_page_id: Any,
    provider_question_id: Any,
) -> str:
    normalized_provider = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    page_id = str(provider_page_id or "").strip()
    question_id = str(provider_question_id or "").strip()
    if not page_id or not question_id:
        return ""
    return f"{normalized_provider}:{page_id}:{question_id}"


__all__ = [
    "SURVEY_PROVIDER_WJX",
    "SURVEY_PROVIDER_QQ",
    "SURVEY_PROVIDER_CREDAMO",
    "SUPPORTED_SURVEY_PROVIDERS",
    "normalize_survey_provider",
    "is_wjx_domain",
    "is_wjx_survey_url",
    "is_qq_survey_url",
    "is_credamo_survey_url",
    "detect_survey_provider",
    "supports_answer_datetime_window",
    "is_supported_survey_url",
    "normalize_survey_parse_url",
    "ensure_question_provider_fields",
    "ensure_questions_provider_fields",
    "make_provider_question_key",
]
