"""腾讯问卷运行时答题与提交辅助。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from software.app.config import HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY
from software.core.engine.async_wait import sleep_or_stop
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import NoSuchElementException
from software.network.browser.runtime_async import BrowserDriver

from software.core.engine.navigation import _human_scroll_after_question
from software.core.engine.runtime_control import _is_headless_mode
from tencent.provider.navigation import _click_next_page_button, dismiss_resume_dialog_if_present
from tencent.provider.runtime_state import get_qq_runtime_state
from tencent.provider.submission import submit

from .runtime_answerers import (
    _answer_qq_dropdown,
    _answer_qq_matrix,
    _answer_qq_matrix_star,
    _answer_qq_multiple,
    _answer_qq_score_like,
    _answer_qq_single,
    _answer_qq_text,
)
from .runtime_flow import (
    _group_questions_by_page,
    _wait_for_page_transition,
)
from .runtime_interactions import (
    _is_question_visible,
    _supports_page_snapshot,
    _wait_for_question_visibility_map,
    _wait_for_question_visible,
)

__all__ = ["brush_qq", "refill_required_questions_on_current_page"]
_QQ_PAGE_READY_TIMEOUT_MS = 2500
_QQ_SINGLE_QUESTION_FALLBACK_TIMEOUT_MS = 1800
_QQ_PAGE_TRANSITION_TIMEOUT_MS = 5000


async def _answer_question_by_meta(
    driver: BrowserDriver,
    question: Any,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    config_entry = ctx.config.question_config_index_map.get(int(question.num or 0))
    if not config_entry:
        logging.warning("腾讯问卷第%d题缺少配置映射，无法补答。", int(question.num or 0))
        return False
    entry_type, config_index = config_entry
    if entry_type == "single":
        await _answer_qq_single(driver, question, config_index, ctx, psycho_plan=psycho_plan)
        return True
    if entry_type == "multiple":
        await _answer_qq_multiple(driver, question, config_index, ctx)
        return True
    if entry_type == "dropdown":
        await _answer_qq_dropdown(driver, question, config_index, ctx, psycho_plan=psycho_plan)
        return True
    if entry_type in {"text", "multi_text"}:
        await _answer_qq_text(driver, question, config_index, ctx)
        return True
    if entry_type in {"scale", "score"}:
        await _answer_qq_score_like(driver, question, config_index, ctx, psycho_plan=psycho_plan)
        return True
    if entry_type == "matrix":
        if question.provider_type == "matrix_star":
            await _answer_qq_matrix_star(driver, question, config_index, ctx, psycho_plan=psycho_plan)
        else:
            await _answer_qq_matrix(driver, question, config_index, ctx, psycho_plan=psycho_plan)
        return True
    logging.warning("腾讯问卷第%d题暂未接入补答题型：%s", int(question.num or 0), entry_type)
    return False


async def refill_required_questions_on_current_page(
    driver: BrowserDriver,
    ctx: ExecutionState,
    *,
    question_numbers: list[int],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> int:
    normalized_numbers: list[int] = []
    for raw_num in list(question_numbers or []):
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num > 0 and question_num not in normalized_numbers:
            normalized_numbers.append(question_num)
    if not normalized_numbers:
        return 0

    runtime_state = get_qq_runtime_state(driver)
    page_question_ids = {
        str(item or "").strip()
        for item in list(runtime_state.page_question_ids or [])
        if str(item or "").strip()
    }
    visible_snapshot = dict(runtime_state.visibility_snapshot or {})
    filled_count = 0
    for question_num in normalized_numbers:
        question = ctx.config.questions_metadata.get(question_num)
        if question is None:
            logging.warning("腾讯问卷第%d题缺少题目元数据，无法补答。", question_num)
            continue
        question_id = str(question.provider_question_id or "").strip()
        if page_question_ids and question_id and question_id not in page_question_ids:
            continue
        if question_id:
            snapshot_item = visible_snapshot.get(question_id) if isinstance(visible_snapshot, dict) else None
            visible = bool((snapshot_item or {}).get("visible")) if isinstance(snapshot_item, dict) else False
            if not visible:
                visible = await _wait_for_question_visible(driver, question_id, timeout_ms=_QQ_SINGLE_QUESTION_FALLBACK_TIMEOUT_MS)
            if not visible:
                continue
        try:
            ctx.update_thread_status(thread_name or "Worker-?", f"补答第{question_num}题", running=True)
        except Exception:
            logging.info("更新线程状态失败：补答第%d题", question_num, exc_info=True)
        if await _answer_question_by_meta(driver, question, ctx, psycho_plan=psycho_plan):
            filled_count += 1
    return filled_count


async def brush_qq(
    driver: BrowserDriver,
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Optional[Any],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    del config
    runtime_config = ctx.config
    unsupported = [item for item in list((runtime_config.questions_metadata or {}).values()) if bool(item.unsupported)]
    if unsupported:
        raise RuntimeError("当前腾讯问卷仍包含未支持题型，已阻止启动")

    page_groups = _group_questions_by_page(ctx)
    total_steps = sum(len(group.questions) for group in page_groups)
    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化腾讯问卷步骤进度失败", exc_info=True)

    active_stop = stop_signal or ctx.stop_event
    step_index = 0
    headless_mode = _is_headless_mode(ctx)
    runtime_state = get_qq_runtime_state(driver)
    runtime_state.psycho_plan = psycho_plan

    await dismiss_resume_dialog_if_present(driver, timeout=1.5, stop_signal=active_stop)

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    for page_index, group in enumerate(page_groups):
        questions = list(group.questions or [])
        page_question_ids = [str(question.provider_question_id or "").strip() for question in questions if str(question.provider_question_id or "").strip()]
        page_snapshot = {}
        if await _supports_page_snapshot(driver):
            page_snapshot = await _wait_for_question_visibility_map(
                driver,
                page_question_ids,
                timeout_ms=_QQ_PAGE_READY_TIMEOUT_MS,
                require_any_visible=True,
            )
        runtime_state.page_index = page_index + 1
        runtime_state.page_question_ids = list(page_question_ids)
        runtime_state.visibility_snapshot = dict(page_snapshot or {})
        for question in questions:
            if _abort_requested():
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False

            question_num = int(question.num or 0)
            question_id = str(question.provider_question_id or "")
            if question_num <= 0 or not question_id:
                continue
            snapshot_item = page_snapshot.get(question_id) if isinstance(page_snapshot, dict) else None
            question_visible = bool((snapshot_item or {}).get("visible")) if isinstance(snapshot_item, dict) else False
            if not question_visible:
                if snapshot_item is None:
                    question_visible = await _wait_for_question_visible(
                        driver,
                        question_id,
                        timeout_ms=_QQ_SINGLE_QUESTION_FALLBACK_TIMEOUT_MS,
                    )
                elif bool((snapshot_item or {}).get("attached")):
                    question_visible = await _is_question_visible(driver, question_id)
                else:
                    question_visible = False
            if not question_visible:
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

            await _answer_question_by_meta(driver, question, ctx, psycho_plan=psycho_plan)

        await _human_scroll_after_question(driver)
        if _abort_requested():
            try:
                ctx.update_thread_status(thread_name, "已中断", running=False)
            except Exception:
                logging.info("更新线程状态失败：已中断", exc_info=True)
            return False

        buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
        if buffer_delay > 0:
            if await sleep_or_stop(active_stop, buffer_delay):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False

        is_last_page = page_index == len(page_groups) - 1
        if is_last_page:
            break

        current_first = str(group.anchor_question_id or "")
        next_first = str(page_groups[page_index + 1].anchor_question_id or "")
        if not current_first or not next_first:
            raise NoSuchElementException("腾讯问卷分页锚点缺失，无法继续翻页")
        clicked = await _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("腾讯问卷下一页按钮未找到")
        await _wait_for_page_transition(
            driver,
            current_first,
            next_first,
            timeout_ms=_QQ_PAGE_TRANSITION_TIMEOUT_MS,
        )
        click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
        if click_delay > 0:
            if await sleep_or_stop(active_stop, click_delay):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False

    if _abort_requested():
        try:
            ctx.update_thread_status(thread_name, "已中断", running=False)
        except Exception:
            logging.info("更新线程状态失败：已中断", exc_info=True)
        return False

    if not bool(getattr(runtime_config, "submit_enabled", True)):
        try:
            ctx.update_thread_status(thread_name, "单测完成", running=False)
        except Exception:
            logging.info("更新线程状态失败：单测完成", exc_info=True)
        return True

    try:
        ctx.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新线程状态失败：提交中", exc_info=True)
    await submit(driver, ctx=ctx, stop_signal=active_stop)
    try:
        ctx.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新线程状态失败：等待结果确认", exc_info=True)
    return True
