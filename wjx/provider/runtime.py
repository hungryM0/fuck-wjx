"""问卷星运行时答题主流程。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

from software.app.config import HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY
from software.core.engine.async_wait import sleep_or_stop
from software.core.engine.navigation import _human_scroll_after_question
from software.core.engine.runtime_control import _is_headless_mode
from software.core.modes.duration_control import has_configured_answer_duration
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import NoSuchElementException
from software.network.browser.runtime_async import BrowserDriver
from software.providers.contracts import SurveyQuestionMeta

from .navigation import _click_next_page_button, dismiss_resume_dialog_if_present, try_click_start_answer_button
from .runtime_answerers import answer_page_batch, answer_question_by_meta
from .runtime_interactions import (
    _collect_visible_question_snapshot,
    _is_question_visible,
    _wait_for_any_visible_questions,
)
from .runtime_state import get_wjx_runtime_state
from .starttime import prepare_answer_duration_before_submit
from .submission import submit

__all__ = ["brush", "brush_wjx", "refill_required_questions_on_current_page"]


def _build_runtime_page_question_plan(
    page_questions: Iterable[SurveyQuestionMeta],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for meta in page_questions:
        if meta is None:
            continue
        try:
            question_num = int(getattr(meta, "num", 0) or 0)
        except Exception:
            question_num = 0
        if question_num <= 0:
            continue
        plan.append(
            {
                "question_num": question_num,
                "type_code": str(getattr(meta, "type_code", "") or "").strip(),
                "required": bool(getattr(meta, "required", False)),
            }
        )
    return plan


def _question_metadata_map(ctx: ExecutionState) -> Dict[int, SurveyQuestionMeta]:
    metadata = getattr(getattr(ctx, "config", ctx), "questions_metadata", {}) or {}
    normalized: Dict[int, SurveyQuestionMeta] = {}
    if not isinstance(metadata, dict):
        return normalized
    for raw_num, meta in metadata.items():
        if meta is None:
            continue
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num <= 0:
            continue
        normalized[question_num] = meta
    return normalized


def _group_questions_by_page(ctx: ExecutionState) -> list[list[SurveyQuestionMeta]]:
    metadata = _question_metadata_map(ctx)
    by_page: dict[int, list[SurveyQuestionMeta]] = {}
    for meta in metadata.values():
        try:
            page_number = max(1, int(getattr(meta, "page", 1) or 1))
        except Exception:
            page_number = 1
        by_page.setdefault(page_number, []).append(meta)
    groups: list[list[SurveyQuestionMeta]] = []
    for page_number in sorted(by_page):
        questions = sorted(
            by_page[page_number],
            key=lambda item: (int(getattr(item, "num", 0) or 0), str(getattr(item, "title", "") or "")),
        )
        if questions:
            groups.append(questions)
    return groups


def _abort_requested(stop_signal: Any) -> bool:
    checker = getattr(stop_signal, "is_set", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return False


def _update_abort_status(ctx: ExecutionState, thread_name: str) -> None:
    try:
        ctx.update_thread_status(thread_name, "已中断", running=False)
    except Exception:
        logging.info("更新线程状态失败：已中断", exc_info=True)


async def _prepare_runtime_entry_gate(
    driver: BrowserDriver,
    active_stop: Any,
) -> bool:
    await dismiss_resume_dialog_if_present(driver, timeout=1.2, stop_signal=active_stop)
    start_clicked = await try_click_start_answer_button(driver, timeout=1.2, stop_signal=active_stop)
    if not start_clicked:
        return not _abort_requested(active_stop)
    return not await sleep_or_stop(active_stop, 0.15)


def _store_runtime_context(
    driver: BrowserDriver,
    *,
    page_number: int,
    page_questions: Iterable[SurveyQuestionMeta],
    psycho_plan: Optional[Any],
) -> None:
    state = get_wjx_runtime_state(driver)
    state.page_number = max(1, int(page_number or 1))
    state.page_questions = _build_runtime_page_question_plan(page_questions)
    state.psycho_plan = psycho_plan


async def _resolve_page_snapshot(
    driver: BrowserDriver,
    page_questions: list[SurveyQuestionMeta],
) -> dict[int, dict[str, Any]]:
    snapshot = await _wait_for_any_visible_questions(driver, timeout_ms=3000, poll_ms=100)
    if snapshot:
        return snapshot
    fallback = await _collect_visible_question_snapshot(driver)
    if fallback:
        return fallback
    expected: dict[int, dict[str, Any]] = {}
    for question in page_questions:
        try:
            question_num = int(getattr(question, "num", 0) or 0)
        except Exception:
            question_num = 0
        if question_num <= 0:
            continue
        expected[question_num] = {
            "visible": False,
            "type": str(getattr(question, "type_code", "") or "").strip(),
            "text": "",
        }
    return expected


async def _finalize_page(
    driver: BrowserDriver,
    active_stop: Any,
    *,
    headless_mode: bool,
    is_last_page: bool,
    runtime_config: ExecutionConfig,
    thread_name: str,
    ctx: ExecutionState,
) -> bool:
    await _human_scroll_after_question(driver)
    if _abort_requested(active_stop):
        _update_abort_status(ctx, thread_name)
        return False

    buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
    if buffer_delay > 0 and await sleep_or_stop(active_stop, buffer_delay):
        _update_abort_status(ctx, thread_name)
        return False

    if is_last_page:
        if has_configured_answer_duration(runtime_config.answer_duration_range_seconds):
            try:
                ctx.update_thread_status(thread_name, "处理作答时长", running=True)
            except Exception:
                logging.info("更新线程状态失败：处理作答时长", exc_info=True)
        if await prepare_answer_duration_before_submit(
            driver,
            active_stop,
            runtime_config.answer_duration_range_seconds,
        ):
            _update_abort_status(ctx, thread_name)
            return False
        if _abort_requested(active_stop):
            _update_abort_status(ctx, thread_name)
            return False
        return True

    clicked = await _click_next_page_button(driver)
    if not clicked:
        raise NoSuchElementException("WJX 下一页按钮未找到")

    click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
    if click_delay > 0 and await sleep_or_stop(active_stop, click_delay):
        _update_abort_status(ctx, thread_name)
        return False
    return True


async def refill_required_questions_on_current_page(
    driver: BrowserDriver,
    ctx: ExecutionState,
    *,
    question_numbers: Iterable[int],
    thread_name: str,
    psycho_plan: Optional[Any] = None,
) -> int:
    normalized_numbers: list[int] = []
    for raw_num in question_numbers:
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num > 0 and question_num not in normalized_numbers:
            normalized_numbers.append(question_num)
    if not normalized_numbers:
        return 0

    metadata = _question_metadata_map(ctx)
    runtime_state = get_wjx_runtime_state(driver)
    snapshot = await _collect_visible_question_snapshot(driver)
    filled_count = 0
    for question_num in normalized_numbers:
        question = metadata.get(question_num)
        if question is None:
            logging.warning("问卷星第%d题缺少题目元数据，无法补答。", question_num)
            continue
        snapshot_item = snapshot.get(question_num) if isinstance(snapshot, dict) else None
        visible = bool((snapshot_item or {}).get("visible")) if isinstance(snapshot_item, dict) else False
        if not visible:
            visible = await _is_question_visible(driver, question_num)
        if not visible:
            continue
        try:
            ctx.update_thread_status(thread_name or "Worker-?", f"补答第{question_num}题", running=True)
        except Exception:
            logging.info("更新线程状态失败：补答第%d题", question_num, exc_info=True)
        answered = await answer_question_by_meta(
            driver,
            question,
            ctx,
            psycho_plan=psycho_plan or runtime_state.psycho_plan,
        )
        if answered:
            filled_count += 1
    return filled_count


async def brush(
    driver: BrowserDriver,
    ctx: ExecutionState,
    stop_signal: Optional[Any] = None,
    *,
    thread_name: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
) -> bool:
    normalized_thread_name = str(thread_name or "Worker-?").strip() or "Worker-?"
    active_stop = stop_signal or ctx.stop_event
    if _abort_requested(active_stop):
        _update_abort_status(ctx, normalized_thread_name)
        return False

    runtime_config = ctx.config
    unsupported = [
        item
        for item in list((runtime_config.questions_metadata or {}).values())
        if bool(getattr(item, "unsupported", False))
    ]
    if unsupported:
        raise RuntimeError("当前问卷仍包含未支持题型，已阻止启动")

    page_groups = _group_questions_by_page(ctx)
    if not page_groups:
        raise RuntimeError("问卷星题目元数据为空，无法进入异步作答链路")

    total_steps = sum(len(group) for group in page_groups)
    try:
        ctx.update_thread_step(normalized_thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化问卷星步骤进度失败", exc_info=True)

    if not await _prepare_runtime_entry_gate(driver, active_stop):
        _update_abort_status(ctx, normalized_thread_name)
        return False

    headless_mode = _is_headless_mode(ctx)
    progress_step = 0
    runtime_state = get_wjx_runtime_state(driver)
    runtime_state.psycho_plan = psycho_plan
    runtime_state.submission_recovery_attempts = 0

    for page_index, questions in enumerate(page_groups):
        if _abort_requested(active_stop):
            _update_abort_status(ctx, normalized_thread_name)
            return False

        page_number = max(1, int(getattr(questions[0], "page", page_index + 1) or (page_index + 1)))
        snapshot = await _resolve_page_snapshot(driver, questions)
        _store_runtime_context(
            driver,
            page_number=page_number,
            page_questions=questions,
            psycho_plan=psycho_plan,
        )

        batch_applied: set[int] = set()
        page_has_dynamic_logic = any(
            bool(getattr(item, "has_jump", False)) or bool(getattr(item, "has_dependent_display_logic", False))
            for item in questions
        )
        if not page_has_dynamic_logic:
            batch_candidates: list[SurveyQuestionMeta] = []
            for candidate in questions:
                candidate_num = int(getattr(candidate, "num", 0) or 0)
                if candidate_num <= 0:
                    continue
                candidate_snapshot = snapshot.get(candidate_num) if isinstance(snapshot, dict) else None
                if bool((candidate_snapshot or {}).get("visible")):
                    batch_candidates.append(candidate)
            if batch_candidates:
                batch_result = await answer_page_batch(
                    driver,
                    batch_candidates,
                    ctx,
                    psycho_plan=psycho_plan,
                )
                batch_applied = {int(item) for item in batch_result.applied}

        for question in questions:
            if _abort_requested(active_stop):
                _update_abort_status(ctx, normalized_thread_name)
                return False

            question_num = int(getattr(question, "num", 0) or 0)
            if question_num <= 0:
                continue

            snapshot_item = snapshot.get(question_num) if isinstance(snapshot, dict) else None
            visible = bool((snapshot_item or {}).get("visible")) if isinstance(snapshot_item, dict) else False
            if not visible:
                visible = await _is_question_visible(driver, question_num)
            if not visible:
                continue

            progress_step += 1
            if total_steps > 0:
                try:
                    ctx.update_thread_step(
                        normalized_thread_name,
                        progress_step,
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新问卷星线程步骤失败", exc_info=True)

            if question_num in batch_applied:
                continue

            await answer_question_by_meta(driver, question, ctx, psycho_plan=psycho_plan)

            if bool(getattr(question, "has_jump", False)) or bool(getattr(question, "has_dependent_display_logic", False)):
                snapshot = await _collect_visible_question_snapshot(driver)

        if not await _finalize_page(
            driver,
            active_stop,
            headless_mode=headless_mode,
            is_last_page=(page_index == len(page_groups) - 1),
            runtime_config=runtime_config,
            thread_name=normalized_thread_name,
            ctx=ctx,
        ):
            return False

    if _abort_requested(active_stop):
        _update_abort_status(ctx, normalized_thread_name)
        return False

    if not bool(getattr(runtime_config, "submit_enabled", True)):
        try:
            ctx.update_thread_status(normalized_thread_name, "单测完成", running=False)
        except Exception:
            logging.info("更新线程状态失败：单测完成", exc_info=True)
        return True

    try:
        ctx.update_thread_status(normalized_thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新线程状态失败：提交中", exc_info=True)
    await submit(driver, ctx=ctx, stop_signal=active_stop)
    try:
        ctx.update_thread_status(normalized_thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新线程状态失败：等待结果确认", exc_info=True)
    return True


async def brush_wjx(
    driver: BrowserDriver,
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Optional[Any],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    del config
    return await brush(
        driver,
        ctx,
        stop_signal=stop_signal,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    )
