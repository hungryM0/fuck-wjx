"""量表题处理"""
from typing import Any, List, Optional

from software.network.browser import By, BrowserDriver
from software.core.persona.context import record_answer
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.strict_ratio import enforce_reference_rank_order, is_strict_ratio_question
from software.core.questions.tendency import get_tendency_index
from software.core.questions.consistency import apply_single_like_consistency
from software.core.questions.utils import normalize_droplist_probs, weighted_index


def scale(
    driver: BrowserDriver,
    current: int,
    index: int,
    scale_prob_config: List,
    dimension: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
    question_index: Optional[int] = None,
    task_ctx: Optional[Any] = None,
) -> None:
    """量表题处理主函数"""
    scale_items_xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    scale_options = driver.find_elements(By.XPATH, scale_items_xpath)
    probabilities = scale_prob_config[index] if index < len(scale_prob_config) else -1
    if not scale_options:
        return
    probs = normalize_droplist_probs(probabilities, len(scale_options))
    probs = apply_single_like_consistency(probs, current)
    resolved_question_index = question_index if question_index is not None else current
    strict_ratio = is_strict_ratio_question(task_ctx, resolved_question_index)
    probs = resolve_distribution_probabilities(
        probs,
        len(scale_options),
        task_ctx,
        resolved_question_index,
        psycho_plan=None if strict_ratio else psycho_plan,
    )
    if strict_ratio:
        probs = enforce_reference_rank_order(probs, normalize_droplist_probs(probabilities, len(scale_options)))
        selected_index = weighted_index(probs)
    else:
        selected_index = get_tendency_index(
            len(scale_options),
            probs,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=resolved_question_index,
        )
    scale_options[selected_index].click()
    record_pending_distribution_choice(
        task_ctx,
        resolved_question_index,
        selected_index,
        len(scale_options),
    )
    # 记录作答上下文
    record_answer(current, "scale", selected_indices=[selected_index])


