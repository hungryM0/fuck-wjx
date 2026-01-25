import logging
from typing import Any, Optional, Tuple

import wjx.core.state as state
from wjx.network.random_ip import _fetch_new_proxy_batch, _mask_proxy_for_log
from wjx.utils.io.load_save import _select_user_agent_from_keys


def _record_bad_proxy_and_maybe_pause(gui_instance: Optional[Any]) -> bool:
    """
    记录连续无效代理次数；达到阈值时暂停执行以避免继续消耗代理 API 额度。
    返回 True 表示已触发暂停。
    """
    with state.lock:
        state._consecutive_bad_proxy_count += 1
        streak = int(state._consecutive_bad_proxy_count)
    if streak >= int(state.MAX_CONSECUTIVE_BAD_PROXIES):
        reason = f"代理连续{state.MAX_CONSECUTIVE_BAD_PROXIES}次不可用，已暂停以防继续扣费"
        logging.warning(reason)
        try:
            if gui_instance and hasattr(gui_instance, "pause_run"):
                gui_instance.pause_run(reason)
        except Exception:
            pass
        return True
    return False


def _reset_bad_proxy_streak() -> None:
    with state.lock:
        state._consecutive_bad_proxy_count = 0


def _select_proxy_for_session() -> Optional[str]:
    if not state.random_proxy_ip_enabled:
        return None
    with state.lock:
        if state.proxy_ip_pool:
            return state.proxy_ip_pool.pop(0)

    # 代理池为空时，使用全局 fetch 锁避免多线程并发重复请求代理 API（会快速耗尽额度）
    with state._proxy_fetch_lock:
        with state.lock:
            if state.proxy_ip_pool:
                return state.proxy_ip_pool.pop(0)

        expected = max(1, int(state.num_threads or 1))
        try:
            fetched = _fetch_new_proxy_batch(expected_count=expected, stop_signal=state.stop_event)
        except Exception as exc:
            logging.warning(f"获取随机代理失败：{exc}")
            return None
        if not fetched:
            return None

        extra = fetched[1:]
        if extra:
            with state.lock:
                for proxy in extra:
                    if proxy not in state.proxy_ip_pool:
                        state.proxy_ip_pool.append(proxy)
        return fetched[0]


def _select_user_agent_for_session() -> Tuple[Optional[str], Optional[str]]:
    if not state.random_user_agent_enabled:
        return None, None
    return _select_user_agent_from_keys(state.user_agent_pool_keys)


def _discard_unresponsive_proxy(proxy_address: str) -> None:
    if not proxy_address:
        return
    with state.lock:
        try:
            state.proxy_ip_pool.remove(proxy_address)
            logging.debug(f"已移除无响应代理：{_mask_proxy_for_log(proxy_address)}")
        except ValueError:
            pass
