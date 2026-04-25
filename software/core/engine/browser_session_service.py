"""浏览器会话服务。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from software.core.engine.driver_factory import (
    create_browser_manager,
    create_playwright_driver,
    shutdown_browser_manager,
)
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser import BrowserDriver, BrowserManager
from software.network.proxy.pool import is_proxy_responsive
from software.network.session_policy import (
    _discard_unresponsive_proxy,
    _record_bad_proxy_and_maybe_pause,
    _select_proxy_for_session,
    _select_user_agent_for_session,
)

_HEADED_RUNTIME_WINDOW_SIZE = (550, 650)


def _resolve_runtime_window_size(config: ExecutionConfig) -> Optional[tuple[int, int]]:
    """无头模式保留较大视口，避免部分站点在小视口下退化为空白页。"""
    if bool(getattr(config, "headless_mode", False)):
        return None
    return _HEADED_RUNTIME_WINDOW_SIZE


class BrowserSessionService:
    """封装单次浏览器会话的创建、注册、销毁逻辑。"""

    def __init__(self, config: ExecutionConfig, state: ExecutionState, gui_instance: Any, thread_name: str):
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.thread_name = str(thread_name or "").strip()
        self.driver: Optional[BrowserDriver] = None
        self._browser_manager: Optional[BrowserManager] = None
        self.proxy_address: Optional[str] = None
        self.sem_acquired = False
        self._browser_sem = state.get_browser_semaphore(max(1, int(config.num_threads or 1)))

    def _register_driver(self, instance: BrowserDriver) -> None:
        if self.gui_instance and hasattr(self.gui_instance, "active_drivers"):
            self.gui_instance.active_drivers.append(instance)

    def _unregister_driver(self, instance: BrowserDriver) -> None:
        if self.gui_instance and hasattr(self.gui_instance, "active_drivers"):
            try:
                self.gui_instance.active_drivers.remove(instance)
            except ValueError as exc:
                log_suppressed_exception("BrowserSessionService._unregister_driver remove", exc, level=logging.WARNING)

    def dispose(self) -> None:
        if not self.driver:
            if self.thread_name:
                self.state.release_proxy_in_use(self.thread_name)
                self.proxy_address = None
            if self.sem_acquired:
                try:
                    self._browser_sem.release()
                    self.sem_acquired = False
                    logging.info("已释放浏览器信号量（无浏览器实例）")
                except Exception as exc:
                    log_suppressed_exception("BrowserSessionService.dispose release semaphore (no driver)", exc, level=logging.WARNING)
            return

        if not self.driver.mark_cleanup_done():
            logging.info("浏览器实例已被其他线程清理，跳过")
            self.driver = None
            if self.sem_acquired:
                self._browser_sem.release()
                self.sem_acquired = False
            return

        driver_instance = self.driver
        self._unregister_driver(driver_instance)
        self.driver = None
        try:
            driver_instance.quit()
            logging.info("已关闭浏览器 context/page")
        except Exception as exc:
            log_suppressed_exception("BrowserSessionService.dispose driver.quit", exc, level=logging.WARNING)

        if self.thread_name:
            self.state.release_proxy_in_use(self.thread_name)
        self.proxy_address = None

        if self.sem_acquired:
            try:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.info("已释放浏览器信号量")
            except Exception as exc:
                log_suppressed_exception("BrowserSessionService.dispose release semaphore", exc, level=logging.WARNING)

    def shutdown(self) -> None:
        self.dispose()
        if self._browser_manager is not None:
            try:
                shutdown_browser_manager(self._browser_manager)
                logging.info("已关闭 BrowserManager 底座")
            except Exception as exc:
                log_suppressed_exception("BrowserSessionService.shutdown manager.close", exc, level=logging.WARNING)
            finally:
                self._browser_manager = None

    def create_browser(self, preferred_browsers: list, window_x_pos: int, window_y_pos: int) -> Optional[str]:
        self.proxy_address = _select_proxy_for_session(self.state, self.thread_name)
        if self.config.random_proxy_ip_enabled and not self.proxy_address:
            if _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
                return None

        if self.proxy_address and not is_proxy_responsive(self.proxy_address):
            logging.warning("提取到的代理质量过低，自动弃用更换下一个")
            _discard_unresponsive_proxy(self.state, self.proxy_address)
            if self.thread_name:
                self.state.release_proxy_in_use(self.thread_name)
            self.proxy_address = None
            if self.config.random_proxy_ip_enabled:
                _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance)
            return None

        browser_proxy_address = self.proxy_address
        submit_proxy_address = None
        if self.config.headless_mode and self.proxy_address:
            browser_proxy_address = None
            submit_proxy_address = self.proxy_address

        ua_value, _ = _select_user_agent_for_session(self.state)
        if not self.sem_acquired:
            self._browser_sem.acquire()
            self.sem_acquired = True
            logging.info("已获取浏览器信号量")

        try:
            if self._browser_manager is None:
                self._browser_manager = create_browser_manager(
                    headless=self.config.headless_mode,
                    prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                    window_position=(window_x_pos, window_y_pos),
                )
            self.driver, active_browser = create_playwright_driver(
                headless=self.config.headless_mode,
                prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                proxy_address=browser_proxy_address,
                user_agent=ua_value,
                window_position=(window_x_pos, window_y_pos),
                manager=self._browser_manager,
                persistent_browser=True,
            )
        except Exception:
            if self.sem_acquired:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.info("创建浏览器失败，已释放信号量")
            if self.thread_name:
                self.state.release_proxy_in_use(self.thread_name)
            self.proxy_address = None
            raise

        self._register_driver(self.driver)
        setattr(self.driver, "_submit_proxy_address", submit_proxy_address)
        runtime_window_size = _resolve_runtime_window_size(self.config)
        if runtime_window_size is not None:
            width, height = runtime_window_size
            self.driver.set_window_size(width, height)
        return active_browser


__all__ = ["BrowserSessionService"]
