"""代理池与预取。"""

from software.network.proxy.pool.pool import (
    coerce_proxy_lease,
    get_proxy_required_ttl_seconds,
    is_proxy_responsive,
    mask_proxy_for_log,
    normalize_proxy_address,
    proxy_lease_has_sufficient_ttl,
)
from software.network.proxy.pool.prefetch import prefetch_proxy_pool

__all__ = [
    "coerce_proxy_lease",
    "get_proxy_required_ttl_seconds",
    "is_proxy_responsive",
    "mask_proxy_for_log",
    "normalize_proxy_address",
    "prefetch_proxy_pool",
    "proxy_lease_has_sufficient_ttl",
]

