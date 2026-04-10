"""向导文本题配置区。"""
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, IndicatorPosition, LineEdit, PushButton, RadioButton, SwitchButton

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.config import QuestionEntry
from software.core.questions.utils import try_parse_random_int_range
from software.ui.helpers.fluent_tooltip import install_tooltip_filters

from .utils import _apply_label_color
from .wizard_sections_common import (
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NONE,
    _apply_ai_label_state_style,
)


class WizardSectionsTextMixin:
    if TYPE_CHECKING:
        _has_content: bool
        text_container_map: Dict[int, QWidget]
        text_add_btn_map: Dict[int, PushButton]
        text_random_mode_map: Dict[int, str]
        text_random_group_map: Dict[int, QButtonGroup]
        text_random_list_radio_map: Dict[int, RadioButton]
        text_random_name_check_map: Dict[int, RadioButton]
        text_random_mobile_check_map: Dict[int, RadioButton]
        text_random_id_card_check_map: Dict[int, RadioButton]
        text_random_integer_check_map: Dict[int, RadioButton]
        text_random_int_min_edit_map: Dict[int, LineEdit]
        text_random_int_max_edit_map: Dict[int, LineEdit]
        ai_check_map: Dict[int, SwitchButton]
        ai_label_map: Dict[int, BodyLabel]
        text_edit_map: Dict[int, Any]
        multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]]
        multi_text_blank_radio_groups: Dict[int, List[QButtonGroup]]
        multi_text_blank_ai_checkboxes: Dict[int, List[SwitchButton]]

        def _get_entry_info(self, idx: int) -> Dict[str, Any]: ...
        @staticmethod
        def _resolve_text_random_int_range(entry: QuestionEntry) -> Tuple[Optional[int], Optional[int]]: ...
        @staticmethod
        def _create_integer_range_edit(parent: QWidget, initial_value: Optional[int], placeholder: str) -> LineEdit: ...
        def _on_text_random_mode_toggled(self, idx: int, mode: str, checked: bool) -> None: ...
        def _on_entry_ai_toggled(self, idx: int, checked: bool) -> None: ...
        @staticmethod
        def _resolve_text_random_mode(entry: QuestionEntry) -> str: ...
        def _sync_text_section_state(self, idx: int) -> None: ...
        def _set_text_answer_enabled(self, idx: int, enabled: bool) -> None: ...
        def _on_multi_text_blank_ai_toggled(self, checkbox: Any, checked: bool, sync_func: Any) -> None: ...

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
