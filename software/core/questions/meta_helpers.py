"""解析后题目元数据的共享辅助逻辑。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from software.core.questions.utils import _normalize_question_type_code
from software.providers.contracts import SurveyQuestionMeta, ensure_survey_question_meta

QuestionMetaLike = SurveyQuestionMeta | Mapping[str, Any]

__all__ = [
    "QuestionMetaLike",
    "count_positive_weights",
    "find_all_zero_attached_selects",
    "find_all_zero_matrix_rows",
    "infer_question_entry_type",
    "normalize_attached_option_selects",
    "normalize_fillable_option_indices",
]


def count_positive_weights(raw_weights: Any) -> int:
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


def find_all_zero_matrix_rows(raw_weights: Any) -> List[int]:
    if not isinstance(raw_weights, list) or not raw_weights:
        return []
    if any(isinstance(item, (list, tuple)) for item in raw_weights):
        invalid_rows: List[int] = []
        for row_index, row_weights in enumerate(raw_weights, start=1):
            if isinstance(row_weights, (list, tuple)) and row_weights and count_positive_weights(row_weights) <= 0:
                invalid_rows.append(row_index)
        return invalid_rows
    return [0] if count_positive_weights(raw_weights) <= 0 else []


def find_all_zero_attached_selects(attached_configs: Any) -> List[Tuple[int, str]]:
    issues: List[Tuple[int, str]] = []
    for cfg_idx, cfg in enumerate(list(attached_configs or []), start=1):
        if not isinstance(cfg, dict):
            continue
        weights = cfg.get("weights")
        if isinstance(weights, list) and weights and count_positive_weights(weights) <= 0:
            issues.append((cfg_idx, str(cfg.get("option_text") or "").strip()))
    return issues


def infer_question_entry_type(question: QuestionMetaLike) -> str:
    meta = ensure_survey_question_meta(question)
    type_code = _normalize_question_type_code(meta.type_code)

    if bool(meta.is_slider_matrix):
        return "matrix"
    if bool(meta.is_multi_text) or (bool(meta.is_text_like) and int(meta.text_inputs or 0) > 1):
        return "multi_text"
    if bool(meta.is_text_like) or type_code in ("1", "2"):
        return "text"
    if type_code == "3":
        return "single"
    if type_code == "4":
        return "multiple"
    if type_code == "5":
        return "score" if bool(meta.is_rating) else "scale"
    if type_code in ("6", "9"):
        return "matrix"
    if type_code == "7":
        return "dropdown"
    if type_code == "8":
        return "slider"
    if type_code == "11":
        return "order"
    return "single"


def normalize_attached_option_selects(
    parsed_configs: Any,
    existing_configs: Any = None,
) -> List[Dict[str, Any]]:
    parsed_list = parsed_configs if isinstance(parsed_configs, list) else []
    existing_map: Dict[int, Dict[str, Any]] = {}
    if isinstance(existing_configs, list):
        for item in existing_configs:
            if not isinstance(item, dict):
                continue
            raw_option_index = item.get("option_index")
            if raw_option_index is None:
                continue
            try:
                option_index = int(raw_option_index)
            except Exception:
                continue
            existing_map[option_index] = item
    normalized: List[Dict[str, Any]] = []
    for item in parsed_list:
        if not isinstance(item, dict):
            continue
        raw_option_index = item.get("option_index")
        if raw_option_index is None:
            continue
        try:
            option_index = int(raw_option_index)
        except Exception:
            continue
        option_text = str(item.get("option_text") or "").strip()
        select_options_raw = item.get("select_options")
        if not isinstance(select_options_raw, list):
            continue
        select_options = [str(opt or "").strip() for opt in select_options_raw if str(opt or "").strip()]
        if not select_options:
            continue
        weights = None
        existing_item = existing_map.get(option_index)
        if existing_item is not None:
            existing_weights = existing_item.get("weights")
            if isinstance(existing_weights, list) and existing_weights:
                weights = []
                for idx in range(len(select_options)):
                    raw_weight = existing_weights[idx] if idx < len(existing_weights) else 0.0
                    try:
                        weights.append(max(0.0, float(raw_weight)))
                    except Exception:
                        weights.append(0.0)
                if not any(weight > 0 for weight in weights):
                    weights = None
        normalized.append(
            {
                "option_index": option_index,
                "option_text": option_text,
                "select_options": select_options,
                "weights": weights,
            }
        )
    return normalized


def normalize_fillable_option_indices(
    parsed_indices: Any,
    option_count: int,
    existing_indices: Any = None,
) -> List[int]:
    source = parsed_indices if isinstance(parsed_indices, list) else existing_indices
    if not isinstance(source, list):
        return []
    total = max(0, int(option_count or 0))
    normalized: List[int] = []
    seen: set[int] = set()
    for raw in source:
        try:
            index = int(raw)
        except Exception:
            continue
        if index < 0 or index >= total or index in seen:
            continue
        seen.add(index)
        normalized.append(index)
    return normalized
