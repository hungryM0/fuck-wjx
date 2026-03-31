"""代理会话。"""

from software.network.proxy.session.auth import (
    RandomIPAuthError,
    activate_trial,
    claim_easter_egg_bonus,
    format_quota_value,
    format_random_ip_error,
    get_device_id,
    get_fresh_quota_snapshot,
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
    load_session_for_startup,
    sync_quota_snapshot_from_server,
)

__all__ = [
    "RandomIPAuthError",
    "activate_trial",
    "claim_easter_egg_bonus",
    "format_quota_value",
    "format_random_ip_error",
    "get_device_id",
    "get_fresh_quota_snapshot",
    "get_quota_snapshot",
    "get_session_snapshot",
    "has_authenticated_session",
    "has_unknown_local_quota",
    "is_quota_exhausted",
    "load_session_for_startup",
    "sync_quota_snapshot_from_server",
]
