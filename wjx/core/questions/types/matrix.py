"""矩阵题处理"""
import random
from typing import List, Union

from wjx.network.browser_driver import By, BrowserDriver
from wjx.core.questions.utils import weighted_index, normalize_probabilities


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
            try:
                normalized_probs = normalize_probabilities(probs)
            except Exception:
                normalized_probs = [1.0 / len(candidate_columns)] * len(candidate_columns)
            selected_column = candidate_columns[weighted_index(normalized_probs)]
        else:
            selected_column = random.choice(candidate_columns)
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
    return index
