"""平台无关的最小导航工具。"""

from __future__ import annotations

import random

from software.logging.log_utils import log_suppressed_exception
from software.network.browser import BrowserDriver


def _human_scroll_after_question(driver: BrowserDriver) -> None:
    distance = random.uniform(120, 260)
    page = getattr(driver, "page", None)
    if page:
        try:
            page.mouse.wheel(0, distance)
            return
        except Exception as exc:
            log_suppressed_exception("navigation._human_scroll_after_question mouse wheel", exc)
    try:
        driver.execute_script("window.scrollBy(0, arguments[0]);", distance)
    except Exception as exc:
        log_suppressed_exception("navigation._human_scroll_after_question script", exc)


__all__ = ["_human_scroll_after_question"]
