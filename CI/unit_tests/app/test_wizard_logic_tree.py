from __future__ import annotations

from software.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    LOGIC_PARSE_STATUS_UNKNOWN,
    SurveyQuestionMeta,
)
from software.ui.pages.workbench.question_editor.wizard_logic_tree import (
    build_logic_tree_state,
)


def test_build_logic_tree_state_builds_inbound_outbound_and_search_text() -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="入口题",
            page=1,
            option_texts=["A", "B"],
            has_dependent_display_logic=True,
            controls_display_targets=[
                {"condition_option_indices": [0], "target_question_num": 2}
            ],
            has_jump=True,
            jump_rules=[{"option_index": 1, "jumpto": 9}],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="条件题",
            page=1,
            option_texts=["是", "否"],
            has_display_condition=True,
            display_conditions=[
                {"condition_question_num": 1, "condition_option_indices": [0]}
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]

    state = build_logic_tree_state(info)

    assert state.has_unknown_logic is False
    assert state.page_map == {1: [0, 1]}
    assert "第1题选中“A”" in state.inbound_summary[1]
    assert "显示 第2题" in state.outbound_summary[0]
    assert "跳转 结束" in state.outbound_summary[0]
    assert len(state.relations[0]) == 2
    assert "入口题" in state.search_text[0]
    assert "第1题选中“a”" in state.search_text[1]


def test_build_logic_tree_state_marks_unknown_logic() -> None:
    info = [
        SurveyQuestionMeta(num=1, title="普通题", page=1, logic_parse_status=LOGIC_PARSE_STATUS_UNKNOWN)
    ]

    state = build_logic_tree_state(info)

    assert state.has_unknown_logic is True
    assert state.inbound_summary[0] == "始终显示"
    assert state.outbound_summary[0] == "无"
