"""题目配置数据结构 - 策略、概率、选项等参数定义"""
import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional, Union

from software.core.questions.text_shared import MULTI_TEXT_DELIMITER
from software.core.questions.utils import (
    build_random_int_token,
    describe_random_int_range,
    normalize_option_fill_texts as _normalize_option_fill_texts,
    normalize_probabilities,
    parse_random_int_token,
    normalize_single_like_prob_config as _normalize_single_like_prob_config,
    resolve_prob_config as _resolve_prob_config,
    serialize_random_int_range,
    try_parse_random_int_range,
)
from software.core.questions.strict_ratio import is_strict_custom_ratio_mode
from software.app.config import DEFAULT_FILL_TEXT, DIMENSION_UNGROUPED, LOCATION_QUESTION_LABEL, QUESTION_TYPE_LABELS
from software.logging.log_utils import log_suppressed_exception

if TYPE_CHECKING:
    from software.core.task import TaskContext

_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"
_TEXT_RANDOM_ID_CARD_TOKEN = "__RANDOM_ID_CARD__"
_TEXT_RANDOM_NONE = "none"
_TEXT_RANDOM_NAME = "name"
_TEXT_RANDOM_MOBILE = "mobile"
_TEXT_RANDOM_ID_CARD = "id_card"
_TEXT_RANDOM_INTEGER = "integer"


def _pretty_text_answer(value: Any) -> str:
    text = str(value or "").strip()
    random_int_range = parse_random_int_token(text)
    if random_int_range is not None:
        return f"随机整数({describe_random_int_range(random_int_range)})"
    if text == _TEXT_RANDOM_NAME_TOKEN:
        return "随机姓名"
    if text == _TEXT_RANDOM_MOBILE_TOKEN:
        return "随机手机号"
    if text == _TEXT_RANDOM_ID_CARD_TOKEN:
        return "随机身份证"
    return text


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
    except Exception as exc:
        log_suppressed_exception("questions.config._infer_option_count option_count", exc)
    try:
        if entry.custom_weights and len(entry.custom_weights) > 0:
            return len(entry.custom_weights)
    except Exception as exc:
        log_suppressed_exception("questions.config._infer_option_count custom_weights", exc)
    try:
        if isinstance(entry.probabilities, (list, tuple)) and len(entry.probabilities) > 0:
            return len(entry.probabilities)
    except Exception as exc:
        log_suppressed_exception("questions.config._infer_option_count probabilities", exc)
    try:
        if entry.texts and len(entry.texts) > 0:
            return len(entry.texts)
    except Exception as exc:
        log_suppressed_exception("questions.config._infer_option_count texts", exc)
    if getattr(entry, "question_type", "") in ("scale", "score"):
        return 5
    return 0


@dataclass
class QuestionEntry:
    question_type: str
    probabilities: Union[List[float], List[List[float]], int, None]
    texts: Optional[List[str]] = None
    rows: int = 1
    option_count: int = 0
    distribution_mode: str = "random"  # random, custom
    custom_weights: Union[List[float], List[List[float]], None] = None
    question_num: Optional[int] = None
    question_title: Optional[str] = None
    survey_provider: str = "wjx"
    provider_question_id: Optional[str] = None
    provider_page_id: Optional[str] = None
    ai_enabled: bool = False
    multi_text_blank_modes: List[str] = field(default_factory=list)
    multi_text_blank_ai_flags: List[bool] = field(default_factory=list)
    multi_text_blank_int_ranges: List[List[int]] = field(default_factory=list)
    text_random_mode: str = _TEXT_RANDOM_NONE
    text_random_int_range: List[int] = field(default_factory=list)
    option_fill_texts: Optional[List[Optional[str]]] = None
    fillable_option_indices: Optional[List[int]] = None
    attached_option_selects: List[dict] = field(default_factory=list)
    is_location: bool = False
    dimension: Optional[str] = None  # 题目所属维度（如"满意度"、"信任感"等），None 表示未分组
    
    # 倾向预设：left/center/right/custom
    psycho_bias: str = "custom"

    def summary(self) -> str:
        def _mode_text(mode: Optional[str]) -> str:
            return {
                "random": "完全随机",
                "custom": "自定义配比",
            }.get(mode or "", "完全随机")

        if self.question_type in ("text", "multi_text"):
            text_random_mode = str(getattr(self, "text_random_mode", _TEXT_RANDOM_NONE) or _TEXT_RANDOM_NONE).strip().lower()
            if self.question_type == "text" and text_random_mode in (_TEXT_RANDOM_NAME, _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_ID_CARD, _TEXT_RANDOM_INTEGER):
                if text_random_mode == _TEXT_RANDOM_NAME:
                    random_label = "随机姓名"
                elif text_random_mode == _TEXT_RANDOM_MOBILE:
                    random_label = "随机手机号"
                elif text_random_mode == _TEXT_RANDOM_ID_CARD:
                    random_label = "随机身份证"
                else:
                    random_label = f"随机整数({describe_random_int_range(getattr(self, 'text_random_int_range', []))})"
                return f"填空题: {random_label}"
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
                pretty_samples = [_pretty_text_answer(sample) for sample in raw_samples if str(sample or "").strip()]
                samples = " | ".join(pretty_samples)
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

        if self.question_type == "order":
            return f"{self.option_count} 个选项 - 自动随机排序"

        if self.question_type == "multiple" and self.probabilities == -1:
            return f"{self.option_count} 个选项 - 随机多选"

        if self.probabilities == -1:
            return f"{self.option_count} 个选项 - 完全随机"

        mode_text = _mode_text(self.distribution_mode)
        fillable_hint = ""
        if self.option_fill_texts and any(text for text in self.option_fill_texts if text):
            fillable_hint = " | 含填空项"
        elif self.attached_option_selects:
            fillable_hint = " | 含嵌入式下拉"

        if self.question_type == "multiple" and self.custom_weights:
            weights_str = ",".join(f"{int(round(max(w, 0)))}%" for w in self.custom_weights if isinstance(w, (int, float)))
            return f"{self.option_count} 个选项 - 概率 {weights_str}{fillable_hint}"

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

            weights_str = ":".join(_format_ratio(_safe_weight(w)) for w in self.custom_weights if isinstance(w, (int, float)))
            return f"{self.option_count} 个选项 - 配比 {weights_str}{fillable_hint}"

        return f"{self.option_count} 个选项 - {mode_text}{fillable_hint}"


def _get_entry_type_label(entry: QuestionEntry) -> str:
    if getattr(entry, "is_location", False):
        return LOCATION_QUESTION_LABEL
    return QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type)

def _resolve_runtime_dimension(
    entry: QuestionEntry,
    *,
    reliability_mode_enabled: bool,
    strict_ratio: bool,
) -> Optional[str]:
    if not reliability_mode_enabled or strict_ratio:
        return None
    raw_dimension = str(getattr(entry, "dimension", "") or "").strip()
    if not raw_dimension or raw_dimension == DIMENSION_UNGROUPED:
        return None
    return raw_dimension


def configure_probabilities(
    entries: List[QuestionEntry],
    ctx: "TaskContext",
    reliability_mode_enabled: bool = True,
):
    _target = ctx

    _target.single_prob = []
    _target.droplist_prob = []
    _target.multiple_prob = []
    _target.matrix_prob = []
    _target.scale_prob = []
    _target.slider_targets = []
    _target.texts = []
    _target.texts_prob = []
    _target.text_entry_types = []
    _target.text_ai_flags = []
    _target.text_titles = []
    _target.multi_text_blank_modes = []
    _target.multi_text_blank_ai_flags = []
    _target.multi_text_blank_int_ranges = []
    _target.single_option_fill_texts = []
    _target.single_attached_option_selects = []
    _target.droplist_option_fill_texts = []
    _target.multiple_option_fill_texts = []
    _target.question_config_index_map = {}
    _target.question_dimension_map = {}
    _target.question_strict_ratio_map = {}
    _target.question_psycho_bias_map = {}

    # 各题型的当前索引,用于构建 question_config_index_map
    _idx_single = 0
    _idx_dropdown = 0
    _idx_multiple = 0
    _idx_matrix = 0
    _idx_scale = 0
    _idx_slider = 0
    _idx_text = 0

    for idx, entry in enumerate(entries, start=1):
        # 确保题号不为 None，使用列表索引作为默认值
        question_num = entry.question_num if entry.question_num is not None else idx
        
        # 若配置里未写明选项数，尽量从权重/概率推断，并回写以便后续编辑显示正确数量
        inferred_count = _infer_option_count(entry)
        if inferred_count and inferred_count != entry.option_count:
            entry.option_count = inferred_count
        probs = _resolve_prob_config(
            entry.probabilities,
            getattr(entry, "custom_weights", None),
            prefer_custom=(getattr(entry, "distribution_mode", None) == "custom"),
        )
        strict_ratio = is_strict_custom_ratio_mode(
            getattr(entry, "distribution_mode", None),
            probs,
            getattr(entry, "custom_weights", None),
        )
        _target.question_strict_ratio_map[question_num] = strict_ratio
        if entry.question_type == "single":
            _target.question_config_index_map[question_num] = ("single", _idx_single)
            _idx_single += 1
            _target.single_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            _target.single_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
            _target.single_attached_option_selects.append(copy.deepcopy(getattr(entry, "attached_option_selects", []) or []))
        elif entry.question_type == "dropdown":
            _target.question_config_index_map[question_num] = ("dropdown", _idx_dropdown)
            _idx_dropdown += 1
            _target.droplist_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            _target.droplist_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "multiple":
            _target.question_config_index_map[question_num] = ("multiple", _idx_multiple)
            _idx_multiple += 1
            if not isinstance(probs, list):
                raise ValueError("多选题必须提供概率列表，数值范围0-100")
            _target.multiple_prob.append([float(value) for value in probs])
            _target.multiple_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "matrix":
            rows = max(1, entry.rows)
            _target.question_config_index_map[question_num] = ("matrix", _idx_matrix)
            _target.question_dimension_map[question_num] = _resolve_runtime_dimension(
                entry,
                reliability_mode_enabled=reliability_mode_enabled,
                strict_ratio=strict_ratio,
            )
            bias_value = getattr(entry, "psycho_bias", "custom")
            if isinstance(bias_value, list):
                _target.question_psycho_bias_map[question_num] = list(bias_value)
            else:
                _target.question_psycho_bias_map[question_num] = str(bias_value or "custom")
            _idx_matrix += rows
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
                    _target.matrix_prob.append(normalized_row)
                    last_row = raw_row if raw_row is not None else last_row
            elif isinstance(probs, list):
                normalized = _normalize_row(probs)
                if normalized is None:
                    normalized = [1.0 / option_count] * option_count
                for _ in range(rows):
                    _target.matrix_prob.append(list(normalized))
            else:
                for _ in range(rows):
                    _target.matrix_prob.append(-1)
        elif entry.question_type in ("scale", "score"):
            _target.question_config_index_map[question_num] = (entry.question_type, _idx_scale)
            _target.question_dimension_map[question_num] = _resolve_runtime_dimension(
                entry,
                reliability_mode_enabled=reliability_mode_enabled,
                strict_ratio=strict_ratio,
            )
            _target.question_psycho_bias_map[question_num] = str(getattr(entry, "psycho_bias", "custom") or "custom")
            _idx_scale += 1
            _target.scale_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
        elif entry.question_type == "slider":
            _target.question_config_index_map[question_num] = ("slider", _idx_slider)
            _idx_slider += 1
            mode = str(getattr(entry, "distribution_mode", "") or "").strip().lower()
            if mode == "random":
                _target.slider_targets.append(float("nan"))
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
            if target_value is None:
                target_value = 50.0
            _target.slider_targets.append(target_value)
        elif entry.question_type in ("text", "multi_text"):
            if not getattr(entry, "is_location", False):
                _target.question_config_index_map[question_num] = ("text", _idx_text)
                _idx_text += 1
            else:
                _target.question_config_index_map[question_num] = ("location", -1)
            text_random_mode = str(getattr(entry, "text_random_mode", _TEXT_RANDOM_NONE) or _TEXT_RANDOM_NONE).strip().lower()
            raw_values = entry.texts or []
            normalized_values: List[str] = []
            for item in raw_values:
                try:
                    text_value = str(item).strip()
                except Exception:
                    text_value = ""
                if text_value:
                    normalized_values.append(text_value)
            normalized_blank_ai_flags: List[bool] = []
            normalized_blank_int_ranges: List[List[int]] = []
            if entry.question_type == "multi_text":
                raw_blank_ai_flags = getattr(entry, "multi_text_blank_ai_flags", []) or []
                if isinstance(raw_blank_ai_flags, list):
                    normalized_blank_ai_flags = [bool(flag) for flag in raw_blank_ai_flags]
                raw_blank_int_ranges = getattr(entry, "multi_text_blank_int_ranges", []) or []
                if isinstance(raw_blank_int_ranges, list):
                    normalized_blank_int_ranges = [
                        serialize_random_int_range(item) for item in raw_blank_int_ranges
                    ]
                raw_blank_modes = getattr(entry, "multi_text_blank_modes", []) or []
                if isinstance(raw_blank_modes, list):
                    for blank_idx, mode in enumerate(raw_blank_modes):
                        mode_text = str(mode or _TEXT_RANDOM_NONE).strip().lower()
                        if mode_text != _TEXT_RANDOM_INTEGER:
                            continue
                        target_range = raw_blank_int_ranges[blank_idx] if blank_idx < len(raw_blank_int_ranges) else []
                        if try_parse_random_int_range(target_range) is None:
                            raise ValueError(f"多项填空题第{blank_idx + 1}个空位的随机整数范围未设置完整")
            if entry.question_type == "text":
                ai_enabled = bool(getattr(entry, "ai_enabled", False))
            elif entry.question_type == "multi_text":
                # 多项填空只在「全空位启用 AI」时走批量 multi_fill_blank。
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
            _target.texts.append(normalized_values)
            _target.texts_prob.append(normalized)
            _target.text_entry_types.append(entry.question_type)
            _target.text_ai_flags.append(ai_enabled)
            _target.text_titles.append(str(getattr(entry, "question_title", "") or ""))
            _target.multi_text_blank_modes.append(getattr(entry, "multi_text_blank_modes", []))
            _target.multi_text_blank_ai_flags.append(normalized_blank_ai_flags)
            _target.multi_text_blank_int_ranges.append(normalized_blank_int_ranges)


def validate_question_config(entries: List[QuestionEntry], questions_info: Optional[List[dict]] = None) -> Optional[str]:
    """验证题目配置是否存在冲突，返回错误信息（如果有）。"""
    if not entries:
        return "未配置任何题目"

    errors: List[str] = []
    question_info_map = {}
    unsupported_questions: List[dict] = []
    for item in questions_info or []:
        if not isinstance(item, dict):
            continue
        q_num = getattr(item, "get", lambda *_args, **_kwargs: None)("num")
        try:
            q_num = int(q_num)
        except Exception:
            q_num = None
        if q_num is not None:
            question_info_map[q_num] = item
        if bool(item.get("unsupported")):
            unsupported_questions.append(item)

    if unsupported_questions:
        lines = ["当前问卷包含暂不支持的题型，已禁止启动："]
        for item in unsupported_questions[:12]:
            title = str(item.get("title") or f"第{item.get('num')}题").strip()
            provider_type = str(item.get("provider_type") or item.get("type_code") or "未知类型").strip()
            reason = str(item.get("unsupported_reason") or "").strip()
            if reason:
                lines.append(f"  - 第 {item.get('num')} 题：{title}（{provider_type}，{reason}）")
            else:
                lines.append(f"  - 第 {item.get('num')} 题：{title}（{provider_type}）")
        if len(unsupported_questions) > 12:
            lines.append(f"  - 其余 {len(unsupported_questions) - 12} 道暂不支持题目已省略")
        return "\n".join(lines)

    for idx, entry in enumerate(entries):
        question_num = getattr(entry, "question_num", idx + 1)
        question_type = getattr(entry, "question_type", "")
        try:
            normalized_question_num = int(question_num)
        except Exception:
            normalized_question_num = idx + 1

        # 验证多选题的概率配置是否有效，以及是否与选择数量限制冲突
        if question_type == "multiple":
            # 获取多选题的限制信息
            multi_min_limit: Optional[int] = None
            multi_max_limit: Optional[int] = None

            question_info = question_info_map.get(normalized_question_num)
            if question_info:
                multi_min_limit = question_info.get("multi_min_limit")
                multi_max_limit = question_info.get("multi_max_limit")

            # 获取概率配置
            probs = getattr(entry, "custom_weights", None) or getattr(entry, "probabilities", None)

            if isinstance(probs, list):
                # 统计概率 > 0 的选项数量
                positive_count = 0
                for prob in probs:
                    try:
                        prob_value = float(prob)
                        if prob_value > 0:
                            positive_count += 1
                    except Exception:
                        continue

                # 所有选项都 <= 0 时，直接判定配置无效
                if positive_count <= 0:
                    errors.append(
                        f"第 {question_num} 题（多选题）配置无效：\n"
                        f"  - 当前所有选项概率都小于等于 0%\n"
                        f"  - 请至少将 1 个选项的概率设为大于 0%"
                    )
                    continue

                # 如果有最少选择数量限制，检查正概率选项是否足够
                if multi_min_limit is not None and multi_min_limit > 0 and positive_count < multi_min_limit:
                    errors.append(
                        f"第 {question_num} 题（多选题）配置冲突：\n"
                        f"  - 题目要求最少选择 {multi_min_limit} 项\n"
                        f"  - 但只有 {positive_count} 个选项的概率大于 0%\n"
                        f"  - 请至少将 {multi_min_limit} 个选项的概率设为大于 0%"
                    )
                if multi_max_limit is not None and multi_max_limit > 0 and positive_count > multi_max_limit:
                    errors.append(
                        f"第 {question_num} 题（多选题）配置冲突：\n"
                        f"  - 题目最多允许选择 {multi_max_limit} 项\n"
                        f"  - 但当前有 {positive_count} 个选项的概率大于 0%\n"
                        f"  - 请把多余选项的概率改为 0%"
                    )

    if errors:
        return "\n\n".join(errors)

    return None


