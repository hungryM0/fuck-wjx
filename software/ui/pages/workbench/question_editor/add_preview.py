"""AddPreviewMixin：配置预览区 UI 构建方法，供 QuestionAddDialog 通过多继承引入。"""
import logging
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLayout
from qfluentwidgets import SubtitleLabel, BodyLabel, CardWidget, PushButton, LineEdit, CheckBox

from software.ui.widgets.no_wheel import NoWheelSlider
from software.app.config import DEFAULT_FILL_TEXT
from software.ui.helpers.ai_fill import ensure_ai_ready
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.logging.log_utils import log_suppressed_exception

from .constants import _get_type_label
from .utils import _apply_label_color, _bind_slider_input


class AddPreviewMixin:
    """配置预览区 UI 构建方法。依赖 QuestionAddDialog 的 state 属性。"""

    # ------- 以下属性/方法由主类（QuestionAddDialog）提供 -------
    _entry_index: int
    answer_count_label: Any
    preview_layout: QVBoxLayout
    preview_container: QWidget

    def _resolve_q_type(self) -> str: ...
    def _current_option_count(self) -> int: ...
    def _current_row_count(self) -> int: ...
    def _resolve_matrix_strategy(self) -> str: ...
    def _resolve_strategy(self) -> str: ...
    def window(self) -> Optional[QWidget]: ...

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

    def _on_ai_toggled(self, checked: bool) -> None:
        if checked and not ensure_ai_ready(self.window() or self):
            try:
                if self.ai_toggle is not None:
                    self.ai_toggle.blockSignals(True)
                    self.ai_toggle.setChecked(False)
                    self.ai_toggle.blockSignals(False)
            except Exception as exc:
                log_suppressed_exception("_on_ai_toggled", exc, level=logging.WARNING)
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
            install_tooltip_filter(self.ai_toggle)
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

                    text_label = BodyLabel(f"列 {col_idx + 1}", row_card)
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


