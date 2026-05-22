"""WJX batch answer action applier."""

from __future__ import annotations

from typing import Sequence

from software.network.browser.runtime_async import BrowserDriver
from software.providers.answering import AnswerAction, BatchFillResult
from software.providers.answering.actions import action_payload as _action_payload

async def apply_answer_actions(driver: BrowserDriver, actions: Sequence[AnswerAction]) -> BatchFillResult:
    unsupported_actions = [
        action
        for action in list(actions or [])
        if int(action.question_num or 0) > 0 and str(action.kind or "").strip() in {"location", "order"}
    ]
    normalized_actions = [
        action
        for action in list(actions or [])
        if int(action.question_num or 0) > 0 and str(action.kind or "").strip() not in {"location", "order"}
    ]
    if not normalized_actions:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in unsupported_actions))
    payload = [_action_payload(action) for action in normalized_actions]
    script = r"""
        return (() => {
            const actions = Array.isArray(arguments[0]) ? arguments[0] : [];
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
                dispatch(target, ['beforeinput', 'input', 'change', 'blur']);
            };
            const isTextInput = (el) => {
                if (!el) return false;
                const tag = String(el.tagName || '').toLowerCase();
                if (tag === 'textarea') return true;
                if (tag !== 'input') return false;
                const type = String(el.getAttribute('type') || '').toLowerCase();
                return !type || ['text', 'search', 'tel', 'number'].includes(type);
            };
            const clickChoice = (root, inputType, optionIndex) => {
                const inputs = Array.from(root.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                const target = inputs[optionIndex] || null;
                const listCandidates = [
                    ...Array.from(root.querySelectorAll('.ui-controlgroup > div')),
                    ...Array.from(root.querySelectorAll("ul[tp='d'] li")),
                    ...Array.from(root.querySelectorAll('.scale-rating ul li')),
                ].filter(visible);
                const visualTarget = listCandidates[optionIndex] || null;
                if (!target && !visualTarget) return false;
                const labelByFor = target && target.id ? root.querySelector(`label[for="${target.id}"]`) : null;
                const candidates = [
                    labelByFor,
                    target?.closest('label'),
                    target?.closest('.ui-controlgroup > div'),
                    target?.closest('li'),
                    target?.parentElement,
                    target,
                    visualTarget?.querySelector('a'),
                    visualTarget,
                ].filter(Boolean);
                for (const node of candidates) {
                    try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { node.click(); } catch (e) {}
                    if (!target || target.checked) return true;
                }
                if (target) {
                    try { target.checked = true; } catch (e) {}
                    dispatch(target);
                    return !!target.checked;
                }
                return !!visualTarget;
            };
            const fillOptionText = (root, optionIndex, value) => {
                const text = String(value || '').trim();
                if (!text) return true;
                const optionRoots = Array.from(root.querySelectorAll('.ui-controlgroup > div'));
                const optionRoot = optionRoots[optionIndex] || null;
                const target = optionRoot
                    ? Array.from(optionRoot.querySelectorAll('input, textarea')).find((el) => visible(el) && isTextInput(el))
                    : null;
                if (!target) return false;
                setNativeValue(target, text);
                return String(target.value || '') === text;
            };
            const applyText = (root, values) => {
                const textValues = Array.isArray(values) && values.length ? values.map((item) => String(item ?? '')) : [''];
                const editableNodes = Array.from(root.querySelectorAll('.textEdit .textCont[contenteditable="true"], .textCont[contenteditable="true"], [contenteditable="true"]'))
                    .filter((el) => visible(el) || visible(el.closest('.textEdit')));
                const textInputs = Array.from(root.querySelectorAll('textarea, input')).filter((el) => visible(el) && isTextInput(el));
                const targets = editableNodes.length ? editableNodes : textInputs;
                if (!targets.length) return false;
                let applied = 0;
                targets.forEach((target, index) => {
                    const value = textValues[index] ?? textValues[textValues.length - 1] ?? '';
                    try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { target.focus(); } catch (e) {}
                    if (target.isContentEditable) {
                        try { target.textContent = value; } catch (e) {}
                        try { target.innerText = value; } catch (e) {}
                        dispatch(target, ['beforeinput', 'input', 'change', 'blur']);
                        const hidden = textInputs[index] || null;
                        if (hidden) setNativeValue(hidden, value);
                        const actual = String((hidden && hidden.value) || target.textContent || target.innerText || '');
                        if (actual === value) applied += 1;
                    } else {
                        setNativeValue(target, value);
                        if (String(target.value || '') === value) applied += 1;
                    }
                });
                return applied > 0 && applied >= Math.min(targets.length, textValues.length);
            };
            const applyMatrix = (root, indices) => {
                const rows = Array.from(root.querySelectorAll('tr')).filter((node) => {
                    const id = String(node.getAttribute('id') || '');
                    return /^drv\d+_\d+$/.test(id) && visible(node);
                });
                if (!rows.length) return false;
                let applied = 0;
                indices.forEach((rawIndex, rowIndex) => {
                    const colIndex = Number(rawIndex);
                    const row = rows[rowIndex];
                    if (!row || colIndex < 0) return;
                    const anchors = Array.from(row.querySelectorAll('a[dval]')).filter(visible);
                    const anchor = anchors[colIndex] || null;
                    if (anchor) {
                        const value = String(anchor.getAttribute('dval') || colIndex + 1);
                        try { anchor.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { anchor.click(); } catch (e) {}
                        try { anchor.classList.add('rate-on'); } catch (e) {}
                        const fid = String(row.getAttribute('fid') || '');
                        const hidden = fid ? document.getElementById(fid) : null;
                        if (hidden) {
                            setNativeValue(hidden, value);
                            if (String(hidden.value || '') === value) applied += 1;
                        } else {
                            applied += 1;
                        }
                        return;
                    }
                    const inputs = Array.from(row.querySelectorAll("input[type='radio'], input[type='checkbox']")).filter(visible);
                    const target = inputs[colIndex] || null;
                    if (!target) return;
                    const candidates = [target.closest('label'), target.closest('td'), target.parentElement, target].filter(Boolean);
                    for (const node of candidates) {
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
            const applySlider = (root, questionNum, rawValue) => {
                const input = root.querySelector(`#q${questionNum}, input.ui-slider-input, input[type="range"]`);
                const targetValue = Number(rawValue);
                if (!input || Number.isNaN(targetValue)) return false;
                const minValue = Number(input.getAttribute('min') || 0);
                const maxValue = Number(input.getAttribute('max') || 100);
                const stepValue = Math.abs(Number(input.getAttribute('step') || 1)) || 1;
                let nextValue = Math.max(minValue, Math.min(maxValue, targetValue));
                nextValue = minValue + Math.round((nextValue - minValue) / stepValue) * stepValue;
                if (Math.abs(nextValue - Math.round(nextValue)) < 1e-6) nextValue = Math.round(nextValue);
                setNativeValue(input, String(nextValue));
                return String(input.value || '') === String(nextValue);
            };
            const applied = [];
            const failed = [];
            for (const action of actions) {
                const questionNum = Number(action.questionNum || 0);
                const root = document.querySelector(`#div${questionNum}`);
                if (!root || !visible(root)) {
                    failed.push(questionNum);
                    continue;
                }
                let ok = false;
                try {
                    if (action.kind === 'choice') {
                        const selected = Array.isArray(action.selectedIndices) ? action.selectedIndices : [];
                        ok = selected.length > 0 && selected.every((index) => clickChoice(root, action.inputType || 'radio', Number(index)));
                        if (ok && Array.isArray(action.optionFillTexts)) {
                            ok = action.optionFillTexts.every((item) => fillOptionText(root, Number(item.optionIndex), item.value));
                        }
                    } else if (action.kind === 'select') {
                        const select = root.querySelector(`#q${questionNum}, select`);
                        const selectedIndex = Number((action.selectedIndices || [])[0] ?? -1);
                        if (select && selectedIndex >= 0) {
                            const options = Array.from(select.options || []);
                            const validOptions = options.filter((opt, idx) => {
                                const text = String(opt.textContent || opt.innerText || '').replace(/\s+/g, ' ').trim();
                                const value = String(opt.value || '').trim();
                                if (idx !== 0) return true;
                                if (!text || value === '' || value === '0' || value === '-1' || value === '-2') return false;
                                return !text.replace(/\s+/g, '').startsWith('请选择');
                            });
                            const target = validOptions[selectedIndex] || null;
                            if (target) {
                                target.selected = true;
                                select.value = target.value;
                                dispatch(select, ['input', 'change', 'blur']);
                                ok = String(select.value || '') === String(target.value || '');
                            }
                        }
                        if (ok && Array.isArray(action.optionFillTexts)) {
                            ok = action.optionFillTexts.every((item) => fillOptionText(root, Number(item.optionIndex), item.value));
                        }
                    } else if (action.kind === 'text') {
                        ok = applyText(root, action.textValues);
                    } else if (action.kind === 'matrix') {
                        ok = applyMatrix(root, action.matrixIndices || []);
                    } else if (action.kind === 'slider') {
                        ok = applySlider(root, questionNum, action.sliderValue);
                    }
                } catch (e) {
                    ok = false;
                }
                if (ok) applied.push(questionNum);
                else failed.push(questionNum);
            }
            return { applied, failed };
        })();
    """
    try:
        raw_result = await driver.execute_script(script, payload) or {}
    except Exception:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized_actions))
    applied = tuple(int(item) for item in list(raw_result.get("applied") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else ()
    failed = tuple(int(item) for item in list(raw_result.get("failed") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else tuple(int(action.question_num) for action in normalized_actions)
    return BatchFillResult(
        applied=applied,
        failed=failed + tuple(int(action.question_num) for action in unsupported_actions),
    )

