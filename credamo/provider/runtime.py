"""Credamo 见数问卷运行时作答主流程。"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.engine.async_wait import sleep_or_stop
from software.core.modes.duration_control import has_configured_answer_duration, simulate_answer_duration_delay
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from software.providers.common import make_provider_question_key
from credamo.provider.runtime_state import get_credamo_runtime_state

from . import runtime_answerers as _runtime_answerers
from . import runtime_dom as _runtime_dom

_DOM_CLICK_SUBMIT = _runtime_dom._click_submit
_DOM_UNANSWERED_QUESTION_ROOTS = _runtime_dom._unanswered_question_roots
_DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS = _runtime_dom._wait_for_dynamic_question_roots
_DOM_WAIT_FOR_PAGE_CHANGE = _runtime_dom._wait_for_page_change
_DOM_WAIT_FOR_QUESTION_ROOTS = _runtime_dom._wait_for_question_roots
_ANSWER_DROPDOWN = _runtime_answerers._answer_dropdown
_ANSWER_MATRIX = _runtime_answerers._answer_matrix
_ANSWER_MULTIPLE = _runtime_answerers._answer_multiple
_ANSWER_ORDER = _runtime_answerers._answer_order
_ANSWER_SCALE = _runtime_answerers._answer_scale
_ANSWER_SINGLE_LIKE = _runtime_answerers._answer_single_like
_ANSWER_TEXT = _runtime_answerers._answer_text
_APPLY_BATCH_ANSWER_ACTIONS = _runtime_answerers.apply_answer_actions
_BUILD_BATCH_ANSWER_ACTION = _runtime_answerers.build_answer_action

_abort_requested = _runtime_dom._abort_requested
_click_element = _runtime_dom._click_element
_click_navigation = _runtime_dom._click_navigation
_click_submit_once = _runtime_dom._click_submit_once
_collect_question_root_snapshot = _runtime_dom._collect_question_root_snapshot
_element_text = _runtime_dom._element_text
_input_value = _runtime_dom._input_value
_is_checked = _runtime_dom._is_checked
_has_answerable_question_roots = _runtime_dom._has_answerable_question_roots
_locator_is_visible = _runtime_dom._locator_is_visible
_looks_like_loading_shell = _runtime_dom._looks_like_loading_shell
_navigation_action = _runtime_dom._navigation_action
_option_click_targets = _runtime_dom._option_click_targets
_option_inputs = _runtime_dom._option_inputs
_page = _runtime_dom._page
_page_loading_snapshot = _runtime_dom._page_loading_snapshot
_question_kind_from_root = _runtime_dom._question_kind_from_root
_question_number_from_root = _runtime_dom._question_number_from_root
_question_answer_state = _runtime_dom._question_answer_state
_question_roots = _runtime_dom._question_roots
_question_signature = _runtime_dom._question_signature
_question_title_text = _runtime_dom._question_title_text
_root_text = _runtime_dom._root_text
_text_inputs = _runtime_dom._text_inputs
_resolve_forced_choice_index = _runtime_answerers._resolve_forced_choice_index
_DEFAULT_DOM_CLICK_SUBMIT = _runtime_dom._click_submit
_DEFAULT_DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS = _runtime_dom._wait_for_dynamic_question_roots
_DEFAULT_DOM_WAIT_FOR_PAGE_CHANGE = _runtime_dom._wait_for_page_change
_DEFAULT_DOM_WAIT_FOR_QUESTION_ROOTS = _runtime_dom._wait_for_question_roots

_CREDAMO_BATCH_ENTRY_TYPES = {"single", "multiple", "scale", "score", "matrix", "text", "multi_text"}


async def _provider_page_id_from_root(page: Any, root: Any, fallback_page_id: Any = None) -> str:
    provider_page_id = ""
    try:
        provider_page_id = str(
            await page.evaluate(
                """
                (el) => {
                  const current = el.closest('.answer-page');
                  const pageNode = current || document.querySelector('.answer-page');
                  const candidates = [
                    pageNode?.getAttribute('data-page'),
                    pageNode?.getAttribute('data-page-id'),
                    pageNode?.getAttribute('page'),
                    document.querySelector('.answer-page')?.getAttribute('data-page'),
                  ];
                  for (const value of candidates) {
                    const text = String(value || '').trim();
                    if (text) return text;
                  }
                  return '';
                }
                """,
                root,
            )
            or ""
        ).strip()
    except Exception:
        provider_page_id = ""
    normalized_page_id = provider_page_id if provider_page_id.isdigit() else ""
    if normalized_page_id:
        return normalized_page_id
    try:
        resolved_fallback_page_id = int(fallback_page_id or 0)
    except Exception:
        resolved_fallback_page_id = 0
    return str(resolved_fallback_page_id) if resolved_fallback_page_id > 0 else ""


async def _provider_question_key_from_root(page: Any, root: Any, fallback_page_id: Any = None) -> str:
    provider_page_id = await _provider_page_id_from_root(page, root, fallback_page_id=fallback_page_id)
    try:
        provider_question_id = str(await root.get_attribute("data-id") or await root.get_attribute("id") or "").strip()
    except Exception:
        provider_question_id = ""
    return make_provider_question_key("credamo", provider_page_id, provider_question_id)


async def _resolve_config_binding(
    page: Any,
    root: Any,
    question_num: int,
    config: ExecutionConfig,
    *,
    fallback_page_id: Any = None,
) -> tuple[int, Optional[tuple[str, int]], Any]:
    provider_key = await _provider_question_key_from_root(page, root, fallback_page_id=fallback_page_id)
    provider_map = getattr(config, "provider_question_config_index_map", {}) or {}
    if provider_key:
        config_entry = provider_map.get(provider_key)
        if config_entry is not None:
            question_meta = (getattr(config, "provider_question_metadata_map", {}) or {}).get(provider_key)
            try:
                resolved_num = int(getattr(question_meta, "num", question_num) or question_num)
            except Exception:
                resolved_num = question_num
            return resolved_num, config_entry, question_meta
    config_entry = config.question_config_index_map.get(question_num)
    question_meta = config.questions_metadata.get(question_num) if hasattr(config, "questions_metadata") else None
    return question_num, config_entry, question_meta


def _sync_runtime_dom_patch_points() -> None:
    """兼容旧测试入口；运行时不再回写底层模块全局状态。"""
    return None


def _sync_runtime_answerer_patch_points() -> None:
    """兼容旧测试入口；运行时不再回写底层模块全局状态。"""
    return None


async def _wait_for_question_roots(page: Any, stop_signal: Any, **kwargs: Any):
    if _DOM_WAIT_FOR_QUESTION_ROOTS is not _DEFAULT_DOM_WAIT_FOR_QUESTION_ROOTS:
        return await _DOM_WAIT_FOR_QUESTION_ROOTS(page, stop_signal, **kwargs)
    timeout_ms = int(kwargs.get("timeout_ms") or getattr(_runtime_dom, "_CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS", 6000))
    loading_shell_extra_timeout_ms = int(
        kwargs.get("loading_shell_extra_timeout_ms")
        or getattr(_runtime_dom, "_CREDAMO_LOADING_SHELL_EXTRA_WAIT_TIMEOUT_MS", 4000)
    )
    poll_seconds = float(getattr(_runtime_dom, "_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS", 0.15))
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    last_roots: list[Any] = []
    loading_shell_retry_used = False
    while not _abort_requested(stop_signal):
        try:
            last_roots = await _question_roots(page)
        except Exception:
            logging.info("Credamo 等待题目加载时读取页面失败", exc_info=True)
            last_roots = []
        if last_roots:
            return last_roots
        if time.monotonic() >= deadline:
            title, body_text = await _page_loading_snapshot(page)
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
        await sleep_or_stop(stop_signal, poll_seconds)
    return last_roots


async def _unanswered_question_roots(page: Any, roots: list[Any], answered_keys: set[str], **kwargs: Any):
    return await _DOM_UNANSWERED_QUESTION_ROOTS(page, roots, answered_keys, **kwargs)


async def _wait_for_dynamic_question_roots(page: Any, answered_keys: set[str], stop_signal: Any, **kwargs: Any):
    if _DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS is not _DEFAULT_DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS:
        return await _DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS(page, answered_keys, stop_signal, **kwargs)
    timeout_ms = int(kwargs.get("timeout_ms") or getattr(_runtime_dom, "_CREDAMO_DYNAMIC_REVEAL_TIMEOUT_MS", 800))
    fallback_start = int(kwargs.get("fallback_start") or 0)
    poll_seconds = float(getattr(_runtime_dom, "_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS", 0.15))
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    latest_roots: list[Any] = []
    while not _abort_requested(stop_signal):
        try:
            latest_roots = await _question_roots(page)
        except Exception:
            logging.info("Credamo 等待动态题目显示时读取页面失败", exc_info=True)
            latest_roots = []
        if await _unanswered_question_roots(page, latest_roots, answered_keys, fallback_start=fallback_start):
            return latest_roots
        if time.monotonic() >= deadline:
            return latest_roots
        await sleep_or_stop(stop_signal, poll_seconds)
    return latest_roots


async def _wait_for_page_change(page: Any, previous_signature: Any, stop_signal: Any, **kwargs: Any) -> bool:
    if _DOM_WAIT_FOR_PAGE_CHANGE is not _DEFAULT_DOM_WAIT_FOR_PAGE_CHANGE:
        return await _DOM_WAIT_FOR_PAGE_CHANGE(page, previous_signature, stop_signal, **kwargs)
    timeout_ms = int(kwargs.get("timeout_ms") or getattr(_runtime_dom, "_CREDAMO_PAGE_TRANSITION_TIMEOUT_MS", 5000))
    poll_seconds = float(getattr(_runtime_dom, "_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS", 0.15))
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        current_signature = await _question_signature(page)
        if current_signature and current_signature != previous_signature:
            return True
        if time.monotonic() >= deadline:
            return False
        await sleep_or_stop(stop_signal, poll_seconds)
    return False


async def _click_submit(page: Any, stop_signal: Any = None, **kwargs: Any) -> bool:
    if _DOM_CLICK_SUBMIT is not _DEFAULT_DOM_CLICK_SUBMIT:
        return await _DOM_CLICK_SUBMIT(page, stop_signal, **kwargs)
    timeout_ms = int(kwargs.get("timeout_ms") or getattr(_runtime_dom, "_CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS", 6000))
    poll_seconds = float(getattr(_runtime_dom, "_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS", 0.15))
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        if await _click_submit_once(page):
            return True
        if time.monotonic() >= deadline:
            return False
        await sleep_or_stop(stop_signal, poll_seconds)
    return False


async def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    return await _ANSWER_SINGLE_LIKE(page, root, weights, option_count)


async def _answer_multiple(
    page: Any,
    root: Any,
    weights: Any,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> bool:
    return await _ANSWER_MULTIPLE(
        page,
        root,
        weights,
        min_limit=min_limit,
        max_limit=max_limit,
    )


async def _answer_text(
    root: Any,
    text_config: Any,
    text_probabilities: Any = None,
    *,
    entry_type: str = "text",
    blank_modes: Optional[list[Any]] = None,
    blank_int_ranges: Optional[list[Any]] = None,
) -> bool:
    return await _ANSWER_TEXT(
        root,
        text_config,
        text_probabilities,
        entry_type=entry_type,
        blank_modes=blank_modes,
        blank_int_ranges=blank_int_ranges,
    )


async def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    return await _ANSWER_DROPDOWN(page, root, weights)


async def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    return await _ANSWER_SCALE(page, root, weights)


async def _answer_matrix(page: Any, root: Any, weights: Any, start_index: int = 0) -> bool:
    return await _ANSWER_MATRIX(page, root, weights, start_index)


async def _answer_order(page: Any, root: Any) -> bool:
    return await _ANSWER_ORDER(page, root)


async def _attempt_answer_current_root(
    page: Any,
    root: Any,
    question_num: int,
    config: ExecutionConfig,
    *,
    fallback_page_id: Any = None,
) -> bool:
    resolved_question_num, config_entry, question_meta = await _resolve_config_binding(
        page,
        root,
        question_num,
        config,
        fallback_page_id=fallback_page_id,
    )
    if config_entry is None:
        fallback_kind = await _question_kind_from_root(page, root)
        logging.info("Credamo 第%s题未匹配到配置，页面题型=%s，题面=%s", resolved_question_num, fallback_kind, await _root_text(page, root))
        return False

    entry_type, config_index = config_entry
    action_attempted = False
    if entry_type == "single":
        weights = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
        action_attempted = bool(await _answer_single_like(page, root, weights, 0))
    elif entry_type in {"scale", "score"}:
        weights = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
        action_attempted = bool(await _answer_scale(page, root, weights))
    elif entry_type == "matrix":
        row_count = max(1, int(getattr(question_meta, "rows", 1) or 1))
        row_weights = []
        for row_offset in range(row_count):
            matrix_index = config_index + row_offset
            row_weights.append(config.matrix_prob[matrix_index] if matrix_index < len(config.matrix_prob) else -1)
        action_attempted = bool(await _answer_matrix(page, root, row_weights, config_index))
    elif entry_type == "dropdown":
        weights = config.droplist_prob[config_index] if config_index < len(config.droplist_prob) else -1
        action_attempted = bool(await _answer_dropdown(page, root, weights))
    elif entry_type == "multiple":
        weights = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else []
        min_limit = getattr(question_meta, "multi_min_limit", None) if question_meta is not None else None
        max_limit = getattr(question_meta, "multi_max_limit", None) if question_meta is not None else None
        action_attempted = bool(
            await _answer_multiple(
                page,
                root,
                weights,
                min_limit=min_limit,
                max_limit=max_limit,
            )
        )
    elif entry_type == "order":
        action_attempted = bool(await _answer_order(page, root))
    elif entry_type in {"text", "multi_text"}:
        text_config = config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT]
        texts_prob = list(getattr(config, "texts_prob", []) or [])
        text_probabilities = texts_prob[config_index] if config_index < len(texts_prob) else [1.0]
        multi_text_blank_modes = list(getattr(config, "multi_text_blank_modes", []) or [])
        multi_text_blank_ranges = list(getattr(config, "multi_text_blank_int_ranges", []) or [])
        action_attempted = bool(
            await _answer_text(
                root,
                text_config,
                text_probabilities,
                entry_type=entry_type,
                blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
                blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
            )
        )
    else:
        logging.info("Credamo 第%s题暂未接入题型：%s", resolved_question_num, entry_type)
        return False

    answer_state = await _question_answer_state(page, root, kind=entry_type)
    if answer_state is False:
        logging.warning("Credamo 第%s题点击后仍未答上，题型=%s", resolved_question_num, entry_type)
        return False
    if answer_state is True:
        return True
    return action_attempted


async def _answer_pending_roots_batch(
    page: Any,
    roots: list[Any],
    pending_roots: list[tuple[Any, int, str]],
    config: ExecutionConfig,
    *,
    page_index: int,
) -> set[str]:
    if not pending_roots:
        return set()
    root_index_by_id = {id(root): index for index, root in enumerate(roots)}
    actions: list[Any] = []
    action_key_by_num: dict[int, str] = {}
    for root, question_num, question_key in pending_roots:
        root_index = root_index_by_id.get(id(root))
        if root_index is None:
            continue
        resolved_question_num, config_entry, question_meta = await _resolve_config_binding(
            page,
            root,
            question_num,
            config,
            fallback_page_id=page_index,
        )
        if config_entry is None:
            continue
        entry_type, config_index = config_entry
        if str(entry_type or "").strip() not in _CREDAMO_BATCH_ENTRY_TYPES:
            continue
        action = _BUILD_BATCH_ANSWER_ACTION(
            root_index=root_index,
            question_num=resolved_question_num,
            entry_type=entry_type,
            config_index=config_index,
            config=config,
            question_meta=question_meta,
        )
        if action is None:
            continue
        actions.append(action)
        action_key_by_num[int(resolved_question_num)] = question_key
    if not actions:
        return set()
    result = await _APPLY_BATCH_ANSWER_ACTIONS(page, actions)
    answered_keys: set[str] = set()
    for question_num in result.applied:
        question_key = action_key_by_num.get(int(question_num))
        if question_key:
            answered_keys.add(question_key)
    return answered_keys


async def refill_required_questions_on_current_page(
    driver: BrowserDriver,
    config: ExecutionConfig,
    *,
    question_numbers: list[int],
    thread_name: str,
    state: Optional[ExecutionState] = None,
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

    page = await _page(driver)
    runtime_state = get_credamo_runtime_state(driver)
    fallback_page_id = getattr(runtime_state, "page_index", 0)
    roots = await _question_roots(page)
    if not roots:
        return 0
    root_by_number: dict[int, Any] = {}
    for local_index, root in enumerate(roots, start=1):
        question_num = await _question_number_from_root(page, root, local_index)
        if question_num > 0 and question_num not in root_by_number:
            root_by_number[question_num] = root

    filled_count = 0
    for question_num in normalized_numbers:
        root = root_by_number.get(question_num)
        if root is None:
            continue
        resolved_question_num, _config_entry, _question_meta = await _resolve_config_binding(
            page,
            root,
            question_num,
            config,
            fallback_page_id=fallback_page_id,
        )
        if state is not None:
            try:
                state.update_thread_status(thread_name or "Worker-?", f"补答第{resolved_question_num}题", running=True)
            except Exception:
                logging.info("更新 Credamo 线程状态失败：补答第%s题", resolved_question_num, exc_info=True)
        if await _attempt_answer_current_root(
            page,
            root,
            question_num,
            config,
            fallback_page_id=fallback_page_id,
        ):
            filled_count += 1
    return filled_count


async def brush_credamo(
    driver: BrowserDriver,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Optional[Any],
    thread_name: str,
    psycho_plan: Optional[Any] = None,
) -> bool:
    active_stop = stop_signal or state.stop_event
    page = await _page(driver)
    total_steps = max(1, len(config.question_config_index_map))
    answered_steps = 0
    page_index = 0
    runtime_state = get_credamo_runtime_state(driver)
    runtime_state.psycho_plan = psycho_plan
    try:
        state.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化 Credamo 线程进度失败", exc_info=True)

    while not _abort_requested(active_stop):
        page_index += 1
        runtime_state.page_index = page_index
        roots = await _wait_for_question_roots(page, active_stop)
        if not roots:
            raise RuntimeError("Credamo 当前页未识别到题目")
        if not await _has_answerable_question_roots(page, roots):
            navigation_action = await _navigation_action(page)
            if navigation_action == "next":
                previous_signature = await _question_signature(page)
                runtime_state.last_page_signature = previous_signature
                try:
                    state.update_thread_status(thread_name, "跳过说明页", running=True)
                except Exception:
                    logging.info("更新 Credamo 线程状态失败：跳过说明页", exc_info=True)
                if not await _click_navigation(page, "next"):
                    raise RuntimeError("Credamo 说明页下一页按钮未找到")
                if not await _wait_for_page_change(page, previous_signature, active_stop):
                    raise RuntimeError("Credamo 点击说明页下一页后页面没有变化")
                continue
            raise RuntimeError("Credamo 当前页未识别到可作答题目")

        answered_keys: set[str] = set()
        runtime_state.answered_question_keys = []
        page_fallback_start = answered_steps
        while not _abort_requested(active_stop):
            pending_roots = await _unanswered_question_roots(page, roots, answered_keys, fallback_start=page_fallback_start)
            if not pending_roots:
                break

            batch_answered_keys = await _answer_pending_roots_batch(
                page,
                roots,
                pending_roots,
                config,
                page_index=page_index,
            )
            if batch_answered_keys:
                answered_keys.update(batch_answered_keys)
                runtime_state.answered_question_keys = list(answered_keys)
                answered_steps = min(total_steps, answered_steps + len(batch_answered_keys))

            for root, question_num, question_key in pending_roots:
                if question_key in batch_answered_keys:
                    continue
                if _abort_requested(active_stop):
                    try:
                        state.update_thread_status(thread_name, "已中断", running=False)
                    except Exception:
                        pass
                    return False

                resolved_question_num, config_entry, _question_meta = await _resolve_config_binding(
                    page,
                    root,
                    question_num,
                    config,
                    fallback_page_id=page_index,
                )
                if config_entry is None:
                    continue

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

                answered = await _attempt_answer_current_root(
                    page,
                    root,
                    question_num,
                    config,
                    fallback_page_id=page_index,
                )
                if answered:
                    answered_keys.add(question_key)
                    runtime_state.answered_question_keys = list(answered_keys)
                    answered_steps = min(total_steps, answered_steps + 1)
                await sleep_or_stop(None, random.uniform(0.03, 0.08))

            roots = await _wait_for_dynamic_question_roots(
                page,
                answered_keys,
                active_stop,
                fallback_start=page_fallback_start,
            )
        navigation_action = await _navigation_action(page)
        if navigation_action != "next":
            break
        previous_signature = await _question_signature(page)
        runtime_state.last_page_signature = previous_signature
        try:
            state.update_thread_status(thread_name, "翻到下一页", running=True)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：翻到下一页", exc_info=True)
        if not await _click_navigation(page, "next"):
            raise RuntimeError("Credamo 下一页按钮未找到")
        if not await _wait_for_page_change(page, previous_signature, active_stop):
            raise RuntimeError("Credamo 点击下一页后页面没有变化")

    if has_configured_answer_duration(config.answer_duration_range_seconds):
        try:
            state.update_thread_status(thread_name, "等待时长中", running=True)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：等待时长中", exc_info=True)
    if await simulate_answer_duration_delay(
        active_stop,
        config.answer_duration_range_seconds,
        survey_provider=getattr(config, "survey_provider", ""),
    ):
        return False
    if not bool(getattr(config, "submit_enabled", True)):
        try:
            state.update_thread_status(thread_name, "单测完成", running=False)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：单测完成", exc_info=True)
        return True
    try:
        state.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：提交中", exc_info=True)
    if not await _click_submit(page, active_stop):
        raise RuntimeError("Credamo 提交按钮未找到")
    try:
        state.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：等待结果确认", exc_info=True)
    return True
