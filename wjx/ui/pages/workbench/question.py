"""题目配置页面和配置向导"""
import copy
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QTableWidgetItem,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    TableWidget,
    ComboBox,
    LineEdit,
    CheckBox,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.core.questions.config import QuestionEntry
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.utils.integrations.ai_service import generate_answer
from wjx.ui.helpers.ai_fill import ensure_ai_ready

# 题目类型选项
TYPE_CHOICES = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("text", "填空题"),
    ("multi_text", "多项填空题"),
    ("dropdown", "下拉题"),
    ("matrix", "矩阵题"),
    ("scale", "量表题"),
    ("score", "评价题"),
    ("slider", "滑块题"),
    ("order", "排序题"),
]

# 填写策略选项
STRATEGY_CHOICES = [
    ("random", "完全随机"),
    ("custom", "自定义配比"),
]


def _get_entry_type_label(entry: QuestionEntry) -> str:
    """获取题目类型的中文标签"""
    type_map = {
        "single": "单选题",
        "multiple": "多选题",
        "text": "填空题",
        "multi_text": "多项填空题",
        "dropdown": "下拉题",
        "matrix": "矩阵题",
        "scale": "量表题",
        "score": "评价题",
        "slider": "滑块题",
        "order": "排序题",
    }
    return type_map.get(entry.question_type, entry.question_type)


class QuestionWizardDialog(QDialog):
    """配置向导：用滑块快速设置权重，编辑填空题答案。"""

    @staticmethod
    def _shorten(text: str, limit: int = 80) -> str:
        if not text:
            return ""
        text = str(text).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    @staticmethod
    def _resolve_matrix_weights(entry: QuestionEntry, rows: int, columns: int) -> List[List[float]]:
        """解析矩阵题的配比配置，返回按行的默认权重。"""
        def _clean_row(raw_row: Any) -> Optional[List[float]]:
            if not isinstance(raw_row, (list, tuple)):
                return None
            cleaned: List[float] = []
            for value in raw_row:
                try:
                    cleaned.append(max(0.0, float(value)))
                except Exception:
                    cleaned.append(0.0)
            if not cleaned:
                return None
            if len(cleaned) < columns:
                cleaned = cleaned + [1.0] * (columns - len(cleaned))
            elif len(cleaned) > columns:
                cleaned = cleaned[:columns]
            if all(v <= 0 for v in cleaned):
                cleaned = [1.0] * columns
            return cleaned

        raw = entry.custom_weights if entry.custom_weights else entry.probabilities
        if isinstance(raw, list) and any(isinstance(item, (list, tuple)) for item in raw):
            per_row: List[List[float]] = []
            last_row = None
            for idx in range(rows):
                row_raw = raw[idx] if idx < len(raw) else last_row
                row_values = _clean_row(row_raw)
                if row_values is None:
                    row_values = [1.0] * columns
                per_row.append(row_values)
                if row_raw is not None:
                    last_row = row_raw
            return per_row
        if isinstance(raw, list):
            uniform = _clean_row(raw)
            if uniform is None:
                uniform = [1.0] * columns
            return [list(uniform) for _ in range(rows)]
        return [[1.0] * columns for _ in range(rows)]

    @staticmethod
    def _apply_label_color(label: BodyLabel, light: str, dark: str) -> None:
        """为标签设置浅色/深色主题颜色。"""
        try:
            label.setTextColor(QColor(light), QColor(dark))
        except Exception:
            style = label.styleSheet() or ""
            style = style.strip()
            if style and not style.endswith(";"):
                style = f"{style};"
            label.setStyleSheet(f"{style}color: {light};")

    def __init__(self, entries: List[QuestionEntry], info: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置向导")
        self.resize(720, 640)
        self.entries = entries
        self.info = info or []
        self.slider_map: Dict[int, List[NoWheelSlider]] = {}
        self.matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]] = {}
        self.text_edit_map: Dict[int, List[LineEdit]] = {}
        self.ai_check_map: Dict[int, CheckBox] = {}
        self.text_container_map: Dict[int, QWidget] = {}
        self.text_add_btn_map: Dict[int, PushButton] = {}
        self._entry_snapshots: List[QuestionEntry] = [copy.deepcopy(entry) for entry in entries]
        self._has_content = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 顶部说明
        intro = BodyLabel("配置各题目的选项权重或填空答案", self)
        intro.setStyleSheet("font-size: 13px;")
        self._apply_label_color(intro, "#666666", "#bfbfbf")
        layout.addWidget(intro)

        # 滚动区域
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        container = QWidget(self)
        container.setStyleSheet("background: transparent;")
        scroll.setWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(4, 4, 12, 4)
        inner.setSpacing(20)

        for idx, entry in enumerate(entries):
            # 获取题目信息
            qnum = ""
            title_text = ""
            option_texts: List[str] = []
            row_texts: List[str] = []
            if idx < len(self.info):
                qnum = str(self.info[idx].get("num") or "")
                title_text = str(self.info[idx].get("title") or "")
                opt_raw = self.info[idx].get("option_texts")
                if isinstance(opt_raw, list):
                    option_texts = [str(x) for x in opt_raw]
                row_raw = self.info[idx].get("row_texts")
                if isinstance(row_raw, list):
                    row_texts = [str(x) for x in row_raw]

            # 题目卡片
            card = CardWidget(container)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(20, 16, 20, 16)
            card_layout.setSpacing(12)

            # 题目标题行
            header = QHBoxLayout()
            header.setSpacing(12)
            title = SubtitleLabel(f"第{qnum or idx + 1}题", card)
            title.setStyleSheet("font-size: 15px; font-weight: 600;")
            header.addWidget(title)
            type_label = BodyLabel(f"[{_get_entry_type_label(entry)}]", card)
            type_label.setStyleSheet("color: #0078d4; font-size: 12px;")
            header.addWidget(type_label)
            header.addStretch(1)
            if entry.question_type == "slider":
                slider_note = BodyLabel("目标值会自动做小幅随机抖动，避免每份都填同一个数", card)
                slider_note.setStyleSheet("font-size: 12px;")
                slider_note.setWordWrap(False)
                slider_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._apply_label_color(slider_note, "#777777", "#bfbfbf")
                header.addWidget(slider_note)
            if entry.question_type == "multiple":
                multi_note = BodyLabel("每个滑块的值对应的是选项的命中概率（%）", card)
                multi_note.setStyleSheet("font-size: 12px;")
                multi_note.setWordWrap(False)
                multi_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._apply_label_color(multi_note, "#777777", "#bfbfbf")
                header.addWidget(multi_note)
            card_layout.addLayout(header)

            # 题目描述
            if title_text:
                desc = BodyLabel(self._shorten(title_text, 120), card)
                desc.setWordWrap(True)
                desc.setStyleSheet("font-size: 12px; margin-bottom: 4px;")
                self._apply_label_color(desc, "#555555", "#c8c8c8")
                card_layout.addWidget(desc)

            # 填空题：显示答案编辑区
            if entry.question_type in ("text", "multi_text"):
                self._has_content = True
                hint = BodyLabel("答案列表（随机选择一个填入）：", card)
                hint.setStyleSheet("font-size: 12px;")
                self._apply_label_color(hint, "#666666", "#bfbfbf")
                card_layout.addWidget(hint)

                # 答案行容器
                text_rows_container = QWidget(card)
                text_rows_layout = QVBoxLayout(text_rows_container)
                text_rows_layout.setContentsMargins(0, 0, 0, 0)
                text_rows_layout.setSpacing(4)
                card_layout.addWidget(text_rows_container)

                texts = list(entry.texts or [DEFAULT_FILL_TEXT])
                edits: List[LineEdit] = []

                def make_add_row_func(container_layout, edit_list, parent_card):
                    def add_row(initial_text: str = ""):
                        row_widget = QWidget(parent_card)
                        row_layout = QHBoxLayout(row_widget)
                        row_layout.setContentsMargins(0, 2, 0, 2)
                        row_layout.setSpacing(8)
                        num_lbl = BodyLabel(f"{len(edit_list) + 1}.", parent_card)
                        num_lbl.setFixedWidth(24)
                        num_lbl.setStyleSheet("font-size: 12px;")
                        self._apply_label_color(num_lbl, "#888888", "#a6a6a6")
                        row_layout.addWidget(num_lbl)
                        edit = LineEdit(parent_card)
                        edit.setText(initial_text)
                        edit.setPlaceholderText("输入答案")
                        row_layout.addWidget(edit, 1)
                        del_btn = PushButton("×", parent_card)
                        del_btn.setFixedWidth(32)
                        row_layout.addWidget(del_btn)
                        container_layout.addWidget(row_widget)
                        edit_list.append(edit)

                        def remove_row():
                            if len(edit_list) > 1:
                                edit_list.remove(edit)
                                row_widget.deleteLater()
                        del_btn.clicked.connect(remove_row)
                    return add_row

                add_row_func = make_add_row_func(text_rows_layout, edits, card)
                for txt in texts:
                    add_row_func(txt)

                # 添加按钮
                btn_row = QHBoxLayout()
                btn_row.setSpacing(8)
                add_btn = PushButton("+ 添加答案", card)
                add_btn.setFixedWidth(100)
                add_btn.clicked.connect(lambda checked=False, f=add_row_func: f(""))
                btn_row.addWidget(add_btn)
                self.text_container_map[idx] = text_rows_container
                self.text_add_btn_map[idx] = add_btn

                if entry.question_type == "text":
                    ai_cb = CheckBox("启用 AI", card)
                    ai_cb.setToolTip("运行时每次填空都会调用 AI")
                    ai_cb.setChecked(bool(getattr(entry, "ai_enabled", False)))
                    ai_cb.toggled.connect(lambda checked, i=idx: self._on_entry_ai_toggled(i, checked))
                    btn_row.addWidget(ai_cb)
                    self.ai_check_map[idx] = ai_cb
                    self._set_text_answer_enabled(idx, not ai_cb.isChecked())

                btn_row.addStretch(1)
                card_layout.addLayout(btn_row)

                self.text_edit_map[idx] = edits
            elif entry.question_type == "matrix":
                # 矩阵量表题：支持统一配比或按行配比
                self._has_content = True
                info_rows = self.info[idx].get("rows") if idx < len(self.info) else 0
                try:
                    info_rows = int(info_rows or 0)
                except Exception:
                    info_rows = 0
                rows = max(1, int(entry.rows or 1), info_rows)
                columns = max(1, int(entry.option_count or len(option_texts) or 1))
                if len(row_texts) < rows:
                    row_texts += [""] * (rows - len(row_texts))

                hint = BodyLabel("矩阵量表：每一行都需要单独设置配比", card)
                hint.setStyleSheet("font-size: 12px;")
                self._apply_label_color(hint, "#666666", "#bfbfbf")
                card_layout.addWidget(hint)

                per_row_scroll = ScrollArea(card)
                per_row_scroll.setWidgetResizable(True)
                per_row_scroll.setMinimumHeight(180)
                per_row_scroll.setMaximumHeight(320)
                per_row_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
                per_row_view = QWidget(card)
                per_row_view.setStyleSheet("background: transparent;")
                per_row_scroll.setWidget(per_row_view)
                per_row_layout = QVBoxLayout(per_row_view)
                per_row_layout.setContentsMargins(0, 0, 0, 0)
                per_row_layout.setSpacing(10)
                card_layout.addWidget(per_row_scroll)

                def build_slider_rows(parent_widget: QWidget, target_layout: QVBoxLayout, values: List[float]) -> List[NoWheelSlider]:
                    sliders: List[NoWheelSlider] = []
                    for col_idx in range(columns):
                        opt_widget = QWidget(parent_widget)
                        opt_layout = QHBoxLayout(opt_widget)
                        opt_layout.setContentsMargins(0, 2, 0, 2)
                        opt_layout.setSpacing(12)

                        opt_text = option_texts[col_idx] if col_idx < len(option_texts) else f"列 {col_idx + 1}"
                        text_label = BodyLabel(self._shorten(opt_text, 50), parent_widget)
                        text_label.setFixedWidth(160)
                        text_label.setStyleSheet("font-size: 13px;")
                        opt_layout.addWidget(text_label)

                        slider = NoWheelSlider(Qt.Orientation.Horizontal, parent_widget)
                        slider.setRange(0, 100)
                        try:
                            slider.setValue(int(values[col_idx]))
                        except Exception:
                            slider.setValue(1)
                        slider.setMinimumWidth(200)
                        opt_layout.addWidget(slider, 1)

                        value_label = BodyLabel(str(slider.value()), parent_widget)
                        value_label.setFixedWidth(36)
                        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        value_label.setStyleSheet("color: #0078d4; font-weight: 500; font-size: 13px;")
                        slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                        opt_layout.addWidget(value_label)

                        target_layout.addWidget(opt_widget)
                        sliders.append(slider)
                    return sliders

                matrix_weights = self._resolve_matrix_weights(entry, rows, columns)

                per_row_sliders: List[List[NoWheelSlider]] = []
                per_row_values = matrix_weights if matrix_weights else [[1.0] * columns for _ in range(rows)]
                for row_idx in range(rows):
                    row_card = CardWidget(per_row_view)
                    row_card_layout = QVBoxLayout(row_card)
                    row_card_layout.setContentsMargins(12, 8, 12, 8)
                    row_card_layout.setSpacing(6)
                    row_label_text = row_texts[row_idx] if row_idx < len(row_texts) else ""
                    if row_label_text:
                        row_label = BodyLabel(self._shorten(f"第{row_idx + 1}行：{row_label_text}", 60), row_card)
                    else:
                        row_label = BodyLabel(f"第{row_idx + 1}行", row_card)
                    row_label.setStyleSheet("font-weight: 500;")
                    self._apply_label_color(row_label, "#444444", "#e0e0e0")
                    row_card_layout.addWidget(row_label)

                    row_sliders = build_slider_rows(row_card, row_card_layout, per_row_values[row_idx])
                    per_row_sliders.append(row_sliders)
                    per_row_layout.addWidget(row_card)

                self.matrix_row_slider_map[idx] = per_row_sliders
            elif entry.question_type == "order":
                # 排序题：无需配置权重
                self._has_content = True
                hint = BodyLabel("排序题无需设置配比，执行时会随机排序；如题干要求仅排序前 N 项，将自动识别。", card)
                hint.setWordWrap(True)
                hint.setStyleSheet("font-size: 12px;")
                self._apply_label_color(hint, "#666666", "#bfbfbf")
                card_layout.addWidget(hint)

                if option_texts:
                    list_container = QWidget(card)
                    list_layout = QVBoxLayout(list_container)
                    list_layout.setContentsMargins(0, 6, 0, 0)
                    list_layout.setSpacing(4)
                    for opt_idx, opt_text in enumerate(option_texts, 1):
                        item = BodyLabel(f"{opt_idx}. {self._shorten(opt_text, 60)}", card)
                        item.setStyleSheet("font-size: 12px;")
                        self._apply_label_color(item, "#666666", "#c8c8c8")
                        list_layout.addWidget(item)
                    card_layout.addWidget(list_container)
            else:
                # 选择题：显示滑块
                self._has_content = True
                if entry.question_type == "slider":
                    slider_hint = BodyLabel("滑块题：此处数值代表填写时的目标值（不是概率）", card)
                    slider_hint.setWordWrap(True)
                    slider_hint.setStyleSheet("font-size: 12px;")
                    self._apply_label_color(slider_hint, "#666666", "#bfbfbf")
                    card_layout.addWidget(slider_hint)
                options = max(1, int(entry.option_count or 1))
                default_weight = 50 if entry.question_type == "multiple" else 1
                weights = list(entry.custom_weights or [])
                if len(weights) < options:
                    weights += [default_weight] * (options - len(weights))
                if all(w <= 0 for w in weights):
                    weights = [default_weight] * options

                sliders: List[NoWheelSlider] = []
                is_multiple = entry.question_type == "multiple"
                for opt_idx in range(options):
                    opt_widget = QWidget(card)
                    opt_layout = QHBoxLayout(opt_widget)
                    opt_layout.setContentsMargins(0, 4, 0, 4)
                    opt_layout.setSpacing(12)

                    num_label = BodyLabel(f"{opt_idx + 1}.", card)
                    num_label.setFixedWidth(24)
                    num_label.setStyleSheet("font-size: 12px;")
                    self._apply_label_color(num_label, "#888888", "#a6a6a6")
                    opt_layout.addWidget(num_label)

                    opt_text = option_texts[opt_idx] if opt_idx < len(option_texts) else "选项"
                    text_label = BodyLabel(self._shorten(opt_text, 50), card)
                    text_label.setFixedWidth(160)
                    text_label.setStyleSheet("font-size: 13px;")
                    opt_layout.addWidget(text_label)

                    slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
                    slider.setRange(0, 100)
                    slider.setValue(int(weights[opt_idx]))
                    slider.setMinimumWidth(200)
                    opt_layout.addWidget(slider, 1)

                    initial_text = f"{slider.value()}%" if is_multiple else str(slider.value())
                    value_label = BodyLabel(initial_text, card)
                    value_label.setFixedWidth(44 if is_multiple else 36)
                    value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    value_label.setStyleSheet("color: #0078d4; font-weight: 500; font-size: 13px;")
                    if is_multiple:
                        slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(f"{v}%"))
                    else:
                        slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                    opt_layout.addWidget(value_label)

                    card_layout.addWidget(opt_widget)
                    sliders.append(slider)

                self.slider_map[idx] = sliders

            inner.addWidget(card)

        if not self._has_content:
            empty_label = BodyLabel("当前无题目需要配置", container)
            empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inner.addWidget(empty_label)

        inner.addStretch(1)
        layout.addWidget(scroll, 1)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        cancel_btn.setFixedWidth(80)
        ok_btn = PrimaryPushButton("保存", self)
        ok_btn.setFixedWidth(80)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def _set_text_answer_enabled(self, idx: int, enabled: bool) -> None:
        container = self.text_container_map.get(idx)
        if container:
            container.setEnabled(enabled)
        add_btn = self.text_add_btn_map.get(idx)
        if add_btn:
            add_btn.setEnabled(enabled)

    def _on_entry_ai_toggled(self, idx: int, checked: bool) -> None:
        if checked and not ensure_ai_ready(self.window() or self):
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            self._set_text_answer_enabled(idx, True)
            return
        self._set_text_answer_enabled(idx, not checked)

    def _restore_entries(self) -> None:
        limit = min(len(self.entries), len(self._entry_snapshots))
        for idx in range(limit):
            snapshot = copy.deepcopy(self._entry_snapshots[idx])
            self.entries[idx].__dict__.update(snapshot.__dict__)

    def reject(self) -> None:
        self._restore_entries()
        super().reject()

    def get_results(self) -> Dict[int, Any]:
        """获取滑块权重结果"""
        result: Dict[int, Any] = {}
        for idx, sliders in self.slider_map.items():
            weights = [max(0, s.value()) for s in sliders]
            if all(w <= 0 for w in weights):
                weights = [1] * len(weights)
            result[idx] = weights

        for idx, row_sliders in self.matrix_row_slider_map.items():
            row_weights: List[List[int]] = []
            for row in row_sliders:
                weights = [max(0, s.value()) for s in row]
                if all(w <= 0 for w in weights):
                    weights = [1] * len(weights)
                row_weights.append(weights)
            result[idx] = row_weights
        return result

    def get_text_results(self) -> Dict[int, List[str]]:
        """获取填空题答案结果"""
        result: Dict[int, List[str]] = {}
        for idx, edits in self.text_edit_map.items():
            texts = [e.text().strip() for e in edits if e.text().strip()]
            if not texts:
                texts = [DEFAULT_FILL_TEXT]
            result[idx] = texts
        return result

    def get_ai_flags(self) -> Dict[int, bool]:
        """获取填空题是否启用 AI"""
        return {idx: cb.isChecked() for idx, cb in self.ai_check_map.items()}


class QuestionPage(ScrollArea):
    """题目配置页，支持简单编辑。"""

    entriesChanged = Signal(int)  # 当前题目配置条目数

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[QuestionEntry] = []
        self.questions_info: List[Dict[str, Any]] = []
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(SubtitleLabel("题目配置", self))
        layout.addWidget(BodyLabel("双击单元格即可编辑；自定义权重用逗号分隔，例如 3,2,1", self))

        self.table = TableWidget(self.view)
        self.table.setRowCount(0)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["题号", "类型", "选项数", "配置详情"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.add_btn = PrimaryPushButton("新增题目", self.view)
        self.del_btn = PushButton("删除选中", self.view)
        self.reset_btn = PushButton("恢复默认", self.view)
        self.ai_btn = PushButton(FluentIcon.ROBOT, "AI 生成答案", self.view)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addWidget(self.ai_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._add_entry)
        self.del_btn.clicked.connect(self._delete_selected)
        self.reset_btn.clicked.connect(self._reset_from_source)
        self.ai_btn.clicked.connect(self._generate_ai_answers)

    # ---------- data helpers ----------
    def set_questions(self, info: List[Dict[str, Any]], entries: List[QuestionEntry]):
        self.questions_info = info or []
        self.set_entries(entries, info)

    def set_entries(self, entries: List[QuestionEntry], info: Optional[List[Dict[str, Any]]] = None):
        self.questions_info = info or self.questions_info
        self.entries = list(entries or [])
        if self.questions_info:
            for idx, entry in enumerate(self.entries):
                if getattr(entry, "question_title", None):
                    continue
                if idx < len(self.questions_info):
                    title = self.questions_info[idx].get("title")
                    if title:
                        entry.question_title = str(title).strip()
        self._refresh_table()

    def get_entries(self) -> List[QuestionEntry]:
        result: List[QuestionEntry] = []
        for row in range(self.table.rowCount()):
            entry = self._entry_from_row(row)
            result.append(entry)
        return result

    # ---------- UI actions ----------
    def _reset_from_source(self):
        self._refresh_table()

    def _add_entry(self):
        """显示新增题目的交互式弹窗"""
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("新增题目")
        dialog.resize(550, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("新增题目配置", dialog))

        # 题目类型
        type_row = QHBoxLayout()
        type_row.addWidget(BodyLabel("题目类型：", dialog))
        type_combo = ComboBox(dialog)
        for value, label in TYPE_CHOICES:
            type_combo.addItem(label, value)
        type_combo.setCurrentIndex(0)
        type_row.addWidget(type_combo, 1)
        layout.addLayout(type_row)

        # 选项数量
        option_row = QHBoxLayout()
        option_label = BodyLabel("选项数量：", dialog)
        option_row.addWidget(option_label)
        option_spin = NoWheelSpinBox(dialog)
        option_spin.setRange(1, 20)
        option_spin.setValue(4)
        option_row.addWidget(option_spin, 1)
        layout.addLayout(option_row)

        # 矩阵题行数
        row_count_widget = QWidget(dialog)
        row_count_layout = QHBoxLayout(row_count_widget)
        row_count_layout.setContentsMargins(0, 0, 0, 0)
        row_count_layout.setSpacing(6)
        row_count_label = BodyLabel("行数：", dialog)
        row_count_spin = NoWheelSpinBox(dialog)
        row_count_spin.setRange(1, 50)
        row_count_spin.setValue(2)
        row_count_layout.addWidget(row_count_label)
        row_count_layout.addWidget(row_count_spin, 1)
        layout.addWidget(row_count_widget)

        # 策略选择
        strategy_row = QHBoxLayout()
        strategy_label = BodyLabel("填写策略：", dialog)
        strategy_row.addWidget(strategy_label)
        strategy_combo = ComboBox(dialog)
        for value, label in STRATEGY_CHOICES:
            strategy_combo.addItem(label, value)
        strategy_combo.setCurrentIndex(0)  # 默认“完全随机”
        strategy_row.addWidget(strategy_combo, 1)
        layout.addLayout(strategy_row)

        matrix_hint = BodyLabel("矩阵题配比请在“配置向导”中按行设置", dialog)
        matrix_hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(matrix_hint)
        order_hint = BodyLabel("排序题不支持配比设置（执行时自动随机排序）", dialog)
        order_hint.setStyleSheet("color: #888; font-size: 12px;")
        order_hint.setVisible(False)
        layout.addWidget(order_hint)

        # 填空题答案列表区域（简洁布局，无卡片）
        text_area_widget = QWidget(dialog)
        text_area_layout = QVBoxLayout(text_area_widget)
        text_area_layout.setContentsMargins(0, 8, 0, 0)
        text_area_layout.setSpacing(6)
        text_area_layout.addWidget(BodyLabel("答案列表（执行时随机选择一个）：", dialog))
        
        text_edits: List[LineEdit] = []
        text_rows_container = QWidget(dialog)
        text_rows_layout = QVBoxLayout(text_rows_container)
        text_rows_layout.setContentsMargins(0, 0, 0, 0)
        text_rows_layout.setSpacing(4)
        text_area_layout.addWidget(text_rows_container)
        
        def add_text_row(initial_text: str = ""):
            row_widget = QWidget(text_rows_container)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            edit = LineEdit(row_widget)
            edit.setPlaceholderText('输入答案')
            edit.setText(initial_text)
            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(del_btn)
            text_rows_layout.addWidget(row_widget)
            text_edits.append(edit)
            
            def remove_row():
                if len(text_edits) > 1:
                    text_edits.remove(edit)
                    row_widget.deleteLater()
            del_btn.clicked.connect(remove_row)
        
        add_text_row()  # 默认添加一行
        
        add_text_btn = PushButton("+ 添加", dialog)
        add_text_btn.setFixedWidth(80)
        add_text_btn.clicked.connect(lambda: add_text_row())
        text_area_layout.addWidget(add_text_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text_area_widget)

        ai_toggle = CheckBox("启用 AI（运行时每次填空调用）", dialog)
        ai_toggle.setToolTip("开启后该题每次填写都会调用 AI")
        layout.addWidget(ai_toggle)

        def _resolve_q_type() -> str:
            idx = type_combo.currentIndex()
            if 0 <= idx < len(TYPE_CHOICES):
                return TYPE_CHOICES[idx][0]
            return type_combo.currentData() or "single"

        def _resolve_strategy() -> str:
            idx = strategy_combo.currentIndex()
            if 0 <= idx < len(STRATEGY_CHOICES):
                return STRATEGY_CHOICES[idx][0]
            return strategy_combo.currentData() or "random"

        def set_text_area_enabled(enabled: bool):
            text_area_widget.setEnabled(enabled)

        def on_ai_toggle(checked: bool):
            if checked and not ensure_ai_ready(dialog):
                ai_toggle.blockSignals(True)
                ai_toggle.setChecked(False)
                ai_toggle.blockSignals(False)
                checked = False
            set_text_area_enabled(not checked)

        # 自定义配比滑块区域
        slider_card = CardWidget(dialog)
        slider_card_layout = QVBoxLayout(slider_card)
        slider_card_layout.setContentsMargins(12, 12, 12, 12)
        slider_card_layout.setSpacing(8)
        slider_hint_label = BodyLabel("", dialog)
        slider_card_layout.addWidget(slider_hint_label)
        
        slider_scroll = ScrollArea(dialog)
        slider_scroll.setWidgetResizable(True)
        slider_scroll.setMinimumHeight(180)
        slider_scroll.setMaximumHeight(300)
        slider_container = QWidget(dialog)
        slider_inner_layout = QVBoxLayout(slider_container)
        slider_inner_layout.setContentsMargins(0, 0, 0, 0)
        slider_inner_layout.setSpacing(6)
        slider_scroll.setWidget(slider_container)
        slider_card_layout.addWidget(slider_scroll)
        layout.addWidget(slider_card)

        sliders: List[NoWheelSlider] = []
        slider_labels: List[BodyLabel] = []

        def rebuild_sliders():
            for i in reversed(range(slider_inner_layout.count())):
                item = slider_inner_layout.itemAt(i)
                widget = item.widget() if item else None
                if widget:
                    widget.deleteLater()
            sliders.clear()
            slider_labels.clear()
            
            count = option_spin.value()
            for idx in range(count):
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(BodyLabel(f"选项 {idx + 1}：", slider_container))
                slider = NoWheelSlider(Qt.Orientation.Horizontal, slider_container)
                slider.setRange(0, 100)
                slider.setValue(50)
                value_label = BodyLabel("50", slider_container)
                value_label.setMinimumWidth(30)
                slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                row.addWidget(slider, 1)
                row.addWidget(value_label)
                
                row_widget = QWidget(slider_container)
                row_widget.setLayout(row)
                slider_inner_layout.addWidget(row_widget)
                sliders.append(slider)
                slider_labels.append(value_label)

        def do_update_visibility():
            q_type = _resolve_q_type()
            strategy = _resolve_strategy()
            is_text = q_type in ("text", "multi_text")
            is_custom = strategy == "custom"
            is_single_text = q_type == "text"
            is_matrix = q_type == "matrix"
            is_order = q_type == "order"
            # 填空题时隐藏策略选择，显示答案列表
            strategy_label.setVisible(not is_text)
            strategy_combo.setVisible(not is_text)
            text_area_widget.setVisible(is_text)
            slider_card.setVisible(not is_text and is_custom)
            ai_toggle.setVisible(is_single_text)
            row_count_widget.setVisible(is_matrix)
            option_label.setText("列数：" if is_matrix else "选项数量：")
            matrix_hint.setVisible(is_matrix)
            order_hint.setVisible(False)
            if is_matrix:
                slider_card.setVisible(False)
                strategy_label.setVisible(False)
                strategy_combo.setVisible(False)
            if is_order:
                slider_card.setVisible(False)
                strategy_label.setVisible(False)
                strategy_combo.setVisible(False)
                matrix_hint.setVisible(False)
            order_hint.setVisible(True)
            if not is_single_text:
                ai_toggle.setChecked(False)
            if is_text:
                set_text_area_enabled(not ai_toggle.isChecked())
            else:
                set_text_area_enabled(True)
            # 根据题目类型更新提示标签
            if q_type == "multiple":
                slider_hint_label.setText("拖动滑块设置各选项被选中的概率（数值越大概率越高）：")
            else:
                slider_hint_label.setText("拖动滑块设置答案分布比例（数值越大概率越高）：")
            if not is_text and is_custom:
                rebuild_sliders()

        def on_option_changed():
            strategy = _resolve_strategy()
            if strategy == "custom":
                rebuild_sliders()

        text_area_widget.setVisible(False)
        ai_toggle.setVisible(False)
        slider_card.setVisible(False)
        type_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        strategy_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        option_spin.valueChanged.connect(on_option_changed)
        ai_toggle.toggled.connect(on_ai_toggle)
        
        # 初始化时调用一次以同步控件可见性（默认完全随机不显示滑块）
        do_update_visibility()

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", dialog)
        ok_btn = PrimaryPushButton("添加", dialog)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            q_type = _resolve_q_type()
            option_count = max(1, option_spin.value())
            strategy = "random" if q_type in ("matrix", "order") else _resolve_strategy()
            rows = max(1, row_count_spin.value()) if q_type == "matrix" else 1

            if q_type in ("text", "multi_text"):
                # 从答案列表中收集文本
                texts = [e.text().strip() or "无" for e in text_edits]
                texts = [t for t in texts if t] or [DEFAULT_FILL_TEXT]
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=[1.0],
                    texts=texts,
                    rows=rows,
                    option_count=max(option_count, len(texts)),
                    distribution_mode="random",
                    custom_weights=None,
                    question_num=str(len(self.entries) + 1),
                    ai_enabled=bool(ai_toggle.isChecked()) if q_type == "text" else False,
                )
            elif q_type == "order":
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=-1,
                    texts=None,
                    rows=rows,
                    option_count=option_count,
                    distribution_mode="random",
                    custom_weights=None,
                    question_num=str(len(self.entries) + 1),
                )
            else:
                custom_weights = None
                if strategy == "custom" and sliders:
                    custom_weights = [float(max(0, s.value())) for s in sliders]
                    # 不再检查是否全部相等，保留用户设置的权重
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=-1 if strategy == "random" else (custom_weights or [1.0] * option_count),
                    texts=None,
                    rows=rows,
                    option_count=option_count,
                    distribution_mode=strategy,
                    custom_weights=custom_weights,
                    question_num=str(len(self.entries) + 1),
                )

            self.entries.append(new_entry)
            self._refresh_table()

    def _delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            InfoBar.warning("", "请先选择要删除的题目", parent=self.window(), position=InfoBarPosition.TOP, duration=1800)
            return
        for row in rows:
            if 0 <= row < len(self.entries):
                self.entries.pop(row)
        self._refresh_table()

    def _generate_ai_answers(self):
        """使用 AI 为填空题生成答案"""
        if not ensure_ai_ready(self.window() or self):
            return

        # 找出所有填空题
        text_questions = []
        for idx, entry in enumerate(self.entries):
            if entry.question_type == "text":
                info = self.questions_info[idx] if idx < len(self.questions_info) else {}
                title = info.get("title", f"第{idx + 1}题")
                text_questions.append((idx, entry, title))

        if not text_questions:
            InfoBar.info("", "当前没有填空题需要生成答案", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
            return

        InfoBar.info("", f"正在为 {len(text_questions)} 道填空题生成答案...", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

        success_count = 0
        fail_count = 0
        for idx, entry, title in text_questions:
            try:
                answer = generate_answer(title)
                if answer:
                    # 更新 entry 的答案
                    entry.texts = [answer]
                    success_count += 1
            except Exception as e:
                fail_count += 1

        self._refresh_table()

        if fail_count == 0:
            InfoBar.success("", f"成功为 {success_count} 道填空题生成答案", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
        else:
            InfoBar.warning("", f"生成完成：成功 {success_count} 道，失败 {fail_count} 道", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    # ---------- table helpers ----------
    def _refresh_table(self):
        self.table.setRowCount(0)
        for idx, entry in enumerate(self.entries):
            self._insert_row(idx, entry)
        self.table.resizeColumnsToContents()
        try:
            self.entriesChanged.emit(int(self.table.rowCount()))
        except Exception:
            pass

    def _insert_row(self, row: int, entry: QuestionEntry):
        self.table.insertRow(row)
        info = self.questions_info[row] if row < len(self.questions_info) else {}
        qnum = str(info.get("num") or entry.question_num or row + 1)
        num_item = QTableWidgetItem(qnum)
        num_item.setData(Qt.ItemDataRole.UserRole, qnum)
        self.table.setItem(row, 0, num_item)

        # 类型
        type_label = _get_entry_type_label(entry)
        self.table.setItem(row, 1, QTableWidgetItem(type_label))

        # 选项数
        option_count = max(1, int(entry.option_count or 1))
        self.table.setItem(row, 2, QTableWidgetItem(str(option_count)))

        # 配置详情 - 显示有意义的摘要
        detail = ""
        if entry.question_type in ("text", "multi_text"):
            texts = entry.texts or []
            if texts:
                detail = f"答案: {' | '.join(texts[:3])}"
                if len(texts) > 3:
                    detail += f" (+{len(texts)-3})"
            else:
                detail = "答案: 无"
            if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
                detail += " | AI"
        elif entry.question_type == "matrix":
            rows = max(1, int(entry.rows or 1))
            cols = max(1, int(entry.option_count or 1))
            if isinstance(entry.custom_weights, list) or isinstance(entry.probabilities, list):
                detail = f"{rows} 行 × {cols} 列 | 按行配比"
            else:
                detail = f"{rows} 行 × {cols} 列 | 完全随机"
        elif entry.question_type == "order":
            detail = "排序题 | 自动随机排序"
        elif entry.custom_weights:
            weights = entry.custom_weights
            detail = f"自定义配比: {','.join(str(int(w)) for w in weights[:5])}"
            if len(weights) > 5:
                detail += "..."
        else:
            strategy = entry.distribution_mode or "random"
            if strategy not in ("random", "custom"):
                strategy = "random"
            if getattr(entry, "probabilities", None) == -1:
                strategy = "random"
            detail = "完全随机" if strategy == "random" else "自定义配比"
        self.table.setItem(row, 3, QTableWidgetItem(detail))

    def _entry_from_row(self, row: int) -> QuestionEntry:
        # 表格现在是只读显示，直接返回 entries 中的条目
        if row < len(self.entries):
            return self.entries[row]
        # 兜底：返回一个默认条目
        return QuestionEntry(
            question_type="single",
            probabilities=-1,
            texts=None,
            rows=1,
            option_count=4,
            distribution_mode="random",
            custom_weights=None,
            question_num=str(row + 1),
        )
