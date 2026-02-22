"""新增题目弹窗：基础信息 + 题目配置预览。"""
from typing import List, Optional
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLayout,
    QDialog,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    ComboBox,
    LineEdit,
    CheckBox,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.core.questions.config import QuestionEntry
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.ui.helpers.ai_fill import ensure_ai_ready

from .constants import TYPE_CHOICES, STRATEGY_CHOICES, _get_type_label
from .utils import _apply_label_color, _bind_slider_input


class QuestionAddDialog(QDialog):
    """新增题目弹窗：基础信息 + 题目配置预览。"""



    def __init__(self, entries: List[QuestionEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增题目")
        self.resize(760, 680)
        self._entry_index = len(entries) + 1
        self._result_entry: Optional[QuestionEntry] = None
        self._text_answers: List[str] = [DEFAULT_FILL_TEXT]
        self._text_edits: List[LineEdit] = []
        self._slider_values: List[float] = []
        self._matrix_weights: List[List[float]] = []
        self._ai_enabled = False
        self._option_backup: Optional[int] = None
        self._matrix_strategy = ""
        self._is_reverse = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = SubtitleLabel("新增题目", self)
        desc = BodyLabel("先选择题型与策略，再在下方配置预览中调整细节。", self)
        desc.setStyleSheet("font-size: 12px;")
        _apply_label_color(desc, "#666666", "#bfbfbf")
        layout.addWidget(title)
        layout.addWidget(desc)

        base_card = CardWidget(self)
        base_layout = QVBoxLayout(base_card)
        base_layout.setContentsMargins(16, 12, 16, 12)
        base_layout.setSpacing(10)
        base_layout.addWidget(SubtitleLabel("基础信息", base_card))

        # 题目类型
        type_row_widget = QWidget(base_card)
        type_row = QHBoxLayout(type_row_widget)
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(8)
        type_row.addWidget(BodyLabel("题目类型：", base_card))
        self.type_combo = ComboBox(base_card)
        for value, label in TYPE_CHOICES:
            self.type_combo.addItem(label, value)
        self.type_combo.setCurrentIndex(0)
        type_row.addWidget(self.type_combo, 1)
        base_layout.addWidget(type_row_widget)

        # 填写策略
        self.strategy_row_widget = QWidget(base_card)
        strategy_row = QHBoxLayout(self.strategy_row_widget)
        strategy_row.setContentsMargins(0, 0, 0, 0)
        strategy_row.setSpacing(8)
        strategy_row.addWidget(BodyLabel("填写策略：", base_card))
        self.strategy_combo = ComboBox(base_card)
        for value, label in STRATEGY_CHOICES:
            self.strategy_combo.addItem(label, value)
        self.strategy_combo.setCurrentIndex(0)
        strategy_row.addWidget(self.strategy_combo, 1)
        base_layout.addWidget(self.strategy_row_widget)

        # 反向题复选框（仅量表/矩阵/评价题显示）
        self.reverse_row_widget = QWidget(base_card)
        reverse_row = QHBoxLayout(self.reverse_row_widget)
        reverse_row.setContentsMargins(0, 0, 0, 0)
        reverse_row.setSpacing(8)
        self.reverse_check = CheckBox("反向题", base_card)
        self.reverse_check.setToolTip("勾选后，信效度一致性约束会翻转该题的基准偏好（正向高分 → 反向低分）")
        self.reverse_check.setChecked(False)
        reverse_row.addWidget(self.reverse_check)
        reverse_row.addStretch(1)
        self.reverse_row_widget.setVisible(False)
        base_layout.addWidget(self.reverse_row_widget)
        self.option_row_widget = QWidget(base_card)
        option_row = QHBoxLayout(self.option_row_widget)
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(8)
        self.option_label = BodyLabel("选项数量：", base_card)
        option_row.addWidget(self.option_label)
        self.option_spin = NoWheelSpinBox(base_card)
        self.option_spin.setRange(1, 20)
        self.option_spin.setValue(4)
        option_row.addWidget(self.option_spin, 1)
        base_layout.addWidget(self.option_row_widget)

        # 填空题答案数量（只读）
        self.answer_count_widget = QWidget(base_card)
        answer_count_layout = QHBoxLayout(self.answer_count_widget)
        answer_count_layout.setContentsMargins(0, 0, 0, 0)
        answer_count_layout.setSpacing(8)
        answer_count_layout.addWidget(BodyLabel("答案数量：", base_card))
        self.answer_count_label = BodyLabel(str(len(self._text_answers or [])), base_card)
        self.answer_count_label.setStyleSheet("color: #666;")
        answer_count_layout.addWidget(self.answer_count_label, 1)
        base_layout.addWidget(self.answer_count_widget)

        # 矩阵行数
        self.row_count_widget = QWidget(base_card)
        row_count_layout = QHBoxLayout(self.row_count_widget)
        row_count_layout.setContentsMargins(0, 0, 0, 0)
        row_count_layout.setSpacing(8)
        row_count_layout.addWidget(BodyLabel("行数：", base_card))
        self.row_count_spin = NoWheelSpinBox(base_card)
        self.row_count_spin.setRange(1, 50)
        self.row_count_spin.setValue(2)
        row_count_layout.addWidget(self.row_count_spin, 1)
        base_layout.addWidget(self.row_count_widget)

        # 矩阵策略
        self.matrix_strategy_widget = QWidget(base_card)
        matrix_strategy_layout = QHBoxLayout(self.matrix_strategy_widget)
        matrix_strategy_layout.setContentsMargins(0, 0, 0, 0)
        matrix_strategy_layout.setSpacing(8)
        matrix_strategy_layout.addWidget(BodyLabel("矩阵策略：", base_card))
        self.matrix_strategy_combo = ComboBox(base_card)
        self.matrix_strategy_combo.addItem("完全随机", "random")
        self.matrix_strategy_combo.addItem("按行配比", "custom")
        self.matrix_strategy_combo.setCurrentIndex(0)
        matrix_strategy_layout.addWidget(self.matrix_strategy_combo, 1)
        base_layout.addWidget(self.matrix_strategy_widget)

        layout.addWidget(base_card)

        preview_card = CardWidget(self)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 12, 16, 12)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(SubtitleLabel("配置预览", preview_card))
        preview_desc = BodyLabel("这里展示该题的配置样式，你可以直接调整。", preview_card)
        preview_desc.setStyleSheet("font-size: 12px;")
        _apply_label_color(preview_desc, "#666666", "#bfbfbf")
        preview_layout.addWidget(preview_desc)

        self.preview_scroll = ScrollArea(preview_card)
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.enableTransparentBackground()
        self.preview_container = QWidget(preview_card)
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_layout.setSpacing(12)
        self.preview_scroll.setWidget(self.preview_container)
        preview_layout.addWidget(self.preview_scroll, 1)
        layout.addWidget(preview_card, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        ok_btn = PrimaryPushButton("添加", self)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self._on_accept)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.option_spin.valueChanged.connect(self._on_option_changed)
        self.row_count_spin.valueChanged.connect(self._on_row_changed)
        self.matrix_strategy_combo.currentIndexChanged.connect(self._on_matrix_strategy_changed)
        self.matrix_strategy_combo.currentTextChanged.connect(self._on_matrix_strategy_changed)

        self._matrix_strategy = self._resolve_matrix_strategy_from_combo()
        self._sync_base_visibility()
        self._rebuild_preview()

    def get_entry(self) -> Optional[QuestionEntry]:
        return self._result_entry

    def _clear_layout(self, layout: QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    def _sync_text_answers_from_edits(self) -> None:
        if not self._text_edits:
            return
        texts = [e.text().strip() for e in self._text_edits if e.text().strip()]
        self._text_answers = texts or self._text_answers or [DEFAULT_FILL_TEXT]

    def _ensure_slider_values(self, count: int, default_value: float) -> None:
        if count <= 0:
            self._slider_values = []
            return
        if not self._slider_values:
            self._slider_values = [float(default_value)] * count
            return
        if len(self._slider_values) < count:
            self._slider_values += [float(default_value)] * (count - len(self._slider_values))
        elif len(self._slider_values) > count:
            self._slider_values = self._slider_values[:count]

    def _ensure_matrix_weights(self, rows: int, columns: int) -> None:
        if rows <= 0 or columns <= 0:
            self._matrix_weights = []
            return
        while len(self._matrix_weights) < rows:
            self._matrix_weights.append([1.0] * columns)
        if len(self._matrix_weights) > rows:
            self._matrix_weights = self._matrix_weights[:rows]
        for idx, row in enumerate(self._matrix_weights):
            if len(row) < columns:
                row.extend([1.0] * (columns - len(row)))
            elif len(row) > columns:
                self._matrix_weights[idx] = row[:columns]

    def _resolve_q_type(self) -> str:
        idx = self.type_combo.currentIndex()
        if 0 <= idx < len(TYPE_CHOICES):
            return TYPE_CHOICES[idx][0]
        return self.type_combo.currentData() or "single"

    def _resolve_strategy(self) -> str:
        idx = self.strategy_combo.currentIndex()
        if 0 <= idx < len(STRATEGY_CHOICES):
            return STRATEGY_CHOICES[idx][0]
        return self.strategy_combo.currentData() or "random"

    def _resolve_matrix_strategy_from_combo(self) -> str:
        data = self.matrix_strategy_combo.currentData()
        if data:
            return str(data)
        text = (self.matrix_strategy_combo.currentText() or "").strip()
        if "按行" in text:
            return "custom"
        return "random"

    def _resolve_matrix_strategy(self) -> str:
        if self._matrix_strategy:
            return self._matrix_strategy
        return self._resolve_matrix_strategy_from_combo()

    def _current_option_count(self) -> int:
        q_type = self._resolve_q_type()
        if q_type == "slider":
            return 1
        return max(1, int(self.option_spin.value()))

    def _current_row_count(self) -> int:
        if self._resolve_q_type() != "matrix":
            return 1
        return max(1, int(self.row_count_spin.value()))

    def _sync_base_visibility(self) -> None:
        q_type = self._resolve_q_type()
        is_text = q_type in ("text", "multi_text")
        is_slider = q_type == "slider"
        is_matrix = q_type == "matrix"
        is_order = q_type == "order"
        is_reverse_applicable = q_type in ("scale", "matrix", "score")

        self.strategy_row_widget.setVisible(not is_text and not is_matrix and not is_order)
        self.row_count_widget.setVisible(is_matrix)
        self.matrix_strategy_widget.setVisible(is_matrix)
        self.option_label.setText("列数：" if is_matrix else "选项数量：")
        self.answer_count_widget.setVisible(is_text)
        self.reverse_row_widget.setVisible(is_reverse_applicable)

        if is_slider:
            if self._option_backup is None:
                self._option_backup = int(self.option_spin.value())
            self.option_spin.blockSignals(True)
            self.option_spin.setValue(1)
            self.option_spin.blockSignals(False)
            self.option_row_widget.setVisible(False)
        elif is_text:
            self.option_row_widget.setVisible(False)
        else:
            self.option_row_widget.setVisible(True)
            if self._option_backup is not None:
                self.option_spin.blockSignals(True)
                self.option_spin.setValue(max(1, int(self._option_backup)))
                self.option_spin.blockSignals(False)
                self._option_backup = None

    def _on_type_changed(self) -> None:
        self._sync_text_answers_from_edits()
        self._sync_base_visibility()
        if self._resolve_q_type() == "matrix":
            self._matrix_strategy = self._resolve_matrix_strategy_from_combo()
        self._rebuild_preview()

    def _on_strategy_changed(self) -> None:
        self._rebuild_preview()

    def _on_option_changed(self) -> None:
        self._rebuild_preview()

    def _on_row_changed(self) -> None:
        self._rebuild_preview()

    def _on_matrix_strategy_changed(self) -> None:
        self._matrix_strategy = self._resolve_matrix_strategy_from_combo()
        self._rebuild_preview()

    def _on_ai_toggled(self, checked: bool) -> None:
        if checked and not ensure_ai_ready(self.window() or self):
            try:
                if self.ai_toggle is not None:
                    self.ai_toggle.blockSignals(True)
                    self.ai_toggle.setChecked(False)
                    self.ai_toggle.blockSignals(False)
            except Exception as exc:
                log_suppressed_exception("_on_ai_toggled: if self.ai_toggle is not None: self.ai_toggle.blockSignals(True) self.ai_togg...", exc, level=logging.WARNING)
            self._set_text_area_enabled(True)
            return
        self._ai_enabled = bool(checked)
        self._set_text_area_enabled(not checked)

    def _set_text_area_enabled(self, enabled: bool) -> None:
        if hasattr(self, "text_area_widget") and self.text_area_widget:
            self.text_area_widget.setEnabled(enabled)
        if hasattr(self, "text_add_btn") and self.text_add_btn:
            self.text_add_btn.setEnabled(enabled)

    def _update_text_answer_count(self) -> None:
        if not hasattr(self, "answer_count_label") or not self.answer_count_label:
            return
        count = len(self._text_edits) if self._text_edits else len(self._text_answers or [])
        self.answer_count_label.setText(str(max(1, int(count))))

    def _build_preview_header(self, card: CardWidget, layout: QVBoxLayout, q_type: str) -> None:
        header = QHBoxLayout()
        header.setSpacing(10)
        title = SubtitleLabel(f"第{self._entry_index}题", card)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)
        type_label = BodyLabel(f"[{_get_type_label(q_type)}]", card)
        type_label.setStyleSheet("color: #0078d4; font-size: 12px;")
        header.addWidget(type_label)
        header.addStretch(1)
        preview_tag = BodyLabel("预览", card)
        preview_tag.setStyleSheet("font-size: 12px;")
        _apply_label_color(preview_tag, "#888888", "#b0b0b0")
        header.addWidget(preview_tag)
        layout.addLayout(header)

    def _rebuild_preview(self) -> None:
        self._sync_text_answers_from_edits()
        q_type = self._resolve_q_type()
        option_count = self._current_option_count()
        rows = self._current_row_count()

        self._clear_layout(self.preview_layout)
        self._text_edits = []
        self.text_area_widget = None
        self.text_add_btn = None
        self.ai_toggle = None

        card = CardWidget(self.preview_container)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)
        self._build_preview_header(card, card_layout, q_type)

        if q_type in ("text", "multi_text"):
            self._rebuild_text_preview(card, card_layout, q_type)
        elif q_type == "matrix":
            self._rebuild_matrix_preview(card, card_layout, option_count, rows)
        elif q_type == "order":
            self._rebuild_order_preview(card, card_layout, option_count)
        else:
            self._rebuild_slider_preview(card, card_layout, q_type, option_count)

        self.preview_layout.addWidget(card)
        self.preview_layout.addStretch(1)

    def _rebuild_text_preview(self, card: CardWidget, card_layout: QVBoxLayout, q_type: str) -> None:
        hint = BodyLabel("答案列表（随机选择一个填入）：", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        self.text_area_widget = QWidget(card)
        text_area_layout = QVBoxLayout(self.text_area_widget)
        text_area_layout.setContentsMargins(0, 0, 0, 0)
        text_area_layout.setSpacing(4)
        card_layout.addWidget(self.text_area_widget)

        self._text_edits = []

        def add_text_row(initial_text: str = ""):
            row_widget = QWidget(self.text_area_widget)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(8)
            num_lbl = BodyLabel(f"{len(self._text_edits) + 1}.", row_widget)
            num_lbl.setFixedWidth(24)
            num_lbl.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_lbl, "#888888", "#a6a6a6")
            row_layout.addWidget(num_lbl)
            edit = LineEdit(row_widget)
            edit.setPlaceholderText("输入答案")
            edit.setText(initial_text)
            row_layout.addWidget(edit, 1)
            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(del_btn)
            text_area_layout.addWidget(row_widget)
            self._text_edits.append(edit)

            def remove_row():
                if len(self._text_edits) > 1:
                    self._text_edits.remove(edit)
                    row_widget.deleteLater()
                    self._update_text_answer_count()

            del_btn.clicked.connect(remove_row)
            self._update_text_answer_count()

        texts = self._text_answers or [DEFAULT_FILL_TEXT]
        for text in texts:
            add_text_row(text)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.text_add_btn = PushButton("+ 添加答案", card)
        self.text_add_btn.setFixedWidth(100)
        self.text_add_btn.clicked.connect(lambda checked=False: add_text_row(""))
        btn_row.addWidget(self.text_add_btn)

        if q_type == "text":
            self.ai_toggle = CheckBox("启用 AI", card)
            self.ai_toggle.setToolTip("运行时每次填空都会调用 AI")
            self.ai_toggle.setChecked(bool(self._ai_enabled))
            self.ai_toggle.toggled.connect(self._on_ai_toggled)
            btn_row.addWidget(self.ai_toggle)
            self._set_text_area_enabled(not self.ai_toggle.isChecked())
        else:
            self._set_text_area_enabled(True)

        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)
        self._update_text_answer_count()

    def _rebuild_matrix_preview(self, card: CardWidget, card_layout: QVBoxLayout,
                                option_count: int, rows: int) -> None:
        hint = BodyLabel("矩阵量表：每一行都需要单独设置配比", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        matrix_strategy = self._resolve_matrix_strategy()
        if matrix_strategy == "custom":
            self._ensure_matrix_weights(rows, option_count)
            for row_idx in range(rows):
                row_card = CardWidget(card)
                row_card_layout = QVBoxLayout(row_card)
                row_card_layout.setContentsMargins(12, 8, 12, 8)
                row_card_layout.setSpacing(6)
                row_label = BodyLabel(f"第{row_idx + 1}行", row_card)
                row_label.setStyleSheet("font-weight: 500;")
                _apply_label_color(row_label, "#444444", "#e0e0e0")
                row_card_layout.addWidget(row_label)

                for col_idx in range(option_count):
                    opt_widget = QWidget(row_card)
                    opt_layout = QHBoxLayout(opt_widget)
                    opt_layout.setContentsMargins(0, 2, 0, 2)
                    opt_layout.setSpacing(12)

                    opt_text = f"列 {col_idx + 1}"
                    text_label = BodyLabel(opt_text, row_card)
                    text_label.setFixedWidth(120)
                    text_label.setStyleSheet("font-size: 13px;")
                    opt_layout.addWidget(text_label)

                    slider = NoWheelSlider(Qt.Orientation.Horizontal, row_card)
                    slider.setRange(0, 100)
                    slider.setValue(int(self._matrix_weights[row_idx][col_idx]))
                    slider.setMinimumWidth(200)
                    opt_layout.addWidget(slider, 1)

                    value_input = LineEdit(row_card)
                    value_input.setFixedWidth(60)
                    value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    value_input.setText(str(slider.value()))
                    _bind_slider_input(slider, value_input)

                    def _on_matrix_slider_changed(value, r=row_idx, c=col_idx):
                        self._matrix_weights[r][c] = float(value)

                    slider.valueChanged.connect(_on_matrix_slider_changed)
                    opt_layout.addWidget(value_input)
                    row_card_layout.addWidget(opt_widget)

                card_layout.addWidget(row_card)
        else:
            hint_random = BodyLabel('当前为完全随机，切换为"按行配比"可编辑。', card)
            hint_random.setStyleSheet("font-size: 12px;")
            _apply_label_color(hint_random, "#888888", "#b0b0b0")
            card_layout.addWidget(hint_random)

    def _rebuild_order_preview(self, card: CardWidget, card_layout: QVBoxLayout, option_count: int) -> None:
        hint = BodyLabel("排序题无需设置配比，执行时会随机排序。", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        list_container = QWidget(card)
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 6, 0, 0)
        list_layout.setSpacing(4)
        display_count = min(option_count, 6)
        for idx in range(display_count):
            item = BodyLabel(f"{idx + 1}. 选项 {idx + 1}", card)
            item.setStyleSheet("font-size: 12px;")
            _apply_label_color(item, "#666666", "#c8c8c8")
            list_layout.addWidget(item)
        if option_count > display_count:
            more = BodyLabel(f"... 还有 {option_count - display_count} 项", card)
            more.setStyleSheet("font-size: 12px;")
            _apply_label_color(more, "#999999", "#b0b0b0")
            list_layout.addWidget(more)
        card_layout.addWidget(list_container)

    def _rebuild_slider_preview(self, card: CardWidget, card_layout: QVBoxLayout,
                                q_type: str, option_count: int) -> None:
        is_multiple = q_type == "multiple"
        is_slider = q_type == "slider"
        strategy = self._resolve_strategy()
        if is_slider and strategy == "random":
            hint_text = "滑块题：当前为完全随机，每次会在 0-100 范围内随机填写"
        elif is_slider:
            hint_text = "滑块题：此处数值代表填写时的目标值，会做小幅抖动避免每份相同（默认 0-100）"
        elif is_multiple:
            hint_text = "每个滑块的值对应的是选项的命中概率（%）"
        elif strategy == "random":
            hint_text = "当前为完全随机，切换为自定义配比可编辑。"
        else:
            hint_text = "拖动滑块设置答案分布配比"

        hint = BodyLabel(hint_text, card)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        count = 1 if is_slider else option_count
        default_weight = 50 if is_slider else (50 if is_multiple else 1)
        self._ensure_slider_values(count, default_weight)

        sliders_container = QWidget(card)
        sliders_layout = QVBoxLayout(sliders_container)
        sliders_layout.setContentsMargins(0, 4, 0, 0)
        sliders_layout.setSpacing(6)
        for idx in range(count):
            opt_widget = QWidget(sliders_container)
            opt_layout = QHBoxLayout(opt_widget)
            opt_layout.setContentsMargins(0, 2, 0, 2)
            opt_layout.setSpacing(12)

            num_label = BodyLabel(f"{idx + 1}.", opt_widget)
            num_label.setFixedWidth(24)
            num_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_label, "#888888", "#a6a6a6")
            opt_layout.addWidget(num_label)

            opt_text = "目标值" if is_slider else f"选项 {idx + 1}"
            text_label = BodyLabel(opt_text, opt_widget)
            text_label.setFixedWidth(120)
            text_label.setStyleSheet("font-size: 13px;")
            opt_layout.addWidget(text_label)

            slider = NoWheelSlider(Qt.Orientation.Horizontal, opt_widget)
            if is_slider:
                slider.setRange(0, 100)
            else:
                slider.setRange(0, 100)
            slider.setValue(int(min(slider.maximum(), max(slider.minimum(), self._slider_values[idx]))))
            slider.setMinimumWidth(200)
            opt_layout.addWidget(slider, 1)

            value_input = LineEdit(opt_widget)
            value_input.setFixedWidth(60)
            value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_input.setText(str(slider.value()))

            def _on_slider_changed(value, index=idx):
                if index < len(self._slider_values):
                    self._slider_values[index] = float(value)

            _bind_slider_input(slider, value_input)
            slider.valueChanged.connect(_on_slider_changed)
            opt_layout.addWidget(value_input)
            if is_multiple:
                percent_label = BodyLabel("%", opt_widget)
                percent_label.setFixedWidth(12)
                percent_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                _apply_label_color(percent_label, "#666666", "#bfbfbf")
                opt_layout.addWidget(percent_label)

            sliders_layout.addWidget(opt_widget)

        if strategy == "random":
            sliders_container.setEnabled(False)
        card_layout.addWidget(sliders_container)

    def _build_entry(self) -> QuestionEntry:
        q_type = self._resolve_q_type()
        option_count = self._current_option_count()
        rows = self._current_row_count()

        # 获取反向题标记（仅量表/矩阵/评价题有效）
        is_reverse = bool(
            q_type in ("scale", "matrix", "score")
            and hasattr(self, "reverse_check")
            and self.reverse_check.isChecked()
        )

        if q_type in ("text", "multi_text"):
            self._sync_text_answers_from_edits()
            texts = [t for t in (self._text_answers or []) if t]
            texts = texts or [DEFAULT_FILL_TEXT]
            return QuestionEntry(
                question_type=q_type,
                probabilities=[1.0],
                texts=texts,
                rows=rows,
                option_count=len(texts),
                distribution_mode="random",
                custom_weights=None,
                question_num=self._entry_index,
                ai_enabled=bool(self._ai_enabled) if q_type == "text" else False,
                dimension=None,
            )
        if q_type == "order":
            return QuestionEntry(
                question_type=q_type,
                probabilities=-1,
                texts=None,
                rows=rows,
                option_count=option_count,
                distribution_mode="random",
                custom_weights=None,
                question_num=self._entry_index,
                dimension=None,
            )
        if q_type == "matrix":
            matrix_strategy = self._resolve_matrix_strategy()
            if matrix_strategy == "custom":
                self._ensure_matrix_weights(rows, option_count)
                weights = [[float(max(0, v)) for v in row] for row in self._matrix_weights]
                from typing import Any, cast
                return QuestionEntry(
                    question_type=q_type,
                    probabilities=cast(Any, weights),
                    texts=None,
                    rows=rows,
                    option_count=option_count,
                    distribution_mode="custom",
                    custom_weights=cast(Any, weights),
                    question_num=self._entry_index,
                    dimension=None,
                    is_reverse=is_reverse,
                )
            return QuestionEntry(
                question_type=q_type,
                probabilities=-1,
                texts=None,
                rows=rows,
                option_count=option_count,
                distribution_mode="random",
                custom_weights=None,
                question_num=self._entry_index,
                dimension=None,
                is_reverse=is_reverse,
            )

        strategy = self._resolve_strategy()
        count = 1 if q_type == "slider" else option_count
        default_weight = 50 if q_type == "slider" else (50 if q_type == "multiple" else 1)
        self._ensure_slider_values(count, default_weight)
        custom_weights = None
        if strategy == "custom":
            custom_weights = [float(max(0, min(100, v))) for v in self._slider_values[:count]]
            if q_type == "slider":
                custom_weights = [custom_weights[0] if custom_weights else 50.0]
                option_count = 1

        probabilities = -1 if strategy == "random" else (custom_weights or [1.0] * count)
        return QuestionEntry(
            question_type=q_type,
            probabilities=probabilities,
            texts=None,
            rows=rows,
            option_count=option_count,
            distribution_mode=strategy,
            custom_weights=custom_weights,
            question_num=self._entry_index,
            dimension=None,
            is_reverse=is_reverse,
        )

    def _on_accept(self) -> None:
        self._result_entry = self._build_entry()
        super().accept()
