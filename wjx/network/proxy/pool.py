"""代理池和租约管理 - 代理租约构建、TTL检查、地址规范化、健康检查"""
from datetime import datetime, timezone
import logging
import time
from urllib.parse import urlsplit
from typing import Any, List, Optional, Tuple

import wjx.network.http_client as http_client
from wjx.core.task_context import ProxyLease
from wjx.utils.app.config import (
    PROXY_HEALTH_CHECK_TIMEOUT,
    PROXY_HEALTH_CHECK_URL,
    PROXY_SOURCE_DEFAULT,
    PROXY_TTL_GRACE_SECONDS,
)
from wjx.utils.logging.log_utils import log_suppressed_exception
from wjx.network.proxy.source import (
    _to_non_negative_int,
    get_proxy_source,
)


# ==================== 地址规范化 ====================

def _normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    if not proxy_address:
        return None
    normalized = proxy_address.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _format_host_port(hostname: str, port: Optional[int]) -> str:
    if not hostname:
        return ""
    if port is None:
        return hostname
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]:{port}"
    return f"{hostname}:{port}"


def _mask_proxy_for_log(proxy_address: Optional[str]) -> str:
    if not proxy_address:
        return ""
    text = str(proxy_address).strip()
    if not text:
        return ""
    if get_proxy_source() != PROXY_SOURCE_DEFAULT:
        return text
    candidate = text if "://" in text else f"http://{text}"
    try:
        parsed = urlsplit(candidate)
        host_port = _format_host_port(parsed.hostname or "", parsed.port)
        if host_port:
            return host_port
    except Exception as exc:
        log_suppressed_exception("random_ip._mask_proxy_for_log parse proxy", exc)
    raw = text
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    if "@" in raw:
        raw = raw.split("@", 1)[1]
    return raw


# ==================== 租约构建 ====================

def _parse_expire_at_to_ts(expire_at: Optional[str]) -> float:
    text = str(expire_at or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        logging.debug("代理 expire_at 解析失败：%s", text, exc_info=True)
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return float(parsed.astimezone(timezone.utc).timestamp())


def _build_proxy_lease(
    proxy_address: Optional[str],
    *,
    expire_at: Optional[str] = None,
    poolable: bool = True,
    source: str = "",
) -> Optional[ProxyLease]:
    normalized = _normalize_proxy_address(proxy_address)
    if not normalized:
        return None
    expire_text = str(expire_at or "").strip()
    return ProxyLease(
        address=normalized,
        expire_at=expire_text,
        expire_ts=_parse_expire_at_to_ts(expire_text),
        poolable=bool(poolable),
        source=str(source or "").strip(),
    )


def _coerce_proxy_lease(item: Any, *, source: str = "") -> Optional[ProxyLease]:
    if isinstance(item, ProxyLease):
        normalized = _normalize_proxy_address(item.address)
        if not normalized:
            return None
        if normalized == item.address:
            return item
        return ProxyLease(
            address=normalized,
            expire_at=item.expire_at,
            expire_ts=float(item.expire_ts or 0.0),
            poolable=bool(item.poolable),
            source=item.source,
        )
    if isinstance(item, str):
        return _build_proxy_lease(item, source=source)
    if isinstance(item, dict):
        address = item.get("address") or item.get("proxy") or item.get("host")
        expire_at = item.get("expire_at")
        poolable = bool(item.get("poolable", True))
        item_source = str(item.get("source") or source or "").strip()
        if address and item.get("port") and isinstance(address, str) and ":" not in address:
            address = f"{address}:{item.get('port')}"
        return _build_proxy_lease(address, expire_at=expire_at, poolable=poolable, source=item_source)
    return None


def _proxy_lease_address(item: Any) -> str:
    lease = _coerce_proxy_lease(item)
    return lease.address if lease is not None else ""


# ==================== TTL 检查 ====================

def get_proxy_required_ttl_seconds(answer_duration_range_seconds: Optional[Tuple[int, int]]) -> int:
    max_seconds = 0
    if isinstance(answer_duration_range_seconds, (list, tuple)):
        if len(answer_duration_range_seconds) >= 2:
            max_seconds = _to_non_negative_int(answer_duration_range_seconds[1], 0)
        elif len(answer_duration_range_seconds) >= 1:
            max_seconds = _to_non_negative_int(answer_duration_range_seconds[0], 0)
    return max(0, int(max_seconds)) + PROXY_TTL_GRACE_SECONDS


def proxy_lease_has_sufficient_ttl(lease: Optional[ProxyLease], *, required_ttl_seconds: int) -> bool:
    if lease is None:
        return False
    expire_ts = float(getattr(lease, "expire_ts", 0.0) or 0.0)
    if expire_ts <= 0:
        return True
    return (expire_ts - time.time()) >= max(0, int(required_ttl_seconds or 0))


# ==================== 默认代理构建 ====================

def _build_default_proxy_lease(payload: dict) -> Optional[ProxyLease]:
    if not isinstance(payload, dict):
        return None
    host = str(payload.get("host") or "").strip()
    port = _to_non_negative_int(payload.get("port"), 0)
    if not host or port <= 0:
        return None
    account = str(payload.get("account") or "").strip()
    password = str(payload.get("password") or "").strip()
    raw = f"{account}:{password}@{host}:{port}" if account and password else f"{host}:{port}"
    expire_at = str(payload.get("expire_at") or "").strip()
    poolable = True
    if not expire_at:
        logging.warning("默认随机IP响应缺少 expire_at，该代理仅允许立即使用，不会进入代理池")
        poolable = False
    return _build_proxy_lease(raw, expire_at=expire_at, poolable=poolable, source=PROXY_SOURCE_DEFAULT)


def _build_default_proxy_leases_from_batch(payload: dict) -> List[ProxyLease]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    leases: List[ProxyLease] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        lease = _build_default_proxy_lease(raw)
        if lease is None:
            continue
        leases.append(lease)
        logging.info("获取到代理: %s", _mask_proxy_for_log(lease.address))
    return leases


# ==================== 健康检查 ====================

def _proxy_is_responsive(proxy_address: str, skip_for_default: bool = True) -> bool:
    masked_proxy = _mask_proxy_for_log(proxy_address)
    if skip_for_default and get_proxy_source() == PROXY_SOURCE_DEFAULT:
        logging.debug(f"默认代理源，跳过健康检查: {masked_proxy}")
        return True
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False
    proxies = {"http": proxy_address, "https": proxy_address}
    try:
        start = time.perf_counter()
        response = http_client.get(PROXY_HEALTH_CHECK_URL, proxies=proxies, timeout=PROXY_HEALTH_CHECK_TIMEOUT)
        elapsed = time.perf_counter() - start
    except Exception as exc:
        logging.debug(f"代理 {masked_proxy} 验证失败: {exc}")
        return False
    if response.status_code >= 400:
        logging.warning(f"代理 {masked_proxy} 返回状态码 {response.status_code}")
        return False
    logging.debug(f"代理 {masked_proxy} 验证通过，耗时 {elapsed:.2f}s")
    return True


def _proxy_is_responsive_fast(proxy_address: str) -> bool:
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False
    proxies = {"http": proxy_address, "https": proxy_address}
    try:
        response = http_client.get(PROXY_HEALTH_CHECK_URL, proxies=proxies, timeout=3)
        return response.status_code < 400
    except Exception:
        return False
