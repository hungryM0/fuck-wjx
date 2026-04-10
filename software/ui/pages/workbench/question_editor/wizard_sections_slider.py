"""向导滑块题配置区。"""
from typing import TYPE_CHECKING, Any, Dict, List

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, IndicatorPosition, LineEdit, RadioButton, SegmentedWidget, SwitchButton

from software.core.questions.config import QuestionEntry
from software.ui.helpers.fluent_tooltip import install_tooltip_filters
from software.ui.widgets.no_wheel import NoWheelSlider

from .psycho_config import BIAS_PRESET_CHOICES, PSYCHO_SUPPORTED_TYPES, build_bias_weights
from .utils import _apply_label_color, _bind_slider_input, _shorten_text
from .wizard_sections_common import (
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NONE,
    _apply_ai_label_state_style,
)


class WizardSectionsSliderMixin:
    if TYPE_CHECKING:
        _has_content: bool
        entries: List[QuestionEntry]
        bias_preset_map: Dict[int, Any]
        slider_map: Dict[int, List[NoWheelSlider]]
        option_fill_edit_map: Dict[int, Dict[int, LineEdit]]
        option_fill_state_map: Dict[int, Dict[int, Dict[str, Any]]]

        def _resolve_slider_bounds(self, idx: int, entry: QuestionEntry) -> tuple[int, int]: ...
        def _get_entry_info(self, idx: int) -> Dict[str, Any]: ...
        @staticmethod
        def _normalize_fillable_option_indices(raw_indices: Any, option_count: int) -> List[int]: ...
        @staticmethod
        def _resolve_option_fill_mode(raw_value: Any) -> tuple[str, bool]: ...
        @staticmethod
        def _resolve_option_fill_int_range(raw_value: Any) -> tuple[int | None, int | None]: ...
        @staticmethod
        def _create_integer_range_edit(parent: QWidget, initial_value: int | None, placeholder: str) -> LineEdit: ...
        def _on_option_fill_mode_toggled(self, state: Dict[str, Any], checked: bool) -> None: ...
        def _on_option_fill_ai_toggled(self, state: Dict[str, Any], checked: bool) -> None: ...
        def _sync_option_fill_state(self, state: Dict[str, Any]) -> None: ...
        def _refresh_ratio_preview_label(
            self,
            label: BodyLabel,
            sliders: List[NoWheelSlider],
            option_names: List[str],
            prefix: str,
        ) -> None: ...

    def _build_slider_section(self, idx: int, entry: QuestionEntry, card: CardWidget,
                              card_layout: QVBoxLayout, option_texts: List[str]) -> None:
        self._has_content = True
        slider_min, slider_max = (0, 100)
        if entry.question_type == "slider":
            slider_min, slider_max = self._resolve_slider_bounds(idx, entry)
        if entry.question_type == "slider":
            slider_hint = BodyLabel("滑块题：此处数值代表填写时的目标值（不是概率）", card)
            slider_hint.setWordWrap(True)
            slider_hint.setStyleSheet("font-size: 12px;")
            _apply_label_color(slider_hint, "#666666", "#bfbfbf")
            card_layout.addWidget(slider_hint)

        options = max(1, int(entry.option_count or 1))

        # 倾向预设选择器（仅支持的题型）
        _preset_seg = None
        if entry.question_type in PSYCHO_SUPPORTED_TYPES:
            preset_row = QHBoxLayout()
            preset_row.setSpacing(8)
            preset_label = BodyLabel("倾向预设：", card)
            preset_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(preset_label, "#666666", "#bfbfbf")
            preset_row.addWidget(preset_label)
            _preset_seg = SegmentedWidget(card)
            for value, text in BIAS_PRESET_CHOICES:
                _preset_seg.addItem(routeKey=value, text=text)
            current_bias = getattr(entry, "psycho_bias", "custom") or "custom"
            _preset_seg.setCurrentItem(current_bias)
            preset_row.addWidget(_preset_seg)
            preset_row.addStretch(1)
            card_layout.addLayout(preset_row)
            self.bias_preset_map[idx] = _preset_seg
        if entry.question_type == "multiple":
            default_weight = 50
        elif entry.question_type == "slider":
            default_weight = int(round((slider_min + slider_max) / 2))
        else:
            default_weight = 1
        raw_weights: Any = entry.custom_weights
        if not isinstance(raw_weights, (list, tuple)) or not raw_weights:
            if isinstance(entry.probabilities, (list, tuple)):
                raw_weights = entry.probabilities
            else:
                raw_weights = []
        weights = list(raw_weights or [])
        if len(weights) < options:
            weights += [default_weight] * (options - len(weights))
        if all(w <= 0 for w in weights):
            weights = [default_weight] * options

        sliders: List[NoWheelSlider] = []
        is_multiple = entry.question_type == "multiple"

        jump_map: Dict[int, int] = {}
        info_entry = self._get_entry_info(idx)
        fillable_option_indices = self._normalize_fillable_option_indices(info_entry.get("fillable_options"), options)
        if not fillable_option_indices:
            fillable_option_indices = self._normalize_fillable_option_indices(
                getattr(entry, "fillable_option_indices", None),
                options,
            )
        fillable_option_set = set(fillable_option_indices)
        saved_option_fill_texts = list(getattr(entry, "option_fill_texts", []) or [])
        option_fill_edits: Dict[int, LineEdit] = {}
        option_fill_states: Dict[int, Dict[str, Any]] = {}
        for rule in (info_entry.get("jump_rules") or []):
            oi = rule.get("option_index")
            jt = rule.get("jumpto")
            if oi is not None and jt is not None:
                jump_map[oi] = jt

        if fillable_option_indices:
            fill_hint = BodyLabel("命中带附加输入框的选项时，可以提交固定文本、随机值，或临时调用 AI 生成内容。", card)
            fill_hint.setWordWrap(True)
            fill_hint.setStyleSheet("font-size: 12px;")
            _apply_label_color(fill_hint, "#666666", "#bfbfbf")
            card_layout.addWidget(fill_hint)

        for opt_idx in range(options):
            opt_widget = QWidget(card)
            opt_layout = QHBoxLayout(opt_widget)
            opt_layout.setContentsMargins(0, 4, 0, 4)
            opt_layout.setSpacing(12)

            num_label = BodyLabel(f"{opt_idx + 1}.", card)
            num_label.setFixedWidth(24)
            num_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_label, "#888888", "#a6a6a6")
            opt_layout.addWidget(num_label)

            opt_text = option_texts[opt_idx] if opt_idx < len(option_texts) else "选项"
            text_label = BodyLabel(_shorten_text(opt_text, 50), card)
            text_label.setFixedWidth(160)
            text_label.setStyleSheet("font-size: 13px;")
            opt_layout.addWidget(text_label)

            has_jump = bool(info_entry.get("has_jump"))
            if has_jump:
                jump_container = QWidget(card)
                jump_container.setFixedWidth(90)
                jump_layout = QHBoxLayout(jump_container)
                jump_layout.setContentsMargins(0, 0, 0, 0)
                if opt_idx in jump_map:
                    jumpto = jump_map[opt_idx]
                    total_questions = len(self.entries)
                    if jumpto > total_questions:
                        jump_text = "➔ 提前结束"
                    else:
                        jump_text = f"➔ 跳至第{jumpto}题"
                    jump_label = BodyLabel(jump_text, jump_container)
                    jump_label.setStyleSheet("font-size: 11px; font-weight: 500;")
                    _apply_label_color(jump_label, "#d93025", "#ff6b6b")
                    jump_layout.addWidget(jump_label)
                jump_layout.addStretch(1)
                opt_layout.addWidget(jump_container)

            slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
            if entry.question_type == "slider":
                slider.setRange(slider_min, slider_max)
            else:
                slider.setRange(0, 100)
            slider.setValue(int(min(slider.maximum(), max(slider.minimum(), weights[opt_idx]))))
            slider.setMinimumWidth(200)
            opt_layout.addWidget(slider, 1)

            value_input = LineEdit(card)
            value_input.setFixedWidth(60)
            value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_input.setText(str(slider.value()))
            _bind_slider_input(slider, value_input)
            opt_layout.addWidget(value_input)
            if is_multiple:
                percent_label = BodyLabel("%", card)
                percent_label.setFixedWidth(12)
                percent_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                _apply_label_color(percent_label, "#666666", "#bfbfbf")
                opt_layout.addWidget(percent_label)

            card_layout.addWidget(opt_widget)
            sliders.append(slider)

            if opt_idx in fillable_option_set:
                raw_fill_value = saved_option_fill_texts[opt_idx] if opt_idx < len(saved_option_fill_texts) else None
                fill_mode, fill_ai_enabled = self._resolve_option_fill_mode(raw_fill_value)
                range_min, range_max = self._resolve_option_fill_int_range(raw_fill_value)

                fill_widget = QWidget(card)
                fill_layout = QHBoxLayout(fill_widget)
                fill_layout.setContentsMargins(36, 0, 0, 4)
                fill_layout.setSpacing(12)

                fill_label = BodyLabel("选中此项时填写：", card)
                fill_label.setFixedWidth(160)
                fill_label.setStyleSheet("font-size: 12px;")
                _apply_label_color(fill_label, "#666666", "#bfbfbf")
                fill_layout.addWidget(fill_label)

                fill_edit = LineEdit(card)
                existing_fill = ""
                if fill_mode == _TEXT_RANDOM_NONE and not fill_ai_enabled and opt_idx < len(saved_option_fill_texts):
                    existing_fill = str(saved_option_fill_texts[opt_idx] or "").strip()
                if existing_fill:
                    fill_edit.setText(existing_fill)
                if entry.question_type == "single":
                    fill_edit.setPlaceholderText("例如：无；留空时运行会自动按默认值处理")
                else:
                    fill_edit.setPlaceholderText("输入命中该选项时要填写的内容")
                fill_layout.addWidget(fill_edit, 1)

                card_layout.addWidget(fill_widget)
                option_fill_edits[opt_idx] = fill_edit

                fill_mode_widget = QWidget(card)
                fill_mode_layout = QVBoxLayout(fill_mode_widget)
                fill_mode_layout.setContentsMargins(36, 0, 0, 8)
                fill_mode_layout.setSpacing(6)

                mode_header_row = QHBoxLayout()
                mode_header_row.setSpacing(8)
                mode_label = BodyLabel("填写模式：", card)
                mode_label.setStyleSheet("font-size: 12px;")
                _apply_label_color(mode_label, "#666666", "#bfbfbf")
                mode_header_row.addWidget(mode_label)

                mode_group = QButtonGroup(card)
                mode_group.setExclusive(True)
                fill_list_radio = RadioButton("使用填写文本", card)
                fill_name_radio = RadioButton("随机姓名", card)
                fill_mobile_radio = RadioButton("随机手机号", card)
                fill_id_card_radio = RadioButton("随机身份证号", card)
                fill_integer_radio = RadioButton("随机整数", card)
                mode_group.addButton(fill_list_radio, 0)
                mode_group.addButton(fill_name_radio, 1)
                mode_group.addButton(fill_mobile_radio, 2)
                mode_group.addButton(fill_id_card_radio, 3)
                mode_group.addButton(fill_integer_radio, 4)

                range_min_edit = self._create_integer_range_edit(card, range_min, "最小值")
                range_max_edit = self._create_integer_range_edit(card, range_max, "最大值")
                range_sep_label = BodyLabel("到", card)
                range_sep_label.setStyleSheet("font-size: 12px;")
                _apply_label_color(range_sep_label, "#666666", "#bfbfbf")

                ai_cb = SwitchButton(card, IndicatorPosition.RIGHT)
                ai_cb.setOnText("")
                ai_cb.setOffText("")
                ai_label = BodyLabel("启用 AI", card)
                _apply_ai_label_state_style(ai_label)
                ai_cb.setToolTip("运行时命中该选项后会调用 AI 生成补充内容")
                ai_label.setToolTip("运行时命中该选项后会调用 AI 生成补充内容")
                ai_cb.setChecked(fill_ai_enabled)
                mode_header_row.addWidget(ai_cb)
                mode_header_row.addWidget(ai_label)
                mode_header_row.addStretch(1)
                fill_mode_layout.addLayout(mode_header_row)

                mode_row_top = QHBoxLayout()
                mode_row_top.setSpacing(8)
                mode_row_top.addWidget(fill_list_radio)
                mode_row_top.addWidget(fill_name_radio)
                mode_row_top.addWidget(fill_mobile_radio)
                mode_row_top.addStretch(1)
                fill_mode_layout.addLayout(mode_row_top)

                mode_row_bottom = QHBoxLayout()
                mode_row_bottom.setSpacing(8)
                mode_row_bottom.addWidget(fill_id_card_radio)
                mode_row_bottom.addWidget(fill_integer_radio)
                mode_row_bottom.addWidget(range_min_edit)
                mode_row_bottom.addWidget(range_sep_label)
                mode_row_bottom.addWidget(range_max_edit)
                mode_row_bottom.addStretch(1)
                fill_mode_layout.addLayout(mode_row_bottom)

                card_layout.addWidget(fill_mode_widget)

                if fill_mode == _TEXT_RANDOM_NAME:
                    fill_name_radio.setChecked(True)
                elif fill_mode == _TEXT_RANDOM_MOBILE:
                    fill_mobile_radio.setChecked(True)
                elif fill_mode == _TEXT_RANDOM_ID_CARD:
                    fill_id_card_radio.setChecked(True)
                elif fill_mode == _TEXT_RANDOM_INTEGER:
                    fill_integer_radio.setChecked(True)
                else:
                    fill_list_radio.setChecked(True)

                fill_state = {
                    "edit": fill_edit,
                    "group": mode_group,
                    "radios": {
                        "list": fill_list_radio,
                        "name": fill_name_radio,
                        "mobile": fill_mobile_radio,
                        "id_card": fill_id_card_radio,
                        "integer": fill_integer_radio,
                    },
                    "min_edit": range_min_edit,
                    "max_edit": range_max_edit,
                    "ai_cb": ai_cb,
                    "ai_label": ai_label,
                }
                option_fill_states[opt_idx] = fill_state
                install_tooltip_filters(
                    (
                        fill_list_radio,
                        fill_name_radio,
                        fill_mobile_radio,
                        fill_id_card_radio,
                        fill_integer_radio,
                        ai_cb,
                        ai_label,
                    )
                )
                for radio in fill_state["radios"].values():
                    radio.toggled.connect(
                        lambda checked, state=fill_state: self._on_option_fill_mode_toggled(state, checked)
                    )
                ai_cb.checkedChanged.connect(
                    lambda checked, state=fill_state: self._on_option_fill_ai_toggled(state, checked)
                )
                self._sync_option_fill_state(fill_state)

        self.slider_map[idx] = sliders
        if option_fill_edits:
            self.option_fill_edit_map[idx] = option_fill_edits
        if option_fill_states:
            self.option_fill_state_map[idx] = option_fill_states

        if entry.question_type in ("single", "dropdown", "scale", "score"):
            ratio_preview_label = BodyLabel("", card)
            ratio_preview_label.setWordWrap(True)
            ratio_preview_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(ratio_preview_label, "#666666", "#bfbfbf")
            card_layout.addWidget(ratio_preview_label)

            def _update_option_preview(_value: int = 0):
                self._refresh_ratio_preview_label(
                    ratio_preview_label,
                    sliders,
                    option_texts,
                    "目标占比（实际会小幅波动）：",
                )

            for slider in sliders:
                slider.valueChanged.connect(_update_option_preview)
            _update_option_preview()

        # 预设 ↔ 滑块联动（用标志位避免循环触发，不用 blockSignals 以保证输入框同步）
        if _preset_seg is not None:
            _applying_preset = [False]

            _slider_anims: Dict[object, QPropertyAnimation] = {}

            def _on_preset_changed(route_key: str, _sliders=sliders, _flag=_applying_preset, _sa=_slider_anims):
                if route_key == "custom":
                    return
                _flag[0] = True
                weights = build_bias_weights(len(_sliders), route_key)
                for si, sl in enumerate(_sliders):
                    old = _sa.get(sl)
                    if old:
                        old.stop()
                    target = int(weights[si]) if si < len(weights) else 1
                    anim = QPropertyAnimation(sl, b"value", sl)
                    anim.setDuration(300)
                    anim.setStartValue(sl.value())
                    anim.setEndValue(target)
                    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    anim.start()
                    _sa[sl] = anim
                QTimer.singleShot(320, lambda: _flag.__setitem__(0, False))
            _preset_seg.currentItemChanged.connect(_on_preset_changed)

            def _make_slider_cb(_seg=_preset_seg, _flag=_applying_preset):
                def _cb(value):
                    if _flag[0]:
                        return
                    if _seg.currentRouteKey() != "custom":
                        _seg.setCurrentItem("custom")
                return _cb
            _slider_cb = _make_slider_cb()
            for sl in sliders:
                sl.valueChanged.connect(_slider_cb)
