"""Provider 解析流程公共辅助。"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Iterator, Optional, TypeVar, cast

__all__ = [
    "build_http_browser_failure_message",
    "exception_has_winerror",
    "parse_with_http_browser_fallback",
    "walk_exception_chain",
]

ResultT = TypeVar("ResultT")


def walk_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)


def exception_has_winerror(exc: BaseException, *, winerror: int) -> bool:
    for current in walk_exception_chain(exc):
        if getattr(current, "winerror", None) == winerror:
            return True
    return False


def build_http_browser_failure_message(
    *,
    http_exc: Optional[BaseException],
    browser_exc: Optional[BaseException],
    browser_environment_error_checker: Callable[[BaseException], bool] | None = None,
    browser_environment_error_formatter: Callable[[BaseException], str] | None = None,
    socket_blocked_winerror: int = 10013,
    combined_socket_blocked_message: str = (
        "本机环境拦截了网络/本地套接字访问（WinError 10013），"
        "程序既拿不到问卷网页，也拉不起 Playwright 浏览器。"
        "请先检查防火墙、安全软件、系统代理或公司管控策略。"
    ),
    http_socket_blocked_message: str = (
        "本机环境拦截了网络套接字访问（WinError 10013），"
        "程序还没拿到问卷网页就被系统、防火墙或安全软件卡死了。"
    ),
    http_error_prefix: str = "无法获取问卷网页：",
    browser_error_prefix: str = "无法启动解析浏览器：",
    generic_message: str = "无法打开问卷链接，请确认链接有效且网络正常",
) -> str:
    browser_checker = browser_environment_error_checker or (lambda _exc: False)

    if http_exc is not None and exception_has_winerror(http_exc, winerror=socket_blocked_winerror):
        if browser_exc is not None and browser_checker(browser_exc):
            return combined_socket_blocked_message
        return http_socket_blocked_message

    if browser_exc is not None and browser_checker(browser_exc):
        if browser_environment_error_formatter is not None:
            return browser_environment_error_formatter(browser_exc)

    if http_exc is not None:
        text = str(http_exc).strip()
        if text:
            return f"{http_error_prefix}{text}"

    if browser_exc is not None:
        text = str(browser_exc).strip()
        if text:
            return f"{browser_error_prefix}{text}"

    return generic_message


async def parse_with_http_browser_fallback(
    *,
    url: str,
    http_loader: Callable[[], Awaitable[Optional[ResultT]]],
    browser_loader: Callable[[], Awaitable[Optional[ResultT]]],
    failure_message_builder: Callable[[Optional[BaseException], Optional[BaseException]], str],
    http_log_message: str,
    browser_log_message: str,
    reraised_exceptions: tuple[type[BaseException], ...] = (),
    should_fallback: Callable[[Optional[ResultT]], bool] | None = None,
    is_invalid_result: Callable[[Optional[ResultT]], bool] | None = None,
) -> ResultT:
    fallback_checker = should_fallback or (lambda result: result is None)
    invalid_checker = is_invalid_result or (lambda result: result is None)

    result: Optional[ResultT] = None
    http_exc: Optional[BaseException] = None
    browser_exc: Optional[BaseException] = None

    try:
        result = await http_loader()
    except Exception as exc:
        if isinstance(exc, reraised_exceptions):
            raise
        http_exc = exc
        logging.exception(http_log_message, url)
        result = None

    if fallback_checker(result):
        try:
            result = await browser_loader()
        except Exception as exc:
            if isinstance(exc, reraised_exceptions):
                raise
            browser_exc = exc
            logging.exception(browser_log_message, url)
            result = None

    if invalid_checker(result):
        raise RuntimeError(failure_message_builder(http_exc, browser_exc))

    return cast(ResultT, result)
