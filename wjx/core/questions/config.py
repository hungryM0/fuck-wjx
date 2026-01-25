from dataclasses import dataclass
from typing import Any, List, Optional, Union

import wjx.core.state as state
from wjx.core.questions.types.text import MULTI_TEXT_DELIMITER
from wjx.core.questions.utils import (
    normalize_option_fill_texts as _normalize_option_fill_texts,
    normalize_probabilities,
    normalize_single_like_prob_config as _normalize_single_like_prob_config,
    resolve_prob_config as _resolve_prob_config,
)
from wjx.utils.app.config import DEFAULT_FILL_TEXT, LOCATION_QUESTION_LABEL, QUESTION_TYPE_LABELS


def _infer_option_count(entry: "QuestionEntry") -> int:
    """
    当配置中缺少选项数量时，尽可能从已保存的权重/文本推导。
    优先顺序：已有数量 > 自定义权重 > 概率列表长度 > 文本数量 >（量表题兜底为5）。
    """
    def _nested_length(raw: Any) -> Optional[int]:
        """用于矩阵题：当传入的是按行拆分的权重列表时，返回其中最长的一行长度。"""
        if not isinstance(raw, list):
            return None
        lengths: List[int] = []
        for item in raw:
            if isinstance(item, (list, tuple)):
                lengths.append(len(item))
        return max(lengths) if lengths else None

    # 矩阵题优先检查按行拆分的权重，避免把“行数”误当成列数
    if getattr(entry, "question_type", "") == "matrix":
        nested_len = _nested_length(getattr(entry, "custom_weights", None))
        if nested_len:
            return nested_len
        nested_len = _nested_length(getattr(entry, "probabilities", None))
        if nested_len:
            return nested_len

    try:
        if entry.option_count and entry.option_count > 0:
            return int(entry.option_count)
    except Exception:
        pass
    try:
        if entry.custom_weights and len(entry.custom_weights) > 0:
            return len(entry.custom_weights)
    except Exception:
        pass
    try:
        if isinstance(entry.probabilities, (list, tuple)) and len(entry.probabilities) > 0:
            return len(entry.probabilities)
    except Exception:
        pass
    try:
        if entry.texts and len(entry.texts) > 0:
            return len(entry.texts)
    except Exception:
        pass
    if getattr(entry, "question_type", "") == "scale":
        return 5
    return 0


@dataclass
class QuestionEntry:
    question_type: str
    probabilities: Union[List[float], int, None]
    texts: Optional[List[str]] = None
    rows: int = 1
    option_count: int = 0
    distribution_mode: str = "random"  # random, custom
    custom_weights: Optional[List[float]] = None
    question_num: Optional[str] = None
    question_title: Optional[str] = None
    ai_enabled: bool = False
    option_fill_texts: Optional[List[Optional[str]]] = None
    fillable_option_indices: Optional[List[int]] = None
    is_location: bool = False

    def summary(self) -> str:
        def _mode_text(mode: Optional[str]) -> str:
            return {
                "random": "完全随机",
                "custom": "自定义配比",
            }.get(mode or "", "完全随机")

        if self.question_type in ("text", "multi_text"):
            raw_samples = self.texts or []
            if self.question_type == "multi_text":
                formatted_samples: List[str] = []
                for sample in raw_samples:
                    try:
                        text_value = str(sample).strip()
                    except Exception:
                        text_value = ""
                    if not text_value:
                        continue
                    if MULTI_TEXT_DELIMITER in text_value:
                        parts = [part.strip() for part in text_value.split(MULTI_TEXT_DELIMITER)]
                        parts = [part for part in parts if part]
                        formatted_samples.append(" / ".join(parts) if parts else text_value)
                    else:
                        formatted_samples.append(text_value)
                samples = " | ".join(formatted_samples)
            else:
                samples = " | ".join(filter(None, raw_samples))
            preview = samples if samples else "未设置示例内容"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            if self.is_location:
                label = "位置题"
            else:
                label = "多项填空题" if self.question_type == "multi_text" else "填空题"
            return f"{label}: {preview}"

        if self.question_type == "matrix":
            mode_text = _mode_text(self.distribution_mode)
            rows = max(1, self.rows)
            columns = max(1, self.option_count)
            return f"{rows} 行 × {columns} 列 - {mode_text}"

        if self.question_type == "multiple" and self.probabilities == -1:
            return f"{self.option_count} 个选项 - 随机多选"

        if self.probabilities == -1:
            return f"{self.option_count} 个选项 - 完全随机"

        mode_text = _mode_text(self.distribution_mode)
        fillable_hint = ""
        if self.option_fill_texts and any(text for text in self.option_fill_texts if text):
            fillable_hint = " | 含填空项"

        if self.question_type == "multiple" and self.custom_weights:
            weights_str = ",".join(f"{int(round(max(w, 0)))}%" for w in self.custom_weights)
            return f"{self.option_count} 个选项 - 权重 {weights_str}{fillable_hint}"

        if self.distribution_mode == "custom" and self.custom_weights:
            def _format_ratio(value: float) -> str:
                rounded = round(value, 1)
                if abs(rounded - int(rounded)) < 1e-6:
                    return str(int(rounded))
                return f"{rounded}".rstrip("0").rstrip(".")

            def _safe_weight(raw_value: Any) -> float:
                try:
                    return max(float(raw_value), 0.0)
                except Exception:
                    return 0.0

            weights_str = ":".join(_format_ratio(_safe_weight(w)) for w in self.custom_weights)
            return f"{self.option_count} 个选项 - 配比 {weights_str}{fillable_hint}"

        return f"{self.option_count} 个选项 - {mode_text}{fillable_hint}"


def _get_entry_type_label(entry: QuestionEntry) -> str:
    if getattr(entry, "is_location", False):
        return LOCATION_QUESTION_LABEL
    return QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type)


def configure_probabilities(entries: List[QuestionEntry]):
    state.single_prob = []
    state.droplist_prob = []
    state.multiple_prob = []
    state.matrix_prob = []
    state.scale_prob = []
    state.slider_targets = []
    state.texts = []
    state.texts_prob = []
    state.text_entry_types = []
    state.text_ai_flags = []
    state.text_titles = []
    state.single_option_fill_texts = []
    state.droplist_option_fill_texts = []
    state.multiple_option_fill_texts = []

    for entry in entries:
        # 若配置里未写明选项数，尽量从权重/概率推断，并回写以便后续编辑显示正确数量
        inferred_count = _infer_option_count(entry)
        if inferred_count and inferred_count != entry.option_count:
            entry.option_count = inferred_count
        probs = _resolve_prob_config(
            entry.probabilities,
            getattr(entry, "custom_weights", None),
            prefer_custom=(getattr(entry, "distribution_mode", None) == "custom"),
        )
        if probs is not entry.probabilities:
            entry.probabilities = probs
        if entry.question_type == "single":
            state.single_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            state.single_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "dropdown":
            state.droplist_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            state.droplist_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "multiple":
            if not isinstance(probs, list):
                raise ValueError("多选题必须提供概率列表，数值范围0-100")
            state.multiple_prob.append([float(value) for value in probs])
            state.multiple_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "matrix":
            rows = max(1, entry.rows)
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

            # 支持按行配置的权重（list[list]），否则退化为对所有行复用同一组
            row_weights_source: Optional[List[Any]] = None
            if isinstance(probs, list) and any(isinstance(item, (list, tuple)) for item in probs):
                row_weights_source = probs
            elif isinstance(entry.custom_weights, list) and any(isinstance(item, (list, tuple)) for item in entry.custom_weights):  # type: ignore[attr-defined]
                row_weights_source = entry.custom_weights  # type: ignore[attr-defined]

            if row_weights_source is not None:
                last_row: Optional[Any] = None
                for idx in range(rows):
                    raw_row = row_weights_source[idx] if idx < len(row_weights_source) else last_row
                    normalized_row = _normalize_row(raw_row)
                    if normalized_row is None:
                        normalized_row = [1.0 / option_count] * option_count
                    state.matrix_prob.append(normalized_row)
                    last_row = raw_row if raw_row is not None else last_row
            elif isinstance(probs, list):
                normalized = _normalize_row(probs)
                if normalized is None:
                    normalized = [1.0 / option_count] * option_count
                for _ in range(rows):
                    state.matrix_prob.append(list(normalized))
            else:
                for _ in range(rows):
                    state.matrix_prob.append(-1)
        elif entry.question_type == "scale":
            state.scale_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
        elif entry.question_type == "slider":
            target_value: Optional[float] = None
            if isinstance(entry.custom_weights, (list, tuple)) and entry.custom_weights:
                try:
                    target_value = float(entry.custom_weights[0])
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
            if target_value is None:
                target_value = 50.0
            state.slider_targets.append(target_value)
        elif entry.question_type in ("text", "multi_text"):
            raw_values = entry.texts or []
            normalized_values: List[str] = []
            for item in raw_values:
                try:
                    text_value = str(item).strip()
                except Exception:
                    text_value = ""
                if text_value:
                    normalized_values.append(text_value)
            ai_enabled = bool(getattr(entry, "ai_enabled", False)) if entry.question_type == "text" else False
            if not normalized_values:
                if ai_enabled:
                    normalized_values = [DEFAULT_FILL_TEXT]
                else:
                    raise ValueError("填空题至少需要一个候选答案")
            if isinstance(probs, list) and len(probs) == len(normalized_values):
                normalized = normalize_probabilities([float(value) for value in probs])
            else:
                normalized = normalize_probabilities([1.0] * len(normalized_values))
            state.texts.append(normalized_values)
            state.texts_prob.append(normalized)
            state.text_entry_types.append(entry.question_type)
            state.text_ai_flags.append(ai_enabled)
            state.text_titles.append(str(getattr(entry, "question_title", "") or ""))
