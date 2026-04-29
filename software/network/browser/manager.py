"""Playwright BrowserManager：每个工作线程复用一个浏览器底座。"""

from __future__ import annotations

import logging
import threading
import traceback
from typing import TYPE_CHECKING, List, Optional, Tuple

from software.app.config import BROWSER_PREFERENCE
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.options import _build_context_args, _build_launch_args
from software.network.browser.startup import (
    _PW_START_LOCK,
    _format_exception_chain,
    _start_playwright_runtime,
    classify_playwright_startup_error,
    is_playwright_startup_environment_error,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """每个工作线程独立持有一个 Playwright + Browser 底座。"""

    def __init__(
        self,
        *,
        prefer_browsers: Optional[List[str]] = None,
        headless: bool = False,
        window_position: Optional[Tuple[int, int]] = None,
    ):
        self._lock = threading.RLock()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._browser_name: Optional[str] = None
        self._prefer_browsers = list(prefer_browsers or BROWSER_PREFERENCE)
        self._headless = bool(headless)
        self._window_position = window_position
        self._closed = False

    @property
    def browser_name(self) -> str:
        return str(self._browser_name or "")

    def is_browser_alive(self) -> bool:
        with self._lock:
            browser = self._browser
            if browser is None:
                return False
            try:
                checker = getattr(browser, "is_connected", None)
                if callable(checker):
                    return bool(checker())
            except Exception:
                return False
            try:
                _ = browser.contexts
                return True
            except Exception:
                return False

    def ensure_browser(
        self,
        *,
        prefer_browsers: Optional[List[str]] = None,
        headless: Optional[bool] = None,
        window_position: Optional[Tuple[int, int]] = None,
        force_restart: bool = False,
    ) -> Tuple[Browser, str]:
        with self._lock:
            if self._closed:
                raise RuntimeError("BrowserManager 已关闭，不能继续创建浏览器会话")

            if prefer_browsers:
                self._prefer_browsers = list(prefer_browsers)
            if headless is not None:
                self._headless = bool(headless)
            if window_position is not None:
                self._window_position = window_position

            if not force_restart and self.is_browser_alive():
                assert self._browser is not None
                return self._browser, str(self._browser_name or "")

            self._shutdown_locked()
            return self._launch_locked()

    def restart_browser(
        self,
        *,
        prefer_browsers: Optional[List[str]] = None,
        headless: Optional[bool] = None,
        window_position: Optional[Tuple[int, int]] = None,
    ) -> Tuple[Browser, str]:
        return self.ensure_browser(
            prefer_browsers=prefer_browsers,
            headless=headless,
            window_position=window_position,
            force_restart=True,
        )

    def new_context_session(
        self,
        *,
        proxy_address: Optional[str],
        user_agent: Optional[str],
        headless: Optional[bool] = None,
        prefer_browsers: Optional[List[str]] = None,
        window_position: Optional[Tuple[int, int]] = None,
    ) -> Tuple[BrowserContext, Page, str, Browser]:
        browser, browser_name = self.ensure_browser(
            prefer_browsers=prefer_browsers,
            headless=headless,
            window_position=window_position,
            force_restart=False,
        )
        context_args = _build_context_args(
            headless=self._headless if headless is None else bool(headless),
            proxy_address=proxy_address,
            user_agent=user_agent,
        )
        context = browser.new_context(**context_args)
        page = context.new_page()
        return context, page, browser_name, browser

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._shutdown_locked()

    def _launch_locked(self) -> Tuple[Browser, str]:
        candidates = list(self._prefer_browsers or BROWSER_PREFERENCE)
        if not candidates:
            candidates = list(BROWSER_PREFERENCE)

        last_exc: Optional[Exception] = None
        for browser_name in candidates:
            pw: Optional[Playwright] = None
            launch_args = _build_launch_args(
                browser_name=browser_name,
                headless=self._headless,
                window_position=self._window_position,
                append_no_proxy=False,
            )
            try:
                with _PW_START_LOCK:
                    pw = _start_playwright_runtime()
                    browser = pw.chromium.launch(**launch_args)
                self._playwright = pw
                self._browser = browser
                self._browser_name = browser_name
                logging.info("[Action Log] BrowserManager 启动底座成功：%s", browser_name)
                return browser, browser_name
            except Exception as exc:
                last_exc = exc
                logging.warning("BrowserManager 启动 %s 失败: %s", browser_name, exc)
                logging.error(
                    "[Action Log] BrowserManager 启动异常链(%s): %s",
                    browser_name,
                    _format_exception_chain(exc),
                )
                logging.error(
                    "[Action Log] BrowserManager 启动堆栈(%s):\n%s",
                    browser_name,
                    "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                )
                if pw is not None:
                    try:
                        pw.stop()
                    except Exception as stop_exc:
                        log_suppressed_exception("BrowserManager._launch_locked pw.stop", stop_exc, level=logging.WARNING)
                if is_playwright_startup_environment_error(exc):
                    break

        friendly = classify_playwright_startup_error(last_exc).message if last_exc is not None else "未知错误"
        if last_exc is not None:
            raise RuntimeError(f"BrowserManager 无法启动任何浏览器: {friendly}") from last_exc
        raise RuntimeError(f"BrowserManager 无法启动任何浏览器: {friendly}")

    def _shutdown_locked(self) -> None:
        browser = self._browser
        playwright_instance = self._playwright
        self._browser = None
        self._playwright = None
        self._browser_name = None

        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                log_suppressed_exception("BrowserManager._shutdown_locked browser.close", exc, level=logging.WARNING)
        if playwright_instance is not None:
            try:
                playwright_instance.stop()
            except Exception as exc:
                log_suppressed_exception("BrowserManager._shutdown_locked playwright.stop", exc, level=logging.WARNING)


def create_browser_manager(
    *,
    prefer_browsers: Optional[List[str]] = None,
    headless: bool = False,
    window_position: Optional[Tuple[int, int]] = None,
) -> BrowserManager:
    """创建每线程独立 BrowserManager。默认懒启动。"""
    return BrowserManager(
        prefer_browsers=prefer_browsers,
        headless=headless,
        window_position=window_position,
    )


def shutdown_browser_manager(manager: Optional[BrowserManager]) -> None:
    if manager is None:
        return
    try:
        manager.shutdown()
    except Exception as exc:
        log_suppressed_exception("browser_manager.shutdown_browser_manager", exc, level=logging.WARNING)


__all__ = [
    "BrowserManager",
    "create_browser_manager",
    "shutdown_browser_manager",
]
