"""Credamo 见数问卷运行时作答主流程。"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.modes.duration_control import has_configured_answer_duration, simulate_answer_duration_delay
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver

from .runtime_answerers import (
    _answer_dropdown,
    _answer_multiple,
    _answer_order,
    _answer_scale,
    _answer_single_like,
    _answer_text,
)
from .runtime_dom import (
    _abort_requested,
    _click_navigation,
    _click_submit,
    _navigation_action,
    _page,
    _question_kind_from_root,
    _question_signature,
    _root_text,
    _unanswered_question_roots,
    _wait_for_dynamic_question_roots,
    _wait_for_page_change,
    _wait_for_question_roots,
)


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
