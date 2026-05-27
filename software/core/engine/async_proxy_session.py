"""异步运行槽位的代理与 UA 会话辅助。"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from software.core.engine.runtime_ui_bridge import RuntimeUiBridge
from software.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.pool import is_proxy_responsive_async
from software.network.session_policy import (
    _discard_unresponsive_proxy,
    _record_bad_proxy_and_maybe_pause,
    _select_proxy_for_session_async,
    _select_user_agent_for_session,
)


class AsyncProxySession:
    """管理单个运行槽位当前轮次的代理和 UA。"""

    def __init__(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        slot_label: str,
        stop_signal: StopSignalLike,
        runtime_bridge: RuntimeUiBridge | None,
        update_step: Callable[[str], None],
    ) -> None:
        self.config = config
        self.state = state
        self.slot_label = slot_label
        self.stop_signal = stop_signal
        self.runtime_bridge = runtime_bridge
        self.update_step = update_step
        self.proxy_address: Optional[str] = None

    async def select_proxy_and_user_agent(self) -> tuple[Optional[str], Optional[str]]:
        should_wait_for_proxy = bool(self.config.random_proxy_ip_enabled)
        if self.config.random_proxy_ip_enabled:
            self.update_step("获取代理")
        proxy_address = await _select_proxy_for_session_async(
            self.state,
            self.slot_label,
            stop_signal=self.stop_signal,
            wait=should_wait_for_proxy,
        )
        if self.config.random_proxy_ip_enabled and not proxy_address:
            if _record_bad_proxy_and_maybe_pause(self.state, self.runtime_bridge):
                return None, None
        if proxy_address and not await is_proxy_responsive_async(proxy_address):
            logging.warning("提取到的代理质量过低，自动弃用更换下一个")
            _discard_unresponsive_proxy(self.state, proxy_address)
            self.state.release_proxy_in_use(self.slot_label)
            return None, None
        ua_value, _ = _select_user_agent_for_session(self.state)
        self.proxy_address = proxy_address
        return proxy_address, ua_value

    def mark_successful_proxy(self) -> None:
        if not self.proxy_address:
            return
        try:
            self.state.mark_successful_proxy_address(self.proxy_address)
        except Exception:
            logging.info("记录成功代理失败：%s", self.proxy_address, exc_info=True)

    def release_current_proxy(self) -> None:
        if self.proxy_address:
            try:
                self.state.release_proxy_in_use(self.slot_label)
            except Exception:
                logging.info("释放代理占用失败", exc_info=True)
        self.proxy_address = None


__all__ = ["AsyncProxySession"]
