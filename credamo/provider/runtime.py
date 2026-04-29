"""Credamo 见数问卷运行时作答主流程。"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.modes.duration_control import has_configured_answer_duration, simulate_answer_duration_delay
from software.core.questions.utils import normalize_droplist_probs, weighted_index
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver

from . import runtime_answerers as _runtime_answerers
from . import runtime_dom as _runtime_dom

_DOM_CLICK_SUBMIT = _runtime_dom._click_submit
_DOM_UNANSWERED_QUESTION_ROOTS = _runtime_dom._unanswered_question_roots
_DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS = _runtime_dom._wait_for_dynamic_question_roots
_DOM_WAIT_FOR_PAGE_CHANGE = _runtime_dom._wait_for_page_change
_DOM_WAIT_FOR_QUESTION_ROOTS = _runtime_dom._wait_for_question_roots
_ANSWER_DROPDOWN = _runtime_answerers._answer_dropdown
_ANSWER_MULTIPLE = _runtime_answerers._answer_multiple
_ANSWER_ORDER = _runtime_answerers._answer_order
_ANSWER_SCALE = _runtime_answerers._answer_scale
_ANSWER_SINGLE_LIKE = _runtime_answerers._answer_single_like
_ANSWER_TEXT = _runtime_answerers._answer_text

_abort_requested = _runtime_dom._abort_requested
_click_element = _runtime_dom._click_element
_click_navigation = _runtime_dom._click_navigation
_click_submit_once = _runtime_dom._click_submit_once
_element_text = _runtime_dom._element_text
_input_value = _runtime_dom._input_value
_is_checked = _runtime_dom._is_checked
_locator_is_visible = _runtime_dom._locator_is_visible
_looks_like_loading_shell = _runtime_dom._looks_like_loading_shell
_navigation_action = _runtime_dom._navigation_action
_option_click_targets = _runtime_dom._option_click_targets
_option_inputs = _runtime_dom._option_inputs
_page = _runtime_dom._page
_page_loading_snapshot = _runtime_dom._page_loading_snapshot
_question_kind_from_root = _runtime_dom._question_kind_from_root
_question_number_from_root = _runtime_dom._question_number_from_root
_question_roots = _runtime_dom._question_roots
_question_signature = _runtime_dom._question_signature
_question_title_text = _runtime_dom._question_title_text
_root_text = _runtime_dom._root_text
_text_inputs = _runtime_dom._text_inputs
_resolve_forced_choice_index = _runtime_answerers._resolve_forced_choice_index


def _sync_runtime_dom_patch_points() -> None:
    """让 runtime.py 上的补丁同步到底层 DOM 模块。"""
    _runtime_dom._abort_requested = _abort_requested
    _runtime_dom._click_navigation = _click_navigation
    _runtime_dom._click_submit_once = _click_submit_once
    _runtime_dom._locator_is_visible = _locator_is_visible
    _runtime_dom._looks_like_loading_shell = _looks_like_loading_shell
    _runtime_dom._navigation_action = _navigation_action
    _runtime_dom._page_loading_snapshot = _page_loading_snapshot
    _runtime_dom._question_number_from_root = _question_number_from_root
    _runtime_dom._question_roots = _question_roots
    _runtime_dom._question_signature = _question_signature
    _runtime_dom._root_text = _root_text


def _sync_runtime_answerer_patch_points() -> None:
    """让 runtime.py 上的补丁同步到底层题型作答模块。"""
    _runtime_answerers._click_element = _click_element
    _runtime_answerers._element_text = _element_text
    _runtime_answerers._input_value = _input_value
    _runtime_answerers._is_checked = _is_checked
    _runtime_answerers._option_click_targets = _option_click_targets
    _runtime_answerers._option_inputs = _option_inputs
    _runtime_answerers._question_title_text = _question_title_text
    _runtime_answerers._resolve_forced_choice_index = _resolve_forced_choice_index
    _runtime_answerers._root_text = _root_text
    _runtime_answerers._text_inputs = _text_inputs
    _runtime_answerers.normalize_droplist_probs = normalize_droplist_probs
    _runtime_answerers.weighted_index = weighted_index


def _wait_for_question_roots(page: Any, stop_signal: Optional[threading.Event], **kwargs: Any):
    _sync_runtime_dom_patch_points()
    return _DOM_WAIT_FOR_QUESTION_ROOTS(page, stop_signal, **kwargs)


def _unanswered_question_roots(page: Any, roots: list[Any], answered_keys: set[str], **kwargs: Any):
    _sync_runtime_dom_patch_points()
    return _DOM_UNANSWERED_QUESTION_ROOTS(page, roots, answered_keys, **kwargs)


def _wait_for_dynamic_question_roots(page: Any, answered_keys: set[str], stop_signal: Optional[threading.Event], **kwargs: Any):
    _sync_runtime_dom_patch_points()
    return _DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS(page, answered_keys, stop_signal, **kwargs)


def _wait_for_page_change(page: Any, previous_signature: Any, stop_signal: Optional[threading.Event], **kwargs: Any) -> bool:
    _sync_runtime_dom_patch_points()
    return _DOM_WAIT_FOR_PAGE_CHANGE(page, previous_signature, stop_signal, **kwargs)


def _click_submit(page: Any, stop_signal: Optional[threading.Event] = None, **kwargs: Any) -> bool:
    _sync_runtime_dom_patch_points()
    return _DOM_CLICK_SUBMIT(page, stop_signal, **kwargs)


def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_SINGLE_LIKE(page, root, weights, option_count)


def _answer_multiple(page: Any, root: Any, weights: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_MULTIPLE(page, root, weights)


def _answer_text(root: Any, text_config: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_TEXT(root, text_config)


def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_DROPDOWN(page, root, weights)


def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_SCALE(page, root, weights)


def _answer_order(page: Any, root: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_ORDER(page, root)


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

    if has_configured_answer_duration(config.answer_duration_range_seconds):
        try:
            state.update_thread_status(thread_name, "等待时长中", running=True)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：等待时长中", exc_info=True)
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
