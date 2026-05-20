"""Pure async browser owner/context pool."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from software.app.config import BROWSER_PREFERENCE
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.options import (
    _build_context_args,
    _build_launch_args,
    _is_browser_disconnected_error,
)
from software.network.browser.pool_config import (
    BrowserPoolConfig,
    DEFAULT_HEADED_CONTEXTS_PER_BROWSER,
    DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER,
)
from software.network.browser.runtime_async import PlaywrightAsyncDriver
from software.network.browser.startup import (
    BrowserStartupRuntimeError,
    _format_exception_chain,
    _start_playwright_async_runtime,
    classify_playwright_startup_error,
    is_playwright_startup_environment_error,
)


_STATIC_RESOURCE_ROUTE_PATTERNS = (
    "**/*.{png,jpg,jpeg,gif,webp,avif,svg,ico,bmp}",
    "**/*.{woff,woff2,ttf,otf,eot}",
    "**/*.{mp4,webm,mp3,wav,ogg,m4a,mov,avi}",
)
_TRACKING_ROUTE_PATTERNS = (
    "**://www.google-analytics.com/**",
    "**://*.google-analytics.com/**",
    "**://*.doubleclick.net/**",
    "**://hm.baidu.com/**",
    "**://*.hm.baidu.com/**",
    "**://cnzz.com/**",
    "**://*.cnzz.com/**",
)
_RUNTIME_ABORT_ROUTE_PATTERNS = _STATIC_RESOURCE_ROUTE_PATTERNS + _TRACKING_ROUTE_PATTERNS


def _normalize_browser_candidates(prefer_browsers: Optional[List[str]]) -> List[str]:
    candidates: List[str] = []
    for item in list(prefer_browsers or BROWSER_PREFERENCE):
        name = str(item or "").strip().lower()
        if name != "edge" or name in candidates:
            continue
        candidates.append(name)
    return candidates or list(BROWSER_PREFERENCE)


@dataclass
class AsyncBrowserSession:
    driver: PlaywrightAsyncDriver
    owner_id: int
    browser_name: str

    async def close(self) -> None:
        mark_cleanup_done = getattr(self.driver, "mark_cleanup_done", None)
        if callable(mark_cleanup_done) and not mark_cleanup_done():
            return
        await self.driver.aclose()


class _OwnerBusyError(RuntimeError):
    """owner 当前没有可用上下文槽位。"""


class AsyncBrowserOwner:
    """Async semaphore gate for browser contexts owned by one pool shard."""

    def __init__(
        self,
        *,
        owner_id: int,
        prefer_browsers: Optional[List[str]] = None,
        headless: bool = False,
        window_position: Optional[Tuple[int, int]] = None,
        max_contexts: int = DEFAULT_HEADED_CONTEXTS_PER_BROWSER,
    ) -> None:
        self.owner_id = max(1, int(owner_id or 1))
        self._prefer_browsers = _normalize_browser_candidates(prefer_browsers)
        self._headless = bool(headless)
        self._window_position = window_position
        self._max_contexts = max(1, int(max_contexts or 1))
        self._broken = False
        self._closed = False
        self._ensure_lock = asyncio.Lock()
        self._context_semaphore = asyncio.Semaphore(self._max_contexts)
        self._active_contexts = 0
        self._browser: Any = None
        self._playwright_instance: Any = None
        self._browser_name = ""
        self._browser_pid: Optional[int] = None
        self._availability_event = asyncio.Event()
        self._availability_event.set()

    @property
    def browser_name(self) -> str:
        return self._browser_name

    @property
    def active_contexts(self) -> int:
        return int(self._active_contexts or 0)

    def mark_broken(self) -> None:
        self._broken = True

    def _notify_availability(self) -> None:
        if self._closed or self._active_contexts < self._max_contexts:
            self._availability_event.set()
            return
        self._availability_event.clear()

    async def wait_until_available(self) -> None:
        while not self._closed:
            await self._availability_event.wait()
            if self._closed or self._active_contexts < self._max_contexts:
                return

    async def _shutdown_browser(self, browser: Any = None, playwright_instance: Any = None) -> None:
        if browser is None:
            browser = self._browser
        if playwright_instance is None:
            playwright_instance = self._playwright_instance
        self._browser = None
        self._playwright_instance = None
        self._browser_name = ""
        self._browser_pid = None
        self._broken = False
        if browser is not None:
            try:
                await browser.close()
            except Exception as exc:
                log_suppressed_exception("AsyncBrowserOwner._shutdown_browser browser.close", exc, level=logging.WARNING)
        if playwright_instance is not None:
            try:
                await playwright_instance.stop()
            except Exception as exc:
                log_suppressed_exception("AsyncBrowserOwner._shutdown_browser playwright.stop", exc, level=logging.WARNING)

    async def _launch_browser(self) -> tuple[Any, str, Any, Optional[int]]:
        candidates = _normalize_browser_candidates(self._prefer_browsers)
        last_exc: Optional[Exception] = None
        for browser_name in candidates:
            pw = None
            try:
                launch_args = _build_launch_args(
                    browser_name=browser_name,
                    headless=self._headless,
                    window_position=self._window_position,
                    append_no_proxy=False,
                )
                pw = await _start_playwright_async_runtime()
                browser = await pw.chromium.launch(**launch_args)
                self._broken = False
                logging.info("[Action Log] AsyncBrowserOwner 启动底座成功：owner=%s browser=%s", self.owner_id, browser_name)
                return browser, browser_name, pw, self._extract_browser_pid(browser)
            except Exception as exc:
                last_exc = exc
                logging.warning("AsyncBrowserOwner 启动 %s 失败(owner=%s): %s", browser_name, self.owner_id, exc)
                logging.error(
                    "[Action Log] AsyncBrowserOwner 启动异常链(owner=%s browser=%s): %s",
                    self.owner_id,
                    browser_name,
                    _format_exception_chain(exc),
                )
                if pw is not None:
                    try:
                        await pw.stop()
                    except Exception as stop_exc:
                        log_suppressed_exception("AsyncBrowserOwner._launch_browser pw.stop", stop_exc, level=logging.WARNING)
                if is_playwright_startup_environment_error(exc):
                    break
        info = classify_playwright_startup_error(last_exc) if last_exc is not None else None
        if info is None:
            info = classify_playwright_startup_error(RuntimeError("未知错误"))
        friendly = info.message
        if last_exc is not None:
            raise BrowserStartupRuntimeError(f"AsyncBrowserOwner 无法启动 Microsoft Edge: {friendly}", info=info) from last_exc
        raise BrowserStartupRuntimeError(
            f"AsyncBrowserOwner 无法启动 Microsoft Edge: {friendly}",
            info=info,
        )

    @staticmethod
    def _extract_browser_pid(browser: Any) -> Optional[int]:
        try:
            proc = getattr(browser, "process", None)
            return int(proc.pid) if proc and getattr(proc, "pid", None) else None
        except Exception:
            return None

    async def _ensure_browser(self) -> tuple[Any, str, Any, Optional[int]]:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwner 已关闭")
        async with self._ensure_lock:
            if self._closed:
                raise RuntimeError("AsyncBrowserOwner 已关闭")
            if self._browser is not None and not self._broken:
                return self._browser, self._browser_name, self._playwright_instance, self._browser_pid
            await self._shutdown_browser()
            browser, browser_name, playwright_instance, browser_pid = await self._launch_browser()
            self._browser = browser
            self._playwright_instance = playwright_instance
            self._browser_name = browser_name
            self._browser_pid = browser_pid
            return browser, browser_name, playwright_instance, browser_pid

    async def _acquire_slot(self, *, wait: bool) -> None:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwner 已关闭")
        if not wait and self._active_contexts >= self._max_contexts:
            raise _OwnerBusyError("AsyncBrowserOwner 没有可用上下文槽位")
        await self._context_semaphore.acquire()
        if self._closed:
            self._context_semaphore.release()
            raise RuntimeError("AsyncBrowserOwner 已关闭")
        self._active_contexts += 1
        self._notify_availability()

    async def open_session(
        self,
        *,
        proxy_address: Optional[str],
        user_agent: Optional[str],
        wait: bool = True,
    ) -> AsyncBrowserSession:
        await self._acquire_slot(wait=wait)
        context = None
        try:
            browser, browser_name, _playwright_instance, _browser_pid = await self._ensure_browser()
            context_args = _build_context_args(
                headless=self._headless,
                proxy_address=proxy_address,
                user_agent=user_agent,
            )
            context = await browser.new_context(**context_args)
            for route_pattern in _RUNTIME_ABORT_ROUTE_PATTERNS:
                await context.route(route_pattern, _abort_runtime_resource)
            page = await context.new_page()
            driver = PlaywrightAsyncDriver(
                context=context,
                page=page,
                browser_name=browser_name,
                release_callback=self._release_slot,
            )
            return AsyncBrowserSession(driver=driver, owner_id=self.owner_id, browser_name=browser_name)
        except Exception as exc:
            if context is not None:
                try:
                    await context.close()
                except Exception as close_exc:
                    log_suppressed_exception("AsyncBrowserOwner.open_session context.close", close_exc, level=logging.WARNING)
            self._release_slot()
            if _is_browser_disconnected_error(exc):
                self.mark_broken()
            raise

    async def ensure_ready(self) -> str:
        """验证浏览器能启动，并保留底座供后续复用。"""
        _browser, browser_name, _playwright_instance, _browser_pid = await self._ensure_browser()
        return browser_name

    def _release_slot(self) -> None:
        if self._active_contexts <= 0:
            return
        self._active_contexts -= 1
        self._context_semaphore.release()
        self._notify_availability()

    async def shutdown(self) -> None:
        self._closed = True
        self._availability_event.set()
        await self._shutdown_browser()


async def _abort_runtime_resource(route: Any, request: Any = None) -> None:
    del request
    try:
        result = route.abort()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        log_suppressed_exception("AsyncBrowserOwner._abort_runtime_resource", exc, level=logging.WARNING)


async def _route_runtime_resource(route: Any, request: Any) -> None:
    action_taken = False

    async def _pass_through() -> None:
        nonlocal action_taken
        action_taken = True
        fallback = getattr(route, "fallback", None)
        if callable(fallback):
            result = fallback()
            if inspect.isawaitable(result):
                await result
            return
        result = route.continue_()
        if inspect.isawaitable(result):
            await result

    try:
        resource_type = str(getattr(request, "resource_type", "") or "").lower()
        url = str(getattr(request, "url", "") or "").lower()
        if "joinnew/processjq.ashx" in url:
            await _pass_through()
            return
        if resource_type in {"image", "font", "media"}:
            action_taken = True
            await route.abort()
            return
        if any(marker in url for marker in ("google-analytics", "doubleclick", "hm.baidu.com", "cnzz.com")):
            action_taken = True
            await route.abort()
            return
        await _pass_through()
    except Exception as exc:
        log_suppressed_exception("AsyncBrowserOwner._route_runtime_resource", exc, level=logging.WARNING)
        if action_taken:
            return
        try:
            await _pass_through()
        except Exception as fallback_exc:
            log_suppressed_exception("AsyncBrowserOwner._route_runtime_resource fallback", fallback_exc, level=logging.WARNING)


class AsyncBrowserOwnerPool:
    """Shared async pool: few browsers, many contexts."""

    def __init__(
        self,
        *,
        config: BrowserPoolConfig,
        headless: bool,
        prefer_browsers: Optional[List[str]] = None,
        window_positions: Optional[List[Tuple[int, int]]] = None,
    ) -> None:
        self.config = config
        self._closed = False
        self._owners: List[AsyncBrowserOwner] = []
        positions = list(window_positions or [])
        for owner_index in range(config.owner_count):
            self._owners.append(
                AsyncBrowserOwner(
                    owner_id=owner_index + 1,
                    prefer_browsers=prefer_browsers,
                    headless=headless,
                    window_position=positions[owner_index] if owner_index < len(positions) else None,
                    max_contexts=config.contexts_per_owner,
                )
            )

    @property
    def owners(self) -> List[AsyncBrowserOwner]:
        return list(self._owners)

    @staticmethod
    def _owner_sort_key(owner: AsyncBrowserOwner) -> tuple[int, int]:
        return (owner.active_contexts, owner.owner_id)

    async def _wait_for_any_owner_available(self, owners: list[AsyncBrowserOwner]) -> None:
        waiters = [asyncio.create_task(owner.wait_until_available()) for owner in owners]
        try:
            done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if done:
                await asyncio.gather(*done, return_exceptions=True)
        finally:
            for task in waiters:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    async def open_session(self, *, proxy_address: Optional[str], user_agent: Optional[str]) -> AsyncBrowserSession:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwnerPool 已关闭")
        last_exc: Optional[Exception] = None
        while True:
            if self._closed:
                raise RuntimeError("AsyncBrowserOwnerPool 已关闭")
            owners = sorted(self._owners, key=self._owner_sort_key)
            busy_seen = False
            for owner in owners:
                try:
                    return await owner.open_session(
                        proxy_address=proxy_address,
                        user_agent=user_agent,
                        wait=False,
                    )
                except _OwnerBusyError:
                    busy_seen = True
                    continue
                except Exception as exc:
                    last_exc = exc
                    if _is_browser_disconnected_error(exc):
                        continue
                    raise
            if busy_seen:
                await self._wait_for_any_owner_available(owners)
                if self._closed:
                    raise RuntimeError("AsyncBrowserOwnerPool 已关闭")
                continue
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("AsyncBrowserOwnerPool 没有可用 owner")

    async def ensure_ready(self) -> str:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwnerPool 已关闭")
        owners = sorted(self._owners, key=self._owner_sort_key)
        last_exc: Optional[Exception] = None
        for owner in owners:
            try:
                return await owner.ensure_ready()
            except Exception as exc:
                last_exc = exc
                if _is_browser_disconnected_error(exc):
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("AsyncBrowserOwnerPool 没有可用 owner")

    async def shutdown(self) -> None:
        self._closed = True
        await asyncio.gather(*(owner.shutdown() for owner in list(self._owners)), return_exceptions=True)


__all__ = [
    "AsyncBrowserOwner",
    "AsyncBrowserOwnerPool",
    "AsyncBrowserSession",
    "BrowserPoolConfig",
    "DEFAULT_HEADED_CONTEXTS_PER_BROWSER",
    "DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER",
]
