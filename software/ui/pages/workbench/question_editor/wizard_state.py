"""配置向导运行时状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import QButtonGroup, QWidget
from qfluentwidgets import BodyLabel, LineEdit, PushButton, RadioButton, SwitchButton

from software.ui.widgets.no_wheel import NoWheelSlider

TextEditsValue = list[LineEdit] | list[list[LineEdit]]


@dataclass(slots=True)
class WizardRuntimeState:
    slider_map: dict[int, list[NoWheelSlider]] = field(default_factory=dict)
    matrix_row_slider_map: dict[int, list[list[NoWheelSlider]]] = field(default_factory=dict)
    text_edit_map: dict[int, TextEditsValue] = field(default_factory=dict)
    ai_check_map: dict[int, SwitchButton] = field(default_factory=dict)
    ai_label_map: dict[int, BodyLabel] = field(default_factory=dict)
    text_container_map: dict[int, QWidget] = field(default_factory=dict)
    text_add_btn_map: dict[int, PushButton] = field(default_factory=dict)
    text_random_mode_map: dict[int, str] = field(default_factory=dict)
    text_random_list_radio_map: dict[int, RadioButton] = field(default_factory=dict)
    text_random_name_check_map: dict[int, RadioButton] = field(default_factory=dict)
    text_random_mobile_check_map: dict[int, RadioButton] = field(default_factory=dict)
    text_random_id_card_check_map: dict[int, RadioButton] = field(default_factory=dict)
    text_random_integer_check_map: dict[int, RadioButton] = field(default_factory=dict)
    text_random_int_min_edit_map: dict[int, LineEdit] = field(default_factory=dict)
    text_random_int_max_edit_map: dict[int, LineEdit] = field(default_factory=dict)
    text_random_group_map: dict[int, QButtonGroup] = field(default_factory=dict)
    multi_text_blank_integer_range_edits: dict[int, list[tuple[LineEdit, LineEdit]]] = field(
        default_factory=dict
    )
    bias_preset_map: dict[int, Any] = field(default_factory=dict)
    attached_select_slider_map: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    option_fill_edit_map: dict[int, dict[int, LineEdit]] = field(default_factory=dict)
    option_fill_state_map: dict[int, dict[int, dict[str, Any]]] = field(default_factory=dict)
    multi_text_blank_radio_groups: dict[int, list[QButtonGroup]] = field(default_factory=dict)
    multi_text_blank_ai_checkboxes: dict[int, list[SwitchButton]] = field(default_factory=dict)


def bind_runtime_state(owner: Any, state: WizardRuntimeState) -> None:
    """把运行时状态对象挂到对话框实例上，先保持旧属性兼容。"""

    owner._runtime_state = state
    owner.slider_map = state.slider_map
    owner.matrix_row_slider_map = state.matrix_row_slider_map
    owner.text_edit_map = state.text_edit_map
    owner.ai_check_map = state.ai_check_map
    owner.ai_label_map = state.ai_label_map
    owner.text_container_map = state.text_container_map
    owner.text_add_btn_map = state.text_add_btn_map
    owner.text_random_mode_map = state.text_random_mode_map
    owner.text_random_list_radio_map = state.text_random_list_radio_map
    owner.text_random_name_check_map = state.text_random_name_check_map
    owner.text_random_mobile_check_map = state.text_random_mobile_check_map
    owner.text_random_id_card_check_map = state.text_random_id_card_check_map
    owner.text_random_integer_check_map = state.text_random_integer_check_map
    owner.text_random_int_min_edit_map = state.text_random_int_min_edit_map
    owner.text_random_int_max_edit_map = state.text_random_int_max_edit_map
    owner.text_random_group_map = state.text_random_group_map
    owner.multi_text_blank_integer_range_edits = state.multi_text_blank_integer_range_edits
    owner.bias_preset_map = state.bias_preset_map
    owner.attached_select_slider_map = state.attached_select_slider_map
    owner.option_fill_edit_map = state.option_fill_edit_map
    owner.option_fill_state_map = state.option_fill_state_map
    owner.multi_text_blank_radio_groups = state.multi_text_blank_radio_groups
    owner.multi_text_blank_ai_checkboxes = state.multi_text_blank_ai_checkboxes
