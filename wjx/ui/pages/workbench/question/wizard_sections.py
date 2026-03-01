"""WizardSectionsMixin：各题型配置区 UI 构建方法，供 QuestionWizardDialog 通过多继承引入。"""
from typing import List, Dict, Any, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QButtonGroup
from qfluentwidgets import ScrollArea, BodyLabel, CardWidget, PushButton, LineEdit, CheckBox

from wjx.ui.widgets.no_wheel import NoWheelSlider
from wjx.core.questions.config import QuestionEntry
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.ui.helpers.ai_fill import ensure_ai_ready
from wjx.ui.pages.workbench.question.psycho_config import (
    PSYCHO_SUPPORTED_TYPES,
    build_psycho_config_row,
)

from .utils import _shorten_text, _apply_label_color, _bind_slider_input

_TEXT_RANDOM_NONE = "none"
_TEXT_RANDOM_NAME = "name"
_TEXT_RANDOM_MOBILE = "mobile"
_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"


class WizardSectionsMixin:
    """各题型配置区 UI 构建方法。依赖 QuestionWizardDialog 的 state dict。"""

    # ------- 以下属性/方法由主类（QuestionWizardDialog）提供 -------
    text_container_map: Dict[int, Any]
    text_add_btn_map: Dict[int, Any]
    text_random_group_map: Dict[int, Any]
    text_random_name_check_map: Dict[int, Any]
    text_random_mobile_check_map: Dict[int, Any]
    ai_check_map: Dict[int, Any]
    text_random_mode_map: Dict[int, str]
    text_edit_map: Dict[int, Any]
    info: List[Any]
    reliability_mode_enabled: bool
    matrix_row_slider_map: Dict[int, Any]
    matrix_reverse_check_map: Dict[int, Any]
    reverse_check_map: Dict[int, Any]
    entries: List[Any]
    slider_map: Dict[int, Any]
    psycho_check_map: Dict[int, Any]  # 潜变量模式复选框
    psycho_bias_map: Dict[int, Any]   # 潜变量偏向下拉框

    def _resolve_matrix_weights(self, entry: Any, rows: int, columns: int) -> List[List[float]]: ...
    def _resolve_slider_bounds(self, idx: int, entry: Any) -> Tuple[int, int]: ...

    def _build_text_section(self, idx: int, entry: QuestionEntry, card: CardWidget, card_layout: QVBoxLayout) -> None:
        self._has_content = True
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

            random_name_cb = CheckBox("随机姓名", card)
            random_mobile_cb = CheckBox("随机手机号", card)
            random_row.addWidget(random_name_cb)
            random_row.addWidget(random_mobile_cb)
            random_row.addStretch(1)
            card_layout.addLayout(random_row)

            random_group = QButtonGroup(card)
            random_group.setExclusive(False)
            random_group.addButton(random_name_cb, 1)
            random_group.addButton(random_mobile_cb, 2)
            self.text_random_group_map[idx] = random_group
            self.text_random_name_check_map[idx] = random_name_cb
            self.text_random_mobile_check_map[idx] = random_mobile_cb

            random_name_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_NAME, checked)
            )
            random_mobile_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_MOBILE, checked)
            )

            ai_cb = CheckBox("启用 AI", card)
            ai_cb.setToolTip("运行时每次填空都会调用 AI")
            ai_cb.setChecked(bool(getattr(entry, "ai_enabled", False)))
            ai_cb.toggled.connect(lambda checked, i=idx: self._on_entry_ai_toggled(i, checked))
            btn_row.addWidget(ai_cb)
            self.ai_check_map[idx] = ai_cb

            random_mode = self._resolve_text_random_mode(entry)
            self.text_random_mode_map[idx] = random_mode
            if random_mode == _TEXT_RANDOM_NAME:
                random_name_cb.setChecked(True)
            elif random_mode == _TEXT_RANDOM_MOBILE:
                random_mobile_cb.setChecked(True)
            self._sync_text_section_state(idx)
        else:
            self._set_text_answer_enabled(idx, True)

        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)
        self.text_edit_map[idx] = edits

    def _build_matrix_section(self, idx: int, entry: QuestionEntry, card: CardWidget,
                              card_layout: QVBoxLayout, option_texts: List[str], row_texts: List[str]) -> None:
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

        # 潜变量模式配置（矩阵题支持）
        if entry.question_type in PSYCHO_SUPPORTED_TYPES:
            psycho_row = build_psycho_config_row(
                card, entry, self.psycho_check_map, self.psycho_bias_map, idx
            )
            card_layout.addLayout(psycho_row)

        hint = BodyLabel("矩阵量表：每一行都需要单独设置配比", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

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

        saved_row_flags = list(getattr(entry, "row_reverse_flags", []) or [])
        if not saved_row_flags and getattr(entry, "is_reverse", False):
            saved_row_flags = [True] * rows

        per_row_sliders: List[List[NoWheelSlider]] = []
        per_row_values = matrix_weights if matrix_weights else [[1.0] * columns for _ in range(rows)]
        row_reverse_cbs: List[CheckBox] = []
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

            if self.reliability_mode_enabled:
                rev_row_layout = QHBoxLayout()
                rev_row_layout.setContentsMargins(0, 0, 0, 2)
                rev_cb = CheckBox("反向题请勾选此处", row_card)
                rev_cb.setToolTip("勾选后，该行的答题倾向会翻转（正向高分 → 反向低分）")
                row_is_rev = saved_row_flags[row_idx] if row_idx < len(saved_row_flags) else False
                rev_cb.setChecked(bool(row_is_rev))
                rev_row_layout.addWidget(rev_cb)
                rev_row_layout.addStretch(1)
                row_card_layout.addLayout(rev_row_layout)
                row_reverse_cbs.append(rev_cb)

            row_sliders = build_slider_rows(row_card, row_card_layout, per_row_values[row_idx])
            per_row_sliders.append(row_sliders)
            per_row_layout.addWidget(row_card)

        self.matrix_row_slider_map[idx] = per_row_sliders
        if self.reliability_mode_enabled and row_reverse_cbs:
            self.matrix_reverse_check_map[idx] = row_reverse_cbs

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

        # 潜变量模式配置（支持的题型）
        if entry.question_type in PSYCHO_SUPPORTED_TYPES:
            psycho_row = build_psycho_config_row(
                card, entry, self.psycho_check_map, self.psycho_bias_map, idx
            )
            card_layout.addLayout(psycho_row)

        if self.reliability_mode_enabled and entry.question_type in ("scale", "score"):
            rev_row = QHBoxLayout()
            rev_row.setContentsMargins(0, 2, 0, 2)
            rev_cb = CheckBox("反向题请勾选此处", card)
            rev_cb.setToolTip("勾选后，信效度一致性约束会翻转该题的基准偏好（正向高分 → 反向低分）")
            rev_cb.setChecked(bool(getattr(entry, "is_reverse", False)))
            rev_row.addWidget(rev_cb)
            rev_row.addStretch(1)
            card_layout.addLayout(rev_row)
            self.reverse_check_map[idx] = rev_cb

        options = max(1, int(entry.option_count or 1))
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
        if idx < len(self.info):
            for rule in (self.info[idx].get("jump_rules") or []):
                oi = rule.get("option_index")
                jt = rule.get("jumpto")
                if oi is not None and jt is not None:
                    jump_map[oi] = jt

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

            has_jump = bool(self.info[idx].get("has_jump")) if idx < len(self.info) else False
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

        self.slider_map[idx] = sliders

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
        if mode in (_TEXT_RANDOM_NAME, _TEXT_RANDOM_MOBILE):
            return mode
        for raw in (entry.texts or []):
            token = str(raw or "").strip()
            if token == _TEXT_RANDOM_NAME_TOKEN:
                return _TEXT_RANDOM_NAME
            if token == _TEXT_RANDOM_MOBILE_TOKEN:
                return _TEXT_RANDOM_MOBILE
        return _TEXT_RANDOM_NONE

    def _sync_text_section_state(self, idx: int) -> None:
        random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        ai_cb = self.ai_check_map.get(idx)
        if random_mode != _TEXT_RANDOM_NONE:
            if ai_cb:
                ai_cb.blockSignals(True)
                ai_cb.setChecked(False)
                ai_cb.blockSignals(False)
                ai_cb.setEnabled(False)
            self._set_text_answer_enabled(idx, False)
            return
        if ai_cb:
            ai_cb.setEnabled(True)
            self._set_text_answer_enabled(idx, not ai_cb.isChecked())
            return
        self._set_text_answer_enabled(idx, True)

    def _on_text_random_mode_toggled(self, idx: int, mode: str, checked: bool) -> None:
        if checked:
            name_cb = self.text_random_name_check_map.get(idx)
            mobile_cb = self.text_random_mobile_check_map.get(idx)
            if mode == _TEXT_RANDOM_NAME and mobile_cb and mobile_cb.isChecked():
                mobile_cb.blockSignals(True)
                mobile_cb.setChecked(False)
                mobile_cb.blockSignals(False)
            if mode == _TEXT_RANDOM_MOBILE and name_cb and name_cb.isChecked():
                name_cb.blockSignals(True)
                name_cb.setChecked(False)
                name_cb.blockSignals(False)
            self.text_random_mode_map[idx] = mode
        else:
            current_mode = _TEXT_RANDOM_NONE
            name_cb = self.text_random_name_check_map.get(idx)
            mobile_cb = self.text_random_mobile_check_map.get(idx)
            if name_cb and name_cb.isChecked():
                current_mode = _TEXT_RANDOM_NAME
            elif mobile_cb and mobile_cb.isChecked():
                current_mode = _TEXT_RANDOM_MOBILE
            self.text_random_mode_map[idx] = current_mode
        self._sync_text_section_state(idx)

    def _on_entry_ai_toggled(self, idx: int, checked: bool) -> None:
        random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        if random_mode != _TEXT_RANDOM_NONE:
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
                cb.setEnabled(False)
            self._set_text_answer_enabled(idx, False)
            return
        if checked and not ensure_ai_ready(self.window() or self):
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            self._set_text_answer_enabled(idx, True)
            return
        self._set_text_answer_enabled(idx, not checked)
