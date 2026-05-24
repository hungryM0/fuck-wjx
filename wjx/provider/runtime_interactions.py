"""WJX 运行时底层页面交互。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Sequence

from software.core.engine.async_wait import sleep_or_stop
from software.network.browser.runtime_async import BrowserDriver


async def _page(driver: BrowserDriver) -> Any:
    page = await driver.page()
    if page is None:
        raise RuntimeError("当前浏览器驱动不支持问卷星原生异步填写")
    return page


async def _wait_for_question_root(driver: BrowserDriver, question_number: int, timeout_ms: int = 2500) -> bool:
    if int(question_number or 0) <= 0:
        return False
    page = await _page(driver)
    selector = f"#div{int(question_number)}"
    try:
        await page.wait_for_selector(selector, state="attached", timeout=max(100, int(timeout_ms or 0)))
    except Exception:
        return False
    return await _is_question_visible(driver, question_number)


async def _is_question_visible(driver: BrowserDriver, question_number: int) -> bool:
    if int(question_number or 0) <= 0:
        return False
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            if (!questionNumber) return false;
            const node = document.querySelector(`#div${questionNumber}`);
            if (!node) return false;
            const style = window.getComputedStyle(node);
            if (!style) return false;
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        })();
    """
    try:
        return bool(await driver.execute_script(script, int(question_number)))
    except Exception:
        return False


async def _collect_visible_question_snapshot(driver: BrowserDriver) -> dict[int, dict[str, Any]]:
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
            const result = {};
            const nodes = Array.from(document.querySelectorAll('#divQuestion [topic], #divQuestion div[id^="div"]'));
            for (const node of nodes) {
                const rawTopic = String(node.getAttribute('topic') || '').trim();
                const idMatch = String(node.getAttribute('id') || '').trim().match(/^div(\d+)$/);
                const questionNum = rawTopic && /^\d+$/.test(rawTopic)
                    ? Number.parseInt(rawTopic, 10)
                    : (idMatch ? Number.parseInt(idMatch[1], 10) : 0);
                if (!questionNum) continue;
                result[String(questionNum)] = {
                    visible: visible(node),
                    type: String(node.getAttribute('type') || '').trim(),
                    text: normalize(node.innerText || node.textContent || '').slice(0, 240),
                };
            }
            return result;
        })();
    """
    try:
        payload = await driver.execute_script(script) or {}
    except Exception:
        payload = {}
    result: dict[int, dict[str, Any]] = {}
    if not isinstance(payload, dict):
        return result
    for raw_key, item in payload.items():
        try:
            question_num = int(raw_key)
        except Exception:
            continue
        if question_num <= 0 or not isinstance(item, dict):
            continue
        result[question_num] = {
            "visible": bool(item.get("visible")),
            "type": str(item.get("type") or "").strip(),
            "text": str(item.get("text") or "").strip(),
        }
    return result


async def _wait_for_any_visible_questions(
    driver: BrowserDriver,
    *,
    timeout_ms: int = 2500,
    poll_ms: int = 80,
) -> dict[int, dict[str, Any]]:
    snapshot = await _collect_visible_question_snapshot(driver)
    if any(bool(item.get("visible")) for item in snapshot.values()):
        return snapshot
    page = await _page(driver)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, float(timeout_ms or 0) / 1000.0)
    while loop.time() < deadline:
        try:
            await page.wait_for_timeout(max(20, int(poll_ms or 0)))
        except Exception:
            await sleep_or_stop(None, max(0.02, float(poll_ms or 0) / 1000.0))
        snapshot = await _collect_visible_question_snapshot(driver)
        if any(bool(item.get("visible")) for item in snapshot.values()):
            return snapshot
    return snapshot


async def _prepare_question_interaction(driver: BrowserDriver, question_number: int, *, settle_ms: int = 120) -> bool:
    if not await _wait_for_question_root(driver, question_number, timeout_ms=2500):
        return False
    page = await _page(driver)
    selector = f"#div{int(question_number)}"
    try:
        locator = page.locator(selector).first
        if await locator.count() <= 0:
            return False
        await locator.scroll_into_view_if_needed(timeout=1800)
        await page.wait_for_timeout(max(0, int(settle_ms or 0)))
        return True
    except Exception:
        return False


async def _click_js(driver: BrowserDriver, selector: str, *, verify_selector: Optional[str] = None) -> bool:
    script = r"""
        return (() => {
            const selector = String(arguments[0] || '');
            const verifySelector = String(arguments[1] || '');
            if (!selector) return false;
            const node = document.querySelector(selector);
            if (!node) return false;
            try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
            try { node.click(); } catch (e) {}
            if (!verifySelector) return true;
            const verifyNode = document.querySelector(verifySelector);
            if (!verifyNode) return false;
            if ('checked' in verifyNode) return !!verifyNode.checked;
            return true;
        })();
    """
    try:
        return bool(await driver.execute_script(script, selector, verify_selector or ""))
    except Exception:
        return False


async def _click_visible_button_by_selectors(driver: BrowserDriver, selectors: Sequence[str]) -> bool:
    page = await _page(driver)
    for selector in selectors:
        if not str(selector or "").strip():
            continue
        try:
            locator = page.locator(selector).first
            if await locator.count() <= 0:
                continue
            await locator.scroll_into_view_if_needed(timeout=1800)
            try:
                await locator.click(timeout=1800)
                return True
            except Exception:
                try:
                    await locator.click(timeout=1800, force=True)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


async def _click_choice_input(driver: BrowserDriver, question_number: int, input_type: str, option_index: int) -> bool:
    if int(question_number or 0) <= 0 or int(option_index) < 0:
        return False
    q_num = int(question_number)
    idx = int(option_index)
    selectors = (
        f"#div{q_num} .ui-controlgroup > div:nth-child({idx + 1})",
        f"#div{q_num} input[type='{input_type}']:nth-of-type({idx + 1})",
        f"#div{q_num} .jq{input_type}:nth-of-type({idx + 1})",
        f"#div{q_num} ul[tp='d'] li:nth-child({idx + 1})",
        f"#div{q_num} ul[tp='d'] li:nth-child({idx + 1}) a",
        f"#div{q_num} .scale-rating ul li:nth-child({idx + 1})",
        f"#div{q_num} .scale-rating ul li:nth-child({idx + 1}) a",
    )
    verify_selector = f"#div{q_num} input[type='{input_type}']:nth-of-type({idx + 1})"
    page = await _page(driver)
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() <= 0:
                continue
            await locator.scroll_into_view_if_needed(timeout=1800)
            try:
                await locator.click(timeout=1800)
            except Exception:
                try:
                    await locator.click(timeout=1800, force=True)
                except Exception:
                    if not await _click_js(driver, selector, verify_selector=verify_selector):
                        continue
            checked = await driver.execute_script(
                """
                const node = document.querySelector(arguments[0]);
                if (node && 'checked' in node) return !!node.checked;
                const optionSelectors = arguments[1] || [];
                for (const selector of optionSelectors) {
                    const optionNode = document.querySelector(selector);
                    if (!optionNode) continue;
                    const className = String(optionNode.className || '').toLowerCase();
                    const ariaChecked = String(optionNode.getAttribute?.('aria-checked') || '').toLowerCase();
                    const dataChecked = String(optionNode.getAttribute?.('data-checked') || '').toLowerCase();
                    if (className.includes('checked') || className.includes('selected') || className.includes('on')) return true;
                    if (ariaChecked === 'true' || dataChecked === 'true') return true;
                }
                return false;
                """,
                verify_selector,
                list(selectors),
            )
            if checked:
                return True
        except Exception:
            continue
    return False


async def _set_select_value(
    driver: BrowserDriver,
    question_number: int,
    option_text: str,
    *,
    option_index: int = -1,
) -> bool:
    q_num = int(question_number or 0)
    if q_num <= 0:
        return False
    text = str(option_text or "").strip()
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const expectedText = String(arguments[1] || '').trim();
            const optionIndex = Number(arguments[2] || -1);
            const select = document.querySelector(`#q${questionNumber}, #div${questionNumber} select`);
            if (!select) return false;
            const options = Array.from(select.options || []);
            const isPlaceholder = (opt, idx) => {
                if (!opt) return true;
                const value = String(opt.value || '').trim();
                const text = String(opt.textContent || opt.innerText || '').replace(/\s+/g, ' ').trim();
                if (idx !== 0) return false;
                if (!text) return true;
                if (value === '' || value === '0' || value === '-1' || value === '-2') return true;
                const compact = text.replace(/\s+/g, '');
                return compact.startsWith('请选择') || compact.startsWith('请先选择');
            };
            const validOptions = options.filter((opt, idx) => !isPlaceholder(opt, idx));
            let target = null;
            if (optionIndex >= 0 && optionIndex < validOptions.length) {
                target = validOptions[optionIndex];
            }
            if (!target && expectedText) {
                target = validOptions.find((opt) => String(opt.textContent || opt.innerText || '').replace(/\s+/g, ' ').trim() === expectedText) || null;
            }
            if (!target) return false;
            target.selected = true;
            select.value = target.value;
            try { select.setAttribute('value', target.value); } catch (e) {}
            ['input', 'change', 'blur'].forEach((name) => {
                try { select.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
            });
            return String(select.value || '') === String(target.value || '');
        })();
    """
    try:
        return bool(await driver.execute_script(script, q_num, text, int(option_index)))
    except Exception:
        return False


async def _fill_text_input(
    driver: BrowserDriver,
    question_number: int,
    value: str,
    *,
    blank_index: int = 0,
) -> bool:
    q_num = int(question_number or 0)
    if q_num <= 0:
        return False
    selectors = (
        f"#div{q_num} input[id^='q{q_num}_']",
        f"#div{q_num} textarea[id^='q{q_num}_']",
        f"#div{q_num} input[type='text']",
        f"#div{q_num} textarea",
        f"#div{q_num} input",
        f"#q{q_num}",
    )
    text = str(value or "")
    gapfill_script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const value = String(arguments[1] || '');
            const blankIndex = Number(arguments[2] || 0);
            const root = document.querySelector(`#div${questionNumber}`);
            if (!root) return false;
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const dispatchEditableEvents = (target) => {
                ['beforeinput', 'input', 'change', 'blur'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
            };
            const setNativeValue = (target, nextValue) => {
                try {
                    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement?.prototype || {}, 'value');
                    if (descriptor && descriptor.set) descriptor.set.call(target, nextValue);
                    else target.value = nextValue;
                } catch (e) {
                    try { target.value = nextValue; } catch (err) {}
                }
            };
            const editableNodes = Array.from(root.querySelectorAll('.textEdit .textCont[contenteditable="true"], .textCont[contenteditable="true"], [contenteditable="true"]'))
                .filter((el) => visible(el) || visible(el.closest('.textEdit')));
            if (!editableNodes.length) return false;
            const hiddenInputs = Array.from(root.querySelectorAll('input[id^="q"], input[type="hidden"], input[type="text"]'))
                .filter((el) => {
                    const id = String(el.id || '');
                    const name = String(el.name || '');
                    return id.startsWith(`q${questionNumber}_`) || name.startsWith(`q${questionNumber}_`);
                });
            const index = Math.max(0, Math.min(blankIndex, editableNodes.length - 1));
            const editable = editableNodes[index];
            const hidden = hiddenInputs[index] || null;
            try { editable.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
            try { editable.focus(); } catch (e) {}
            try { editable.textContent = value; } catch (e) {}
            try { editable.innerText = value; } catch (e) {}
            dispatchEditableEvents(editable);
            const label = editable.closest('.textEdit');
            if (label) {
                try { label.classList.remove('initStyle'); } catch (e) {}
                try { label.setAttribute('value', value); } catch (e) {}
                dispatchEditableEvents(label);
            }
            if (hidden) {
                setNativeValue(hidden, value);
                dispatchEditableEvents(hidden);
            }
            return String((hidden && hidden.value) || editable.textContent || editable.innerText || '') === value;
        })();
    """
    try:
        if await driver.execute_script(gapfill_script, q_num, text, int(blank_index)):
            return True
    except Exception:
        pass
    page = await _page(driver)
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
        except Exception:
            continue
        if count <= 0:
            continue
        target_index = min(max(0, int(blank_index)), count - 1)
        target = locator.nth(target_index)
        try:
            await target.scroll_into_view_if_needed(timeout=1800)
            await target.fill(text, timeout=2500)
            return True
        except Exception:
            try:
                await target.click(timeout=1500)
                await target.fill("")
                await target.type(text, delay=20, timeout=2500)
                return True
            except Exception:
                continue
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const value = String(arguments[1] || '');
            const blankIndex = Number(arguments[2] || 0);
            const root = document.querySelector(`#div${questionNumber}`);
            if (!root) return false;
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
            const setNativeValue = (target, nextValue) => {
                try {
                    const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                    if (descriptor && descriptor.set) descriptor.set.call(target, nextValue);
                    else target.value = nextValue;
                } catch (e) {
                    try { target.value = nextValue; } catch (err) {}
                }
            };
            const dispatchEditableEvents = (target) => {
                ['beforeinput', 'input', 'change', 'blur'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
            };
            const hiddenInputs = Array.from(root.querySelectorAll('input[id^="q"], input[type="hidden"], input[type="text"]'))
                .filter((el) => {
                    if (!isTextInput(el)) return false;
                    const id = String(el.id || '');
                    const name = String(el.name || '');
                    return id.startsWith(`q${questionNumber}_`) || name.startsWith(`q${questionNumber}_`);
                });
            const editableNodes = Array.from(root.querySelectorAll('.textEdit .textCont[contenteditable="true"], .textCont[contenteditable="true"], [contenteditable="true"]'))
                .filter((el) => visible(el) || visible(el.closest('.textEdit')));
            if (editableNodes.length) {
                const index = Math.max(0, Math.min(blankIndex, editableNodes.length - 1));
                const editable = editableNodes[index];
                const hidden = hiddenInputs[index] || null;
                try { editable.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                try { editable.focus(); } catch (e) {}
                try { editable.textContent = value; } catch (e) {}
                try { editable.innerText = value; } catch (e) {}
                dispatchEditableEvents(editable);
                const label = editable.closest('.textEdit');
                if (label) {
                    try { label.classList.remove('initStyle'); } catch (e) {}
                    try { label.setAttribute('value', value); } catch (e) {}
                    dispatchEditableEvents(label);
                }
                if (hidden) {
                    setNativeValue(hidden, value);
                    dispatchEditableEvents(hidden);
                }
                return String((hidden && hidden.value) || editable.textContent || editable.innerText || '') === value;
            }
            const inputs = Array.from(root.querySelectorAll('input, textarea')).filter((el) => visible(el) && isTextInput(el));
            const target = inputs[Math.max(0, Math.min(blankIndex, inputs.length - 1))];
            if (!target) return false;
            try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
            try { target.focus(); } catch (e) {}
            setNativeValue(target, value);
            dispatchEditableEvents(target);
            return String(target.value || '') === value;
        })();
    """
    try:
        return bool(await driver.execute_script(script, q_num, text, int(blank_index)))
    except Exception:
        return False


async def _select_location_input(
    driver: BrowserDriver,
    question_number: int,
    location_parts: Optional[Sequence[str]] = None,
) -> str:
    q_num = int(question_number or 0)
    if q_num <= 0:
        return ""
    target_parts = [str(item or "").strip() for item in list(location_parts or [])[:3]]
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const targetParts = Array.isArray(arguments[1]) ? arguments[1].map((item) => String(item || '').trim()) : [];
            if (!questionNumber) return "";
            const root = document.querySelector(`#div${questionNumber}`);
            const input = document.querySelector(`#q${questionNumber}`);
            if (!root || !input) return "";
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const dispatch = (target, names = ['input', 'change', 'blur']) => {
                for (const name of names) {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                }
            };
            const setNativeValue = (target, nextValue) => {
                const value = String(nextValue || '');
                try {
                    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement?.prototype || {}, 'value');
                    if (descriptor && descriptor.set) descriptor.set.call(target, value);
                    else target.value = value;
                } catch (e) {
                    try { target.value = value; } catch (err) {}
                }
                try { target.setAttribute('value', value); } catch (e) {}
                dispatch(target);
            };
            const normalizeName = (value) => String(value || '')
                .replace(/\s+/g, '')
                .replace(/省|市|区|县|自治州|自治县|地区|盟/g, '');
            const optionMatches = (option, target) => {
                const expected = String(target || '').trim();
                if (!expected || expected === '自动选择') return false;
                const optionText = String(option.textContent || option.innerText || '').replace(/\s+/g, ' ').trim();
                const optionValue = String(option.value || '').trim();
                const textNorm = normalizeName(optionText);
                const expectedNorm = normalizeName(expected);
                if (!expectedNorm) return false;
                return optionText === expected
                    || optionValue === expected
                    || textNorm === expectedNorm
                    || textNorm.includes(expectedNorm)
                    || expectedNorm.includes(textNorm);
            };
            const chooseValid = (select, target) => {
                const expected = String(target || '').trim();
                const hasTarget = Boolean(expected) && expected !== '自动选择';
                if (!select) return hasTarget ? null : { value: "", text: "" };
                const options = Array.from(select.options || []);
                const validOptions = options.filter((item, index) => {
                    const value = String(item.value || '').trim();
                    const text = String(item.textContent || item.innerText || '').replace(/\s+/g, ' ').trim();
                    if (!value && index === 0) return false;
                    if (!text || text.startsWith('--请选择') || text.includes('请选择')) return false;
                    return Boolean(value || text);
                });
                if (!validOptions.length) return null;
                const option = hasTarget
                    ? (validOptions.find((item) => optionMatches(item, expected)) || null)
                    : validOptions[0];
                if (!option) return null;
                select.value = option.value;
                try { option.selected = true; } catch (e) {}
                dispatch(select);
                try {
                    if (window.jQuery) {
                        window.jQuery(select).val(option.value).trigger('change');
                    }
                } catch (e) {}
                return {
                    value: String(option.value || '').trim(),
                    text: String(option.textContent || option.innerText || option.value || '').replace(/\s+/g, ' ').trim(),
                };
            };
            const readSelectText = (select) => {
                if (!select) return "";
                const selected = select.options && select.selectedIndex >= 0 ? select.options[select.selectedIndex] : null;
                const text = String((selected && (selected.textContent || selected.innerText)) || select.value || '').replace(/\s+/g, ' ').trim();
                return text.includes('请选择') ? "" : text;
            };
            const waitForOptions = (select) => {
                if (!select) return Promise.resolve(false);
                return new Promise((resolve) => {
                    const hasValid = () => Array.from(select.options || []).some((option, index) => {
                        const text = String(option.textContent || option.innerText || '').replace(/\s+/g, ' ').trim();
                        const value = String(option.value || '').trim();
                        return index > 0 && !text.includes('请选择') && Boolean(value || text);
                    });
                    if (hasValid()) {
                        resolve(true);
                        return;
                    }
                    let settled = false;
                    const observer = new MutationObserver(() => {
                        if (!hasValid()) return;
                        if (settled) return;
                        settled = true;
                        try { observer.disconnect(); } catch (e) {}
                        resolve(true);
                    });
                    try { observer.observe(select, { childList: true, subtree: true }); } catch (e) {}
                    window.setTimeout(() => {
                        if (settled) return;
                        settled = true;
                        try { observer.disconnect(); } catch (e) {}
                        resolve(hasValid());
                    }, 1200);
                });
            };
            const waitForLayer = () => new Promise((resolve) => {
                const findLayer = () => {
                    const layers = Array.from(document.querySelectorAll('.layui-layer, #layui-layer1')).filter(visible);
                    return layers.find((layer) => layer.querySelector('select.province, select[name="province"]')) || null;
                };
                const existing = findLayer();
                if (existing) {
                    resolve(existing);
                    return;
                }
                let settled = false;
                const observer = new MutationObserver(() => {
                    const layer = findLayer();
                    if (!layer || settled) return;
                    settled = true;
                    try { observer.disconnect(); } catch (e) {}
                    resolve(layer);
                });
                try { observer.observe(document.body || document.documentElement, { childList: true, subtree: true }); } catch (e) {}
                window.setTimeout(() => {
                    if (settled) return;
                    settled = true;
                    try { observer.disconnect(); } catch (e) {}
                    resolve(findLayer());
                }, 1200);
            });
            return (async () => {
                try { input.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                try { input.click(); } catch (e) {}
                const layer = await waitForLayer();
                if (!layer) return "";
                const province = layer.querySelector('select.province, select[name="province"]');
                const city = layer.querySelector('select.city, select[name="city"]');
                const area = layer.querySelector('select.area, select[name="area"]');
                const provinceValue = chooseValid(province, targetParts[0]);
                if (!provinceValue) return "";
                if (city) await waitForOptions(city);
                const cityValue = chooseValid(city, targetParts[1]);
                if (!cityValue) return "";
                if (area) await waitForOptions(area);
                const areaValue = chooseValid(area, targetParts[2]);
                if (!areaValue) return "";
                const values = [
                    readSelectText(province) || provinceValue.text || provinceValue.value,
                    readSelectText(city) || cityValue.text || cityValue.value,
                    readSelectText(area) || areaValue.text || areaValue.value,
                ]
                    .map((item) => String(item || '').trim())
                    .filter(Boolean);
                const finalValue = values.join('-');
                if (finalValue) setNativeValue(input, finalValue);
                return String(input.value || finalValue || '').trim();
            })();
        })();
    """
    try:
        value = str(await driver.execute_script(script, q_num, target_parts) or "").strip()
        if value:
            try:
                if not await _confirm_location_picker(driver):
                    return ""
            except Exception:
                return ""
        return value
    except Exception:
        return ""


async def _confirm_location_picker(driver: BrowserDriver) -> bool:
    selectors = (
        ".layui-layer .button_a",
        ".layui-layer .layer_save_btn a",
        ".layui-layer .save_btn",
        "#layui-layer1 .layui-layer-btn a.layui-layer-btn0",
        ".layui-layer .layui-layer-btn a.layui-layer-btn0",
        "#layui-layer1 .layui-layer-btn a",
        ".layui-layer .layui-layer-btn a",
    )
    try:
        if await _click_visible_button_by_selectors(driver, selectors):
            return True
    except Exception:
        pass
    script = r"""
        return (() => {
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const textOf = (el) => String(el.textContent || el.innerText || '').replace(/\s+/g, ' ').trim();
            const layers = Array.from(document.querySelectorAll('#layui-layer1, .layui-layer')).filter(visible);
            for (const layer of layers) {
                const buttons = Array.from(layer.querySelectorAll('a, button, input[type="button"], input[type="submit"]')).filter(visible);
                const done = buttons.find((node) => {
                    const text = textOf(node);
                    const value = String(node.value || '').replace(/\s+/g, ' ').trim();
                    const className = String(node.className || '').toLowerCase();
                    return text === '完成'
                        || value === '完成'
                        || className.includes('layui-layer-btn0')
                        || className.includes('save')
                        || className.includes('confirm');
                });
                if (done) {
                    try { done.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { done.click(); return true; } catch (e) {}
                }
            }
            if (typeof window.countyok === 'function') {
                try { window.countyok(); return true; } catch (e) {}
            }
            return false;
        })();
    """
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


async def _fill_choice_option_additional_text(
    driver: BrowserDriver,
    question_number: int,
    option_index: int,
    value: Optional[str],
    *,
    input_type: str,
) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    q_num = int(question_number or 0)
    if q_num <= 0 or int(option_index) < 0:
        return False
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const optionIndex = Number(arguments[1] || 0);
            const value = String(arguments[2] || '');
            const inputType = String(arguments[3] || 'radio');
            const root = document.querySelector(`#div${questionNumber}`);
            if (!root) return false;
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
            const options = Array.from(root.querySelectorAll('.ui-controlgroup > div'));
            const optionRoot = options[optionIndex] || null;
            let target = optionRoot
                ? Array.from(optionRoot.querySelectorAll('input, textarea')).find((el) => visible(el) && isTextInput(el))
                : null;
            if (!target) {
                const choiceInputs = Array.from(root.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                const choice = choiceInputs[optionIndex] || null;
                const anchors = [optionRoot, choice].filter(Boolean);
                const textInputs = Array.from(root.querySelectorAll('input, textarea')).filter((el) => visible(el) && isTextInput(el));
                target = textInputs.find((el) => anchors.some((anchor) => {
                    try { return !!(anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING); } catch (e) { return false; }
                })) || null;
            }
            if (!target) return false;
            try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
            try { target.focus(); } catch (e) {}
            try {
                const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                if (descriptor && descriptor.set) descriptor.set.call(target, value);
                else target.value = value;
            } catch (e) {
                try { target.value = value; } catch (err) {}
            }
            ['input', 'change', 'blur'].forEach((name) => {
                try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
            });
            return String(target.value || '') === value;
        })();
    """
    try:
        return bool(await driver.execute_script(script, q_num, int(option_index), text, input_type))
    except Exception:
        return False


async def _set_slider_value(driver: BrowserDriver, question_number: int, target_value: float) -> bool:
    q_num = int(question_number or 0)
    if q_num <= 0:
        return False
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const targetValue = Number(arguments[1]);
            const input = document.querySelector(`#q${questionNumber}, #div${questionNumber} input.ui-slider-input, #div${questionNumber} input[type="range"]`);
            if (!input || Number.isNaN(targetValue)) return false;
            const minValue = Number(input.getAttribute('min') || 0);
            const maxValue = Number(input.getAttribute('max') || 100);
            const stepValue = Math.abs(Number(input.getAttribute('step') || 1)) || 1;
            let nextValue = targetValue;
            if (nextValue < minValue) nextValue = minValue;
            if (nextValue > maxValue) nextValue = maxValue;
            const stepCount = Math.round((nextValue - minValue) / stepValue);
            nextValue = minValue + stepCount * stepValue;
            if (Math.abs(nextValue - Math.round(nextValue)) < 1e-6) nextValue = Math.round(nextValue);
            const normalized = String(nextValue);
            try { input.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
            try {
                const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement?.prototype || {}, 'value');
                if (descriptor && descriptor.set) descriptor.set.call(input, normalized);
                else input.value = normalized;
            } catch (e) {
                try { input.value = normalized; } catch (err) {}
            }
            ['input', 'change', 'blur'].forEach((name) => {
                try { input.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
            });
            return String(input.value || '') === normalized;
        })();
    """
    try:
        return bool(await driver.execute_script(script, q_num, float(target_value)))
    except Exception:
        return False


async def _click_matrix_cell(driver: BrowserDriver, question_number: int, row_index: int, column_index: int) -> bool:
    q_num = int(question_number or 0)
    row = int(row_index)
    col = int(column_index)
    if q_num <= 0 or row < 0 or col < 0:
        return False
    script = r"""
        return (() => {
            const questionNumber = Number(arguments[0] || 0);
            const rowIndex = Number(arguments[1] || 0);
            const columnIndex = Number(arguments[2] || 0);
            const root = document.querySelector(`#div${questionNumber}`);
            if (!root) return false;
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const rowNodes = Array.from(root.querySelectorAll("tr")).filter((node) => {
                const id = String(node.getAttribute('id') || '');
                return /^drv\d+_\d+$/.test(id) && visible(node);
            });
            const targetRow = rowNodes[rowIndex];
            if (!targetRow) return false;
            const anchors = Array.from(targetRow.querySelectorAll("a[dval]")).filter(visible);
            const anchor = anchors[columnIndex];
            if (anchor) {
                const value = String(anchor.getAttribute('dval') || columnIndex + 1);
                try { anchor.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                try { anchor.click(); } catch (e) {}
                try { anchor.classList.add('rate-on'); } catch (e) {}
                const fid = String(targetRow.getAttribute('fid') || '');
                const hidden = fid ? document.getElementById(fid) : null;
                if (hidden) {
                    try { hidden.value = value; } catch (e) {}
                    ['input', 'change', 'click'].forEach((name) => {
                        try { hidden.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                    });
                }
                return !hidden || String(hidden.value || '') === value;
            }
            const inputs = Array.from(targetRow.querySelectorAll("input[type='radio'], input[type='checkbox']")).filter(visible);
            const target = inputs[columnIndex];
            if (!target) return false;
            const clickCandidates = [
                target,
                target.closest('label'),
                target.closest('td'),
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
        })();
    """
    try:
        return bool(await driver.execute_script(script, q_num, row, col))
    except Exception:
        return False


async def _resolve_current_page_number(driver: BrowserDriver) -> int:
    script = r"""
        return (() => {
            const active = document.querySelector('#divQuestion fieldset[style*="display: block"], #divQuestion fieldset:not([style*="display: none"])');
            if (!active) return 1;
            const fieldsets = Array.from(document.querySelectorAll('#divQuestion fieldset'));
            const index = fieldsets.indexOf(active);
            return index >= 0 ? index + 1 : 1;
        })();
    """
    try:
        value = await driver.execute_script(script)
    except Exception:
        value = 1
    try:
        return max(1, int(value or 1))
    except Exception:
        return 1


async def _wait_for_page_number_change(
    driver: BrowserDriver,
    previous_page_number: int,
    *,
    timeout_ms: int = 5000,
    poll_ms: int = 80,
) -> bool:
    page = await _page(driver)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, float(timeout_ms or 0) / 1000.0)
    while loop.time() < deadline:
        current_page_number = await _resolve_current_page_number(driver)
        if current_page_number != int(previous_page_number or 0):
            return True
        try:
            await page.wait_for_timeout(max(20, int(poll_ms or 0)))
        except Exception:
            await sleep_or_stop(None, max(0.02, float(poll_ms or 0) / 1000.0))
    return await _resolve_current_page_number(driver) != int(previous_page_number or 0)


async def _question_text(driver: BrowserDriver, question_number: int) -> str:
    script = r"""
        return (() => {
            const root = document.querySelector(`#div${Number(arguments[0] || 0)}`);
            if (!root) return '';
            return String(root.innerText || root.textContent || '').replace(/\s+/g, ' ').trim();
        })();
    """
    try:
        return str(await driver.execute_script(script, int(question_number or 0)) or "").strip()
    except Exception:
        return ""


async def _question_option_texts(driver: BrowserDriver, question_number: int) -> list[str]:
    script = r"""
        return (() => {
            const root = document.querySelector(`#div${Number(arguments[0] || 0)}`);
            if (!root) return [];
            const normalize = (text) => String(text || '').replace(/\s+/g, ' ').trim();
            const direct = Array.from(root.querySelectorAll('.ui-controlgroup > div')).map((node) => {
                const label = node.querySelector('.label, label');
                return normalize(label ? (label.innerText || label.textContent || '') : (node.innerText || node.textContent || ''));
            }).filter(Boolean);
            if (direct.length) return direct;
            const dropdown = Array.from(root.querySelectorAll('select option')).map((node) => normalize(node.textContent || node.innerText || '')).filter(Boolean);
            if (dropdown.length) return dropdown;
            const scale = Array.from(root.querySelectorAll("ul[tp='d'] li, .scale-rating ul li")).map((node) => normalize(node.innerText || node.textContent || '')).filter(Boolean);
            return scale;
        })();
    """
    try:
        payload = await driver.execute_script(script, int(question_number or 0)) or []
    except Exception:
        payload = []
    if not isinstance(payload, list):
        return []
    return [str(item or "").strip() for item in payload if str(item or "").strip()]


async def _visible_matrix_row_count(driver: BrowserDriver, question_number: int) -> int:
    script = r"""
        return (() => {
            const root = document.querySelector(`#div${Number(arguments[0] || 0)}`);
            if (!root) return 0;
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            return Array.from(root.querySelectorAll("tr")).filter((node) => {
                const id = String(node.getAttribute('id') || '');
                return /^drv\d+_\d+$/.test(id) && visible(node);
            }).length;
        })();
    """
    try:
        value = await driver.execute_script(script, int(question_number or 0))
    except Exception:
        value = 0
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


async def _visible_text_input_count(driver: BrowserDriver, question_number: int) -> int:
    script = r"""
        return (() => {
            const root = document.querySelector(`#div${Number(arguments[0] || 0)}`);
            if (!root) return 0;
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
            return Array.from(root.querySelectorAll('input, textarea')).filter((el) => visible(el) && isTextInput(el)).length;
        })();
    """
    try:
        value = await driver.execute_script(script, int(question_number or 0))
    except Exception:
        value = 0
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


async def _click_reorder_sequence(driver: BrowserDriver, question_number: int, ordered_indices: Sequence[int]) -> bool:
    q_num = int(question_number or 0)
    normalized = [int(item) for item in ordered_indices if int(item) >= 0]
    if q_num <= 0 or not normalized:
        return False

    script = r"""
        return (async () => {
            const questionNumber = Number(arguments[0] || 0);
            const orderedIndices = Array.isArray(arguments[1])
                ? arguments[1].map((item) => Number(item)).filter((item) => Number.isInteger(item) && item >= 0)
                : [];
            const root = document.querySelector(`#div${questionNumber}`);
            if (!root || !orderedIndices.length) return false;
            const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const optionItems = () => Array.from(root.querySelectorAll('li')).filter(visible);
            const isMarked = (item) => {
                const marker = item?.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index');
                const markerText = String((marker && (marker.textContent || marker.innerText)) || '').replace(/\s+/g, '').trim();
                const markerClass = String((marker && marker.className) || '').toLowerCase();
                const itemClass = String(item?.className || '').toLowerCase();
                const checked = String(item?.getAttribute('check') || '').trim();
                const input = item?.querySelector('input[type="checkbox"], input[type="radio"]');
                return Boolean(markerText)
                    || checked === '1'
                    || Boolean(input?.checked)
                    || markerClass.includes('sel')
                    || markerClass.includes('on')
                    || markerClass.includes('checked')
                    || itemClass.includes('checked');
            };
            const keepQuestionInView = () => {
                const rect = root.getBoundingClientRect();
                const targetTop = Math.max(70, Math.min(160, window.innerHeight * 0.22));
                if (rect.top < 50 || rect.top > window.innerHeight * 0.48) {
                    const nextTop = Math.max(0, window.scrollY + rect.top - targetTop);
                    try { window.scrollTo({ top: nextTop, left: window.scrollX, behavior: 'auto' }); } catch (e) {
                        try { window.scrollTo(window.scrollX, nextTop); } catch (err) {}
                    }
                }
            };
            const findItem = (optionIndex) => {
                const serialItem = root.querySelector(`li[serial="${optionIndex + 1}"]`);
                if (serialItem && visible(serialItem)) return serialItem;
                return optionItems()[optionIndex] || null;
            };
            const markedCount = () => optionItems().filter((item) => isMarked(item)).length;
            const clickItem = (item) => {
                const candidates = [
                    item?.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index'),
                    item?.querySelector('a, label, span, input:not([type="hidden"])'),
                    item,
                ].filter(Boolean);
                for (const node of candidates) {
                    try {
                        node.click();
                        return true;
                    } catch (e) {
                        try {
                            node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                            return true;
                        } catch (err) {}
                    }
                }
                return false;
            };
            const uniqueIndices = Array.from(new Set(orderedIndices));
            const expected = Math.min(uniqueIndices.length, optionItems().length);
            if (expected <= 0) return false;
            keepQuestionInView();
            await sleep(120);
            for (const optionIndex of uniqueIndices) {
                let item = findItem(optionIndex);
                if (!item) continue;
                if (isMarked(item)) continue;
                keepQuestionInView();
                await sleep(90);
                let ranked = false;
                for (let attempt = 0; attempt < 3; attempt += 1) {
                    item = findItem(optionIndex) || item;
                    if (!item || isMarked(item)) {
                        ranked = true;
                        break;
                    }
                    const before = markedCount();
                    clickItem(item);
                    await sleep(320);
                    item = findItem(optionIndex) || item;
                    const after = markedCount();
                    if ((item && isMarked(item)) || after > before) {
                        ranked = true;
                        break;
                    }
                    keepQuestionInView();
                    await sleep(120);
                }
                if (!ranked) return false;
            }
            await sleep(180);
            return markedCount() >= expected;
        })();
    """
    try:
        return bool(await driver.execute_script(script, q_num, normalized))
    except Exception:
        return False


async def _click_submit_button(driver: BrowserDriver, *, timeout_ms: int = 10000) -> bool:
    page = await _page(driver)
    selectors = (
        "#ctlNext",
        "#submit_button",
        "#SubmitBtnGroup .submitbtn",
        ".submitbtn.mainBgColor",
        "#SM_BTN_1",
        "#divSubmit",
        ".btn-submit",
        "button[type='submit']",
        "a.button.mainBgColor",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() <= 0:
                continue
            await locator.scroll_into_view_if_needed(timeout=1800)
            try:
                await locator.click(timeout=max(500, int(timeout_ms or 0)))
            except Exception:
                try:
                    await locator.click(timeout=max(500, int(timeout_ms or 0)), force=True)
                except Exception:
                    if not await _click_js(driver, selector):
                        continue
            return True
        except Exception:
            continue
    script = r"""
        return (() => {
            const clickVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return false;
                try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                try { el.click(); } catch (e) {}
                return true;
            };
            const submitLike = Array.from(document.querySelectorAll('div,a,button,input,span')).find((el) => {
                const text = String(el.innerText || el.textContent || el.value || '').replace(/\s+/g, '');
                return text === '提交' || text === '完成' || text === '交卷' || text === '确认提交' || text === '确认';
            });
            if (clickVisible(submitLike)) return true;
            if (typeof submit_button_click === 'function') {
                submit_button_click();
                return true;
            }
            return false;
        })();
    """
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


__all__ = [
    "_click_choice_input",
    "_click_matrix_cell",
    "_click_reorder_sequence",
    "_click_submit_button",
    "_collect_visible_question_snapshot",
    "_fill_choice_option_additional_text",
    "_fill_text_input",
    "_is_question_visible",
    "_page",
    "_prepare_question_interaction",
    "_question_option_texts",
    "_question_text",
    "_resolve_current_page_number",
    "_select_location_input",
    "_set_select_value",
    "_set_slider_value",
    "_visible_matrix_row_count",
    "_visible_text_input_count",
    "_wait_for_any_visible_questions",
    "_wait_for_page_number_change",
    "_wait_for_question_root",
]
