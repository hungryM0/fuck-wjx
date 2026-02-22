"""作答规则引擎：按用户配置的条件规则约束后续题目作答。"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

from wjx.core.persona.context import get_answered

_thread_local = threading.local()
_CONDITION_MODES = {"selected", "not_selected"}
_ACTION_MODES = {"must_select", "must_not_select"}


@dataclass
class AnswerRule:
    id: str
    condition_question_num: int
    condition_mode: str
    condition_option_indices: List[int]
    target_question_num: int
    action_mode: str
    target_option_indices: List[int]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_int_list(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
    result: List[int] = []
    seen = set()
    for item in values:
        idx = _to_int(item, -1)
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)


def normalize_rule_dict(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    condition_question_num = _to_int(raw.get("condition_question_num"), -1)
    target_question_num = _to_int(raw.get("target_question_num"), -1)
    condition_mode = str(raw.get("condition_mode") or "").strip()
    action_mode = str(raw.get("action_mode") or "").strip()
    if condition_question_num <= 0 or target_question_num <= 0:
        return None
    if condition_mode not in _CONDITION_MODES:
        return None
    if action_mode not in _ACTION_MODES:
        return None
    condition_option_indices = _to_int_list(raw.get("condition_option_indices"))
    target_option_indices = _to_int_list(raw.get("target_option_indices"))
    if not condition_option_indices or not target_option_indices:
        return None
    rule_id = str(raw.get("id") or "").strip() or (
        f"rule-{condition_question_num}-{target_question_num}-{len(condition_option_indices)}-{len(target_option_indices)}"
    )
    return {
        "id": rule_id,
        "condition_question_num": condition_question_num,
        "condition_mode": condition_mode,
        "condition_option_indices": condition_option_indices,
        "target_question_num": target_question_num,
        "action_mode": action_mode,
        "target_option_indices": target_option_indices,
    }


def _normalize_rule(raw: Any) -> Optional[AnswerRule]:
    normalized = normalize_rule_dict(raw)
    if not normalized:
        return None
    return AnswerRule(**normalized)


def reset_consistency_context(answer_rules: Optional[Sequence[Dict[str, Any]]] = None) -> None:
    """每份问卷开始时调用，注入并重置作答规则上下文。"""
    parsed_rules: List[AnswerRule] = []
    for item in answer_rules or []:
        normalized = _normalize_rule(item)
        if normalized:
            parsed_rules.append(normalized)
    _thread_local.answer_rules = parsed_rules


def _get_answer_rules() -> List[AnswerRule]:
    rules = getattr(_thread_local, "answer_rules", None)
    if not rules:
        return []
    return list(rules)


def _sanitize_probabilities(probabilities: Sequence[float]) -> List[float]:
    result: List[float] = []
    for value in probabilities:
        try:
            weight = float(value)
        except Exception:
            weight = 0.0
        if weight < 0:
            weight = 0.0
        result.append(weight)
    return result


def _is_rule_triggered(rule: AnswerRule) -> bool:
    if rule.condition_question_num >= rule.target_question_num:
        return False
    answered = get_answered()
    if not answered:
        return False
    record = answered.get(rule.condition_question_num)
    if record is None:
        return False
    selected_indices = set(_to_int_list(getattr(record, "selected_indices", [])))
    condition_set = set(rule.condition_option_indices)
    if not condition_set:
        return False
    if rule.condition_mode == "selected":
        return bool(selected_indices.intersection(condition_set))
    if rule.condition_mode == "not_selected":
        return bool(selected_indices.isdisjoint(condition_set))
    return False


def _pick_latest_triggered_rule(question_number: int) -> Optional[AnswerRule]:
    selected_rule: Optional[AnswerRule] = None
    for rule in _get_answer_rules():
        if rule.target_question_num != question_number:
            continue
        if _is_rule_triggered(rule):
            # 冲突按列表顺序覆盖：越靠后越优先
            selected_rule = rule
    return selected_rule


def _apply_rule(
    base_probabilities: List[float],
    rule: AnswerRule,
) -> List[float]:
    if not base_probabilities:
        return []
    valid_indices: Set[int] = {idx for idx in rule.target_option_indices if 0 <= idx < len(base_probabilities)}
    if not valid_indices:
        logging.warning(
            "作答规则[%s]命中但目标选项越界，已忽略该规则（题号=%s）",
            rule.id,
            rule.target_question_num,
        )
        return list(base_probabilities)
    if rule.action_mode == "must_select":
        adjusted = [weight if idx in valid_indices else 0.0 for idx, weight in enumerate(base_probabilities)]
    else:
        adjusted = [0.0 if idx in valid_indices else weight for idx, weight in enumerate(base_probabilities)]
    if sum(adjusted) <= 0:
        logging.warning(
            "作答规则[%s]命中后无可用选项，已回退原概率（题号=%s）",
            rule.id,
            rule.target_question_num,
        )
        return list(base_probabilities)
    logging.debug(
        "作答规则[%s]已生效：条件题=%s，目标题=%s，动作=%s，目标选项=%s",
        rule.id,
        rule.condition_question_num,
        rule.target_question_num,
        rule.action_mode,
        sorted(valid_indices),
    )
    return adjusted


def apply_single_like_consistency(
    probabilities: Sequence[float],
    question_number: int,
) -> List[float]:
    """
    对单选/下拉题的权重进行规则约束。

    说明：
    - 仅使用规则列表中“最后一条命中的规则”作为最终约束。
    - 约束后如果全为 0，会自动回退到原概率并记录 warning。
    """
    base_probabilities = _sanitize_probabilities(probabilities)
    rule = _pick_latest_triggered_rule(question_number)
    if rule is None:
        return base_probabilities
    return _apply_rule(base_probabilities, rule)
