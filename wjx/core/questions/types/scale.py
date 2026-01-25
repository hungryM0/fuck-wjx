"""量表题处理"""
import random
from typing import List, Union

from wjx.network.browser_driver import By, BrowserDriver
from wjx.core.questions.utils import weighted_index


def scale(driver: BrowserDriver, current: int, index: int, scale_prob_config: List) -> None:
    """量表题处理主函数"""
    scale_items_xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    scale_options = driver.find_elements(By.XPATH, scale_items_xpath)
    probabilities = scale_prob_config[index] if index < len(scale_prob_config) else -1
    if not scale_options:
        return
    if probabilities == -1:
        selected_index = random.randrange(len(scale_options))
    else:
        selected_index = weighted_index(probabilities)
    scale_options[selected_index].click()
