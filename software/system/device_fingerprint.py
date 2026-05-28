"""设备身份生成。"""
from __future__ import annotations

import logging
import uuid

from software.system.secure_store import read_secret, set_secret

_DEVICE_ID_PREFIX = "sc-v2-"
_DEVICE_SECRET_KEY = "random_ip/device_id"


def build_stable_device_id() -> str:
    """返回持久设备 ID。首次生成 UUID，后续从安全存储复用。"""
    persisted = read_secret(_DEVICE_SECRET_KEY)
    value = str(persisted.value or "").strip()
    if value:
        return value

    device_id = f"{_DEVICE_ID_PREFIX}{uuid.uuid4().hex[:32]}"
    set_secret(_DEVICE_SECRET_KEY, device_id)
    confirmed = read_secret(_DEVICE_SECRET_KEY)
    confirmed_value = str(confirmed.value or "").strip()
    if confirmed_value:
        return confirmed_value
    logging.warning("设备 ID 写入安全存储失败，退回当前会话 UUID：status=%s", confirmed.status)
    return device_id
