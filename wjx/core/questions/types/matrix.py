"""矩阵题处理"""
from typing import List, Union

from wjx.network.browser import By, BrowserDriver
from wjx.core.questions.tendency import get_tendency_index
from wjx.core.stats.collector import stats_collector


def matrix(driver: BrowserDriver, current: int, index: int, matrix_prob_config: List) -> int:
    """矩阵题处理主函数，返回更新后的索引"""
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

        if isinstance(probabilities, list):
            try:
                probs = [float(value) for value in probabilities]
            except Exception:
                probs = []
            if len(probs) != len(candidate_columns):
                probs = [1.0] * len(candidate_columns)
            selected_column = candidate_columns[get_tendency_index(len(candidate_columns), probs)]
        else:
            selected_column = candidate_columns[get_tendency_index(len(candidate_columns), -1)]
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
        # 记录统计数据：行索引 (0-based)，列索引 (0-based，减去表头偏移)
        stats_collector.record_matrix_choice(current, row_index - 1, selected_column - 2)
    return index

