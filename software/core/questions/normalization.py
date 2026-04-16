"""题目配置转运行时数据。"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from software.app.config import DEFAULT_FILL_TEXT, DIMENSION_UNGROUPED
from software.core.psychometrics import JOINT_PSYCHOMETRIC_SUPPORTED_TYPES
from software.core.questions.schema import (
    GLOBAL_RELIABILITY_DIMENSION,
    QuestionEntry,
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
    _infer_option_count,
)
from software.core.questions.strict_ratio import is_strict_custom_ratio_mode
from software.core.questions.utils import (
    build_random_int_token,
    normalize_option_fill_texts as _normalize_option_fill_texts,
    normalize_probabilities,
    normalize_single_like_prob_config as _normalize_single_like_prob_config,
    resolve_prob_config as _resolve_prob_config,
    serialize_random_int_range,
    try_parse_random_int_range,
)

if TYPE_CHECKING:
    from software.core.task import ExecutionConfig

__all__ = ["configure_probabilities"]


def _resolve_runtime_dimension(
    entry: QuestionEntry,
    *,
    reliability_mode_enabled: bool,
    strict_ratio: bool,
) -> Optional[str]:
    allows_joint_ratio = str(getattr(entry, "question_type", "") or "").strip() in JOINT_PSYCHOMETRIC_SUPPORTED_TYPES
    if not reliability_mode_enabled or (strict_ratio and not allows_joint_ratio):
        return None
    raw_dimension = str(getattr(entry, "dimension", "") or "").strip()
    if not raw_dimension or raw_dimension == DIMENSION_UNGROUPED:
        return None
    return raw_dimension


def configure_probabilities(
    entries: List[QuestionEntry],
    ctx: "ExecutionConfig",
    reliability_mode_enabled: bool = True,
) -> None:
    def _count_positive_weights(raw_weights: Any) -> int:
        if not isinstance(raw_weights, (list, tuple)):
            return 0
        count = 0
        for value in raw_weights:
            try:
                if float(value) > 0:
                    count += 1
            except Exception:
                continue
        return count

    def _raise_if_all_zero_single_like(raw_weights: Any, question_num: int, question_type: str) -> None:
        if isinstance(raw_weights, list) and raw_weights and _count_positive_weights(raw_weights) <= 0:
            raise ValueError(
                f"第 {question_num} 题（{question_type}）配置无效：所有选项配比均为 0，请至少保留一个大于 0 的选项。"
            )

    def _raise_if_all_zero_matrix(raw_weights: Any, question_num: int) -> None:
        if not isinstance(raw_weights, list) or not raw_weights:
            return
        if any(isinstance(item, (list, tuple)) for item in raw_weights):
            for row_idx, row_weights in enumerate(raw_weights, start=1):
                if isinstance(row_weights, (list, tuple)) and _count_positive_weights(row_weights) <= 0:
                    raise ValueError(
                        f"第 {question_num} 题（矩阵题）配置无效：第 {row_idx} 行配比全部为 0，请至少保留一个大于 0 的选项。"
                    )
            return
        if _count_positive_weights(raw_weights) <= 0:
            raise ValueError(
                f"第 {question_num} 题（矩阵题）配置无效：所有选项配比均为 0，请至少保留一个大于 0 的选项。"
            )

    def _raise_if_all_zero_attached_selects(entry: QuestionEntry, question_num: int) -> None:
        for cfg_idx, cfg in enumerate(list(getattr(entry, "attached_option_selects", []) or []), start=1):
            if not isinstance(cfg, dict):
                continue
            weights = cfg.get("weights")
            if isinstance(weights, list) and weights and _count_positive_weights(weights) <= 0:
                option_text = str(cfg.get("option_text") or "").strip()
                raise ValueError(
                    f"第 {question_num} 题（嵌入式下拉）配置无效：第 {cfg_idx} 组（{option_text or '未命名选项'}）配比全部为 0，请至少保留一个大于 0 的选项。"
                )

    target = ctx
    target.single_prob = []
    target.droplist_prob = []
    target.multiple_prob = []
    target.matrix_prob = []
    target.scale_prob = []
    target.slider_targets = []
    target.texts = []
    target.texts_prob = []
    target.text_entry_types = []
    target.text_ai_flags = []
    target.text_titles = []
    target.multi_text_blank_modes = []
    target.multi_text_blank_ai_flags = []
    target.multi_text_blank_int_ranges = []
    target.single_option_fill_texts = []
    target.single_attached_option_selects = []
    target.droplist_option_fill_texts = []
    target.multiple_option_fill_texts = []
    target.question_config_index_map = {}
    target.question_dimension_map = {}
    target.question_strict_ratio_map = {}
    target.question_psycho_bias_map = {}

    idx_single = idx_dropdown = idx_multiple = idx_matrix = idx_scale = idx_slider = idx_text = 0
    reliability_candidates: List[Tuple[int, bool, str]] = []

    for idx, entry in enumerate(entries, start=1):
        question_num = entry.question_num if entry.question_num is not None else idx
        inferred_count = _infer_option_count(entry)
        if inferred_count and inferred_count != entry.option_count:
            entry.option_count = inferred_count
        probs = _resolve_prob_config(
            entry.probabilities,
            getattr(entry, "custom_weights", None),
            prefer_custom=(getattr(entry, "distribution_mode", None) == "custom"),
        )
        _raise_if_all_zero_attached_selects(entry, question_num)
        strict_ratio = is_strict_custom_ratio_mode(
            getattr(entry, "distribution_mode", None),
            probs,
            getattr(entry, "custom_weights", None),
        )
        target.question_strict_ratio_map[question_num] = strict_ratio

        if entry.question_type == "single":
            _raise_if_all_zero_single_like(probs, question_num, "single")
            target.question_config_index_map[question_num] = ("single", idx_single)
            idx_single += 1
            target.single_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            target.single_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
            target.single_attached_option_selects.append(copy.deepcopy(getattr(entry, "attached_option_selects", []) or []))
        elif entry.question_type == "dropdown":
            _raise_if_all_zero_single_like(probs, question_num, "dropdown")
            target.question_config_index_map[question_num] = ("dropdown", idx_dropdown)
            target.question_dimension_map[question_num] = _resolve_runtime_dimension(
                entry,
                reliability_mode_enabled=reliability_mode_enabled,
                strict_ratio=strict_ratio,
            )
            target.question_psycho_bias_map[question_num] = str(getattr(entry, "psycho_bias", "custom") or "custom")
            reliability_candidates.append((question_num, strict_ratio, entry.question_type))
            idx_dropdown += 1
            target.droplist_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            target.droplist_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "multiple":
            target.question_config_index_map[question_num] = ("multiple", idx_multiple)
            idx_multiple += 1
            if not isinstance(probs, list):
                raise ValueError("多选题必须提供概率列表，数值范围0-100")
            target.multiple_prob.append([float(value) for value in probs])
            target.multiple_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "matrix":
            _raise_if_all_zero_matrix(probs, question_num)
            rows = max(1, entry.rows)
            target.question_config_index_map[question_num] = ("matrix", idx_matrix)
            target.question_dimension_map[question_num] = _resolve_runtime_dimension(
                entry,
                reliability_mode_enabled=reliability_mode_enabled,
                strict_ratio=strict_ratio,
            )
            bias_value = getattr(entry, "psycho_bias", "custom")
            target.question_psycho_bias_map[question_num] = list(bias_value) if isinstance(bias_value, list) else str(bias_value or "custom")
            reliability_candidates.append((question_num, strict_ratio, entry.question_type))
            idx_matrix += rows
            option_count = max(1, _infer_option_count(entry))

            def _normalize_row(raw_row: Any) -> Optional[List[float]]:
                if not isinstance(raw_row, (list, tuple)):
                    return None
                cleaned: List[float] = []
                for value in raw_row:
                    try:
                        cleaned.append(max(0.0, float(value)))
                    except Exception:
                        continue
                if not cleaned:
                    return None
                if len(cleaned) < option_count:
                    cleaned = cleaned + [1.0] * (option_count - len(cleaned))
                elif len(cleaned) > option_count:
                    cleaned = cleaned[:option_count]
                try:
                    return normalize_probabilities(cleaned)
                except Exception:
                    return None

            row_weights_source: Optional[List[Any]] = None
            if isinstance(probs, list) and any(isinstance(item, (list, tuple)) for item in probs):
                row_weights_source = probs
            elif isinstance(entry.custom_weights, list) and any(isinstance(item, (list, tuple)) for item in entry.custom_weights):
                row_weights_source = entry.custom_weights

            if row_weights_source is not None:
                last_row: Optional[Any] = None
                for row_idx in range(rows):
                    raw_row = row_weights_source[row_idx] if row_idx < len(row_weights_source) else last_row
                    normalized_row = _normalize_row(raw_row)
                    if normalized_row is None:
                        normalized_row = [1.0 / option_count] * option_count
                    target.matrix_prob.append(normalized_row)
                    last_row = raw_row if raw_row is not None else last_row
            elif isinstance(probs, list):
                normalized = _normalize_row(probs)
                if normalized is None:
                    normalized = [1.0 / option_count] * option_count
                for _ in range(rows):
                    target.matrix_prob.append(list(normalized))
            else:
                for _ in range(rows):
                    target.matrix_prob.append(-1)
        elif entry.question_type in ("scale", "score"):
            _raise_if_all_zero_single_like(probs, question_num, entry.question_type)
            target.question_config_index_map[question_num] = (entry.question_type, idx_scale)
            target.question_dimension_map[question_num] = _resolve_runtime_dimension(
                entry,
                reliability_mode_enabled=reliability_mode_enabled,
                strict_ratio=strict_ratio,
            )
            target.question_psycho_bias_map[question_num] = str(getattr(entry, "psycho_bias", "custom") or "custom")
            reliability_candidates.append((question_num, strict_ratio, entry.question_type))
            idx_scale += 1
            target.scale_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
        elif entry.question_type == "slider":
            target.question_config_index_map[question_num] = ("slider", idx_slider)
            idx_slider += 1
            mode = str(getattr(entry, "distribution_mode", "") or "").strip().lower()
            if mode == "random":
                target.slider_targets.append(float("nan"))
                continue
            target_value: Optional[float] = None
            if isinstance(entry.custom_weights, (list, tuple)) and entry.custom_weights:
                try:
                    first = entry.custom_weights[0]
                    target_value = float(first) if isinstance(first, (int, float)) else None
                except Exception:
                    target_value = None
            if target_value is None:
                if isinstance(probs, (int, float)):
                    target_value = float(probs)
                elif isinstance(probs, list) and probs:
                    try:
                        target_value = float(probs[0])
                    except Exception:
                        target_value = None
            target.slider_targets.append(50.0 if target_value is None else target_value)
        elif entry.question_type in ("text", "multi_text"):
            if not getattr(entry, "is_location", False):
                target.question_config_index_map[question_num] = ("text", idx_text)
                idx_text += 1
            else:
                target.question_config_index_map[question_num] = ("location", -1)
            text_random_mode = str(getattr(entry, "text_random_mode", _TEXT_RANDOM_NONE) or _TEXT_RANDOM_NONE).strip().lower()
            normalized_values = [str(item).strip() for item in (entry.texts or []) if str(item).strip()]
            normalized_blank_ai_flags: List[bool] = []
            normalized_blank_int_ranges: List[List[int]] = []
            if entry.question_type == "multi_text":
                raw_blank_ai_flags = getattr(entry, "multi_text_blank_ai_flags", []) or []
                if isinstance(raw_blank_ai_flags, list):
                    normalized_blank_ai_flags = [bool(flag) for flag in raw_blank_ai_flags]
                raw_blank_int_ranges = getattr(entry, "multi_text_blank_int_ranges", []) or []
                if isinstance(raw_blank_int_ranges, list):
                    normalized_blank_int_ranges = [serialize_random_int_range(item) for item in raw_blank_int_ranges]
                for blank_idx, mode in enumerate(getattr(entry, "multi_text_blank_modes", []) or []):
                    if str(mode or _TEXT_RANDOM_NONE).strip().lower() != _TEXT_RANDOM_INTEGER:
                        continue
                    target_range = raw_blank_int_ranges[blank_idx] if blank_idx < len(raw_blank_int_ranges) else []
                    if try_parse_random_int_range(target_range) is None:
                        raise ValueError(f"多项填空题第{blank_idx + 1}个空位的随机整数范围未设置完整")
            if entry.question_type == "text":
                ai_enabled = bool(getattr(entry, "ai_enabled", False))
            elif entry.question_type == "multi_text":
                ai_enabled = bool(getattr(entry, "ai_enabled", False)) or (
                    bool(normalized_blank_ai_flags) and all(normalized_blank_ai_flags)
                )
            else:
                ai_enabled = False
            if entry.question_type == "text" and text_random_mode in (_TEXT_RANDOM_NAME, _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_ID_CARD, _TEXT_RANDOM_INTEGER):
                ai_enabled = False
                if text_random_mode == _TEXT_RANDOM_NAME:
                    normalized_values = [_TEXT_RANDOM_NAME_TOKEN]
                elif text_random_mode == _TEXT_RANDOM_MOBILE:
                    normalized_values = [_TEXT_RANDOM_MOBILE_TOKEN]
                elif text_random_mode == _TEXT_RANDOM_ID_CARD:
                    normalized_values = [_TEXT_RANDOM_ID_CARD_TOKEN]
                else:
                    text_random_range = serialize_random_int_range(getattr(entry, "text_random_int_range", []))
                    if len(text_random_range) != 2:
                        raise ValueError("填空题随机整数范围未设置完整")
                    normalized_values = [build_random_int_token(*text_random_range)]
            if not normalized_values:
                if ai_enabled:
                    normalized_values = [DEFAULT_FILL_TEXT]
                else:
                    raise ValueError("填空题至少需要一个候选答案")
            if isinstance(probs, list) and len(probs) == len(normalized_values):
                normalized = normalize_probabilities([float(value) for value in probs])
            else:
                normalized = normalize_probabilities([1.0] * len(normalized_values))
            target.texts.append(normalized_values)
            target.texts_prob.append(normalized)
            target.text_entry_types.append(entry.question_type)
            target.text_ai_flags.append(ai_enabled)
            target.text_titles.append(str(getattr(entry, "question_title", "") or ""))
            target.multi_text_blank_modes.append(getattr(entry, "multi_text_blank_modes", []))
            target.multi_text_blank_ai_flags.append(normalized_blank_ai_flags)
            target.multi_text_blank_int_ranges.append(normalized_blank_int_ranges)

    has_explicit_runtime_dimension = any(
        isinstance(dimension, str) and bool(str(dimension).strip())
        for dimension in target.question_dimension_map.values()
    )
    if reliability_mode_enabled and reliability_candidates and not has_explicit_runtime_dimension:
        for question_num, strict_ratio, question_type in reliability_candidates:
            supports_joint_ratio = str(question_type or "").strip() in JOINT_PSYCHOMETRIC_SUPPORTED_TYPES
            if (strict_ratio and not supports_joint_ratio) or target.question_dimension_map.get(question_num):
                continue
            target.question_dimension_map[question_num] = GLOBAL_RELIABILITY_DIMENSION
