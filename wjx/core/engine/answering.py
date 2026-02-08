import logging
import random
import threading
import time
from typing import List, Optional

import wjx.core.state as state
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
from wjx.core.questions.types.dropdown import droplist as _droplist_impl
from wjx.core.questions.types.matrix import matrix as _matrix_impl
from wjx.core.questions.types.multiple import multiple as _multiple_impl
from wjx.core.questions.types.reorder import reorder as _reorder_impl
from wjx.core.questions.types.scale import scale as _scale_impl
from wjx.core.questions.types.score import score as _score_impl
from wjx.core.questions.types.single import single as _single_impl
from wjx.core.questions.types.slider import slider_question as _slider_question_impl, _resolve_slider_score
from wjx.core.questions.types.text import (
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    driver_question_is_location as _driver_question_is_location,
    vacant as _vacant_impl,
)
from wjx.core.survey.parser import _should_mark_as_multi_text, _should_treat_question_as_text_like
from wjx.network.browser_driver import BrowserDriver, By, NoSuchElementException


def brush(driver: BrowserDriver, stop_signal: Optional[threading.Event] = None) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    questions_per_page = detect(driver, stop_signal=stop_signal)
    total_question_count = sum(questions_per_page)
    fast_mode = _is_fast_mode()
    single_question_index = 0
    vacant_question_index = 0
    droplist_question_index = 0
    multiple_question_index = 0
    matrix_question_index = 0
    scale_question_index = 0
    slider_question_index = 0
    current_question_number = 0
    active_stop = stop_signal or state.stop_event
    question_delay_plan: Optional[List[float]] = None
    if _full_simulation_active() and total_question_count > 0:
        target_seconds = _calculate_full_simulation_run_target(total_question_count)
        question_delay_plan = _build_per_question_delay_plan(total_question_count, target_seconds)
        planned_total = sum(question_delay_plan)
        logging.info(
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
            if _full_simulation_active():
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
            is_reorder_question = (question_type == "11") or _driver_question_looks_like_reorder(question_div)

            # 检测说明页/阅读材料：有 type 属性但无可交互控件
            if _driver_question_looks_like_description(question_div, question_type):
                logging.debug("跳过第%d题（说明页/阅读材料，type=%s）", current_question_number, question_type)
                continue

            if not question_visible:
                logging.debug("跳过第%d题（未显示，type=%s）", current_question_number, question_type)
                continue

            # 通过配置映射表查找当前题号在对应题型概率列表中的正确索引
            # 这样即使前面有题目被问卷条件逻辑隐藏，索引也不会错位
            _config_entry = state.question_config_index_map.get(current_question_number)

            if question_type in ("1", "2"):
                # 检测是否为位置题
                is_location_question = _driver_question_is_location(question_div) if question_div is not None else False
                if is_location_question:
                    print(f"第{current_question_number}题为位置题，暂不支持，已跳过")
                else:
                    _text_idx = _config_entry[1] if _config_entry and _config_entry[0] == "text" else vacant_question_index
                    _vacant_impl(
                        driver,
                        current_question_number,
                        _text_idx,
                        state.texts,
                        state.texts_prob,
                        state.text_entry_types,
                        state.text_ai_flags,
                        state.text_titles,
                    )
                    vacant_question_index += 1
            elif question_type == "3":
                _single_idx = _config_entry[1] if _config_entry and _config_entry[0] == "single" else single_question_index
                _single_impl(driver, current_question_number, _single_idx, state.single_prob, state.single_option_fill_texts)
                single_question_index += 1
            elif question_type == "4":
                _multi_idx = _config_entry[1] if _config_entry and _config_entry[0] == "multiple" else multiple_question_index
                _multiple_impl(driver, current_question_number, _multi_idx, state.multiple_prob, state.multiple_option_fill_texts)
                multiple_question_index += 1
            elif question_type == "5":
                _scale_idx = _config_entry[1] if _config_entry and _config_entry[0] == "scale" else scale_question_index
                if _driver_question_looks_like_rating(question_div):
                    _score_impl(driver, current_question_number, _scale_idx, state.scale_prob)
                else:
                    _scale_impl(driver, current_question_number, _scale_idx, state.scale_prob)
                scale_question_index += 1
            elif question_type == "6":
                _matrix_idx = _config_entry[1] if _config_entry and _config_entry[0] == "matrix" else matrix_question_index
                matrix_question_index = _matrix_impl(driver, current_question_number, _matrix_idx, state.matrix_prob)
            elif question_type == "7":
                _drop_idx = _config_entry[1] if _config_entry and _config_entry[0] == "dropdown" else droplist_question_index
                _droplist_impl(driver, current_question_number, _drop_idx, state.droplist_prob, state.droplist_option_fill_texts)
                droplist_question_index += 1
            elif question_type == "8":
                _slider_idx = _config_entry[1] if _config_entry and _config_entry[0] == "slider" else slider_question_index
                slider_score = _resolve_slider_score(_slider_idx, state.slider_targets)
                _slider_question_impl(driver, current_question_number, slider_score)
                slider_question_index += 1
            elif is_reorder_question:
                _reorder_impl(driver, current_question_number)
            else:
                # 兜底：尝试把未知类型当成填空题/多项填空题处理，避免直接跳过
                handled = False
                if question_div is not None:
                    checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
                    if checkbox_count or radio_count:
                        if checkbox_count >= radio_count:
                            _multiple_impl(driver, current_question_number, multiple_question_index, state.multiple_prob, state.multiple_option_fill_texts)
                            multiple_question_index += 1
                        else:
                            _single_impl(driver, current_question_number, single_question_index, state.single_prob, state.single_option_fill_texts)
                            single_question_index += 1
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
                    is_location_question = _driver_question_is_location(question_div) if question_div is not None else False
                    is_multi_text_question = _should_mark_as_multi_text(
                        question_type, option_count, text_input_count, is_location_question
                    )
                    is_text_like_question = _should_treat_question_as_text_like(
                        question_type, option_count, text_input_count
                    )

                    if is_text_like_question:
                        _vacant_impl(
                            driver,
                            current_question_number,
                            vacant_question_index,
                            state.texts,
                            state.texts_prob,
                            state.text_entry_types,
                            state.text_ai_flags,
                            state.text_titles,
                        )
                        vacant_question_index += 1
                        print(
                            f"第{current_question_number}题识别为"
                            f"{'多项填空' if is_multi_text_question else '填空'}，已按填空题处理"
                        )
                    else:
                        print(f"第{current_question_number}题为不支持类型(type={question_type})")
        if _full_simulation_active():
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
            if _simulate_answer_duration_delay(active_stop):
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
        return False
    submit(driver, stop_signal=active_stop)
    return True
