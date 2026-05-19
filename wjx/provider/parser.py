"""问卷星解析实现（provider 层）。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS
from software.network.browser import (
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.browser.parse_pool import acquire_parse_browser_session
from software.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)
from software.providers.parse_flow import (
    build_http_browser_failure_message,
    exception_has_winerror as _exception_has_winerror_common,
    parse_with_http_browser_fallback,
    walk_exception_chain as _walk_exception_chain_common,
)
from wjx.provider.html_parser import (
    _normalize_html_text,
    extract_survey_title_from_html,
    parse_survey_questions_from_html,
)

PAUSED_SURVEY_ERROR_MESSAGE = "问卷已暂停，需要前往问卷星后台重新发布"
STOPPED_SURVEY_ERROR_MESSAGE = "问卷已停止，无法作答"
ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE = "问卷发布者企业标准版未购买或已到期，暂时不能填写"
NOT_OPEN_SURVEY_ERROR_MESSAGE = "该问卷暂未开放，无法解析"
_PAUSED_SURVEY_ID_RE = re.compile(r"此问卷[（(]\d+[）)]已暂停")
_NOT_OPEN_TIME_RE = re.compile(
    r"此问卷将于\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})\s*开放"
)


def _walk_exception_chain(exc: BaseException):
    return _walk_exception_chain_common(exc)


def _exception_has_winerror_10013(exc: BaseException) -> bool:
    return _exception_has_winerror_common(exc, winerror=10013)


def _build_parser_failure_message(http_exc: Optional[BaseException], browser_exc: Optional[BaseException]) -> str:
    return build_http_browser_failure_message(
        http_exc=http_exc,
        browser_exc=browser_exc,
        browser_environment_error_checker=is_playwright_startup_environment_error,
        browser_environment_error_formatter=describe_playwright_startup_error,
    )


def is_paused_survey_page(html: str) -> bool:
    """检测页面是否为“问卷已暂停，不能填写”提示页。"""
    text = _normalize_html_text(html)
    if not text or "已暂停" not in text:
        return False
    if "不能填写" in text or "问卷已暂停" in text:
        return True
    return bool(_PAUSED_SURVEY_ID_RE.search(text))


def _html_has_question_content(html: str) -> bool:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        question_container = soup.find("div", id="divQuestion")
        if not question_container:
            return False
        return bool(
            question_container.find_all("fieldset")
            or question_container.find_all("div", attrs={"topic": True})
        )
    except Exception:
        return False


def is_stopped_survey_page(html: str) -> bool:
    """检测页面是否为“问卷停止作答”提示页。"""
    text = _normalize_html_text(html)
    if not text or "停止状态" not in text or "无法作答" not in text:
        return False

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for selector_id in ("divWorkError", "divTip"):
            error_container = soup.find("div", id=selector_id)
            if error_container is not None:
                error_text = _normalize_html_text(error_container.get_text(" ", strip=True))
                if "停止状态" in error_text and "无法作答" in error_text:
                    return True
    except Exception:
        pass

    if _html_has_question_content(html):
        return False

    normalized = "".join(text.split())
    return "此问卷处于停止状态，无法作答" in normalized


def is_enterprise_unavailable_survey_page(html: str) -> bool:
    """检测企业标准版未购买或到期导致的不可填写提示。"""
    text = _normalize_html_text(html)
    if not text:
        return False
    normalized = "".join(text.split())
    if "企业标准版" not in normalized:
        return False
    if "问卷发布者" not in normalized:
        return False
    if "未购买" not in normalized and "已到期" not in normalized:
        return False
    return "暂时不能被填写" in normalized or "暂时不能填写" in normalized


def build_not_open_survey_message(html: str) -> Optional[str]:
    """构造"问卷暂未开放"提示文案。"""
    text = _normalize_html_text(html)
    if not text:
        return None

    if _html_has_question_content(html):
        return None

    normalized = "".join(text.split())
    
    # 保留所有关键词，但通过DOM检查优先避免误判
    keywords = (
        "此问卷将于",
        "请到时再进入此页面进行填写",
        "距离开始还有",
        "尚未开始",
        "未到开始时间",
        "未开放",
        "开放时间",
    )
    if not any(keyword in normalized for keyword in keywords):
        return None

    match = _NOT_OPEN_TIME_RE.search(text)
    if match:
        open_time = str(match.group(1) or "").replace("/", "-").strip()
        if open_time:
            return f"{NOT_OPEN_SURVEY_ERROR_MESSAGE}，开放时间：{open_time}"
    return NOT_OPEN_SURVEY_ERROR_MESSAGE


def _raise_wjx_page_state_errors(html: str) -> None:
    if is_paused_survey_page(html):
        raise SurveyPausedError(PAUSED_SURVEY_ERROR_MESSAGE)
    if is_stopped_survey_page(html):
        raise SurveyStoppedError(STOPPED_SURVEY_ERROR_MESSAGE)
    if is_enterprise_unavailable_survey_page(html):
        raise SurveyEnterpriseUnavailableError(ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE)
    not_open_message = build_not_open_survey_message(html)
    if not_open_message:
        raise SurveyNotOpenError(not_open_message)


def _parse_wjx_html(html: str) -> Tuple[List[Dict[str, Any]], str]:
    _raise_wjx_page_state_errors(html)
    return parse_survey_questions_from_html(html), extract_survey_title_from_html(html) or ""


async def _load_rendered_wjx_parse_result(url: str) -> Tuple[List[Dict[str, Any]], str]:
    async with acquire_parse_browser_session() as driver:
        await driver.get(url, timeout=20000, wait_until="domcontentloaded")
        page = await driver.page()
        if page is not None:
            selector_seen = True
            try:
                await page.wait_for_selector("#divQuestion, div[topic], fieldset", state="attached", timeout=6000)
            except Exception:
                selector_seen = False
                try:
                    await page.wait_for_load_state("networkidle", timeout=2000)
                except Exception:
                    pass
            if selector_seen:
                try:
                    await page.wait_for_load_state("networkidle", timeout=1000)
                except Exception:
                    pass
        page_source = await driver.page_source()
        return _parse_wjx_html(page_source)


async def parse_wjx_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    async def _load_http_parse_result() -> Tuple[List[Dict[str, Any]], str]:
        resp = await http_client.aget(url, timeout=12, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
        return _parse_wjx_html(resp.text)

    info, title = await parse_with_http_browser_fallback(
        url=url,
        http_loader=_load_http_parse_result,
        browser_loader=lambda: _load_rendered_wjx_parse_result(url),
        failure_message_builder=_build_parser_failure_message,
        http_log_message="使用 httpx 获取问卷失败，url=%r",
        browser_log_message="使用 Playwright 获取问卷失败，url=%r",
        reraised_exceptions=(
            SurveyPausedError,
            SurveyStoppedError,
            SurveyEnterpriseUnavailableError,
            SurveyNotOpenError,
        ),
        should_fallback=lambda result: result is None or result[0] is None,
        is_invalid_result=lambda result: result is None or not result[0],
    )
    normalized_title = _normalize_html_text(title) if title else ""
    return info, normalized_title


__all__ = [
    "PAUSED_SURVEY_ERROR_MESSAGE",
    "STOPPED_SURVEY_ERROR_MESSAGE",
    "ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE",
    "NOT_OPEN_SURVEY_ERROR_MESSAGE",
    "SurveyPausedError",
    "SurveyStoppedError",
    "SurveyEnterpriseUnavailableError",
    "SurveyNotOpenError",
    "build_not_open_survey_message",
    "is_enterprise_unavailable_survey_page",
    "is_paused_survey_page",
    "is_stopped_survey_page",
    "parse_wjx_survey",
]


