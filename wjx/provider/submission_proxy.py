"""问卷星无头提交代理切换。"""

from __future__ import annotations

import logging
import threading
from typing import Optional
from urllib.parse import quote, urlparse

import httpx

from software.app.config import get_proxy_auth
from software.core.task import ExecutionState
from software.network.browser import BrowserDriver
from software.network.proxy import (
    PROXY_SOURCE_CUSTOM,
    get_proxy_required_ttl_seconds,
    get_proxy_source,
    proxy_lease_has_sufficient_ttl,
)
from software.network.proxy.api import fetch_proxy_batch
from software.network.proxy.pool import coerce_proxy_lease, mask_proxy_for_log, normalize_proxy_address

_HEADLESS_SUBMIT_RETRYABLE_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)


def _build_submit_proxy_url(proxy_address: Optional[str]) -> Optional[str]:
    """构造给 httpx 使用的代理 URL，必要时补全认证信息。"""
    normalized = normalize_proxy_address(proxy_address)
    if not normalized:
        return None

    try:
        parsed = urlparse(normalized)
    except Exception:
        return normalized

    scheme = str(parsed.scheme or "http").lower()
    host = str(parsed.hostname or "").strip()
    if not host:
        return normalized
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    host_port = f"{host}:{parsed.port}" if parsed.port else host

    username = parsed.username
    password = parsed.password
    if not username and get_proxy_source() == PROXY_SOURCE_CUSTOM:
        try:
            auth = get_proxy_auth()
            username, password = auth.split(":", 1)
        except Exception:
            username = None
            password = None

    if username:
        user = quote(str(username), safe="")
        pwd = quote("" if password is None else str(password), safe="")
        netloc = f"{user}:{pwd}@{host_port}"
    else:
        netloc = host_port

    return f"{scheme}://{netloc}"


def _is_retryable_submit_proxy_error(exc: BaseException) -> bool:
    return isinstance(exc, _HEADLESS_SUBMIT_RETRYABLE_ERRORS)


def _required_submit_proxy_ttl_seconds(ctx: Optional[ExecutionState]) -> int:
    if ctx is None:
        return 20
    return int(get_proxy_required_ttl_seconds(getattr(ctx, "answer_duration_range_seconds", (0, 0))))


def _remove_proxy_from_ctx_pool(ctx: ExecutionState, proxy_address: Optional[str]) -> bool:
    normalized = normalize_proxy_address(proxy_address)
    if not normalized:
        return False

    removed = False
    with ctx.lock:
        retained = []
        for item in list(ctx.proxy_ip_pool or []):
            lease = coerce_proxy_lease(item)
            if lease is None:
                continue
            if lease.address == normalized:
                removed = True
                continue
            retained.append(lease)
        ctx.proxy_ip_pool = retained
    return removed


def _pop_replacement_proxy_from_pool_locked(ctx: ExecutionState, current_proxy: Optional[str]) -> Optional[str]:
    required_ttl = _required_submit_proxy_ttl_seconds(ctx)
    current = normalize_proxy_address(current_proxy)
    retained = []
    selected = None
    for item in list(ctx.proxy_ip_pool or []):
        lease = coerce_proxy_lease(item)
        if lease is None:
            continue
        if lease.address == current:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            logging.info("已丢弃即将过期的提交代理：%s", mask_proxy_for_log(lease.address))
            continue
        if selected is None:
            selected = lease.address
            continue
        retained.append(lease)
    ctx.proxy_ip_pool = retained
    return selected


def _acquire_replacement_submit_proxy(
    driver: BrowserDriver,
    ctx: Optional[ExecutionState],
    *,
    stop_signal: Optional[threading.Event],
) -> Optional[str]:
    if ctx is None or not bool(getattr(ctx, "random_proxy_ip_enabled", False)):
        return None
    if stop_signal and stop_signal.is_set():
        return None

    current_proxy = normalize_proxy_address(getattr(driver, "_submit_proxy_address", None))
    removed_from_pool = _remove_proxy_from_ctx_pool(ctx, current_proxy)
    if current_proxy:
        logging.warning("无头提交代理疑似失效，已废弃：%s", mask_proxy_for_log(current_proxy))
    elif removed_from_pool:
        logging.info("已从代理池移除重复的失效提交代理")

    with ctx.lock:
        candidate = _pop_replacement_proxy_from_pool_locked(ctx, current_proxy)
    if candidate:
        setattr(driver, "_submit_proxy_address", candidate)
        logging.info("无头提交改用代理池中的新代理：%s", mask_proxy_for_log(candidate))
        return candidate

    with ctx._proxy_fetch_lock:
        with ctx.lock:
            candidate = _pop_replacement_proxy_from_pool_locked(ctx, current_proxy)
        if candidate:
            setattr(driver, "_submit_proxy_address", candidate)
            logging.info("无头提交改用代理池中的新代理：%s", mask_proxy_for_log(candidate))
            return candidate

        if stop_signal and stop_signal.is_set():
            return None

        try:
            fetched = fetch_proxy_batch(expected_count=1, stop_signal=stop_signal)
        except Exception as exc:
            logging.warning("无头提交切换新代理失败：%s", exc)
            return None
        for item in fetched or []:
            lease = coerce_proxy_lease(item)
            candidate = lease.address if lease is not None else ""
            if not candidate or candidate == current_proxy:
                continue
            if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=_required_submit_proxy_ttl_seconds(ctx)):
                logging.info("已跳过即将过期的新提交代理：%s", mask_proxy_for_log(candidate))
                continue
            setattr(driver, "_submit_proxy_address", candidate)
            logging.info("无头提交已切换为新提取代理：%s", mask_proxy_for_log(candidate))
            return candidate
    return None


__all__ = [
    "_acquire_replacement_submit_proxy",
    "_build_submit_proxy_url",
    "_is_retryable_submit_proxy_error",
]
