"""题目配置向导卡片与校验。"""

import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSizePolicy, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    HorizontalSeparator,
    InfoBadge,
    LineEdit,
    MessageBox,
    SubtitleLabel,
)

from software.core.questions.config import QuestionEntry
from software.providers.contracts import (
    SurveyQuestionMeta,
    ensure_survey_question_meta,
)
from software.ui.widgets.no_wheel import NoWheelSlider

from .constants import (
    ANSWER_WEIGHT_MIN,
    MULTIPLE_OPTION_WEIGHT_MAX,
    SLIDER_TARGET_MAX,
    _get_entry_type_label,
)
from .question_media_preview import QuestionMediaStrip
from .utils import _apply_label_color, _shorten_text, resolve_display_question_num
from .wizard_validation import (
    validate_before_accept,
    validate_non_zero_weights,
    validate_random_integer_inputs,
)


class WizardCardsMixin:
    if TYPE_CHECKING:
        info: List[SurveyQuestionMeta]
        entries: List[QuestionEntry]
        slider_map: Dict[int, List[NoWheelSlider]]
        matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]]
        text_random_mode_map: Dict[int, str]
        text_random_int_min_edit_map: Dict[int, LineEdit]
        text_random_int_max_edit_map: Dict[int, LineEdit]
        multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]]
        option_fill_state_map: Dict[int, Dict[int, Dict[str, Any]]]
        attached_select_slider_map: Dict[int, List[Dict[str, Any]]]
        bias_preset_map: Dict[int, Any]
        _entry_snapshots: List[QuestionEntry]
        _logic_tree_state: Any

        def _navigate_to_question(self, question_idx: int, animate: bool = False) -> None: ...
        def get_multi_text_blank_modes(self) -> Dict[int, List[str]]: ...
        def _refresh_ratio_preview_label(
            self,
            label: BodyLabel,
            sliders: List[NoWheelSlider],
            option_names: List[str],
            prefix: str,
        ) -> None: ...
        def _build_text_section(
            self,
            idx: int,
            entry: QuestionEntry,
            card: CardWidget,
            card_layout: QVBoxLayout,
        ) -> None: ...
        def _build_matrix_section(
            self,
            idx: int,
            entry: QuestionEntry,
            card: CardWidget,
            card_layout: QVBoxLayout,
            option_texts: List[str],
            row_texts: List[str],
        ) -> None: ...
        def _build_order_section(
            self,
            idx: int,
            card: CardWidget,
            card_layout: QVBoxLayout,
            option_texts: List[str],
        ) -> None: ...
        def _build_slider_section(
            self,
            idx: int,
            entry: QuestionEntry,
            card: CardWidget,
            card_layout: QVBoxLayout,
            option_texts: List[str],
        ) -> None: ...
        def _build_location_section(
            self,
            idx: int,
            entry: QuestionEntry,
            card: CardWidget,
            card_layout: QVBoxLayout,
        ) -> None: ...

    def _resolve_matrix_weights(
        self, entry: QuestionEntry, rows: int, columns: int
    ) -> List[List[float]]:
        """解析矩阵题的配比配置，返回按行的默认权重。"""

        def _clean_row(raw_row: Any) -> Optional[List[float]]:
            if not isinstance(raw_row, (list, tuple)):
                return None
            cleaned: List[float] = []
            for value in raw_row:
                try:
                    cleaned.append(max(0.0, float(value)))
                except Exception:
                    cleaned.append(0.0)
            if not cleaned:
                return None
            if len(cleaned) < columns:
                cleaned = cleaned + [1.0] * (columns - len(cleaned))
            elif len(cleaned) > columns:
                cleaned = cleaned[:columns]
            if all(v <= 0 for v in cleaned):
                cleaned = [1.0] * columns
            return cleaned

        raw = entry.custom_weights if entry.custom_weights else entry.probabilities
        if isinstance(raw, list) and any(isinstance(item, (list, tuple)) for item in raw):
            per_row: List[List[float]] = []
            last_row = None
            for idx in range(rows):
                row_raw = raw[idx] if idx < len(raw) else last_row
                row_values = _clean_row(row_raw)
                if row_values is None:
                    row_values = [1.0] * columns
                per_row.append(row_values)
                if row_raw is not None:
                    last_row = row_raw
            return per_row
        if isinstance(raw, list):
            uniform = _clean_row(raw)
            if uniform is None:
                uniform = [1.0] * columns
            return [list(uniform) for _ in range(rows)]
        return [[1.0] * columns for _ in range(rows)]

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _get_entry_info(self, idx: int) -> SurveyQuestionMeta:
        if 0 <= idx < len(self.info):
            info = self.info[idx]
            if isinstance(info, SurveyQuestionMeta):
                return info
        return ensure_survey_question_meta({}, index=idx + 1)

    def _format_question_label(self, idx: int) -> str:
        info = self._get_entry_info(idx)
        qnum = resolve_display_question_num(info, idx + 1)
        return f"第{qnum or idx + 1}题"

    def _format_compact_question_label(self, idx: int) -> str:
        info = self._get_entry_info(idx)
        qnum = resolve_display_question_num(info, idx + 1)
        return f"{qnum or idx + 1}."

    def _media_items_for(
        self, idx: int, scope: str, index: int | None = None
    ) -> List[Dict[str, Any]]:
        info = self._get_entry_info(idx)
        items: List[Dict[str, Any]] = []
        for item in list(info.question_media or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("scope") or "").strip().lower() != scope:
                continue
            if scope == "title":
                items.append(dict(item))
                continue
            raw_index = item.get("index")
            if raw_index is None:
                continue
            try:
                item_index = int(raw_index)
            except Exception:
                continue
            if item_index == index:
                items.append(dict(item))
        return items

    def _display_text_for_option(self, idx: int, option_index: int, raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if text:
            return text
        if self._media_items_for(idx, "option", option_index):
            return f"选项 {option_index + 1}"
        return "选项"

    def _display_text_for_row(self, idx: int, row_index: int, raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if text:
            return text
        if self._media_items_for(idx, "row", row_index):
            return f"第 {row_index + 1} 行"
        return f"第 {row_index + 1} 行"

    def _inbound_summary_for(self, idx: int) -> str:
        state = getattr(self, "_logic_tree_state", None)
        if state is None:
            return "始终显示"
        return str(state.inbound_summary.get(idx) or "始终显示")

    def _outbound_summary_for(self, idx: int) -> str:
        state = getattr(self, "_logic_tree_state", None)
        if state is None:
            return "无"
        return str(state.outbound_summary.get(idx) or "无")

    @staticmethod
    def _make_badge(text: str, light: str, dark: str, parent: QWidget) -> InfoBadge:
        return InfoBadge.custom(text, QColor(light), QColor(dark), parent=parent)

    def _build_header_badges(
        self,
        idx: int,
        entry: QuestionEntry,
        info_entry: SurveyQuestionMeta,
        parent: QWidget,
    ) -> List[InfoBadge]:
        badges: List[InfoBadge] = [
            self._make_badge(_get_entry_type_label(entry), "#0f6cbd", "#63b3ff", parent)
        ]
        badges.append(
            self._make_badge("必答" if bool(info_entry.required) else "非必答", "#8a3ffc", "#c7a8ff", parent)
        )

        media_items = list(info_entry.question_media or [])
        has_option_media = any(
            isinstance(item, dict) and str(item.get("scope") or "").strip().lower() == "option"
            for item in media_items
        )
        has_row_media = any(
            isinstance(item, dict) and str(item.get("scope") or "").strip().lower() == "row"
            for item in media_items
        )
        if self._media_items_for(idx, "title") or has_option_media or has_row_media:
            badges.append(self._make_badge("图片题", "#0f766e", "#4fd1c5", parent))
        if bool(info_entry.has_display_condition):
            badges.append(self._make_badge("条件显示", "#166534", "#4ade80", parent))
        if bool(info_entry.has_dependent_display_logic):
            badges.append(self._make_badge("控制后续", "#0f766e", "#67e8f9", parent))
        if bool(info_entry.has_jump):
            badges.append(self._make_badge("跳题", "#b45309", "#fbbf24", parent))
        return badges

    def _show_validation_error(
        self, message: str, idx: int, focus_widget: Optional[QWidget] = None
    ) -> None:
        self._navigate_to_question(idx, animate=False)
        box = MessageBox("保存失败", message, self)
        box.yesButton.setText("知道了")
        box.cancelButton.hide()
        self._validation_error_dialog = box
        box.finished.connect(self._clear_validation_error_dialog_ref)
        box.destroyed.connect(self._clear_validation_error_dialog_ref)
        if focus_widget is not None:
            box.finished.connect(self._restore_validation_focus)
            box.setProperty("_focus_widget_after_validation_error", focus_widget)
        box.open()

    def _clear_validation_error_dialog_ref(self, *_args) -> None:
        self._validation_error_dialog = None

    def _restore_validation_focus(self, *_args) -> None:
        dialog = cast(Any, self).sender()
        if dialog is None:
            return
        widget = dialog.property("_focus_widget_after_validation_error")
        if isinstance(widget, QWidget):
            QTimer.singleShot(0, widget.setFocus)

    def _validate_random_integer_inputs(self) -> bool:
        return validate_random_integer_inputs(self)

    def _validate_non_zero_weights(self) -> bool:
        return validate_non_zero_weights(self)

    def accept(self) -> None:
        if not validate_before_accept(self):
            return
        cast(Any, super()).accept()

    def _resolve_slider_bounds(self, idx: int, entry: QuestionEntry) -> tuple[int, int]:
        min_val = 0.0
        max_val = 10.0

        question_info = self._get_entry_info(idx)
        min_val = self._to_float(question_info.get("slider_min"), min_val)
        raw_max = question_info.get("slider_max")
        max_val = self._to_float(raw_max, float(SLIDER_TARGET_MAX) if raw_max is None else max_val)
        max_val = min(max_val, float(SLIDER_TARGET_MAX))

        if max_val <= min_val:
            max_val = min_val + 1.0

        if isinstance(entry.custom_weights, (list, tuple)) and entry.custom_weights:
            current = self._to_float(entry.custom_weights[0], min_val)
            max_val = max(max_val, min(current, float(SLIDER_TARGET_MAX)))

        min_int = int(round(min_val))
        max_int = int(round(max_val))
        if max_int <= min_int:
            max_int = min_int + 1
        return (min_int, max_int)

    def _build_entry_card(
        self,
        idx: int,
        entry: QuestionEntry,
        parent: QWidget,
    ) -> CardWidget:
        """构建单个题目的配置卡片。"""
        info_entry = self._get_entry_info(idx)
        qnum = str(resolve_display_question_num(info_entry, idx + 1) or "")
        title_text = str(info_entry.get("title") or "").strip()
        option_texts = [self._display_text_for_option(idx, i, str(text or "")) for i, text in enumerate(list(info_entry.get("option_texts") or []))]
        row_texts = [self._display_text_for_row(idx, i, str(text or "")) for i, text in enumerate(list(info_entry.get("row_texts") or []))]

        card = CardWidget(parent)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)
        card_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        header_badges = self._build_header_badges(idx, entry, info_entry, card)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title = SubtitleLabel(f"{qnum or idx + 1}.", card)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        title_row.addWidget(title)
        for badge in header_badges:
            title_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        title_row.addStretch(1)
        card_layout.addLayout(title_row)

        if title_text:
            desc = BodyLabel(title_text, card)
            desc.setWordWrap(True)
            desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            desc.setStyleSheet("font-size: 13px;")
            _apply_label_color(desc, "#444444", "#e0e0e0")
            card_layout.addWidget(desc)

        title_media = self._media_items_for(idx, "title")
        if title_media:
            card_layout.addWidget(QuestionMediaStrip("题干图片", title_media, fixed_size=72, parent=card))

        card_layout.addWidget(HorizontalSeparator(card))

        if bool(getattr(entry, "is_location", False)):
            self._build_location_section(idx, entry, card, card_layout)
        elif entry.question_type in ("text", "multi_text"):
            self._build_text_section(idx, entry, card, card_layout)
        elif entry.question_type == "matrix":
            self._build_matrix_section(idx, entry, card, card_layout, option_texts, row_texts)
        elif entry.question_type == "order":
            self._build_order_section(idx, card, card_layout, option_texts)
        else:
            self._build_slider_section(idx, entry, card, card_layout, option_texts)

        self._build_attached_select_section(idx, entry, card, card_layout)
        return card

    def _build_attached_select_section(
        self,
        idx: int,
        entry: QuestionEntry,
        card: CardWidget,
        card_layout: QVBoxLayout,
    ) -> None:
        raw_configs = getattr(entry, "attached_option_selects", None) or []
        if not isinstance(raw_configs, list) or not raw_configs:
            return

        stored_configs: List[Dict[str, Any]] = []
        separator = HorizontalSeparator(card)
        separator.setContentsMargins(0, 4, 0, 4)
        card_layout.addWidget(separator)

        section_title = BodyLabel("嵌入式下拉", card)
        section_title.setStyleSheet("font-size: 12px; font-weight: 600;")
        _apply_label_color(section_title, "#444444", "#e0e0e0")
        card_layout.addWidget(section_title)

        for item in raw_configs:
            if not isinstance(item, dict):
                continue
            select_options_raw = item.get("select_options")
            if not isinstance(select_options_raw, list):
                continue
            select_options = [
                str(opt or "").strip() for opt in select_options_raw if str(opt or "").strip()
            ]
            if not select_options:
                continue
            try:
                raw_option_index = item.get("option_index")
                if raw_option_index is None:
                    raise ValueError("option_index is missing")
                option_index = int(raw_option_index)
            except Exception:
                option_index = len(stored_configs)
            option_text = str(item.get("option_text") or "").strip() or f"第{option_index + 1}项"

            raw_weights = item.get("weights")
            weights: List[float] = []
            if isinstance(raw_weights, list) and raw_weights:
                for opt_idx in range(len(select_options)):
                    raw_weight = raw_weights[opt_idx] if opt_idx < len(raw_weights) else 0.0
                    try:
                        weights.append(max(0.0, float(raw_weight)))
                    except Exception:
                        weights.append(0.0)
            if len(weights) < len(select_options):
                weights.extend([1.0] * (len(select_options) - len(weights)))
            if not any(weight > 0 for weight in weights):
                weights = [1.0] * len(select_options)

            item_title = BodyLabel(f"命中“{_shorten_text(option_text, 40)}”", card)
            item_title.setWordWrap(True)
            item_title.setStyleSheet("font-size: 12px; margin-top: 4px;")
            _apply_label_color(item_title, "#0f6cbd", "#63b3ff")
            card_layout.addWidget(item_title)

            sliders: List[NoWheelSlider] = []
            for opt_idx, select_text in enumerate(select_options):
                row_widget = QWidget(card)
                row_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
                row_layout = QVBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 2)
                row_layout.setSpacing(2)
                row_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

                header_row = QHBoxLayout()
                header_row.setContentsMargins(0, 0, 0, 0)
                header_row.setSpacing(8)

                num_label = BodyLabel(f"{opt_idx + 1}.", card)
                num_label.setFixedWidth(24)
                num_label.setStyleSheet("font-size: 12px;")
                _apply_label_color(num_label, "#888888", "#a6a6a6")
                header_row.addWidget(num_label)

                text_label = BodyLabel(select_text, card)
                text_label.setWordWrap(True)
                text_label.setMinimumWidth(96)
                text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                text_label.setStyleSheet("font-size: 13px;")
                header_row.addWidget(text_label, 1)

                slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
                slider.setRange(ANSWER_WEIGHT_MIN, MULTIPLE_OPTION_WEIGHT_MAX)
                slider.setValue(
                    int(
                        min(
                            MULTIPLE_OPTION_WEIGHT_MAX,
                            max(ANSWER_WEIGHT_MIN, round(weights[opt_idx])),
                        )
                    )
                )

                header_row.addStretch(1)

                control_row = QHBoxLayout()
                control_row.setContentsMargins(18, 0, 0, 0)
                control_row.setSpacing(8)

                value_input = LineEdit(card)
                value_input.setFixedWidth(52)
                value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                value_input.setText(str(slider.value()))
                from .utils import _bind_slider_input

                _bind_slider_input(slider, value_input)

                slider.setMinimumWidth(48)
                slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                row_layout.addLayout(header_row)
                control_row.addWidget(slider, 1)
                control_row.addWidget(value_input)
                row_layout.addLayout(control_row)

                card_layout.addWidget(row_widget)
                sliders.append(slider)

            ratio_preview_label = BodyLabel("", card)
            ratio_preview_label.setWordWrap(True)
            ratio_preview_label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Maximum,
            )
            ratio_preview_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(ratio_preview_label, "#666666", "#bfbfbf")
            card_layout.addWidget(ratio_preview_label)

            def _update_option_preview(
                _value: int = 0,
                _label=ratio_preview_label,
                _sliders=sliders,
                _options=select_options,
            ):
                self._refresh_ratio_preview_label(
                    _label,
                    _sliders,
                    _options,
                    "下拉占比：",
                )

            for slider in sliders:
                slider.valueChanged.connect(_update_option_preview)
            _update_option_preview()

            stored_configs.append(
                {
                    "option_index": option_index,
                    "option_text": option_text,
                    "select_options": select_options,
                    "sliders": sliders,
                }
            )

        if stored_configs:
            self.attached_select_slider_map[idx] = stored_configs

    def _restore_entries(self) -> None:
        limit = min(len(self.entries), len(self._entry_snapshots))
        for idx in range(limit):
            snapshot = copy.deepcopy(self._entry_snapshots[idx])
            self.entries[idx].__dict__.update(snapshot.__dict__)
