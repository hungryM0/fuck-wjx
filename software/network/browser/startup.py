"""Playwright 启动与环境错误诊断。"""

from __future__ import annotations

import errno
import gc
import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from playwright.sync_api import Playwright

_PW_START_LOCK = threading.Lock()
_PLAYWRIGHT_START_RETRY_DELAYS = (0.35, 0.8, 1.5)
BROWSER_STARTUP_ERROR_ENVIRONMENT = "browser_environment"
BROWSER_STARTUP_ERROR_LAUNCH = "launch_failed"


@dataclass(frozen=True)
class BrowserStartupErrorInfo:
    kind: str
    message: str
    is_environment_error: bool = False

__all__ = [
    "BROWSER_STARTUP_ERROR_ENVIRONMENT",
    "BROWSER_STARTUP_ERROR_LAUNCH",
    "BrowserStartupErrorInfo",
    "_PW_START_LOCK",
    "_format_exception_chain",
    "_load_playwright_sync",
    "_start_playwright_runtime",
    "classify_playwright_startup_error",
    "describe_playwright_startup_error",
    "is_playwright_startup_environment_error",
]


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


def _iter_exception_chain(exc: BaseException):
    current: Optional[BaseException] = exc
    depth = 0
    while current is not None and depth < 8:
        yield current
        current = current.__cause__ or current.__context__
        depth += 1


def is_playwright_startup_environment_error(exc: BaseException) -> bool:
    """识别 Playwright 启动前就被本机环境拦截的致命错误。"""
    chain_text = _format_exception_chain(exc).lower()
    if "notimplementederror" in chain_text and "create_subprocess_exec" in chain_text:
        return True
    if "nameerror" in chain_text and "base_events" in chain_text:
        return True

    for current in _iter_exception_chain(exc):
        if isinstance(current, NotImplementedError):
            return True
        if isinstance(current, OSError):
            winerror = getattr(current, "winerror", None)
            if winerror == 10106:
                return True
        if isinstance(current, PermissionError):
            winerror = getattr(current, "winerror", None)
            err_no = getattr(current, "errno", None)
            text = str(current).lower()
            if winerror == 10013:
                return True
            if err_no == errno.EACCES and ("socket" in text or "套接字" in text):
                return True

    return False


def describe_playwright_startup_error(exc: BaseException) -> str:
    """给浏览器启动异常生成更像人话的提示。"""
    if is_playwright_startup_environment_error(exc):
        chain_text = _format_exception_chain(exc).lower()
        if "notimplementederror" in chain_text:
            return (
                "Playwright 启动依赖的 Windows asyncio 子进程能力不可用，"
                "浏览器底座无法拉起。通常是事件循环策略或运行环境被改坏了。"
            )
        if "base_events" in chain_text or "winerror 10106" in chain_text:
            return (
                "本机的 Windows 网络/asyncio 底层环境已经损坏（常见为 WinError 10106，"
                "Winsock 服务提供程序异常），Playwright 还没真正启动就先崩了。"
            )
        return (
            "本机环境拦截了 Playwright 创建本地套接字/事件循环（常见为 WinError 10013），"
            "浏览器底座还没启动就被系统、安全软件或防火墙卡死了。"
        )
    return str(exc)


def classify_playwright_startup_error(exc: BaseException) -> BrowserStartupErrorInfo:
    """统一浏览器预检与真实启动失败的错误分类。"""
    is_environment = is_playwright_startup_environment_error(exc)
    return BrowserStartupErrorInfo(
        kind=BROWSER_STARTUP_ERROR_ENVIRONMENT if is_environment else BROWSER_STARTUP_ERROR_LAUNCH,
        message=describe_playwright_startup_error(exc),
        is_environment_error=is_environment,
    )


def _start_playwright_runtime() -> Playwright:
    """启动 Playwright；若命中已知的 Windows 启动抖动，做有限自愈重试。"""
    sync_playwright, _ = _load_playwright_sync()
    last_exc: Optional[Exception] = None
    max_attempts = max(1, len(_PLAYWRIGHT_START_RETRY_DELAYS) + 1)

    for attempt in range(1, max_attempts + 1):
        try:
            return sync_playwright().start()
        except Exception as exc:
            last_exc = exc
            if not is_playwright_startup_environment_error(exc) or attempt >= max_attempts:
                raise

            wait_seconds = _PLAYWRIGHT_START_RETRY_DELAYS[attempt - 1]
            logging.warning(
                "[Action Log] Playwright 底座启动第 %s/%s 次失败，%.2f 秒后重试：%s",
                attempt,
                max_attempts,
                wait_seconds,
                describe_playwright_startup_error(exc),
            )
            gc.collect()
            time.sleep(wait_seconds)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Playwright 底座启动失败：未知错误")
