"""题目策略页：条件规则 + 维度分组。"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)
from qfluentwidgets import (
    BodyLabel,
    HorizontalSeparator,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SegmentedWidget,
    TableWidget,
)

from software.core.questions.consistency import sanitize_answer_rules

from .dimension_panel import DimensionGroupingPanel
from .rule_dialog import (
    ACTION_MODE_LABELS,
    ALLOWED_RULE_TYPE_CODES,
    CONDITION_MODE_LABELS,
    ConditionRuleDialog,
    build_question_label,
    normalize_question_type_code,
    to_int,
    to_int_list,
)


class ConditionRulePanel(QWidget):
    """条件规则列表面板。"""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: List[Dict[str, Any]] = []
        self._questions_info: List[Dict[str, Any]] = []
        self._question_map: Dict[int, Dict[str, Any]] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(BodyLabel("按前题答案去约束后题选项。规则列表里越靠后，冲突时优先级越高。", self))

        btn_row = QHBoxLayout()
        self.add_btn = PrimaryPushButton("新增条件规则", self)
        self.edit_btn = PushButton("编辑选中", self)
        self.del_btn = PushButton("删除选中", self)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.table = TableWidget(self)
        self.table.setRowCount(0)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["条件题目", "条件类型", "条件选项", "目标题目", "动作类型", "目标选项"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(420)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        header.setSectionResizeMode(3, header.ResizeMode.Stretch)
        header.setSectionResizeMode(4, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, header.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.add_btn.clicked.connect(self._on_add_rule)
        self.edit_btn.clicked.connect(self._on_edit_rule)
        self.del_btn.clicked.connect(self._on_delete_rule)
        self.table.doubleClicked.connect(lambda _idx: self._on_edit_rule())

    def set_questions_info(self, info: Sequence[Dict[str, Any]]) -> None:
        self._questions_info = list(info or [])
        self._question_map.clear()
        for question in self._questions_info:
            q_num = to_int(question.get("num"), 0)
            if q_num > 0:
                self._question_map[q_num] = dict(question)
        self._rules = self._sanitize_rules(self._rules, show_removed_toast=True)
        self._refresh_table()

    def set_rules(self, rules: Sequence[Dict[str, Any]]) -> None:
        self._rules = self._sanitize_rules(list(rules or []), show_removed_toast=True)
        self._refresh_table()

    def get_rules(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._rules)

    def _sanitize_rules(self, rules: List[Dict[str, Any]], show_removed_toast: bool = False) -> List[Dict[str, Any]]:
        sanitized, stats = sanitize_answer_rules(rules or [], self._questions_info or None)
        if show_removed_toast and stats.get("unsupported", 0):
            count = int(stats["unsupported"])
            suffix = "已自动移除 1 条不再支持的条件规则" if count == 1 else f"已自动移除 {count} 条不再支持的条件规则"
            self._toast(suffix, "warning")
        return sanitized

    def _toast(self, message: str, level: str = "warning") -> None:
        parent = self.window() or self
        if level == "error":
            InfoBar.error("", message, parent=parent, position=InfoBarPosition.TOP, duration=2200)
            return
        if level == "success":
            InfoBar.success("", message, parent=parent, position=InfoBarPosition.TOP, duration=1800)
            return
        InfoBar.warning("", message, parent=parent, position=InfoBarPosition.TOP, duration=2200)

    def _selected_rows(self) -> List[int]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        return sorted({idx.row() for idx in selection.selectedRows()})

    def _get_selectable_questions(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for question in self._questions_info:
            type_code = normalize_question_type_code(question.get("type_code"))
            if type_code not in ALLOWED_RULE_TYPE_CODES:
                continue
            result.append(question)
        return result

    def _on_add_rule(self) -> None:
        selectable = self._get_selectable_questions()
        if len(selectable) < 2:
            self._toast("当前问卷可用题目不足（需要至少 2 道单选/多选/量表/评价/矩阵题）", "warning")
            return
        dialog = ConditionRuleDialog(self._questions_info, parent=self.window() or self)
        if dialog.exec() != ConditionRuleDialog.DialogCode.Accepted:
            return
        rule = dialog.get_rule()
        if not rule:
            return
        self._rules.append(rule)
        self._refresh_table()
        self.changed.emit()

    def _on_edit_rule(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self._toast("请先选择要编辑的条件规则", "warning")
            return
        if len(rows) > 1:
            self._toast("一次只能编辑一条条件规则", "warning")
            return
        row = rows[0]
        if row < 0 or row >= len(self._rules):
            return
        dialog = ConditionRuleDialog(
            self._questions_info,
            parent=self.window() or self,
            rule_data=self._rules[row],
        )
        if dialog.exec() != ConditionRuleDialog.DialogCode.Accepted:
            return
        rule = dialog.get_rule()
        if not rule:
            return
        self._rules[row] = rule
        self._refresh_table()
        self.changed.emit()

    def _on_delete_rule(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self._toast("请先选择要删除的条件规则", "warning")
            return
        count = len(rows)
        msg = MessageBox(
            "确认删除",
            f"确定要删除选中的 {count} 条条件规则吗？此操作不可撤销。",
            self.window() or self,
        )
        msg.yesButton.setText("确认删除")
        msg.cancelButton.setText("取消")
        if not msg.exec():
            return
        for row in sorted(rows, reverse=True):
            if 0 <= row < len(self._rules):
                self._rules.pop(row)
        self._refresh_table()
        self.changed.emit()

    def _question_label_by_num(self, question_num: int, row_index: Optional[int] = None) -> str:
        info = self._question_map.get(question_num)
        if not info:
            return f"第{question_num}题（题目不存在）"
        base = build_question_label(info)
        if row_index is not None:
            raw_row_texts = info.get("row_texts")
            row_texts: List[Any] = raw_row_texts if isinstance(raw_row_texts, list) else []
            if row_index < len(row_texts):
                row_label = str(row_texts[row_index] or "").strip() or f"第{row_index + 1}行"
            else:
                row_label = f"第{row_index + 1}行"
            return f"{base} / {row_label}"
        return base

    def _option_label_text(self, question_num: int, option_indices: List[int]) -> str:
        info = self._question_map.get(question_num) or {}
        raw_texts = info.get("option_texts")
        option_texts: List[Any] = raw_texts if isinstance(raw_texts, list) else []
        if not option_indices:
            return "-"
        labels: List[str] = []
        for idx in option_indices:
            if isinstance(idx, int) and 0 <= idx < len(option_texts):
                text = str(option_texts[idx] or "").strip() or f"选项{idx + 1}"
                labels.append(f"{idx + 1}. {text}")
            else:
                labels.append(f"{idx + 1}")
        return "；".join(labels)

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for row, rule in enumerate(self._rules):
            self.table.insertRow(row)
            condition_num = to_int(rule.get("condition_question_num"), 0)
            target_num = to_int(rule.get("target_question_num"), 0)
            condition_mode = str(rule.get("condition_mode") or "selected").strip()
            action_mode = str(rule.get("action_mode") or "must_select").strip()
            condition_options = to_int_list(rule.get("condition_option_indices"))
            target_options = to_int_list(rule.get("target_option_indices"))
            raw_cri = rule.get("condition_row_index")
            condition_row_index: Optional[int] = to_int(raw_cri, -1) if raw_cri is not None else None
            if condition_row_index is not None and condition_row_index < 0:
                condition_row_index = None
            raw_tri = rule.get("target_row_index")
            target_row_index: Optional[int] = to_int(raw_tri, -1) if raw_tri is not None else None
            if target_row_index is not None and target_row_index < 0:
                target_row_index = None

            self.table.setItem(row, 0, QTableWidgetItem(self._question_label_by_num(condition_num, condition_row_index)))
            self.table.setItem(row, 1, QTableWidgetItem(CONDITION_MODE_LABELS.get(condition_mode, condition_mode)))
            self.table.setItem(row, 2, QTableWidgetItem(self._option_label_text(condition_num, condition_options)))
            self.table.setItem(row, 3, QTableWidgetItem(self._question_label_by_num(target_num, target_row_index)))
            self.table.setItem(row, 4, QTableWidgetItem(ACTION_MODE_LABELS.get(action_mode, action_mode)))
            self.table.setItem(row, 5, QTableWidgetItem(self._option_label_text(target_num, target_options)))


class QuestionStrategyPage(ScrollArea):
    """题目策略页。"""

    strategyChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        switch_row = QHBoxLayout()
        self.segmented = SegmentedWidget(self.view)
        self.segmented.addItem(routeKey="rules", text="条件规则")
        self.segmented.addItem(routeKey="dimensions", text="维度分组")
        self.segmented.setFixedHeight(52)
        self.segmented.setItemFontSize(16)
        self.segmented.setStyleSheet(
            "SegmentedItem{min-width:96px; min-height:34px; padding:10px 24px;}"
        )
        switch_row.addWidget(self.segmented)
        switch_row.addStretch(1)
        layout.addLayout(switch_row)
        self.section_separator = HorizontalSeparator(self.view)
        layout.addWidget(self.section_separator)

        self.stack = QStackedWidget(self.view)
        self.rule_panel = ConditionRulePanel(self.stack)
        self.dimension_panel = DimensionGroupingPanel(self.stack)
        self.stack.addWidget(self.rule_panel)
        self.stack.addWidget(self.dimension_panel)
        layout.addWidget(self.stack, 1)

        self.segmented.currentItemChanged.connect(self._on_segment_changed)
        self.rule_panel.changed.connect(self.strategyChanged.emit)
        self.dimension_panel.changed.connect(self.strategyChanged.emit)
        self.segmented.setCurrentItem("rules")
        self.stack.setCurrentWidget(self.rule_panel)

    def _on_segment_changed(self, route_key: str) -> None:
        if route_key == "dimensions":
            self.stack.setCurrentWidget(self.dimension_panel)
            return
        self.stack.setCurrentWidget(self.rule_panel)

    def set_questions_info(self, info: Sequence[Dict[str, Any]]) -> None:
        questions = list(info or [])
        self.rule_panel.set_questions_info(questions)
        self.dimension_panel.set_entries(self.dimension_panel._entries, questions)

    def set_entries(self, entries: Sequence[Any], info: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        self.dimension_panel.set_entries(entries, info)

    def set_rules(self, rules: Sequence[Dict[str, Any]]) -> None:
        self.rule_panel.set_rules(rules)

    def get_rules(self) -> List[Dict[str, Any]]:
        return self.rule_panel.get_rules()

    def set_dimension_groups(self, groups: Sequence[Any]) -> None:
        self.dimension_panel.set_dimension_groups(groups)

    def get_dimension_groups(self) -> List[str]:
        return self.dimension_panel.get_dimension_groups()
