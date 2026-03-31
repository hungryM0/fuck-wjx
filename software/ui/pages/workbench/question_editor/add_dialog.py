"""新增题目弹窗：基础信息 + 题目配置预览。"""
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
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
)

from software.ui.widgets.no_wheel import NoWheelSpinBox
from software.core.questions.config import QuestionEntry
from software.app.config import DEFAULT_FILL_TEXT

from .constants import TYPE_CHOICES, STRATEGY_CHOICES
from .utils import _apply_label_color
from .add_preview import AddPreviewMixin


class QuestionAddDialog(AddPreviewMixin, QDialog):
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
        self.strategy_row_widget.setVisible(not is_text and not is_matrix and not is_order)
        self.row_count_widget.setVisible(is_matrix)
        self.matrix_strategy_widget.setVisible(is_matrix)
        self.option_label.setText("列数：" if is_matrix else "选项数量：")
        self.answer_count_widget.setVisible(is_text)

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

    def _build_entry(self) -> QuestionEntry:
        q_type = self._resolve_q_type()
        option_count = self._current_option_count()
        rows = self._current_row_count()

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
                text_random_mode="none",
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
        )

    def _on_accept(self) -> None:
        self._result_entry = self._build_entry()
        super().accept()

