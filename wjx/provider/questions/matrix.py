"""矩阵题处理"""
from decimal import Decimal
import math
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from software.network.browser import By, BrowserDriver
from software.core.persona.context import record_answer
from software.core.questions.consistency import apply_matrix_row_consistency
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.strict_ratio import enforce_reference_rank_order, is_strict_ratio_question
from software.core.questions.tendency import get_tendency_index
from software.logging.log_utils import log_suppressed_exception
from wjx.provider.questions.slider import set_slider_value


def _format_matrix_weight_value(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value or "").strip() or "随机"
    if math.isnan(number) or math.isinf(number):
        return "随机"
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _resolve_selected_weight_text(
    selected_index: int,
    resolved_probabilities: Union[List[float], int, float, None],
    raw_probabilities: Any,
) -> str:
    if isinstance(resolved_probabilities, list) and 0 <= selected_index < len(resolved_probabilities):
        return _format_matrix_weight_value(resolved_probabilities[selected_index])
    if isinstance(raw_probabilities, list) and 0 <= selected_index < len(raw_probabilities):
        return _format_matrix_weight_value(raw_probabilities[selected_index])
    return "随机"


def _extract_matrix_column_texts(driver: BrowserDriver, current: int, expected_count: int) -> List[str]:
    column_texts: List[str] = []
    try:
        header_cells = driver.find_elements(By.CSS_SELECTOR, f"#drv{current}_1 > td")
    except Exception:
        header_cells = []
    if len(header_cells) > 1:
        for cell in header_cells[1:]:
            try:
                text = str(cell.text or "").strip()
            except Exception:
                text = ""
            column_texts.append(" ".join(text.split()))
    if not any(column_texts):
        try:
            header_cells = driver.find_elements(By.CSS_SELECTOR, f"#divRefTab{current} th")
        except Exception:
            header_cells = []
        if len(header_cells) > 1:
            column_texts = []
            for cell in header_cells[1:]:
                try:
                    text = str(cell.text or "").strip()
                except Exception:
                    text = ""
                column_texts.append(" ".join(text.split()))
    if expected_count > 0:
        if len(column_texts) < expected_count:
            column_texts.extend("" for _ in range(expected_count - len(column_texts)))
        elif len(column_texts) > expected_count:
            column_texts = column_texts[:expected_count]
    return column_texts


def _log_matrix_row_choice(
    current: int,
    row_number: int,
    selected_index: int,
    column_text: str,
    resolved_probabilities: Union[List[float], int, float, None],
    raw_probabilities: Any,
) -> None:
    logging.info(
        "矩阵题作答：题号=%s 行号=%s 目标权重=%s 最终选中列=%s 页面列文本=%s",
        current,
        row_number,
        _resolve_selected_weight_text(selected_index, resolved_probabilities, raw_probabilities),
        selected_index + 1,
        column_text or "",
    )


def _collect_slider_matrix_inputs(driver: BrowserDriver, current: int):
    try:
        return driver.find_elements(By.CSS_SELECTOR, f"#div{current} input.ui-slider-input[rowid]")
    except Exception:
        return []


def _parse_slider_numeric(raw, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(raw)
    except Exception:
        return default


def _format_slider_candidate(value: float) -> float:
    if abs(value - round(value)) < 1e-6:
        return float(int(round(value)))
    return float(value)


def _build_slider_matrix_values(driver: BrowserDriver, current: int, slider_input) -> List[float]:
    try:
        marks = driver.find_elements(By.CSS_SELECTOR, f"#div{current} .ruler .cm[data-value]")
    except Exception:
        marks = []
    values: List[float] = []
    seen: set[float] = set()
    for mark in marks:
        parsed = _parse_slider_numeric(mark.get_attribute("data-value"))
        if parsed is None:
            continue
        normalized = _format_slider_candidate(parsed)
        if normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
    if values:
        return values

    min_value = _parse_slider_numeric(slider_input.get_attribute("min"), 0.0) or 0.0
    max_value = _parse_slider_numeric(slider_input.get_attribute("max"), 100.0) or 100.0
    step_value = abs(_parse_slider_numeric(slider_input.get_attribute("step"), 1.0) or 1.0)
    if step_value <= 0:
        step_value = 1.0
    if max_value < min_value:
        min_value, max_value = max_value, min_value
    fallback_values: List[float] = []
    current_value = min_value
    while current_value <= max_value + 1e-9 and len(fallback_values) < 200:
        fallback_values.append(_format_slider_candidate(current_value))
        current_value += step_value
    return fallback_values or [_format_slider_candidate(min_value)]


def _read_slider_matrix_total(driver: BrowserDriver, current: int, slider_inputs) -> Optional[float]:
    if not slider_inputs:
        return None
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except Exception:
        return None
    try:
        total_raw = question_div.get_attribute("total")
    except Exception:
        total_raw = None
    total_value = _parse_slider_numeric(total_raw)
    if total_value is None:
        return None
    for slider_input in slider_inputs:
        try:
            if str(slider_input.get_attribute("issum") or "").strip() != "1":
                return None
        except Exception:
            return None
    return total_value


def _normalize_row_probabilities(
    raw_probabilities: Any,
    candidate_count: int,
    current: int,
    row_offset: int,
    task_ctx: Optional[Any],
    resolved_question_index: int,
    psycho_plan: Optional[Any],
) -> Tuple[Union[List[float], int], Optional[List[float]]]:
    strict_reference: Optional[List[float]] = None
    row_probabilities: Union[List[float], int] = -1
    if isinstance(raw_probabilities, list):
        try:
            probs = [float(value) for value in raw_probabilities]
        except Exception:
            probs = []
        if len(probs) != candidate_count:
            probs = [1.0] * candidate_count
        strict_reference = list(probs)
        probs = apply_matrix_row_consistency(probs, current, row_offset)
        if any(p > 0 for p in probs):
            row_probabilities = resolve_distribution_probabilities(
                probs,
                candidate_count,
                task_ctx,
                resolved_question_index,
                row_index=row_offset,
                psycho_plan=psycho_plan,
            )
    else:
        uniform_probs = apply_matrix_row_consistency([1.0] * candidate_count, current, row_offset)
        if any(p > 0 for p in uniform_probs):
            row_probabilities = resolve_distribution_probabilities(
                uniform_probs,
                candidate_count,
                task_ctx,
                resolved_question_index,
                row_index=row_offset,
                psycho_plan=psycho_plan,
            )
    return row_probabilities, strict_reference


def _score_sum_constrained_paths(
    per_row_probabilities: List[Union[List[float], int]],
    candidate_values: List[float],
    total_value: float,
) -> Optional[List[int]]:
    if not per_row_probabilities:
        return []
    decimals = 0
    decimal_values = [Decimal(str(value)) for value in candidate_values]
    target_decimal = Decimal(str(total_value))
    for value in [*decimal_values, target_decimal]:
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            continue
        if exponent < 0:
            decimals = max(decimals, -exponent)
    scale = 10 ** min(decimals, 3)
    scaled_values = [int((value * scale).to_integral_value()) for value in decimal_values]
    scaled_target = int((target_decimal * scale).to_integral_value())

    states: Dict[int, Tuple[float, List[int]]] = {0: (0.0, [])}
    for row_probs in per_row_probabilities:
        next_states: Dict[int, Tuple[float, List[int]]] = {}
        for current_sum, (current_score, path) in states.items():
            for idx, scaled_value in enumerate(scaled_values):
                next_sum = current_sum + scaled_value
                probability = 1.0
                if isinstance(row_probs, list) and idx < len(row_probs):
                    probability = max(float(row_probs[idx]), 1e-9)
                candidate_score = current_score + math.log(probability)
                existing = next_states.get(next_sum)
                if existing is None or candidate_score > existing[0]:
                    next_states[next_sum] = (candidate_score, path + [idx])
        states = next_states
        if not states:
            return None

    exact = states.get(scaled_target)
    if exact is not None:
        return exact[1]

    best_path: Optional[List[int]] = None
    best_distance: Optional[int] = None
    best_score: Optional[float] = None
    for sum_value, (score, path) in states.items():
        distance = abs(sum_value - scaled_target)
        if (
            best_distance is None
            or distance < best_distance
            or (distance == best_distance and (best_score is None or score > best_score))
        ):
            best_distance = distance
            best_score = score
            best_path = path
    return best_path


def _fill_slider_matrix(
    driver: BrowserDriver,
    current: int,
    index: int,
    matrix_prob_config: List,
    dimension: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
    question_index: Optional[int] = None,
    task_ctx: Optional[Any] = None,
) -> int:
    slider_inputs = _collect_slider_matrix_inputs(driver, current)
    if not slider_inputs:
        return index

    candidate_values = _build_slider_matrix_values(driver, current, slider_inputs[0])
    resolved_question_index = question_index if question_index is not None else current
    strict_ratio_question = is_strict_ratio_question(task_ctx, resolved_question_index)
    total_constraint = _read_slider_matrix_total(driver, current, slider_inputs)
    per_row_probabilities: List[Union[List[float], int]] = []
    for row_offset, _slider_input in enumerate(slider_inputs):
        raw_probabilities = matrix_prob_config[index + row_offset] if index + row_offset < len(matrix_prob_config) else -1
        row_probabilities, strict_reference = _normalize_row_probabilities(
            raw_probabilities,
            len(candidate_values),
            current,
            row_offset,
            task_ctx,
            resolved_question_index,
            psycho_plan,
        )
        if strict_ratio_question and isinstance(row_probabilities, list):
            row_probabilities = enforce_reference_rank_order(
                row_probabilities,
                strict_reference or row_probabilities,
            )
        per_row_probabilities.append(row_probabilities)

    selected_indices: Optional[List[int]] = None
    if total_constraint is not None:
        selected_indices = _score_sum_constrained_paths(
            per_row_probabilities,
            candidate_values,
            total_constraint,
        )

    for row_offset, slider_input in enumerate(slider_inputs):
        row_probabilities = per_row_probabilities[row_offset]
        raw_probabilities = matrix_prob_config[index + row_offset] if index + row_offset < len(matrix_prob_config) else -1
        if selected_indices is not None and row_offset < len(selected_indices):
            selected_index = selected_indices[row_offset]
        else:
            selected_index = get_tendency_index(
                len(candidate_values),
                row_probabilities,
                dimension=dimension,
                psycho_plan=psycho_plan,
                question_index=resolved_question_index,
                row_index=row_offset,
            )
        selected_value = candidate_values[selected_index]
        try:
            container = slider_input.find_element(By.XPATH, "./..")
        except Exception:
            container = None
        try:
            set_slider_value(driver, slider_input, selected_value, container=container)
        except Exception as exc:
            log_suppressed_exception("matrix._fill_slider_matrix: set_slider_value(...)", exc, level=logging.ERROR)
        record_pending_distribution_choice(
            task_ctx,
            resolved_question_index,
            selected_index,
            len(candidate_values),
            row_index=row_offset,
        )
        _log_matrix_row_choice(
            current,
            row_offset + 1,
            selected_index,
            str(selected_value),
            row_probabilities,
            raw_probabilities,
        )
        record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_offset)
    return index + len(slider_inputs)


def matrix(
    driver: BrowserDriver,
    current: int,
    index: int,
    matrix_prob_config: List,
    dimension: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
    question_index: Optional[int] = None,
    task_ctx: Optional[Any] = None,
) -> int:
    """矩阵题处理主函数，返回更新后的索引。"""
    slider_inputs = _collect_slider_matrix_inputs(driver, current)
    if slider_inputs:
        return _fill_slider_matrix(
            driver,
            current,
            index,
            matrix_prob_config,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=question_index,
            task_ctx=task_ctx,
        )

    rows_xpath = f'//*[@id="divRefTab{current}"]/tbody/tr'
    row_elements = driver.find_elements(By.XPATH, rows_xpath)
    matrix_row_count = sum(1 for row in row_elements if row.get_attribute("rowindex") is not None)

    columns_xpath = f'//*[@id="drv{current}_1"]/td'
    column_elements = driver.find_elements(By.XPATH, columns_xpath)
    if len(column_elements) <= 1:
        return index
    candidate_columns = list(range(2, len(column_elements) + 1))
    column_texts = _extract_matrix_column_texts(driver, current, len(candidate_columns))
    resolved_question_index = question_index if question_index is not None else current
    strict_ratio_question = is_strict_ratio_question(task_ctx, resolved_question_index)

    for row_index in range(1, matrix_row_count + 1):
        raw_probabilities = matrix_prob_config[index] if index < len(matrix_prob_config) else -1
        index += 1
        strict_reference: Optional[List[float]] = None

        row_probabilities: Union[List[float], int] = -1
        if isinstance(raw_probabilities, list):
            try:
                probs = [float(value) for value in raw_probabilities]
            except Exception:
                probs = []
            if len(probs) != len(candidate_columns):
                probs = [1.0] * len(candidate_columns)
            strict_reference = list(probs)
            probs = apply_matrix_row_consistency(probs, current, row_index - 1)
            if any(p > 0 for p in probs):
                row_probabilities = resolve_distribution_probabilities(
                    probs,
                    len(candidate_columns),
                    task_ctx,
                    resolved_question_index,
                    row_index=row_index - 1,
                    psycho_plan=psycho_plan,
                )
        else:
            uniform_probs = apply_matrix_row_consistency([1.0] * len(candidate_columns), current, row_index - 1)
            if any(p > 0 for p in uniform_probs):
                row_probabilities = resolve_distribution_probabilities(
                    uniform_probs,
                    len(candidate_columns),
                    task_ctx,
                    resolved_question_index,
                    row_index=row_index - 1,
                    psycho_plan=psycho_plan,
                )
        if strict_ratio_question and isinstance(row_probabilities, list):
            row_probabilities = enforce_reference_rank_order(
                row_probabilities,
                strict_reference or row_probabilities,
            )
        selected_index = get_tendency_index(
            len(candidate_columns),
            row_probabilities,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=resolved_question_index,
            row_index=row_index - 1,
        )
        selected_column = candidate_columns[selected_index]
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
        record_pending_distribution_choice(
            task_ctx,
            resolved_question_index,
            selected_column - 2,
            len(candidate_columns),
            row_index=row_index - 1,
        )
        _log_matrix_row_choice(
            current,
            row_index,
            selected_column - 2,
            column_texts[selected_column - 2] if selected_column - 2 < len(column_texts) else "",
            row_probabilities,
            raw_probabilities,
        )
        # 记录统计数据：行索引 (0-based)，列索引 (0-based，减去表头偏移)
        record_answer(current, "matrix", selected_indices=[selected_column - 2], row_index=row_index - 1)
    return index



