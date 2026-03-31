"""WizardSectionsMixin：各题型配置区 UI 构建方法，供 QuestionWizardDialog 通过多继承引入。"""
from html import escape
from typing import List, Dict, Any, Tuple, Optional, cast

from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, QEasingCurve, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QButtonGroup
from qfluentwidgets import (
    ScrollArea,
    BodyLabel,
    CardWidget,
    PushButton,
    LineEdit,
    RadioButton,
    SegmentedWidget,
    SwitchButton,
    IndicatorPosition,
    isDarkTheme,
)

from software.core.questions.utils import OPTION_FILL_AI_TOKEN, parse_random_int_token, try_parse_random_int_range
from software.ui.widgets.no_wheel import NoWheelSlider
from software.core.questions.config import QuestionEntry
from software.app.config import DEFAULT_FILL_TEXT
from software.ui.helpers.ai_fill import ensure_ai_ready
from software.ui.helpers.fluent_tooltip import install_tooltip_filter, install_tooltip_filters

from .utils import (
    _shorten_text,
    _apply_label_color,
    _bind_slider_input,
)
from .psycho_config import PSYCHO_SUPPORTED_TYPES, BIAS_PRESET_CHOICES, build_bias_weights

_TEXT_RANDOM_NONE = "none"
_TEXT_RANDOM_NAME = "name"
_TEXT_RANDOM_MOBILE = "mobile"
_TEXT_RANDOM_ID_CARD = "id_card"
_TEXT_RANDOM_INTEGER = "integer"
_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"
_TEXT_RANDOM_ID_CARD_TOKEN = "__RANDOM_ID_CARD__"


def _apply_ai_label_state_style(label: BodyLabel) -> None:
    """为 AI 标签补上明确的禁用态颜色，避免默认主题下发灰不明显。"""
    active_color = "#f5f5f5" if isDarkTheme() else "#202020"
    disabled_color = "#7f7f7f" if isDarkTheme() else "#9a9a9a"
    label.setStyleSheet(
        f"QLabel {{ color: {active_color}; }} QLabel:disabled {{ color: {disabled_color}; }}"
    )
class WizardSectionsMixin:
    """各题型配置区 UI 构建方法。依赖 QuestionWizardDialog 的 state dict。"""

    # ------- 以下属性/方法由主类（QuestionWizardDialog）提供 -------
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
    def _resolve_matrix_weights(self, entry: Any, rows: int, columns: int) -> List[List[float]]: ...
    def _resolve_slider_bounds(self, idx: int, entry: Any) -> Tuple[int, int]: ...

    @staticmethod
    def _compute_ratio_percentages(values: List[Any]) -> List[float]:
        cleaned: List[float] = []
        for value in values:
            try:
                cleaned.append(max(0.0, float(value)))
            except Exception:
                cleaned.append(0.0)
        count = len(cleaned)
        if count <= 0:
            return []
        total = sum(cleaned)
        if total <= 0:
            return [100.0 / count] * count
        return [(item / total) * 100.0 for item in cleaned]

    @staticmethod
    def _format_ratio_percent(value: float) -> str:
        rounded = round(float(value), 1)
        text = f"{rounded:.1f}"
        if text.endswith(".0"):
            text = text[:-2]
        return f"{text}%"

    @staticmethod
    def _pick_ratio_color(value: float) -> str:
        if value < 10:
            return "#d13438"
        if value < 20:
            return "#f7630c"
        if value < 50:
            return "#ffb900"
        return "#107c10"

    def _build_ratio_preview_text(self, option_names: List[str], percentages: List[float], prefix: str) -> str:
        if not percentages:
            return f"{prefix}暂无"
        normalized_names: List[str] = []
        for idx in range(len(percentages)):
            raw_name = str(option_names[idx] or "").strip() if idx < len(option_names) else ""
            normalized_names.append(escape(_shorten_text(raw_name or f"选项{idx + 1}", 14)))

        chunks: List[str] = []
        for idx in range(len(percentages)):
            percent_text = self._format_ratio_percent(percentages[idx])
            percent_color = self._pick_ratio_color(percentages[idx])
            colored_percent = f"<span style='color:{percent_color};'>{percent_text}</span>"
            chunks.append(f"{normalized_names[idx]} {colored_percent}")
        return f"{prefix}{'｜'.join(chunks)}"

    def _refresh_ratio_preview_label(
        self,
        label: BodyLabel,
        sliders: List[NoWheelSlider],
        option_names: List[str],
        prefix: str,
    ) -> None:
        percentages = self._compute_ratio_percentages([slider.value() for slider in sliders])
        label.setText(self._build_ratio_preview_text(option_names, percentages, prefix))
        label.setToolTip("这里显示的是目标占比，实际作答会受信效度和一致性约束影响而小幅波动。")
        install_tooltip_filter(label)

    @staticmethod
    def _create_integer_range_edit(parent: QWidget, initial_value: Optional[int], placeholder: str) -> LineEdit:
        edit = LineEdit(parent)
        edit.setFixedWidth(88)
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setPlaceholderText(placeholder)
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?\d*"), edit))
        if initial_value is not None:
            edit.setText(str(int(initial_value)))
        return edit

    @staticmethod
    def _resolve_text_random_int_range(entry: QuestionEntry) -> Tuple[Optional[int], Optional[int]]:
        raw_range = getattr(entry, "text_random_int_range", []) or []
        if raw_range:
            parsed = try_parse_random_int_range(raw_range)
            if parsed is not None:
                return parsed
        for raw in (entry.texts or []):
            parsed = parse_random_int_token(raw)
            if parsed is not None:
                return parsed
        return None, None

    @staticmethod
    def _normalize_fillable_option_indices(raw_indices: Any, option_count: int) -> List[int]:
        if not isinstance(raw_indices, list):
            return []
        total = max(0, int(option_count or 0))
        normalized: List[int] = []
        seen = set()
        for raw in raw_indices:
            try:
                index = int(raw)
            except Exception:
                continue
            if index < 0 or index >= total or index in seen:
                continue
            seen.add(index)
            normalized.append(index)
        return normalized

    @staticmethod
    def _resolve_option_fill_mode(raw_value: Any) -> Tuple[str, bool]:
        text = str(raw_value or "").strip()
        if not text:
            return _TEXT_RANDOM_NONE, False
        if text == OPTION_FILL_AI_TOKEN:
            return _TEXT_RANDOM_NONE, True
        if text == _TEXT_RANDOM_NAME_TOKEN:
            return _TEXT_RANDOM_NAME, False
        if text == _TEXT_RANDOM_MOBILE_TOKEN:
            return _TEXT_RANDOM_MOBILE, False
        if text == _TEXT_RANDOM_ID_CARD_TOKEN:
            return _TEXT_RANDOM_ID_CARD, False
        if parse_random_int_token(text) is not None:
            return _TEXT_RANDOM_INTEGER, False
        return _TEXT_RANDOM_NONE, False

    @staticmethod
    def _resolve_option_fill_int_range(raw_value: Any) -> Tuple[Optional[int], Optional[int]]:
        parsed = parse_random_int_token(raw_value)
        if parsed is None:
            return None, None
        return parsed

    def _sync_option_fill_state(self, state: Dict[str, Any]) -> None:
        mode_group = state.get("group")
        fill_edit = state.get("edit")
        ai_cb = state.get("ai_cb")
        ai_label = state.get("ai_label")
        range_min_edit = state.get("min_edit")
        range_max_edit = state.get("max_edit")
        radios = state.get("radios") or {}
        checked_id = mode_group.checkedId() if mode_group is not None else 0
        ai_enabled = bool(ai_cb.isChecked()) if ai_cb is not None else False

        for radio in radios.values():
            if radio is None:
                continue
            radio.setEnabled(not ai_enabled)
            radio.setToolTip("启用 AI 时，上方填写模式不可用" if ai_enabled else "")

        for edit in (range_min_edit, range_max_edit):
            if edit is None:
                continue
            edit.setEnabled((checked_id == 4) and not ai_enabled)

        if fill_edit is not None:
            fill_edit.setEnabled((checked_id == 0) and not ai_enabled)

        if ai_cb is not None:
            ai_cb.setEnabled(True)
            ai_cb.setToolTip("运行时命中该选项后会调用 AI 生成补充内容")
        if ai_label is not None:
            ai_label.setEnabled(True)
            ai_label.setToolTip("运行时命中该选项后会调用 AI 生成补充内容")

    def _on_option_fill_mode_toggled(self, state: Dict[str, Any], checked: bool) -> None:
        if not checked:
            return
        self._sync_option_fill_state(state)

    def _on_option_fill_ai_toggled(self, state: Dict[str, Any], checked: bool) -> None:
        ai_cb = state.get("ai_cb")
        if checked and not self._ensure_ai_checkbox_ready(ai_cb):
            self._sync_option_fill_state(state)
            return
        if checked:
            list_radio = state.get("radios", {}).get("list")
            if list_radio is not None:
                list_radio.setChecked(True)
        self._sync_option_fill_state(state)

    def _build_text_section(self, idx: int, entry: QuestionEntry, card: CardWidget, card_layout: QVBoxLayout) -> None:
        self._has_content = True

        # 检测是否为多项填空题
        is_multi_text = False
        blank_count = 1
        info_entry = self._get_entry_info(idx)
        text_input_count = info_entry.get("text_inputs", 0)
        is_multi_text_flag = info_entry.get("is_multi_text", False)
        if is_multi_text_flag or entry.question_type == "multi_text":
            is_multi_text = True
            blank_count = max(1, text_input_count)

        # 如果是多项填空题，使用矩阵式输入界面
        if is_multi_text:
            self._build_multi_text_matrix_input(idx, entry, card, card_layout, blank_count)
            return

        hint = BodyLabel("答案列表（随机选择一个填入）：", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

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
                _apply_label_color(num_lbl, "#888888", "#a6a6a6")
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

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = PushButton("+ 添加答案", card)
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(lambda checked=False, f=add_row_func: f(""))
        btn_row.addWidget(add_btn)
        self.text_container_map[idx] = text_rows_container
        self.text_add_btn_map[idx] = add_btn

        if entry.question_type == "text":
            random_row = QHBoxLayout()
            random_row.setSpacing(8)
            random_hint = BodyLabel("随机处理：", card)
            random_hint.setStyleSheet("font-size: 12px;")
            _apply_label_color(random_hint, "#666666", "#bfbfbf")
            random_row.addWidget(random_hint)

            random_list_radio = RadioButton("使用答案列表", card)
            random_name_cb = RadioButton("随机姓名", card)
            random_mobile_cb = RadioButton("随机手机号", card)
            random_id_card_cb = RadioButton("随机身份证号", card)
            random_integer_cb = RadioButton("随机整数", card)
            random_int_min, random_int_max = self._resolve_text_random_int_range(entry)
            random_min_edit = self._create_integer_range_edit(card, random_int_min, "最小值")
            random_max_edit = self._create_integer_range_edit(card, random_int_max, "最大值")
            range_separator = BodyLabel("到", card)
            range_separator.setStyleSheet("font-size: 12px;")
            _apply_label_color(range_separator, "#666666", "#bfbfbf")
            random_row.addWidget(random_list_radio)
            random_row.addWidget(random_name_cb)
            random_row.addWidget(random_mobile_cb)
            random_row.addWidget(random_id_card_cb)
            random_row.addWidget(random_integer_cb)
            random_row.addWidget(random_min_edit)
            random_row.addWidget(range_separator)
            random_row.addWidget(random_max_edit)
            random_row.addStretch(1)
            card_layout.addLayout(random_row)

            random_group = QButtonGroup(card)
            random_group.setExclusive(True)
            random_group.addButton(random_list_radio, 0)
            random_group.addButton(random_name_cb, 1)
            random_group.addButton(random_mobile_cb, 2)
            random_group.addButton(random_id_card_cb, 3)
            random_group.addButton(random_integer_cb, 4)
            self.text_random_group_map[idx] = random_group
            self.text_random_list_radio_map[idx] = random_list_radio
            self.text_random_name_check_map[idx] = random_name_cb
            self.text_random_mobile_check_map[idx] = random_mobile_cb
            self.text_random_id_card_check_map[idx] = random_id_card_cb
            self.text_random_integer_check_map[idx] = random_integer_cb
            self.text_random_int_min_edit_map[idx] = random_min_edit
            self.text_random_int_max_edit_map[idx] = random_max_edit

            random_list_radio.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_NONE, checked)
            )
            random_name_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_NAME, checked)
            )
            random_mobile_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_MOBILE, checked)
            )
            random_id_card_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_ID_CARD, checked)
            )
            random_integer_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_INTEGER, checked)
            )

            ai_cb = SwitchButton(card, IndicatorPosition.RIGHT)
            ai_cb.setOnText("")
            ai_cb.setOffText("")
            ai_label = BodyLabel("启用 AI", card)
            _apply_ai_label_state_style(ai_label)
            ai_cb.setToolTip("运行时每次填空都会调用 AI")
            ai_label.setToolTip("运行时每次填空都会调用 AI")
            install_tooltip_filters(
                (
                    random_list_radio,
                    random_name_cb,
                    random_mobile_cb,
                    random_id_card_cb,
                    random_integer_cb,
                    ai_cb,
                    ai_label,
                )
            )
            ai_cb.setChecked(bool(getattr(entry, "ai_enabled", False)))
            ai_cb.checkedChanged.connect(lambda checked, i=idx: self._on_entry_ai_toggled(i, checked))
            btn_row.addWidget(ai_cb)
            btn_row.addWidget(ai_label)
            self.ai_check_map[idx] = ai_cb
            self.ai_label_map[idx] = ai_label

            random_mode = self._resolve_text_random_mode(entry)
            self.text_random_mode_map[idx] = random_mode
            if random_mode == _TEXT_RANDOM_NAME:
                random_name_cb.setChecked(True)
            elif random_mode == _TEXT_RANDOM_MOBILE:
                random_mobile_cb.setChecked(True)
            elif random_mode == _TEXT_RANDOM_ID_CARD:
                random_id_card_cb.setChecked(True)
            elif random_mode == _TEXT_RANDOM_INTEGER:
                random_integer_cb.setChecked(True)
            else:
                random_list_radio.setChecked(True)
            self._sync_text_section_state(idx)
        else:
            self._set_text_answer_enabled(idx, True)

        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)
        self.text_edit_map[idx] = edits

    def _build_multi_text_matrix_input(
        self, idx: int, entry: QuestionEntry, card: CardWidget,
        card_layout: QVBoxLayout, blank_count: int
    ) -> None:
        """为多项填空题构建矩阵式输入界面"""
        from software.core.questions.text_shared import MULTI_TEXT_DELIMITER

        # 提示标签
        hint = BodyLabel(f"答案列表（随机选择一组填入，共 {blank_count} 个填空）：", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        # 表头
        header_widget = QWidget(card)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 4, 0, 4)
        header_layout.setSpacing(8)

        num_spacer = QWidget(card)
        num_spacer.setFixedWidth(24)
        header_layout.addWidget(num_spacer)

        for i in range(blank_count):
            col_label = BodyLabel(f"填空{i+1}", card)
            col_label.setStyleSheet("font-size: 11px; font-weight: bold;")
            _apply_label_color(col_label, "#888888", "#a6a6a6")
            header_layout.addWidget(col_label, 1)

        del_spacer = QWidget(card)
        del_spacer.setFixedWidth(32)
        header_layout.addWidget(del_spacer)

        card_layout.addWidget(header_widget)

        # 答案行容器
        rows_container = QWidget(card)
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(4)
        card_layout.addWidget(rows_container)

        row_edits: List[List[LineEdit]] = []

        texts = list(entry.texts or [DEFAULT_FILL_TEXT])

        def make_add_row_func(container_layout, row_edit_list, parent_card, num_blanks):
            def add_row(initial_values: Optional[List[str]] = None):
                values: List[str] = initial_values if initial_values is not None else [""] * num_blanks

                row_widget = QWidget(parent_card)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 2, 0, 2)
                row_layout.setSpacing(8)

                num_lbl = BodyLabel(f"{len(row_edit_list) + 1}.", parent_card)
                num_lbl.setFixedWidth(24)
                num_lbl.setStyleSheet("font-size: 12px;")
                _apply_label_color(num_lbl, "#888888", "#a6a6a6")
                row_layout.addWidget(num_lbl)

                edits_in_row: List[LineEdit] = []
                for i in range(num_blanks):
                    edit = LineEdit(parent_card)
                    edit.setText(values[i] if i < len(values) else "")
                    edit.setPlaceholderText(f"填空{i+1}")
                    row_layout.addWidget(edit, 1)
                    edits_in_row.append(edit)

                del_btn = PushButton("×", parent_card)
                del_btn.setFixedWidth(32)
                row_layout.addWidget(del_btn)

                container_layout.addWidget(row_widget)
                row_edit_list.append(edits_in_row)

                def remove_row():
                    if len(row_edit_list) > 1:
                        row_edit_list.remove(edits_in_row)
                        row_widget.deleteLater()

                del_btn.clicked.connect(remove_row)

            return add_row

        add_row_func = make_add_row_func(rows_layout, row_edits, card, blank_count)

        for text in texts:
            parts = text.split(MULTI_TEXT_DELIMITER) if MULTI_TEXT_DELIMITER in text else [text]
            while len(parts) < blank_count:
                parts.append("")
            parts = parts[:blank_count]
            add_row_func(parts)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = PushButton("+ 添加答案组", card)
        add_btn.setFixedWidth(120)
        add_btn.clicked.connect(lambda checked=False, f=add_row_func: f(None))
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)

        self.text_edit_map[idx] = row_edits
        self.text_container_map[idx] = rows_container
        self.text_add_btn_map[idx] = add_btn

        # 填空项配置区域
        from PySide6.QtWidgets import QRadioButton
        config_hint = BodyLabel("填空项配置：", card)
        config_hint.setStyleSheet("font-size: 12px; margin-top: 8px;")
        _apply_label_color(config_hint, "#666666", "#bfbfbf")
        card_layout.addWidget(config_hint)

        # 存储每个填空项的单选按钮组和AI复选框
        blank_radio_groups: List[QButtonGroup] = []
        blank_mode_radios: List[Dict[str, QRadioButton]] = []
        blank_ai_checkboxes: List[SwitchButton] = []
        blank_integer_range_edits: List[Tuple[LineEdit, LineEdit]] = []

        # 解析现有配置
        saved_modes = getattr(entry, "multi_text_blank_modes", None) or []
        if not isinstance(saved_modes, list):
            saved_modes = []
        while len(saved_modes) < blank_count:
            saved_modes.append(_TEXT_RANDOM_NONE)

        saved_ai_flags = getattr(entry, "multi_text_blank_ai_flags", None) or []
        if not isinstance(saved_ai_flags, list):
            saved_ai_flags = []
        while len(saved_ai_flags) < blank_count:
            saved_ai_flags.append(False)

        saved_int_ranges = getattr(entry, "multi_text_blank_int_ranges", None) or []
        if not isinstance(saved_int_ranges, list):
            saved_int_ranges = []
        while len(saved_int_ranges) < blank_count:
            saved_int_ranges.append([])

        for blank_idx in range(blank_count):
            blank_row = QHBoxLayout()
            blank_row.setSpacing(8)
            blank_label = BodyLabel(f"填空{blank_idx + 1}:", card)
            blank_label.setFixedWidth(60)
            blank_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(blank_label, "#666666", "#bfbfbf")
            blank_row.addWidget(blank_label)

            radio_group = QButtonGroup(card)
            radio_group.setExclusive(True)

            radio_list = QRadioButton("使用答案列表", card)
            radio_name = QRadioButton("随机姓名", card)
            radio_mobile = QRadioButton("随机手机号", card)
            radio_id_card = QRadioButton("随机身份证号", card)
            radio_integer = QRadioButton("随机整数", card)
            parsed_range = try_parse_random_int_range(saved_int_ranges[blank_idx])
            range_min, range_max = parsed_range if parsed_range is not None else (None, None)
            range_min_edit = self._create_integer_range_edit(card, range_min, "最小值")
            range_max_edit = self._create_integer_range_edit(card, range_max, "最大值")
            range_sep_label = BodyLabel("到", card)
            range_sep_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(range_sep_label, "#666666", "#bfbfbf")

            radio_group.addButton(radio_list, 0)
            radio_group.addButton(radio_name, 1)
            radio_group.addButton(radio_mobile, 2)
            radio_group.addButton(radio_id_card, 3)
            radio_group.addButton(radio_integer, 4)

            current_mode = saved_modes[blank_idx] if blank_idx < len(saved_modes) else _TEXT_RANDOM_NONE
            if current_mode == _TEXT_RANDOM_NAME:
                radio_name.setChecked(True)
            elif current_mode == _TEXT_RANDOM_MOBILE:
                radio_mobile.setChecked(True)
            elif current_mode == _TEXT_RANDOM_ID_CARD:
                radio_id_card.setChecked(True)
            elif current_mode == _TEXT_RANDOM_INTEGER:
                radio_integer.setChecked(True)
            else:
                radio_list.setChecked(True)

            blank_row.addWidget(radio_list)
            blank_row.addWidget(radio_name)
            blank_row.addWidget(radio_mobile)
            blank_row.addWidget(radio_id_card)
            blank_row.addWidget(radio_integer)
            blank_row.addWidget(range_min_edit)
            blank_row.addWidget(range_sep_label)
            blank_row.addWidget(range_max_edit)

            # 每个填空项的AI复选框
            ai_cb = SwitchButton(card, IndicatorPosition.RIGHT)
            ai_cb.setOnText("")
            ai_cb.setOffText("")
            ai_label = BodyLabel("启用 AI", card)
            _apply_ai_label_state_style(ai_label)
            ai_cb.setToolTip("运行时每次填空都会调用 AI")
            ai_label.setToolTip("运行时每次填空都会调用 AI")
            install_tooltip_filters((ai_cb, ai_label))
            ai_cb.setChecked(saved_ai_flags[blank_idx] if blank_idx < len(saved_ai_flags) else False)
            blank_row.addWidget(ai_cb)
            blank_row.addWidget(ai_label)
            blank_ai_checkboxes.append(ai_cb)

            blank_row.addStretch(1)
            card_layout.addLayout(blank_row)

            blank_radio_groups.append(radio_group)
            blank_mode_radios.append({
                "list": radio_list,
                "name": radio_name,
                "mobile": radio_mobile,
                "id_card": radio_id_card,
                "integer": radio_integer,
            })
            blank_integer_range_edits.append((range_min_edit, range_max_edit))

            # 互斥逻辑：控制该列输入框的启用/禁用
            def make_sync_func(col_idx, radios, ai_checkbox, edits_list, int_range_edits):
                def sync_column_state():
                    mode_id = radios["list"].group().checkedId()
                    ai_enabled = ai_checkbox.isChecked()
                    use_list = (mode_id == 0 and not ai_enabled)
                    use_integer_range = (mode_id == 4 and not ai_enabled)

                    # 禁用/启用该列的所有输入框
                    for row in edits_list:
                        if col_idx < len(row):
                            row[col_idx].setEnabled(use_list)

                    for edit in int_range_edits:
                        edit.setEnabled(use_integer_range)

                    # AI和随机模式互斥
                    if ai_enabled:
                        radios["list"].setEnabled(False)
                        radios["name"].setEnabled(False)
                        radios["mobile"].setEnabled(False)
                        radios["id_card"].setEnabled(False)
                        radios["integer"].setEnabled(False)
                    else:
                        radios["list"].setEnabled(True)
                        radios["name"].setEnabled(True)
                        radios["mobile"].setEnabled(True)
                        radios["id_card"].setEnabled(True)
                        radios["integer"].setEnabled(True)

                return sync_column_state

            sync_func = make_sync_func(
                blank_idx,
                blank_mode_radios[-1],
                ai_cb,
                row_edits,
                blank_integer_range_edits[-1],
            )
            radio_group.buttonClicked.connect(lambda checked=False, f=sync_func: f())
            ai_cb.checkedChanged.connect(
                lambda checked, cb=ai_cb, f=sync_func: self._on_multi_text_blank_ai_toggled(cb, checked, f)
            )
            # 初始化状态
            sync_func()

        # 存储到映射
        if not hasattr(self, "multi_text_blank_radio_groups"):
            self.multi_text_blank_radio_groups = {}
        if not hasattr(self, "multi_text_blank_ai_checkboxes"):
            self.multi_text_blank_ai_checkboxes = {}
        if not hasattr(self, "multi_text_blank_integer_range_edits"):
            self.multi_text_blank_integer_range_edits = {}
        self.multi_text_blank_radio_groups[idx] = blank_radio_groups
        self.multi_text_blank_ai_checkboxes[idx] = blank_ai_checkboxes
        self.multi_text_blank_integer_range_edits[idx] = blank_integer_range_edits

        # 控制「添加答案组」按钮：所有填空都启用AI时禁用该按钮（答案列表无用）
        def update_add_btn_state():
            all_ai = all(blank_ai_checkboxes[i].isChecked() for i in range(blank_count))
            add_btn.setEnabled(not all_ai)

        for _ai_cb in blank_ai_checkboxes:
            _ai_cb.checkedChanged.connect(lambda _checked, f=update_add_btn_state: f())

        # 初始化按钮状态
        update_add_btn_state()

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
                text_label = BodyLabel(_shorten_text(opt_text, 50), parent_widget)
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
                        anim = QPropertyAnimation(sl, b"value", sl)
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
                item = BodyLabel(f"{opt_idx}. {_shorten_text(opt_text, 60)}", card)
                item.setStyleSheet("font-size: 12px;")
                _apply_label_color(item, "#666666", "#c8c8c8")
                list_layout.addWidget(item)
            card_layout.addWidget(list_container)

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

    def _set_text_answer_enabled(self, idx: int, enabled: bool) -> None:
        container = self.text_container_map.get(idx)
        if container:
            container.setEnabled(enabled)
        add_btn = self.text_add_btn_map.get(idx)
        if add_btn:
            add_btn.setEnabled(enabled)

    @staticmethod
    def _resolve_text_random_mode(entry: QuestionEntry) -> str:
        mode = str(getattr(entry, "text_random_mode", _TEXT_RANDOM_NONE) or _TEXT_RANDOM_NONE).strip().lower()
        if mode in (_TEXT_RANDOM_NAME, _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_ID_CARD, _TEXT_RANDOM_INTEGER):
            return mode
        for raw in (entry.texts or []):
            token = str(raw or "").strip()
            if token == _TEXT_RANDOM_NAME_TOKEN:
                return _TEXT_RANDOM_NAME
            if token == _TEXT_RANDOM_MOBILE_TOKEN:
                return _TEXT_RANDOM_MOBILE
            if token == _TEXT_RANDOM_ID_CARD_TOKEN:
                return _TEXT_RANDOM_ID_CARD
            if parse_random_int_token(token) is not None:
                return _TEXT_RANDOM_INTEGER
        return _TEXT_RANDOM_NONE

    def _sync_text_section_state(self, idx: int) -> None:
        random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        ai_cb = self.ai_check_map.get(idx)
        ai_label = self.ai_label_map.get(idx)
        random_list_radio = self.text_random_list_radio_map.get(idx)
        random_name_cb = self.text_random_name_check_map.get(idx)
        random_mobile_cb = self.text_random_mobile_check_map.get(idx)
        random_id_card_cb = self.text_random_id_card_check_map.get(idx)
        random_integer_cb = self.text_random_integer_check_map.get(idx)
        random_min_edit = self.text_random_int_min_edit_map.get(idx)
        random_max_edit = self.text_random_int_max_edit_map.get(idx)

        def _set_random_controls_enabled(enabled: bool, tooltip: str = "") -> None:
            for cb in (random_list_radio, random_name_cb, random_mobile_cb, random_id_card_cb, random_integer_cb):
                if cb is None:
                    continue
                cb.setEnabled(enabled)
                cb.setToolTip(tooltip)

        def _set_integer_range_enabled(enabled: bool) -> None:
            for edit in (random_min_edit, random_max_edit):
                if edit is None:
                    continue
                edit.setEnabled(enabled)

        if random_mode != _TEXT_RANDOM_NONE:
            _set_random_controls_enabled(True)
            _set_integer_range_enabled(random_mode == _TEXT_RANDOM_INTEGER)
            if ai_cb:
                ai_cb.setToolTip("运行时每次填空都会调用 AI")
                ai_cb.setEnabled(True)
            if ai_label:
                ai_label.setToolTip("运行时每次填空都会调用 AI")
                ai_label.setEnabled(True)
            self._set_text_answer_enabled(idx, False)
            return
        if ai_cb:
            ai_cb.setToolTip("运行时每次填空都会调用 AI")
            ai_cb.setEnabled(True)
            if ai_label:
                ai_label.setToolTip("运行时每次填空都会调用 AI")
                ai_label.setEnabled(True)
            if ai_cb.isChecked():
                _set_random_controls_enabled(False, "启用 AI 时，上方随机处理不可用")
                _set_integer_range_enabled(False)
            else:
                _set_random_controls_enabled(True)
                _set_integer_range_enabled(False)
            self._set_text_answer_enabled(idx, not ai_cb.isChecked())
            return
        if ai_label:
            ai_label.setToolTip("运行时每次填空都会调用 AI")
            ai_label.setEnabled(True)
        _set_random_controls_enabled(True)
        _set_integer_range_enabled(False)
        self._set_text_answer_enabled(idx, True)

    def _on_text_random_mode_toggled(self, idx: int, mode: str, checked: bool) -> None:
        if checked:
            self.text_random_mode_map[idx] = mode
        self._sync_text_section_state(idx)

    def _on_entry_ai_toggled(self, idx: int, checked: bool) -> None:
        random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        if checked and not self._ensure_ai_checkbox_ready(self.ai_check_map.get(idx)):
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.setEnabled(True)
            self._set_text_answer_enabled(idx, True)
            self._sync_text_section_state(idx)
            return
        if checked and random_mode != _TEXT_RANDOM_NONE:
            list_radio = self.text_random_list_radio_map.get(idx)
            self.text_random_mode_map[idx] = _TEXT_RANDOM_NONE
            if list_radio is not None:
                list_radio.setChecked(True)
        self._sync_text_section_state(idx)

    def _ensure_ai_checkbox_ready(self, checkbox: Any) -> bool:
        if checkbox is None:
            return False
        if ensure_ai_ready(cast(QWidget, self).window() or cast(QWidget, self)):
            return True
        checkbox.blockSignals(True)
        checkbox.setChecked(False)
        checkbox.blockSignals(False)
        return False

    def _on_multi_text_blank_ai_toggled(self, checkbox: Any, checked: bool, sync_func: Any) -> None:
        if checked and not self._ensure_ai_checkbox_ready(checkbox):
            sync_func()
            return
        sync_func()

