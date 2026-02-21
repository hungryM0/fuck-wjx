"""代理预取服务 - 封装代理池初始化逻辑"""
from __future__ import annotations

import threading
from typing import List, Optional

from wjx.network.proxy import (
    _fetch_new_proxy_batch,
    get_effective_proxy_api_url,
)


def prefetch_proxy_pool(
    expected_count: int,
    proxy_api_url: Optional[str] = None,
    stop_signal: Optional[threading.Event] = None,
) -> List[str]:
    """预取一批代理 IP。

    Args:
        expected_count: 期望数量（通常等于线程数）
        proxy_api_url: 自定义代理 API URL，为 None 时使用默认
        stop_signal: 停止信号

    Returns:
        代理地址列表（可能为空）

    Raises:
        Exception: 代理获取失败时抛出（由调用方处理）
    """
    effective_url = proxy_api_url or get_effective_proxy_api_url()
    proxy_pool = _fetch_new_proxy_batch(
        expected_count=max(1, expected_count),
        proxy_url=effective_url,
        notify_on_area_error=False,
        stop_signal=stop_signal,
    )
    return proxy_pool
