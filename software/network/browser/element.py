"""Playwright ElementHandle 的 Selenium 风格薄封装。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Optional

from software.logging.log_utils import log_suppressed_exception
from software.network.browser.exceptions import NoSuchElementException
from software.network.browser.options import _build_selector

if TYPE_CHECKING:
    from playwright.sync_api import Page


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
                log_suppressed_exception("browser_element.PlaywrightElement.click fallback", exc, level=logging.WARNING)
        try:
            self._handle.evaluate("el => { el.click(); return true; }")
            return
        except Exception as exc:
            last_exc = exc
            log_suppressed_exception("browser_element.PlaywrightElement.click js fallback", exc, level=logging.WARNING)
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
            log_suppressed_exception("browser_element.PlaywrightElement.clear js fallback", exc, level=logging.WARNING)

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
            log_suppressed_exception("browser_element.PlaywrightElement.send_keys type fallback", exc, level=logging.WARNING)

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


__all__ = ["PlaywrightElement"]
