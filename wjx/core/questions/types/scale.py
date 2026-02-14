"""量表题处理"""
from typing import List, Union

from wjx.network.browser import By, BrowserDriver
from wjx.core.persona.context import record_answer
from wjx.core.questions.tendency import get_tendency_index
from wjx.core.stats.collector import stats_collector


def scale(driver: BrowserDriver, current: int, index: int, scale_prob_config: List) -> None:
    """量表题处理主函数"""
    scale_items_xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    scale_options = driver.find_elements(By.XPATH, scale_items_xpath)
    probabilities = scale_prob_config[index] if index < len(scale_prob_config) else -1
    if not scale_options:
        return
    selected_index = get_tendency_index(len(scale_options), probabilities)
    scale_options[selected_index].click()
    # 记录统计数据
    stats_collector.record_scale_choice(current, selected_index)
    # 记录作答上下文
    record_answer(current, "scale", selected_indices=[selected_index])

