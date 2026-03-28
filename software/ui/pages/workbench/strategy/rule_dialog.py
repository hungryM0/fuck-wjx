"""条件规则弹窗。"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    ScrollArea,
    SubtitleLabel,
)

from software.core.questions.consistency import normalize_rule_dict

ALLOWED_RULE_TYPE_CODES = {"3", "4", "5", "6"}
RULE_TYPE_CODE_LABELS = {"3": "单选题", "4": "多选题", "5": "量表题", "6": "矩阵题"}
CONDITION_MODE_LABELS = {
    "selected": "选择了以下选项",
    "not_selected": "未选择以下选项",
}
ACTION_MODE_LABELS = {
    "must_select": "一定选择以下选项",
    "must_not_select": "一定不选择以下选项",
}


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def to_int_list(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
    result: List[int] = []
    seen = set()
    for item in values:
        try:
            idx = int(item)
        except Exception:
            continue
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)


def normalize_question_type_code(value: Any) -> str:
    try:
        return str(value or "").strip()
    except Exception:
        return ""


def build_question_label(question: Dict[str, Any]) -> str:
    q_num = to_int(question.get("num"), 0)
    title = str(question.get("title") or "").strip()
    type_code = normalize_question_type_code(question.get("type_code"))
    if type_code == "5" and question.get("is_rating"):
        type_label = "评价题"
    else:
        type_label = RULE_TYPE_CODE_LABELS.get(type_code, "")
    suffix = f" [{type_label}]" if type_label else ""
    if title:
        return f"第{q_num}题：{title}{suffix}"
    return f"第{q_num}题{suffix}"


def clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        if child_layout is not None:
            while child_layout.count():
                nested = child_layout.takeAt(0)
                if nested is None:
                    continue
                nested_widget = nested.widget()
                if nested_widget is not None:
                    nested_widget.hide()
                    nested_widget.deleteLater()


class ConditionRuleDialog(QDialog):
    """新增/编辑条件规则弹窗。"""

    def __init__(
        self,
        questions_info: List[Dict[str, Any]],
        parent=None,
        rule_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("添加条件规则" if not rule_data else "编辑条件规则")
        self.resize(860, 760)
        self._rule_data = copy.deepcopy(rule_data) if rule_data else None
        self._result_rule: Optional[Dict[str, Any]] = None
        self._questions_info = list(questions_info or [])
        self._question_map: Dict[int, Dict[str, Any]] = {}
        self._condition_checks: List[CheckBox] = []
        self._target_checks: List[CheckBox] = []
        self._build_question_map()
        self._build_ui()
        self._bind_events()
        self._apply_initial_rule()

    def _build_question_map(self) -> None:
        self._question_map.clear()
        for item in self._questions_info:
            q_num = to_int(item.get("num"), 0)
            if q_num <= 0:
                continue
            type_code = normalize_question_type_code(item.get("type_code"))
            if type_code not in ALLOWED_RULE_TYPE_CODES:
                continue
            self._question_map[q_num] = item

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = SubtitleLabel("添加条件规则" if not self._rule_data else "编辑条件规则", self)
        root.addWidget(title)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        container = QWidget(self)
        scroll.setWidget(container)
        main = QVBoxLayout(container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(14)

        self._condition_card = CardWidget(container)
        condition_layout = QVBoxLayout(self._condition_card)
        condition_layout.setContentsMargins(18, 16, 18, 16)
        condition_layout.setSpacing(12)
        condition_layout.addWidget(SubtitleLabel("条件设置", self._condition_card))

        condition_question_row = QHBoxLayout()
        condition_question_row.addWidget(BodyLabel("条件题目", self._condition_card))
        condition_question_row.addSpacing(8)
        self.condition_question_combo = ComboBox(self._condition_card)
        self.condition_question_combo.setMinimumWidth(560)
        self._fill_question_combo(self.condition_question_combo)
        condition_question_row.addWidget(self.condition_question_combo, 1)
        condition_layout.addLayout(condition_question_row)

        self._condition_row_widget = QWidget(self._condition_card)
        condition_row_row = QHBoxLayout(self._condition_row_widget)
        condition_row_row.setContentsMargins(0, 0, 0, 0)
        condition_row_row.addWidget(BodyLabel("条件行", self._condition_card))
        condition_row_row.addSpacing(8)
        self.condition_row_combo = ComboBox(self._condition_card)
        self.condition_row_combo.setMinimumWidth(560)
        condition_row_row.addWidget(self.condition_row_combo, 1)
        self._condition_row_widget.hide()
        condition_layout.addWidget(self._condition_row_widget)

        condition_type_row = QHBoxLayout()
        condition_type_row.addWidget(BodyLabel("条件类型", self._condition_card))
        condition_type_row.addSpacing(8)
        self.condition_selected_radio = RadioButton("选择了以下选项", self._condition_card)
        self.condition_not_selected_radio = RadioButton("未选择以下选项", self._condition_card)
        self.condition_mode_group = QButtonGroup(self._condition_card)
        self.condition_mode_group.addButton(self.condition_selected_radio)
        self.condition_mode_group.addButton(self.condition_not_selected_radio)
        self.condition_selected_radio.setChecked(True)
        condition_type_row.addWidget(self.condition_selected_radio)
        condition_type_row.addWidget(self.condition_not_selected_radio)
        condition_type_row.addStretch(1)
        condition_layout.addLayout(condition_type_row)

        condition_layout.addWidget(BodyLabel("条件选项", self._condition_card))
        self.condition_options_widget = QWidget(self._condition_card)
        self.condition_options_layout = QVBoxLayout(self.condition_options_widget)
        self.condition_options_layout.setContentsMargins(8, 4, 8, 4)
        self.condition_options_layout.setSpacing(8)
        condition_layout.addWidget(self.condition_options_widget)
        main.addWidget(self._condition_card)

        self._action_card = CardWidget(container)
        action_layout = QVBoxLayout(self._action_card)
        action_layout.setContentsMargins(18, 16, 18, 16)
        action_layout.setSpacing(12)
        action_layout.addWidget(SubtitleLabel("动作设置", self._action_card))

        target_question_row = QHBoxLayout()
        target_question_row.addWidget(BodyLabel("目标题目", self._action_card))
        target_question_row.addSpacing(8)
        self.target_question_combo = ComboBox(self._action_card)
        self.target_question_combo.setMinimumWidth(560)
        self._fill_question_combo(self.target_question_combo)
        target_question_row.addWidget(self.target_question_combo, 1)
        action_layout.addLayout(target_question_row)

        self._target_row_widget = QWidget(self._action_card)
        target_row_row = QHBoxLayout(self._target_row_widget)
        target_row_row.setContentsMargins(0, 0, 0, 0)
        target_row_row.addWidget(BodyLabel("目标行", self._action_card))
        target_row_row.addSpacing(8)
        self.target_row_combo = ComboBox(self._action_card)
        self.target_row_combo.setMinimumWidth(560)
        target_row_row.addWidget(self.target_row_combo, 1)
        self._target_row_widget.hide()
        action_layout.addWidget(self._target_row_widget)

        action_type_row = QHBoxLayout()
        action_type_row.addWidget(BodyLabel("动作类型", self._action_card))
        action_type_row.addSpacing(8)
        self.must_select_radio = RadioButton("一定选择以下选项", self._action_card)
        self.must_not_select_radio = RadioButton("一定不选择以下选项", self._action_card)
        self.action_mode_group = QButtonGroup(self._action_card)
        self.action_mode_group.addButton(self.must_select_radio)
        self.action_mode_group.addButton(self.must_not_select_radio)
        self.must_select_radio.setChecked(True)
        action_type_row.addWidget(self.must_select_radio)
        action_type_row.addWidget(self.must_not_select_radio)
        action_type_row.addStretch(1)
        action_layout.addLayout(action_type_row)

        action_layout.addWidget(BodyLabel("目标选项", self._action_card))
        self.target_options_widget = QWidget(self._action_card)
        self.target_options_layout = QVBoxLayout(self.target_options_widget)
        self.target_options_layout.setContentsMargins(8, 4, 8, 4)
        self.target_options_layout.setSpacing(8)
        action_layout.addWidget(self.target_options_widget)
        main.addWidget(self._action_card)

        main.addStretch(1)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = PushButton("取消", self)
        self.ok_btn = PrimaryPushButton("确定", self)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

    def _fill_question_combo(self, combo: ComboBox) -> None:
        combo.clear()
        combo.addItem("请选择题目", userData=None)
        sorted_questions = sorted(self._question_map.values(), key=lambda x: to_int(x.get("num"), 0))
        for question in sorted_questions:
            combo.addItem(build_question_label(question), userData=to_int(question.get("num"), 0))

    def _bind_events(self) -> None:
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_confirm_clicked)
        self.condition_question_combo.currentIndexChanged.connect(self._on_condition_question_changed)
        self.target_question_combo.currentIndexChanged.connect(self._on_target_question_changed)
        self.condition_row_combo.currentIndexChanged.connect(self._on_condition_row_changed)
        self.target_row_combo.currentIndexChanged.connect(self._on_target_row_changed)

    def _apply_initial_rule(self) -> None:
        self._render_condition_options([], None, None)
        self._render_target_options([], None, None)
        if not self._rule_data:
            return
        condition_num = to_int(self._rule_data.get("condition_question_num"), -1)
        target_num = to_int(self._rule_data.get("target_question_num"), -1)
        condition_mode = str(self._rule_data.get("condition_mode") or "selected").strip()
        action_mode = str(self._rule_data.get("action_mode") or "must_select").strip()
        condition_indices = to_int_list(self._rule_data.get("condition_option_indices"))
        target_indices = to_int_list(self._rule_data.get("target_option_indices"))
        raw_cri = self._rule_data.get("condition_row_index")
        condition_row_index: Optional[int] = to_int(raw_cri, -1) if raw_cri is not None else None
        if condition_row_index is not None and condition_row_index < 0:
            condition_row_index = None
        raw_tri = self._rule_data.get("target_row_index")
        target_row_index: Optional[int] = to_int(raw_tri, -1) if raw_tri is not None else None
        if target_row_index is not None and target_row_index < 0:
            target_row_index = None

        condition_idx = self.condition_question_combo.findData(condition_num)
        if condition_idx >= 0:
            self.condition_question_combo.blockSignals(True)
            self.condition_question_combo.setCurrentIndex(condition_idx)
            self.condition_question_combo.blockSignals(False)
        target_idx = self.target_question_combo.findData(target_num)
        if target_idx >= 0:
            self.target_question_combo.blockSignals(True)
            self.target_question_combo.setCurrentIndex(target_idx)
            self.target_question_combo.blockSignals(False)

        self._update_row_selector(self.condition_question_combo, self._condition_row_widget, self.condition_row_combo)
        self._update_row_selector(self.target_question_combo, self._target_row_widget, self.target_row_combo)
        if condition_row_index is not None:
            row_idx = self.condition_row_combo.findData(condition_row_index)
            if row_idx >= 0:
                self.condition_row_combo.blockSignals(True)
                self.condition_row_combo.setCurrentIndex(row_idx)
                self.condition_row_combo.blockSignals(False)
        if target_row_index is not None:
            row_idx = self.target_row_combo.findData(target_row_index)
            if row_idx >= 0:
                self.target_row_combo.blockSignals(True)
                self.target_row_combo.setCurrentIndex(row_idx)
                self.target_row_combo.blockSignals(False)

        if condition_mode == "not_selected":
            self.condition_not_selected_radio.setChecked(True)
        else:
            self.condition_selected_radio.setChecked(True)

        if action_mode == "must_not_select":
            self.must_not_select_radio.setChecked(True)
        else:
            self.must_select_radio.setChecked(True)

        self._render_condition_options(condition_indices, condition_num, condition_row_index)
        self._render_target_options(target_indices, target_num, target_row_index)

    def _on_condition_question_changed(self) -> None:
        q_num = self._get_combo_question_num(self.condition_question_combo)
        self._update_row_selector(self.condition_question_combo, self._condition_row_widget, self.condition_row_combo)
        row_index = self._get_combo_row_index(self.condition_row_combo)
        self._render_condition_options([], q_num, row_index)

    def _on_target_question_changed(self) -> None:
        q_num = self._get_combo_question_num(self.target_question_combo)
        self._update_row_selector(self.target_question_combo, self._target_row_widget, self.target_row_combo)
        row_index = self._get_combo_row_index(self.target_row_combo)
        self._render_target_options([], q_num, row_index)

    def _on_condition_row_changed(self) -> None:
        q_num = self._get_combo_question_num(self.condition_question_combo)
        row_index = self._get_combo_row_index(self.condition_row_combo)
        self._render_condition_options([], q_num, row_index)

    def _on_target_row_changed(self) -> None:
        q_num = self._get_combo_question_num(self.target_question_combo)
        row_index = self._get_combo_row_index(self.target_row_combo)
        self._render_target_options([], q_num, row_index)

    def _get_combo_question_num(self, combo: ComboBox) -> Optional[int]:
        idx = combo.currentIndex()
        if idx < 0:
            return None
        data = combo.itemData(idx)
        if data is None:
            return None
        q_num = to_int(data, -1)
        if q_num <= 0:
            return None
        return q_num

    def _get_combo_row_index(self, combo: ComboBox) -> Optional[int]:
        idx = combo.currentIndex()
        if idx < 0:
            return None
        data = combo.itemData(idx)
        if data is None:
            return None
        row_idx = to_int(data, -1)
        if row_idx < 0:
            return None
        return row_idx

    def _is_matrix_question(self, question_num: Optional[int]) -> bool:
        if not question_num:
            return False
        info = self._question_map.get(question_num) or {}
        return normalize_question_type_code(info.get("type_code")) == "6"

    def _update_row_selector(self, question_combo: ComboBox, row_widget: QWidget, row_combo: ComboBox) -> None:
        q_num = self._get_combo_question_num(question_combo)
        if q_num is not None and self._is_matrix_question(q_num):
            info = self._question_map.get(q_num) or {}
            raw_row_texts = info.get("row_texts")
            row_texts: List[Any] = raw_row_texts if isinstance(raw_row_texts, list) else []
            row_combo.clear()
            row_combo.addItem("请选择行", userData=None)
            for i, text in enumerate(row_texts):
                label = str(text or "").strip() or f"第{i + 1}行"
                row_combo.addItem(f"第{i + 1}行：{label}", userData=i)
            row_widget.show()
        else:
            row_combo.clear()
            row_widget.hide()

    def _render_condition_options(self, selected_indices: List[int], question_num: Optional[int], row_index: Optional[int]) -> None:
        self._condition_checks = self._render_option_checks(
            self.condition_options_layout,
            selected_indices,
            question_num,
            row_index,
            "请先选择条件题目",
        )

    def _render_target_options(self, selected_indices: List[int], question_num: Optional[int], row_index: Optional[int]) -> None:
        self._target_checks = self._render_option_checks(
            self.target_options_layout,
            selected_indices,
            question_num,
            row_index,
            "请先选择目标题目",
        )

    def _render_option_checks(
        self,
        layout: QVBoxLayout,
        selected_indices: List[int],
        question_num: Optional[int],
        row_index: Optional[int],
        empty_hint: str,
    ) -> List[CheckBox]:
        clear_layout(layout)
        if not question_num:
            label = BodyLabel(empty_hint, self)
            label.setStyleSheet("color: #888888;")
            layout.addWidget(label)
            return []
        info = self._question_map.get(question_num) or {}
        type_code = normalize_question_type_code(info.get("type_code"))
        if type_code == "6" and row_index is None:
            label = BodyLabel("请先选择行", self)
            label.setStyleSheet("color: #888888;")
            layout.addWidget(label)
            return []
        option_texts = info.get("option_texts") if isinstance(info.get("option_texts"), list) else []
        checks: List[CheckBox] = []
        if not option_texts:
            label = BodyLabel("该题未解析到选项，无法配置条件规则", self)
            label.setStyleSheet("color: #888888;")
            layout.addWidget(label)
            return checks
        selected_set = set(selected_indices or [])
        for idx, text in enumerate(option_texts):
            option_text = str(text or "").strip() or f"选项{idx + 1}"
            check = CheckBox(f"{idx + 1}. {option_text}", self)
            check.setChecked(idx in selected_set)
            layout.addWidget(check)
            checks.append(check)
        return checks

    def _collect_checked_indices(self, checks: List[CheckBox]) -> List[int]:
        result: List[int] = []
        for idx, check in enumerate(checks):
            if check.isChecked():
                result.append(idx)
        return result

    def _warn(self, message: str) -> None:
        InfoBar.warning("", message, parent=self, position=InfoBarPosition.TOP, duration=2200)

    def _on_confirm_clicked(self) -> None:
        rule = self._build_rule()
        if not rule:
            return
        self._result_rule = rule
        self.accept()

    def _build_rule(self) -> Optional[Dict[str, Any]]:
        condition_num = self._get_combo_question_num(self.condition_question_combo)
        target_num = self._get_combo_question_num(self.target_question_combo)
        if not condition_num:
            self._warn("请先选择条件题目")
            return None
        if not target_num:
            self._warn("请先选择目标题目")
            return None
        if condition_num == target_num:
            self._warn("条件题目和目标题目不能是同一题")
            return None
        if condition_num >= target_num:
            self._warn("仅支持前置条件：条件题号必须小于目标题号")
            return None

        condition_info = self._question_map.get(condition_num)
        target_info = self._question_map.get(target_num)
        if not condition_info or normalize_question_type_code(condition_info.get("type_code")) not in ALLOWED_RULE_TYPE_CODES:
            self._warn("条件题目类型不支持")
            return None
        if not target_info or normalize_question_type_code(target_info.get("type_code")) not in ALLOWED_RULE_TYPE_CODES:
            self._warn("目标题目类型不支持")
            return None

        condition_row_index: Optional[int] = None
        if self._is_matrix_question(condition_num):
            condition_row_index = self._get_combo_row_index(self.condition_row_combo)
            if condition_row_index is None:
                self._warn("请先选择条件行")
                return None

        target_row_index: Optional[int] = None
        if self._is_matrix_question(target_num):
            target_row_index = self._get_combo_row_index(self.target_row_combo)
            if target_row_index is None:
                self._warn("请先选择目标行")
                return None

        condition_indices = self._collect_checked_indices(self._condition_checks)
        if not condition_indices:
            self._warn("请至少勾选一个条件选项")
            return None
        target_indices = self._collect_checked_indices(self._target_checks)
        if not target_indices:
            self._warn("请至少勾选一个目标选项")
            return None

        condition_mode = "not_selected" if self.condition_not_selected_radio.isChecked() else "selected"
        action_mode = "must_not_select" if self.must_not_select_radio.isChecked() else "must_select"
        rule_id = ""
        if isinstance(self._rule_data, dict):
            rule_id = str(self._rule_data.get("id") or "").strip()
        if not rule_id:
            rule_id = uuid.uuid4().hex

        rule: Dict[str, Any] = {
            "id": rule_id,
            "condition_question_num": condition_num,
            "condition_mode": condition_mode,
            "condition_option_indices": condition_indices,
            "target_question_num": target_num,
            "action_mode": action_mode,
            "target_option_indices": target_indices,
        }
        if condition_row_index is not None:
            rule["condition_row_index"] = condition_row_index
        if target_row_index is not None:
            rule["target_row_index"] = target_row_index
        return normalize_rule_dict(rule)

    def get_rule(self) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._result_rule)
