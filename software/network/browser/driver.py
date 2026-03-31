"""浏览器驱动封装 - Playwright 浏览器实例创建与操作"""
from __future__ import annotations

import logging
import random
import subprocess
import threading
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set, Tuple
from urllib.parse import urlparse

from software.network.proxy.policy.source import PROXY_SOURCE_CUSTOM, get_proxy_source
from software.network.proxy.pool import normalize_proxy_address
from software.logging.log_utils import log_suppressed_exception
from software.app.config import BROWSER_PREFERENCE, HEADLESS_WINDOW_SIZE, get_proxy_auth

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright

_PW_START_LOCK = threading.Lock()
_COMMON_BROWSER_SAFE_ARGS = [
    "--disable-gpu",
]
_EDGE_CLEAN_ARGS = [
    "--disable-extensions",
    "--disable-background-networking",
]
_BROWSER_DISCONNECT_MARKERS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "browser closed",
    "connection closed",
    "not connected",
    "has been disconnected",
)


def _load_playwright_sync():
    """延迟导入 Playwright，避免应用启动阶段就触发底层 asyncio/系统依赖。"""
    from playwright.sync_api import TimeoutError as playwright_timeout_error
    from playwright.sync_api import sync_playwright

    return sync_playwright, playwright_timeout_error


def _format_exception_chain(exc: BaseException) -> str:
    """格式化异常链，便于定位被掩盖的底层错误。"""
    parts: List[str] = []
    current: Optional[BaseException] = exc
    depth = 0
    while current is not None and depth < 8:
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
        depth += 1
    return " <- ".join(parts)


class NoSuchElementException(Exception):
    pass


class TimeoutException(Exception):
    pass


class ProxyConnectionError(Exception):
    pass


class By:
    CSS_SELECTOR = "css"
    XPATH = "xpath"
    ID = "id"


def _build_selector(by: str, value: str) -> str:
    if by == By.XPATH:
        return f"xpath={value}"
    if by == By.ID:
        if value.startswith("#") or value.startswith("xpath=") or value.startswith("css="):
            return value
        return f"#{value}"
    return value


_PROXY_TUNNEL_ERRORS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NO_SUPPORTED_PROXIES",
)


def _is_proxy_tunnel_error(exc: Exception) -> bool:
    message = str(exc)
    if not message:
        return False
    return any(code in message for code in _PROXY_TUNNEL_ERRORS)


def _is_browser_disconnected_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    if not message:
        return False
    return any(marker in message for marker in _BROWSER_DISCONNECT_MARKERS)


def _parse_proxy_context_args(proxy_address: Optional[str]) -> Dict[str, Any]:
    normalized_proxy = normalize_proxy_address(proxy_address)
    if not normalized_proxy:
        return {}

    proxy_settings: Dict[str, Any] = {"server": normalized_proxy}
    try:
        parsed = urlparse(normalized_proxy)
        if parsed.scheme and parsed.hostname:
            server = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server += f":{parsed.port}"
            proxy_settings["server"] = server
        if parsed.username:
            proxy_settings["username"] = parsed.username
        if parsed.password:
            proxy_settings["password"] = parsed.password
    except Exception as exc:
        log_suppressed_exception("browser_driver._parse_proxy_context_args parse proxy", exc, level=logging.WARNING)

    if get_proxy_source() == PROXY_SOURCE_CUSTOM and "username" not in proxy_settings:
        try:
            auth = get_proxy_auth()
            username, password = auth.split(":", 1)
            proxy_settings["username"] = username
            proxy_settings["password"] = password
        except Exception:
            logging.info("代理认证解析失败", exc_info=True)

    return {"proxy": proxy_settings}


def _build_context_args(
    *,
    headless: bool,
    proxy_address: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    context_args: Dict[str, Any] = {}
    context_args.update(_parse_proxy_context_args(proxy_address))
    if user_agent:
        context_args["user_agent"] = user_agent
    if headless and HEADLESS_WINDOW_SIZE:
        try:
            width, height = [int(x) for x in HEADLESS_WINDOW_SIZE.split(",")]
            context_args["viewport"] = {"width": width, "height": height}
        except Exception as exc:
            log_suppressed_exception("browser_driver._build_context_args parse headless size", exc, level=logging.WARNING)
    return context_args


def _build_launch_args(
    *,
    browser_name: str,
    headless: bool,
    window_position: Optional[Tuple[int, int]],
    append_no_proxy: bool,
) -> Dict[str, Any]:
    launch_args: Dict[str, Any] = {"headless": headless, "args": list(_COMMON_BROWSER_SAFE_ARGS)}
    if browser_name == "edge":
        launch_args["channel"] = "msedge"
        launch_args["args"].extend(_EDGE_CLEAN_ARGS)
    elif browser_name == "chrome":
        launch_args["channel"] = "chrome"

    if window_position and not headless:
        x, y = window_position
        launch_args["args"].append(f"--window-position={x},{y}")

    if append_no_proxy:
        launch_args["args"].append("--no-proxy-server")

    return launch_args


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
            # 旧版本 API 兜底：能读 contexts 认为还活着
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
                # 常驻模式使用 context 级代理，避免 launch 级代理与后续会话冲突
                append_no_proxy=False,
            )
            try:
                with _PW_START_LOCK:
                    sync_playwright, _ = _load_playwright_sync()
                    pw = sync_playwright().start()
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
                continue

        raise RuntimeError(f"BrowserManager 无法启动任何浏览器: {last_exc}")

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


class PlaywrightElement:
    def __init__(self, handle, page: Page):
        self._handle = handle
        self._page = page

    @property
    def text(self) -> str:
        try:
            return self._handle.inner_text()
        except Exception:
            return ""

    def get_attribute(self, name: str):
        try:
            return self._handle.get_attribute(name)
        except Exception:
            return None

    def is_displayed(self) -> bool:
        try:
            return self._handle.bounding_box() is not None
        except Exception:
            return False

    @property
    def size(self) -> Dict[str, float]:
        try:
            box = self._handle.bounding_box()
        except Exception:
            box = None
        if not box:
            return {"width": 0, "height": 0}
        return {"width": box.get("width") or 0, "height": box.get("height") or 0}

    @property
    def tag_name(self) -> str:
        try:
            value = self._handle.evaluate("el => el.tagName.toLowerCase()")
            return value or ""
        except Exception:
            return ""

    def click(self) -> None:
        last_exc: Optional[Exception] = None
        try:
            self._handle.click()
            return
        except Exception as exc:
            last_exc = exc
            try:
                self._handle.scroll_into_view_if_needed()
                self._handle.click()
                return
            except Exception as exc:
                last_exc = exc
                log_suppressed_exception("browser_driver.PlaywrightElement.click fallback", exc, level=logging.WARNING)
        try:
            self._handle.evaluate(
                "el => { el.click(); return true; }"
            )
            return
        except Exception as exc:
            last_exc = exc
            log_suppressed_exception("browser_driver.PlaywrightElement.click js fallback", exc, level=logging.WARNING)
        if last_exc is not None:
            raise last_exc

    def clear(self) -> None:
        try:
            self._handle.fill("")
            return
        except Exception as exc:
            log_suppressed_exception("clear: self._handle.fill(\"\")", exc, level=logging.WARNING)
        try:
            self._handle.evaluate(
                "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }"
            )
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightElement.clear js fallback", exc, level=logging.WARNING)

    def send_keys(self, value: str) -> None:
        text = "" if value is None else str(value)
        try:
            self._handle.fill(text)
            return
        except Exception as exc:
            log_suppressed_exception("send_keys: self._handle.fill(text)", exc, level=logging.WARNING)
        try:
            self._handle.type(text)
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightElement.send_keys type fallback", exc, level=logging.WARNING)

    def find_element(self, by: str, value: str):
        selector = _build_selector(by, value)
        handle = self._handle.query_selector(selector)
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightElement(handle, self._page)

    def find_elements(self, by: str, value: str):
        selector = _build_selector(by, value)
        handles = self._handle.query_selector_all(selector)
        return [PlaywrightElement(h, self._page) for h in handles]


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
            log_suppressed_exception("browser_driver.PlaywrightDriver.get set timeouts", exc, level=logging.WARNING)

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
            log_suppressed_exception("browser_driver.PlaywrightDriver.set_window_size", exc, level=logging.WARNING)

    def refresh(self) -> None:
        try:
            self._page.reload(wait_until="domcontentloaded")
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.refresh", exc, level=logging.WARNING)

    def mark_cleanup_done(self) -> bool:
        """标记清理已完成，返回 True 表示可以执行清理，False 表示已被其他线程清理过。"""
        with self._cleanup_lock:
            if self._cleanup_done:
                return False
            self._cleanup_done = True
            return True

    def quit(self) -> None:
        """默认仅关闭 page/context；若驱动独占底座则附带关闭底座。"""
        try:
            self._page.close()
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.quit page.close", exc, level=logging.WARNING)
        try:
            self._context.close()
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.quit context.close", exc, level=logging.WARNING)

        if self._manager_owned and self._browser_manager is not None:
            try:
                self._browser_manager.shutdown()
            except Exception as exc:
                log_suppressed_exception("browser_driver.PlaywrightDriver.quit manager.shutdown", exc, level=logging.WARNING)
            return

        if self._browser is not None and self._playwright is not None:
            # 临时模式（parse_survey）仍需回收底座，避免泄漏进程
            try:
                self._browser.close()
            except Exception as exc:
                log_suppressed_exception("browser_driver.PlaywrightDriver.quit browser.close", exc, level=logging.WARNING)
            try:
                self._playwright.stop()
            except Exception as exc:
                log_suppressed_exception("browser_driver.PlaywrightDriver.quit playwright.stop", exc, level=logging.WARNING)


BrowserDriver = PlaywrightDriver


def list_browser_pids() -> Set[int]:
    """列出当前运行的浏览器进程 PID（跨平台）。"""
    pids: Set[int] = set()

    if sys.platform == "win32":
        # Windows: 使用 tasklist
        names = ("chrome.exe", "msedge.exe")
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
    else:
        # macOS/Linux: 使用 pgrep
        names = ("Google Chrome", "Chromium", "chrome", "chromium")
        for name in names:
            try:
                result = subprocess.run(
                    ["pgrep", "-f", name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line:
                        try:
                            pids.add(int(line))
                        except ValueError:
                            continue
            except Exception:
                continue

    return pids



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
        log_suppressed_exception("browser_driver.shutdown_browser_manager", exc, level=logging.WARNING)


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
                sync_playwright, _ = _load_playwright_sync()
                pw = sync_playwright().start()
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
                    log_suppressed_exception("browser_driver._create_transient_driver pw.stop", stop_exc, level=logging.WARNING)
            continue

    raise RuntimeError(f"无法启动任何浏览器: {last_exc}")


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

    raise RuntimeError(f"创建浏览器上下文失败: {last_exc}")



