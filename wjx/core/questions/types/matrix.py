"""矩阵题处理"""
from typing import List, Optional, Union

from wjx.network.browser import By, BrowserDriver
from wjx.core.questions.tendency import get_tendency_index


def matrix(driver: BrowserDriver, current: int, index: int, matrix_prob_config: List, dimension: Optional[str] = None, is_reverse: Union[bool, List[bool]] = False) -> int:
    """矩阵题处理主函数，返回更新后的索引。

    is_reverse 可以是：
    - bool：所有行统一翻转
    - List[bool]：每行独立控制，长度不足时末尾行回退到 False
    """
    rows_xpath = f'//*[@id="divRefTab{current}"]/tbody/tr'
    row_elements = driver.find_elements(By.XPATH, rows_xpath)
    matrix_row_count = sum(1 for row in row_elements if row.get_attribute("rowindex") is not None)

    columns_xpath = f'//*[@id="drv{current}_1"]/td'
    column_elements = driver.find_elements(By.XPATH, columns_xpath)
    if len(column_elements) <= 1:
        return index
    candidate_columns = list(range(2, len(column_elements) + 1))

    for row_index in range(1, matrix_row_count + 1):
        raw_probabilities = matrix_prob_config[index] if index < len(matrix_prob_config) else -1
        index += 1
        probabilities = raw_probabilities

        # 取当前行的反向标记
        if isinstance(is_reverse, list):
            row_is_reverse = is_reverse[row_index - 1] if row_index - 1 < len(is_reverse) else False
        else:
            row_is_reverse = bool(is_reverse)

        if isinstance(probabilities, list):
            try:
                probs = [float(value) for value in probabilities]
            except Exception:
                probs = []
            if len(probs) != len(candidate_columns):
                probs = [1.0] * len(candidate_columns)
            selected_column = candidate_columns[get_tendency_index(len(candidate_columns), probs, dimension=dimension, is_reverse=row_is_reverse)]
        else:
            selected_column = candidate_columns[get_tendency_index(len(candidate_columns), -1, dimension=dimension, is_reverse=row_is_reverse)]
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
        # 记录统计数据：行索引 (0-based)，列索引 (0-based，减去表头偏移)
    return index

