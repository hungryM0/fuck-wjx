"""答题核心逻辑 - 按配置策略自动填写问卷。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from software.app.config import HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY
from software.core.engine.dom_helpers import (
    _count_choice_inputs_driver,
    _driver_question_looks_like_description,
    _driver_question_looks_like_slider_matrix,
)
from software.core.engine.runtime_control import _is_headless_mode
from software.core.modes.duration_control import has_configured_answer_duration, simulate_answer_duration_delay
from software.core.questions.utils import _should_treat_question_as_text_like
from software.core.reverse_fill.runtime import resolve_current_reverse_fill_answer
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver, By, NoSuchElementException
from wjx.provider.detection import detect as _wjx_detect
from wjx.provider.navigation import _click_next_page_button, _human_scroll_after_question
from wjx.provider.questions.multiple import multiple as _multiple_impl
from wjx.provider.questions.single import single as _single_impl
from wjx.provider.questions.text import (
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    text as _text_impl,
)
from wjx.provider.runtime_dispatch import _dispatcher, _question_title_for_log
from wjx.provider.submission import submit


def _build_initial_indices() -> Dict[str, int]:
    return {
        "single": 0,
        "text": 0,
        "dropdown": 0,
        "multiple": 0,
        "matrix": 0,
        "scale": 0,
        "slider": 0,
    }


def _update_abort_status(ctx: ExecutionState, thread_name: str) -> None:
    try:
        ctx.update_thread_status(thread_name, "已中断", running=False)
    except Exception:
        logging.info("更新线程状态失败：已中断", exc_info=True)


def _fallback_unknown_question(
    driver: BrowserDriver,
    ctx: ExecutionState,
    *,
    question_num: int,
    question_type: str,
    question_div,
    indices: Dict[str, int],
) -> None:
    config = ctx.config
    handled = False
    if question_div is not None:
        checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
        if checkbox_count or radio_count:
            if checkbox_count >= radio_count:
                _multiple_impl(
                    driver,
                    question_num,
                    indices["multiple"],
                    config.multiple_prob,
                    config.multiple_option_fill_texts,
                )
                indices["multiple"] += 1
            else:
                _single_impl(
                    driver,
                    question_num,
                    indices["single"],
                    config.single_prob,
                    config.single_option_fill_texts,
                    config.single_attached_option_selects,
                    task_ctx=ctx,
                )
                indices["single"] += 1
            handled = True

    if handled:
        return

    option_count = 0
    if question_div is not None:
        try:
            option_elements = question_div.find_elements(By.CSS_SELECTOR, ".ui-controlgroup > div")
            option_count = len(option_elements)
        except Exception:
            option_count = 0
    text_input_count = _count_visible_text_inputs_driver(question_div) if question_div is not None else 0
    has_slider_matrix = _driver_question_looks_like_slider_matrix(question_div)
    is_text_like_question = _should_treat_question_as_text_like(
        question_type,
        option_count,
        text_input_count,
        has_slider_matrix=has_slider_matrix,
    )

    if is_text_like_question:
        reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, question_num)
        _text_impl(
            driver,
            question_num,
            indices["text"],
            config.texts,
            config.texts_prob,
            config.text_entry_types,
            config.text_ai_flags,
            config.text_titles,
            config.multi_text_blank_modes,
            config.multi_text_blank_ai_flags,
            config.multi_text_blank_int_ranges,
            task_ctx=ctx,
        )
        if reverse_fill_answer is None:
            indices["text"] += 1
        return

    print(f"第{question_num}题为不支持类型(type={question_type})")


def brush(
    driver: BrowserDriver,
    ctx: ExecutionState,
    stop_signal: Optional[threading.Event] = None,
    *,
    thread_name: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    thread_name = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
    questions_per_page = _wjx_detect(driver, stop_signal=stop_signal)
    headless_mode = _is_headless_mode(ctx)
    try:
        total_steps = sum(max(0, int(count or 0)) for count in questions_per_page)
    except Exception:
        total_steps = 0
    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化线程步骤进度失败", exc_info=True)

    indices = _build_initial_indices()
    current_question_number = 0
    active_stop = stop_signal or ctx.stop_event
    runtime_config = ctx.config

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    if _abort_requested():
        _update_abort_status(ctx, thread_name)
        return False

    total_pages = len(questions_per_page)
    for page_index, questions_count in enumerate(questions_per_page):
        for _ in range(1, questions_count + 1):
            if _abort_requested():
                _update_abort_status(ctx, thread_name)
                return False
            current_question_number += 1
            if total_steps > 0:
                try:
                    ctx.update_thread_step(
                        thread_name,
                        current_question_number,
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新线程步骤进度失败", exc_info=True)
            question_selector = f"#div{current_question_number}"
            try:
                question_div = driver.find_element(By.CSS_SELECTOR, question_selector)
            except Exception:
                question_div = None
            if question_div is None:
                continue

            question_visible = False
            for attempt in range(5):
                try:
                    if question_div.is_displayed():
                        question_visible = True
                        break
                except Exception:
                    break
                if attempt < 4:
                    time.sleep(0.1)

            question_type = question_div.get_attribute("type")
            if question_type is None:
                logging.info("跳过第%d题（type 属性为空）", current_question_number)
                continue
            if _driver_question_looks_like_description(question_div, question_type):
                title = _question_title_for_log(driver, current_question_number, question_div)
                if title:
                    logging.info("跳过第%d题（说明页/阅读材料，type=%s，标题=%s）", current_question_number, question_type, title)
                else:
                    logging.info("跳过第%d题（说明页/阅读材料，type=%s）", current_question_number, question_type)
                continue

            if not question_visible:
                title = _question_title_for_log(driver, current_question_number, question_div)
                if title:
                    logging.info("跳过第%d题（未显示，type=%s，标题=%s）", current_question_number, question_type, title)
                else:
                    logging.info("跳过第%d题（未显示，type=%s）", current_question_number, question_type)
                continue

            config_entry = runtime_config.question_config_index_map.get(current_question_number)
            dispatch_result = _dispatcher.fill(
                driver=driver,
                question_type=question_type,
                question_num=current_question_number,
                question_div=question_div,
                config_entry=config_entry,
                indices=indices,
                ctx=ctx,
                psycho_plan=psycho_plan,
            )

            if dispatch_result is False:
                _fallback_unknown_question(
                    driver,
                    ctx,
                    question_num=current_question_number,
                    question_type=question_type,
                    question_div=question_div,
                    indices=indices,
                )

        _human_scroll_after_question(driver)
        if _abort_requested():
            _update_abort_status(ctx, thread_name)
            return False
        buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
        if buffer_delay > 0:
            if active_stop:
                if active_stop.wait(buffer_delay):
                    _update_abort_status(ctx, thread_name)
                    return False
            else:
                time.sleep(buffer_delay)
        is_last_page = (page_index == total_pages - 1)
        if is_last_page:
            if has_configured_answer_duration(runtime_config.answer_duration_range_seconds):
                try:
                    ctx.update_thread_status(thread_name, "等待时长中", running=True)
                except Exception:
                    logging.info("更新线程状态失败：等待时长中", exc_info=True)
            if simulate_answer_duration_delay(active_stop, runtime_config.answer_duration_range_seconds):
                _update_abort_status(ctx, thread_name)
                return False
            if _abort_requested():
                _update_abort_status(ctx, thread_name)
                return False
            break
        clicked = _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("Next page button not found")
        click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
        if click_delay > 0:
            if active_stop:
                if active_stop.wait(click_delay):
                    _update_abort_status(ctx, thread_name)
                    return False
            else:
                time.sleep(click_delay)

    if _abort_requested():
        _update_abort_status(ctx, thread_name)
        return False
    try:
        ctx.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新线程状态失败：提交中", exc_info=True)
    submit(driver, ctx=ctx, stop_signal=active_stop)
    try:
        ctx.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新线程状态失败：等待结果确认", exc_info=True)
    return True


def brush_wjx(
    driver: BrowserDriver,
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    del config
    return brush(
        driver,
        ctx,
        stop_signal=stop_signal,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    )
