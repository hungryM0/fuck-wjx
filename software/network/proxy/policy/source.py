"""代理源和配置管理 - 代理源切换、地区设置、API覆盖、占用时长"""
import logging
import threading
from typing import Any, Optional, Set, Tuple

from software.app.config import (
    IP_EXTRACT_ENDPOINT,
    PROXY_MINUTE_OPTIONS,
    PROXY_POOL_ORDINARY,
    PROXY_POOL_QUALITY,
    PROXY_SOURCE_CUSTOM,
    PROXY_QUOTA_COST_MAP,
    PROXY_SOURCE_DEFAULT,
    PROXY_TTL_GRACE_SECONDS,
)

PROXY_SOURCE_BENEFIT = "benefit"
PROXY_UPSTREAM_DEFAULT = "default"
PROXY_UPSTREAM_BENEFIT = "idiot"
_SUPPORTED_PROXY_SOURCES = frozenset({PROXY_SOURCE_DEFAULT, PROXY_SOURCE_BENEFIT, PROXY_SOURCE_CUSTOM})
_OFFICIAL_PROXY_SOURCES = frozenset({PROXY_SOURCE_DEFAULT, PROXY_SOURCE_BENEFIT})

_config_lock = threading.Lock()
_proxy_api_url_override: Optional[str] = None
_proxy_area_code_override: Optional[str] = None
_current_proxy_source: str = PROXY_SOURCE_DEFAULT
_proxy_occupy_minute: int = 1

_ORDINARY_POOL_PROVINCE_CODES: Set[str] = {
    "110000", "120000", "130000", "140000", "150000", "210000", "220000",
    "230000", "320000", "330000", "340000", "350000", "360000", "370000",
    "410000", "420000", "430000", "440000", "460000", "500000", "510000",
    "610000", "620000", "640000",
}


# ==================== 代理源 get/set ====================

def normalize_proxy_source(source: Optional[str]) -> str:
    try:
        cleaned = str(source or "").strip().lower()
    except Exception:
        cleaned = ""
    if cleaned in _SUPPORTED_PROXY_SOURCES:
        return cleaned
    return PROXY_SOURCE_DEFAULT


def set_proxy_source(source: str) -> None:
    global _current_proxy_source
    normalized = normalize_proxy_source(source)
    with _config_lock:
        _current_proxy_source = normalized
    logging.info(f"代理源已切换为: {normalized}")


def get_proxy_source() -> str:
    with _config_lock:
        return normalize_proxy_source(_current_proxy_source)


def is_custom_proxy_source(source: Optional[str] = None) -> bool:
    current = get_proxy_source() if source is None else normalize_proxy_source(source)
    return current == PROXY_SOURCE_CUSTOM


def is_official_proxy_source(source: Optional[str] = None) -> bool:
    current = get_proxy_source() if source is None else normalize_proxy_source(source)
    return current in _OFFICIAL_PROXY_SOURCES


def source_supports_quota_session(source: Optional[str] = None) -> bool:
    return is_official_proxy_source(source)


def source_uses_custom_api_override(source: Optional[str] = None) -> bool:
    return is_custom_proxy_source(source)


def get_proxy_upstream(source: Optional[str] = None) -> str:
    current = get_proxy_source() if source is None else normalize_proxy_source(source)
    if current == PROXY_SOURCE_BENEFIT:
        return PROXY_UPSTREAM_BENEFIT
    return PROXY_UPSTREAM_DEFAULT


# ==================== 代理占用时长 ====================

def _map_answer_seconds_to_proxy_minute(total_seconds: int) -> int:
    seconds = max(0, int(total_seconds))
    if seconds < 60:
        return 1
    if seconds <= 180:
        return 3
    if seconds <= 300:
        return 5
    if seconds <= 600:
        return 10
    if seconds <= 900:
        return 15
    return 30


def get_proxy_required_seconds_by_answer_seconds(total_seconds: int) -> int:
    return max(0, int(total_seconds)) + int(PROXY_TTL_GRACE_SECONDS)


def get_proxy_minute_by_answer_seconds(total_seconds: int) -> int:
    required_seconds = get_proxy_required_seconds_by_answer_seconds(total_seconds)
    minute = int(_map_answer_seconds_to_proxy_minute(required_seconds))
    if minute not in PROXY_MINUTE_OPTIONS:
        return 1
    return minute


def get_quota_cost_by_minute(minute: int) -> int:
    safe_minute = int(minute) if int(minute) in PROXY_MINUTE_OPTIONS else 1
    return int(PROXY_QUOTA_COST_MAP.get(safe_minute, 1))


def set_proxy_occupy_minute_by_answer_duration(answer_duration_range_seconds: Optional[Tuple[int, int]]) -> int:
    global _proxy_occupy_minute
    min_seconds = max_seconds = 0
    if isinstance(answer_duration_range_seconds, (list, tuple)):
        if len(answer_duration_range_seconds) >= 1:
            min_seconds = _to_non_negative_int(answer_duration_range_seconds[0], 0)
        max_seconds = _to_non_negative_int(answer_duration_range_seconds[1], min_seconds) if len(answer_duration_range_seconds) >= 2 else min_seconds
    max_seconds = max(max_seconds, min_seconds)
    minute = get_proxy_minute_by_answer_seconds(max_seconds)
    required_seconds = get_proxy_required_seconds_by_answer_seconds(max_seconds)
    with _config_lock:
        _proxy_occupy_minute = minute
    logging.info(
        "已根据作答时长更新代理 minute=%s（min=%s秒, max=%s秒, ttl=%s秒）",
        minute,
        min_seconds,
        max_seconds,
        required_seconds,
    )
    return minute


def get_proxy_occupy_minute() -> int:
    with _config_lock:
        minute = int(_proxy_occupy_minute or 1)
    if minute not in PROXY_MINUTE_OPTIONS:
        return 1
    return minute


# ==================== 地区和 API 覆盖 ====================

def _validate_proxy_api_url(api_url: Optional[str]) -> str:
    try:
        cleaned = str(api_url or "").strip()
    except Exception:
        cleaned = ""
    if not cleaned:
        return ""
    if not (cleaned.lower().startswith("http://") or cleaned.lower().startswith("https://")):
        raise ValueError("随机IP提取接口必须以 http:// 或 https:// 开头")
    return cleaned


def _normalize_area_code(area_code: Optional[str]) -> str:
    try:
        cleaned = str(area_code or "").strip()
    except Exception:
        cleaned = ""
    if not cleaned or not cleaned.isdigit() or len(cleaned) != 6:
        return ""
    return cleaned


def _is_province_level_area_code(area_code: str) -> bool:
    return bool(area_code) and len(area_code) == 6 and area_code.isdigit() and area_code.endswith("0000")


def _resolve_default_pool_by_area(area_code: Optional[str]) -> Optional[str]:
    normalized_area = _normalize_area_code(area_code)
    if not normalized_area:
        return None
    if _is_province_level_area_code(normalized_area) and normalized_area in _ORDINARY_POOL_PROVINCE_CODES:
        return PROXY_POOL_ORDINARY
    return PROXY_POOL_QUALITY


def get_default_proxy_area_code() -> str:
    with _config_lock:
        return _normalize_area_code(_proxy_area_code_override) or ""


def get_effective_proxy_api_url() -> str:
    with _config_lock:
        override = (_proxy_api_url_override or "").strip()
        source = normalize_proxy_source(_current_proxy_source)
    if source_uses_custom_api_override(source):
        return override
    return IP_EXTRACT_ENDPOINT


def get_custom_proxy_api_override() -> str:
    with _config_lock:
        return (_proxy_api_url_override or "").strip()


def has_custom_proxy_api_override() -> bool:
    return bool(get_custom_proxy_api_override())


def is_custom_proxy_api_active() -> bool:
    return is_custom_proxy_source()


def get_proxy_area_code() -> Optional[str]:
    with _config_lock:
        return _proxy_area_code_override


def set_proxy_area_code(area_code: Optional[str]) -> Optional[str]:
    global _proxy_area_code_override
    with _config_lock:
        if area_code is None:
            _proxy_area_code_override = None
            return None
        _proxy_area_code_override = _normalize_area_code(area_code)
        return _proxy_area_code_override


def set_proxy_api_override(api_url: Optional[str]) -> str:
    global _proxy_api_url_override
    cleaned = _validate_proxy_api_url(api_url)
    with _config_lock:
        _proxy_api_url_override = cleaned or None
    return get_effective_proxy_api_url()


# ==================== 工具函数 ====================

def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(0, int(default))
    return max(0, parsed)


