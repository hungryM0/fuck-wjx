from __future__ import annotations

from PySide6.QtWidgets import QWidget

from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.strategy.question_selector_dialog import QuestionSelectorDialog
from software.ui.pages.workbench.strategy.rule_dialog import (
    ConditionRuleDialog,
    build_question_label,
    normalize_question_type_code,
    to_int,
    to_int_list,
)


def _questions() -> list[SurveyQuestionMeta]:
    return [
        SurveyQuestionMeta(num=1, title="性别", type_code="3", option_texts=["男", "女"]),
        SurveyQuestionMeta(num=2, title="满意度", type_code="4", option_texts=["高", "低"]),
        SurveyQuestionMeta(
            num=3,
            title="矩阵",
            type_code="6",
            row_texts=["服务", "价格"],
            option_texts=["好", "差"],
        ),
        SurveyQuestionMeta(num=4, title="填空", type_code="1", option_texts=[]),
    ]


def _select_combo_data(combo, value: int) -> None:
    idx = combo.findData(value)
    assert idx >= 0
    combo.setCurrentIndex(idx)


def _dialog_parent(qtbot) -> QWidget:
    parent = QWidget()
    parent.resize(960, 720)
    qtbot.addWidget(parent)
    return parent


def test_rule_dialog_helpers_normalize_mixed_values() -> None:
    assert to_int("12") == 12
    assert to_int("bad", 5) == 5
    assert to_int_list(["2", -1, "x", 2, 0]) == [0, 2]
    assert normalize_question_type_code(None) == ""
    assert build_question_label(SurveyQuestionMeta(num=1, title="", type_code="5", is_rating=True)) == "第1题 [评价题]"


def test_question_selector_filters_and_returns_unique_selected_indices(qtbot) -> None:
    dialog = QuestionSelectorDialog(
        "添加题目",
        [
            {"question_num": 1, "title": "年龄", "type_label": "填空", "group_name": "人口", "entry_index": 3},
            {"question_num": 2, "title": "满意度", "type_label": "单选", "entry_index": 1},
            {"question_num": 3, "title": "满意度复核", "type_label": "单选", "entry_index": 1},
        ],
    )
    qtbot.addWidget(dialog)

    dialog._on_search("满意")
    assert dialog.table.rowCount() == 2

    dialog.table.selectRow(0)
    dialog.table.selectRow(1)
    assert dialog.validate() is True
    assert dialog.get_selected_indices() == [1]

    dialog._on_search("年龄")
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 3).text() == "人口"


def test_condition_rule_dialog_builds_valid_rule_and_preserves_existing_id(qtbot) -> None:
    parent = _dialog_parent(qtbot)
    dialog = ConditionRuleDialog(
        _questions(),
        parent=parent,
        rule_data={
            "id": "rule-1",
            "condition_question_num": 1,
            "condition_option_indices": [0],
            "target_question_num": 2,
            "target_option_indices": [1],
            "condition_mode": "not_selected",
            "action_mode": "must_not_select",
        },
    )

    rule = dialog._build_rule()

    assert rule is not None
    assert rule["id"] == "rule-1"
    assert rule["condition_question_num"] == 1
    assert rule["condition_mode"] == "not_selected"
    assert rule["target_question_num"] == 2
    assert rule["action_mode"] == "must_not_select"
    assert rule["target_option_indices"] == [1]


def test_condition_rule_dialog_matrix_rows_and_validation_failures(monkeypatch, qtbot) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(ConditionRuleDialog, "_warn", lambda self, message: warnings.append(message))
    parent = _dialog_parent(qtbot)
    dialog = ConditionRuleDialog(_questions(), parent=parent)

    assert dialog._build_rule() is None
    assert warnings[-1] == "请先选择条件题目"

    _select_combo_data(dialog.condition_question_combo, 3)
    dialog._on_condition_question_changed()
    assert not dialog._condition_row_widget.isHidden()
    assert dialog.condition_row_combo.count() == 3
    assert dialog._build_rule() is None
    assert warnings[-1] == "请先选择目标题目"

    _select_combo_data(dialog.target_question_combo, 2)
    dialog._on_target_question_changed()
    assert dialog._build_rule() is None
    assert warnings[-1] == "仅支持前置条件：条件题号必须小于目标题号"

    _select_combo_data(dialog.condition_question_combo, 1)
    dialog._on_condition_question_changed()
    _select_combo_data(dialog.target_question_combo, 3)
    dialog._on_target_question_changed()
    assert dialog._build_rule() is None
    assert warnings[-1] == "请先选择目标行"

    _select_combo_data(dialog.target_row_combo, 0)
    dialog._on_target_row_changed()
    assert dialog._build_rule() is None
    assert warnings[-1] == "请至少勾选一个条件选项"

    dialog._condition_checks[0].setChecked(True)
    assert dialog._build_rule() is None
    assert warnings[-1] == "请至少勾选一个目标选项"

    dialog._target_checks[1].setChecked(True)
    rule = dialog._build_rule()
    assert rule is not None
    assert rule["condition_question_num"] == 1
    assert rule["target_question_num"] == 3
    assert rule["target_row_index"] == 0
    assert rule["condition_option_indices"] == [0]
    assert rule["target_option_indices"] == [1]
