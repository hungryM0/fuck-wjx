"""随机 IP 额度管理 - 以后端会话状态为准。"""
from __future__ import annotations

from software.network.proxy.session.auth import (
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
)


def get_random_ip_limit() -> float:
    snapshot = get_session_snapshot()
    total_quota = float(snapshot.get("total_quota") or 0.0)
    return max(0.0, total_quota)


def get_random_ip_counter_snapshot_local() -> tuple[float, float, bool]:
    from software.network.proxy.policy.source import is_custom_proxy_source

    if is_custom_proxy_source():
        return 0, 0, True

    if has_authenticated_session():
        snapshot = get_quota_snapshot()
        return float(snapshot["used_quota"]), float(snapshot["total_quota"]), False

    return 0.0, 0.0, False


def normalize_random_ip_enabled_value(desired_enabled: bool) -> bool:
    if not desired_enabled:
        return False
    from software.network.proxy.policy.source import is_custom_proxy_source

    if is_custom_proxy_source():
        return True
    if not has_authenticated_session():
        return False
    snapshot = get_session_snapshot()
    if has_unknown_local_quota(snapshot):
        return True
    return not is_quota_exhausted(snapshot)

