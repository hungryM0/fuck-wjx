"""Credamo batch answer action applier."""

from __future__ import annotations

from typing import Any

from software.providers.answering import AnswerAction, BatchFillResult



async def apply_answer_actions(page: Any, actions: list[AnswerAction]) -> BatchFillResult:
    normalized = [action for action in list(actions or []) if int(action.root_index) >= 0 and int(action.question_num or 0) > 0]
    if not normalized:
        return BatchFillResult()
    payload = [
        {
            "rootIndex": int(action.root_index),
            "questionNum": int(action.question_num),
            "kind": str(action.kind or ""),
            "selectedIndices": [int(item) for item in action.selected_indices],
            "matrixIndices": [int(item) for item in action.matrix_indices],
            "textValues": [str(item or "") for item in action.text_values],
        }
        for action in normalized
    ]
    try:
        raw_result = await page.evaluate(
            r"""(actions) => {
                const roots = Array.from(document.querySelectorAll('.answer-page .question')).filter((root) => {
                    const style = window.getComputedStyle(root);
                    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = root.getBoundingClientRect();
                    return rect.width >= 8 && rect.height >= 8;
                });
                const visible = (node, minWidth = 4, minHeight = 4) => {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width >= minWidth && rect.height >= minHeight;
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
                    return !type || ['text', 'search', 'number', 'tel', 'email'].includes(type);
                };
                const clickOption = (root, selector, index) => {
                    const controls = Array.from(root.querySelectorAll(selector)).filter(visible);
                    const target = controls[index] || null;
                    if (!target) return false;
                    const candidates = [
                        target.closest('label'),
                        target.closest('.choice-row'),
                        target.closest('.choice'),
                        target.closest('.el-radio'),
                        target.closest('.el-checkbox'),
                        target.parentElement,
                        target,
                    ].filter(Boolean);
                    for (const node of candidates) {
                        try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { node.click(); } catch (e) {}
                        if (target.checked || target.getAttribute('aria-checked') === 'true') return true;
                    }
                    try { target.checked = true; } catch (e) {}
                    try { target.setAttribute('aria-checked', 'true'); } catch (e) {}
                    dispatch(target);
                    return !!target.checked || target.getAttribute('aria-checked') === 'true';
                };
                const applyText = (root, values) => {
                    const textValues = Array.isArray(values) && values.length ? values.map((item) => String(item ?? '')) : [''];
                    const inputs = Array.from(
                        root.querySelectorAll("textarea, input:not([readonly])[type='text'], input:not([readonly])[type='search'], input:not([readonly])[type='number'], input:not([readonly])[type='tel'], input:not([readonly])[type='email'], input:not([readonly]):not([type])")
                    ).filter(visible);
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
                const applyScale = (root, index) => {
                    const options = Array.from(root.querySelectorAll('.scale .nps-item, .nps-item, .el-rate__item')).filter(visible);
                    const target = options[index] || null;
                    if (!target) return false;
                    try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { target.click(); } catch (e) {}
                    try { target.classList.add('selected'); } catch (e) {}
                    return true;
                };
                const applyMatrix = (root, indices) => {
                    const rows = Array.from(root.querySelectorAll('tbody tr, .matrix-row, .el-table__row')).filter((row) => visible(row));
                    let answerableRows = rows.filter((row) => row.querySelectorAll("input[type='radio'], [role='radio'], .el-radio, .el-radio__input").length >= 2);
                    if (!answerableRows.length) return false;
                    let applied = 0;
                    indices.forEach((rawIndex, rowIndex) => {
                        const row = answerableRows[rowIndex];
                        const colIndex = Number(rawIndex);
                        if (!row || colIndex < 0) return;
                        const controls = Array.from(row.querySelectorAll("input[type='radio'], [role='radio'], .el-radio, .el-radio__input")).filter(visible);
                        const target = controls[colIndex] || null;
                        if (!target) return;
                        const candidates = [target.closest('label'), target.closest('.el-radio'), target.parentElement, target].filter(Boolean);
                        for (const node of candidates) {
                            try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                            try { node.click(); } catch (e) {}
                            if (target.checked || target.getAttribute('aria-checked') === 'true' || target.classList.contains('is-checked')) break;
                        }
                        try { target.checked = true; } catch (e) {}
                        try { target.setAttribute('aria-checked', 'true'); } catch (e) {}
                        try { target.classList.add('is-checked'); } catch (e) {}
                        dispatch(target);
                        applied += 1;
                    });
                    return applied === indices.length;
                };
                const applied = [];
                const failed = [];
                for (const action of actions || []) {
                    const rootIndex = Number(action.rootIndex);
                    const questionNum = Number(action.questionNum || 0);
                    const root = roots[rootIndex] || null;
                    if (!root) {
                        failed.push(questionNum);
                        continue;
                    }
                    let ok = false;
                    try {
                        if (action.kind === 'single') {
                            ok = clickOption(root, "input[type='radio'], [role='radio']", Number((action.selectedIndices || [])[0] ?? -1));
                        } else if (action.kind === 'multiple') {
                            const selected = Array.isArray(action.selectedIndices) ? action.selectedIndices : [];
                            ok = selected.length > 0 && selected.every((index) => clickOption(root, "input[type='checkbox'], [role='checkbox']", Number(index)));
                        } else if (action.kind === 'scale') {
                            ok = applyScale(root, Number((action.selectedIndices || [])[0] ?? -1));
                        } else if (action.kind === 'matrix') {
                            ok = applyMatrix(root, action.matrixIndices || []);
                        } else if (action.kind === 'text' || action.kind === 'multi_text') {
                            ok = applyText(root, action.textValues);
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
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized))
    applied = tuple(int(item) for item in list(raw_result.get("applied") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else ()
    failed = tuple(int(item) for item in list(raw_result.get("failed") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else tuple(int(action.question_num) for action in normalized)
    return BatchFillResult(applied=applied, failed=failed)
