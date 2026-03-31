"""浏览器驱动工厂 - 创建和配置 Playwright 浏览器实例"""
from typing import List, Optional, Tuple

from software.network.browser import (
    BrowserDriver,
    BrowserManager,
    create_browser_manager as _create_browser_manager,
    create_playwright_driver as _browser_create_playwright_driver,
    shutdown_browser_manager as _shutdown_browser_manager,
)


def create_browser_manager(
    *,
    headless: bool = False,
    prefer_browsers: Optional[List[str]] = None,
    window_position: Optional[Tuple[int, int]] = None,
) -> BrowserManager:
    return _create_browser_manager(
        headless=headless,
        prefer_browsers=prefer_browsers,
        window_position=window_position,
    )


def shutdown_browser_manager(manager: Optional[BrowserManager]) -> None:
    _shutdown_browser_manager(manager)


def create_playwright_driver(
    headless: bool = False,
    prefer_browsers: Optional[List[str]] = None,
    proxy_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    window_position: Optional[Tuple[int, int]] = None,
    manager: Optional[BrowserManager] = None,
    persistent_browser: bool = True,
    transient_launch: bool = False,
) -> Tuple[BrowserDriver, str]:
    """Delegate to browser implementation (Playwright-only)."""
    return _browser_create_playwright_driver(
        headless=headless,
        prefer_browsers=prefer_browsers,
        proxy_address=proxy_address,
        user_agent=user_agent,
        window_position=window_position,
        manager=manager,
        persistent_browser=persistent_browser,
        transient_launch=transient_launch,
    )


