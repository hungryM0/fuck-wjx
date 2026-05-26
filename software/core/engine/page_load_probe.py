"""随机代理模式下的页面首载探测。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import software.core.modes.timed_mode as timed_mode
from software.core.engine.async_wait import sleep_or_stop
from software.providers.common import (
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    normalize_survey_provider,
)
from software.providers.registry import is_device_quota_limit_page as _provider_is_device_quota_limit_page

PAGE_LOAD_PROBE_ANSWERABLE = "answerable"
PAGE_LOAD_PROBE_BUSINESS_PAGE = "business_page"
PAGE_LOAD_PROBE_PROXY_UNUSABLE = "proxy_unusable"

_PROXY_ERROR_TEXT_MARKERS = (
    "err_tunnel_connection_failed",
    "err_proxy_connection_failed",
    "err_no_supported_proxies",
    "err_connection_timed_out",
    "err_timed_out",
    "err_connection_reset",
    "err_connection_closed",
    "err_name_not_resolved",
    "err_address_unreachable",
    "proxy error",
    "bad gateway",
    "gateway timeout",
    "this site can't be reached",
    "无法访问此网站",
    "连接已重置",
    "连接超时",
    "代理服务器",
    "proxy server",
)


@dataclass(frozen=True)
class PageLoadProbeResult:
    status: str
    detail: str = ""
    retryable: bool = False


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


async def _extract_text_snapshot(driver: Any) -> tuple[str, str]:
    try:
        snapshot = await driver.execute_script(
            """
            return (() => {
                const title = document.title || '';
                const bodyText = (document.body && document.body.innerText) || '';
                return { title, bodyText };
            })();
            """
        ) or {}
    except Exception:
        return "", ""
    if not isinstance(snapshot, dict):
        return "", ""
    return _normalize_text(snapshot.get("title")), _normalize_text(snapshot.get("bodyText"))


def _contains_proxy_error_text(*texts: str) -> bool:
    normalized = " ".join(_normalize_text(text).lower() for text in texts if text)
    if not normalized:
        return False
    return any(marker in normalized for marker in _PROXY_ERROR_TEXT_MARKERS)


async def _generic_probe_snapshot(driver: Any) -> dict[str, Any]:
    try:
        result = await driver.execute_script(
            """
            return (() => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const selectors = {
                    questionBlock:
                        '#divQuestion fieldset, #divQuestion [topic], #divQuestion .div_question, ' +
                        '.question-list > section.question, section.question, .question, [topic]',
                    inputs:
                        '#divQuestion input, #divQuestion textarea, #divQuestion select, ' +
                        '.question-list input, .question-list textarea, .question-list select, ' +
                        'form input:not([type="hidden"]), form textarea, form select',
                    actions:
                        '#submit_button, #divSubmit, #ctlNext, #divNext, #btnNext, #next, #SM_BTN_1, ' +
                        '.submitDiv a, .page-control button, .btn-next, .btn-submit, .next-btn, .next-button, ' +
                        '.btn-start, .startbtn, button[type="submit"], a[role="button"]',
                };
                const hasVisible = (selector) => Array.from(document.querySelectorAll(selector)).some(visible);
                return {
                    readyState: document.readyState || '',
                    bodyText: (document.body && document.body.innerText) || '',
                    title: document.title || '',
                    hasQuestionBlock: hasVisible(selectors.questionBlock),
                    hasInputs: hasVisible(selectors.inputs),
                    hasActions: hasVisible(selectors.actions),
                };
            })();
            """
        ) or {}
    except Exception:
        return {}
    return result if isinstance(result, dict) else {}


async def _probe_wjx_page(driver: Any) -> PageLoadProbeResult:
    snapshot = await _generic_probe_snapshot(driver)
    title = _normalize_text(snapshot.get("title"))
    body_text = _normalize_text(snapshot.get("bodyText"))
    if _contains_proxy_error_text(title, body_text):
        return PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="proxy_error_page", retryable=False)

    if any(bool(snapshot.get(key)) for key in ("hasQuestionBlock", "hasInputs", "hasActions")):
        return PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail="wjx_dom_ready")

    return await _fallback_probe(driver, title=title, body_text=body_text, snapshot=snapshot)


async def _probe_qq_page(driver: Any) -> PageLoadProbeResult:
    try:
        result = await driver.execute_script(
            """
            return (() => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const hasQuestions = Array.from(document.querySelectorAll('.question-list > section.question')).some(visible);
                const hasInputs = Array.from(
                    document.querySelectorAll(
                        '.question-list input:not([type="hidden"]), .question-list textarea, .question-list select'
                    )
                ).some(visible);
                const hasActions = Array.from(
                    document.querySelectorAll('.page-control button, .btn-next, .btn-submit, button[type="submit"]')
                ).some(visible);
                return {
                    title: document.title || '',
                    bodyText: (document.body && document.body.innerText) || '',
                    readyState: document.readyState || '',
                    hasQuestions,
                    hasInputs,
                    hasActions,
                };
            })();
            """
        ) or {}
    except Exception:
        result = {}

    title = _normalize_text(result.get("title"))
    body_text = _normalize_text(result.get("bodyText"))
    if _contains_proxy_error_text(title, body_text):
        return PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="proxy_error_page", retryable=False)

    if any(bool(result.get(key)) for key in ("hasQuestions", "hasInputs", "hasActions")):
        return PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail="qq_dom_ready")

    return await _fallback_probe(driver, title=title, body_text=body_text, snapshot=result)


async def _fallback_probe(
    driver: Any,
    *,
    title: str = "",
    body_text: str = "",
    snapshot: dict[str, Any] | None = None,
) -> PageLoadProbeResult:
    ready, not_started, ended, normalized_text = await timed_mode._page_status(driver)
    if ready:
        return PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail="generic_ready")
    if not_started:
        return PageLoadProbeResult(PAGE_LOAD_PROBE_BUSINESS_PAGE, detail="not_started")
    if ended:
        return PageLoadProbeResult(PAGE_LOAD_PROBE_BUSINESS_PAGE, detail="ended")

    normalized_title = _normalize_text(title)
    normalized_body = _normalize_text(body_text or normalized_text)
    if not normalized_title and not normalized_body:
        return PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="blank_page", retryable=True)

    if _contains_proxy_error_text(normalized_title, normalized_body):
        return PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="proxy_error_page", retryable=False)

    snapshot = snapshot or {}
    ready_state = str(snapshot.get("readyState") or "").strip().lower()
    if ready_state in {"loading", "interactive"}:
        return PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="page_still_loading", retryable=True)
    return PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="no_answerable_signal", retryable=True)


async def probe_loaded_page(driver: Any, *, provider: str) -> PageLoadProbeResult:
    normalized_provider = normalize_survey_provider(provider)
    if await _provider_is_device_quota_limit_page(driver, provider=normalized_provider):
        return PageLoadProbeResult(PAGE_LOAD_PROBE_BUSINESS_PAGE, detail="device_quota_limit")
    if normalized_provider == SURVEY_PROVIDER_WJX:
        return await _probe_wjx_page(driver)
    if normalized_provider == SURVEY_PROVIDER_QQ:
        return await _probe_qq_page(driver)
    title, body_text = await _extract_text_snapshot(driver)
    return await _fallback_probe(driver, title=title, body_text=body_text)


async def wait_for_page_probe(
    driver: Any,
    *,
    provider: str,
    timeout_ms: int,
    poll_interval_seconds: float,
) -> PageLoadProbeResult:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(timeout_ms) / 1000.0)
    interval = max(0.05, float(poll_interval_seconds or 0.25))
    last_result = PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail="probe_not_started", retryable=True)

    while True:
        last_result = await probe_loaded_page(driver, provider=provider)
        if last_result.status in {PAGE_LOAD_PROBE_ANSWERABLE, PAGE_LOAD_PROBE_BUSINESS_PAGE}:
            return last_result
        if not last_result.retryable:
            return last_result
        if loop.time() >= deadline:
            return PageLoadProbeResult(
                PAGE_LOAD_PROBE_PROXY_UNUSABLE,
                detail=last_result.detail or "probe_timeout",
                retryable=False,
            )
        await sleep_or_stop(None, interval)


__all__ = [
    "PAGE_LOAD_PROBE_ANSWERABLE",
    "PAGE_LOAD_PROBE_BUSINESS_PAGE",
    "PAGE_LOAD_PROBE_PROXY_UNUSABLE",
    "PageLoadProbeResult",
    "probe_loaded_page",
    "wait_for_page_probe",
]
