"""腾讯问卷流程判断与翻页辅助。"""
from __future__ import annotations

from typing import Any, Dict, List

from software.core.task import ExecutionState
from software.network.browser import BrowserDriver
from software.providers.contracts import SurveyQuestionMeta

QQ_COMPLETION_MARKERS = (
    "感谢您的参与",
    "提交成功",
    "问卷提交成功",
    "答卷已提交",
    "感谢填写",
    "我们已收到",
    "已收到您的回答",
)

QQ_VERIFICATION_MARKERS = (
    "验证码",
    "安全验证",
    "滑动验证",
    "请完成验证",
    "请先完成验证",
    "验证后继续",
)

QQ_VALIDATION_MARKERS = (
    "请选择",
    "请填写",
    "为必答题",
    "此题必填",
    "请先完成",
)


from .runtime_interactions import _page

def qq_submission_requires_verification(driver: BrowserDriver) -> bool:
    try:
        return bool(
            _page(driver).evaluate(
                """(markers) => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                    if (!markers.some((marker) => bodyText.includes(marker))) return false;
                    const strongMarkers = ['安全验证', '滑动验证', '请完成验证', '请先完成验证'];
                    if (strongMarkers.some((marker) => bodyText.includes(marker))) return true;
                    const modalSelectors = [
                        '.t-dialog',
                        '.t-popup',
                        '.captcha',
                        '.verify',
                        '[class*="captcha"]',
                        '[class*="verify"]',
                    ];
                    return modalSelectors.some((sel) => Array.from(document.querySelectorAll(sel)).some(visible));
                }""",
                list(QQ_VERIFICATION_MARKERS),
            )
        )
    except Exception:
        return False

def qq_submission_validation_message(driver: BrowserDriver) -> str:
    try:
        message = _page(driver).evaluate(
            """(markers) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const selectors = ['.error', '.question-error', '.t-form__error', '.t-message', '[class*="error"]'];
                const messages = [];
                for (const sel of selectors) {
                    for (const node of document.querySelectorAll(sel)) {
                        if (!visible(node)) continue;
                        const text = (node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (text) messages.push(text);
                    }
                }
                const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                for (const marker of markers) {
                    if (bodyText.includes(marker)) {
                        messages.push(marker);
                    }
                }
                return Array.from(new Set(messages)).slice(0, 3).join(' | ');
            }""",
            list(QQ_VALIDATION_MARKERS),
        ) or ""
        return str(message or "").strip()
    except Exception:
        return ""

def qq_is_completion_page(driver: BrowserDriver) -> bool:
    try:
        return bool(
            _page(driver).evaluate(
                """(markers) => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                    const hasMarker = markers.some((marker) => bodyText.includes(marker));
                    const hasVisibleAction = Array.from(document.querySelectorAll('.page-control button, .btn-next, .btn-submit')).some(visible);
                    const hasVisibleQuestion = Array.from(document.querySelectorAll('.question-list > section.question')).some(visible);
                    if (hasMarker && !hasVisibleAction) return true;
                    if (!hasVisibleAction && !hasVisibleQuestion && hasMarker) return true;
                    return false;
                }""",
                list(QQ_COMPLETION_MARKERS),
            )
        )
    except Exception:
        return False

def _group_questions_by_page(ctx: ExecutionState) -> List[List[SurveyQuestionMeta]]:
    grouped: Dict[int, List[SurveyQuestionMeta]] = {}
    for question_num in sorted(ctx.questions_metadata.keys()):
        item = ctx.questions_metadata.get(question_num)
        if not item or bool(item.is_description):
            continue
        page_number = max(1, int(item.page or 1))
        grouped.setdefault(page_number, []).append(item)
    return [grouped[key] for key in sorted(grouped.keys())]

def _wait_for_page_transition(
    driver: BrowserDriver,
    current_first_question_id: str,
    next_first_question_id: str,
    timeout_ms: int = 12000,
) -> None:
    page = _page(driver)
    current_selector = f'section.question[data-question-id="{current_first_question_id}"]'
    next_selector = f'section.question[data-question-id="{next_first_question_id}"]'
    try:
        page.wait_for_selector(current_selector, state="hidden", timeout=min(4000, timeout_ms))
    except Exception:
        pass
    page.wait_for_selector(next_selector, state="visible", timeout=timeout_ms)
