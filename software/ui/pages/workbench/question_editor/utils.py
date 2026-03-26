"""UI 辅助函数"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import QLabel
from qfluentwidgets import LineEdit

from software.core.questions.config import QuestionEntry
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.ui.widgets.no_wheel import NoWheelSlider

logger = logging.getLogger(__name__)


def _shorten_text(text: str, limit: int = 80) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _apply_label_color(label: QLabel, light: str, dark: str) -> None:
    """为标签设置浅色/深色主题颜色。"""
    try:
        getattr(label, 'setTextColor')(QColor(light), QColor(dark))
    except AttributeError as e:
        # setTextColor 方法不存在，使用样式表作为备选方案
        logger.info(f"setTextColor 方法不可用，使用样式表: {e}")
        style = label.styleSheet() or ""
        style = style.strip()
        if style and not style.endswith(";"):
            style = f"{style};"
        label.setStyleSheet(f"{style}color: {light};")


def _bind_slider_input(slider: NoWheelSlider, edit: LineEdit) -> None:
    """绑定滑块与输入框，避免循环触发。"""
    min_value = int(slider.minimum())
    max_value = int(slider.maximum())
    edit.setValidator(QIntValidator(min_value, max_value, edit))

    def sync_edit(value: int) -> None:
        edit.blockSignals(True)
        edit.setText(str(int(value)))
        edit.blockSignals(False)

    def sync_slider_live(text: str) -> None:
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            logger.info(f"滑块输入框数值转换失败: '{text}' 不是有效整数")
            return
        if value < min_value or value > max_value:
            return
        slider.setValue(value)

    def sync_slider_final() -> None:
        text = edit.text().strip()
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            logger.info(f"滑块输入框最终值转换失败: '{text}' 不是有效整数")
            return
        value = max(min_value, min(max_value, value))
        slider.setValue(value)
        edit.blockSignals(True)
        edit.setText(str(value))
        edit.blockSignals(False)

    slider.valueChanged.connect(sync_edit)
    edit.textChanged.connect(sync_slider_live)
    edit.editingFinished.connect(sync_slider_final)


def _normalize_question_num(raw: Any) -> Optional[int]:
    try:
        if raw is None:
            return None
        return int(raw)
    except Exception:
        return None


def _normalize_question_title(raw: Any) -> str:
    try:
        text = str(raw or "").strip()
    except Exception:
        return ""
    if not text:
        return ""
    return "".join(text.split())


def _normalize_provider_key(raw_provider: Any, raw_question_id: Any) -> Optional[Tuple[str, str]]:
    provider = normalize_survey_provider(raw_provider, default=SURVEY_PROVIDER_WJX)
    question_id = str(raw_question_id or "").strip()
    if not question_id:
        return None
    return provider, question_id


def _build_entry_info_fallback(entry: QuestionEntry) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "provider": normalize_survey_provider(getattr(entry, "survey_provider", None), default=SURVEY_PROVIDER_WJX),
        "title": str(getattr(entry, "question_title", None) or "").strip(),
        "question_type": str(getattr(entry, "question_type", None) or "").strip(),
        "options": int(max(0, getattr(entry, "option_count", 0) or 0)),
        "rows": int(max(1, getattr(entry, "rows", 1) or 1)),
        "is_location": bool(getattr(entry, "is_location", False)),
        "is_multi_text": str(getattr(entry, "question_type", "") or "").strip() == "multi_text",
        "is_text_like": str(getattr(entry, "question_type", "") or "").strip() in {"text", "multi_text"},
    }
    if info["question_type"] == "multi_text":
        info["text_inputs"] = max(
            2,
            len(getattr(entry, "multi_text_blank_modes", []) or []),
            len(getattr(entry, "multi_text_blank_ai_flags", []) or []),
            len(getattr(entry, "multi_text_blank_int_ranges", []) or []),
        )
    elif info["question_type"] == "text":
        info["text_inputs"] = 1
    raw_fillable_options = getattr(entry, "fillable_option_indices", None)
    if isinstance(raw_fillable_options, list):
        fillable_options: List[int] = []
        seen = set()
        option_count = int(info.get("options") or 0)
        for raw in raw_fillable_options:
            try:
                index = int(raw)
            except Exception:
                continue
            if index < 0 or (option_count > 0 and index >= option_count) or index in seen:
                continue
            seen.add(index)
            fillable_options.append(index)
        if fillable_options:
            info["fillable_options"] = fillable_options
    question_num = _normalize_question_num(getattr(entry, "question_num", None))
    if question_num is not None:
        info["num"] = question_num
    provider_question_id = str(getattr(entry, "provider_question_id", None) or "").strip()
    if provider_question_id:
        info["provider_question_id"] = provider_question_id
    provider_page_id = str(getattr(entry, "provider_page_id", None) or "").strip()
    if provider_page_id:
        info["provider_page_id"] = provider_page_id
    return info


def build_entry_info_list(entries: List[QuestionEntry], questions_info: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """将当前配置题目与原始题目元数据按稳定标识对齐，避免依赖裸下标。"""
    selectable_info: List[Dict[str, Any]] = []
    provider_map: Dict[Tuple[str, str], List[int]] = {}
    question_num_map: Dict[int, List[int]] = {}
    title_map: Dict[str, List[int]] = {}

    for raw_item in questions_info or []:
        if not isinstance(raw_item, dict):
            continue
        if bool(raw_item.get("is_description")) or bool(raw_item.get("unsupported")):
            continue
        item = dict(raw_item)
        info_index = len(selectable_info)
        selectable_info.append(item)

        provider_key = _normalize_provider_key(item.get("provider"), item.get("provider_question_id"))
        if provider_key:
            provider_map.setdefault(provider_key, []).append(info_index)

        question_num = _normalize_question_num(item.get("num"))
        if question_num is not None:
            question_num_map.setdefault(question_num, []).append(info_index)

        title_key = _normalize_question_title(item.get("title"))
        if title_key:
            title_map.setdefault(title_key, []).append(info_index)

    unused_indices = set(range(len(selectable_info)))
    aligned_info: List[Dict[str, Any]] = []

    def _take_first(indices: Optional[List[int]]) -> Optional[Dict[str, Any]]:
        if not indices:
            return None
        for candidate in indices:
            if candidate in unused_indices:
                unused_indices.remove(candidate)
                return dict(selectable_info[candidate])
        return None

    for idx, entry in enumerate(entries or []):
        matched_info: Optional[Dict[str, Any]] = None

        provider_key = _normalize_provider_key(
            getattr(entry, "survey_provider", None),
            getattr(entry, "provider_question_id", None),
        )
        if provider_key:
            matched_info = _take_first(provider_map.get(provider_key))

        if matched_info is None:
            question_num = _normalize_question_num(getattr(entry, "question_num", None))
            if question_num is not None:
                matched_info = _take_first(question_num_map.get(question_num))

        if matched_info is None:
            title_key = _normalize_question_title(getattr(entry, "question_title", None))
            if title_key:
                matched_info = _take_first(title_map.get(title_key))

        if matched_info is None and idx in unused_indices:
            unused_indices.remove(idx)
            matched_info = dict(selectable_info[idx])

        aligned_info.append(matched_info or _build_entry_info_fallback(entry))

    return aligned_info


