"""问卷星运行时题型分发。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from software.core.ai.runtime import extract_question_title_from_dom
from software.core.engine.dom_helpers import (
    _count_choice_inputs_driver,
    _driver_question_looks_like_rating,
    _driver_question_looks_like_reorder,
    _driver_question_looks_like_slider_matrix,
)
from software.core.questions.utils import _should_treat_question_as_text_like
from software.core.reverse_fill.runtime import resolve_current_reverse_fill_answer
from software.core.task import ExecutionState
from software.network.browser import BrowserDriver
from wjx.provider.questions.dropdown import dropdown as _dropdown_impl
from wjx.provider.questions.matrix import matrix as _matrix_impl
from wjx.provider.questions.multiple import multiple as _multiple_impl
from wjx.provider.questions.reorder import reorder as _reorder_impl
from wjx.provider.questions.scale import scale as _scale_impl
from wjx.provider.questions.score import score as _score_impl
from wjx.provider.questions.single import single as _single_impl
from wjx.provider.questions.slider import slider as _slider_impl, _resolve_slider_score
from wjx.provider.questions.text import (
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    driver_question_is_location as _driver_question_is_location,
    text as _text_impl,
)

QuestionHandler = Callable[..., Optional[int]]


@dataclass(frozen=True)
class _QuestionHandlerSpec:
    index_key: str
    handler: QuestionHandler
    config_aliases: Tuple[str, ...] = ()
    needs_question_div: bool = False
    needs_psycho_plan: bool = False


def _question_title_for_log(driver: BrowserDriver, question_num: int, question_div) -> str:
    try:
        title = extract_question_title_from_dom(driver, question_num)
    except Exception:
        title = ""
    if title:
        return title
    if question_div is None:
        return ""
    try:
        raw_text = str(question_div.text or "").strip()
    except Exception:
        raw_text = ""
    if not raw_text:
        return ""
    compact = " ".join(raw_text.split())
    return compact[:60] + "..." if len(compact) > 60 else compact


def _should_advance_reverse_fill_index(
    config_entry: Optional[Tuple[str, int]],
    index_key: str,
    config_aliases: Tuple[str, ...],
    reverse_fill_answer: Any,
) -> bool:
    if reverse_fill_answer is None:
        return True
    if config_entry and config_entry[0] in (index_key, *config_aliases):
        return True
    return False


class _QuestionDispatcher:
    """题型分发器。"""

    def __init__(self) -> None:
        self._registry: Dict[str, _QuestionHandlerSpec] = {}
        self._lock = threading.Lock()
        self._register_defaults()

    def register(
        self,
        question_type: str,
        *,
        index_key: str,
        handler: QuestionHandler,
        config_aliases: Tuple[str, ...] = (),
        needs_question_div: bool = False,
        needs_psycho_plan: bool = False,
    ) -> None:
        with self._lock:
            self._registry[str(question_type)] = _QuestionHandlerSpec(
                index_key=index_key,
                handler=handler,
                config_aliases=tuple(config_aliases),
                needs_question_div=bool(needs_question_div),
                needs_psycho_plan=bool(needs_psycho_plan),
            )

    def _register_defaults(self) -> None:
        self.register("3", index_key="single", handler=self._handle_single)
        self.register("4", index_key="multiple", handler=self._handle_multiple)
        self.register(
            "5",
            index_key="scale",
            handler=self._handle_scale,
            config_aliases=("score",),
            needs_question_div=True,
            needs_psycho_plan=True,
        )
        self.register("6", index_key="matrix", handler=self._handle_matrix, needs_psycho_plan=True)
        self.register("9", index_key="matrix", handler=self._handle_matrix, needs_psycho_plan=True)
        self.register("7", index_key="dropdown", handler=self._handle_dropdown, needs_psycho_plan=True)
        self.register("8", index_key="slider", handler=self._handle_slider)

    def _handle_single(self, driver, q_num, idx, ctx: ExecutionState):
        config = ctx.config
        _single_impl(
            driver,
            q_num,
            idx,
            config.single_prob,
            config.single_option_fill_texts,
            config.single_attached_option_selects,
            task_ctx=ctx,
        )

    def _handle_multiple(self, driver, q_num, idx, ctx: ExecutionState):
        config = ctx.config
        _multiple_impl(driver, q_num, idx, config.multiple_prob, config.multiple_option_fill_texts, task_ctx=ctx)

    def _handle_scale(self, driver, q_num, idx, ctx: ExecutionState, question_div=None, psycho_plan=None):
        config = ctx.config
        dim = config.question_dimension_map.get(q_num)
        if question_div is not None and _driver_question_looks_like_rating(question_div):
            _score_impl(
                driver,
                q_num,
                idx,
                config.scale_prob,
                dimension=dim,
                psycho_plan=psycho_plan,
                question_index=q_num,
                task_ctx=ctx,
            )
        else:
            _scale_impl(
                driver,
                q_num,
                idx,
                config.scale_prob,
                dimension=dim,
                psycho_plan=psycho_plan,
                question_index=q_num,
                task_ctx=ctx,
            )

    def _handle_matrix(self, driver, q_num, idx, ctx: ExecutionState, psycho_plan=None):
        config = ctx.config
        dim = config.question_dimension_map.get(q_num)
        return _matrix_impl(
            driver,
            q_num,
            idx,
            config.matrix_prob,
            dimension=dim,
            psycho_plan=psycho_plan,
            question_index=q_num,
            task_ctx=ctx,
        )

    def _handle_dropdown(self, driver, q_num, idx, ctx: ExecutionState, psycho_plan=None):
        config = ctx.config
        _dropdown_impl(
            driver,
            q_num,
            idx,
            config.droplist_prob,
            config.droplist_option_fill_texts,
            dimension=config.question_dimension_map.get(q_num),
            psycho_plan=psycho_plan,
            question_index=q_num,
            task_ctx=ctx,
        )

    def _handle_slider(self, driver, q_num, idx, ctx: ExecutionState):
        slider_score = _resolve_slider_score(idx, ctx.config.slider_targets)
        _slider_impl(driver, q_num, slider_score)

    def fill(
        self,
        driver: BrowserDriver,
        question_type: str,
        question_num: int,
        question_div,
        config_entry: Optional[Tuple[str, int]],
        indices: Dict[str, int],
        ctx: ExecutionState,
        psycho_plan: Optional[Any] = None,
    ) -> Optional[bool]:
        is_reorder = (question_type == "11") or _driver_question_looks_like_reorder(question_div)
        reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, question_num)

        if is_reorder:
            _reorder_impl(driver, question_num)
            return None

        if question_type in ("1", "2"):
            is_location = _driver_question_is_location(question_div) if question_div is not None else False
            if is_location:
                print(f"第{question_num}题为位置题，暂不支持，已跳过")
                return False
            config = ctx.config
            _idx = config_entry[1] if config_entry and config_entry[0] == "text" else indices.get("text", 0)
            _text_impl(
                driver,
                question_num,
                _idx,
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
            if _should_advance_reverse_fill_index(config_entry, "text", (), reverse_fill_answer):
                indices["text"] = _idx + 1
            return None

        if question_div is not None and config_entry and config_entry[0] == "text":
            checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
            option_count = checkbox_count + radio_count
            text_input_count = _count_visible_text_inputs_driver(question_div)
            has_slider_matrix = _driver_question_looks_like_slider_matrix(question_div)
            if _should_treat_question_as_text_like(
                question_type,
                option_count,
                text_input_count,
                has_slider_matrix=has_slider_matrix,
            ):
                config = ctx.config
                sequential_idx = int(indices.get("text", 0) or 0)
                mapped_idx: Optional[int] = None
                try:
                    mapped_idx = max(0, int(config_entry[1]))
                except Exception:
                    mapped_idx = None
                if mapped_idx is not None and mapped_idx < sequential_idx:
                    logging.warning(
                        "文本题索引回拨已拦截：题号=%s 类型=%s 映射索引=%s 当前顺序索引=%s，继续沿用顺序索引",
                        question_num,
                        question_type,
                        mapped_idx,
                        sequential_idx,
                    )
                _idx = sequential_idx if mapped_idx is None or mapped_idx < sequential_idx else mapped_idx
                _text_impl(
                    driver,
                    question_num,
                    _idx,
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
                if _should_advance_reverse_fill_index(config_entry, "text", (), reverse_fill_answer):
                    indices["text"] = _idx + 1
                return None

        if _driver_question_looks_like_slider_matrix(question_div):
            sequential_idx = int(indices.get("matrix", 0) or 0)
            mapped_idx: Optional[int] = None
            if config_entry and config_entry[0] == "matrix":
                try:
                    mapped_idx = max(0, int(config_entry[1]))
                except Exception:
                    mapped_idx = None
            _idx = mapped_idx if mapped_idx is not None and mapped_idx >= sequential_idx else sequential_idx
            result = self._handle_matrix(driver, question_num, _idx, ctx, psycho_plan=psycho_plan)
            if _should_advance_reverse_fill_index(config_entry, "matrix", (), reverse_fill_answer):
                indices["matrix"] = result if isinstance(result, int) else (_idx + 1)
            return None

        with self._lock:
            spec = self._registry.get(question_type)
        if spec is None:
            return False

        index_key = spec.index_key
        sequential_idx = int(indices.get(index_key, 0) or 0)
        mapped_idx: Optional[int] = None
        if config_entry and config_entry[0] in (index_key, *spec.config_aliases):
            try:
                mapped_idx = max(0, int(config_entry[1]))
            except Exception:
                mapped_idx = None
        if mapped_idx is not None and mapped_idx < sequential_idx:
            logging.warning(
                "题型索引回拨已拦截：题号=%s 类型=%s 映射索引=%s 当前顺序索引=%s，继续沿用顺序索引",
                question_num,
                question_type,
                mapped_idx,
                sequential_idx,
            )
            _idx = sequential_idx
        else:
            _idx = mapped_idx if mapped_idx is not None else sequential_idx

        handler_kwargs: Dict[str, Any] = {}
        if spec.needs_question_div:
            handler_kwargs["question_div"] = question_div
        if spec.needs_psycho_plan:
            handler_kwargs["psycho_plan"] = psycho_plan
        result = spec.handler(driver, question_num, _idx, ctx, **handler_kwargs)

        if _should_advance_reverse_fill_index(config_entry, index_key, spec.config_aliases, reverse_fill_answer):
            if isinstance(result, int):
                indices[index_key] = result
            else:
                indices[index_key] = _idx + 1
        return None


_dispatcher = _QuestionDispatcher()


__all__ = [
    "_QuestionDispatcher",
    "_dispatcher",
    "_question_title_for_log",
]
