"""维度分组面板。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    HorizontalSeparator,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PrimaryPushButton,
    SubtitleLabel,
    TitleLabel,
)

from software.app.config import DIMENSION_UNGROUPED, PRESET_DIMENSIONS
from software.core.questions.config import QuestionEntry

from .dimension_sections import DimensionSectionWidget
from .rule_dialog import normalize_question_type_code, to_int
from .utils import (
    entry_dimension_label,
    normalize_dimension_name,
    question_supports_dimension_grouping,
    sanitize_dimension_groups,
    summarize_bias,
)


class DimensionNameDialog(MessageBoxBase):
    """输入维度名称弹窗。"""

    def __init__(self, title: str, confirm_text: str, initial_value: str = "", parent=None):
        self._fallback_parent: Optional[QWidget] = None
        if parent is None:
            self._fallback_parent = QWidget()
            self._fallback_parent.resize(960, 640)
            parent = self._fallback_parent
        super().__init__(parent)
        self.setWindowTitle(title)
        self._value = ""
        self.widget.setFixedWidth(520)

        self.titleLabel = TitleLabel(title, self.widget)
        self.tipLabel = BodyLabel("维度名称会用于题目分组和运行时信效度计划。", self.widget)
        self.name_edit = LineEdit(self.widget)
        self.name_edit.setPlaceholderText("例如：满意度、信任感、使用意愿")
        self.name_edit.setText(initial_value)
        self.name_edit.returnPressed.connect(self.yesButton.click)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.tipLabel)
        self.viewLayout.addWidget(self.name_edit)

        self.yesButton.setText(confirm_text)
        self.cancelButton.setText("取消")
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def validate(self) -> bool:
        self._value = self.name_edit.text().strip()
        return True

    def get_value(self) -> str:
        return str(self._value or "").strip()


class DimensionGroupingPanel(QWidget):
    """维度分组与拖拽分配面板。"""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[QuestionEntry] = []
        self._questions_info: List[Dict[str, Any]] = []
        self._question_info_map: Dict[int, Dict[str, Any]] = {}
        self._dimension_groups: List[str] = []
        self._section_widgets: Dict[str, DimensionSectionWidget] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.content_card = CardWidget(self)
        content_layout = QVBoxLayout(self.content_card)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(10)
        content_layout.addWidget(SubtitleLabel("维度分组", self.content_card))
        content_layout.addWidget(
            BodyLabel("把题目拖到目标维度下完成分组，点击维度右侧按钮可重命名或删除。", self.content_card)
        )

        add_row = QHBoxLayout()
        self.name_edit = LineEdit(self.content_card)
        self.name_edit.setPlaceholderText("输入新维度名称")
        self.preset_combo = ComboBox(self.content_card)
        self.preset_combo.setPlaceholderText("从预设快速添加")
        for preset in PRESET_DIMENSIONS:
            self.preset_combo.addItem(str(preset), userData=str(preset))
        self.preset_combo.setCurrentIndex(-1)
        self.add_btn = PrimaryPushButton("新增维度", self.content_card)
        add_row.addWidget(self.name_edit, 1)
        add_row.addWidget(self.preset_combo)
        add_row.addWidget(self.add_btn)
        content_layout.addLayout(add_row)

        self.sections_container = QWidget(self.content_card)
        self.sections_layout = QVBoxLayout(self.sections_container)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(14)
        content_layout.addWidget(self.sections_container, 1)

        layout.addWidget(self.content_card, 1)

        self.add_btn.clicked.connect(self._on_add_dimension)

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
        self._refresh_sections()

    def set_dimension_groups(self, groups: Sequence[Any]) -> None:
        self._dimension_groups = sanitize_dimension_groups(groups, self._entries)
        self._refresh_sections()

    def get_dimension_groups(self) -> List[str]:
        return list(self._dimension_groups)

    def _toast(self, message: str, level: str = "warning") -> None:
        parent = self.window() or self
        if level == "error":
            InfoBar.error("", message, parent=parent, position=InfoBarPosition.TOP, duration=2600)
            return
        if level == "success":
            return
        InfoBar.warning("", message, parent=parent, position=InfoBarPosition.TOP, duration=2200)

    def _refresh_sections(self) -> None:
        self._clear_section_widgets()
        rows_by_group = self._group_question_rows()
        ordered_groups = [DIMENSION_UNGROUPED, *self._dimension_groups]
        last_index = len(ordered_groups) - 1
        self._section_widgets = {}

        for index, group_name in enumerate(ordered_groups):
            section = DimensionSectionWidget(group_name, self.sections_container)
            section.set_rows(rows_by_group.get(group_name, []))
            section.entriesDropped.connect(self._on_entries_dropped)
            section.renameRequested.connect(self._on_rename_dimension)
            section.deleteRequested.connect(self._on_delete_dimension)
            self.sections_layout.addWidget(section)
            self._section_widgets[group_name] = section
            if index < last_index:
                self.sections_layout.addWidget(HorizontalSeparator(self.sections_container))
        self.sections_layout.addStretch(1)

    def _clear_section_widgets(self) -> None:
        self._section_widgets = {}
        while self.sections_layout.count():
            item = self.sections_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_question_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for entry_idx, entry, info in self._supported_entry_rows():
            question_num = to_int(getattr(entry, "question_num", entry_idx + 1), entry_idx + 1)
            rows.append(
                {
                    "entry_index": entry_idx,
                    "group_name": entry_dimension_label(entry),
                    "question_num": question_num,
                    "title": self._resolve_entry_title(entry, info, entry_idx),
                    "type_label": self._resolve_entry_type_label(entry, info),
                    "bias_text": summarize_bias(entry),
                }
            )
        return sorted(rows, key=lambda item: int(item["question_num"]))

    def _group_question_rows(self) -> Dict[str, List[Dict[str, object]]]:
        rows_by_group: Dict[str, List[Dict[str, object]]] = {
            DIMENSION_UNGROUPED: [],
            **{name: [] for name in self._dimension_groups},
        }
        for row in self._build_question_rows():
            group_name = str(row.get("group_name") or DIMENSION_UNGROUPED)
            rows_by_group.setdefault(group_name, []).append(row)
        return rows_by_group

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
        self._refresh_sections()
        self.changed.emit()
        self._toast(f"已新增维度“{normalized}”", "success")

    def _on_rename_dimension(self, group_name: Optional[str] = None) -> None:
        current_name = str(group_name or "").strip()
        if not current_name:
            self._toast("请先选择要重命名的维度", "warning")
            return
        if current_name == DIMENSION_UNGROUPED:
            self._toast("“未分组”是系统保留组，不能重命名", "warning")
            return
        dialog = DimensionNameDialog("重命名维度", "保存", current_name, self.window() or self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        new_name = self._validate_new_dimension_name(dialog.get_value(), old_name=current_name)
        if not new_name or new_name == current_name:
            return

        self._dimension_groups = [new_name if name == current_name else name for name in self._dimension_groups]
        for entry in self._entries:
            if normalize_dimension_name(getattr(entry, "dimension", None)) == current_name:
                entry.dimension = new_name
        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self._refresh_sections()
        self.changed.emit()
        self._toast(f"维度已重命名为“{new_name}”", "success")

    def _on_delete_dimension(self, group_name: Optional[str] = None) -> None:
        current_name = str(group_name or "").strip()
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
        self._refresh_sections()
        self.changed.emit()
        self._toast(f"已删除维度“{current_name}”", "success")

    def _apply_entries_to_dimension(self, entry_indices: Sequence[int], dimension_name: Optional[str]) -> bool:
        normalized = normalize_dimension_name(dimension_name)
        changed = False
        for idx in sorted(set(entry_indices)):
            if not isinstance(idx, int) or idx < 0 or idx >= len(self._entries):
                continue
            current = normalize_dimension_name(getattr(self._entries[idx], "dimension", None))
            if current == normalized:
                continue
            self._entries[idx].dimension = normalized
            changed = True

        if not changed:
            return False

        self._dimension_groups = sanitize_dimension_groups(self._dimension_groups, self._entries)
        self._refresh_sections()
        self.changed.emit()
        return True

    def _on_entries_dropped(self, entry_indices: List[int], group_name: Any) -> None:
        target_group = str(group_name or "").strip()
        if not target_group:
            return
        target_dimension = None if target_group == DIMENSION_UNGROUPED else target_group
        self._apply_entries_to_dimension(entry_indices, target_dimension)
