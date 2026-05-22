"""Tencent batch answer action applier."""

from __future__ import annotations

from typing import Sequence

from software.network.browser.runtime_async import BrowserDriver
from software.providers.answering import AnswerAction, BatchFillResult
from software.providers.answering.actions import action_payload as _action_payload

async def apply_answer_actions(driver: BrowserDriver, actions: Sequence[AnswerAction]) -> BatchFillResult:
    normalized_actions = [
        action
        for action in list(actions or [])
        if int(action.question_num or 0) > 0 and str(action.question_id or "").strip()
    ]
    if not normalized_actions:
        return BatchFillResult()
    page = await driver.page()
    if page is None:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized_actions))
    payload = [_action_payload(action) for action in normalized_actions]
    try:
        raw_result = await page.evaluate(
            r"""(actions) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const dispatch = (target, names = ['input', 'change', 'click']) => {
                    for (const name of names) {
                        try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                    }
                };
                const setNativeValue = (target, value) => {
                    const nextValue = String(value ?? '');
                    try {
                        const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                        const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                        if (descriptor && descriptor.set) descriptor.set.call(target, nextValue);
                        else target.value = nextValue;
                    } catch (e) {
                        try { target.value = nextValue; } catch (err) {}
                    }
                    try { target.setAttribute('value', nextValue); } catch (e) {}
                    dispatch(target, ['input', 'change', 'blur']);
                };
                const isTextInput = (el) => {
                    if (!el) return false;
                    const tag = String(el.tagName || '').toLowerCase();
                    if (tag === 'textarea') return true;
                    if (tag !== 'input') return false;
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    return !type || ['text', 'search', 'tel', 'number'].includes(type);
                };
                const clickChoice = (section, inputType, optionIndex) => {
                    const inputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                    const target = inputs[optionIndex] || null;
                    if (!target) return false;
                    const candidates = [
                        target.closest('label'),
                        target.closest('.question-option'),
                        target.closest('.option'),
                        target.closest('.t-radio'),
                        target.closest('.t-checkbox'),
                        target.parentElement,
                        target,
                    ].filter(Boolean);
                    for (const node of candidates) {
                        try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { node.click(); } catch (e) {}
                        if (target.checked) return true;
                    }
                    try { target.checked = true; } catch (e) {}
                    dispatch(target);
                    return !!target.checked;
                };
                const fillOptionText = (section, optionIndex, value, inputType) => {
                    const text = String(value || '').trim();
                    if (!text) return true;
                    const optionInputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                    const targetInput = optionInputs[optionIndex] || null;
                    const containers = [
                        targetInput?.closest('.question-option'),
                        targetInput?.closest('.option'),
                        targetInput?.closest('.t-radio'),
                        targetInput?.closest('.t-checkbox'),
                        targetInput?.closest('.question-item'),
                        targetInput?.closest('label'),
                        targetInput?.parentElement,
                    ].filter(Boolean);
                    for (const container of containers) {
                        const target = Array.from(container.querySelectorAll('textarea, input')).find((el) => visible(el) && isTextInput(el));
                        if (!target) continue;
                        setNativeValue(target, text);
                        return String(target.value || '') === text;
                    }
                    return false;
                };
                const applyText = (section, values) => {
                    const textValues = Array.isArray(values) && values.length ? values.map((item) => String(item ?? '')) : [''];
                    const inputs = Array.from(section.querySelectorAll('textarea, input')).filter((el) => visible(el) && isTextInput(el));
                    if (!inputs.length) return false;
                    let applied = 0;
                    inputs.forEach((target, index) => {
                        const value = textValues[index] ?? textValues[textValues.length - 1] ?? '';
                        try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { target.focus(); } catch (e) {}
                        setNativeValue(target, value);
                        if (String(target.value || '') === value) applied += 1;
                    });
                    return applied > 0 && applied >= Math.min(inputs.length, textValues.length);
                };
                const applyMatrix = (section, indices) => {
                    const tableRows = Array.from(section.querySelectorAll('tbody tr')).filter((row) => row && row.querySelector('input[type="radio"]') && visible(row));
                    const blockRows = Array.from(section.querySelectorAll('.question-item')).filter((row) => row && row.querySelector('input[type="radio"]') && visible(row));
                    const rows = tableRows.length ? tableRows : blockRows;
                    if (!rows.length) return false;
                    let applied = 0;
                    indices.forEach((rawIndex, rowIndex) => {
                        const colIndex = Number(rawIndex);
                        const row = rows[rowIndex];
                        if (!row || colIndex < 0) return;
                        const inputs = Array.from(row.querySelectorAll('input[type="radio"]')).filter(visible);
                        const target = inputs[colIndex] || null;
                        if (!target) return;
                        const candidates = [
                            target.closest('label'),
                            target.closest('.checkbtn'),
                            target.closest('.matrix-option'),
                            target.closest('td'),
                            target.parentElement,
                            target,
                        ].filter(Boolean);
                        for (const node of candidates) {
                            try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                            try { node.click(); } catch (e) {}
                            if (target.checked) break;
                        }
                        if (!target.checked) {
                            try { target.checked = true; } catch (e) {}
                            dispatch(target);
                        }
                        if (target.checked) applied += 1;
                    });
                    return applied === indices.length;
                };
                const applied = [];
                const failed = [];
                for (const action of actions || []) {
                    const questionNum = Number(action.questionNum || 0);
                    const section = document.querySelector(`section.question[data-question-id="${action.questionId}"]`);
                    if (!section || !visible(section)) {
                        failed.push(questionNum);
                        continue;
                    }
                    let ok = false;
                    try {
                        if (action.kind === 'choice') {
                            const selected = Array.isArray(action.selectedIndices) ? action.selectedIndices : [];
                            ok = selected.length > 0 && selected.every((index) => clickChoice(section, action.inputType || 'radio', Number(index)));
                            if (ok && Array.isArray(action.optionFillTexts)) {
                                ok = action.optionFillTexts.every((item) => fillOptionText(section, Number(item.optionIndex), item.value, action.inputType || 'radio'));
                            }
                        } else if (action.kind === 'text') {
                            ok = applyText(section, action.textValues);
                        } else if (action.kind === 'matrix') {
                            ok = applyMatrix(section, action.matrixIndices || []);
                        }
                    } catch (e) {
                        ok = false;
                    }
                    if (ok) applied.push(questionNum);
                    else failed.push(questionNum);
                }
                return { applied, failed };
            }""",
            payload,
        ) or {}
    except Exception:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized_actions))
    applied = tuple(int(item) for item in list(raw_result.get("applied") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else ()
    failed = tuple(int(item) for item in list(raw_result.get("failed") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else tuple(int(action.question_num) for action in normalized_actions)
    return BatchFillResult(applied=applied, failed=failed)

