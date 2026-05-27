"""会话策略 - 代理切换与浏览器实例复用逻辑"""
import asyncio
from collections import deque
from typing import Iterable, Optional, Tuple
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
_PROXY_FETCH_BUFFER_MULTIPLIER = 2
_PROXY_FETCH_MAX_BATCH_SIZE = 20


def _ensure_proxy_pool_deque_locked(ctx: ExecutionState) -> deque:
    pool = ctx.config.proxy_ip_pool
    if isinstance(pool, deque):
        return pool
    normalized_pool = deque(pool or [])
    ctx.config.proxy_ip_pool = normalized_pool
    return normalized_pool


def _get_proxy_fetch_async_lock(ctx: ExecutionState) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    current_lock = getattr(ctx, "_proxy_fetch_async_lock", None)
    current_loop = getattr(ctx, "_proxy_fetch_async_lock_loop", None)
    if not isinstance(current_lock, asyncio.Lock) or current_loop is not loop:
        current_lock = asyncio.Lock()
        setattr(ctx, "_proxy_fetch_async_lock", current_lock)
        setattr(ctx, "_proxy_fetch_async_lock_loop", loop)
    return current_lock


def is_proxy_fetch_in_progress(ctx: ExecutionState) -> bool:
    current_lock = getattr(ctx, "_proxy_fetch_async_lock", None)
    return isinstance(current_lock, asyncio.Lock) and current_lock.locked()


def release_proxy_fetch_lock(ctx: ExecutionState) -> None:
    current_lock = getattr(ctx, "_proxy_fetch_async_lock", None)
    if isinstance(current_lock, asyncio.Lock) and current_lock.locked():
        current_lock.release()


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


def _cooldown_proxy_addresses_locked(ctx: ExecutionState) -> set[str]:
    ctx._purge_expired_proxy_cooldowns_locked()
    return {
        str(address or "").strip()
        for address, cooldown_until in ctx.proxy_cooldown_until_by_address.items()
        if str(address or "").strip() and float(cooldown_until or 0.0) > 0.0
    }


def _purge_unusable_proxy_pool_locked(
    ctx: ExecutionState,
    *,
    required_ttl: Optional[int] = None,
    blocked_addresses: Optional[set[str]] = None,
) -> set[str]:
    ctx._purge_expired_proxy_cooldowns_locked()
    required_ttl_seconds = _required_proxy_ttl_seconds(ctx) if required_ttl is None else int(required_ttl)
    pool = _ensure_proxy_pool_deque_locked(ctx)
    kept = deque()
    seen = set()
    removed = 0
    while pool:
        item = pool.popleft()
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
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl_seconds):
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
    return seen


def _pop_available_proxy_lease_locked(ctx: ExecutionState) -> Optional[ProxyLease]:
    required_ttl = _required_proxy_ttl_seconds(ctx)
    blocked_addresses = _blocked_proxy_addresses_locked(ctx)
    _purge_unusable_proxy_pool_locked(
        ctx,
        required_ttl=required_ttl,
        blocked_addresses=blocked_addresses,
    )
    pool = _ensure_proxy_pool_deque_locked(ctx)
    while pool:
        lease = coerce_proxy_lease(pool.popleft())
        if lease is None:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
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


def _merge_fetched_proxy_leases_locked(
    ctx: ExecutionState,
    fetched: Iterable[object],
    *,
    select_first: bool,
) -> Optional[ProxyLease]:
    required_ttl = _required_proxy_ttl_seconds(ctx)
    blocked_addresses = _blocked_proxy_addresses_locked(ctx)
    existing = _purge_unusable_proxy_pool_locked(
        ctx,
        required_ttl=required_ttl,
        blocked_addresses=blocked_addresses,
    )
    existing.update(blocked_addresses)
    pool = _ensure_proxy_pool_deque_locked(ctx)
    selected: Optional[ProxyLease] = None
    changed = False

    for item in fetched or []:
        lease = coerce_proxy_lease(item)
        if lease is None:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            logging.info("已丢弃即将过期的新代理：%s", mask_proxy_for_log(lease.address))
            continue
        if ctx._is_proxy_in_cooldown_locked(lease.address):
            logging.info("已跳过冷却中的新代理：%s", mask_proxy_for_log(lease.address))
            continue
        if lease.address in existing:
            logging.info("已跳过重复或正在占用的新代理：%s", mask_proxy_for_log(lease.address))
            continue
        if select_first and selected is None:
            selected = lease
            existing.add(lease.address)
            continue
        if not lease.poolable:
            continue
        pool.append(lease)
        existing.add(lease.address)
        changed = True

    if changed or selected is not None:
        ctx.notify_runtime_change()
    return selected


def merge_prefetched_proxy_leases(ctx: ExecutionState, fetched: Iterable[object]) -> int:
    """把后台预热到的代理并入运行池，返回实际入池数量。"""
    if not fetched:
        return 0
    with ctx.lock:
        before = len(_ensure_proxy_pool_deque_locked(ctx))
        _merge_fetched_proxy_leases_locked(ctx, fetched, select_first=False)
        merged_count = max(0, len(_ensure_proxy_pool_deque_locked(ctx)) - before)
    if merged_count:
        ctx.notify_runtime_change()
    return merged_count


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
    buffer_capacity = max(waiting_count, idle_capacity * _PROXY_FETCH_BUFFER_MULTIPLIER)
    return max(1, min(buffer_capacity, remaining_to_start, _PROXY_FETCH_MAX_BATCH_SIZE))


def resolve_proxy_prefetch_request_count(ctx: ExecutionState) -> int:
    """计算后台预取还需要补多少代理。"""
    if not bool(getattr(ctx.config, "random_proxy_ip_enabled", False)):
        return 0
    with ctx.lock:
        active_count = len(ctx.proxy_in_use_by_thread)
        remaining_to_start = max(0, int(ctx.config.target_num or 0) - int(ctx.cur_num or 0) - active_count)
        if remaining_to_start <= 0:
            return 0
        worker_count = max(1, int(getattr(ctx.config, "num_threads", 1) or 1))
        target_buffer = min(
            worker_count * _PROXY_FETCH_BUFFER_MULTIPLIER,
            remaining_to_start,
            _PROXY_FETCH_MAX_BATCH_SIZE,
        )
        current_pool_size = len(_ensure_proxy_pool_deque_locked(ctx))
    return max(0, int(target_buffer) - int(current_pool_size))


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
    lock = _get_proxy_fetch_async_lock(ctx)
    while not _should_stop_proxy_wait(ctx, stop_signal):
        try:
            await asyncio.wait_for(lock.acquire(), timeout=_PROXY_WAIT_POLL_SECONDS)
            return True
        except asyncio.TimeoutError:
            continue
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
            if is_proxy_fetch_in_progress(ctx):
                if await _wait_for_next_proxy_cycle_async(ctx, stop_signal):
                    return None
                continue

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
                        with ctx.lock:
                            selected = _merge_fetched_proxy_leases_locked(ctx, fetched, select_first=True)
                        if selected is not None:
                            return _mark_proxy_in_use(ctx, thread_name, selected)
            finally:
                release_proxy_fetch_lock(ctx)

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
        retained = deque()
        pool = _ensure_proxy_pool_deque_locked(ctx)
        while pool:
            item = pool.popleft()
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


