"""浏览器驱动稳定门面。

具体实现拆在同目录下的 manager / session / element / transient 等模块中，
本文件只保留旧 import 路径，避免业务代码跟着迁移。
"""

from __future__ import annotations

from software.network.browser.element import PlaywrightElement
from software.network.browser.exceptions import (
    By,
    NoSuchElementException,
    ProxyConnectionError,
    TimeoutException,
)
from software.network.browser.manager import (
    BrowserManager,
    create_browser_manager,
    shutdown_browser_manager,
)
from software.network.browser.session import BrowserDriver, PlaywrightDriver
from software.network.browser.startup import (
    BROWSER_STARTUP_ERROR_ENVIRONMENT,
    BROWSER_STARTUP_ERROR_LAUNCH,
    BrowserStartupErrorInfo,
    classify_playwright_startup_error,
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.browser.transient import (
    _create_transient_driver,
    create_playwright_driver,
    list_browser_pids,
)

__all__ = [
    "By",
    "BrowserManager",
    "BrowserDriver",
    "BROWSER_STARTUP_ERROR_ENVIRONMENT",
    "BROWSER_STARTUP_ERROR_LAUNCH",
    "BrowserStartupErrorInfo",
    "NoSuchElementException",
    "PlaywrightDriver",
    "PlaywrightElement",
    "ProxyConnectionError",
    "TimeoutException",
    "_create_transient_driver",
    "classify_playwright_startup_error",
    "create_browser_manager",
    "create_playwright_driver",
    "describe_playwright_startup_error",
    "is_playwright_startup_environment_error",
    "list_browser_pids",
    "shutdown_browser_manager",
]
