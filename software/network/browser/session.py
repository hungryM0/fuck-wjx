"""PlaywrightDriver：页面会话与清理逻辑。"""

from __future__ import annotations

import logging
import random
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Dict, Literal, Optional, Set

from software.logging.log_utils import log_suppressed_exception
from software.network.browser.element import PlaywrightElement
from software.network.browser.exceptions import NoSuchElementException, ProxyConnectionError
from software.network.browser.options import _build_selector, _is_proxy_tunnel_error
from software.network.browser.startup import _load_playwright_sync

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright
    from software.network.browser.manager import BrowserManager


class PlaywrightDriver:
    def __init__(
        self,
        *,
        context: BrowserContext,
        page: Page,
        browser_name: str,
        browser: Optional[Browser] = None,
        playwright_instance: Optional[Playwright] = None,
        manager: Optional[BrowserManager] = None,
        manager_owned: bool = False,
    ):
        self._context = context
        self._page = page
        self._browser = browser
        self._playwright = playwright_instance
        self._browser_manager = manager
        self._manager_owned = manager_owned
        self.browser_name = browser_name
        self.session_id = f"pw-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        self.browser_pid = self._extract_browser_pid(browser)
        self.browser_pids: Set[int] = {self.browser_pid} if self.browser_pid else set()
        self._owner_thread_id = threading.get_ident()
        self._owner_thread_name = threading.current_thread().name or "UnnamedThread"
        self._cleanup_done = False
        self._cleanup_lock = threading.Lock()

    @staticmethod
    def _extract_browser_pid(browser: Optional[Browser]) -> Optional[int]:
        if browser is None:
            return None
        try:
            proc = getattr(browser, "process", None)
            return int(proc.pid) if proc and getattr(proc, "pid", None) else None
        except Exception:
            return None

    def find_element(self, by: str, value: str):
        handle = self._page.query_selector(_build_selector(by, value))
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightElement(handle, self._page)

    def find_elements(self, by: str, value: str):
        handles = self._page.query_selector_all(_build_selector(by, value))
        return [PlaywrightElement(h, self._page) for h in handles]

    def execute_script(self, script: str, *args):
        processed_args = [arg._handle if isinstance(arg, PlaywrightElement) else arg for arg in args]
        try:
            wrapper = (
                "(args) => {"
                "  const fn = function(){"
                + script
                + "  };"
                "  return fn.apply(null, Array.isArray(args) ? args : []);"
                "}"
            )
            return self._page.evaluate(wrapper, processed_args)
        except Exception as exc:
            logging.info("execute_script failed: %s", exc)
            return None

    def get(
        self,
        url: str,
        timeout: int = 20000,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded",
    ) -> None:
        _, playwright_timeout_error = _load_playwright_sync()
        try:
            self._page.set_default_navigation_timeout(timeout)
            self._page.set_default_timeout(timeout)
        except Exception as exc:
            log_suppressed_exception("browser_session.PlaywrightDriver.get set timeouts", exc, level=logging.WARNING)

        try:
            self._page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except playwright_timeout_error as exc:
            logging.info("Page.goto timeout after %d ms: %s", timeout, exc)
            raise
        except Exception as exc:
            if _is_proxy_tunnel_error(exc):
                logging.info("Page.goto proxy tunnel failure: %s", exc)
                raise ProxyConnectionError(str(exc)) from exc
            raise

    @property
    def current_url(self) -> str:
        return self._page.url

    @property
    def page(self) -> Page:
        return self._page

    @property
    def page_source(self) -> str:
        try:
            return self._page.content()
        except Exception:
            return ""

    @property
    def title(self) -> str:
        try:
            return self._page.title()
        except Exception:
            return ""

    def set_window_size(self, width: int, height: int) -> None:
        try:
            self._page.set_viewport_size({"width": width, "height": height})
        except Exception as exc:
            log_suppressed_exception("browser_session.PlaywrightDriver.set_window_size", exc, level=logging.WARNING)

    def refresh(self) -> None:
        try:
            self._page.reload(wait_until="domcontentloaded")
        except Exception as exc:
            log_suppressed_exception("browser_session.PlaywrightDriver.refresh", exc, level=logging.WARNING)

    def mark_cleanup_done(self) -> bool:
        """标记清理已完成，返回 True 表示可以执行清理，False 表示已被其他线程清理过。"""
        with self._cleanup_lock:
            if self._cleanup_done:
                return False
            self._cleanup_done = True
            return True

    def _is_owner_thread(self) -> bool:
        return threading.get_ident() == self._owner_thread_id

    def _force_terminate_browser_process_tree(self) -> bool:
        pids: Set[int] = set(int(pid) for pid in self.browser_pids if pid)
        current_pid = self._extract_browser_pid(self._browser)
        if current_pid:
            pids.add(current_pid)
        if not pids:
            return False

        _no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        terminated = False
        for pid in sorted(pids):
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=_no_window,
                )
            except Exception as exc:
                log_suppressed_exception(
                    "browser_session.PlaywrightDriver._force_terminate_browser_process_tree taskkill",
                    exc,
                    level=logging.WARNING,
                )
                continue

            output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
            if result.returncode == 0:
                terminated = True
                continue
            if "not found" in output or "没有运行的任务" in output or "找不到进程" in output:
                terminated = True
                continue
            logging.warning("跨线程强制关闭浏览器进程失败(pid=%s): %s", pid, output.strip() or f"returncode={result.returncode}")
        return terminated

    def quit(self) -> None:
        """默认仅关闭 page/context；若驱动独占底座则附带关闭底座。"""
        if not self._is_owner_thread():
            current_thread = threading.current_thread().name or "UnnamedThread"
            logging.warning(
                "检测到跨线程清理 PlaywrightDriver，跳过 sync_api 关闭以避免 greenlet 线程炸裂: owner=%s current=%s",
                self._owner_thread_name,
                current_thread,
            )
            self._force_terminate_browser_process_tree()
            return
        try:
            self._page.close()
        except Exception as exc:
            log_suppressed_exception("browser_session.PlaywrightDriver.quit page.close", exc, level=logging.WARNING)
        try:
            self._context.close()
        except Exception as exc:
            log_suppressed_exception("browser_session.PlaywrightDriver.quit context.close", exc, level=logging.WARNING)

        if self._manager_owned and self._browser_manager is not None:
            try:
                self._browser_manager.shutdown()
            except Exception as exc:
                log_suppressed_exception("browser_session.PlaywrightDriver.quit manager.shutdown", exc, level=logging.WARNING)
            return

        if self._browser is not None and self._playwright is not None:
            try:
                self._browser.close()
            except Exception as exc:
                log_suppressed_exception("browser_session.PlaywrightDriver.quit browser.close", exc, level=logging.WARNING)
            try:
                self._playwright.stop()
            except Exception as exc:
                log_suppressed_exception("browser_session.PlaywrightDriver.quit playwright.stop", exc, level=logging.WARNING)


BrowserDriver = PlaywrightDriver


__all__ = ["BrowserDriver", "PlaywrightDriver"]
