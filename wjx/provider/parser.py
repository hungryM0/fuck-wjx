"""问卷星解析实现（provider 层）。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from software.core.engine.driver_factory import create_playwright_driver
from wjx.provider.html_parser import (
    _normalize_html_text,
    extract_survey_title_from_html,
    parse_survey_questions_from_html,
)
import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS

PAUSED_SURVEY_ERROR_MESSAGE = "问卷已暂停，需要前往问卷星后台重新发布"
_PAUSED_SURVEY_ID_RE = re.compile(r"此问卷[（(]\d+[）)]已暂停")


class SurveyPausedError(RuntimeError):
    """问卷已暂停时抛出的业务异常。"""


def is_paused_survey_page(html: str) -> bool:
    """检测页面是否为“问卷已暂停，不能填写”提示页。"""
    text = _normalize_html_text(html)
    if not text or "已暂停" not in text:
        return False
    if "不能填写" in text or "问卷已暂停" in text:
        return True
    return bool(_PAUSED_SURVEY_ID_RE.search(text))


def parse_wjx_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    info: Optional[List[Dict[str, Any]]] = None
    title = ""

    try:
        resp = http_client.get(url, timeout=12, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
        html = resp.text
        if is_paused_survey_page(html):
            raise SurveyPausedError(PAUSED_SURVEY_ERROR_MESSAGE)
        info = parse_survey_questions_from_html(html)
        title = extract_survey_title_from_html(html) or title
    except SurveyPausedError:
        raise
    except Exception:
        logging.exception("使用 httpx 获取问卷失败，url=%r", url)
        info = None

    if info is None:
        driver = None
        try:
            driver, _ = create_playwright_driver(
                headless=True,
                user_agent=None,
                persistent_browser=False,
                transient_launch=True,
            )
            driver.get(url)
            time.sleep(2.5)
            page_source = driver.page_source
            if is_paused_survey_page(page_source):
                raise SurveyPausedError(PAUSED_SURVEY_ERROR_MESSAGE)
            info = parse_survey_questions_from_html(page_source)
            title = extract_survey_title_from_html(page_source) or title
        except SurveyPausedError:
            raise
        except Exception:
            logging.exception("使用 Playwright 获取问卷失败，url=%r", url)
            info = None
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                logging.info("关闭解析用浏览器实例失败", exc_info=True)

    if not info:
        raise RuntimeError("无法打开问卷链接，请确认链接有效且网络正常")

    normalized_title = _normalize_html_text(title) if title else ""
    return info, normalized_title


__all__ = [
    "PAUSED_SURVEY_ERROR_MESSAGE",
    "SurveyPausedError",
    "is_paused_survey_page",
    "parse_wjx_survey",
]


