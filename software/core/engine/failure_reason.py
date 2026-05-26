"""执行引擎统一失败原因。"""

from __future__ import annotations

from enum import Enum


class FailureReason(str, Enum):
    PROXY_UNAVAILABLE = "proxy_unavailable"
    PAGE_LOAD_FAILED = "page_load_failed"
    FILL_FAILED = "fill_failed"
    SUBMISSION_VERIFICATION_REQUIRED = "submission_verification_required"
    DEVICE_QUOTA_LIMIT = "device_quota_limit"
    USER_STOPPED = "user_stopped"


__all__ = ["FailureReason"]
