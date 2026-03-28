"""答题核心逻辑 - 按配置策略自动填写问卷"""
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from software.core.task import TaskContext
from software.core.engine.dom_helpers import (
    _count_choice_inputs_driver,
    _driver_question_looks_like_description,
    _driver_question_looks_like_rating,
    _driver_question_looks_like_reorder,
)
from software.core.modes.duration_control import simulate_answer_duration_delay
from software.core.engine.navigation import _click_next_page_button, _human_scroll_after_question
from software.core.engine.runtime_control import _is_headless_mode
from software.core.engine.submission import submit
from software.core.persona.context import reset_context as _reset_answer_context
from software.core.persona.generator import generate_persona, reset_persona, set_current_persona
from software.core.questions.types.dropdown import dropdown as _dropdown_impl
from software.core.questions.types.matrix import matrix as _matrix_impl
from software.core.questions.types.multiple import multiple as _multiple_impl
from software.core.questions.types.reorder import reorder as _reorder_impl
from software.core.questions.types.scale import scale as _scale_impl
from software.core.questions.types.score import score as _score_impl
from software.core.questions.types.single import single as _single_impl
from software.core.questions.types.slider import slider as _slider_impl, _resolve_slider_score
from software.core.questions.types.text import (
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    driver_question_is_location as _driver_question_is_location,
    text as _text_impl,
)
from software.core.questions.consistency import reset_consistency_context
from software.core.questions.strict_ratio import is_strict_ratio_question
from software.core.questions.tendency import reset_tendency
from software.core.questions.utils import _should_treat_question_as_text_like
from software.core.psychometrics import build_dimension_psychometric_plan
from software.providers.registry import fill_survey as _fill_provider_survey
from software.core.ai.runtime import extract_question_title_from_dom
from software.network.browser import BrowserDriver, By, NoSuchElementException
from software.app.config import HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY


_PSYCHO_BIAS_CHOICES = {"left", "center", "right"}
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


def _resolve_option_count(probability_config: Any, metadata_fallback: int, default_value: int = 5) -> int:
    """解析心理测量计划所需选项数。"""
    if isinstance(probability_config, list) and probability_config:
        return max(2, len(probability_config))
    if metadata_fallback > 0:
        return max(2, int(metadata_fallback))
    return max(2, int(default_value))


def _infer_bias_from_probabilities(probability_config: Any, option_count: int) -> str:
    """当预设为 custom 时，根据当前权重大致推断 left/center/right。"""
    if not isinstance(probability_config, list) or not probability_config:
        return "center"

    weights: List[float] = []
    for raw in probability_config:
        try:
            weights.append(max(0.0, float(raw)))
        except Exception:
            weights.append(0.0)

    total = sum(weights)
    if total <= 0:
        return "center"

    denom = max(1, option_count - 1)
    weighted_mean = sum(idx * weight for idx, weight in enumerate(weights)) / total
    ratio = weighted_mean / denom
    if ratio <= 0.4:
        return "left"
    if ratio >= 0.6:
        return "right"
    return "center"


def _resolve_bias(raw_bias: Any, probability_config: Any, option_count: int) -> str:
    if isinstance(raw_bias, str):
        normalized = raw_bias.strip().lower()
        if normalized in _PSYCHO_BIAS_CHOICES:
            return normalized
    return _infer_bias_from_probabilities(probability_config, option_count)


def _build_psychometric_plan_for_run(ctx: TaskContext) -> Optional[Any]:
    """根据当前任务配置构建本轮问卷的心理测量作答计划。"""
    grouped_items: Dict[str, List[Tuple[int, str, int, str, Optional[int]]]] = {}

    for question_num in sorted(ctx.question_config_index_map.keys()):
        config_entry = ctx.question_config_index_map.get(question_num)
        if not config_entry:
            continue

        question_type, start_index = config_entry
        dimension = str(ctx.question_dimension_map.get(question_num) or "").strip()
        if not dimension:
            continue
        if is_strict_ratio_question(ctx, question_num):
            continue

        question_meta = ctx.questions_metadata.get(question_num) or {}
        meta_option_count = int(question_meta.get("options") or 0)
        saved_bias = ctx.question_psycho_bias_map.get(question_num, "custom")

        if question_type in ("scale", "score"):
            probability_config = ctx.scale_prob[start_index] if start_index < len(ctx.scale_prob) else -1
            option_count = _resolve_option_count(probability_config, meta_option_count, default_value=5)
            bias = _resolve_bias(saved_bias, probability_config, option_count)
            grouped_items.setdefault(dimension, []).append((question_num, question_type, option_count, bias, None))
            continue

        if question_type == "matrix":
            row_count = int(question_meta.get("rows") or 0)
            if row_count <= 0:
                row_count = 1

            for row_idx in range(row_count):
                matrix_prob_idx = start_index + row_idx
                probability_config = (
                    ctx.matrix_prob[matrix_prob_idx]
                    if matrix_prob_idx < len(ctx.matrix_prob)
                    else -1
                )
                option_count = _resolve_option_count(
                    probability_config,
                    meta_option_count,
                    default_value=max(meta_option_count, 5),
                )
                row_bias = (
                    saved_bias[row_idx]
                    if isinstance(saved_bias, list) and row_idx < len(saved_bias)
                    else saved_bias
                )
                bias = _resolve_bias(row_bias, probability_config, option_count)
                grouped_items.setdefault(dimension, []).append((question_num, "matrix", option_count, bias, row_idx))

    if not grouped_items:
        return None

    try:
        target_alpha = float(getattr(ctx, "psycho_target_alpha", 0.9) or 0.9)
    except Exception:
        target_alpha = 0.9
    target_alpha = max(0.70, min(0.95, target_alpha))

    return build_dimension_psychometric_plan(
        grouped_items=grouped_items,
        target_alpha=target_alpha,
    )


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
        self.register(
            "6",
            index_key="matrix",
            handler=self._handle_matrix,
            needs_psycho_plan=True,
        )
        self.register("7", index_key="dropdown", handler=self._handle_dropdown)
        self.register("8", index_key="slider", handler=self._handle_slider)

    # -- 各题型处理器 --------------------------------------------------

    def _handle_single(self, driver, q_num, idx, ctx: TaskContext):
        _single_impl(
            driver,
            q_num,
            idx,
            ctx.single_prob,
            ctx.single_option_fill_texts,
            ctx.single_attached_option_selects,
            task_ctx=ctx,
        )

    def _handle_multiple(self, driver, q_num, idx, ctx: TaskContext):
        _multiple_impl(driver, q_num, idx, ctx.multiple_prob, ctx.multiple_option_fill_texts, task_ctx=ctx)

    def _handle_scale(self, driver, q_num, idx, ctx: TaskContext, question_div=None, psycho_plan=None):
        dim = ctx.question_dimension_map.get(q_num)
        if question_div is not None and _driver_question_looks_like_rating(question_div):
            _score_impl(
                driver,
                q_num,
                idx,
                ctx.scale_prob,
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
                ctx.scale_prob,
                dimension=dim,
                psycho_plan=psycho_plan,
                question_index=q_num,
                task_ctx=ctx,
            )

    def _handle_matrix(self, driver, q_num, idx, ctx: TaskContext, psycho_plan=None):
        dim = ctx.question_dimension_map.get(q_num)
        return _matrix_impl(
            driver,
            q_num,
            idx,
            ctx.matrix_prob,
            dimension=dim,
            psycho_plan=psycho_plan,
            question_index=q_num,
            task_ctx=ctx,
        )

    def _handle_dropdown(self, driver, q_num, idx, ctx: TaskContext):
        _dropdown_impl(driver, q_num, idx, ctx.droplist_prob, ctx.droplist_option_fill_texts, task_ctx=ctx)

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
        psycho_plan: Optional[Any] = None,
    ) -> Optional[bool]:
        """分发题型并填写。"""
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
            _text_impl(driver, question_num, _idx, ctx.texts, ctx.texts_prob, ctx.text_entry_types, ctx.text_ai_flags, ctx.text_titles, ctx.multi_text_blank_modes, ctx.multi_text_blank_ai_flags, ctx.multi_text_blank_int_ranges)
            indices["text"] = _idx + 1
            return None  # 文本题内部已处理计数，返回 None

        # 常规题型分发
        with self._lock:
            spec = self._registry.get(question_type)
        if spec is None:
            return False  # 未知题型

        index_key = spec.index_key
        _idx = (
            config_entry[1]
            if config_entry and config_entry[0] in (index_key, *spec.config_aliases)
            else indices.get(index_key, 0)
        )

        handler_kwargs: Dict[str, Any] = {}
        if spec.needs_question_div:
            handler_kwargs["question_div"] = question_div
        if spec.needs_psycho_plan:
            handler_kwargs["psycho_plan"] = psycho_plan
        result = spec.handler(driver, question_num, _idx, ctx, **handler_kwargs)

        if isinstance(result, int):
            indices[index_key] = result
        else:
            indices[index_key] = _idx + 1
        return None


_dispatcher = _QuestionDispatcher()


def register_question_handler(
    question_type: str,
    *,
    index_key: str,
    handler: QuestionHandler,
    config_aliases: Tuple[str, ...] = (),
    needs_question_div: bool = False,
    needs_psycho_plan: bool = False,
) -> None:
    """为题型执行注册扩展处理器。"""
    _dispatcher.register(
        question_type,
        index_key=index_key,
        handler=handler,
        config_aliases=config_aliases,
        needs_question_div=needs_question_div,
        needs_psycho_plan=needs_psycho_plan,
    )


def brush(
    driver: BrowserDriver,
    ctx: TaskContext,
    stop_signal: Optional[threading.Event] = None,
    *,
    thread_name: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
    provider_dispatched: bool = False,
    detect_fn: Optional[Callable] = None,
) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    thread_name = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
    if not provider_dispatched:
        try:
            ctx.update_thread_status(thread_name, "识别题目", running=True)
        except Exception:
            logging.info("更新线程状态失败：识别题目", exc_info=True)

        # 每份问卷开始前：生成画像 → 重置上下文 → 重置倾向
        # 画像必须在 reset_tendency() 之前设置，因为倾向模块会参考画像的满意度
        persona = generate_persona()
        set_current_persona(persona)
        _reset_answer_context()
        reset_tendency()
        reset_consistency_context(ctx.answer_rules, list((ctx.questions_metadata or {}).values()))
        if psycho_plan is None:
            psycho_plan = _build_psychometric_plan_for_run(ctx)
        if psycho_plan is not None:
            dimension_count = len(getattr(psycho_plan, "plans", {}) or {})
            logging.info(
                "本轮启用心理测量计划：维度数=%d，题目数=%d，目标α=%.2f",
                dimension_count,
                len(getattr(psycho_plan, "items", []) or []),
                float(getattr(ctx, "psycho_target_alpha", 0.9) or 0.9),
            )
        survey_provider = str(getattr(ctx, "survey_provider", "wjx") or "wjx").strip().lower()
        try:
            return _fill_provider_survey(
                driver,
                ctx,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=psycho_plan,
                provider=survey_provider,
            )
        finally:
            reset_persona()

    questions_per_page = detect_fn(driver, stop_signal=stop_signal) if detect_fn is not None else []
    headless_mode = _is_headless_mode(ctx)
    try:
        total_steps = sum(max(0, int(count or 0)) for count in questions_per_page)
    except Exception:
        total_steps = 0
    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化线程步骤进度失败", exc_info=True)

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

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    if _abort_requested():
        try:
            ctx.update_thread_status(thread_name, "已中断", running=False)
        except Exception:
            logging.info("更新线程状态失败：已中断", exc_info=True)
        return False

    total_pages = len(questions_per_page)
    for page_index, questions_count in enumerate(questions_per_page):
        for _ in range(1, questions_count + 1):
            if _abort_requested():
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
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

            # 先读取题型（即使题目不可见也需要，用于维护索引）
            question_type = question_div.get_attribute("type")

            # 检测说明页/阅读材料：有 type 属性但无可交互控件
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
                psycho_plan=psycho_plan,
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
                            _single_impl(
                                driver,
                                current_question_number,
                                _indices["single"],
                                ctx.single_prob,
                                ctx.single_option_fill_texts,
                                ctx.single_attached_option_selects,
                            )
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
                            ctx.multi_text_blank_modes,
                            ctx.multi_text_blank_ai_flags,
                            ctx.multi_text_blank_int_ranges,
                        )
                        _indices["text"] += 1
                    else:
                        print(f"第{current_question_number}题为不支持类型(type={question_type})")

        _human_scroll_after_question(driver)
        if _abort_requested():
            try:
                ctx.update_thread_status(thread_name, "已中断", running=False)
            except Exception:
                logging.info("更新线程状态失败：已中断", exc_info=True)
            return False
        buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
        if buffer_delay > 0:
            if active_stop:
                if active_stop.wait(buffer_delay):
                    try:
                        ctx.update_thread_status(thread_name, "已中断", running=False)
                    except Exception:
                        logging.info("更新线程状态失败：已中断", exc_info=True)
                    return False
            else:
                time.sleep(buffer_delay)
        is_last_page = (page_index == total_pages - 1)
        if is_last_page:
            if simulate_answer_duration_delay(active_stop, ctx.answer_duration_range_seconds):
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
            # 最后一页直接跳出循环，由后续的 submit() 处理提交
            break
        clicked = _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("Next page button not found")
        click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
        if click_delay > 0:
            if active_stop:
                if active_stop.wait(click_delay):
                    try:
                        ctx.update_thread_status(thread_name, "已中断", running=False)
                    except Exception:
                        logging.info("更新线程状态失败：已中断", exc_info=True)
                    return False
            else:
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



