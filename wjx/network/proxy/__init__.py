"""随机 IP / 代理能力聚合导出。"""

from wjx.network.proxy.source import (
    get_default_proxy_area_code,
    get_effective_proxy_api_url,
    get_proxy_area_code,
    get_proxy_minute_by_answer_seconds,
    get_proxy_occupy_minute,
    get_proxy_source,
    get_quota_cost_by_minute,
    is_custom_proxy_api_active,
    set_proxy_api_override,
    set_proxy_area_code,
    set_proxy_occupy_minute_by_answer_duration,
    set_proxy_source,
)
from wjx.network.proxy.pool import (
    _coerce_proxy_lease,
    _mask_proxy_for_log,
    _normalize_proxy_address,
    _proxy_is_responsive,
    get_proxy_required_ttl_seconds,
    proxy_lease_has_sufficient_ttl,
)
from wjx.network.proxy.provider import (
    AreaProxyQualityError,
    ProxyApiFatalError,
    _fetch_new_proxy_batch,
    _format_status_payload,
    get_status,
    test_custom_proxy_api,
)
from wjx.utils.app.config import (
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
)
from wjx.network.proxy.quota import (
    get_random_ip_counter_snapshot_local,
    get_random_ip_limit,
    normalize_random_ip_enabled_value,
)
from wjx.network.proxy.gui_bridge import (
    handle_random_ip_submission,
    on_random_ip_toggle,
    refresh_ip_counter_display,
    show_quota_request_dialog,
    show_random_ip_activation_dialog,
)

__all__ = [
    "AreaProxyQualityError",
    "ProxyApiFatalError",
    "PROXY_SOURCE_CUSTOM",
    "PROXY_SOURCE_DEFAULT",
    "_coerce_proxy_lease",
    "_fetch_new_proxy_batch",
    "_format_status_payload",
    "_mask_proxy_for_log",
    "_normalize_proxy_address",
    "_proxy_is_responsive",
    "get_default_proxy_area_code",
    "get_effective_proxy_api_url",
    "get_proxy_area_code",
    "get_proxy_minute_by_answer_seconds",
    "get_proxy_occupy_minute",
    "get_proxy_required_ttl_seconds",
    "get_proxy_source",
    "get_quota_cost_by_minute",
    "get_random_ip_counter_snapshot_local",
    "get_random_ip_limit",
    "get_status",
    "handle_random_ip_submission",
    "is_custom_proxy_api_active",
    "normalize_random_ip_enabled_value",
    "on_random_ip_toggle",
    "proxy_lease_has_sufficient_ttl",
    "refresh_ip_counter_display",
    "set_proxy_api_override",
    "set_proxy_area_code",
    "set_proxy_occupy_minute_by_answer_duration",
    "set_proxy_source",
    "show_quota_request_dialog",
    "show_random_ip_activation_dialog",
    "test_custom_proxy_api",
]
