"""排序题处理"""
import random
import re
import time
from typing import Any, List, Optional, Tuple
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.network.browser import By, BrowserDriver
from wjx.core.questions.utils import extract_text_from_element, smooth_scroll_to_element
from wjx.core.questions.types.multiple import (
    detect_multiple_choice_limit_range,
    detect_multiple_choice_limit,
    _log_multi_limit_once,
    _safe_positive_int,
    _extract_multi_limit_range_from_text,
)


def _extract_reorder_required_from_text(text: Optional[str], total_options: Optional[int] = None) -> Optional[int]:
    """从文本提取排序题需要选择的数量"""


    if not text:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if total_options:
        all_keywords = ("全选", "全部选择", "请选择全部", "全部选项", "所有选项", "全部排序", "全都排序")
        if any(keyword in normalized for keyword in all_keywords):
            return total_options
        range_patterns = (
            re.compile(r"数字?\s*(\d+)\s*[-~—－到]\s*(\d+)\s*填"),
            re.compile(r"(\d+)\s*[-~—－到]\s*(\d+)\s*填入括号"),
        )
        for pattern in range_patterns:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second and max(first, second) == total_options:
                    return total_options
    patterns = (
        re.compile(r"(?:选|选择|勾选|挑选)[^0-9]{0,4}(\d+)\s*[项个条]"),
        re.compile(r"至少\s*(\d+)\s*[项个条]"),
    )
    for pattern in patterns:
        match = pattern.search(normalized)
        if match:
            return _safe_positive_int(match.group(1))
    return None


def detect_reorder_required_count(driver: BrowserDriver, question_number: int, total_options: Optional[int] = None) -> Optional[int]:
    """检测多选排序题需要勾选的数量"""
    limit = detect_multiple_choice_limit(driver, question_number)
    detected_required: Optional[int] = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except Exception:
        container = None
    if container is None:
        return None
    fragments: List[str] = []
    for selector in (".qtypetip", ".topichtml", ".field-label"):
        try:
            fragments.append(container.find_element(By.CSS_SELECTOR, selector).text)
        except Exception:
            continue
    try:
        fragments.append(container.text)
    except Exception as exc:
        log_suppressed_exception("detect_reorder_required_count: fragments.append(container.text)", exc, level=logging.ERROR)
    for fragment in fragments:
        required = _extract_reorder_required_from_text(fragment, total_options)
        if required:
            print(f"第{question_number}题检测到需要选择 {required} 项并排序。")
            detected_required = required
            break
    if detected_required is not None:
        return detected_required
    return limit


def reorder(driver: BrowserDriver, current: int) -> None:
    """排序题处理主函数"""
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except Exception:
        container = None
    
    items_xpath_candidates = [
        f"//*[@id='div{current}']//li[.//input[starts-with(@name,'q{current}')]]",
        f"//*[@id='div{current}']//ul/li",
        f"//*[@id='div{current}']//ol/li",
    ]
    items_xpath = items_xpath_candidates[-1]
    order_items: List[Any] = []
    for candidate_xpath in items_xpath_candidates:
        try:
            order_items = driver.find_elements(By.XPATH, candidate_xpath)
        except Exception:
            order_items = []
        if order_items:
            items_xpath = candidate_xpath
            break
    if not order_items:
        return
    if container:
        smooth_scroll_to_element(driver, container, "center")
    
    rank_mode = False
    if container:
        try:
            rank_mode = bool(container.find_elements(By.CSS_SELECTOR, ".sortnum, .sortnum-sel"))
        except Exception:
            rank_mode = False

    def _is_item_selected(item) -> bool:
        try:
            inputs = item.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']")
        except Exception:
            inputs = []
        for ipt in inputs:
            try:
                if ipt.is_selected():
                    return True
            except Exception:
                continue
        try:
            cls = (item.get_attribute("class") or "").lower()
            if any(token in cls for token in ("selected", "checked", "jqchecked", "active", "on", "check", "cur", "sel")):
                return True
            data_checked = (item.get_attribute("data-checked") or "").lower()
            aria_checked = (item.get_attribute("aria-checked") or "").lower()
            if data_checked in ("true", "checked") or aria_checked == "true":
                return True
        except Exception as exc:
            log_suppressed_exception("_is_item_selected: cls = (item.get_attribute(\"class\") or \"\").lower()", exc, level=logging.ERROR)
        try:
            badges = item.find_elements(
                By.CSS_SELECTOR, ".ui-icon-number, .order-number, .order-index, .num, .sortnum, .sortnum-sel"
            )
            for badge in badges:
                try:
                    text = extract_text_from_element(badge).strip()
                except Exception:
                    text = ""
                if text:
                    return True
        except Exception as exc:
            log_suppressed_exception("_is_item_selected: badges = item.find_elements( By.CSS_SELECTOR, \".ui-icon-number, .order-number...", exc, level=logging.ERROR)
        return False

    def _count_selected() -> int:
        try:
            if container is not None:
                count = len(
                    container.find_elements(
                        By.CSS_SELECTOR,
                        "input[type='checkbox']:checked, input[type='radio']:checked, li.jqchecked, li.selected, li.on, li.checked, li.check, .option.on, .option.selected",
                    )
                )
                if count > 0:
                    return count
                badges = container.find_elements(By.CSS_SELECTOR, ".sortnum, .sortnum-sel")
                badge_count = 0
                for badge in badges:
                    try:
                        text = extract_text_from_element(badge).strip()
                    except Exception:
                        text = ""
                    if text:
                        badge_count += 1
                if badge_count:
                    return badge_count
                candidates = container.find_elements(By.CSS_SELECTOR, "li[aria-checked='true'], li[data-checked='true']")
                if candidates:
                    return len(candidates)
                hidden_inputs = container.find_elements(By.CSS_SELECTOR, "input[type='hidden'][name^='q'][value]")
                forced_inputs = [h for h in hidden_inputs if (h.get_attribute("data-forced") or "") == "1"]
                if forced_inputs:
                    return len(forced_inputs)
                selected_hidden = 0
                for hidden in hidden_inputs:
                    try:
                        checked_attr = (hidden.get_attribute("checked") or "").lower()
                        data_checked = (hidden.get_attribute("data-checked") or "").lower()
                        aria_checked = (hidden.get_attribute("aria-checked") or "").lower()
                    except Exception:
                        checked_attr = data_checked = aria_checked = ""
                    if checked_attr in ("true", "checked") or data_checked in ("true", "checked") or aria_checked == "true":
                        selected_hidden += 1
                if selected_hidden:
                    return selected_hidden
        except Exception as exc:
            log_suppressed_exception("_count_selected: if container is not None: count = len( container.find_elements( By.CSS_SELECT...", exc, level=logging.ERROR)
        count = 0
        for item in order_items:
            if _is_item_selected(item):
                count += 1
        return count

    def _click_item(option_idx: int, item) -> bool:
        selector = (
            f"#div{current} ul > li:nth-child({option_idx + 1}), "
            f"#div{current} ol > li:nth-child({option_idx + 1})"
        )

        def _after_rank_click(changed: bool) -> None:
            if changed and rank_mode:
                time.sleep(0.28)

        def _playwright_click_selector(css_selector: str) -> bool:
            page = getattr(driver, "page", None)
            if not page:
                return False
            try:
                page.click(css_selector, timeout=1200)
                return True
            except Exception:
                return False

        def _native_click(target) -> None:
            try:
                if target is not None and hasattr(target, "click"):
                    target.click()
            except Exception as exc:
                log_suppressed_exception("_native_click: if target is not None and hasattr(target, \"click\"): target.click()", exc, level=logging.ERROR)

        def _safe_dom_click(target) -> None:
            driver.execute_script(
                r"""
                const el = arguments[0];
                if (!el) return;
                const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
                const vh = window.innerHeight || document.documentElement.clientHeight || 0;
                const inView = !!(rect && rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.bottom <= vh);
                const y = window.scrollY || document.documentElement.scrollTop || 0;
                try { if (!inView) el.scrollIntoView({block:'nearest', inline:'nearest'}); } catch(e) {}
                try { el.focus({preventScroll:true}); } catch(e) {}
                try { el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, composed:true})); } catch(e) {}
                try { el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, composed:true})); } catch(e) {}
                try { el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, composed:true})); } catch(e) {}
                try { el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, composed:true})); } catch(e) {}
                try { el.click(); } catch(e) {}
                try { if (inView) window.scrollTo(0, y); } catch(e) {}
                """,
                target,
            )

        def _mouse_click_center(target) -> bool:
            page = getattr(driver, "page", None)
            if not page:
                return False
            try:
                payload = driver.execute_script(
                    r"""
                    const el = arguments[0];
                    if (!el || !el.getBoundingClientRect) return null;
                    const rect = el.getBoundingClientRect();
                    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
                    const vh = window.innerHeight || document.documentElement.clientHeight || 0;
                    if (rect.bottom < 0 || rect.top > vh) {
                        try { el.scrollIntoView({block:'nearest', inline:'nearest'}); } catch(e) {}
                    }
                    const r2 = el.getBoundingClientRect();
                    return {x: r2.left + r2.width / 2, y: r2.top + r2.height / 2, w: r2.width, h: r2.height};
                    """,
                    target,
                )
            except Exception:
                payload = None
            if not isinstance(payload, dict):
                return False
            try:
                x = float(payload.get("x", 0))
                y = float(payload.get("y", 0))
            except Exception:
                return False
            if x <= 0 or y <= 0:
                return False
            try:
                page.mouse.click(x, y)
                return True
            except Exception:
                return False

        def _click_targets(base_item) -> List[Any]:
            targets: List[Any] = []
            if base_item:
                targets.append(base_item)
                for css in (
                    "input[type='checkbox']",
                    "input[type='radio']",
                    "input[type='hidden']",
                    "label",
                    "a",
                    ".option",
                    ".item",
                    ".ui-state-default",
                    ".ui-sortable-handle",
                    "span",
                    "div",
                ):
                    try:
                        found = base_item.find_elements(By.CSS_SELECTOR, css)
                    except Exception:
                        found = []
                    for el in found[:3]:
                        targets.append(el)
            return targets

        def _get_item_fresh() -> Any:
            try:
                items_now = driver.find_elements(By.XPATH, items_xpath)
            except Exception:
                items_now = []
            if 0 <= option_idx < len(items_now):
                return items_now[option_idx]
            try:
                return driver.find_element(By.CSS_SELECTOR, selector)
            except Exception:
                return item

        if _is_item_selected(item):
            return True

        count_before = _count_selected()
        if rank_mode:
            clicked = False
            for css in (
                f"#div{current} ul > li:nth-child({option_idx + 1})",
                f"#div{current} ol > li:nth-child({option_idx + 1})",
            ):
                if _playwright_click_selector(css):
                    clicked = True
                    break
            if clicked:
                deadline = time.time() + 0.55
                while time.time() < deadline:
                    try:
                        if _count_selected() > count_before:
                            _after_rank_click(True)
                            return True
                    except Exception as exc:
                        log_suppressed_exception("_click_item: if _count_selected() > count_before: _after_rank_click(True) return True", exc, level=logging.ERROR)
                    try:
                        fresh_check = _get_item_fresh()
                        if fresh_check and _is_item_selected(fresh_check):
                            _after_rank_click(True)
                            return True
                    except Exception as exc:
                        log_suppressed_exception("_click_item: fresh_check = _get_item_fresh()", exc, level=logging.ERROR)
                    time.sleep(0.05)
        for _ in range(6):
            base_item = _get_item_fresh()
            if base_item and _is_item_selected(base_item):
                return True

            for target in _click_targets(base_item):
                try:
                    _native_click(target)
                except Exception as exc:
                    log_suppressed_exception("_click_item: _native_click(target)", exc, level=logging.ERROR)

                deadline = time.time() + 0.45
                while time.time() < deadline:
                    try:
                        if _count_selected() > count_before:
                            _after_rank_click(True)
                            return True
                    except Exception as exc:
                        log_suppressed_exception("_click_item: if _count_selected() > count_before: _after_rank_click(True) return True", exc, level=logging.ERROR)
                    try:
                        fresh_check = _get_item_fresh()
                        if fresh_check and _is_item_selected(fresh_check):
                            _after_rank_click(True)
                            return True
                    except Exception as exc:
                        log_suppressed_exception("_click_item: fresh_check = _get_item_fresh()", exc, level=logging.ERROR)
                    time.sleep(0.05)

                try:
                    _safe_dom_click(target)
                except Exception as exc:
                    log_suppressed_exception("_click_item: _safe_dom_click(target)", exc, level=logging.ERROR)
                deadline = time.time() + 0.45
                while time.time() < deadline:
                    try:
                        if _count_selected() > count_before:
                            _after_rank_click(True)
                            return True
                    except Exception as exc:
                        log_suppressed_exception("_click_item: if _count_selected() > count_before: _after_rank_click(True) return True", exc, level=logging.ERROR)
                    try:
                        fresh_check = _get_item_fresh()
                        if fresh_check and _is_item_selected(fresh_check):
                            _after_rank_click(True)
                            return True
                    except Exception as exc:
                        log_suppressed_exception("_click_item: fresh_check = _get_item_fresh()", exc, level=logging.ERROR)
                    time.sleep(0.05)

                try:
                    if _mouse_click_center(target):
                        deadline = time.time() + 0.45
                        while time.time() < deadline:
                            try:
                                if _count_selected() > count_before:
                                    _after_rank_click(True)
                                    return True
                            except Exception as exc:
                                log_suppressed_exception("_click_item: if _count_selected() > count_before: _after_rank_click(True) return True", exc, level=logging.ERROR)
                            time.sleep(0.05)
                except Exception as exc:
                    log_suppressed_exception("_click_item: if _mouse_click_center(target): deadline = time.time() + 0.45 while time.time...", exc, level=logging.ERROR)

            time.sleep(0.06)

        try:
            return _is_item_selected(_get_item_fresh())
        except Exception:
            return False

    def _ensure_reorder_complete(target_count: int) -> None:
        target_count = max(1, min(target_count, total_options))
        for _ in range(3):
            current_count = _count_selected()
            if current_count >= target_count:
                return
            missing_indices = [i for i, it in enumerate(order_items) if not _is_item_selected(it)]
            if not missing_indices:
                break
            random.shuffle(missing_indices)
            for option_idx in missing_indices:
                item = order_items[option_idx]
                if _click_item(option_idx, item):
                    current_count += 1
                    if current_count >= target_count:
                        return
            time.sleep(0.12)

    def _wait_until_reorder_done(target_count: int, max_wait: Optional[float] = None) -> None:
        target_count = max(1, min(target_count, total_options))
        wait_window = max_wait
        if wait_window is None:
            wait_window = 2.8 if rank_mode else 1.5
        deadline = time.time() + wait_window
        while time.time() < deadline:
            current_count = _count_selected()
            if current_count >= target_count:
                return
            _ensure_reorder_complete(target_count)
            time.sleep(0.08)

    total_options = len(order_items)
    required_count = detect_reorder_required_count(driver, current, total_options)
    min_select_limit, max_select_limit = detect_multiple_choice_limit_range(driver, current)
    
    if rank_mode and container:
        fragments: List[str] = []
        for selector in (".qtypetip", ".topichtml", ".field-label"):
            try:
                fragments.append(container.find_element(By.CSS_SELECTOR, selector).text)
            except Exception:
                continue
        cand_min, cand_max = _extract_multi_limit_range_from_text("\n".join(fragments))
        if cand_min is None and cand_max is None:
            min_select_limit = None
            max_select_limit = None
        else:
            min_select_limit = cand_min
            max_select_limit = cand_max
    force_select_all = required_count is not None and required_count == total_options
    if force_select_all and max_select_limit is not None and required_count is not None and max_select_limit < required_count:
        max_select_limit = required_count
    if min_select_limit is not None or max_select_limit is not None:
        _log_multi_limit_once(driver, current, min_select_limit, max_select_limit)
    if force_select_all:
        candidate_indices = list(range(len(order_items)))
        random.shuffle(candidate_indices)
        for option_idx in candidate_indices:
            item = order_items[option_idx]
            if _is_item_selected(item):
                continue
            _click_item(option_idx, item)
        for _ in range(2):
            selected_now = _count_selected()
            if selected_now >= total_options:
                break
            missing_indices = [i for i, it in enumerate(order_items) if not _is_item_selected(it)]
            random.shuffle(missing_indices)
            for option_idx in missing_indices:
                item = order_items[option_idx]
                _click_item(option_idx, item)
        _wait_until_reorder_done(total_options)
        return
    
    if required_count is None:
        effective_limit = max_select_limit if max_select_limit is not None else len(order_items)
    else:
        effective_limit = required_count
        if max_select_limit is not None:
            effective_limit = min(effective_limit, max_select_limit)
    if min_select_limit is not None:
        effective_limit = max(effective_limit, min_select_limit)
    effective_limit = max(1, min(effective_limit, len(order_items)))

    if rank_mode:
        plan_count = effective_limit
        if required_count is None and min_select_limit is None and max_select_limit is None:
            plan_count = total_options
        plan_count = max(1, min(int(plan_count), total_options))

        click_plan = list(range(total_options))
        random.shuffle(click_plan)
        click_plan = click_plan[:plan_count]

        def _force_mark_rank_selected(li, rank: int) -> None:
            if not li or not container:
                return
            try:
                driver.execute_script(
                    r"""
                    const li = arguments[0];
                    const rank = Number(arguments[1] || 0);
                    if (!li || !rank) return;
                    li.classList.add('check', 'selected', 'jqchecked', 'on');
                    li.setAttribute('aria-checked', 'true');
                    li.setAttribute('data-checked', 'true');
                    const badge = li.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index');
                    if (badge) {
                        badge.textContent = String(rank);
                        badge.style.display = '';
                    }
                    const hidden = li.querySelector("input.custom[type='hidden'][name^='q'], input[type='hidden'][name^='q']");
                    if (hidden) {
                        hidden.setAttribute('data-forced', '1');
                        hidden.setAttribute('data-checked', 'true');
                        hidden.setAttribute('aria-checked', 'true');
                    }
                    """,
                    li,
                    int(rank),
                )
            except Exception as exc:
                log_suppressed_exception("_force_mark_rank_selected: driver.execute_script( r\"\"\" const li = arguments[0]; const rank = Number(argu...", exc, level=logging.ERROR)

        def _get_item_badge_text(li) -> str:
            if not li:
                return ""
            try:
                badge = li.find_element(By.CSS_SELECTOR, ".sortnum, .sortnum-sel, .order-number, .order-index")
            except Exception:
                badge = None
            if not badge:
                return ""
            try:
                return extract_text_from_element(badge).strip()
            except Exception:
                return ""

        selected_count = _count_selected()
        for option_idx in click_plan:
            item = order_items[option_idx]
            if _is_item_selected(item):
                continue
            before = _count_selected()
            expected_rank = max(1, min(before + 1, plan_count))
            try:
                item.click()
            except Exception as exc:
                log_suppressed_exception("reorder: item.click()", exc, level=logging.ERROR)

            deadline = time.time() + 0.65
            while time.time() < deadline:
                try:
                    if _get_item_badge_text(item):
                        break
                except Exception as exc:
                    log_suppressed_exception("reorder: if _get_item_badge_text(item): break", exc, level=logging.ERROR)
                try:
                    if _count_selected() > before:
                        break
                except Exception as exc:
                    log_suppressed_exception("reorder: if _count_selected() > before: break", exc, level=logging.ERROR)
                time.sleep(0.05)

            selected_count = _count_selected()
            if selected_count <= before:
                _force_mark_rank_selected(item, expected_rank)
                selected_count = _count_selected()
            if selected_count >= plan_count:
                break

        deadline = time.time() + 1.2
        while time.time() < deadline:
            current_count = _count_selected()
            if current_count >= plan_count:
                break
            time.sleep(0.05)
        return

    candidate_indices = list(range(len(order_items)))
    random.shuffle(candidate_indices)
    selected_indices = candidate_indices[:effective_limit]

    for option_idx in selected_indices:
        item = order_items[option_idx]
        if _is_item_selected(item):
            continue
        _click_item(option_idx, item)

    selected_count = _count_selected()
    if selected_count < effective_limit:
        for option_idx, item in enumerate(order_items):
            if selected_count >= effective_limit:
                break
            if _is_item_selected(item):
                continue
            if _click_item(option_idx, item):
                selected_count += 1
    selected_count = _count_selected()
    if selected_count < effective_limit and container:
        try:
            order = list(range(len(order_items)))
            random.shuffle(order)
            driver.execute_script(
                r"""
                const container = arguments[0];
                const order = arguments[1];
                const limit = arguments[2];
                if (!container || !Array.isArray(order)) return;
                const items = Array.from(container.querySelectorAll('ul > li, ol > li'));
                const maxCount = Math.max(1, Math.min(Number(limit || items.length) || items.length, items.length));
                const chosen = order.slice(0, maxCount);
                const chosenSet = new Set(chosen);

                chosen.forEach((idx, pos) => {
                    const li = items[idx];
                    if (!li) return;
                    const rank = pos + 1;
                    li.classList.add('selected', 'jqchecked', 'on', 'check');
                    li.setAttribute('aria-checked', 'true');
                    li.setAttribute('data-checked', 'true');
                    const badge = li.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index');
                    if (badge) {
                        badge.textContent = String(rank);
                        badge.style.display = '';
                    }
                    const hidden = li.querySelector("input.custom[type='hidden'][name^='q'], input[type='hidden'][name^='q']");
                    if (hidden) {
                        hidden.value = String(rank);
                        hidden.setAttribute('data-forced', '1');
                        hidden.setAttribute('data-checked', 'true');
                        hidden.setAttribute('aria-checked', 'true');
                    }
                    const box = li.querySelector("input[type='checkbox'], input[type='radio']");
                    if (box) {
                        box.checked = true;
                        box.value = String(rank);
                        box.setAttribute('checked', 'checked');
                        box.setAttribute('data-checked', 'true');
                        box.setAttribute('aria-checked', 'true');
                        try { box.dispatchEvent(new Event('change', {bubbles:true})); } catch (err) {}
                    }
                });

                items.forEach((li, idx) => {
                    if (chosenSet.has(idx)) return;
                    li.classList.remove('selected', 'jqchecked', 'on', 'check');
                    li.removeAttribute('aria-checked');
                    li.removeAttribute('data-checked');
                    const badge = li.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index');
                    if (badge) badge.textContent = '';
                    const hidden = li.querySelector("input.custom[type='hidden'][name^='q'], input[type='hidden'][name^='q']");
                    if (hidden) {
                        hidden.value = '';
                        hidden.removeAttribute('data-forced');
                        hidden.removeAttribute('data-checked');
                        hidden.removeAttribute('aria-checked');
                    }
                    const box = li.querySelector("input[type='checkbox'], input[type='radio']");
                    if (box) {
                        box.checked = false;
                        box.removeAttribute('checked');
                        box.removeAttribute('data-checked');
                        box.removeAttribute('aria-checked');
                    }
                });
                """,
                container,
                order,
                effective_limit,
            )
        except Exception as exc:
            log_suppressed_exception("reorder: order = list(range(len(order_items)))", exc, level=logging.ERROR)
    _wait_until_reorder_done(effective_limit)

