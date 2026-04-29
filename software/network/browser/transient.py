"""浏览器会话工厂：临时启动与常驻底座上下文创建。"""

from __future__ import annotations

import logging
import subprocess
import traceback
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from software.app.config import BROWSER_PREFERENCE
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.manager import BrowserManager, create_browser_manager
from software.network.browser.options import (
    _build_context_args,
    _build_launch_args,
    _is_browser_disconnected_error,
)
from software.network.browser.session import BrowserDriver, PlaywrightDriver
from software.network.browser.startup import (
    _PW_START_LOCK,
    _format_exception_chain,
    _start_playwright_runtime,
    classify_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.proxy.pool import normalize_proxy_address

if TYPE_CHECKING:
    from playwright.sync_api import Playwright


def list_browser_pids() -> Set[int]:
    """列出当前运行的浏览器进程 PID（仅 Windows）。"""
    names = ("chrome.exe", "msedge.exe")
    pids: Set[int] = set()
    _no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    for name in names:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_no_window,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        pids.add(int(parts[1]))
                    except (ValueError, IndexError):
                        continue
        except Exception:
            continue
    return pids


def _create_transient_driver(
    *,
    headless: bool,
    prefer_browsers: Optional[List[str]],
    proxy_address: Optional[str],
    user_agent: Optional[str],
    window_position: Optional[Tuple[int, int]],
) -> Tuple[BrowserDriver, str]:
    candidates = prefer_browsers or list(BROWSER_PREFERENCE)
    if not candidates:
        candidates = list(BROWSER_PREFERENCE)

    normalized_proxy = normalize_proxy_address(proxy_address)
    last_exc: Optional[Exception] = None

    for browser_name in candidates:
        pw: Optional[Playwright] = None
        try:
            launch_args = _build_launch_args(
                browser_name=browser_name,
                headless=headless,
                window_position=window_position,
                append_no_proxy=not bool(normalized_proxy),
            )
            with _PW_START_LOCK:
                pw = _start_playwright_runtime()
                browser = pw.chromium.launch(**launch_args)

            context_args = _build_context_args(
                headless=headless,
                proxy_address=normalized_proxy,
                user_agent=user_agent,
            )
            context = browser.new_context(**context_args)
            page = context.new_page()
            driver = PlaywrightDriver(
                context=context,
                page=page,
                browser_name=browser_name,
                browser=browser,
                playwright_instance=pw,
                manager=None,
                manager_owned=False,
            )
            return driver, browser_name
        except Exception as exc:
            last_exc = exc
            logging.warning("启动临时 %s 浏览器失败: %s", browser_name, exc)
            logging.error(
                "[Action Log] 临时浏览器初始化异常链(%s): %s",
                browser_name,
                _format_exception_chain(exc),
            )
            logging.error(
                "[Action Log] 临时浏览器初始化堆栈(%s):\n%s",
                browser_name,
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
            if pw is not None:
                try:
                    pw.stop()
                except Exception as stop_exc:
                    log_suppressed_exception("browser_transient._create_transient_driver pw.stop", stop_exc, level=logging.WARNING)
            if is_playwright_startup_environment_error(exc):
                break

    friendly = classify_playwright_startup_error(last_exc).message if last_exc is not None else "未知错误"
    if last_exc is not None:
        raise RuntimeError(f"无法启动任何浏览器: {friendly}") from last_exc
    raise RuntimeError(f"无法启动任何浏览器: {friendly}")


def create_playwright_driver(
    *,
    headless: bool = False,
    prefer_browsers: Optional[List[str]] = None,
    proxy_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    window_position: Optional[Tuple[int, int]] = None,
    manager: Optional[BrowserManager] = None,
    persistent_browser: bool = True,
    transient_launch: bool = False,
) -> Tuple[BrowserDriver, str]:
    if transient_launch:
        persistent_browser = False

    if not persistent_browser:
        return _create_transient_driver(
            headless=headless,
            prefer_browsers=prefer_browsers,
            proxy_address=proxy_address,
            user_agent=user_agent,
            window_position=window_position,
        )

    manager_owned = False
    manager_instance = manager
    if manager_instance is None:
        manager_instance = create_browser_manager(
            prefer_browsers=prefer_browsers,
            headless=headless,
            window_position=window_position,
        )
        manager_owned = True

    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            context, page, browser_name, browser = manager_instance.new_context_session(
                proxy_address=proxy_address,
                user_agent=user_agent,
                headless=headless,
                prefer_browsers=prefer_browsers,
                window_position=window_position,
            )
            driver = PlaywrightDriver(
                context=context,
                page=page,
                browser_name=browser_name,
                browser=browser,
                manager=manager_instance,
                manager_owned=manager_owned,
            )
            return driver, browser_name
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _is_browser_disconnected_error(exc):
                logging.warning("检测到底座浏览器断开，尝试重建并重试一次: %s", exc)
                try:
                    manager_instance.restart_browser(
                        prefer_browsers=prefer_browsers,
                        headless=headless,
                        window_position=window_position,
                    )
                    continue
                except Exception as restart_exc:
                    last_exc = restart_exc
            break

    friendly = classify_playwright_startup_error(last_exc).message if last_exc is not None else "未知错误"
    if last_exc is not None:
        raise RuntimeError(f"创建浏览器上下文失败: {friendly}") from last_exc
    raise RuntimeError(f"创建浏览器上下文失败: {friendly}")


__all__ = [
    "_create_transient_driver",
    "create_playwright_driver",
    "list_browser_pids",
]
