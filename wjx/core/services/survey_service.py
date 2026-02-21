"""问卷解析服务 - 封装问卷 HTML 获取与结构化解析逻辑"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import wjx.network.http_client as http_client
from wjx.core.engine import (
    create_playwright_driver,
    parse_survey_questions_from_html,
    _extract_survey_title_from_html,
    _normalize_html_text,
)
from wjx.utils.app.config import DEFAULT_HTTP_HEADERS


def parse_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    """解析问卷结构，返回 (questions_info, title)。

    先尝试 httpx 拉取 HTML 解析；失败后回退到 Playwright 无头浏览器。

    Args:
        url: 问卷星链接

    Returns:
        (questions_info, title) 二元组

    Raises:
        RuntimeError: 两种方式均无法解析时抛出
    """
    info: Optional[List[Dict[str, Any]]] = None
    title = ""

    # ── 方式一：HTTP 直接拉取 ─────────────────────────────────────────
    try:
        resp = http_client.get(url, timeout=12, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
        html = resp.text
        info = parse_survey_questions_from_html(html)
        title = _extract_survey_title_from_html(html) or title
    except Exception:
        logging.exception("使用 httpx 获取问卷失败，url=%r", url)
        info = None

    # ── 方式二：Playwright 无头浏览器 ─────────────────────────────────
    if info is None:
        driver = None
        try:
            driver, _ = create_playwright_driver(headless=True, user_agent=None)
            driver.get(url)
            time.sleep(2.5)
            page_source = driver.page_source
            info = parse_survey_questions_from_html(page_source)
            title = _extract_survey_title_from_html(page_source) or title
        except Exception:
            logging.exception("使用 Playwright 获取问卷失败，url=%r", url)
            info = None
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                logging.debug("关闭解析用浏览器实例失败", exc_info=True)

    if not info:
        raise RuntimeError("无法打开问卷链接，请确认链接有效且网络正常")

    normalized_title = _normalize_html_text(title) if title else ""
    return info, normalized_title
