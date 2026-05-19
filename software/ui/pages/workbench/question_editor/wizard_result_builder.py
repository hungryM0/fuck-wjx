"""配置向导结果收集。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple, cast

from PySide6.QtWidgets import QButtonGroup
from qfluentwidgets import LineEdit, SwitchButton

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.config import QuestionEntry
from software.core.questions.utils import (
    OPTION_FILL_AI_TOKEN,
    build_random_int_token,
    serialize_random_int_range,
)
from software.providers.contracts import SurveyQuestionMeta
from software.ui.widgets.no_wheel import NoWheelSlider

from .wizard_sections import (
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
)

TextEditsValue = List[LineEdit] | List[List[LineEdit]]
OptionFillState = Dict[str, Any]
AttachedSelectConfig = Dict[str, Any]


class WizardResultSource(Protocol):
    slider_map: Dict[int, List[NoWheelSlider]]
    matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]]
    text_edit_map: Dict[int, TextEditsValue]
    text_random_mode_map: Dict[int, str]
    text_random_int_min_edit_map: Dict[int, LineEdit]
    text_random_int_max_edit_map: Dict[int, LineEdit]
    multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]]
    option_fill_state_map: Dict[int, Dict[int, OptionFillState]]
    attached_select_slider_map: Dict[int, List[AttachedSelectConfig]]
    bias_preset_map: Dict[int, Any]
    ai_check_map: Dict[int, SwitchButton]
    entries: List[QuestionEntry]

    def _format_question_label(self, idx: int) -> str: ...
    def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...


def get_results(source: WizardResultSource) -> Dict[int, Any]:
    result: Dict[int, Any] = {}
    for idx, sliders in source.slider_map.items():
        weights = [max(0, slider.value()) for slider in sliders]
        if weights and not any(weight > 0 for weight in weights):
            raise ValueError(f"{source._format_question_label(idx)}的选项配比不能全为0。")
        result[idx] = weights

    for idx, row_sliders in source.matrix_row_slider_map.items():
        row_weights: List[List[int]] = []
        for row_idx, row in enumerate(row_sliders):
            weights = [max(0, slider.value()) for slider in row]
            if weights and not any(weight > 0 for weight in weights):
                question_label = source._format_question_label(idx)
                raise ValueError(f"{question_label}的第{row_idx + 1}行配比不能全为0。")
            row_weights.append(weights)
        result[idx] = row_weights
    return result


def get_text_results(source: WizardResultSource) -> Dict[int, List[str]]:
    from software.core.questions.text_shared import MULTI_TEXT_DELIMITER

    result: Dict[int, List[str]] = {}
    for idx, edits in source.text_edit_map.items():
        if edits and isinstance(edits[0], list):
            texts = []
            matrix_edits = cast(List[List[LineEdit]], edits)
            for row_edits in matrix_edits:
                row_values = [edit.text().strip() for edit in row_edits]
                if not any(row_values):
                    continue
                merged = MULTI_TEXT_DELIMITER.join(row_values)
                if merged:
                    texts.append(merged)
        else:
            flat_edits = cast(List[LineEdit], edits)
            texts = [edit.text().strip() for edit in flat_edits if edit.text().strip()]
        if not texts:
            texts = [DEFAULT_FILL_TEXT]
        result[idx] = texts
    return result


def get_option_fill_results(source: WizardResultSource) -> Dict[int, List[Optional[str]]]:
    result: Dict[int, List[Optional[str]]] = {}
    for idx, state_map in source.option_fill_state_map.items():
        if not state_map:
            continue
        info = source._get_entry_info(idx)
        option_count = int(info.get("options") or 0)
        max_index = max(state_map.keys()) if state_map else -1
        normalized_count = max(option_count, max_index + 1, 0)
        values: List[Optional[str]] = [None] * normalized_count
        for option_index, state in state_map.items():
            if 0 <= option_index < normalized_count:
                values[option_index] = _build_option_fill_value(state)
        result[idx] = values
    return result


def get_text_random_modes(source: WizardResultSource) -> Dict[int, str]:
    return dict(source.text_random_mode_map)


def get_text_random_int_ranges(source: WizardResultSource) -> Dict[int, List[int]]:
    result: Dict[int, List[int]] = {}
    for idx, min_edit in source.text_random_int_min_edit_map.items():
        max_edit = source.text_random_int_max_edit_map.get(idx)
        raw_range = [min_edit.text().strip(), max_edit.text().strip() if max_edit else ""]
        result[idx] = serialize_random_int_range(raw_range)
    return result


def get_multi_text_blank_modes(source: WizardResultSource) -> Dict[int, List[str]]:
    result: Dict[int, List[str]] = {}
    groups_map = getattr(source, "multi_text_blank_radio_groups", None)
    if not groups_map:
        return result
    for idx, groups in groups_map.items():
        result[idx] = [_resolve_random_mode(group) for group in groups]
    return result


def get_multi_text_blank_int_ranges(source: WizardResultSource) -> Dict[int, List[List[int]]]:
    result: Dict[int, List[List[int]]] = {}
    for idx, edit_pairs in source.multi_text_blank_integer_range_edits.items():
        ranges: List[List[int]] = []
        for min_edit, max_edit in edit_pairs:
            ranges.append(
                serialize_random_int_range([min_edit.text().strip(), max_edit.text().strip()])
            )
        result[idx] = ranges
    return result


def get_multi_text_blank_ai_flags(source: WizardResultSource) -> Dict[int, List[bool]]:
    result: Dict[int, List[bool]] = {}
    checkboxes_map = getattr(source, "multi_text_blank_ai_checkboxes", None)
    if not checkboxes_map:
        return result
    for idx, checkboxes in checkboxes_map.items():
        result[idx] = [checkbox.isChecked() for checkbox in checkboxes]
    return result


def get_ai_flags(source: WizardResultSource) -> Dict[int, bool]:
    result: Dict[int, bool] = {}
    for idx, checkbox in source.ai_check_map.items():
        random_mode = source.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        result[idx] = False if random_mode != _TEXT_RANDOM_NONE else checkbox.isChecked()
    return result


def get_attached_select_results(
    source: WizardResultSource,
) -> Dict[int, List[Dict[str, Any]]]:
    result: Dict[int, List[Dict[str, Any]]] = {}
    for idx, config_items in source.attached_select_slider_map.items():
        serialized_items: List[Dict[str, Any]] = []
        for item in config_items:
            sliders = item.get("sliders") or []
            weights = [max(0, slider.value()) for slider in sliders]
            if weights and not any(weight > 0 for weight in weights):
                option_text = str(item.get("option_text") or "").strip()
                if not option_text:
                    option_text = f"第{int(item.get('option_index', 0)) + 1}项"
                raise ValueError(
                    f"{source._format_question_label(idx)}里“{option_text}”对应的嵌入式下拉配比不能全为0。"
                )
            serialized_items.append(
                {
                    "option_index": int(item.get("option_index", 0)),
                    "option_text": str(item.get("option_text") or "").strip(),
                    "select_options": list(item.get("select_options") or []),
                    "weights": weights,
                }
            )
        result[idx] = serialized_items
    return result


def get_bias_presets(source: WizardResultSource) -> Dict[int, Any]:
    result: Dict[int, Any] = {}
    for idx, seg in source.bias_preset_map.items():
        if isinstance(seg, list):
            result[idx] = [str(_current_bias_value(widget)) for widget in seg]
        else:
            result[idx] = str(_current_bias_value(seg))
    return result


def get_dimensions(source: WizardResultSource) -> Dict[int, Optional[str]]:
    result: Dict[int, Optional[str]] = {}
    for idx, entry in enumerate(source.entries):
        try:
            raw = str(getattr(entry, "dimension", "") or "").strip()
        except Exception:
            raw = ""
        result[idx] = raw or None
    return result


def _build_option_fill_value(state: OptionFillState) -> Optional[str]:
    ai_checkbox = cast(Optional[SwitchButton], state.get("ai_cb"))
    if ai_checkbox is not None and ai_checkbox.isChecked():
        return OPTION_FILL_AI_TOKEN

    group = cast(Optional[QButtonGroup], state.get("group"))
    checked_id = group.checkedId() if group is not None else 0
    if checked_id == 1:
        return _TEXT_RANDOM_NAME_TOKEN
    if checked_id == 2:
        return _TEXT_RANDOM_MOBILE_TOKEN
    if checked_id == 3:
        return _TEXT_RANDOM_ID_CARD_TOKEN
    if checked_id == 4:
        min_edit = cast(Optional[LineEdit], state.get("min_edit"))
        max_edit = cast(Optional[LineEdit], state.get("max_edit"))
        return build_random_int_token(
            min_edit.text().strip() if min_edit is not None else "",
            max_edit.text().strip() if max_edit is not None else "",
        )

    edit = cast(Optional[LineEdit], state.get("edit"))
    raw_value = edit.text().strip() if edit is not None else ""
    return raw_value or None


def _resolve_random_mode(group: QButtonGroup) -> str:
    checked_id = group.checkedId()
    if checked_id == 1:
        return _TEXT_RANDOM_NAME
    if checked_id == 2:
        return _TEXT_RANDOM_MOBILE
    if checked_id == 3:
        return _TEXT_RANDOM_ID_CARD
    if checked_id == 4:
        return _TEXT_RANDOM_INTEGER
    return _TEXT_RANDOM_NONE


def _current_bias_value(widget: Any) -> str:
    if hasattr(widget, "currentData"):
        return str(widget.currentData() or "custom")
    if hasattr(widget, "currentRouteKey"):
        return str(widget.currentRouteKey() or "custom")
    return "custom"
