"""随机 IP 额度管理 - 以后端会话状态为准。"""
from __future__ import annotations

from wjx.network.proxy.auth import (
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
)


def get_random_ip_limit() -> int:
    snapshot = get_session_snapshot()
    total_quota = int(snapshot.get("total_quota") or 0)
    return max(0, total_quota)


def get_random_ip_counter_snapshot_local() -> tuple[int, int, bool]:
    from wjx.network.proxy.source import is_custom_proxy_api_active

    if is_custom_proxy_api_active():
        return 0, 0, True

    if has_authenticated_session():
        snapshot = get_quota_snapshot()
        return int(snapshot["used_quota"]), int(snapshot["total_quota"]), False

    return 0, 0, False


def normalize_random_ip_enabled_value(desired_enabled: bool) -> bool:
    if not desired_enabled:
        return False
    from wjx.network.proxy.source import is_custom_proxy_api_active

    if is_custom_proxy_api_active():
        return True
    if not has_authenticated_session():
        return False
    snapshot = get_quota_snapshot()
    return int(snapshot["remaining_quota"]) > 0
