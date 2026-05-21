from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, EditableComboBox, LineEdit

from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.question_editor.constants import _get_entry_type_label
from software.ui.pages.workbench.question_editor.wizard_cards import WizardCardsMixin
from software.ui.pages.workbench.question_editor.wizard_logic_tree import LogicTreeState
from software.ui.pages.workbench.question_editor.wizard_sections_location import WizardSectionsLocationMixin


class _Host(WizardCardsMixin, WizardSectionsLocationMixin):
    def __init__(self) -> None:
        self.info = [
            SurveyQuestionMeta(
                num=11,
                display_num=21,
                title="题干",
                option_texts=["甲", ""],
                row_texts=["", "第二行"],
                question_media=[
                    {"kind": "image", "scope": "title", "source_url": "https://example.com/title.png", "label": ""},
                    {"kind": "image", "scope": "option", "index": 1, "source_url": "https://example.com/opt.png", "label": ""},
                    {"kind": "image", "scope": "row", "index": 0, "source_url": "https://example.com/row.png", "label": ""},
                ],
                slider_min="3",
                slider_max="2",
                required=True,
                has_display_condition=True,
                has_dependent_display_logic=True,
                has_jump=True,
            )
        ]
        self.entries = [QuestionEntry("single", [1, 2], question_num=11)]
        self.slider_map = {}
        self.matrix_row_slider_map = {}
        self.text_edit_map = {}
        self.text_add_btn_map = {}
        self.location_combo_map = {}
        self.text_random_mode_map = {}
        self.text_random_int_min_edit_map = {}
        self.text_random_int_max_edit_map = {}
        self.multi_text_blank_integer_range_edits = {}
        self.option_fill_state_map = {}
        self.attached_select_slider_map = {}
        self.bias_preset_map = {}
        self._entry_snapshots = [QuestionEntry("single", [9, 8], question_num=88, attached_option_selects=[{"x": 1}])]
        self._logic_tree_state = LogicTreeState(
            has_unknown_logic=False,
            inbound_summary={0: "来自第1题"},
            outbound_summary={0: "跳到第2题"},
        )

    def _navigate_to_question(self, question_idx: int, animate: bool = False) -> None:
        del question_idx, animate

    def get_multi_text_blank_modes(self):
        return {}

    def _refresh_ratio_preview_label(self, label, sliders, option_names, prefix: str) -> None:
        label.setText(f"{prefix}{','.join(option_names)}={sum(slider.value() for slider in sliders)}")


class WizardCardsHelperTests:
    def test_helper_methods_cover_weights_labels_media_badges_and_restore(self, qtbot) -> None:
        host = _Host()
        parent = QWidget()
        qtbot.addWidget(parent)

        assert host._resolve_matrix_weights(QuestionEntry("matrix", [[0, 2], [3]], custom_weights=[[1, -2, 9]], rows=2), 2, 2) == [[1.0, 0.0], [1.0, 0.0]]
        assert host._resolve_matrix_weights(QuestionEntry("matrix", [0, 0, 3], rows=2), 2, 2) == [[1.0, 1.0], [1.0, 1.0]]
        assert host._format_question_label(0) == "第21题"
        assert host._format_compact_question_label(0) == "21."
        assert host._media_items_for(0, "title")[0]["scope"] == "title"
        assert host._display_text_for_option(0, 1, "") == "选项 2"
        assert host._display_text_for_row(0, 0, "") == "第 1 行"
        assert host._inbound_summary_for(0) == "来自第1题"
        assert host._outbound_summary_for(0) == "跳到第2题"
        assert host._resolve_slider_bounds(0, QuestionEntry("slider", [1], custom_weights=[8])) == (3, 8)

        badges = host._build_header_badges(0, QuestionEntry("single", [1], question_num=11), host.info[0], parent)
        assert [badge.text() for badge in badges] == ["单选题", "必答", "图片题", "条件显示", "控制后续", "跳题"]

        host.entries[0].question_num = 999
        host.entries[0].attached_option_selects = []
        host._restore_entries()
        assert host.entries[0].question_num == 88
        assert host.entries[0].attached_option_selects == [{"x": 1}]

    def test_location_entry_uses_location_label_and_skips_text_controls(self, qtbot) -> None:
        host = _Host()
        host.info[0] = SurveyQuestionMeta(
            num=1,
            title="您所在的地区",
            type_code="1",
            is_text_like=True,
            is_location=True,
            required=True,
        )
        host.entries[0] = QuestionEntry(
            "text",
            [1.0],
            texts=["无"],
            question_num=1,
            question_title="您所在的地区",
            is_location=True,
        )
        parent = QWidget()
        qtbot.addWidget(parent)

        assert _get_entry_type_label(host.entries[0]) == "地区题"
        card = host._build_entry_card(0, host.entries[0], parent)
        qtbot.addWidget(card)
        badges = host._build_header_badges(0, host.entries[0], host.info[0], parent)

        assert badges[0].text() == "地区题"
        assert host._has_content is True
        assert 0 not in host.text_edit_map
        assert 0 not in host.text_add_btn_map
        assert all(edit.placeholderText() != "候选答案" for edit in card.findChildren(LineEdit))
        assert len(card.findChildren(ComboBox)) == 2
        assert len(card.findChildren(EditableComboBox)) == 1
        assert 0 in host.location_combo_map

    def test_build_attached_select_section_populates_slider_map(self, qtbot) -> None:
        host = _Host()
        host.entries[0] = QuestionEntry(
            "single",
            [1, 2],
            question_num=11,
            attached_option_selects=[
                {
                    "option_index": 1,
                    "option_text": "很长很长的选项文本",
                    "select_options": ["A", "B"],
                    "weights": [0, 4],
                },
                {"option_index": 2, "option_text": "坏数据", "select_options": []},
            ],
        )
        card = QWidget()
        layout = QVBoxLayout(card)
        qtbot.addWidget(card)

        host._build_attached_select_section(0, host.entries[0], card, layout)

        stored = host.attached_select_slider_map[0][0]
        assert stored["option_index"] == 1
        assert stored["select_options"] == ["A", "B"]
        assert [slider.value() for slider in stored["sliders"]] == [0, 4]


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
