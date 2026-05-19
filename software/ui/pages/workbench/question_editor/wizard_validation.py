"""配置向导保存前校验。"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, Tuple

from PySide6.QtWidgets import QWidget
from qfluentwidgets import LineEdit

from software.core.questions.utils import try_parse_random_int_range
from software.providers.contracts import SurveyQuestionMeta
from software.ui.widgets.no_wheel import NoWheelSlider

from .utils import _shorten_text


class WizardValidationHost(Protocol):
    text_random_mode_map: Dict[int, str]
    text_random_int_min_edit_map: Dict[int, LineEdit]
    text_random_int_max_edit_map: Dict[int, LineEdit]
    multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]]
    option_fill_state_map: Dict[int, Dict[int, Dict[str, Any]]]
    slider_map: Dict[int, List[NoWheelSlider]]
    matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]]
    attached_select_slider_map: Dict[int, List[Dict[str, Any]]]

    def _format_question_label(self, idx: int) -> str: ...
    def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
    def _show_validation_error(
        self, message: str, idx: int, focus_widget: QWidget | None = None
    ) -> None: ...
    def get_multi_text_blank_modes(self) -> Dict[int, List[str]]: ...


def validate_before_accept(host: WizardValidationHost) -> bool:
    return validate_random_integer_inputs(host) and validate_non_zero_weights(host)


def validate_random_integer_inputs(host: WizardValidationHost) -> bool:
    for idx, mode in host.text_random_mode_map.items():
        if str(mode or "").strip().lower() != "integer":
            continue
        min_edit = host.text_random_int_min_edit_map.get(idx)
        max_edit = host.text_random_int_max_edit_map.get(idx)
        raw_range = _build_raw_range(min_edit, max_edit)
        if try_parse_random_int_range(raw_range) is None:
            question_label = host._format_question_label(idx)
            host._show_validation_error(
                f"{question_label}的随机整数范围未填写完整，请输入最小值和最大值。",
                idx,
                min_edit or max_edit,
            )
            return False

    for idx, modes in host.get_multi_text_blank_modes().items():
        range_edits = host.multi_text_blank_integer_range_edits.get(idx, [])
        for blank_idx, mode in enumerate(modes):
            if str(mode or "").strip().lower() != "integer":
                continue
            min_edit = range_edits[blank_idx][0] if blank_idx < len(range_edits) else None
            max_edit = range_edits[blank_idx][1] if blank_idx < len(range_edits) else None
            raw_range = _build_raw_range(min_edit, max_edit)
            if try_parse_random_int_range(raw_range) is None:
                question_label = host._format_question_label(idx)
                host._show_validation_error(
                    f"{question_label}的填空{blank_idx + 1}随机整数范围未填写完整，请输入最小值和最大值。",
                    idx,
                    min_edit or max_edit,
                )
                return False

    for idx, option_states in host.option_fill_state_map.items():
        for option_idx, state in option_states.items():
            ai_cb = state.get("ai_cb")
            if ai_cb is not None and ai_cb.isChecked():
                continue
            group = state.get("group")
            if group is None or group.checkedId() != 4:
                continue
            min_edit = state.get("min_edit")
            max_edit = state.get("max_edit")
            raw_range = _build_raw_range(min_edit, max_edit)
            if try_parse_random_int_range(raw_range) is None:
                question_label = host._format_question_label(idx)
                host._show_validation_error(
                    f"{question_label}的第{option_idx + 1}个附加填空随机整数范围未填写完整，请输入最小值和最大值。",
                    idx,
                    min_edit or max_edit,
                )
                return False

    return True


def validate_non_zero_weights(host: WizardValidationHost) -> bool:
    for idx, sliders in host.slider_map.items():
        weights = [max(0, slider.value()) for slider in sliders]
        if weights and not any(weight > 0 for weight in weights):
            host._show_validation_error(
                f"{host._format_question_label(idx)}的选项配比不能全为0，请至少保留一个大于0的值。",
                idx,
                sliders[0],
            )
            return False

    for idx, row_sliders in host.matrix_row_slider_map.items():
        info = host._get_entry_info(idx)
        row_texts = info.get("row_texts")
        for row_idx, row in enumerate(row_sliders):
            weights = [max(0, slider.value()) for slider in row]
            if not weights or any(weight > 0 for weight in weights):
                continue
            row_name = f"第{row_idx + 1}行"
            if isinstance(row_texts, list) and row_idx < len(row_texts):
                row_text = str(row_texts[row_idx] or "").strip()
                if row_text:
                    row_name = f"{row_name}（{_shorten_text(row_text, 24)}）"
            host._show_validation_error(
                f"{host._format_question_label(idx)}的{row_name}配比不能全为0，请至少保留一个大于0的值。",
                idx,
                row[0],
            )
            return False

    for idx, config_items in host.attached_select_slider_map.items():
        for item in config_items:
            sliders = item.get("sliders") or []
            if not sliders:
                continue
            weights = [max(0, slider.value()) for slider in sliders]
            if any(weight > 0 for weight in weights):
                continue
            option_text = str(item.get("option_text") or "").strip()
            if not option_text:
                option_text = f"第{int(item.get('option_index', 0)) + 1}项"
            question_label = host._format_question_label(idx)
            option_label = _shorten_text(option_text, 28)
            host._show_validation_error(
                f"{question_label}里“{option_label}”对应的嵌入式下拉配比不能全为0，请至少保留一个大于0的值。",
                idx,
                sliders[0],
            )
            return False

    return True


def _build_raw_range(
    min_edit: LineEdit | QWidget | None,
    max_edit: LineEdit | QWidget | None,
) -> List[str]:
    return [
        _read_line_edit_text(min_edit),
        _read_line_edit_text(max_edit),
    ]


def _read_line_edit_text(widget: LineEdit | QWidget | None) -> str:
    if isinstance(widget, LineEdit):
        return widget.text().strip()
    return ""
