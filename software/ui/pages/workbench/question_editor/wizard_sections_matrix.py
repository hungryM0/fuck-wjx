"""向导矩阵与排序题配置区。"""
from typing import TYPE_CHECKING, Any, Dict, List

from PySide6.QtCore import QByteArray, QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, LineEdit, ScrollArea, SegmentedWidget

from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.widgets.no_wheel import NoWheelSlider

from .psycho_config import BIAS_PRESET_CHOICES, PSYCHO_SUPPORTED_TYPES, build_bias_weights
from .utils import _apply_label_color, _bind_slider_input, _configure_wrapped_text_label, _shorten_text


class WizardSectionsMatrixMixin:
    if TYPE_CHECKING:
        _has_content: bool
        matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]]
        bias_preset_map: Dict[int, Any]

        def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
        def _resolve_matrix_weights(self, entry: QuestionEntry, rows: int, columns: int) -> List[List[float]]: ...
        def _refresh_ratio_preview_label(
            self,
            label: BodyLabel,
            sliders: List[NoWheelSlider],
            option_names: List[str],
            prefix: str,
        ) -> None: ...

    def _build_matrix_section(self, idx: int, entry: QuestionEntry, card: CardWidget,
                              card_layout: QVBoxLayout, option_texts: List[str], row_texts: List[str]) -> None:
        self._has_content = True
        info_rows = self._get_entry_info(idx).get("rows", 0)
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
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        _is_psycho = entry.question_type in PSYCHO_SUPPORTED_TYPES
        _saved_bias = getattr(entry, "psycho_bias", None)
        _matrix_row_preset_segs = []

        per_row_scroll = ScrollArea(card)
        per_row_scroll.setWidgetResizable(True)
        per_row_scroll.setMinimumHeight(180)
        per_row_scroll.setMaximumHeight(320)
        per_row_scroll.enableTransparentBackground()
        per_row_view = QWidget(card)
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
                text_label = BodyLabel(opt_text, parent_widget)
                _configure_wrapped_text_label(text_label, 160)
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

                value_input = LineEdit(parent_widget)
                value_input.setFixedWidth(60)
                value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                value_input.setText(str(slider.value()))
                _bind_slider_input(slider, value_input)
                opt_layout.addWidget(value_input)

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
                row_label = BodyLabel(_shorten_text(f"第{row_idx + 1}行：{row_label_text}", 60), row_card)
            else:
                row_label = BodyLabel(f"第{row_idx + 1}行", row_card)
            row_label.setStyleSheet("font-weight: 500;")
            _apply_label_color(row_label, "#444444", "#e0e0e0")
            row_card_layout.addWidget(row_label)

            if _is_psycho:
                r_preset_row = QHBoxLayout()
                r_preset_row.setSpacing(8)
                r_preset_lbl = BodyLabel("倾向预设：", row_card)
                r_preset_lbl.setStyleSheet("font-size: 12px;")
                _apply_label_color(r_preset_lbl, "#666666", "#bfbfbf")
                r_preset_row.addWidget(r_preset_lbl)
                r_seg = SegmentedWidget(row_card)
                for _v, _t in BIAS_PRESET_CHOICES:
                    r_seg.addItem(routeKey=_v, text=_t)
                if isinstance(_saved_bias, list) and row_idx < len(_saved_bias):
                    r_seg.setCurrentItem(_saved_bias[row_idx] or "custom")
                else:
                    r_seg.setCurrentItem((_saved_bias if isinstance(_saved_bias, str) else None) or "custom")
                r_preset_row.addWidget(r_seg)
                r_preset_row.addStretch(1)
                row_card_layout.addLayout(r_preset_row)
                _matrix_row_preset_segs.append(r_seg)

            row_sliders = build_slider_rows(row_card, row_card_layout, per_row_values[row_idx])
            per_row_sliders.append(row_sliders)

            row_preview_label = BodyLabel("", row_card)
            row_preview_label.setWordWrap(True)
            row_preview_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(row_preview_label, "#666666", "#bfbfbf")
            row_card_layout.addWidget(row_preview_label)

            def _make_row_preview_update(
                _label: BodyLabel = row_preview_label,
                _row_sliders: List[NoWheelSlider] = row_sliders,
            ):
                def _update(_value: int = 0):
                    self._refresh_ratio_preview_label(
                        _label,
                        _row_sliders,
                        option_texts,
                        "本行目标占比（实际会小幅波动）：",
                    )
                return _update

            _row_preview_update = _make_row_preview_update()
            for _slider in row_sliders:
                _slider.valueChanged.connect(_row_preview_update)
            _row_preview_update()
            per_row_layout.addWidget(row_card)

        self.matrix_row_slider_map[idx] = per_row_sliders

        # 每行预设 ↔ 该行滑块联动
        if _matrix_row_preset_segs:
            self.bias_preset_map[idx] = _matrix_row_preset_segs

            def _wire_row(seg, sliders, cols):
                _flag = [False]
                _anims: Dict[object, QPropertyAnimation] = {}

                def _on_preset(route_key):
                    if route_key == "custom":
                        return
                    _flag[0] = True
                    weights = build_bias_weights(cols, route_key)
                    for si, sl in enumerate(sliders):
                        old = _anims.get(sl)
                        if old:
                            old.stop()
                        target = int(weights[si]) if si < len(weights) else 1
                        anim = QPropertyAnimation(sl, QByteArray(b"value"), sl)
                        anim.setDuration(300)
                        anim.setStartValue(sl.value())
                        anim.setEndValue(target)
                        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                        anim.start()
                        _anims[sl] = anim
                    QTimer.singleShot(320, lambda: _flag.__setitem__(0, False))

                seg.currentItemChanged.connect(_on_preset)

                def _on_slider(_):
                    if _flag[0]:
                        return
                    if seg.currentRouteKey() != "custom":
                        seg.setCurrentItem("custom")
                for sl in sliders:
                    sl.valueChanged.connect(_on_slider)

            for r_seg, row_sl in zip(_matrix_row_preset_segs, per_row_sliders):
                _wire_row(r_seg, row_sl, columns)
    def _build_order_section(self, card: CardWidget, card_layout: QVBoxLayout, option_texts: List[str]) -> None:
        self._has_content = True
        hint = BodyLabel("排序题无需设置配比，执行时会随机排序；如题干要求仅排序前 N 项，将自动识别。", card)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        if option_texts:
            list_container = QWidget(card)
            list_layout = QVBoxLayout(list_container)
            list_layout.setContentsMargins(0, 6, 0, 0)
            list_layout.setSpacing(4)
            for opt_idx, opt_text in enumerate(option_texts, 1):
                item = BodyLabel(f"{opt_idx}. {opt_text}", card)
                item.setWordWrap(True)
                item.setStyleSheet("font-size: 12px;")
                _apply_label_color(item, "#666666", "#c8c8c8")
                list_layout.addWidget(item)
            card_layout.addWidget(list_container)
