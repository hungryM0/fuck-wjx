"""评价题处理（星级评价）"""
from typing import Any, List, Optional
import logging
from software.logging.log_utils import log_suppressed_exception


from software.network.browser import By, BrowserDriver, NoSuchElementException
from software.core.persona.context import record_answer
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.consistency import apply_single_like_consistency
from software.core.questions.strict_ratio import enforce_reference_rank_order, is_strict_ratio_question
from software.core.questions.tendency import get_tendency_index
from software.core.questions.utils import normalize_droplist_probs, weighted_index


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


def score(
    driver: BrowserDriver,
    current: int,
    index: int,
    score_prob_config: List,
    dimension: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
    question_index: Optional[int] = None,
    task_ctx: Optional[Any] = None,
) -> None:
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
    probs = normalize_droplist_probs(probabilities, len(options))
    probs = apply_single_like_consistency(probs, current)
    resolved_question_index = question_index if question_index is not None else current
    strict_ratio = is_strict_ratio_question(task_ctx, resolved_question_index)
    probs = resolve_distribution_probabilities(
        probs,
        len(options),
        task_ctx,
        resolved_question_index,
        psycho_plan=None if strict_ratio else psycho_plan,
    )
    if strict_ratio:
        probs = enforce_reference_rank_order(probs, normalize_droplist_probs(probabilities, len(options)))
        selected_index = weighted_index(probs)
    else:
        selected_index = get_tendency_index(
            len(options),
            probs,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=resolved_question_index,
        )
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
    record_pending_distribution_choice(
        task_ctx,
        resolved_question_index,
        selected_index,
        len(options),
    )
    # 记录统计数据
    # 记录作答上下文
    record_answer(current, "score", selected_indices=[selected_index])



