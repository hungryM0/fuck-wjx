"""腾讯问卷运行时底层页面交互。"""
from __future__ import annotations

import time
from typing import List, Optional, Sequence

from software.network.browser import BrowserDriver


def _page(driver: BrowserDriver):
    page = getattr(driver, "page", None)
    if page is None:
        raise RuntimeError("当前浏览器驱动不支持腾讯问卷自动填写")
    return page

def _wait_for_question_visible(driver: BrowserDriver, provider_question_id: str, timeout_ms: int = 8000) -> bool:
    if not provider_question_id:
        return False
    selector = f'section.question[data-question-id="{provider_question_id}"]'
    try:
        _page(driver).wait_for_selector(selector, state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False

def _is_question_visible(driver: BrowserDriver, provider_question_id: str) -> bool:
    if not provider_question_id:
        return False
    try:
        return bool(
            _page(driver).evaluate(
                """(questionId) => {
                    const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                    if (!section) return false;
                    const style = window.getComputedStyle(section);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = section.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }""",
                provider_question_id,
            )
        )
    except Exception:
        return False

def _click_choice_input(driver: BrowserDriver, provider_question_id: str, input_type: str, option_index: int) -> bool:
    return bool(
        _page(driver).evaluate(
            """({ questionId, inputType, optionIndex }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section || optionIndex < 0) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const inputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                const target = inputs[optionIndex];
                if (!target) return false;
                const clickCandidates = [
                    target,
                    target.closest('label'),
                    target.closest('.question-option'),
                    target.closest('.option'),
                    target.closest('.t-radio'),
                    target.closest('.t-checkbox'),
                    target.parentElement,
                ].filter(Boolean);
                for (const node of clickCandidates) {
                    try { node.click(); } catch (e) {}
                    if (target.checked) return true;
                }
                try { target.checked = true; } catch (e) {}
                ['input', 'change', 'click'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                return !!target.checked;
            }""",
            {
                "questionId": provider_question_id,
                "inputType": str(input_type or "radio"),
                "optionIndex": int(option_index),
            },
        )
    )

def _fill_text_question(driver: BrowserDriver, provider_question_id: str, value: str) -> bool:
    if not provider_question_id:
        return False
    page = _page(driver)
    next_value = str(value or "")
    base_selector = f'section.question[data-question-id="{provider_question_id}"]'
    candidate_selectors = (
        f"{base_selector} textarea",
        f"{base_selector} input.inputs-input",
        f"{base_selector} input[type=\"text\"]",
        f"{base_selector} input[type=\"search\"]",
        f"{base_selector} input[type=\"tel\"]",
        f"{base_selector} input[type=\"number\"]",
        f"{base_selector} input",
    )
    _prepare_question_interaction(
        driver,
        provider_question_id,
        control_selectors=(
            "textarea",
            "input.inputs-input",
            "input[type=\"text\"]",
            "input",
        ),
        settle_ms=220,
    )
    for selector in candidate_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            locator.scroll_into_view_if_needed(timeout=1500)
            locator.fill(next_value, timeout=2500)
            if str(locator.input_value() or "") == next_value:
                return True
        except Exception:
            try:
                locator = page.locator(selector).first
                if locator.count() <= 0:
                    continue
                locator.scroll_into_view_if_needed(timeout=1500)
                locator.click(timeout=1500)
                locator.fill("")
                locator.type(next_value, delay=20, timeout=2500)
                if str(locator.input_value() or "") == next_value:
                    return True
            except Exception:
                continue
    return bool(
        page.evaluate(
            """({ questionId, rawValue }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const isTextInput = (el) => {
                    if (!el) return false;
                    const tag = (el.tagName || '').toLowerCase();
                    if (tag === 'textarea') return true;
                    if (tag !== 'input') return false;
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    return !type || ['text', 'search', 'tel', 'number'].includes(type);
                };
                const target = Array.from(section.querySelectorAll('textarea, input')).find((el) => visible(el) && isTextInput(el));
                if (!target) return false;
                const nextValue = String(rawValue || '');
                try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                try { target.focus(); } catch (e) {}
                try {
                    const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                    if (descriptor && descriptor.set) {
                        descriptor.set.call(target, nextValue);
                    } else {
                        target.value = nextValue;
                    }
                } catch (e) {
                    try { target.value = nextValue; } catch (err) {}
                }
                try { target.setAttribute('value', nextValue); } catch (e) {}
                ['input', 'change', 'blur'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                return String(target.value || '') === nextValue;
            }""",
            {"questionId": provider_question_id, "rawValue": next_value},
        )
    )

def _fill_choice_option_additional_text(
    driver: BrowserDriver,
    provider_question_id: str,
    option_index: int,
    value: Optional[str],
    *,
    input_type: Optional[str] = None,
) -> bool:
    if not provider_question_id or option_index < 0:
        return False
    text = str(value or "").strip()
    if not text:
        return False
    page = _page(driver)
    return bool(
        page.evaluate(
            """({ questionId, optionIndex, rawValue, inputType }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section || optionIndex < 0) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const isTextInput = (el) => {
                    if (!el) return false;
                    const tag = String(el.tagName || '').toLowerCase();
                    if (tag === 'textarea') return true;
                    if (tag !== 'input') return false;
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    return !type || ['text', 'search', 'tel', 'number'].includes(type);
                };
                const normalize = (textValue) => String(textValue || '').trim().replace(/\\s+/g, ' ');
                const allTextInputs = Array.from(section.querySelectorAll('textarea, input')).filter((el) => visible(el) && isTextInput(el));
                const containers = [];
                const pushContainer = (node) => {
                    if (!node || containers.includes(node)) return;
                    containers.push(node);
                };
                if (inputType) {
                    const optionInputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                    const targetInput = optionInputs[optionIndex];
                    pushContainer(targetInput?.closest('.question-option'));
                    pushContainer(targetInput?.closest('.option'));
                    pushContainer(targetInput?.closest('.t-radio'));
                    pushContainer(targetInput?.closest('.t-checkbox'));
                    pushContainer(targetInput?.closest('.question-item'));
                    pushContainer(targetInput?.closest('label'));
                    pushContainer(targetInput?.parentElement);
                }
                const checkedInputs = Array.from(section.querySelectorAll('input[type="radio"]:checked, input[type="checkbox"]:checked')).filter(visible);
                for (const checked of checkedInputs) {
                    pushContainer(checked.closest('.question-option'));
                    pushContainer(checked.closest('.option'));
                    pushContainer(checked.closest('.t-radio'));
                    pushContainer(checked.closest('.t-checkbox'));
                    pushContainer(checked.closest('.question-item'));
                    pushContainer(checked.closest('label'));
                    pushContainer(checked.parentElement);
                }
                let target = null;
                for (const container of containers) {
                    const candidate = Array.from(container.querySelectorAll('textarea, input')).find((el) => visible(el) && isTextInput(el));
                    if (candidate) {
                        target = candidate;
                        break;
                    }
                }
                if (!target && allTextInputs.length === 1) {
                    target = allTextInputs[0];
                }
                if (!target) {
                    const normalizedValue = normalize(rawValue);
                    target = allTextInputs.find((el) => normalize(el.value) === normalizedValue) || null;
                }
                if (!target) return false;
                const nextValue = String(rawValue || '');
                try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                try { target.focus(); } catch (e) {}
                try {
                    const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                    if (descriptor && descriptor.set) {
                        descriptor.set.call(target, nextValue);
                    } else {
                        target.value = nextValue;
                    }
                } catch (e) {
                    try { target.value = nextValue; } catch (err) {}
                }
                try { target.setAttribute('value', nextValue); } catch (e) {}
                ['input', 'change', 'blur'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                return normalize(target.value) === normalize(nextValue);
            }""",
            {
                "questionId": provider_question_id,
                "optionIndex": int(option_index),
                "rawValue": text,
                "inputType": str(input_type or "").strip() or None,
            },
        )
    )

def _prepare_question_interaction(
    driver: BrowserDriver,
    provider_question_id: str,
    *,
    control_selectors: Sequence[str],
    settle_ms: int = 180,
) -> bool:
    if not provider_question_id:
        return False
    page = _page(driver)
    base_selector = f'section.question[data-question-id="{provider_question_id}"]'
    selectors = [f"{base_selector} {selector}" for selector in control_selectors] + [base_selector]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, state="attached", timeout=2500)
        except Exception:
            continue
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            locator.scroll_into_view_if_needed(timeout=1800)
            page.wait_for_timeout(max(0, int(settle_ms or 0)))
            return True
        except Exception:
            continue
    return False

def _is_dropdown_open(driver: BrowserDriver, provider_question_id: str) -> bool:
    if not provider_question_id:
        return False
    page = _page(driver)
    selector = f'section.question[data-question-id="{provider_question_id}"]'
    try:
        return bool(
            page.evaluate(
                """(questionSelector) => {
                    const section = document.querySelector(questionSelector);
                    if (!section) return false;
                    const trigger = section.querySelector('.t-select, .t-input__wrap, .t-input');
                    if (trigger) {
                        const className = String(trigger.className || '');
                        if (className.includes('t-popup-open') || className.includes('t-is-focused')) return true;
                    }
                    return !!Array.from(document.querySelectorAll('.t-select-option, [role="listitem"], .t-popup li')).find((el) => {
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width > 0 && rect.height > 0;
                    });
                }""",
                selector,
            )
        )
    except Exception:
        return False

def _open_dropdown(driver: BrowserDriver, provider_question_id: str) -> bool:
    if not provider_question_id:
        return False
    page = _page(driver)
    base_selector = f'section.question[data-question-id="{provider_question_id}"]'
    candidate_selectors = (
        f"{base_selector} input.t-input__inner",
        f"{base_selector} .t-input",
        f"{base_selector} .t-input__suffix",
        f"{base_selector} .t-select",
        f"{base_selector} .t-select__wrap",
    )
    for selector in candidate_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            locator.scroll_into_view_if_needed(timeout=1500)
            locator.click(timeout=1500)
        except Exception:
            continue
        try:
            page.wait_for_timeout(150)
        except Exception:
            time.sleep(0.15)
        if _is_dropdown_open(driver, provider_question_id):
            return True
    return False

def _read_dropdown_value(driver: BrowserDriver, provider_question_id: str) -> str:
    if not provider_question_id:
        return ""
    page = _page(driver)
    selector = f'section.question[data-question-id="{provider_question_id}"] input.t-input__inner'
    try:
        locator = page.locator(selector).first
        if locator.count() <= 0:
            return ""
        return str(locator.input_value() or "").strip()
    except Exception:
        return ""

def _wait_dropdown_value(driver: BrowserDriver, provider_question_id: str, expected_text: str, timeout_ms: int = 1200) -> bool:
    normalized_expected = str(expected_text or "").strip()
    if not provider_question_id or not normalized_expected:
        return False
    page = _page(driver)
    deadline = time.time() + max(0.1, timeout_ms / 1000.0)
    while time.time() < deadline:
        current_value = _read_dropdown_value(driver, provider_question_id)
        if current_value == normalized_expected:
            return True
        try:
            page.wait_for_timeout(80)
        except Exception:
            time.sleep(0.08)
    return _read_dropdown_value(driver, provider_question_id) == normalized_expected

def _describe_dropdown_state(driver: BrowserDriver, provider_question_id: str) -> str:
    if not provider_question_id:
        return "question_id=empty"
    page = _page(driver)
    try:
        payload = page.evaluate(
            """(questionId) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const normalize = (text) => String(text || '').trim().replace(/\\s+/g, ' ');
                const popupScore = (popup, anchorRect) => {
                    if (!popup || !anchorRect) return Number.POSITIVE_INFINITY;
                    const rect = popup.getBoundingClientRect();
                    const dx = Math.abs(rect.left - anchorRect.left);
                    const dyTop = Math.abs(rect.top - anchorRect.bottom);
                    const dyBottom = Math.abs(rect.bottom - anchorRect.top);
                    return dx + Math.min(dyTop, dyBottom);
                };
                const pickPopup = (anchor) => {
                    const anchorRect = anchor?.getBoundingClientRect?.() || null;
                    const candidates = Array.from(document.querySelectorAll('.t-popup.t-select__dropdown')).filter((popup) => {
                        if (!visible(popup)) return false;
                        const refHidden = String(popup.getAttribute('data-popper-reference-hidden') || '').toLowerCase();
                        return refHidden !== 'true';
                    });
                    if (!candidates.length) return null;
                    if (!anchorRect) return candidates[candidates.length - 1];
                    return candidates
                        .map((popup) => ({ popup, score: popupScore(popup, anchorRect) }))
                        .sort((a, b) => a.score - b.score)[0]?.popup || candidates[candidates.length - 1];
                };
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                const input = section?.querySelector('input.t-input__inner');
                const popupCandidates = Array.from(document.querySelectorAll('.t-popup.t-select__dropdown')).filter(visible);
                const popup = pickPopup(input);
                const options = popup
                    ? Array.from(popup.querySelectorAll('.t-select-option, [role="listitem"]')).filter(visible).map((el) => normalize(el.innerText || el.textContent)).slice(0, 8)
                    : [];
                return {
                    currentValue: normalize(input?.value),
                    popupCount: popupCandidates.length,
                    options,
                };
            }""",
            provider_question_id,
        ) or {}
    except Exception as exc:
        return f"state_error={exc}"
    current_value = str(payload.get("currentValue") or "").strip()
    popup_count = int(payload.get("popupCount") or 0)
    options = list(payload.get("options") or [])
    return f"value={current_value or '-'} popup_count={popup_count} options={options}"

def _resolve_dropdown_popup_index(driver: BrowserDriver, provider_question_id: str) -> int:
    if not provider_question_id:
        return -1
    page = _page(driver)
    try:
        popup_index = page.evaluate(
            """(questionId) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const popupScore = (popup, anchorRect) => {
                    if (!popup || !anchorRect) return Number.POSITIVE_INFINITY;
                    const rect = popup.getBoundingClientRect();
                    const dx = Math.abs(rect.left - anchorRect.left);
                    const dyTop = Math.abs(rect.top - anchorRect.bottom);
                    const dyBottom = Math.abs(rect.bottom - anchorRect.top);
                    return dx + Math.min(dyTop, dyBottom);
                };
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                const input = section?.querySelector('input.t-input__inner');
                const anchorRect = input?.getBoundingClientRect?.() || null;
                const entries = Array.from(document.querySelectorAll('.t-popup.t-select__dropdown'))
                    .map((popup, index) => ({ popup, index }))
                    .filter(({ popup }) => {
                        if (!visible(popup)) return false;
                        const refHidden = String(popup.getAttribute('data-popper-reference-hidden') || '').toLowerCase();
                        if (refHidden === 'true') return false;
                        return Array.from(popup.querySelectorAll('.t-select-option, [role="listitem"]')).some(visible);
                    });
                if (!entries.length) return -1;
                if (!anchorRect) return entries[entries.length - 1].index;
                const picked = entries
                    .map((entry) => ({ index: entry.index, score: popupScore(entry.popup, anchorRect) }))
                    .sort((a, b) => a.score - b.score)[0];
                return picked ? picked.index : entries[entries.length - 1].index;
            }""",
            provider_question_id,
        )
    except Exception:
        return -1
    try:
        return int(popup_index)
    except Exception:
        return -1

def _wait_dropdown_popup_index(driver: BrowserDriver, provider_question_id: str, timeout_ms: int = 2000) -> int:
    if not provider_question_id:
        return -1
    page = _page(driver)
    deadline = time.time() + max(0.1, timeout_ms / 1000.0)
    while time.time() < deadline:
        popup_index = _resolve_dropdown_popup_index(driver, provider_question_id)
        if popup_index >= 0:
            return popup_index
        try:
            page.wait_for_timeout(80)
        except Exception:
            time.sleep(0.08)
    return _resolve_dropdown_popup_index(driver, provider_question_id)

def _select_dropdown_option(driver: BrowserDriver, provider_question_id: str, option_text: str) -> bool:
    if not provider_question_id or not str(option_text or "").strip():
        return False
    page = _page(driver)
    normalized_target = str(option_text or "").strip()
    popup_index = _wait_dropdown_popup_index(driver, provider_question_id, timeout_ms=2500)
    if popup_index < 0:
        return False
    try:
        popup_locator = page.locator('.t-popup.t-select__dropdown').nth(popup_index)
        popup_locator.wait_for(state="visible", timeout=1800)
        candidates = popup_locator.locator('.t-select-option, [role="listitem"]')
        count = candidates.count()
    except Exception:
        return False
    for index in range(count):
        try:
            candidate = candidates.nth(index)
            if not candidate.is_visible():
                continue
            text = str(candidate.inner_text() or "").strip().replace("\n", " ")
        except Exception:
            continue
        if text != normalized_target and normalized_target not in text:
            continue
        try:
            candidate.scroll_into_view_if_needed(timeout=1500)
            candidate.click(timeout=1500)
        except Exception:
            try:
                candidate.click(timeout=1500, force=True)
            except Exception:
                continue
        try:
            page.wait_for_timeout(150)
        except Exception:
            time.sleep(0.15)
        if _wait_dropdown_value(driver, provider_question_id, normalized_target, timeout_ms=1200):
            return True
    return False

def _click_matrix_cell(driver: BrowserDriver, provider_question_id: str, row_index: int, column_index: int) -> bool:
    if not provider_question_id or row_index < 0 or column_index < 0:
        return False
    page = _page(driver)
    base_selector = f'section.question[data-question-id="{provider_question_id}"]'

    def _checked_index() -> int:
        try:
            return int(
                page.evaluate(
                    """({ questionId, rowIndex }) => {
                        const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                        if (!section || rowIndex < 0) return -1;
                        const tableRows = Array.from(section.querySelectorAll('tbody tr')).filter((row) => {
                            return row && row.querySelector('input[type="radio"]');
                        });
                        const blockRows = Array.from(section.querySelectorAll('.question-item')).filter((row) => {
                            return row && row.querySelector('input[type="radio"]');
                        });
                        const rows = tableRows.length > rowIndex ? tableRows : blockRows;
                        const row = rows[rowIndex];
                        if (!row) return -1;
                        return Array.from(row.querySelectorAll('input[type="radio"]')).findIndex((input) => input.checked);
                    }""",
                    {
                        "questionId": provider_question_id,
                        "rowIndex": int(row_index),
                    },
                )
                or -1
            )
        except Exception:
            return -1

    def _click_locator(locator) -> bool:
        try:
            if locator.count() <= 0:
                return False
            locator.scroll_into_view_if_needed(timeout=1800)
        except Exception:
            return False
        for force in (False, True):
            try:
                locator.click(timeout=1800, force=force)
            except Exception:
                continue
            try:
                page.wait_for_timeout(180)
            except Exception:
                time.sleep(0.18)
            if _checked_index() == column_index:
                return True
        return False

    try:
        table_rows = page.locator(f"{base_selector} tbody tr")
        if table_rows.count() > row_index:
            row_locator = table_rows.nth(row_index)
            table_candidates = (
                row_locator.locator("td").nth(column_index + 1).locator("label.clickBlock").first,
                row_locator.locator("td").nth(column_index + 1).locator("label[for]").first,
                row_locator.locator("td").nth(column_index + 1).locator(".matrix-option").first,
                row_locator.locator("td").nth(column_index + 1),
            )
            for locator in table_candidates:
                if _click_locator(locator):
                    return True
    except Exception:
        pass

    try:
        question_rows = page.locator(f"{base_selector} .question-item")
        if question_rows.count() > row_index:
            row_locator = question_rows.nth(row_index)
            group_locator = row_locator.locator(".checkbtn").nth(column_index)
            block_candidates = (
                group_locator.locator("label.checkbtn-label").first,
                group_locator.locator("label[for]").first,
                group_locator,
                row_locator.locator('input[type="radio"]').nth(column_index),
            )
            for locator in block_candidates:
                if _click_locator(locator):
                    return True
    except Exception:
        pass

    return bool(
        page.evaluate(
            """async ({ questionId, rowIndex, columnIndex }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section || rowIndex < 0 || columnIndex < 0) return false;
                const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
                const tableRows = Array.from(section.querySelectorAll('tbody tr')).filter((row) => {
                    return row && row.querySelector('input[type="radio"]');
                });
                const blockRows = Array.from(section.querySelectorAll('.question-item')).filter((row) => {
                    return row && row.querySelector('input[type="radio"]');
                });
                const rows = tableRows.length > rowIndex ? tableRows : blockRows;
                const row = rows[rowIndex];
                if (!row) return false;
                try { row.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                await wait(100);
                const inputs = Array.from(row.querySelectorAll('input[type="radio"]'));
                const target = inputs[columnIndex];
                if (!target) return false;
                const currentCheckedIndex = () => Array.from(row.querySelectorAll('input[type="radio"]')).findIndex((input) => input.checked);
                const isConfirmed = () => currentCheckedIndex() === columnIndex;
                if (isConfirmed()) return true;
                const targetId = String(target.id || '');
                const labelByFor = targetId
                    ? (row.querySelector(`label.clickBlock[for="${targetId}"]`) || row.querySelector(`label[for="${targetId}"]`))
                    : null;
                const clickCandidates = [
                    labelByFor,
                    target.closest('label.clickBlock'),
                    target.closest('.checkbtn'),
                    target.closest('.matrix-option'),
                    target.closest('.ui-radio'),
                    target.closest('td'),
                    target.closest('label'),
                    target.parentElement,
                    target,
                ].filter(Boolean);
                for (const node of clickCandidates) {
                    try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    await wait(80);
                    try { node.click(); } catch (e) {}
                    await wait(180);
                    if (isConfirmed()) return true;
                    try {
                        node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                    } catch (e) {}
                    await wait(180);
                    if (isConfirmed()) return true;
                }
                try { target.checked = true; } catch (e) {}
                ['input', 'change', 'click'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                await wait(180);
                return isConfirmed();
            }""",
            {
                "questionId": provider_question_id,
                "rowIndex": int(row_index),
                "columnIndex": int(column_index),
            },
        )
    )

def _normalize_selected_indices(indices: Sequence[int], option_count: int) -> List[int]:
    result: List[int] = []
    seen = set()
    for raw in indices:
        try:
            idx = int(raw)
        except Exception:
            continue
        if idx < 0 or idx >= option_count or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)

def _apply_multiple_constraints(
    selected_indices: Sequence[int],
    option_count: int,
    min_required: int,
    max_allowed: int,
    required_indices: Sequence[int],
    blocked_indices: Sequence[int],
    positive_priority_indices: Sequence[int],
) -> List[int]:
    blocked = set(_normalize_selected_indices(blocked_indices, option_count))
    required = _normalize_selected_indices(required_indices, option_count)
    selected = [idx for idx in _normalize_selected_indices(selected_indices, option_count) if idx not in blocked]
    for idx in required:
        if idx not in selected:
            selected.append(idx)
    selected = _normalize_selected_indices(selected, option_count)
    max_allowed = max(1, min(max_allowed, option_count))
    min_required = max(1, min(min_required, option_count))
    if len(selected) > max_allowed:
        kept = list(required[:max_allowed])
        for idx in selected:
            if idx in kept:
                continue
            if len(kept) >= max_allowed:
                break
            kept.append(idx)
        selected = _normalize_selected_indices(kept, option_count)
    if len(selected) < min_required:
        for idx in list(positive_priority_indices) + list(range(option_count)):
            if idx in blocked or idx in selected:
                continue
            selected.append(idx)
            if len(selected) >= min_required:
                break
    if len(selected) > max_allowed:
        selected = selected[:max_allowed]
    return _normalize_selected_indices(selected, option_count)
