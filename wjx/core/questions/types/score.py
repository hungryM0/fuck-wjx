"""评价题处理（星级评价）"""
from typing import List
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.network.browser import By, BrowserDriver, NoSuchElementException
from wjx.core.persona.context import record_answer
from wjx.core.questions.tendency import get_tendency_index
from wjx.core.stats.collector import stats_collector


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
    except NoSuchElementException:
        # 这是正常分支：不在 evaluateTagWrap 中才是有效选项
        pass
    except Exception as exc:
        log_suppressed_exception("_is_valid_score_option: check evaluateTagWrap", exc, level=logging.WARNING)
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
    selected_index = get_tendency_index(len(options), probabilities)
    if selected_index >= len(options):
        selected_index = max(0, len(options) - 1)
    target = options[selected_index]
    try:
        target.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", target)
        except Exception as exc:
            log_suppressed_exception("score: driver.execute_script(\"arguments[0].click();\", target)", exc, level=logging.ERROR)
    # 记录统计数据
    stats_collector.record_score_choice(current, selected_index)
    # 记录作答上下文
    record_answer(current, "score", selected_indices=[selected_index])

