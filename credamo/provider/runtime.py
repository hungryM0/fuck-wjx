"""Credamo 见数问卷运行时作答实现。"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from typing import Any, List, Optional, Tuple

from software.app.config import DEFAULT_FILL_TEXT
from software.core.modes.duration_control import simulate_answer_duration_delay
from software.core.questions.utils import (
    get_fill_text_from_config,
    normalize_droplist_probs,
    weighted_index,
)
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver


_CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS = 20000
_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS = 0.5
_CREDAMO_PAGE_TRANSITION_TIMEOUT_MS = 12000
_CREDAMO_DYNAMIC_REVEAL_TIMEOUT_MS = 2000
_QUESTION_NUMBER_RE = re.compile(r"\d+")
_NEXT_BUTTON_MARKERS = ("下一页", "next", "继续")
_SUBMIT_BUTTON_MARKERS = ("提交", "完成", "交卷", "submit", "finish", "done")


def _page(driver: BrowserDriver) -> Any:
    return getattr(driver, "page")


def _abort_requested(stop_signal: Optional[threading.Event]) -> bool:
    return bool(stop_signal and stop_signal.is_set())


def _question_roots(page: Any) -> List[Any]:
    script = r"""
() => {
  const visible = (el, minWidth = 8, minHeight = 8) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  const roots = [];
  Array.from(document.querySelectorAll('.answer-page .question')).forEach((root) => {
    if (!visible(root)) return;
    roots.push(root);
  });
  return roots;
}
"""
    roots = page.evaluate_handle(script)
    try:
        properties = roots.get_properties()
        return [prop.as_element() for prop in properties.values() if prop.as_element() is not None]
    finally:
        try:
            roots.dispose()
        except Exception:
            pass


def _wait_for_question_roots(
    page: Any,
    stop_signal: Optional[threading.Event],
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
) -> List[Any]:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    last_roots: List[Any] = []
    while not _abort_requested(stop_signal):
        try:
            last_roots = _question_roots(page)
        except Exception:
            logging.info("Credamo 等待题目加载时读取页面失败", exc_info=True)
            last_roots = []
        if last_roots:
            return last_roots
        if time.monotonic() >= deadline:
            return last_roots
        if stop_signal is not None:
            stop_signal.wait(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
        else:
            time.sleep(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return last_roots


def _root_text(page: Any, root: Any) -> str:
    try:
        return str(page.evaluate("el => (el.innerText || '').replace(/\\s+/g, ' ').trim()", root) or "")
    except Exception:
        return ""


def _question_number_from_root(page: Any, root: Any, fallback_num: int) -> int:
    try:
        raw = str(page.evaluate("el => (el.querySelector('.question-title .qstNo')?.textContent || '')", root) or "")
    except Exception:
        raw = ""
    match = _QUESTION_NUMBER_RE.search(raw)
    if match:
        try:
            return max(1, int(match.group(0)))
        except Exception:
            pass
    return max(1, int(fallback_num or 1))


def _question_kind_from_root(page: Any, root: Any) -> str:
    script = r"""
(el) => {
  const visible = (node, minWidth = 4, minHeight = 4) => {
    if (!node) return false;
    const style = window.getComputedStyle(node);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = node.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  const editableInputs = Array.from(
    el.querySelectorAll(
      'textarea, input:not([readonly])[type="text"], input:not([readonly])[type="search"], input:not([readonly])[type="number"], input:not([readonly])[type="tel"], input:not([readonly])[type="email"], input:not([readonly]):not([type])'
    )
  ).filter((node) => visible(node));
  if (el.querySelector('.multi-choice, input[type="checkbox"], [role="checkbox"]')) return 'multiple';
  if (el.querySelector('.pc-dropdown, .el-select')) return 'dropdown';
  if (el.querySelector('.scale, .nps-item, .el-rate__item')) return 'scale';
  if (el.querySelector('.rank-order')) return 'order';
  if (editableInputs.length > 1) return 'multi_text';
  if (editableInputs.length > 0) return 'text';
  if (el.querySelector('.single-choice, input[type="radio"], [role="radio"]')) return 'single';
  return '';
}
"""
    try:
        return str(page.evaluate(script, root) or "").strip().lower()
    except Exception:
        return ""


def _question_signature(page: Any) -> Tuple[Tuple[str, str], ...]:
    signature: List[Tuple[str, str]] = []
    for root in _question_roots(page):
        try:
            question_id = str(root.get_attribute("id") or root.get_attribute("data-id") or "")
        except Exception:
            question_id = ""
        signature.append((question_id, _root_text(page, root)))
    return tuple(signature)


def _runtime_question_key(page: Any, root: Any, question_num: int) -> str:
    try:
        question_id = str(root.get_attribute("id") or root.get_attribute("data-id") or "").strip()
    except Exception:
        question_id = ""
    if question_id:
        return f"id:{question_id}"
    return f"num:{question_num}|text:{_root_text(page, root)[:120]}"


def _unanswered_question_roots(
    page: Any,
    roots: List[Any],
    answered_keys: set[str],
    *,
    fallback_start: int = 0,
) -> List[Tuple[Any, int, str]]:
    pending: List[Tuple[Any, int, str]] = []
    for local_index, root in enumerate(roots, start=1):
        question_num = _question_number_from_root(page, root, fallback_start + local_index)
        key = _runtime_question_key(page, root, question_num)
        if key in answered_keys:
            continue
        pending.append((root, question_num, key))
    return pending


def _wait_for_dynamic_question_roots(
    page: Any,
    answered_keys: set[str],
    stop_signal: Optional[threading.Event],
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_REVEAL_TIMEOUT_MS,
    fallback_start: int = 0,
) -> List[Any]:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    latest_roots: List[Any] = []
    while not _abort_requested(stop_signal):
        try:
            latest_roots = _question_roots(page)
        except Exception:
            logging.info("Credamo 等待动态题目显示时读取页面失败", exc_info=True)
            latest_roots = []
        if _unanswered_question_roots(page, latest_roots, answered_keys, fallback_start=fallback_start):
            return latest_roots
        if time.monotonic() >= deadline:
            return latest_roots
        if stop_signal is not None:
            stop_signal.wait(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
        else:
            time.sleep(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return latest_roots


def _click_element(page: Any, element: Any) -> bool:
    try:
        element.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        element.click(timeout=3000)
        return True
    except Exception:
        pass
    try:
        return bool(page.evaluate("el => { el.click(); return true; }", element))
    except Exception:
        return False


def _is_checked(page: Any, element: Any) -> bool:
    try:
        return bool(page.evaluate("el => !!el.checked", element))
    except Exception:
        return False


def _input_value(page: Any, element: Any) -> str:
    try:
        return str(page.evaluate("el => String(el.value || '')", element) or "")
    except Exception:
        return ""


def _option_inputs(root: Any, kind: str) -> List[Any]:
    selector = f"input[type='{kind}'], [role='{kind}']"
    try:
        return root.query_selector_all(selector)
    except Exception:
        return []


def _option_click_targets(root: Any, kind: str) -> List[Any]:
    selectors = {
        "radio": ".single-choice .choice-row, .single-choice .choice, .choice-row, .choice",
        "checkbox": ".multi-choice .choice-row, .multi-choice .choice, .choice-row, .choice",
    }
    selector = selectors.get(kind, "")
    if not selector:
        return []
    try:
        return root.query_selector_all(selector)
    except Exception:
        return []


def _text_inputs(root: Any) -> List[Any]:
    try:
        return root.query_selector_all(
            "textarea, input:not([readonly])[type='text'], input:not([readonly])[type='search'], "
            "input:not([readonly])[type='number'], input:not([readonly])[type='tel'], "
            "input:not([readonly])[type='email'], input:not([readonly]):not([type])"
        )
    except Exception:
        return []


def _normalize_runtime_text(value: Any) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text)


def _element_text(page: Any, element: Any) -> str:
    for reader in (
        lambda: element.inner_text(timeout=500),
        lambda: element.text_content(timeout=500),
        lambda: element.get_attribute("value"),
        lambda: page.evaluate("el => (el.innerText || el.textContent || el.value || '').trim()", element),
    ):
        try:
            text = _normalize_runtime_text(reader())
        except Exception:
            text = ""
        if text:
            return text
    return ""


def _question_title_text(page: Any, root: Any) -> str:
    for selector in (".question-title", ".qstTitle", ".title", "[class*='title']"):
        try:
            title_node = root.query_selector(selector)
        except Exception:
            title_node = None
        if title_node is None:
            continue
        text = _element_text(page, title_node)
        if text:
            return text
    return _root_text(page, root)


def _resolve_forced_choice_index(page: Any, root: Any, option_texts: List[str]) -> Optional[int]:
    if not option_texts:
        return None
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None

    title_text = _question_title_text(page, root)
    extra_fragments = [_root_text(page, root)]
    forced_index, _forced_text = credamo_parser._extract_force_select_option(
        title_text,
        option_texts,
        extra_fragments=extra_fragments,
    )
    if forced_index is None:
        forced_index, _forced_text = credamo_parser._extract_arithmetic_option(
            title_text,
            option_texts,
            extra_fragments=extra_fragments,
        )
    if forced_index is None or forced_index < 0:
        return None
    if forced_index >= len(option_texts):
        return None
    return forced_index


def _click_single_choice_at_index(page: Any, root: Any, target_index: int, inputs: List[Any], targets: List[Any]) -> bool:
    if target_index < 0:
        return False
    if inputs and target_index < len(inputs):
        target = inputs[target_index]
        if _click_element(page, target) and _is_checked(page, target):
            return True
    if targets and target_index < len(targets):
        target = targets[target_index]
        if _click_element(page, target):
            refreshed_inputs = _option_inputs(root, "radio")
            if target_index < len(refreshed_inputs) and _is_checked(page, refreshed_inputs[target_index]):
                return True
            if not refreshed_inputs:
                return True
    if inputs and target_index < len(inputs):
        target = inputs[target_index]
        try:
            if bool(page.evaluate("el => { el.click(); return !!el.checked; }", target)):
                return True
        except Exception:
            pass
    return False


def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    inputs = _option_inputs(root, "radio")
    targets = _option_click_targets(root, "radio")
    target_count = len(inputs) if inputs else len(targets)
    if target_count <= 0:
        return False
    forced_source = targets if targets else inputs
    forced_option_texts = [_element_text(page, item) for item in forced_source]
    forced_index = _resolve_forced_choice_index(page, root, forced_option_texts)
    if forced_index is not None and _click_single_choice_at_index(page, root, forced_index, inputs, targets):
        return True
    probabilities = normalize_droplist_probs(weights, target_count)
    target_index = weighted_index(probabilities)
    return _click_single_choice_at_index(page, root, min(target_index, target_count - 1), inputs, targets)


def _positive_multiple_indexes(weights: Any, option_count: int) -> List[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []
    if not isinstance(weights, list) or not weights:
        return [random.randrange(count)]
    normalized: List[float] = []
    for idx in range(count):
        raw = weights[idx] if idx < len(weights) else 0.0
        try:
            normalized.append(max(0.0, float(raw)))
        except Exception:
            normalized.append(0.0)
    selected = [idx for idx, weight in enumerate(normalized) if weight > 0 and random.uniform(0, 100) <= weight]
    if not selected:
        positive = [idx for idx, weight in enumerate(normalized) if weight > 0]
        selected = [random.choice(positive)] if positive else [random.randrange(count)]
    return selected


def _answer_multiple(page: Any, root: Any, weights: Any) -> bool:
    inputs = _option_inputs(root, "checkbox")
    targets = _option_click_targets(root, "checkbox")
    total = len(inputs) if inputs else len(targets)
    if total <= 0:
        return False
    clicked = False
    for index in _positive_multiple_indexes(weights, total):
        if index < len(inputs):
            clicked_now = _click_element(page, inputs[index]) and _is_checked(page, inputs[index])
            if not clicked_now:
                try:
                    clicked_now = bool(page.evaluate("el => { el.click(); return !!el.checked; }", inputs[index]))
                except Exception:
                    clicked_now = False
            clicked = clicked_now or clicked
            continue
        if targets and index < len(targets):
            if _click_element(page, targets[index]):
                refreshed_inputs = _option_inputs(root, "checkbox")
                if index < len(refreshed_inputs) and _is_checked(page, refreshed_inputs[index]):
                    clicked = True
    return clicked


def _answer_text(root: Any, text_config: Any) -> bool:
    inputs = _text_inputs(root)
    if not inputs:
        return False
    values = text_config if isinstance(text_config, list) and text_config else [DEFAULT_FILL_TEXT]
    changed = False
    for index, input_element in enumerate(inputs):
        value = get_fill_text_from_config(values, index) or DEFAULT_FILL_TEXT
        try:
            input_element.fill(str(value), timeout=3000)
            changed = True
        except Exception:
            try:
                input_element.type(str(value), timeout=3000)
                changed = True
            except Exception:
                logging.info("Credamo 填空输入失败", exc_info=True)
    return changed


def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    trigger = None
    for selector in (".pc-dropdown .el-input", ".pc-dropdown .el-select", ".el-input", ".el-select", ".el-input__inner"):
        try:
            trigger = root.query_selector(selector)
        except Exception:
            trigger = None
        if trigger is not None:
            break
    try:
        value_input = root.query_selector(".el-input__inner")
    except Exception:
        value_input = None
    if trigger is None or value_input is None:
        return False
    previous_value = _input_value(page, value_input)
    try:
        trigger.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    if not _click_element(page, trigger):
        return False
    try:
        page.wait_for_timeout(120)
    except Exception:
        time.sleep(0.12)
    options = page.locator(".el-select-dropdown__item")
    try:
        option_count = int(options.count())
    except Exception:
        option_count = 0
    if option_count <= 0:
        try:
            option_count = max(1, len(root.query_selector_all(".el-select-dropdown__item, option")))
        except Exception:
            option_count = 1
    probabilities = normalize_droplist_probs(weights, option_count)
    target_index = min(weighted_index(probabilities), option_count - 1)

    def visible_dropdown_options() -> List[Any]:
        script = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 4 && rect.height >= 4;
  };
        return Array.from(document.querySelectorAll('.el-select-dropdown__item')).filter(visible);
}
"""
        try:
            handle = page.evaluate_handle(script)
        except Exception:
            return []
        try:
            properties = handle.get_properties()
            return [prop.as_element() for prop in properties.values() if prop.as_element() is not None]
        finally:
            try:
                handle.dispose()
            except Exception:
                pass

    visible_options = visible_dropdown_options()
    if visible_options:
        forced_option_texts = [_element_text(page, item) for item in visible_options]
        forced_index = _resolve_forced_choice_index(page, root, forced_option_texts)
        if forced_index is not None and forced_index < len(visible_options):
            target = visible_options[forced_index]
            if _click_element(page, target):
                try:
                    page.wait_for_timeout(120)
                except Exception:
                    time.sleep(0.12)
                current_value = _input_value(page, value_input)
                if current_value and current_value != previous_value:
                    return True
        target = visible_options[min(target_index, len(visible_options) - 1)]
        if _click_element(page, target):
            try:
                page.wait_for_timeout(120)
            except Exception:
                time.sleep(0.12)
            current_value = _input_value(page, value_input)
            if current_value and current_value != previous_value:
                return True

    try:
        value_input.focus()
    except Exception:
        pass
    try:
        for _ in range(target_index + 1):
            page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        try:
            page.wait_for_timeout(120)
        except Exception:
            time.sleep(0.12)
        current_value = _input_value(page, value_input)
        if current_value and current_value != previous_value:
            return True
    except Exception:
        pass
    target = options.nth(target_index)
    try:
        target.click(timeout=3000, force=True)
    except Exception:
        try:
            handle = target.element_handle(timeout=1000)
            if handle is None:
                return False
            page.evaluate("el => { el.click(); return true; }", handle)
        except Exception:
            return False
    current_value = _input_value(page, value_input)
    return bool(current_value and current_value != previous_value)


def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    try:
        options = root.query_selector_all(".scale .nps-item, .nps-item, .el-rate__item")
    except Exception:
        options = []
    if not options:
        return False
    probabilities = normalize_droplist_probs(weights, len(options))
    target_index = min(weighted_index(probabilities), len(options) - 1)
    return _click_element(page, options[target_index])


def _answer_order(page: Any, root: Any) -> bool:
    try:
        items = root.query_selector_all(".rank-order .choice-row, .choice-row")
    except Exception:
        items = []
    if not items:
        return False
    order = list(range(len(items)))
    random.shuffle(order)
    clicked = False
    for index in order:
        clicked = _click_element(page, items[index]) or clicked
        time.sleep(random.uniform(0.05, 0.12))
    return clicked


def _locator_is_visible(locator: Any) -> bool:
    try:
        return bool(locator.is_visible(timeout=300))
    except Exception:
        return False


def _navigation_action(page: Any) -> Optional[str]:
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    try:
        count = int(locator.count())
    except Exception:
        count = 0
    found_next = False
    for index in range(count):
        item = locator.nth(index)
        if not _locator_is_visible(item):
            continue
        try:
            text = str(item.text_content(timeout=500) or "").strip()
        except Exception:
            text = ""
        if not text:
            try:
                text = str(item.get_attribute("value") or "").strip()
            except Exception:
                text = ""
        lowered = text.casefold()
        if any(marker in lowered for marker in _SUBMIT_BUTTON_MARKERS):
            return "submit"
        if any(marker in lowered for marker in _NEXT_BUTTON_MARKERS):
            found_next = True
    return "next" if found_next else None


def _click_navigation(page: Any, action: str) -> bool:
    primary_button = page.locator("#credamo-submit-btn").first
    try:
        primary_count = int(primary_button.count())
    except Exception:
        primary_count = 0
    if primary_count > 0 and _locator_is_visible(primary_button):
        try:
            primary_text = str(primary_button.text_content(timeout=500) or "").strip()
        except Exception:
            primary_text = ""
        if not primary_text:
            try:
                primary_text = str(primary_button.get_attribute("value") or "").strip()
            except Exception:
                primary_text = ""
        lowered_primary = primary_text.casefold()
        targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
        if any(marker in lowered_primary for marker in targets):
            try:
                primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass

    targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    try:
        count = int(locator.count())
    except Exception:
        count = 0
    for index in range(count):
        item = locator.nth(index)
        if not _locator_is_visible(item):
            continue
        try:
            text = str(item.text_content(timeout=500) or "").strip()
        except Exception:
            text = ""
        if not text:
            try:
                text = str(item.get_attribute("value") or "").strip()
            except Exception:
                text = ""
        lowered = text.casefold()
        if not any(marker in lowered for marker in targets):
            continue
        try:
            item.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        try:
            item.click(timeout=3000)
            return True
        except Exception:
            try:
                handle = item.element_handle(timeout=1000)
                if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                    return True
            except Exception:
                continue
    return False


def _wait_for_page_change(
    page: Any,
    previous_signature: Tuple[Tuple[str, str], ...],
    stop_signal: Optional[threading.Event],
    *,
    timeout_ms: int = _CREDAMO_PAGE_TRANSITION_TIMEOUT_MS,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        current_signature = _question_signature(page)
        if current_signature and current_signature != previous_signature:
            return True
        if time.monotonic() >= deadline:
            return False
        if stop_signal is not None:
            stop_signal.wait(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
        else:
            time.sleep(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return False


def _click_submit_once(page: Any) -> bool:
    return _click_navigation(page, "submit")


def _click_submit(
    page: Any,
    stop_signal: Optional[threading.Event] = None,
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        if _click_submit_once(page):
            return True
        if time.monotonic() >= deadline:
            return False
        if stop_signal is not None:
            stop_signal.wait(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
        else:
            time.sleep(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return False


def brush_credamo(
    driver: BrowserDriver,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any] = None,
) -> bool:
    del psycho_plan
    active_stop = stop_signal or state.stop_event
    page = _page(driver)
    total_steps = max(1, len(config.question_config_index_map))
    answered_steps = 0
    try:
        state.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化 Credamo 线程进度失败", exc_info=True)

    while not _abort_requested(active_stop):
        roots = _wait_for_question_roots(page, active_stop)
        if not roots:
            raise RuntimeError("Credamo 当前页未识别到题目")

        answered_keys: set[str] = set()
        page_fallback_start = answered_steps
        while not _abort_requested(active_stop):
            pending_roots = _unanswered_question_roots(page, roots, answered_keys, fallback_start=page_fallback_start)
            if not pending_roots:
                break

            for root, question_num, question_key in pending_roots:
                if _abort_requested(active_stop):
                    try:
                        state.update_thread_status(thread_name, "已中断", running=False)
                    except Exception:
                        pass
                    return False

                answered_keys.add(question_key)
                config_entry = config.question_config_index_map.get(question_num)
                if config_entry is None:
                    fallback_kind = _question_kind_from_root(page, root)
                    logging.info("Credamo 第%s题未匹配到配置，页面题型=%s，题面=%s", question_num, fallback_kind, _root_text(page, root))
                    answered_steps = min(total_steps, answered_steps + 1)
                    continue

                entry_type, config_index = config_entry
                try:
                    state.update_thread_step(
                        thread_name,
                        min(total_steps, answered_steps + 1),
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新 Credamo 线程进度失败", exc_info=True)

                if entry_type == "single":
                    weights = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
                    _answer_single_like(page, root, weights, 0)
                elif entry_type in {"scale", "score"}:
                    weights = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
                    _answer_scale(page, root, weights)
                elif entry_type == "dropdown":
                    weights = config.droplist_prob[config_index] if config_index < len(config.droplist_prob) else -1
                    _answer_dropdown(page, root, weights)
                elif entry_type == "multiple":
                    weights = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else []
                    _answer_multiple(page, root, weights)
                elif entry_type == "order":
                    _answer_order(page, root)
                elif entry_type in {"text", "multi_text"}:
                    text_config = config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT]
                    _answer_text(root, text_config)
                else:
                    logging.info("Credamo 第%s题暂未接入题型：%s", question_num, entry_type)
                answered_steps = min(total_steps, answered_steps + 1)
                time.sleep(random.uniform(0.08, 0.22))

            roots = _wait_for_dynamic_question_roots(
                page,
                answered_keys,
                active_stop,
                fallback_start=page_fallback_start,
            )
        navigation_action = _navigation_action(page)
        if navigation_action != "next":
            break
        previous_signature = _question_signature(page)
        try:
            state.update_thread_status(thread_name, "翻到下一页", running=True)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：翻到下一页", exc_info=True)
        if not _click_navigation(page, "next"):
            raise RuntimeError("Credamo 下一页按钮未找到")
        if not _wait_for_page_change(page, previous_signature, active_stop):
            raise RuntimeError("Credamo 点击下一页后页面没有变化")

    if simulate_answer_duration_delay(active_stop, config.answer_duration_range_seconds):
        return False
    try:
        state.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：提交中", exc_info=True)
    if not _click_submit(page, active_stop):
        raise RuntimeError("Credamo 提交按钮未找到")
    try:
        state.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：等待结果确认", exc_info=True)
    return True
