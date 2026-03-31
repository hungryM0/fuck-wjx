"""UI 侧代理与额度访问门面。"""

from software.network.proxy.api import format_status_payload, test_custom_proxy_api
from software.network.proxy.areas import (
    load_area_codes,
    load_benefit_supported_areas,
    load_supported_area_codes,
)
from software.network.proxy.policy import (
    PROXY_SOURCE_BENEFIT,
    apply_custom_proxy_api,
    apply_proxy_area_code,
    apply_proxy_source_settings,
    get_proxy_minute_by_answer_seconds,
    get_proxy_settings,
    get_quota_cost_by_minute,
    get_random_ip_counter_snapshot_local,
)
from software.network.proxy.session import (
    RandomIPAuthError,
    claim_easter_egg_bonus,
    format_quota_value,
    format_random_ip_error,
    get_session_snapshot,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
)

__all__ = [
    "PROXY_SOURCE_BENEFIT",
    "RandomIPAuthError",
    "apply_custom_proxy_api",
    "apply_proxy_area_code",
    "apply_proxy_source_settings",
    "claim_easter_egg_bonus",
    "format_quota_value",
    "format_random_ip_error",
    "format_status_payload",
    "get_proxy_minute_by_answer_seconds",
    "get_proxy_settings",
    "get_quota_cost_by_minute",
    "get_random_ip_counter_snapshot_local",
    "get_session_snapshot",
    "has_authenticated_session",
    "has_unknown_local_quota",
    "is_quota_exhausted",
    "load_area_codes",
    "load_benefit_supported_areas",
    "load_supported_area_codes",
    "test_custom_proxy_api",
]
