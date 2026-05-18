from __future__ import annotations

from PySide6.QtWidgets import QTreeWidgetItem

from software.core.questions.config import QuestionEntry
from software.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    LOGIC_PARSE_STATUS_UNKNOWN,
    SurveyQuestionMeta,
)
from software.ui.pages.workbench.question_editor.wizard_dialog import (
    QuestionWizardDialog,
)


def _build_entries() -> list[QuestionEntry]:
    return [
        QuestionEntry(
            question_type="single",
            probabilities=[1, 1],
            texts=None,
            rows=1,
            option_count=2,
            distribution_mode="custom",
            custom_weights=[50, 50],
            question_num=1,
        ),
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["默认值"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=2,
        ),
    ]


def test_question_wizard_dialog_shows_logic_view_and_switches_question(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["显示下一题", "结束"],
            has_dependent_display_logic=True,
            controls_display_targets=[
                {"condition_option_indices": [0], "target_question_num": 2}
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="第二题",
            page=1,
            has_display_condition=True,
            display_conditions=[
                {"condition_question_num": 1, "condition_option_indices": [0]}
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    assert dlg._content_splitter is not None
    assert dlg._content_splitter.count() == 2
    assert dlg._content_splitter.handleWidth() >= 6
    assert dlg._current_view_mode == "logic"

    page_item = dlg._tree_widget.topLevelItem(0)
    question_item = page_item.child(1)
    dlg._on_tree_item_clicked(question_item, 0)
    assert dlg._current_question_idx == 1

    relation_item = page_item.child(0).child(0)
    assert isinstance(relation_item, QTreeWidgetItem)
    dlg._on_tree_item_clicked(relation_item, 0)
    assert dlg._current_question_idx == 1


def test_question_wizard_dialog_hides_logic_view_when_unknown(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_UNKNOWN,
        )
    ]
    entries = [
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["a"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    assert dlg._current_view_mode == "sequential"
