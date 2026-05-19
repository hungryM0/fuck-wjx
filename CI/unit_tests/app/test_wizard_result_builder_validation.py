from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QButtonGroup, QRadioButton
from qfluentwidgets import LineEdit

from software.core.questions.config import QuestionEntry
from software.core.questions.utils import OPTION_FILL_AI_TOKEN
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.question_editor import wizard_result_builder as builder
from software.ui.pages.workbench.question_editor import wizard_validation as validation


class _Slider:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _Check:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _Combo:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentData(self) -> str:
        return self._value


class _Segment:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentRouteKey(self) -> str:
        return self._value


class _Host:
    def __init__(self) -> None:
        self.slider_map = {}
        self.matrix_row_slider_map = {}
        self.text_edit_map = {}
        self.text_random_mode_map = {}
        self.text_random_int_min_edit_map = {}
        self.text_random_int_max_edit_map = {}
        self.multi_text_blank_integer_range_edits = {}
        self.option_fill_state_map = {}
        self.attached_select_slider_map = {}
        self.bias_preset_map = {}
        self.ai_check_map = {}
        self.entries = [QuestionEntry("single", [1, 1], question_num=1, dimension="体验")]
        self.multi_text_blank_radio_groups = {}
        self.multi_text_blank_ai_checkboxes = {}
        self.errors: list[tuple[str, int, object]] = []

    def _format_question_label(self, idx: int) -> str:
        return f"第{idx + 1}题"

    def _get_entry_info(self, idx: int):
        _ = idx
        return SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="6",
            options=2,
            row_texts=["服务很长很长很长很长很长很长很长很长"],
        )

    def _show_validation_error(self, message: str, idx: int, focus_widget=None) -> None:
        self.errors.append((message, idx, focus_widget))

    def get_multi_text_blank_modes(self):
        return builder.get_multi_text_blank_modes(self)


def _line(text: str) -> LineEdit:
    edit = LineEdit()
    edit.setText(text)
    return edit


def _radio_group(checked_id: int) -> QButtonGroup:
    group = QButtonGroup()
    for button_id in range(5):
        button = QRadioButton()
        group.addButton(button, button_id)
        if button_id == checked_id:
            button.setChecked(True)
    return group


def test_wizard_result_builder_collects_normal_results(qtbot) -> None:
    host = _Host()
    host.slider_map = {0: [_Slider(10), _Slider(-3)]}
    host.matrix_row_slider_map = {1: [[_Slider(0), _Slider(5)], [_Slider(2), _Slider(0)]]}
    host.text_edit_map = {0: [_line(" A "), _line("")], 1: [[_line("r1"), _line("c2")], [_line(""), _line("")]]}
    host.text_random_mode_map = {0: "none", 1: "integer"}
    host.text_random_int_min_edit_map = {1: _line("3")}
    host.text_random_int_max_edit_map = {1: _line("7")}
    host.multi_text_blank_radio_groups = {2: [_radio_group(1), _radio_group(4), _radio_group(0)]}
    host.multi_text_blank_integer_range_edits = {2: [(_line(""), _line("")), (_line("1"), _line("9"))]}
    host.multi_text_blank_ai_checkboxes = {2: [_Check(True), _Check(False)]}
    host.ai_check_map = {0: _Check(True), 1: _Check(True)}
    host.attached_select_slider_map = {
        0: [
            {
                "option_index": 1,
                "option_text": "选项",
                "select_options": ["A", "B"],
                "sliders": [_Slider(0), _Slider(4)],
            }
        ]
    }
    host.bias_preset_map = {0: _Combo("left"), 1: [_Segment("center"), _Combo("right")]}

    assert builder.get_results(host)[0] == [10, 0]
    assert builder.get_results(host)[1] == [[0, 5], [2, 0]]
    assert builder.get_text_results(host)[0] == ["A"]
    assert builder.get_text_results(host)[1] == ["r1||c2"]
    assert builder.get_text_random_modes(host) == {0: "none", 1: "integer"}
    assert builder.get_text_random_int_ranges(host) == {1: [3, 7]}
    assert builder.get_multi_text_blank_modes(host) == {2: ["name", "integer", "none"]}
    assert builder.get_multi_text_blank_int_ranges(host) == {2: [[], [1, 9]]}
    assert builder.get_multi_text_blank_ai_flags(host) == {2: [True, False]}
    assert builder.get_ai_flags(host) == {0: True, 1: False}
    assert builder.get_attached_select_results(host)[0][0]["weights"] == [0, 4]
    assert builder.get_bias_presets(host) == {0: "left", 1: ["center", "right"]}
    assert builder.get_dimensions(host) == {0: "体验"}


def test_wizard_result_builder_option_fill_modes_and_defaults(qtbot) -> None:
    host = _Host()
    host.text_edit_map = {0: [_line(""), _line("  ")]}
    host.option_fill_state_map = {
        0: {
            0: {"ai_cb": _Check(True), "group": _radio_group(0), "edit": _line("manual")},
            1: {"group": _radio_group(1)},
            2: {"group": _radio_group(2)},
            3: {"group": _radio_group(3)},
            4: {"group": _radio_group(4), "min_edit": _line("5"), "max_edit": _line("9")},
            5: {"group": _radio_group(0), "edit": _line("  custom  ")},
            6: {"group": _radio_group(0), "edit": _line("")},
        }
    }

    assert builder.get_text_results(host)[0] == ["无"]
    values = builder.get_option_fill_results(host)[0]
    assert values[0] == OPTION_FILL_AI_TOKEN
    assert values[1] == "__RANDOM_NAME__"
    assert values[2] == "__RANDOM_MOBILE__"
    assert values[3] == "__RANDOM_ID_CARD__"
    assert values[4] == "__RANDOM_INT__:5:9"
    assert values[5] == "custom"
    assert values[6] is None


def test_wizard_result_builder_rejects_zero_weight_groups() -> None:
    host = _Host()
    host.slider_map = {0: [_Slider(0), _Slider(-1)]}
    try:
        builder.get_results(host)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "选项配比不能全为0" in str(exc)

    host.slider_map = {}
    host.matrix_row_slider_map = {0: [[_Slider(0), _Slider(0)]]}
    try:
        builder.get_results(host)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "第1行配比不能全为0" in str(exc)

    host.matrix_row_slider_map = {}
    host.attached_select_slider_map = {0: [{"option_index": 2, "option_text": "", "sliders": [_Slider(0)]}]}
    try:
        builder.get_attached_select_results(host)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "第3项" in str(exc)


def test_wizard_validation_random_integer_and_weights(qtbot) -> None:
    host = _Host()
    host.text_random_mode_map = {0: "integer"}
    host.text_random_int_min_edit_map = {0: _line("")}
    host.text_random_int_max_edit_map = {0: _line("5")}
    assert validation.validate_random_integer_inputs(host) is False
    assert "随机整数范围未填写完整" in host.errors[-1][0]

    host = _Host()
    host.multi_text_blank_radio_groups = {0: [_radio_group(4)]}
    host.multi_text_blank_integer_range_edits = {0: [(_line(""), _line(""))]}
    assert validation.validate_random_integer_inputs(host) is False
    assert "填空1随机整数范围未填写完整" in host.errors[-1][0]

    host = _Host()
    host.option_fill_state_map = {0: {2: {"group": _radio_group(4), "min_edit": _line(""), "max_edit": _line("9")}}}
    assert validation.validate_random_integer_inputs(host) is False
    assert "第3个附加填空随机整数范围未填写完整" in host.errors[-1][0]

    host = _Host()
    host.option_fill_state_map = {0: {0: {"ai_cb": _Check(True), "group": _radio_group(4)}}}
    assert validation.validate_random_integer_inputs(host) is True

    host.slider_map = {0: [_Slider(0)]}
    assert validation.validate_non_zero_weights(host) is False
    assert "选项配比不能全为0" in host.errors[-1][0]

    host = _Host()
    host.matrix_row_slider_map = {0: [[_Slider(0)]]}
    assert validation.validate_non_zero_weights(host) is False
    assert "第1行" in host.errors[-1][0]

    host = _Host()
    host.attached_select_slider_map = {0: [{"option_text": "嵌入选项", "sliders": [_Slider(0)]}]}
    assert validation.validate_before_accept(host) is False
    assert "嵌入选项" in host.errors[-1][0]

    host = _Host()
    host.slider_map = {0: [_Slider(1)]}
    host.matrix_row_slider_map = {1: [[_Slider(0), _Slider(2)]]}
    host.attached_select_slider_map = {2: [{"sliders": [_Slider(1)]}]}
    assert validation.validate_before_accept(host) is True
