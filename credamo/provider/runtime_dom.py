"""Credamo 见数运行时页面识别、导航与通用 DOM 操作。"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, List, Optional, Tuple

from software.network.browser import BrowserDriver


_CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS = 20000
_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS = 0.5
_CREDAMO_PAGE_TRANSITION_TIMEOUT_MS = 12000
_CREDAMO_DYNAMIC_REVEAL_TIMEOUT_MS = 2000
_CREDAMO_LOADING_SHELL_EXTRA_WAIT_TIMEOUT_MS = 25000
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


def _page_loading_snapshot(page: Any) -> Tuple[str, str]:
    try:
        title = str(page.title() or "").strip()
    except Exception:
        title = ""
    try:
        body_text = str(page.locator("body").inner_text(timeout=1000) or "").strip()
    except Exception:
        body_text = ""
    return title, re.sub(r"\s+", " ", body_text).strip()


def _looks_like_loading_shell(title: str, body_text: str) -> bool:
    normalized_title = str(title or "").strip()
    normalized_body = str(body_text or "").strip()
    if not normalized_body:
        return normalized_title in {"", "答卷"}
    compact_body = normalized_body.replace(" ", "")
    if compact_body in {"载入中", "载入中...", "载入中..", "loading", "loading..."}:
        return True
    if normalized_title == "答卷" and len(compact_body) <= 16:
        return True
    return False


def _wait_for_question_roots(
    page: Any,
    stop_signal: Optional[threading.Event],
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
    loading_shell_extra_timeout_ms: int = _CREDAMO_LOADING_SHELL_EXTRA_WAIT_TIMEOUT_MS,
) -> List[Any]:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    last_roots: List[Any] = []
    loading_shell_retry_used = False
    while not _abort_requested(stop_signal):
        try:
            last_roots = _question_roots(page)
        except Exception:
            logging.info("Credamo 等待题目加载时读取页面失败", exc_info=True)
            last_roots = []
        if last_roots:
            return last_roots
        if time.monotonic() >= deadline:
            title, body_text = _page_loading_snapshot(page)
            if (
                not loading_shell_retry_used
                and loading_shell_extra_timeout_ms > 0
                and _looks_like_loading_shell(title, body_text)
            ):
                loading_shell_retry_used = True
                deadline = time.monotonic() + max(0.0, loading_shell_extra_timeout_ms / 1000)
                logging.warning(
                    "Credamo 页面仍在载入壳页，延长等待题目：title=%s body=%s",
                    title or "<empty>",
                    (body_text[:80] or "<empty>"),
                )
                continue
            logging.warning(
                "Credamo 等待题目超时：title=%s body=%s",
                title or "<empty>",
                (body_text[:120] or "<empty>"),
            )
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
