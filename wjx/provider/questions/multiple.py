"""多选题处理"""
import logging
import math
import random
from typing import Any, List, Optional

from software.core.persona.context import apply_persona_boost, record_answer
from software.core.questions.consistency import get_multiple_rule_constraint
from software.core.questions.strict_ratio import (
    is_strict_ratio_question,
    stochastic_round,
    weighted_sample_without_replacement,
)
from software.core.questions.utils import (
    extract_text_from_element,
    fill_option_additional_text,
    resolve_option_fill_text_from_config,
)
from software.network.browser import BrowserDriver

from .multiple_dom import (
    _click_multiple_option,
    _collect_multiple_option_elements,
    _warn_option_locator_once,
)
from .multiple_limits import (
    _extract_multi_limit_range_from_text,
    _log_multi_limit_once,
    _safe_positive_int,
    clear_multiple_choice_cache,
    detect_multiple_choice_limit,
    detect_multiple_choice_limit_range,
)
from .multiple_rules import (
    _WARNED_PROB_MISMATCH,
    _apply_rule_constraints,
    _normalize_selected_indices,
    _resolve_rule_sets,
)

__all__ = [
    'clear_multiple_choice_cache',
    'detect_multiple_choice_limit_range',
    'detect_multiple_choice_limit',
    '_log_multi_limit_once',
    '_safe_positive_int',
    '_extract_multi_limit_range_from_text',
    'multiple',
]


def multiple(
    driver: BrowserDriver,
    current: int,
    index: int,
    multiple_prob_config: List,
    multiple_option_fill_texts_config: List,
    task_ctx: Optional[Any] = None,
) -> None:
    """多选题处理主函数"""
    option_elements, option_source = _collect_multiple_option_elements(driver, current)
    if not option_elements:
        _warn_option_locator_once(
            current,
            "第%d题（多选）：未找到可用选项容器，已跳过（定位来源=%s）。",
            current,
            option_source,
        )
        return
    if option_source != "css:#div .ui-controlgroup > div":
        _warn_option_locator_once(
            current,
            "第%d题（多选）：选项容器结构异常，已使用回退定位（%s）。",
            current,
            option_source,
        )

    min_select_limit, max_select_limit = detect_multiple_choice_limit_range(driver, current)
    max_allowed = max_select_limit if max_select_limit is not None else len(option_elements)
    max_allowed = max(1, min(max_allowed, len(option_elements)))
    min_required = min_select_limit if min_select_limit is not None else 1
    min_required = max(1, min(min_required, len(option_elements)))
    if min_required > max_allowed:
        min_required = max_allowed
    _log_multi_limit_once(driver, current, min_select_limit, max_select_limit)
    selection_probabilities = multiple_prob_config[index] if index < len(multiple_prob_config) else [50.0] * len(option_elements)
    fill_entries = multiple_option_fill_texts_config[index] if index < len(multiple_option_fill_texts_config) else None

    # 提取选项文本，用于画像约束和上下文记录
    option_texts: List[str] = []
    for elem in option_elements:
        option_texts.append(extract_text_from_element(elem))

    must_select_indices, must_not_select_indices, rule_id = get_multiple_rule_constraint(current, len(option_elements))
    required_indices, blocked_indices = _resolve_rule_sets(
        must_select_indices,
        must_not_select_indices,
        len(option_elements),
        current,
        rule_id,
    )

    def _apply_selected_indices(selected_indices: List[int]) -> List[int]:
        confirmed_indices: List[int] = []
        for option_idx in selected_indices:
            option_element = option_elements[option_idx]
            if not _click_multiple_option(driver, option_element):
                logging.warning(
                    "第%d题（多选）：第 %d 个选项点击失败，已跳过。",
                    current,
                    option_idx + 1,
                )
                continue
            confirmed_indices.append(option_idx)
            fill_value = resolve_option_fill_text_from_config(
                fill_entries,
                option_idx,
                driver=driver,
                question_number=current,
                option_text=option_texts[option_idx] if option_idx < len(option_texts) else "",
            )
            fill_option_additional_text(driver, current, option_idx, fill_value)
        return confirmed_indices

    if selection_probabilities == -1 or (isinstance(selection_probabilities, list) and len(selection_probabilities) == 1 and selection_probabilities[0] == -1):
        available_pool = [
            idx for idx in range(len(option_elements))
            if idx not in blocked_indices and idx not in required_indices
        ]
        min_total = max(min_required, len(required_indices))
        max_total = min(max_allowed, len(required_indices) + len(available_pool))
        if min_total > max_total:
            logging.warning(
                "第%d题（多选）：条件规则[%s]与题目选择数量限制冲突，已按最多可选 %d 项处理。",
                current,
                rule_id or "-",
                max_total,
            )
            min_total = max_total
        extra_min = max(0, min_total - len(required_indices))
        extra_max = max(0, max_total - len(required_indices))
        extra_count = random.randint(extra_min, extra_max) if extra_max >= extra_min else 0
        sampled = random.sample(available_pool, extra_count) if extra_count > 0 else []
        selected_indices = list(required_indices)
        selected_indices.extend(sampled)
        selected_indices = _apply_rule_constraints(
            selected_indices,
            len(option_elements),
            min_required,
            max_allowed,
            required_indices,
            blocked_indices,
            positive_priority_indices=available_pool,
            current=current,
            rule_id=rule_id,
        )
        confirmed_indices = _apply_selected_indices(selected_indices)
        if not confirmed_indices:
            logging.warning("第%d题（多选）：随机模式点击失败，未选中任何选项。", current)
            return
        # 记录统计数据
        # 记录作答上下文
        selected_texts = [option_texts[i] for i in confirmed_indices if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed_indices, selected_texts=selected_texts)
        return

    if len(option_elements) != len(selection_probabilities):
        if len(selection_probabilities) > len(option_elements):
            # 截断：配置多于实际选项，丢弃多余部分，值得提醒
            if current not in _WARNED_PROB_MISMATCH:
                _WARNED_PROB_MISMATCH.add(current)
                logging.warning(
                    "第%d题（多选）：配置概率数(%d)多于页面实际选项数(%d)，多余部分已截断。",
                    current, len(selection_probabilities), len(option_elements)
                )
            selection_probabilities = selection_probabilities[: len(option_elements)]
        else:
            # 扩展：配置少于实际选项，用0补齐（未配置的选项不会被选中），属正常行为
            padding = [0.0] * (len(option_elements) - len(selection_probabilities))
            selection_probabilities = list(selection_probabilities) + padding
    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        if math.isnan(prob_value) or math.isinf(prob_value):
            prob_value = 0.0
        prob_value = max(0.0, min(100.0, prob_value))
        sanitized_probabilities.append(prob_value)
    selection_probabilities = sanitized_probabilities

    strict_ratio = is_strict_ratio_question(task_ctx, current)
    # 画像约束：对匹配画像的选项概率加成
    # 多选题概率是 0-100 的百分比，加成后上限仍为 100
    if not strict_ratio:
        boosted = apply_persona_boost(option_texts, selection_probabilities)
        selection_probabilities = [min(100.0, p) for p in boosted]
    for idx in blocked_indices:
        selection_probabilities[idx] = 0.0
    for idx in required_indices:
        selection_probabilities[idx] = 0.0

    if strict_ratio:
        positive_optional = [
            idx for idx, prob in enumerate(selection_probabilities)
            if prob > 0 and idx not in blocked_indices and idx not in required_indices
        ]
        if not positive_optional and not required_indices:
            if current not in _WARNED_PROB_MISMATCH:
                _WARNED_PROB_MISMATCH.add(current)
                logging.warning(
                    "第%d题（多选）：严格配比模式下所有可选项概率都 <= 0，已跳过本题；请至少保留一个 > 0%% 的选项。",
                    current,
                )
            return

        required_selected = _normalize_selected_indices(required_indices, len(option_elements))
        if len(required_selected) > max_allowed:
            logging.warning(
                "第%d题（多选）：必选项 %d 个已超过题目最多可选 %d 项，严格配比模式下按最多可选截断。",
                current,
                len(required_selected),
                max_allowed,
            )
            required_selected = required_selected[:max_allowed]

        min_total = max(min_required, len(required_selected))
        max_total = min(max_allowed, len(required_selected) + len(positive_optional))
        if min_total > max_total:
            logging.warning(
                "第%d题（多选）：严格配比模式下正概率可选项不足，题目要求最少选 %d 项，实际最多只能选 %d 项。",
                current,
                min_required,
                max_total,
            )
            min_total = max_total

        expected_optional = sum(selection_probabilities[idx] for idx in positive_optional) / 100.0
        total_target = len(required_selected) + stochastic_round(expected_optional)
        total_target = max(min_total, min(max_total, total_target))
        optional_target = max(0, total_target - len(required_selected))
        sampled_optional = weighted_sample_without_replacement(
            positive_optional,
            [selection_probabilities[idx] for idx in positive_optional],
            optional_target,
        )
        selected_indices = _normalize_selected_indices(required_selected + sampled_optional, len(option_elements))
        confirmed_indices = _apply_selected_indices(selected_indices)
        if len(confirmed_indices) < min_required:
            logging.warning(
                "第%d题（多选）：严格配比模式下题目最少需选 %d 项，实际点击成功 %d 项（正概率可选 %d，规则必选 %d）。",
                current,
                min_required,
                len(confirmed_indices),
                len(positive_optional),
                len(required_selected),
            )
        if not confirmed_indices:
            return
        selected_texts = [option_texts[i] for i in confirmed_indices if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed_indices, selected_texts=selected_texts)
        return

    selection_mask: List[int] = []
    attempts = 0
    max_attempts = 32
    positive_indices = [i for i, p in enumerate(selection_probabilities) if p > 0]
    if not positive_indices and not required_indices:
        if current not in _WARNED_PROB_MISMATCH:
            _WARNED_PROB_MISMATCH.add(current)
            logging.warning(
                "第%d题（多选）：所有选项概率都 <= 0，已跳过本题作答；请在配置中至少保留一个 > 0%% 的选项。",
                current,
            )
        return
    if positive_indices:
        while sum(selection_mask) == 0 and attempts < max_attempts:
            selection_mask = [1 if random.random() < (prob / 100.0) else 0 for prob in selection_probabilities]
            attempts += 1
        if sum(selection_mask) == 0:
            # 32次尝试都没选中任何选项，从正概率选项中随机选一个
            selection_mask = [0] * len(option_elements)
            selection_mask[random.choice(positive_indices)] = 1
    selected_indices = [
        idx
        for idx, selected in enumerate(selection_mask)
        if selected == 1 and selection_probabilities[idx] > 0
    ]
    selected_indices = _apply_rule_constraints(
        selected_indices,
        len(option_elements),
        min_required,
        max_allowed,
        required_indices,
        blocked_indices,
        positive_priority_indices=positive_indices,
        current=current,
        rule_id=rule_id,
    )
    if not selected_indices and positive_indices:
        selected_indices = [random.choice(positive_indices)]
    selected_indices = _normalize_selected_indices(selected_indices, len(option_elements))
    confirmed_indices = _apply_selected_indices(selected_indices)
    if len(confirmed_indices) < min_required:
        logging.warning(
            "第%d题（多选）：题目最少需选 %d 项，实际点击成功 %d 项（可用正概率选项 %d，规则必选 %d）。",
            current,
            min_required,
            len(confirmed_indices),
            len(positive_indices),
            len(required_indices),
        )
    if not confirmed_indices:
        return

    # 记录统计数据

    # 记录作答上下文
    selected_texts = [option_texts[i] for i in confirmed_indices if i < len(option_texts)]
    record_answer(current, "multiple", selected_indices=confirmed_indices, selected_texts=selected_texts)
