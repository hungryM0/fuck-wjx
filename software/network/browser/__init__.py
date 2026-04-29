"""浏览器驱动子包。"""
from __future__ import annotations

from software.network.browser.driver import (
    By,
    BROWSER_STARTUP_ERROR_ENVIRONMENT,
    BROWSER_STARTUP_ERROR_LAUNCH,
    BrowserManager,
    BrowserDriver,
    BrowserStartupErrorInfo,
    NoSuchElementException,
    PlaywrightDriver,
    PlaywrightElement,
    ProxyConnectionError,
    TimeoutException,
    classify_playwright_startup_error,
    create_browser_manager,
    create_playwright_driver,
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
    list_browser_pids,
    shutdown_browser_manager,
)

__all__ = [
    "By",
    "BROWSER_STARTUP_ERROR_ENVIRONMENT",
    "BROWSER_STARTUP_ERROR_LAUNCH",
    "BrowserManager",
    "BrowserDriver",
    "BrowserStartupErrorInfo",
    "NoSuchElementException",
    "PlaywrightDriver",
    "PlaywrightElement",
    "ProxyConnectionError",
    "TimeoutException",
    "classify_playwright_startup_error",
    "create_browser_manager",
    "create_playwright_driver",
    "describe_playwright_startup_error",
    "is_playwright_startup_environment_error",
    "list_browser_pids",
    "shutdown_browser_manager",
]


