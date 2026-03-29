"""矩阵题处理"""
import random
from typing import Any, List, Optional, Union

from software.network.browser import By, BrowserDriver
from software.core.persona.context import record_answer
from software.core.questions.consistency import apply_matrix_row_consistency
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.strict_ratio import enforce_reference_rank_order, is_strict_ratio_question
from software.core.questions.tendency import get_tendency_index
from software.core.questions.utils import weighted_index


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
    rows_xpath = f'//*[@id="divRefTab{current}"]/tbody/tr'
    row_elements = driver.find_elements(By.XPATH, rows_xpath)
    matrix_row_count = sum(1 for row in row_elements if row.get_attribute("rowindex") is not None)

    columns_xpath = f'//*[@id="drv{current}_1"]/td'
    column_elements = driver.find_elements(By.XPATH, columns_xpath)
    if len(column_elements) <= 1:
        return index
    candidate_columns = list(range(2, len(column_elements) + 1))
    resolved_question_index = question_index if question_index is not None else current
    strict_ratio = is_strict_ratio_question(task_ctx, resolved_question_index)

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
                    psycho_plan=None if strict_ratio else psycho_plan,
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
                    psycho_plan=None if strict_ratio else psycho_plan,
                )
        if strict_ratio:
            if isinstance(row_probabilities, list):
                row_probabilities = enforce_reference_rank_order(
                    row_probabilities,
                    strict_reference or row_probabilities,
                )
            if isinstance(row_probabilities, list) and row_probabilities:
                selected_index = weighted_index(row_probabilities)
            else:
                selected_index = random.randrange(len(candidate_columns))
        else:
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
        # 记录统计数据：行索引 (0-based)，列索引 (0-based，减去表头偏移)
        record_answer(current, "matrix", selected_indices=[selected_column - 2], row_index=row_index - 1)
    return index



