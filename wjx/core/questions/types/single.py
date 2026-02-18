"""单选题处理"""
from typing import Any, List, Optional, Set, Union
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.network.browser import By, BrowserDriver
from wjx.core.persona.context import apply_persona_boost, record_answer
from wjx.core.questions.consistency import (
    apply_demographic_consistency,
    apply_single_like_consistency,
    build_question_semantic,
    record_demographic_answer,
    record_consistency_answer,
)
from wjx.core.questions.utils import (
    weighted_index,
    normalize_droplist_probs,
    get_fill_text_from_config,
    fill_option_additional_text,
    extract_text_from_element,
)
from wjx.core.stats.collector import stats_collector


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
            except Exception as exc:
                log_suppressed_exception("single: if not elem.is_displayed(): continue", exc, level=logging.ERROR)
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
            except Exception as exc:
                log_suppressed_exception("single: if not radio.is_displayed(): continue", exc, level=logging.ERROR)
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
    if config_len is not None and config_len > len(option_elements):
        # 仅在截断（丢弃多余配置）时提示，补零扩展属正常行为无需提示
        logging.debug(
            "单选题概率配置数(%s)多于实际选项数(%s)（题号%s），多余部分已截断并重新归一化。",
            config_len,
            len(option_elements),
            current,
        )
    # 画像约束：提取选项文本，对匹配画像的选项加权
    option_texts = []
    for elem in option_elements:
        option_texts.append(extract_text_from_element(elem))
    probabilities = apply_persona_boost(option_texts, probabilities)
    semantic = build_question_semantic(driver, current, option_texts)
    probabilities = apply_single_like_consistency(probabilities, semantic)
    probabilities = apply_demographic_consistency(probabilities, driver, current, option_texts)
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
            except Exception as exc:
                log_suppressed_exception("single: inner_radio = target_elem.find_element(By.XPATH, \".//input[@type='radio']\")", exc, level=logging.ERROR)
    if not clicked:
        try:
            driver.find_element(
                By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div:nth-child({selected_option})"
            ).click()
            clicked = True
        except Exception as exc:
            logging.warning("单选题默认选择器点击失败（题号%s，索引%s）：%s", current, selected_option, exc)
            return

    # 记录统计数据
    stats_collector.record_single_choice(current, target_index)

    # 记录作答上下文（供后续题目参考）
    selected_text = option_texts[target_index] if target_index < len(option_texts) else ""
    record_answer(current, "single", selected_indices=[target_index], selected_texts=[selected_text])
    record_consistency_answer(semantic, [target_index])
    record_demographic_answer(driver, current, option_texts, [target_index])

    fill_entries = single_option_fill_texts_config[index] if index < len(single_option_fill_texts_config) else None
    fill_value = get_fill_text_from_config(fill_entries, selected_option - 1)
    fill_option_additional_text(driver, current, selected_option - 1, fill_value)

