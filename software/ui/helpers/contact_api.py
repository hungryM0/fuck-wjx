"""联系表单网络访问门面。"""
from __future__ import annotations

from typing import Any

import software.network.http as http_client
from software.network.proxy.session import format_quota_value, get_session_snapshot


def post(*args: Any, **kwargs: Any):
    return http_client.post(*args, **kwargs)


__all__ = ["format_quota_value", "get_session_snapshot", "post"]

