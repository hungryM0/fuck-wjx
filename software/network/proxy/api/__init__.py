"""代理远端接口。"""

from software.network.proxy.api.provider import (
    AreaProxyQualityError,
    ProxyApiFatalError,
    fetch_proxy_batch,
    format_status_payload,
    get_status,
    test_custom_proxy_api,
)

__all__ = [
    "AreaProxyQualityError",
    "ProxyApiFatalError",
    "fetch_proxy_batch",
    "format_status_payload",
    "get_status",
    "test_custom_proxy_api",
]

