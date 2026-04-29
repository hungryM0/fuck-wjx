"""浏览器驱动异常与 Selenium 风格常量。"""

from __future__ import annotations


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


__all__ = [
    "By",
    "NoSuchElementException",
    "ProxyConnectionError",
    "TimeoutException",
]
