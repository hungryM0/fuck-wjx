"""随机 IP 会话数据模型。"""
from __future__ import annotations

from dataclasses import dataclass


class RandomIPAuthError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 0, retry_after_seconds: int = 0):
        self.detail = str(detail or "unknown_error")
        self.status_code = int(status_code or 0)
        self.retry_after_seconds = max(0, int(retry_after_seconds or 0))
        super().__init__(self.detail)

@dataclass
class RandomIPSession:
    device_id: str = ""
    user_id: int = 0
    remaining_quota: float = 0.0
    total_quota: float = 0.0
    used_quota: float = 0.0
    quota_known: bool = False
