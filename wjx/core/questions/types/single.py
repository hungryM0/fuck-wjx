"""单选题处理"""
import logging
from typing import Any, List, Optional, Set, Union

from wjx.network.browser_driver import By, BrowserDriver
from wjx.core.questions.utils import (
    weighted_index,
    normalize_droplist_probs,
    get_fill_text_from_config,
    fill_option_additional_text,
)


def single(driver: BrowserDriver, current: int, index: int, single_prob_config: List, single_option_fill_texts_config: List) -> None:
    """单选题处理主函数"""
    # 兼容不同模板下的单选题 DOM 结构，按优先级收集可点击的选项节点
    option_elements: List[Any] = []
    probe_xpaths = [
        f'//*[@id="div{current}"]/div[2]/div',
        f'//*[@id="div{current}"]//div[contains(@class,"ui-radio")]',
        f'//*[@id="div{current}"]//div[contains(@class,"jqradio")]',
        f'//*[@id="div{current}"]//li[contains(@class,"option") or contains(@class,"radio")]/label',
        f'//*[@id="div{current}"]//label[contains(@class,"radio") or contains(@class,"option")]',
    ]
    seen: Set[Any] = set()
    for xpath in probe_xpaths:
        try:
            found = driver.find_elements(By.XPATH, xpath)
        except Exception:
            found = []
        for elem in found:
            try:
                if not elem.is_displayed():
                    continue
            except Exception:
                pass
            if elem not in seen:
                seen.add(elem)
                option_elements.append(elem)
    if not option_elements:
        try:
            radios = driver.find_elements(By.XPATH, f'//*[@id="div{current}"]//input[@type="radio"]')
        except Exception:
            radios = []
        for radio in radios:
            try:
                if not radio.is_displayed():
                    continue
            except Exception:
                pass
            if radio not in seen:
                seen.add(radio)
                option_elements.append(radio)
    if not option_elements:
        logging.warning(f"第{current}题未找到任何单选选项，已跳过该题。")
        return
    
    prob_config = single_prob_config[index] if index < len(single_prob_config) else -1
    config_len = None
    try:
        if hasattr(prob_config, "__len__") and not isinstance(prob_config, (int, float)):
            config_len = len(prob_config)
    except Exception:
        config_len = None
    probabilities = normalize_droplist_probs(prob_config, len(option_elements))
    if config_len is not None and config_len != len(option_elements):
        logging.debug(
            "单选题概率配置与选项数不一致（题号%s，概率数%s，选项数%s），已按设定权重自动扩展/截断并重新归一化。",
            current,
            config_len,
            len(option_elements),
        )
    target_index = weighted_index(probabilities)
    selected_option = target_index + 1
    target_elem = option_elements[target_index] if target_index < len(option_elements) else None
    clicked = False
    if target_elem:
        try:
            target_elem.click()
            clicked = True
        except Exception as exc:
            logging.debug("单选题直接点击失败（题号%s，索引%s）：%s", current, selected_option, exc)
            try:
                inner_radio = target_elem.find_element(By.XPATH, ".//input[@type='radio']")
                inner_radio.click()
                clicked = True
            except Exception:
                pass
    if not clicked:
        try:
            driver.find_element(
                By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div:nth-child({selected_option})"
            ).click()
            clicked = True
        except Exception as exc:
            logging.warning("单选题默认选择器点击失败（题号%s，索引%s）：%s", current, selected_option, exc)
            return
    
    fill_entries = single_option_fill_texts_config[index] if index < len(single_option_fill_texts_config) else None
    fill_value = get_fill_text_from_config(fill_entries, selected_option - 1)
    fill_option_additional_text(driver, current, selected_option - 1, fill_value)
