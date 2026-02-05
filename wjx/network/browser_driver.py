from __future__ import annotations

import logging
import os
import random
import sys
import time
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

import base64

from wjx.utils.app.config import BROWSER_PREFERENCE, HEADLESS_WINDOW_SIZE
from wjx.utils.logging.log_utils import log_suppressed_exception
from wjx.network.random_ip import (
    _normalize_proxy_address,
    get_proxy_source,
    PROXY_SOURCE_DEFAULT,
    PROXY_SOURCE_CUSTOM,
)

# 默认代理账号密码（base64 编码的 "username:password"），允许环境变量覆盖以便部署时替换
_PROXY_AUTH_B64 = "MTgxNzAxMTk4MDg6dFdKNWhMRG9Id3JIZ1RraWowelk="


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
        try:
            self._handle.click()
        except Exception:
            try:
                self._handle.scroll_into_view_if_needed()
                self._handle.click()
            except Exception as exc:
                log_suppressed_exception("browser_driver.PlaywrightElement.click fallback", exc)

    def clear(self) -> None:
        try:
            self._handle.fill("")
            return
        except Exception:
            pass
        try:
            self._handle.evaluate(
                "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }"
            )
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightElement.clear js fallback", exc)

    def send_keys(self, value: str) -> None:
        text = "" if value is None else str(value)
        try:
            self._handle.fill(text)
            return
        except Exception:
            pass
        try:
            self._handle.type(text)
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightElement.send_keys type fallback", exc)

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
    def __init__(self, playwright, browser: Browser, context: BrowserContext, page: Page, browser_name: str):
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._page = page
        self.browser_name = browser_name
        self.session_id = f"pw-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        try:
            proc = getattr(browser, "process", None)
            self.browser_pid = int(proc.pid) if proc and getattr(proc, "pid", None) else None
        except Exception:
            self.browser_pid = None
        self.browser_pids: Set[int] = set()

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
            # Playwright 的 page.evaluate 仅允许传入一个 arg；这里把所有参数打包成数组，
            # 再通过 apply 将其展开成 function(){...} 的 arguments[0..n]，以兼容历史脚本写法。
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
            logging.debug("execute_script failed: %s", exc)
            return None

    def get(
        self,
        url: str,
        timeout: int = 18000,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "domcontentloaded",
    ) -> None:
        try:
            self._page.set_default_navigation_timeout(timeout)
            self._page.set_default_timeout(timeout)
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.get set timeouts", exc)

        try:
            self._page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except PlaywrightTimeoutError as exc:
            logging.warning("Page.goto timeout after %d ms: %s", timeout, exc)
            raise
        except Exception as exc:
            if _is_proxy_tunnel_error(exc):
                logging.warning("Page.goto proxy tunnel failure: %s", exc)
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
            log_suppressed_exception("browser_driver.PlaywrightDriver.set_window_size", exc)

    def refresh(self) -> None:
        try:
            self._page.reload(wait_until="domcontentloaded")
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.refresh", exc)

    def quit(self) -> None:
        try:
            self._page.close()
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.quit page.close", exc)
        try:
            self._context.close()
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.quit context.close", exc)
        try:
            self._browser.close()
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.quit browser.close", exc)
        try:
            self._playwright.stop()
        except Exception as exc:
            log_suppressed_exception("browser_driver.PlaywrightDriver.quit playwright.stop", exc)


BrowserDriver = PlaywrightDriver


def list_browser_pids() -> Set[int]:
    try:
        import psutil
    except ImportError:
        return set()
    names = {"msedge.exe", "chrome.exe", "chromium.exe"}
    pids: Set[int] = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = (proc.info.get("name") or "").lower()
            if proc_name in names:
                pids.add(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return pids


def graceful_terminate_process_tree(pids: Set[int], wait_seconds: float = 3.0) -> int:
    """
    尝试温和终止指定 PID 及其子进程，避免使用 taskkill。
    返回被处理的进程数量（不保证全部存活）。
    """
    try:
        import psutil
    except ImportError:
        return 0

    unique_pids = [int(p) for p in sorted(set(pids or [])) if int(p) > 0]
    if not unique_pids:
        return 0

    procs = []
    seen = set()
    for pid in unique_pids:
        try:
            proc = psutil.Process(pid)
            stack = [proc]
            while stack:
                cur = stack.pop()
                if cur.pid in seen:
                    continue
                seen.add(cur.pid)
                procs.append(cur)
                try:
                    stack.extend(cur.children(recursive=False))
                except Exception as exc:
                    log_suppressed_exception("browser_driver.graceful_terminate_process_tree children", exc)
        except Exception:
            continue

    for proc in procs:
        try:
            proc.terminate()
        except Exception as exc:
            log_suppressed_exception("browser_driver.graceful_terminate_process_tree terminate", exc)

    _, alive = psutil.wait_procs(procs, timeout=max(0.1, float(wait_seconds or 0.0)))
    for proc in alive:
        try:
            proc.kill()
        except Exception as exc:
            log_suppressed_exception("browser_driver.graceful_terminate_process_tree kill", exc)
    return len(procs)


def _collect_process_tree(root_pid: Optional[int]) -> Set[int]:
    """收集给定 PID 及其子进程 PID，失败时返回空集合。"""
    if not root_pid:
        return set()
    try:
        import psutil
    except ImportError:
        return {int(root_pid)}
    try:
        root = psutil.Process(int(root_pid))
    except Exception:
        return {int(root_pid)}
    pids: Set[int] = {int(root.pid)}
    try:
        for child in root.children(recursive=True):
            try:
                pids.add(int(child.pid))
            except Exception:
                continue
    except Exception as exc:
        log_suppressed_exception("browser_driver._collect_process_tree children", exc)
    return pids


def create_playwright_driver(
    *,
    headless: bool = False,
    prefer_browsers: Optional[List[str]] = None,
    proxy_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    window_position: Optional[Tuple[int, int]] = None,
) -> Tuple[BrowserDriver, str]:
    candidates = prefer_browsers or list(BROWSER_PREFERENCE)
    if not candidates:
        candidates = list(BROWSER_PREFERENCE)

    normalized_proxy = _normalize_proxy_address(proxy_address)
    last_exc: Optional[Exception] = None

    for browser in candidates:
        pre_launch_pids = list_browser_pids()
        try:
            pw = sync_playwright().start()
        except Exception as exc:
            last_exc = exc
            continue

        try:
            launch_args: Dict[str, Any] = {"headless": headless}
            if browser == "edge":
                launch_args["channel"] = "msedge"
            elif browser == "chrome":
                launch_args["channel"] = "chrome"
            
            # 初始化 args 列表
            if "args" not in launch_args:
                launch_args["args"] = []
            
            if window_position and not headless:
                x, y = window_position
                launch_args["args"].append(f"--window-position={x},{y}")

            if not normalized_proxy:
                # 没有指定代理时，添加 --no-proxy-server 绕过系统代理
                launch_args["args"].append("--no-proxy-server")

            browser_instance = pw.chromium.launch(**launch_args)

            context_args: Dict[str, Any] = {}
            if normalized_proxy:
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
                    log_suppressed_exception("browser_driver.create_playwright_driver parse proxy", exc)

                if get_proxy_source() in (PROXY_SOURCE_DEFAULT, PROXY_SOURCE_CUSTOM) and "username" not in proxy_settings:
                    try:
                        encoded = os.environ.get("WJX_PROXY_AUTH_B64", _PROXY_AUTH_B64)
                        decoded = base64.b64decode(encoded).decode("utf-8")
                        username, password = decoded.split(":", 1)
                        proxy_settings["username"] = username
                        proxy_settings["password"] = password
                    except Exception:
                        logging.debug("解码失败", exc_info=True)
                
                context_args["proxy"] = proxy_settings
            if user_agent:
                context_args["user_agent"] = user_agent
            if headless and HEADLESS_WINDOW_SIZE:
                try:
                    width, height = [int(x) for x in HEADLESS_WINDOW_SIZE.split(",")]
                    context_args["viewport"] = {"width": width, "height": height}
                except Exception as exc:
                    log_suppressed_exception("browser_driver.create_playwright_driver parse headless size", exc)

            context = browser_instance.new_context(**context_args)
            page = context.new_page()
            driver = PlaywrightDriver(pw, browser_instance, context, page, browser)

            collected_pids: Set[int] = set()
            main_pid = getattr(driver, "browser_pid", None)
            if main_pid:
                collected_pids.update(_collect_process_tree(main_pid))
            else:
                try:
                    time.sleep(0.05)
                    after = list_browser_pids()
                    diff = list(after - pre_launch_pids)[:10]
                    collected_pids.update(diff)
                    # 尝试进一步补全子进程
                    for pid in list(collected_pids):
                        collected_pids.update(_collect_process_tree(pid))
                    if not collected_pids:
                        logging.warning("[Action Log] 未捕获浏览器主 PID,回退到差集依然为空")
                except Exception as exc:
                    log_suppressed_exception("browser_driver.create_playwright_driver collect pid fallback", exc)

            driver.browser_pids = collected_pids
            logging.debug("[Action Log] 捕获浏览器 PID: %s", sorted(collected_pids) if collected_pids else "无")
            return driver, browser
        except Exception as exc:
            last_exc = exc
            logging.warning("启动 %s 浏览器失败: %s", browser, exc)
            try:
                pw.stop()
            except Exception as exc:
                log_suppressed_exception("browser_driver.create_playwright_driver pw.stop", exc)

    raise RuntimeError(f"无法启动任何浏览器: {last_exc}")
