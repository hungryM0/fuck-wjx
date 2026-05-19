"""WizardSectionsMixin：各题型配置区 UI 构建方法。"""

from typing import Any, Dict, List, Tuple

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import QSizePolicy, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    SegmentedWidget,
)

from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.widgets.no_wheel import NoWheelSlider

from .psycho_config import (
    BIAS_PRESET_CHOICES,
    PSYCHO_SUPPORTED_TYPES,
    build_bias_weights,
)
from .wizard_sections_common import (
    WizardSectionsCommonMixin,
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
    _apply_ai_label_state_style,
)
from .wizard_sections_slider import WizardSectionsSliderMixin
from .wizard_sections_text import WizardSectionsTextMixin
from .utils import _apply_label_color, _bind_slider_input, _shorten_text
from .constants import ANSWER_WEIGHT_MAX, ANSWER_WEIGHT_MIN


class WizardSectionsMixin(
    WizardSectionsCommonMixin,
    WizardSectionsTextMixin,
    WizardSectionsSliderMixin,
):
    """各题型配置区 UI 构建方法。依赖 QuestionWizardDialog 的 state dict。"""

    text_container_map: Dict[int, Any]
    text_add_btn_map: Dict[int, Any]
    text_random_group_map: Dict[int, Any]
    text_random_list_radio_map: Dict[int, Any]
    text_random_name_check_map: Dict[int, Any]
    text_random_mobile_check_map: Dict[int, Any]
    text_random_id_card_check_map: Dict[int, Any]
    text_random_integer_check_map: Dict[int, Any]
    text_random_int_min_edit_map: Dict[int, Any]
    text_random_int_max_edit_map: Dict[int, Any]
    ai_check_map: Dict[int, Any]
    ai_label_map: Dict[int, Any]
    text_random_mode_map: Dict[int, str]
    text_edit_map: Dict[int, Any]
    info: List[Any]
    reliability_mode_enabled: bool
    matrix_row_slider_map: Dict[int, Any]
    entries: List[Any]
    slider_map: Dict[int, Any]
    bias_preset_map: Dict[int, Any]
    option_fill_edit_map: Dict[int, Any]
    option_fill_state_map: Dict[int, Any]

    def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
    def _media_items_for(
        self, idx: int, scope: str, index: int | None = None
    ) -> List[Dict[str, Any]]: ...
    def _resolve_matrix_weights(
        self, entry: QuestionEntry, rows: int, columns: int
    ) -> List[List[float]]: ...
    def _resolve_slider_bounds(self, idx: int, entry: Any) -> Tuple[int, int]: ...

    def _build_matrix_section(
        self,
        idx: int,
        entry: QuestionEntry,
        card: CardWidget,
        card_layout: QVBoxLayout,
        option_texts: List[str],
        row_texts: List[str],
    ) -> None:
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

        is_psycho = entry.question_type in PSYCHO_SUPPORTED_TYPES
        saved_bias = getattr(entry, "psycho_bias", None)
        matrix_row_preset_segs = []

        per_row_view = QWidget(card)
        per_row_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        per_row_layout = QVBoxLayout(per_row_view)
        per_row_layout.setContentsMargins(0, 0, 0, 0)
        per_row_layout.setSpacing(4)
        per_row_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        card_layout.addWidget(per_row_view)

        def build_slider_rows(
            parent_widget: QWidget,
            target_layout: QVBoxLayout,
            values: List[float],
        ) -> List[NoWheelSlider]:
            sliders: List[NoWheelSlider] = []
            for col_idx in range(columns):
                opt_widget = QWidget(parent_widget)
                opt_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
                opt_layout = QVBoxLayout(opt_widget)
                opt_layout.setContentsMargins(0, 0, 0, 2)
                opt_layout.setSpacing(2)
                opt_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

                header_row = QHBoxLayout()
                header_row.setContentsMargins(0, 0, 0, 0)
                header_row.setSpacing(8)

                opt_text = option_texts[col_idx] if col_idx < len(option_texts) else f"列 {col_idx + 1}"
                option_widget = self._build_media_text_widget(
                    parent_widget,
                    idx=idx,
                    scope="option",
                    media_index=col_idx,
                    text=opt_text,
                    text_width=140,
                    font_style="font-size: 13px;",
                )
                header_row.addWidget(option_widget, 0)

                slider = NoWheelSlider(Qt.Orientation.Horizontal, parent_widget)
                slider.setRange(ANSWER_WEIGHT_MIN, ANSWER_WEIGHT_MAX)
                try:
                    slider.setValue(int(values[col_idx]))
                except Exception:
                    slider.setValue(1)

                header_row.addStretch(1)

                control_row = QHBoxLayout()
                control_row.setContentsMargins(18, 0, 0, 0)
                control_row.setSpacing(8)

                value_input = LineEdit(parent_widget)
                value_input.setFixedWidth(52)
                value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                value_input.setText(str(slider.value()))
                _bind_slider_input(slider, value_input)

                slider.setMinimumWidth(48)
                slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                opt_layout.addLayout(header_row)
                control_row.addWidget(slider, 1)
                control_row.addWidget(value_input)
                opt_layout.addLayout(control_row)

                target_layout.addWidget(opt_widget)
                sliders.append(slider)
            return sliders

        matrix_weights = self._resolve_matrix_weights(entry, rows, columns)

        per_row_sliders: List[List[NoWheelSlider]] = []
        per_row_values = (
            matrix_weights if matrix_weights else [[1.0] * columns for _ in range(rows)]
        )
        for row_idx in range(rows):
            row_card = CardWidget(per_row_view)
            row_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            row_card_layout = QVBoxLayout(row_card)
            row_card_layout.setContentsMargins(10, 6, 10, 4)
            row_card_layout.setSpacing(3)
            row_card_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
            row_label_text = row_texts[row_idx] if row_idx < len(row_texts) else ""
            if row_label_text:
                row_label = BodyLabel(
                    _shorten_text(f"第{row_idx + 1}行：{row_label_text}", 60),
                    row_card,
                )
            else:
                row_label = BodyLabel(f"第{row_idx + 1}行", row_card)
            row_label.setStyleSheet("font-weight: 500;")
            _apply_label_color(row_label, "#444444", "#e0e0e0")
            row_card_layout.addWidget(row_label)

            if is_psycho:
                preset_row = QHBoxLayout()
                preset_row.setSpacing(8)
                preset_lbl = BodyLabel("倾向预设：", row_card)
                preset_lbl.setStyleSheet("font-size: 12px;")
                _apply_label_color(preset_lbl, "#666666", "#bfbfbf")
                preset_row.addWidget(preset_lbl)
                seg = SegmentedWidget(row_card)
                for value, text in BIAS_PRESET_CHOICES:
                    seg.addItem(routeKey=value, text=text)
                if isinstance(saved_bias, list) and row_idx < len(saved_bias):
                    current_bias = saved_bias[row_idx] or "custom"
                else:
                    current_bias = (saved_bias if isinstance(saved_bias, str) else None) or "custom"
                seg.setCurrentItem(current_bias)
                preset_row.addWidget(seg)
                preset_row.addStretch(1)
                row_card_layout.addLayout(preset_row)
                matrix_row_preset_segs.append(seg)

            row_sliders = build_slider_rows(row_card, row_card_layout, per_row_values[row_idx])
            per_row_sliders.append(row_sliders)

            row_preview_label = BodyLabel("", row_card)
            row_preview_label.setWordWrap(True)
            row_preview_label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Maximum,
            )
            row_preview_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(row_preview_label, "#666666", "#bfbfbf")
            row_card_layout.addWidget(row_preview_label)

            def make_row_preview_update(
                label: BodyLabel = row_preview_label,
                sliders: List[NoWheelSlider] = row_sliders,
            ):
                def update(_value: int = 0):
                    self._refresh_ratio_preview_label(
                        label,
                        sliders,
                        option_texts,
                        "本行目标占比（实际会小幅波动）：",
                    )

                return update

            row_preview_update = make_row_preview_update()
            for slider in row_sliders:
                slider.valueChanged.connect(row_preview_update)
            row_preview_update()
            per_row_layout.addWidget(row_card)

        self.matrix_row_slider_map[idx] = per_row_sliders

        if matrix_row_preset_segs:
            self.bias_preset_map[idx] = matrix_row_preset_segs

            def wire_row(seg, sliders, cols):
                flag = [False]
                anims: Dict[object, QPropertyAnimation] = {}

                def on_preset(route_key):
                    if route_key == "custom":
                        return
                    flag[0] = True
                    weights = build_bias_weights(cols, route_key)
                    for slider_index, slider in enumerate(sliders):
                        old = anims.get(slider)
                        if old:
                            old.stop()
                        target = int(weights[slider_index]) if slider_index < len(weights) else 1
                        anim = QPropertyAnimation(slider, QByteArray(b"value"), slider)
                        anim.setDuration(300)
                        anim.setStartValue(slider.value())
                        anim.setEndValue(target)
                        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                        anim.start()
                        anims[slider] = anim
                    QTimer.singleShot(320, lambda: flag.__setitem__(0, False))

                seg.currentItemChanged.connect(on_preset)

                def on_slider(_):
                    if flag[0]:
                        return
                    if seg.currentRouteKey() != "custom":
                        seg.setCurrentItem("custom")

                for slider in sliders:
                    slider.valueChanged.connect(on_slider)

            for seg, row_sliders in zip(matrix_row_preset_segs, per_row_sliders):
                wire_row(seg, row_sliders, columns)

    def _build_order_section(
        self,
        idx: int,
        card: CardWidget,
        card_layout: QVBoxLayout,
        option_texts: List[str],
    ) -> None:
        self._has_content = True
        if option_texts:
            list_container = QWidget(card)
            list_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            list_layout = QVBoxLayout(list_container)
            list_layout.setContentsMargins(0, 6, 0, 0)
            list_layout.setSpacing(4)
            for opt_idx, opt_text in enumerate(option_texts, 1):
                row_label = BodyLabel(
                    f"{opt_idx}. {str(opt_text or '').strip() or f'选项{opt_idx}'}",
                    list_container,
                )
                row_label.setWordWrap(True)
                row_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                row_label.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Maximum,
                )
                row_label.setStyleSheet("font-size: 12px;")
                _apply_label_color(row_label, "#444444", "#e0e0e0")
                list_layout.addWidget(row_label)
            card_layout.addWidget(list_container)


__all__ = [
    "WizardSectionsMixin",
    "_TEXT_RANDOM_ID_CARD",
    "_TEXT_RANDOM_ID_CARD_TOKEN",
    "_TEXT_RANDOM_INTEGER",
    "_TEXT_RANDOM_MOBILE",
    "_TEXT_RANDOM_MOBILE_TOKEN",
    "_TEXT_RANDOM_NAME",
    "_TEXT_RANDOM_NAME_TOKEN",
    "_TEXT_RANDOM_NONE",
    "_apply_ai_label_state_style",
]
