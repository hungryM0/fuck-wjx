"""腾讯问卷提交流程。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

from software.app.config import (
    HEADLESS_SUBMIT_CLICK_SETTLE_DELAY,
    HEADLESS_SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    SUBMIT_INITIAL_DELAY,
)
from software.core.modes.duration_control import (
    has_configured_answer_duration,
    sample_answer_duration_seconds,
)
from software.core.engine.runtime_control import _is_headless_mode, _sleep_with_stop
from software.core.engine.stop_signal import StopSignalLike
from software.core.questions.runtime_async import extract_text_from_runtime_element
from software.core.task import ExecutionState
from software.network.browser import By, NoSuchElementException
from software.network.browser.runtime_async import BrowserDriver
from tencent.provider.runtime_flow import (
    QQ_COMPLETION_MARKERS,
    QQ_VALIDATION_MARKERS,
    qq_is_completion_page,
    qq_submission_requires_verification,
)
from tencent.provider.runtime_state import peek_qq_runtime_state


@dataclass(frozen=True)
class SubmissionRecoveryHint:
    question_numbers: tuple[int, ...]
    message: str


def _resolve_submit_duration_seconds(ctx: Optional[ExecutionState]) -> int:
    if ctx is None:
        return 0
    answer_duration = getattr(getattr(ctx, "config", None), "answer_duration_range_seconds", (0, 0))
    if not has_configured_answer_duration(answer_duration):
        return 0
    try:
        sampled = sample_answer_duration_seconds(answer_duration, survey_provider="qq")
    except Exception:
        logging.warning("腾讯问卷提交时长采样失败，已跳过浏览器提交流程时长注入", exc_info=True)
        return 0
    return max(1, int(round(float(sampled or 0.0))))


async def _install_submit_duration_override(driver: BrowserDriver, target_seconds: int) -> bool:
    normalized_target = max(1, int(target_seconds or 0))
    script = r"""
return (() => {
    const targetSeconds = Math.max(1, Math.round(Number(arguments[0] || 0)));
    if (!targetSeconds) {
        return { ok: false, reason: 'invalid-target' };
    }

    window.__surveyControllerQqDurationTarget = targetSeconds;

    const isTargetUrl = (url) => /\/api\/v2\/respondent\/surveys\/\d+\/answers(?:\?|$)/.test(String(url || ''));
    const rewriteBody = (body) => {
        if (typeof body !== 'string' || !body) {
            return body;
        }
        try {
            const payload = JSON.parse(body);
            if (!payload || typeof payload !== 'object') {
                return body;
            }
            const answerSurvey = payload.answer_survey;
            if (!answerSurvey || typeof answerSurvey !== 'object') {
                return body;
            }
            payload.answer_survey.duration = Math.max(
                1,
                Math.round(Number(window.__surveyControllerQqDurationTarget || targetSeconds))
            );
            return JSON.stringify(payload);
        } catch (_error) {
            return body;
        }
    };

    if (!window.__surveyControllerQqDurationHookInstalled) {
        if (typeof window.fetch === 'function') {
            const originalFetch = window.fetch.bind(window);
            window.fetch = (input, init) => {
                const requestUrl =
                    typeof input === 'string'
                        ? input
                        : (input && typeof input.url === 'string' ? input.url : '');
                let nextInit = init;
                if (isTargetUrl(requestUrl) && init && typeof init.body === 'string') {
                    nextInit = { ...init, body: rewriteBody(init.body) };
                }
                return originalFetch(input, nextInit);
            };
        }

        if (typeof XMLHttpRequest !== 'undefined' && XMLHttpRequest.prototype) {
            const originalOpen = XMLHttpRequest.prototype.open;
            const originalSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url) {
                try {
                    this.__surveyControllerQqRequestUrl = String(url || '');
                } catch (_error) {}
                return originalOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function(body) {
                let nextBody = body;
                try {
                    if (isTargetUrl(this.__surveyControllerQqRequestUrl) && typeof body === 'string') {
                        nextBody = rewriteBody(body);
                    }
                } catch (_error) {}
                return originalSend.call(this, nextBody);
            };
        }

        window.__surveyControllerQqDurationHookInstalled = true;
    }

    return {
        ok: true,
        targetSeconds,
        hooked: !!window.__surveyControllerQqDurationHookInstalled,
    };
})();
    """
    try:
        result = await driver.execute_script(script, normalized_target)
    except Exception as exc:
        logging.warning("腾讯问卷提交时长注入失败：%s", exc)
        return False
    if isinstance(result, dict) and bool(result.get("ok")):
        logging.info(
            "腾讯问卷提交时长已注入为 %s 秒（hooked=%s）",
            int(result.get("targetSeconds") or normalized_target),
            bool(result.get("hooked")),
        )
        return True
    logging.warning("腾讯问卷提交时长注入未生效：target=%s result=%s", normalized_target, result)
    return False


async def _prepare_submit_duration_override(driver: BrowserDriver, ctx: Optional[ExecutionState]) -> None:
    target_seconds = _resolve_submit_duration_seconds(ctx)
    if target_seconds <= 0:
        return
    await _install_submit_duration_override(driver, target_seconds)


def _runtime_context_summary(driver: BrowserDriver) -> str:
    state = peek_qq_runtime_state(driver)
    if state is None:
        return ""
    page_index = max(0, int(getattr(state, "page_index", 0) or 0))
    question_ids = [str(item or "").strip() for item in list(getattr(state, "page_question_ids", []) or []) if str(item or "").strip()]
    if page_index <= 0 and not question_ids:
        return ""
    parts: list[str] = []
    if page_index > 0:
        parts.append(f"page={page_index}")
    if question_ids:
        parts.append(f"questions={question_ids}")
    return " ".join(parts)


async def _extract_submission_recovery_hint(driver: BrowserDriver) -> Optional[SubmissionRecoveryHint]:
    script = r"""
return (() => {
    const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    const normalize = (text) => String(text || '').replace(/\s+/g, ' ').trim();
    const markers = ['请选择', '请填写', '为必答题', '此题必填', '请先完成'];
    const selectors = ['.error', '.question-error', '.t-form__error', '.t-message', '[class*="error"]'];
    const messages = [];
    const questionNumbers = [];

    const pushQuestionNumber = (node) => {
        const section = node?.closest?.('section.question[data-question-id]');
        if (!section) return;
        const rawNum = normalize(section.getAttribute('data-question-index') || section.getAttribute('data-index') || '');
        const numMatch = rawNum.match(/\d+/);
        if (numMatch) {
            const value = Number.parseInt(numMatch[0], 10);
            if (value > 0 && !questionNumbers.includes(value)) {
                questionNumbers.push(value);
                return;
            }
        }
        const titleNode = section.querySelector('.question-title, .title, [class*="title"], legend, h3');
        const titleText = normalize(titleNode?.innerText || titleNode?.textContent || section.innerText || '');
        const titleMatch = titleText.match(/(?:^|\D)(\d{1,4})(?:[\.、\s]|$)/);
        if (!titleMatch) return;
        const value = Number.parseInt(titleMatch[1], 10);
        if (value > 0 && !questionNumbers.includes(value)) {
            questionNumbers.push(value);
        }
    };

    for (const sel of selectors) {
        for (const node of document.querySelectorAll(sel)) {
            if (!visible(node)) continue;
            const text = normalize(node.innerText || node.textContent || '');
            if (!text) continue;
            if (!markers.some((marker) => text.includes(marker))) continue;
            messages.push(text);
            pushQuestionNumber(node);
        }
    }

    return {
        questionNumbers,
        messages: Array.from(new Set(messages)).slice(0, 5),
    };
})();
    """
    try:
        payload = await driver.execute_script(script) or {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return None

    question_numbers: list[int] = []
    for raw_num in list(payload.get("questionNumbers") or []):
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num > 0 and question_num not in question_numbers:
            question_numbers.append(question_num)

    messages: list[str] = []
    for raw_message in list(payload.get("messages") or []):
        text = str(raw_message or "").strip()
        if not text:
            continue
        if not any(marker in text for marker in QQ_VALIDATION_MARKERS):
            continue
        if text not in messages:
            messages.append(text)

    if not question_numbers and not messages:
        return None
    message = " | ".join(messages[:3]).strip() or "提交后检测到未作答提示"
    return SubmissionRecoveryHint(tuple(question_numbers), message)


async def _click_submit_button(driver: BrowserDriver, max_wait: float = 10.0) -> bool:
    submit_keywords = ("提交", "完成", "交卷", "确认提交", "确认")
    locator_candidates = [
        (By.CSS_SELECTOR, "#ctlNext"),
        (By.CSS_SELECTOR, "#submit_button"),
        (By.CSS_SELECTOR, "#SubmitBtnGroup .submitbtn"),
        (By.CSS_SELECTOR, ".submitbtn.mainBgColor"),
        (By.CSS_SELECTOR, "#SM_BTN_1"),
        (By.CSS_SELECTOR, "#divSubmit"),
        (By.CSS_SELECTOR, ".btn-submit"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//a[normalize-space(.)='提交' or normalize-space(.)='完成' or normalize-space(.)='交卷' or normalize-space(.)='确认提交' or normalize-space(.)='确认']"),
        (By.XPATH, "//button[normalize-space(.)='提交' or normalize-space(.)='完成' or normalize-space(.)='交卷' or normalize-space(.)='确认提交' or normalize-space(.)='确认']"),
    ]

    async def _text_looks_like_submit(element) -> bool:
        text = (await extract_text_from_runtime_element(element)).strip()
        if not text:
            text = (await element.get_attribute("value") or "").strip()
        if not text:
            return False
        return any(keyword in text for keyword in submit_keywords)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(max_wait or 0.0))
    while True:
        for by, value in locator_candidates:
            try:
                elements = await driver.find_elements(by, value)
            except Exception:
                continue
            for element in elements:
                try:
                    if not await element.is_displayed():
                        continue
                except Exception:
                    continue
                if by == By.CSS_SELECTOR and value == "button[type='submit']" and not await _text_looks_like_submit(element):
                    continue
                for click_method in (
                    lambda: element.click(),
                    lambda: driver.execute_script("arguments[0].click();", element),
                ):
                    try:
                        result = click_method()
                        if asyncio.iscoroutine(result):
                            await result
                        logging.info("腾讯问卷提交按钮已点击：%s=%s", by, value)
                        return True
                    except Exception:
                        continue
        if loop.time() >= deadline:
            break
        await asyncio.sleep(0.2)

    try:
        force_triggered = bool(
            await driver.execute_script(
                r"""
                return (() => {
                    const clickVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) return false;
                        el.click();
                        return true;
                    };

                    const submitLike = Array.from(document.querySelectorAll('div,a,button,input,span')).find((el) => {
                        const text = (el.innerText || el.textContent || el.value || '').replace(/\s+/g, '');
                        return text === '提交' || text === '完成' || text === '交卷' || text === '确认提交';
                    });
                    if (clickVisible(submitLike)) return true;

                    if (typeof submit_button_click === 'function') {
                        submit_button_click();
                        return true;
                    }
                    return false;
                })();
                """
            )
        )
        if force_triggered:
            logging.info("腾讯问卷提交按钮常规选择器未命中，已触发 JS 兜底")
            return True
    except Exception:
        pass
    return False


async def _click_submit_confirm_button(driver: BrowserDriver, settle_delay: float = 0.0) -> None:
    confirm_candidates = [
        (By.XPATH, '//*[@id="layui-layer1"]/div[3]/a'),
        (By.CSS_SELECTOR, "#layui-layer1 .layui-layer-btn a"),
        (By.CSS_SELECTOR, ".layui-layer .layui-layer-btn a.layui-layer-btn0"),
    ]
    for by, value in confirm_candidates:
        try:
            element = await driver.find_element(by, value)
        except Exception:
            element = None
        if not element:
            continue
        try:
            if not await element.is_displayed():
                continue
        except Exception:
            continue
        try:
            await element.click()
            if settle_delay > 0:
                await asyncio.sleep(settle_delay)
            return
        except Exception:
            continue


async def submit(
    driver: BrowserDriver,
    ctx: Optional[ExecutionState] = None,
    stop_signal: StopSignalLike | None = None,
) -> None:
    headless_mode = _is_headless_mode(ctx)
    settle_delay = float(HEADLESS_SUBMIT_CLICK_SETTLE_DELAY if headless_mode else SUBMIT_CLICK_SETTLE_DELAY)
    pre_submit_delay = float(HEADLESS_SUBMIT_INITIAL_DELAY if headless_mode else SUBMIT_INITIAL_DELAY)

    if pre_submit_delay > 0 and await _sleep_with_stop(stop_signal, pre_submit_delay):
        return
    if stop_signal and stop_signal.is_set():
        return
    await _prepare_submit_duration_override(driver, ctx)
    if stop_signal and stop_signal.is_set():
        return

    clicked = await _click_submit_button(driver, max_wait=10.0)
    if not clicked:
        runtime_context = _runtime_context_summary(driver)
        if runtime_context:
            logging.warning("腾讯问卷提交按钮未找到：%s", runtime_context)
        raise NoSuchElementException("Submit button not found")
    if settle_delay > 0:
        await asyncio.sleep(settle_delay)
    await _click_submit_confirm_button(driver, settle_delay=settle_delay)


async def consume_submission_success_signal(driver: BrowserDriver) -> bool:
    _runtime_context_summary(driver)
    return bool(await qq_is_completion_page(driver))


async def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    _runtime_context_summary(driver)
    script = r"""
return (() => {
    const normalize = (text) => String(text || '').replace(/\s+/g, '').toLowerCase();
    const text = normalize(document.body?.innerText || '');
    if (!text) return false;

    const limitMarkers = [
        '设备达到填写次数上限',
        '设备已达到填写次数上限',
        '本设备达到填写次数上限',
        '本设备已达到填写次数上限',
        '设备填写次数已达上限',
        '本设备已填写',
        '该设备已参与',
        '该设备已填写',
        '此设备已填写',
        '达到设备填写上限',
        '超过填写次数上限',
    ];
    if (!limitMarkers.some((marker) => text.includes(marker))) return false;

    const completionMarkers = %s;
    const looksLikeCompletion = completionMarkers.some((marker) => text.includes(normalize(marker)));
    const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    const hasVisibleQuestion = Array.from(document.querySelectorAll('.question-list > section.question, section.question')).some(visible);
    const hasVisibleAction = Array.from(document.querySelectorAll('.page-control button, .btn-next, .btn-submit, button[type="submit"]')).some(visible);
    return looksLikeCompletion && !hasVisibleQuestion && !hasVisibleAction;
})();
    """ % repr(list(QQ_COMPLETION_MARKERS))
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


async def attempt_submission_recovery(
    driver: BrowserDriver,
    ctx: ExecutionState,
    gui_instance: Optional[Any],
    stop_signal: StopSignalLike | None,
    *,
    thread_name: str = "",
) -> bool:
    del gui_instance
    if stop_signal and stop_signal.is_set():
        return False
    if await qq_submission_requires_verification(driver):
        return False

    runtime_state = peek_qq_runtime_state(driver)
    if runtime_state is None:
        return False
    recovery_attempts = int(getattr(runtime_state, "submission_recovery_attempts", 0) or 0)
    if recovery_attempts >= 1:
        return False

    hint = await _extract_submission_recovery_hint(driver)
    if hint is None:
        return False

    target_questions: list[int] = []
    for question_num in hint.question_numbers:
        if question_num > 0 and question_num not in target_questions:
            target_questions.append(question_num)
    if not target_questions:
        current_page_numbers: list[int] = []
        page_question_ids = {
            str(item or "").strip()
            for item in list(getattr(runtime_state, "page_question_ids", []) or [])
            if str(item or "").strip()
        }
        for question_num, question in sorted((ctx.config.questions_metadata or {}).items()):
            question_id = str(getattr(question, "provider_question_id", "") or "").strip()
            if question_id and question_id in page_question_ids and bool(getattr(question, "required", False)):
                current_page_numbers.append(int(question_num))
        target_questions = current_page_numbers
    if not target_questions:
        logging.warning("腾讯问卷提交补救放弃：识别到校验提示，但当前页没有可补题目。message=%s", hint.message)
        return False

    logging.warning("腾讯问卷提交命中未作答提示，准备补答并重提：questions=%s message=%s", target_questions, hint.message)
    try:
        ctx.update_thread_status(thread_name or "Worker-?", "补答必答题", running=True)
    except Exception:
        logging.info("更新线程状态失败：补答必答题", exc_info=True)

    from tencent.provider.runtime import refill_required_questions_on_current_page

    filled_count = await refill_required_questions_on_current_page(
        driver,
        ctx,
        question_numbers=target_questions,
        thread_name=thread_name or "Worker-?",
        psycho_plan=getattr(runtime_state, "psycho_plan", None),
    )
    if filled_count <= 0:
        logging.warning("腾讯问卷提交补救失败：未成功补答任何题目。questions=%s", target_questions)
        return False

    runtime_state.submission_recovery_attempts = recovery_attempts + 1
    await submit(driver, ctx=ctx, stop_signal=stop_signal)
    return True


__all__ = [
    "_click_submit_button",
    "attempt_submission_recovery",
    "consume_submission_success_signal",
    "is_device_quota_limit_page",
    "submit",
]
