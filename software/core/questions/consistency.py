"""条件规则引擎：按用户配置的条件规则约束后续题目作答。"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from software.core.persona.context import get_answered

_thread_local = threading.local()
_CONDITION_MODES = {"selected", "not_selected"}
_ACTION_MODES = {"must_select", "must_not_select"}
_SUPPORTED_RULE_TYPE_CODES = {"3", "4", "5", "6"}
_QUESTION_TYPE_LABELS = {
    "3": "单选题",
    "4": "多选题",
    "5": "量表题",
    "6": "矩阵题",
}


@dataclass
class AnswerRule:
    id: str
    condition_question_num: int
    condition_mode: str
    condition_option_indices: List[int]
    target_question_num: int
    action_mode: str
    target_option_indices: List[int]
    condition_row_index: Optional[int] = None  # 矩阵题条件行（0-based），None 表示非矩阵题
    target_row_index: Optional[int] = None     # 矩阵题目标行（0-based），None 表示非矩阵题


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


def _normalize_question_type_code(value: Any) -> str:
    try:
        return str(value or "").strip()
    except Exception:
        return ""


def get_answer_rule_question_type_label(question: Any) -> str:
    if not isinstance(question, dict):
        return ""
    type_code = _normalize_question_type_code(question.get("type_code"))
    if type_code == "5" and question.get("is_rating"):
        return "评价题"
    return _QUESTION_TYPE_LABELS.get(type_code, "")


def question_supports_answer_rule(question: Any) -> bool:
    if not isinstance(question, dict):
        return False
    type_code = _normalize_question_type_code(question.get("type_code"))
    return type_code in _SUPPORTED_RULE_TYPE_CODES


def _build_question_info_map(questions_info: Optional[Sequence[Dict[str, Any]]]) -> Dict[int, Dict[str, Any]]:
    question_map: Dict[int, Dict[str, Any]] = {}
    for item in questions_info or []:
        if not isinstance(item, dict):
            continue
        q_num = _to_int(item.get("num"), 0)
        if q_num <= 0:
            continue
        question_map[q_num] = item
    return question_map


def sanitize_answer_rules(
    answer_rules: Optional[Sequence[Dict[str, Any]]],
    questions_info: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """清洗规则，并在提供题目信息时移除已不再受支持的题型规则。"""
    stats = {"invalid": 0, "unsupported": 0}
    sanitized: List[Dict[str, Any]] = []
    question_map = _build_question_info_map(questions_info)
    has_question_info = bool(question_map)

    for item in answer_rules or []:
        normalized = normalize_rule_dict(item)
        if not normalized:
            stats["invalid"] += 1
            continue
        if has_question_info:
            condition_info = question_map.get(normalized["condition_question_num"])
            target_info = question_map.get(normalized["target_question_num"])
            if not condition_info or not target_info:
                stats["unsupported"] += 1
                continue
            if not question_supports_answer_rule(condition_info) or not question_supports_answer_rule(target_info):
                stats["unsupported"] += 1
                continue
        sanitized.append(normalized)
    return sanitized, stats


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
    # 矩阵题行索引（可选）
    condition_row_index: Optional[int] = None
    target_row_index: Optional[int] = None
    raw_cri = raw.get("condition_row_index")
    if raw_cri is not None:
        cri = _to_int(raw_cri, -1)
        if cri >= 0:
            condition_row_index = cri
    raw_tri = raw.get("target_row_index")
    if raw_tri is not None:
        tri = _to_int(raw_tri, -1)
        if tri >= 0:
            target_row_index = tri
    rule_id = str(raw.get("id") or "").strip() or (
        f"rule-{condition_question_num}-{target_question_num}-{len(condition_option_indices)}-{len(target_option_indices)}"
    )
    result: Dict[str, Any] = {
        "id": rule_id,
        "condition_question_num": condition_question_num,
        "condition_mode": condition_mode,
        "condition_option_indices": condition_option_indices,
        "target_question_num": target_question_num,
        "action_mode": action_mode,
        "target_option_indices": target_option_indices,
    }
    if condition_row_index is not None:
        result["condition_row_index"] = condition_row_index
    if target_row_index is not None:
        result["target_row_index"] = target_row_index
    return result


def _normalize_rule(raw: Any) -> Optional[AnswerRule]:
    normalized = normalize_rule_dict(raw)
    if not normalized:
        return None
    return AnswerRule(
        id=normalized["id"],
        condition_question_num=normalized["condition_question_num"],
        condition_mode=normalized["condition_mode"],
        condition_option_indices=normalized["condition_option_indices"],
        target_question_num=normalized["target_question_num"],
        action_mode=normalized["action_mode"],
        target_option_indices=normalized["target_option_indices"],
        condition_row_index=normalized.get("condition_row_index"),
        target_row_index=normalized.get("target_row_index"),
    )


def reset_consistency_context(
    answer_rules: Optional[Sequence[Dict[str, Any]]] = None,
    questions_info: Optional[Sequence[Dict[str, Any]]] = None,
) -> None:
    """每份问卷开始时调用，注入并重置条件规则上下文。"""
    parsed_rules: List[AnswerRule] = []
    sanitized_rules, _ = sanitize_answer_rules(answer_rules, questions_info)
    for item in sanitized_rules:
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
    # 矩阵题：从行级答案中取选中索引
    if rule.condition_row_index is not None:
        selected_indices = set(_to_int_list(record.row_answers.get(rule.condition_row_index, [])))
    else:
        selected_indices = set(_to_int_list(getattr(record, "selected_indices", [])))
    condition_set = set(rule.condition_option_indices)
    if not condition_set:
        return False
    if rule.condition_mode == "selected":
        return bool(selected_indices.intersection(condition_set))
    if rule.condition_mode == "not_selected":
        return bool(selected_indices.isdisjoint(condition_set))
    return False


def _pick_latest_triggered_rule(question_number: int, row_index: Optional[int] = None) -> Optional[AnswerRule]:
    selected_rule: Optional[AnswerRule] = None
    for rule in _get_answer_rules():
        if rule.target_question_num != question_number:
            continue
        if rule.target_row_index != row_index:
            continue
        if _is_rule_triggered(rule):
            # 冲突按列表顺序覆盖：越靠后越优先
            selected_rule = rule
    return selected_rule


def _resolve_valid_rule_indices(rule: AnswerRule, option_count: int) -> Set[int]:
    return {idx for idx in rule.target_option_indices if 0 <= idx < option_count}


def _apply_rule(
    base_probabilities: List[float],
    rule: AnswerRule,
) -> List[float]:
    if not base_probabilities:
        return []
    valid_indices = _resolve_valid_rule_indices(rule, len(base_probabilities))
    if not valid_indices:
        logging.warning(
            "条件规则[%s]命中但目标选项越界，已忽略该规则（题号=%s）",
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
            "条件规则[%s]命中后无可用选项，已回退原概率（题号=%s）",
            rule.id,
            rule.target_question_num,
        )
        return list(base_probabilities)
    logging.info(
        "条件规则[%s]已生效：条件题=%s，目标题=%s，动作=%s，目标选项=%s",
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
    """对单选/量表/评价题的权重进行规则约束。"""
    base_probabilities = _sanitize_probabilities(probabilities)
    rule = _pick_latest_triggered_rule(question_number, row_index=None)
    if rule is None:
        return base_probabilities
    return _apply_rule(base_probabilities, rule)


def apply_matrix_row_consistency(
    probabilities: Sequence[float],
    question_number: int,
    row_index: int,
) -> List[float]:
    """对矩阵题指定行的权重进行规则约束。"""
    base_probabilities = _sanitize_probabilities(probabilities)
    rule = _pick_latest_triggered_rule(question_number, row_index=row_index)
    if rule is None:
        return base_probabilities
    return _apply_rule(base_probabilities, rule)


def get_multiple_rule_constraint(
    question_number: int,
    option_count: int,
) -> Tuple[Set[int], Set[int], Optional[str]]:
    """获取多选题规则约束：必选集合 / 禁选集合 / 规则ID。"""
    rule = _pick_latest_triggered_rule(question_number, row_index=None)
    if rule is None:
        return set(), set(), None
    valid_indices = _resolve_valid_rule_indices(rule, option_count)
    if not valid_indices:
        logging.warning(
            "条件规则[%s]命中但目标选项越界，已忽略该规则（题号=%s）",
            rule.id,
            rule.target_question_num,
        )
        return set(), set(), rule.id
    logging.info(
        "条件规则[%s]已生效：条件题=%s，目标题=%s，动作=%s，目标选项=%s",
        rule.id,
        rule.condition_question_num,
        rule.target_question_num,
        rule.action_mode,
        sorted(valid_indices),
    )
    if rule.action_mode == "must_select":
        return set(valid_indices), set(), rule.id
    return set(), set(valid_indices), rule.id


