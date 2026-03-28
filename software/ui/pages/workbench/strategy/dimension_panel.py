"""维度分组面板。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from software.app.config import DIMENSION_UNGROUPED, PRESET_DIMENSIONS
from software.core.questions.config import QuestionEntry

from .rule_dialog import normalize_question_type_code, to_int
from .utils import (
    entry_dimension_label,
    normalize_dimension_name,
    question_supports_dimension_grouping,
    sanitize_dimension_groups,
    summarize_bias,
)


class DimensionNameDialog(QDialog):
    """输入维度名称弹窗。"""

    def __init__(self, title: str, confirm_text: str, initial_value: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 180)
        self._value = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(SubtitleLabel(title, self))
        layout.addWidget(BodyLabel("维度名称会用于题目分组和运行时信效度计划。", self))

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如：满意度、信任感、使用意愿")
        self.name_edit.setText(initial_value)
        layout.addWidget(self.name_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        ok_btn = PrimaryPushButton(confirm_text, self)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self._accept_value)

    def _accept_value(self) -> None:
        self._value = self.name_edit.text().strip()
        self.accept()

    def get_value(self) -> str:
        return str(self._value or "").strip()


class DimensionGroupingPanel(QWidget):
    """维度分组与批量分配面板。"""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[QuestionEntry] = []
        self._questions_info: List[Dict[str, Any]] = []
        self._question_info_map: Dict[int, Dict[str, Any]] = {}
        self._dimension_groups: List[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(BodyLabel("给量表题、评价题、矩阵题指定心理维度。启用“提升问卷信效度”时，系统会按维度分别生成作答计划。", self))

        content_row = QHBoxLayout()
        content_row.setSpacing(12)
        layout.addLayout(content_row, 1)

        self.group_card = CardWidget(self)
        group_layout = QVBoxLayout(self.group_card)
        group_layout.setContentsMargins(16, 16, 16, 16)
        group_layout.setSpacing(10)
        group_layout.addWidget(SubtitleLabel("维度列表", self.group_card))
        group_layout.addWidget(BodyLabel("“未分组”为系统保留组。自定义维度可以手动新增、重命名、删除。", self.group_card))

        add_row = QHBoxLayout()
        self.name_edit = LineEdit(self.group_card)
        self.name_edit.setPlaceholderText("输入新维度名称")
        self.preset_combo = ComboBox(self.group_card)
        self.preset_combo.setPlaceholderText("从预设快速添加")
        for preset in PRESET_DIMENSIONS:
            self.preset_combo.addItem(str(preset), userData=str(preset))
        self.preset_combo.setCurrentIndex(-1)
        self.add_btn = PrimaryPushButton("新增维度", self.group_card)
        add_row.addWidget(self.name_edit, 1)
        add_row.addWidget(self.preset_combo)
        add_row.addWidget(self.add_btn)
        group_layout.addLayout(add_row)

        self.group_table = TableWidget(self.group_card)
        self.group_table.setColumnCount(2)
        self.group_table.setHorizontalHeaderLabels(["维度名称", "题目数"])
        self.group_table.verticalHeader().setVisible(False)
        self.group_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.group_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.group_table.setAlternatingRowColors(True)
        self.group_table.setMinimumWidth(300)
        self.group_table.setMinimumHeight(320)
        group_header = self.group_table.horizontalHeader()
        group_header.setSectionResizeMode(0, group_header.ResizeMode.Stretch)
        group_header.setSectionResizeMode(1, group_header.ResizeMode.ResizeToContents)
        group_layout.addWidget(self.group_table, 1)

        group_btn_row = QHBoxLayout()
        self.rename_btn = PushButton("重命名选中", self.group_card)
        self.delete_btn = PushButton("删除选中", self.group_card)
        group_btn_row.addWidget(self.rename_btn)
        group_btn_row.addWidget(self.delete_btn)
        group_btn_row.addStretch(1)
        group_layout.addLayout(group_btn_row)
        content_row.addWidget(self.group_card, 0)

        self.question_card = CardWidget(self)
        question_layout = QVBoxLayout(self.question_card)
        question_layout.setContentsMargins(16, 16, 16, 16)
        question_layout.setSpacing(10)
        question_layout.addWidget(SubtitleLabel("题目分配", self.question_card))
        question_layout.addWidget(BodyLabel("这里只显示量表题、评价题、矩阵题。先选题，再分配到左侧选中的维度。", self.question_card))

        assign_row = QHBoxLayout()
        self.assign_btn = PrimaryPushButton("分配到选中维度", self.question_card)
        self.clear_btn = PushButton("移回未分组", self.question_card)
        assign_row.addWidget(self.assign_btn)
        assign_row.addWidget(self.clear_btn)
        assign_row.addStretch(1)
        question_layout.addLayout(assign_row)

        self.question_table = TableWidget(self.question_card)
        self.question_table.setColumnCount(5)
        self.question_table.setHorizontalHeaderLabels(["题号", "题型", "题目标题", "当前维度", "倾向预设"])
        self.question_table.verticalHeader().setVisible(False)
        self.question_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.question_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.question_table.setAlternatingRowColors(True)
        self.question_table.setMinimumHeight(420)
        question_header = self.question_table.horizontalHeader()
        question_header.setSectionResizeMode(0, question_header.ResizeMode.ResizeToContents)
        question_header.setSectionResizeMode(1, question_header.ResizeMode.ResizeToContents)
        question_header.setSectionResizeMode(2, question_header.ResizeMode.Stretch)
        question_header.setSectionResizeMode(3, question_header.ResizeMode.ResizeToContents)
        question_header.setSectionResizeMode(4, question_header.ResizeMode.ResizeToContents)
        question_layout.addWidget(self.question_table, 1)
        content_row.addWidget(self.question_card, 1)

        self.add_btn.clicked.connect(self._on_add_dimension)
        self.rename_btn.clicked.connect(self._on_rename_dimension)
        self.delete_btn.clicked.connect(self._on_delete_dimension)
        self.assign_btn.clicked.connect(self._on_assign_dimension)
        self.clear_btn.clicked.connect(self._on_clear_dimension)

    def set_entries(self, entries: Sequence[QuestionEntry], questions_info: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        self._entries = list(entries or [])
        if questions_info is not None:
            self._questions_info = list(questions_info or [])
            self._question_info_map = {}
            for info in self._questions_info:
                q_num = to_int(info.get("num"), 0)
                if q_num > 0:
                    self._question_info_map[q_num] = dict(info)
        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self._refresh_dimension_table()
        self._refresh_question_table()

    def set_dimension_groups(self, groups: Sequence[Any]) -> None:
        self._dimension_groups = sanitize_dimension_groups(groups, self._entries)
        self._refresh_dimension_table()
        self._refresh_question_table()

    def get_dimension_groups(self) -> List[str]:
        return list(self._dimension_groups)

    def _toast(self, message: str, level: str = "warning") -> None:
        parent = self.window() or self
        if level == "error":
            InfoBar.error("", message, parent=parent, position=InfoBarPosition.TOP, duration=2600)
            return
        if level == "success":
            InfoBar.success("", message, parent=parent, position=InfoBarPosition.TOP, duration=1800)
            return
        InfoBar.warning("", message, parent=parent, position=InfoBarPosition.TOP, duration=2200)

    def _refresh_dimension_table(self) -> None:
        all_groups = [DIMENSION_UNGROUPED, *self._dimension_groups]
        counts = {name: 0 for name in all_groups}
        for entry in self._entries:
            if not question_supports_dimension_grouping(entry):
                continue
            label = entry_dimension_label(entry)
            counts[label] = counts.get(label, 0) + 1
        self.group_table.setRowCount(0)
        for row, group_name in enumerate(all_groups):
            self.group_table.insertRow(row)
            name_item = QTableWidgetItem(group_name)
            count_item = QTableWidgetItem(str(counts.get(group_name, 0)))
            if group_name == DIMENSION_UNGROUPED:
                name_item.setToolTip("系统保留组，不允许重命名或删除。")
            self.group_table.setItem(row, 0, name_item)
            self.group_table.setItem(row, 1, count_item)
        if self.group_table.rowCount() > 0 and self.group_table.currentRow() < 0:
            self.group_table.selectRow(0)

    def _supported_entry_rows(self) -> List[Tuple[int, QuestionEntry, Dict[str, Any]]]:
        rows: List[Tuple[int, QuestionEntry, Dict[str, Any]]] = []
        for idx, entry in enumerate(self._entries):
            if not question_supports_dimension_grouping(entry):
                continue
            question_num = to_int(getattr(entry, "question_num", idx + 1), idx + 1)
            info = self._question_info_map.get(question_num, {})
            rows.append((idx, entry, info))
        return rows

    def _resolve_entry_title(self, entry: QuestionEntry, info: Dict[str, Any], index: int) -> str:
        title = str(getattr(entry, "question_title", "") or "").strip()
        if title:
            return title
        title = str(info.get("title") or "").strip()
        if title:
            return title
        return f"第{index + 1}题"

    def _resolve_entry_type_label(self, entry: QuestionEntry, info: Dict[str, Any]) -> str:
        type_code = normalize_question_type_code(info.get("type_code"))
        if type_code == "5" and info.get("is_rating"):
            return "评价题"
        return {
            "scale": "量表题",
            "score": "评价题",
            "matrix": "矩阵题",
        }.get(str(getattr(entry, "question_type", "") or "").strip().lower(), "量表题")

    def _refresh_question_table(self) -> None:
        rows = self._supported_entry_rows()
        self.question_table.setRowCount(0)
        for table_row, (entry_idx, entry, info) in enumerate(rows):
            question_num = to_int(getattr(entry, "question_num", entry_idx + 1), entry_idx + 1)
            self.question_table.insertRow(table_row)
            num_item = QTableWidgetItem(str(question_num))
            num_item.setData(0x0100, entry_idx)
            self.question_table.setItem(table_row, 0, num_item)
            self.question_table.setItem(table_row, 1, QTableWidgetItem(self._resolve_entry_type_label(entry, info)))
            self.question_table.setItem(table_row, 2, QTableWidgetItem(self._resolve_entry_title(entry, info, entry_idx)))
            self.question_table.setItem(table_row, 3, QTableWidgetItem(entry_dimension_label(entry)))
            self.question_table.setItem(table_row, 4, QTableWidgetItem(summarize_bias(entry)))

    def _selected_dimension_name(self) -> Optional[str]:
        rows = self.group_table.selectionModel().selectedRows() if self.group_table.selectionModel() is not None else []
        if not rows:
            return None
        row = rows[0].row()
        item = self.group_table.item(row, 0)
        if item is None:
            return None
        return str(item.text() or "").strip() or None

    def _selected_entry_indices(self) -> List[int]:
        selection = self.question_table.selectionModel()
        if selection is None:
            return []
        result: List[int] = []
        for model_index in selection.selectedRows():
            item = self.question_table.item(model_index.row(), 0)
            if item is None:
                continue
            data = item.data(0x0100)
            if isinstance(data, int):
                result.append(data)
        return sorted(set(result))

    def _validate_new_dimension_name(self, raw_value: Any, *, old_name: Optional[str] = None) -> Optional[str]:
        normalized = normalize_dimension_name(raw_value)
        if not normalized:
            self._toast("维度名称不能为空，也不能叫“未分组”", "warning")
            return None
        if old_name and normalized == old_name:
            return normalized
        if normalized in set(self._dimension_groups):
            self._toast(f"维度“{normalized}”已经存在了", "warning")
            return None
        return normalized

    def _on_add_dimension(self) -> None:
        manual_name = self.name_edit.text().strip()
        preset_name = ""
        if self.preset_combo.currentIndex() >= 0:
            preset_name = str(self.preset_combo.currentData() or "").strip()
        target_name = manual_name or preset_name
        normalized = self._validate_new_dimension_name(target_name)
        if not normalized:
            return
        self._dimension_groups.append(normalized)
        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self.name_edit.clear()
        self.preset_combo.setCurrentIndex(-1)
        self._refresh_dimension_table()
        self._refresh_question_table()
        self.changed.emit()
        self._toast(f"已新增维度“{normalized}”", "success")

    def _on_rename_dimension(self) -> None:
        current_name = self._selected_dimension_name()
        if not current_name:
            self._toast("请先选择要重命名的维度", "warning")
            return
        if current_name == DIMENSION_UNGROUPED:
            self._toast("“未分组”是系统保留组，不能重命名", "warning")
            return
        dialog = DimensionNameDialog("重命名维度", "保存", current_name, self.window() or self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = self._validate_new_dimension_name(dialog.get_value(), old_name=current_name)
        if not new_name or new_name == current_name:
            return
        self._dimension_groups = [new_name if name == current_name else name for name in self._dimension_groups]
        for entry in self._entries:
            if normalize_dimension_name(getattr(entry, "dimension", None)) == current_name:
                entry.dimension = new_name
        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self._refresh_dimension_table()
        self._refresh_question_table()
        self.changed.emit()
        self._toast(f"维度已重命名为“{new_name}”", "success")

    def _on_delete_dimension(self) -> None:
        current_name = self._selected_dimension_name()
        if not current_name:
            self._toast("请先选择要删除的维度", "warning")
            return
        if current_name == DIMENSION_UNGROUPED:
            self._toast("“未分组”是系统保留组，不能删除", "warning")
            return
        assigned_count = 0
        for entry in self._entries:
            if normalize_dimension_name(getattr(entry, "dimension", None)) == current_name:
                assigned_count += 1
        box = MessageBox(
            "确认删除维度",
            f"删除后，当前维度下的 {assigned_count} 道题会自动回到“未分组”。",
            self.window() or self,
        )
        box.yesButton.setText("确认删除")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self._dimension_groups = [name for name in self._dimension_groups if name != current_name]
        for entry in self._entries:
            if normalize_dimension_name(getattr(entry, "dimension", None)) == current_name:
                entry.dimension = None
        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self._refresh_dimension_table()
        self._refresh_question_table()
        self.changed.emit()
        self._toast(f"已删除维度“{current_name}”", "success")

    def _assign_entries_to_dimension(self, dimension_name: Optional[str]) -> None:
        selected_entries = self._selected_entry_indices()
        if not selected_entries:
            self._toast("请先选择要分配的题目", "warning")
            return
        normalized = normalize_dimension_name(dimension_name)
        for idx in selected_entries:
            if 0 <= idx < len(self._entries):
                self._entries[idx].dimension = normalized
        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self._refresh_dimension_table()
        self._refresh_question_table()
        self.changed.emit()

    def _on_assign_dimension(self) -> None:
        current_name = self._selected_dimension_name()
        if not current_name:
            self._toast("请先在左侧选择一个维度，再分配题目", "warning")
            return
        self._assign_entries_to_dimension(current_name)
        self._toast(f"已把选中题目分配到“{current_name}”", "success")

    def _on_clear_dimension(self) -> None:
        self._assign_entries_to_dimension(None)
        self._toast("已把选中题目移回“未分组”", "success")
