"""评价题处理（星级评价）"""
import random
from typing import List

from wjx.network.browser_driver import By, BrowserDriver
from wjx.core.questions.utils import weighted_index


def _is_valid_score_option(element) -> bool:
    try:
        class_text = (element.get_attribute("class") or "").lower()
    except Exception:
        class_text = ""
    if "evaluatetagitem" in class_text or "writervaluate" in class_text:
        return False
    try:
        element.find_element(By.XPATH, "ancestor::*[contains(@class,'evaluateTagWrap')]")
        return False
    except Exception:
        pass
    return True


def _collect_score_options(question_div) -> List:
    selectors = (
        ".scale-rating ul li a",
        ".scale-rating a[val]",
        ".scale-rating .rate-off, .scale-rating .rate-on",
        "ul[tp='d'] li a",
        "ul[class*='modlen'] li a",
    )
    for selector in selectors:
        try:
            options = question_div.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            options = []
        if options:
            filtered = [opt for opt in options if _is_valid_score_option(opt)]
            if filtered:
                return filtered
    try:
        li_elements = question_div.find_elements(By.CSS_SELECTOR, ".scale-rating ul li")
    except Exception:
        li_elements = []
    options = []
    for li in li_elements:
        try:
            anchor = li.find_element(By.CSS_SELECTOR, "a")
        except Exception:
            anchor = None
        if anchor is None:
            continue
        if _is_valid_score_option(anchor):
            options.append(anchor)
    return options


def score(driver: BrowserDriver, current: int, index: int, score_prob_config: List) -> None:
    """评价题处理主函数"""
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except Exception:
        question_div = None
    if question_div is None:
        return
    options = _collect_score_options(question_div)
    if not options:
        return
    probabilities = score_prob_config[index] if index < len(score_prob_config) else -1
    if probabilities == -1:
        selected_index = random.randrange(len(options))
    else:
        selected_index = weighted_index(probabilities)
        if selected_index >= len(options):
            selected_index = max(0, len(options) - 1)
    target = options[selected_index]
    try:
        target.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", target)
        except Exception:
            pass
