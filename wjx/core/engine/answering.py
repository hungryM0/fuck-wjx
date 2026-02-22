"""答题核心逻辑 - 按配置策略自动填写问卷"""
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from wjx.core.task_context import TaskContext
from wjx.core.engine.dom_helpers import (
    _count_choice_inputs_driver,
    _driver_question_looks_like_description,
    _driver_question_looks_like_rating,
    _driver_question_looks_like_reorder,
)
from wjx.core.engine.full_simulation import (
    _build_per_question_delay_plan,
    _calculate_full_simulation_run_target,
    _full_simulation_active,
    _simulate_answer_duration_delay,
)
from wjx.core.engine.navigation import _click_next_page_button, _human_scroll_after_question
from wjx.core.engine.question_detection import detect
from wjx.core.engine.runtime_control import _is_fast_mode, _sleep_with_stop
from wjx.core.engine.submission import submit
from wjx.core.persona.context import reset_context as _reset_answer_context
from wjx.core.persona.generator import generate_persona, reset_persona, set_current_persona
from wjx.core.questions.types.dropdown import dropdown as _dropdown_impl
from wjx.core.questions.types.matrix import matrix as _matrix_impl
from wjx.core.questions.types.multiple import multiple as _multiple_impl
from wjx.core.questions.types.reorder import reorder as _reorder_impl
from wjx.core.questions.types.scale import scale as _scale_impl
from wjx.core.questions.types.score import score as _score_impl
from wjx.core.questions.types.single import single as _single_impl
from wjx.core.questions.types.slider import slider as _slider_impl, _resolve_slider_score
from wjx.core.questions.types.text import (
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    driver_question_is_location as _driver_question_is_location,
    text as _text_impl,
)
from wjx.core.questions.consistency import reset_consistency_context
from wjx.core.questions.tendency import reset_tendency
from wjx.core.survey.parser import _should_mark_as_multi_text, _should_treat_question_as_text_like
from wjx.network.browser import BrowserDriver, By, NoSuchElementException


# ---------------------------------------------------------------------------
# 策略模式题型分发器
# ---------------------------------------------------------------------------

class _QuestionDispatcher:
    """题型分发器 - 策略模式实现。

    每种题型对应一个 callable，签名为:
        handler(driver, question_num, type_index, ctx) -> Optional[int]
    返回值：
        - None   : 按验，计数器 += 1
        - int    : 直接用返回值覆盖计数器（矩阵题）
        - False  : 是一个哨兵标识（不支持/跳过）
    """

    #: type_code -> (index_key, handler)
    #  index_key: 在 _indices 字典中的键名
    _REGISTRY: Dict[str, Tuple[str, Any]] = {}

    def __init__(self) -> None:
        self._build_registry()

    def _build_registry(self) -> None:
        """(re)build 注册表。"""
        self._REGISTRY = {
            # type_code -> (index_key, handler_fn)
            # handler_fn signature: (driver, q_num, index, ctx) -> int | None
            "3":  ("single",   self._handle_single),
            "4":  ("multiple", self._handle_multiple),
            "5":  ("scale",    self._handle_scale),
            "6":  ("matrix",   self._handle_matrix),
            "7":  ("dropdown", self._handle_dropdown),
            "8":  ("slider",   self._handle_slider),
        }

    # -- 各题型处理器 --------------------------------------------------

    def _handle_single(self, driver, q_num, idx, ctx: TaskContext):
        _single_impl(driver, q_num, idx, ctx.single_prob, ctx.single_option_fill_texts)

    def _handle_multiple(self, driver, q_num, idx, ctx: TaskContext):
        _multiple_impl(driver, q_num, idx, ctx.multiple_prob, ctx.multiple_option_fill_texts)

    def _handle_scale(self, driver, q_num, idx, ctx: TaskContext, question_div=None):
        dim = ctx.question_dimension_map.get(q_num)
        is_rev = ctx.question_reverse_map.get(q_num, False)
        if question_div is not None and _driver_question_looks_like_rating(question_div):
            _score_impl(driver, q_num, idx, ctx.scale_prob, dimension=dim, is_reverse=is_rev)
        else:
            _scale_impl(driver, q_num, idx, ctx.scale_prob, dimension=dim, is_reverse=is_rev)

    def _handle_matrix(self, driver, q_num, idx, ctx: TaskContext):
        dim = ctx.question_dimension_map.get(q_num)
        is_rev = ctx.question_reverse_map.get(q_num, False)
        return _matrix_impl(driver, q_num, idx, ctx.matrix_prob, dimension=dim, is_reverse=is_rev)

    def _handle_dropdown(self, driver, q_num, idx, ctx: TaskContext):
        _dropdown_impl(driver, q_num, idx, ctx.droplist_prob, ctx.droplist_option_fill_texts)

    def _handle_slider(self, driver, q_num, idx, ctx: TaskContext):
        slider_score = _resolve_slider_score(idx, ctx.slider_targets)
        _slider_impl(driver, q_num, slider_score)

    def fill(
        self,
        driver: BrowserDriver,
        question_type: str,
        question_num: int,
        question_div,
        config_entry: Optional[Tuple[str, int]],
        indices: Dict[str, int],
        ctx: TaskContext,
    ) -> Optional[bool]:
        """分发题型并填写。

        Args:
            driver: 浏览器驱动
            question_type: HTML type 属性字符串
            question_num: 当前题号
            question_div: 题目 DOM 元素
            config_entry: (type_key, idx) | None
            indices: 各题型当前计数器字典
            ctx: 任务上下文（替代全局 state）

        Returns:
            None  -> 分发就序型题型，计数器 +=1
            int   -> 返回计数器新值（矩阵题）
            False -> 不支持或跳过
        """
        is_reorder = (question_type == "11") or _driver_question_looks_like_reorder(question_div)

        # 排序题
        if is_reorder:
            _reorder_impl(driver, question_num)
            return None

        # 文本题 (type 1/2)
        if question_type in ("1", "2"):
            is_location = _driver_question_is_location(question_div) if question_div is not None else False
            if is_location:
                print(f"第{question_num}题为位置题，暂不支持，已跳过")
                return False
            _idx = config_entry[1] if config_entry and config_entry[0] == "text" else indices.get("text", 0)
            _text_impl(driver, question_num, _idx, ctx.texts, ctx.texts_prob, ctx.text_entry_types, ctx.text_ai_flags, ctx.text_titles)
            indices["text"] = _idx + 1
            return None  # 文本题内部已处理计数，返回 None

        # 常规题型分发
        entry = self._REGISTRY.get(question_type)
        if entry is None:
            return False  # 未知题型

        index_key, handler = entry
        _idx = (
            config_entry[1]
            if config_entry and config_entry[0] in (index_key, "score" if index_key == "scale" else None)
            else indices.get(index_key, 0)
        )

        if question_type == "5":  # scale / score 需要传 question_div
            result = handler(driver, question_num, _idx, ctx, question_div=question_div)
        else:
            result = handler(driver, question_num, _idx, ctx)

        if isinstance(result, int):
            indices[index_key] = result
        else:
            indices[index_key] = _idx + 1
        return None


_dispatcher = _QuestionDispatcher()


def brush(
    driver: BrowserDriver,
    ctx: TaskContext,
    stop_signal: Optional[threading.Event] = None,
) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    # 每份问卷开始前：生成画像 → 重置上下文 → 重置倾向
    # 画像必须在 reset_tendency() 之前设置，因为倾向模块会参考画像的满意度
    persona = generate_persona()
    set_current_persona(persona)
    _reset_answer_context()
    reset_tendency()
    reset_consistency_context(ctx.answer_rules)
    logging.debug("本轮画像：%s", persona.to_description())
    questions_per_page = detect(driver, stop_signal=stop_signal)
    total_question_count = sum(questions_per_page)
    fast_mode = _is_fast_mode(ctx)

    # 各题型计数器统一放入字典，方便 dispatcher 内部修改
    _indices: Dict[str, int] = {
        "single": 0,
        "text": 0,
        "dropdown": 0,
        "multiple": 0,
        "matrix": 0,
        "scale": 0,
        "slider": 0,
    }

    current_question_number = 0
    active_stop = stop_signal or ctx.stop_event
    question_delay_plan: Optional[List[float]] = None
    if _full_simulation_active(ctx) and total_question_count > 0:
        target_seconds = _calculate_full_simulation_run_target(total_question_count)
        question_delay_plan = _build_per_question_delay_plan(total_question_count, target_seconds)
        planned_total = sum(question_delay_plan)
        logging.debug(
            "[Action Log] 时长控制：本次计划总耗时约 %.1f 秒，共 %d 题",
            planned_total,
            total_question_count,
        )

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    if _abort_requested():
        return False

    total_pages = len(questions_per_page)
    for page_index, questions_count in enumerate(questions_per_page):
        for _ in range(1, questions_count + 1):
            if _abort_requested():
                return False
            current_question_number += 1
            if _full_simulation_active(ctx):
                if _sleep_with_stop(active_stop, random.uniform(0.8, 1.5)):
                    return False
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

            # 先读取题型（即使题目不可见也需要，用于维护索引）
            question_type = question_div.get_attribute("type")

            # 检测说明页/阅读材料：有 type 属性但无可交互控件
            if question_type is None:
                logging.debug("跳过第%d题（type 属性为空）", current_question_number)
                continue
            if _driver_question_looks_like_description(question_div, question_type):
                logging.debug("跳过第%d题（说明页/阅读材料，type=%s）", current_question_number, question_type)
                continue

            if not question_visible:
                logging.debug("跳过第%d题（未显示，type=%s）", current_question_number, question_type)
                continue

            # 通过配置映射表查找当前题号在对应题型概率列表中的正确索引
            _config_entry = ctx.question_config_index_map.get(current_question_number)

            # ── 策略模式分发 ─────────────────────────────────────────
            dispatch_result = _dispatcher.fill(
                driver=driver,
                question_type=question_type,
                question_num=current_question_number,
                question_div=question_div,
                config_entry=_config_entry,
                indices=_indices,
                ctx=ctx,
            )

            if dispatch_result is False:
                # 未知题型处理：尝试选择题 / 填空题
                handled = False
                if question_div is not None:
                    checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
                    if checkbox_count or radio_count:
                        if checkbox_count >= radio_count:
                            _multiple_impl(driver, current_question_number, _indices["multiple"], ctx.multiple_prob, ctx.multiple_option_fill_texts)
                            _indices["multiple"] += 1
                        else:
                            _single_impl(driver, current_question_number, _indices["single"], ctx.single_prob, ctx.single_option_fill_texts)
                            _indices["single"] += 1
                        handled = True

                if not handled:
                    option_count = 0
                    if question_div is not None:
                        try:
                            option_elements = question_div.find_elements(By.CSS_SELECTOR, ".ui-controlgroup > div")
                            option_count = len(option_elements)
                        except Exception:
                            option_count = 0
                    text_input_count = _count_visible_text_inputs_driver(question_div) if question_div is not None else 0
                    is_location_q = _driver_question_is_location(question_div) if question_div is not None else False
                    is_multi_text_question = _should_mark_as_multi_text(
                        question_type, option_count, text_input_count, is_location_q
                    )
                    is_text_like_question = _should_treat_question_as_text_like(
                        question_type, option_count, text_input_count
                    )

                    if is_text_like_question:
                        _text_impl(
                            driver,
                            current_question_number,
                            _indices["text"],
                            ctx.texts,
                            ctx.texts_prob,
                            ctx.text_entry_types,
                            ctx.text_ai_flags,
                            ctx.text_titles,
                        )
                        _indices["text"] += 1
                        print(
                            f"第{current_question_number}题识别为"
                            f"{'多项填空' if is_multi_text_question else '填空'}，已按填空题处理"
                        )
                    else:
                        print(f"第{current_question_number}题为不支持类型(type={question_type})")

        if _full_simulation_active(ctx):
            _human_scroll_after_question(driver)
        if (
            question_delay_plan
            and current_question_number < total_question_count
        ):
            plan_index = min(current_question_number - 1, len(question_delay_plan) - 1)
            delay_seconds = question_delay_plan[plan_index] if plan_index >= 0 else 0.0
            if delay_seconds > 0.01:
                if active_stop:
                    if active_stop.wait(delay_seconds):
                        return False
                else:
                    time.sleep(delay_seconds)
        if _abort_requested():
            return False
        buffer_delay = 0.0 if fast_mode else 0.5
        if buffer_delay > 0:
            if active_stop:
                if active_stop.wait(buffer_delay):
                    return False
            else:
                time.sleep(buffer_delay)
        is_last_page = (page_index == total_pages - 1)
        if is_last_page:
            if _simulate_answer_duration_delay(ctx, active_stop):
                return False
            if _abort_requested():
                return False
            # 最后一页直接跳出循环，由后续的 submit() 处理提交
            break
        clicked = _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("Next page button not found")
        click_delay = 0.0 if fast_mode else 0.5
        if click_delay > 0:
            if active_stop:
                if active_stop.wait(click_delay):
                    return False
            else:
                time.sleep(click_delay)
    if _abort_requested():
        reset_persona()
        return False
    submit(driver, ctx=ctx, stop_signal=active_stop)
    reset_persona()
    return True
