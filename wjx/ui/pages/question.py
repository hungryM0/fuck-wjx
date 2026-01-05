"""题目配置页面和配置向导"""
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt, Signal
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
    InfoBar,
    InfoBarPosition,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.engine import QuestionEntry
from wjx.utils.config import DEFAULT_FILL_TEXT

# 题目类型选项
TYPE_CHOICES = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("text", "填空题"),
    ("multi_text", "多项填空题"),
    ("dropdown", "下拉题"),
    ("matrix", "矩阵题"),
    ("scale", "量表题"),
    ("slider", "滑块题"),
]

# 填写策略选项
STRATEGY_CHOICES = [
    ("random", "完全随机"),
    ("uniform", "均匀分布"),
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
        "slider": "滑块题",
    }
    return type_map.get(entry.question_type, entry.question_type)


class QuestionWizardDialog(QDialog):
    """配置向导：用滑块快速设置权重。"""

    @staticmethod
    def _shorten(text: str, limit: int = 120) -> str:
        if not text:
            return ""
        text = str(text).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def __init__(self, entries: List[QuestionEntry], info: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置向导")
        self.resize(900, 700)
        self.entries = entries
        self.info = info or []
        self.slider_map: Dict[int, List[NoWheelSlider]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget(self)
        scroll.setWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(10)

        intro = BodyLabel(
            "拖动滑块为每个选项设置权重：数值越大，被选中的概率越高；默认均为 1，可根据需要调整。",
            self,
        )
        intro.setWordWrap(True)
        inner.addWidget(intro)

        for idx, entry in enumerate(entries):
            if entry.question_type in ("text", "multi_text"):
                continue
            card = CardWidget(container)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(8)
            qnum = ""
            title_text = ""
            option_texts: List[str] = []
            if idx < len(self.info):
                qnum = str(self.info[idx].get("num") or "")
                title_text = str(self.info[idx].get("title") or "")
                opt_raw = self.info[idx].get("option_texts")
                if isinstance(opt_raw, list):
                    option_texts = [str(x) for x in opt_raw]
            title = SubtitleLabel(f"第{qnum or idx + 1}题 · {_get_entry_type_label(entry)}", card)
            card_layout.addWidget(title)
            if title_text:
                title_label = BodyLabel(self._shorten(title_text, 200), card)
                title_label.setWordWrap(True)
                title_label.setStyleSheet("color:#444;")
                card_layout.addWidget(title_label)

            options = max(1, int(entry.option_count or 1))
            weights = list(entry.custom_weights or [])
            if len(weights) < options:
                weights += [1] * (options - len(weights))
            if all(w <= 0 for w in weights):
                weights = [1] * options

            sliders: List[NoWheelSlider] = []
            for opt_idx in range(options):
                row = QHBoxLayout()
                row.setSpacing(8)
                opt_label_text = option_texts[opt_idx] if opt_idx < len(option_texts) else ""
                prefix = f"{opt_idx + 1}. "
                display_text = prefix + self._shorten(opt_label_text or "选项", 140)
                row.addWidget(BodyLabel(display_text, card))
                slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
                slider.setRange(0, 100)
                slider.setValue(int(weights[opt_idx]))
                value_label = BodyLabel(str(slider.value()), card)
                slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(str(v)))
                row.addWidget(slider, 1)
                row.addWidget(value_label)
                card_layout.addLayout(row)
                sliders.append(slider)

            self.slider_map[idx] = sliders
            inner.addWidget(card)

        if not self.slider_map:
            inner.addWidget(BodyLabel("当前题目类型无需配置向导。", container))
        inner.addStretch(1)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = PrimaryPushButton("保存", self)
        cancel_btn = PushButton("取消", self)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def get_results(self) -> Dict[int, List[int]]:
        result: Dict[int, List[int]] = {}
        for idx, sliders in self.slider_map.items():
            weights = [max(0, s.value()) for s in sliders]
            if all(w <= 0 for w in weights):
                weights = [1] * len(weights)
            result[idx] = weights
        return result


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
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._add_entry)
        self.del_btn.clicked.connect(self._delete_selected)
        self.reset_btn.clicked.connect(self._reset_from_source)

    # ---------- data helpers ----------
    def set_questions(self, info: List[Dict[str, Any]], entries: List[QuestionEntry]):
        self.questions_info = info or []
        self.set_entries(entries, info)

    def set_entries(self, entries: List[QuestionEntry], info: Optional[List[Dict[str, Any]]] = None):
        self.questions_info = info or self.questions_info
        self.entries = list(entries or [])
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
        option_row.addWidget(BodyLabel("选项数量：", dialog))
        option_spin = NoWheelSpinBox(dialog)
        option_spin.setRange(1, 20)
        option_spin.setValue(4)
        option_row.addWidget(option_spin, 1)
        layout.addLayout(option_row)

        # 策略选择
        strategy_row = QHBoxLayout()
        strategy_label = BodyLabel("填写策略：", dialog)
        strategy_row.addWidget(strategy_label)
        strategy_combo = ComboBox(dialog)
        for value, label in STRATEGY_CHOICES:
            strategy_combo.addItem(label, value)
        strategy_combo.setCurrentIndex(1)  # 默认选择"自定义配比"
        strategy_row.addWidget(strategy_combo, 1)
        layout.addLayout(strategy_row)

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
                if item.widget():
                    item.widget().deleteLater()
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
            type_idx = type_combo.currentIndex()
            strategy_idx = strategy_combo.currentIndex()
            q_type = TYPE_CHOICES[type_idx][0] if 0 <= type_idx < len(TYPE_CHOICES) else "single"
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            is_text = q_type in ("text", "multi_text")
            is_custom = strategy == "custom"
            # 填空题时隐藏策略选择，显示答案列表
            strategy_label.setVisible(not is_text)
            strategy_combo.setVisible(not is_text)
            text_area_widget.setVisible(is_text)
            slider_card.setVisible(not is_text and is_custom)
            # 根据题目类型更新提示标签
            if q_type == "multiple":
                slider_hint_label.setText("拖动滑块设置各选项被选中的概率（数值越大概率越高）：")
            else:
                slider_hint_label.setText("拖动滑块设置答案分布比例（数值越大概率越高）：")
            if not is_text and is_custom:
                rebuild_sliders()

        def on_option_changed():
            strategy_idx = strategy_combo.currentIndex()
            strategy = STRATEGY_CHOICES[strategy_idx][0] if 0 <= strategy_idx < len(STRATEGY_CHOICES) else "random"
            if strategy == "custom":
                rebuild_sliders()

        text_area_widget.setVisible(False)
        slider_card.setVisible(False)
        type_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        strategy_combo.currentIndexChanged.connect(lambda _: do_update_visibility())
        option_spin.valueChanged.connect(on_option_changed)
        
        # 初始化时调用一次以显示滑块（因为默认是自定义配比）
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
            q_type = type_combo.currentData() or "single"
            option_count = max(1, option_spin.value())
            strategy = strategy_combo.currentData() or "random"

            if q_type in ("text", "multi_text"):
                # 从答案列表中收集文本
                texts = [e.text().strip() or "无" for e in text_edits]
                texts = [t for t in texts if t] or [DEFAULT_FILL_TEXT]
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=[1.0],
                    texts=texts,
                    rows=1,
                    option_count=max(option_count, len(texts)),
                    distribution_mode="random",
                    custom_weights=None,
                    question_num=str(len(self.entries) + 1),
                )
            else:
                custom_weights = None
                if strategy == "custom" and sliders:
                    custom_weights = [float(max(1, s.value())) for s in sliders]
                    if all(w == custom_weights[0] for w in custom_weights):
                        custom_weights = None
                new_entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=-1 if strategy == "random" else [1.0] * option_count,
                    texts=None,
                    rows=1,
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
        elif entry.custom_weights:
            weights = entry.custom_weights
            detail = f"自定义配比: {','.join(str(int(w)) for w in weights[:5])}"
            if len(weights) > 5:
                detail += "..."
        else:
            strategy = entry.distribution_mode or "random"
            if getattr(entry, "probabilities", None) == -1:
                strategy = "random"
            detail = "完全随机" if strategy == "random" else "均匀分布"
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
