"""会话策略 - 代理切换与浏览器实例复用逻辑"""
import asyncio
from typing import Optional, Tuple
import logging

from software.core.engine.stop_signal import StopSignalLike
from software.core.engine.runtime_ui_bridge import RuntimeUiBridge
from software.core.task import ExecutionState, ProxyLease
from software.network.proxy.pool import coerce_proxy_lease, mask_proxy_for_log
from software.network.proxy.api import fetch_proxy_batch_async
from software.network.proxy import get_proxy_required_ttl_seconds, proxy_lease_has_sufficient_ttl
from software.core.config.codec import _select_user_agent_from_ratios

_PROXY_WAIT_POLL_SECONDS = 0.3
_BAD_PROXY_COOLDOWN_SECONDS = 180.0


def _active_proxy_addresses_locked(ctx: ExecutionState, *, exclude_thread_name: str = "") -> set[str]:
    return ctx.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)


def _blocked_proxy_addresses_locked(ctx: ExecutionState, *, exclude_thread_name: str = "") -> set[str]:
    blocked = _active_proxy_addresses_locked(ctx, exclude_thread_name=exclude_thread_name)
    blocked.update(ctx.successful_proxy_addresses_locked())
    return blocked


def _record_bad_proxy_and_maybe_pause(
    ctx: ExecutionState,
    runtime_bridge: Optional[RuntimeUiBridge],
) -> bool:
    """
    记录代理不可用事件。
    现阶段不再根据代理异常次数自动暂停任务，统一由提交连续失败止损控制。
    """
    _ = ctx, runtime_bridge
    return False


def _required_proxy_ttl_seconds(ctx: ExecutionState) -> int:
    return int(
        get_proxy_required_ttl_seconds(
            getattr(ctx.config, "answer_duration_range_seconds", (0, 0)),
            survey_provider=getattr(ctx.config, "survey_provider", ""),
        )
    )


def _mark_proxy_temporarily_bad(
    ctx: ExecutionState,
    proxy_address: str,
    *,
    cooldown_seconds: float = _BAD_PROXY_COOLDOWN_SECONDS,
) -> None:
    normalized = str(proxy_address or "").strip()
    if not normalized:
        return
    ctx.mark_proxy_in_cooldown(normalized, cooldown_seconds)
    _discard_unresponsive_proxy(ctx, normalized)
    logging.info(
        "代理进入冷却 %.0fs：%s",
        float(cooldown_seconds or 0.0),
        mask_proxy_for_log(normalized),
    )


def _purge_unusable_proxy_pool_locked(ctx: ExecutionState) -> None:
    ctx._purge_expired_proxy_cooldowns_locked()
    required_ttl = _required_proxy_ttl_seconds(ctx)
    kept = []
    seen = set()
    removed = 0
    for item in list(ctx.config.proxy_ip_pool or []):
        lease = coerce_proxy_lease(item)
        if lease is None:
            removed += 1
            continue
        if not lease.poolable:
            removed += 1
            continue
        if lease.address in seen:
            removed += 1
            continue
        if ctx._is_proxy_in_cooldown_locked(lease.address):
            removed += 1
            logging.info("已移除冷却中的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            removed += 1
            logging.info("已丢弃即将过期的代理：%s", mask_proxy_for_log(lease.address))
            continue
        seen.add(lease.address)
        kept.append(lease)
    if removed:
        logging.info("代理池已清理无效/重复代理 %s 个", removed)
    ctx.config.proxy_ip_pool = kept
    if removed:
        ctx.notify_runtime_change()


def _pop_available_proxy_lease_locked(ctx: ExecutionState) -> Optional[ProxyLease]:
    _purge_unusable_proxy_pool_locked(ctx)
    blocked_addresses = _blocked_proxy_addresses_locked(ctx)
    while ctx.config.proxy_ip_pool:
        lease = coerce_proxy_lease(ctx.config.proxy_ip_pool.pop(0))
        if lease is None:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=_required_proxy_ttl_seconds(ctx)):
            logging.info("已跳过即将过期的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if ctx._is_proxy_in_cooldown_locked(lease.address):
            logging.info("已跳过冷却中的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if lease.address in blocked_addresses:
            logging.info("已跳过已占用或已成功使用过的代理：%s", mask_proxy_for_log(lease.address))
            continue
        return lease
    return None


def _mark_proxy_in_use(ctx: ExecutionState, thread_name: str, lease: Optional[ProxyLease]) -> Optional[str]:
    if lease is None:
        return None
    if thread_name:
        ctx.mark_proxy_in_use(thread_name, lease)
    logging.info(
        "线程[%s] 已分配随机IP：%s（来源=%s）",
        thread_name or "?",
        mask_proxy_for_log(lease.address),
        str(getattr(lease, "source", "") or "unknown"),
    )
    return lease.address


def _resolve_proxy_request_num_locked(ctx: ExecutionState) -> int:
    waiting_count = max(1, int(ctx.proxy_waiting_threads or 0))
    active_count = len(ctx.proxy_in_use_by_thread)
    remaining_to_start = max(0, int(ctx.config.target_num or 0) - int(ctx.cur_num or 0) - active_count)
    if remaining_to_start <= 0:
        return 0
    parallel_capacity = max(1, int(getattr(ctx.config, "num_threads", 1) or 1))
    idle_capacity = max(0, parallel_capacity - active_count)
    request_count = max(waiting_count, idle_capacity)
    return max(1, min(request_count, remaining_to_start, 80))


def _should_stop_proxy_wait(
    ctx: ExecutionState,
    stop_signal: Optional[StopSignalLike],
) -> bool:
    if stop_signal is not None and stop_signal.is_set():
        return True
    return bool(getattr(ctx, "stop_event", None) and ctx.stop_event.is_set())


def _wait_for_next_proxy_cycle(
    ctx: ExecutionState,
    stop_signal: Optional[StopSignalLike],
    *,
    timeout: float = _PROXY_WAIT_POLL_SECONDS,
) -> bool:
    return ctx.wait_for_runtime_change(stop_signal=stop_signal, timeout=timeout)


async def _wait_for_next_proxy_cycle_async(
    ctx: ExecutionState,
    stop_signal: Optional[StopSignalLike],
    *,
    timeout: float = _PROXY_WAIT_POLL_SECONDS,
) -> bool:
    return await asyncio.to_thread(
        ctx.wait_for_runtime_change,
        stop_signal=stop_signal,
        timeout=timeout,
    )


async def _acquire_proxy_fetch_lock_async(
    ctx: ExecutionState,
    stop_signal: Optional[StopSignalLike],
) -> bool:
    while not _should_stop_proxy_wait(ctx, stop_signal):
        acquired = await asyncio.to_thread(
            ctx._proxy_fetch_lock.acquire,
            True,
            _PROXY_WAIT_POLL_SECONDS,
        )
        if acquired:
            return True
    return False


async def _select_proxy_for_session_async(
    ctx: ExecutionState,
    thread_name: str = "",
    *,
    stop_signal: Optional[StopSignalLike] = None,
    wait: bool = False,
) -> Optional[str]:
    if not ctx.config.random_proxy_ip_enabled:
        return None
    selected: Optional[ProxyLease] = None
    with ctx.lock:
        selected = _pop_available_proxy_lease_locked(ctx)
    if selected is not None:
        return _mark_proxy_in_use(ctx, thread_name, selected)

    ctx.register_proxy_waiter()
    try:
        while True:
            if _should_stop_proxy_wait(ctx, stop_signal):
                return None
            with ctx.lock:
                selected = _pop_available_proxy_lease_locked(ctx)
            if selected is not None:
                return _mark_proxy_in_use(ctx, thread_name, selected)

            # 代理池为空时，使用全局 fetch 锁避免多线程并发重复请求代理 API（会快速耗尽额度）
            fetch_lock_acquired = await _acquire_proxy_fetch_lock_async(ctx, stop_signal)
            if not fetch_lock_acquired:
                return None
            try:
                with ctx.lock:
                    selected = _pop_available_proxy_lease_locked(ctx)
                    if selected is None:
                        request_num = _resolve_proxy_request_num_locked(ctx)
                    else:
                        request_num = 0
                if selected is not None:
                    return _mark_proxy_in_use(ctx, thread_name, selected)

                if request_num > 0:
                    try:
                        fetched = await fetch_proxy_batch_async(
                            expected_count=request_num,
                            stop_signal=ctx.stop_event,
                        )
                    except Exception as exc:
                        logging.warning(f"获取随机代理失败：{exc}")
                        fetched = None
                    if fetched:
                        selected = None
                        with ctx.lock:
                            _purge_unusable_proxy_pool_locked(ctx)
                            _pool_leases = [coerce_proxy_lease(item) for item in ctx.config.proxy_ip_pool]
                            existing = {lease.address for lease in _pool_leases if lease is not None}
                            existing.update(_blocked_proxy_addresses_locked(ctx))
                            required_ttl = _required_proxy_ttl_seconds(ctx)
                            for item in fetched:
                                lease = coerce_proxy_lease(item)
                                if lease is None:
                                    continue
                                if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
                                    logging.info("已丢弃即将过期的新代理：%s", mask_proxy_for_log(lease.address))
                                    continue
                                if ctx._is_proxy_in_cooldown_locked(lease.address):
                                    logging.info("已跳过冷却中的新代理：%s", mask_proxy_for_log(lease.address))
                                    continue
                                if selected is None:
                                    if lease.address in existing:
                                        logging.info("已跳过重复或正在占用的新代理：%s", mask_proxy_for_log(lease.address))
                                        continue
                                    selected = lease
                                    existing.add(lease.address)
                                    continue
                                if not lease.poolable or lease.address in existing:
                                    continue
                                ctx.config.proxy_ip_pool.append(lease)
                                existing.add(lease.address)
                            ctx.notify_runtime_change()
                        if selected is not None:
                            return _mark_proxy_in_use(ctx, thread_name, selected)
            finally:
                ctx._proxy_fetch_lock.release()

            if not wait:
                return None
            if await _wait_for_next_proxy_cycle_async(ctx, stop_signal):
                return None
    finally:
        ctx.unregister_proxy_waiter()


def _select_user_agent_for_session(ctx: ExecutionState) -> Tuple[Optional[str], Optional[str]]:
    if not ctx.config.random_user_agent_enabled:
        return None, None
    return _select_user_agent_from_ratios(ctx.config.user_agent_ratios)


def _discard_unresponsive_proxy(ctx: ExecutionState, proxy_address: str) -> None:
    if not proxy_address:
        return
    with ctx.lock:
        removed = False
        normalized = str(proxy_address or "").strip()
        retained = []
        for item in list(ctx.config.proxy_ip_pool or []):
            lease = coerce_proxy_lease(item)
            if lease is None:
                continue
            if lease.address == normalized:
                removed = True
                continue
            retained.append(lease)
        ctx.config.proxy_ip_pool = retained
        if removed:
            logging.info(f"已移除无响应代理：{mask_proxy_for_log(proxy_address)}")
            ctx.notify_runtime_change()


