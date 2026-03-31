"""会话策略 - 代理切换与浏览器实例复用逻辑"""
from typing import Any, Optional, Tuple
import logging

from software.core.task import ProxyLease, TaskContext
from software.network.proxy.pool import coerce_proxy_lease, mask_proxy_for_log
from software.network.proxy.api import fetch_proxy_batch
from software.network.proxy import get_proxy_required_ttl_seconds, proxy_lease_has_sufficient_ttl
from software.io.config import _select_user_agent_from_ratios
def _record_bad_proxy_and_maybe_pause(
    ctx: TaskContext,
    gui_instance: Optional[Any],
) -> bool:
    """
    记录代理不可用事件。
    现阶段不再根据代理异常次数自动暂停任务，统一由提交连续失败止损控制。
    """
    _ = ctx, gui_instance
    return False


def _required_proxy_ttl_seconds(ctx: TaskContext) -> int:
    return int(get_proxy_required_ttl_seconds(getattr(ctx, "answer_duration_range_seconds", (0, 0))))


def _purge_unusable_proxy_pool_locked(ctx: TaskContext) -> None:
    required_ttl = _required_proxy_ttl_seconds(ctx)
    kept = []
    seen = set()
    removed = 0
    for item in list(ctx.proxy_ip_pool or []):
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
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            removed += 1
            logging.info("已丢弃即将过期的代理：%s", mask_proxy_for_log(lease.address))
            continue
        seen.add(lease.address)
        kept.append(lease)
    if removed:
        logging.info("代理池已清理无效/重复代理 %s 个", removed)
    ctx.proxy_ip_pool = kept


def _pop_available_proxy_lease_locked(ctx: TaskContext) -> Optional[ProxyLease]:
    _purge_unusable_proxy_pool_locked(ctx)
    while ctx.proxy_ip_pool:
        lease = coerce_proxy_lease(ctx.proxy_ip_pool.pop(0))
        if lease is None:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=_required_proxy_ttl_seconds(ctx)):
            logging.info("已跳过即将过期的代理：%s", mask_proxy_for_log(lease.address))
            continue
        return lease
    return None


def _mark_proxy_in_use(ctx: TaskContext, thread_name: str, lease: Optional[ProxyLease]) -> Optional[str]:
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


def _resolve_proxy_request_num_locked(ctx: TaskContext) -> int:
    waiting_count = max(1, int(ctx.proxy_waiting_threads or 0))
    active_count = len(ctx.proxy_in_use_by_thread)
    remaining_to_start = max(0, int(ctx.target_num or 0) - int(ctx.cur_num or 0) - active_count)
    if remaining_to_start <= 0:
        return 0
    return max(1, min(waiting_count, remaining_to_start, 80))


def _select_proxy_for_session(ctx: TaskContext, thread_name: str = "") -> Optional[str]:
    if not ctx.random_proxy_ip_enabled:
        return None
    selected: Optional[ProxyLease] = None
    with ctx.lock:
        selected = _pop_available_proxy_lease_locked(ctx)
    if selected is not None:
        return _mark_proxy_in_use(ctx, thread_name, selected)

    ctx.register_proxy_waiter()
    try:
        with ctx.lock:
            selected = _pop_available_proxy_lease_locked(ctx)
        if selected is not None:
            return _mark_proxy_in_use(ctx, thread_name, selected)

        # 代理池为空时，使用全局 fetch 锁避免多线程并发重复请求代理 API（会快速耗尽额度）
        with ctx._proxy_fetch_lock:
            with ctx.lock:
                selected = _pop_available_proxy_lease_locked(ctx)
                if selected is None:
                    request_num = _resolve_proxy_request_num_locked(ctx)
                else:
                    request_num = 0
            if selected is not None:
                return _mark_proxy_in_use(ctx, thread_name, selected)

            if request_num <= 0:
                return None

            try:
                fetched = fetch_proxy_batch(expected_count=request_num, stop_signal=ctx.stop_event)
            except Exception as exc:
                logging.warning(f"获取随机代理失败：{exc}")
                return None
            if not fetched:
                return None

            selected: Optional[ProxyLease] = None
            with ctx.lock:
                _purge_unusable_proxy_pool_locked(ctx)
                _pool_leases = [coerce_proxy_lease(item) for item in ctx.proxy_ip_pool]
                existing = {lease.address for lease in _pool_leases if lease is not None}
                required_ttl = _required_proxy_ttl_seconds(ctx)
                for item in fetched:
                    lease = coerce_proxy_lease(item)
                    if lease is None:
                        continue
                    if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
                        logging.info("已丢弃即将过期的新代理：%s", mask_proxy_for_log(lease.address))
                        continue
                    if selected is None:
                        selected = lease
                        continue
                    if not lease.poolable or lease.address in existing:
                        continue
                    ctx.proxy_ip_pool.append(lease)
                    existing.add(lease.address)
            return _mark_proxy_in_use(ctx, thread_name, selected)
    finally:
        ctx.unregister_proxy_waiter()


def _select_user_agent_for_session(ctx: TaskContext) -> Tuple[Optional[str], Optional[str]]:
    if not ctx.random_user_agent_enabled:
        return None, None
    return _select_user_agent_from_ratios(ctx.user_agent_ratios)


def _discard_unresponsive_proxy(ctx: TaskContext, proxy_address: str) -> None:
    if not proxy_address:
        return
    with ctx.lock:
        removed = False
        normalized = str(proxy_address or "").strip()
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
        if removed:
            logging.info(f"已移除无响应代理：{mask_proxy_for_log(proxy_address)}")


