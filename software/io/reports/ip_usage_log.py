"""IP 使用记录数据接口 - 从自建 API 获取每日提取记录。"""
from __future__ import annotations

from typing import Any

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS

_API_URL = "https://api-wjx.hungrym0.top/ipzan/usage"


def _to_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except Exception:
        try:
            return int(float(str(raw).strip()))
        except Exception:
            return None


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
        if records and all(("label" in item or "total" in item) for item in records):
            return records
        for item in records:
            nested = _extract_records(item)
            if nested:
                return nested
        return []
    if not isinstance(payload, dict):
        return []

    for key in ("records", "history", "items", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            records = [item for item in value if isinstance(item, dict)]
            if records:
                return records

    for value in payload.values():
        nested = _extract_records(value)
        if nested:
            return nested

    return []


def _extract_remaining_ip(payload: Any) -> int | None:
    if isinstance(payload, dict):
        for key in ("remaining_ip", "remainingIp", "ip_remaining", "remaining"):
            parsed = _to_int(payload.get(key))
            if parsed is not None:
                return max(0, parsed)

        for value in payload.values():
            parsed = _extract_remaining_ip(value)
            if parsed is not None:
                return parsed
    elif isinstance(payload, list):
        for item in payload:
            parsed = _extract_remaining_ip(item)
            if parsed is not None:
                return parsed
    return None


def get_usage_summary() -> dict[str, Any]:
    """返回 usage 接口中的记录列表和剩余 IP 数。"""
    resp = http_client.get(_API_URL, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
    resp.raise_for_status()
    payload = resp.json()
    return {
        "records": _extract_records(payload),
        "remaining_ip": _extract_remaining_ip(payload),
    }



