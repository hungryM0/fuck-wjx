"""腾讯问卷运行时答题与提交辅助。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from software.app.config import HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY
from software.core.modes.duration_control import simulate_answer_duration_delay
from software.core.task import TaskContext
from software.network.browser import BrowserDriver, NoSuchElementException

from software.core.engine.navigation import _human_scroll_after_question
from software.core.engine.runtime_control import _is_headless_mode
from tencent.provider.navigation import _click_next_page_button, dismiss_resume_dialog_if_present
from tencent.provider.submission import submit

from .runtime_answerers import (
    _answer_qq_dropdown,
    _answer_qq_matrix,
    _answer_qq_multiple,
    _answer_qq_score_like,
    _answer_qq_single,
    _answer_qq_text,
)
from .runtime_flow import (
    _group_questions_by_page,
    _wait_for_page_transition,
    qq_is_completion_page,
    qq_submission_requires_verification,
    qq_submission_validation_message,
)
from .runtime_interactions import _is_question_visible, _wait_for_question_visible

__all__ = [
    "brush_qq",
    "qq_is_completion_page",
    "qq_submission_requires_verification",
    "qq_submission_validation_message",
]


def brush_qq(
    driver: BrowserDriver,
    ctx: TaskContext,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    unsupported = [item for item in list((ctx.questions_metadata or {}).values()) if bool(item.get("unsupported"))]
    if unsupported:
        raise RuntimeError("当前腾讯问卷仍包含未支持题型，已阻止启动")

    page_groups = _group_questions_by_page(ctx)
    total_steps = sum(len(group) for group in page_groups)
    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化腾讯问卷步骤进度失败", exc_info=True)

    active_stop = stop_signal or ctx.stop_event
    step_index = 0
    headless_mode = _is_headless_mode(ctx)

    dismiss_resume_dialog_if_present(driver, timeout=1.5, stop_signal=active_stop)

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    for page_index, questions in enumerate(page_groups):
        for question in questions:
            if _abort_requested():
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False

            question_num = int(question.get("num") or 0)
            question_id = str(question.get("provider_question_id") or "")
            if question_num <= 0 or not question_id:
                continue
            if not _wait_for_question_visible(driver, question_id, timeout_ms=8000):
                logging.warning("腾讯问卷第%d题未出现在当前页面，已跳过。", question_num)
                continue
            if not _is_question_visible(driver, question_id):
                continue

            step_index += 1
            if total_steps > 0:
                try:
                    ctx.update_thread_step(
                        thread_name,
                        step_index,
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新腾讯问卷线程步骤失败", exc_info=True)

            config_entry = ctx.question_config_index_map.get(question_num)
            if not config_entry:
                logging.warning("腾讯问卷第%d题缺少配置映射，已跳过。", question_num)
                continue
            entry_type, config_index = config_entry
            if entry_type == "single":
                _answer_qq_single(driver, question, config_index, ctx)
            elif entry_type == "multiple":
                _answer_qq_multiple(driver, question, config_index, ctx)
            elif entry_type == "dropdown":
                _answer_qq_dropdown(driver, question, config_index, ctx, psycho_plan=psycho_plan)
            elif entry_type in {"text", "multi_text"}:
                _answer_qq_text(driver, question, config_index, ctx)
            elif entry_type in {"scale", "score"}:
                _answer_qq_score_like(driver, question, config_index, ctx, psycho_plan=psycho_plan)
            elif entry_type == "matrix":
                _answer_qq_matrix(driver, question, config_index, ctx, psycho_plan=psycho_plan)
            else:
                logging.warning("腾讯问卷第%d题暂未接入运行时类型：%s", question_num, entry_type)

        _human_scroll_after_question(driver)
        if _abort_requested():
            try:
                ctx.update_thread_status(thread_name, "已中断", running=False)
            except Exception:
                logging.info("更新线程状态失败：已中断", exc_info=True)
            return False

        buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
        if buffer_delay > 0:
            if active_stop and active_stop.wait(buffer_delay):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False
            if not active_stop:
                time.sleep(buffer_delay)

        is_last_page = page_index == len(page_groups) - 1
        if is_last_page:
            if simulate_answer_duration_delay(active_stop, ctx.answer_duration_range_seconds):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False
            break

        current_first = str(questions[0].get("provider_question_id") or "")
        next_first = str(page_groups[page_index + 1][0].get("provider_question_id") or "")
        clicked = _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("腾讯问卷下一页按钮未找到")
        _wait_for_page_transition(driver, current_first, next_first)
        click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
        if click_delay > 0:
            if active_stop and active_stop.wait(click_delay):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False
            if not active_stop:
                time.sleep(click_delay)

    if _abort_requested():
        try:
            ctx.update_thread_status(thread_name, "已中断", running=False)
        except Exception:
            logging.info("更新线程状态失败：已中断", exc_info=True)
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
