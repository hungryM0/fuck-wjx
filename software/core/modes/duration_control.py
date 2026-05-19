"""答题时长控制 - 模拟真实答题时间分布"""
from __future__ import annotations

import logging
import random
from typing import Any, Optional, Tuple

from software.core.engine.async_wait import sleep_or_stop
from software.network.proxy.policy.source import get_proxy_minute_by_answer_seconds
from software.providers.common import SURVEY_PROVIDER_WJX
from software.logging.log_utils import log_suppressed_exception

_COMPLETION_MARKERS = (
    "答卷已经提交",
    "感谢您的参与",
    "问卷提交成功",
    "提交成功",
    "已完成本次问卷",
    "已完成本次答卷",
    "感谢您的宝贵时间",
    "问卷已结束",
)
_NAVIGATION_TRANSIENT_ERRORS = (
    "execution context was destroyed",
    "most likely because of a navigation",
)


def _is_navigation_transient_error(exc: BaseException) -> bool:
    """页面跳转时 Playwright 可能短暂无法读取 DOM。"""

    message = str(exc or "").lower()
    return any(pattern in message for pattern in _NAVIGATION_TRANSIENT_ERRORS)


def has_configured_answer_duration(answer_duration_range_seconds: Tuple[int, int] = (0, 0)) -> bool:
    """是否配置了提交前作答时长等待。"""

    try:
        raw_min, raw_max = answer_duration_range_seconds
    except Exception:
        return False
    return max(0, int(raw_min), int(raw_max)) > 0


def sample_answer_duration_seconds(
    answer_duration_range_seconds: Tuple[int, int] = (0, 0),
    *,
    survey_provider: Optional[str] = None,
) -> float:
    """按现有配置规则采样一次作答时长秒数。"""

    try:
        raw_min, raw_max = answer_duration_range_seconds
    except Exception:
        return 0.0
    if not has_configured_answer_duration(answer_duration_range_seconds):
        return 0.0

    min_delay = max(0, int(raw_min))
    max_delay = max(min_delay, int(raw_max))

    if min_delay == max_delay:
        base = max_delay
        jitter = max(5, int(base * 0.2))
        min_delay = max(0, base - jitter)
        max_delay = base + jitter

    normalized_provider = str(survey_provider or "").strip().lower()
    safe_upper = max_delay
    if normalized_provider and normalized_provider != SURVEY_PROVIDER_WJX:
        proxy_ref_seconds = max(0, int(max(raw_min, raw_max)))
        ip_minute = get_proxy_minute_by_answer_seconds(
            proxy_ref_seconds,
            survey_provider=normalized_provider,
        )
        if ip_minute > 0:
            ip_limit_seconds = int(ip_minute) * 60
            safe_upper = min(max_delay, max(min_delay, ip_limit_seconds - 1))

    center = (min_delay + safe_upper) / 2.0
    std_dev = (safe_upper - min_delay) / 6.0 if safe_upper > min_delay else 0.0

    if std_dev > 0:
        wait_seconds = random.gauss(center, std_dev)
    else:
        wait_seconds = float(min_delay)

    return max(min_delay, min(safe_upper, wait_seconds))


async def wait_answer_duration_seconds(
    stop_signal: Optional[Any] = None,
    seconds: float = 0.0,
) -> bool:
    """按给定秒数等待作答时长；返回 True 表示等待中被中断。"""

    wait_seconds = max(0.0, float(seconds or 0.0))
    if wait_seconds <= 0:
        return False
    logging.info(
        "[Action Log] Simulating answer duration: waiting %.1f seconds before submit",
        wait_seconds,
    )
    return bool(await sleep_or_stop(stop_signal, wait_seconds))





async def simulate_answer_duration_delay(
    stop_signal: Optional[Any] = None,
    answer_duration_range_seconds: Tuple[int, int] = (0, 0),
    *,
    survey_provider: Optional[str] = None,
) -> bool:
    """在提交前模拟答题时长等待；返回 True 表示等待中被中断。"""

    wait_seconds = sample_answer_duration_seconds(
        answer_duration_range_seconds,
        survey_provider=survey_provider,
    )
    return await wait_answer_duration_seconds(stop_signal, wait_seconds)


async def is_survey_completion_page(driver: Any, provider: Optional[str] = None) -> bool:
    """尝试检测当前页面是否为问卷提交完成页。"""
    try:
        current_url = str(await driver.current_url() or "")
        if "complete" in current_url.lower():
            return True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: current_url", exc, level=logging.WARNING)

    try:
        from software.providers.registry import is_completion_page as _provider_is_completion_page

        if await _provider_is_completion_page(driver, provider=provider):
            return True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: provider_is_completion_page", exc, level=logging.WARNING)

    detected = False
    try:
        divdsc = None
        try:
            divdsc = await driver.find_element("id", "divdsc")
        except Exception:
            divdsc = None
        if divdsc and await divdsc.is_displayed():
            text = await divdsc.text() or ""
            if any(marker in text for marker in _COMPLETION_MARKERS):
                detected = True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: divdsc = None", exc, level=logging.WARNING)
    if not detected:
        for attempt in range(2):
            try:
                page_text = await driver.execute_script(
                    "return (document.body && document.body.innerText) || '';"
                ) or ""
                has_marker = any(marker in page_text for marker in _COMPLETION_MARKERS)
                if has_marker:
                    action_visible = bool(
                        await driver.execute_script(
                            r"""
                            return (() => {
                                const selectors = [
                                    '#submit_button',
                                    '#divSubmit',
                                    '#ctlNext',
                                    '#divNext',
                                    '#btnNext',
                                    '#SM_BTN_1',
                                    '#SubmitBtnGroup .submitbtn',
                                    '.btn-next',
                                    '.btn-submit',
                                    '.page-control button',
                                    'button[type="submit"]',
                                    'a.button.mainBgColor'
                                ];
                                const visible = (el) => {
                                    if (!el) return false;
                                    const style = window.getComputedStyle(el);
                                    if (!style) return false;
                                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                                    const rect = el.getBoundingClientRect();
                                    return rect.width > 0 && rect.height > 0;
                                };
                                for (const sel of selectors) {
                                    const nodes = document.querySelectorAll(sel);
                                    for (const node of nodes) {
                                        if (visible(node)) return true;
                                    }
                                }
                                return false;
                            })();
                            """
                        )
                    )
                    detected = not action_visible
                break
            except Exception as exc:
                if _is_navigation_transient_error(exc):
                    if attempt == 0:
                        await sleep_or_stop(None, 0.2)
                        continue
                    logging.debug(
                        "[Suppressed] is_survey_completion_page: page_text during navigation: %s",
                        exc,
                    )
                    break
                log_suppressed_exception("is_survey_completion_page: page_text", exc, level=logging.WARNING)
                break
    return bool(detected)



