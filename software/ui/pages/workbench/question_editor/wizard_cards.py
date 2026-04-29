"""题目配置向导卡片与校验。"""
import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, LineEdit, MessageBox, SubtitleLabel

from software.core.questions.config import QuestionEntry
from software.core.questions.utils import try_parse_random_int_range
from software.providers.contracts import SurveyQuestionMeta, ensure_survey_question_meta
from software.ui.widgets.no_wheel import NoWheelSlider

from .constants import _get_entry_type_label
from .utils import _apply_label_color, _bind_slider_input, _configure_wrapped_text_label, _shorten_text


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

        def _navigate_to_question(self, question_idx: int, animate: bool) -> None: ...
        def get_multi_text_blank_modes(self) -> Dict[int, List[str]]: ...
        def _refresh_ratio_preview_label(
            self,
            label: BodyLabel,
            sliders: List[NoWheelSlider],
            option_names: List[str],
            prefix: str,
        ) -> None: ...
        def _build_text_section(self, idx: int, entry: QuestionEntry, card: CardWidget, card_layout: QVBoxLayout) -> None: ...
        def _build_matrix_section(
            self,
            idx: int,
            entry: QuestionEntry,
            card: CardWidget,
            card_layout: QVBoxLayout,
            option_texts: List[str],
            row_texts: List[str],
        ) -> None: ...
        def _build_order_section(self, card: CardWidget, card_layout: QVBoxLayout, option_texts: List[str]) -> None: ...
        def _build_slider_section(
            self,
            idx: int,
            entry: QuestionEntry,
            card: CardWidget,
            card_layout: QVBoxLayout,
            option_texts: List[str],
        ) -> None: ...
        def _register_question_card_interaction_targets(self, card: CardWidget, idx: int) -> None: ...

    def _resolve_matrix_weights(self, entry: QuestionEntry, rows: int, columns: int) -> List[List[float]]:
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
        qnum = str(info.get("num") or "").strip()
        return f"第{qnum or idx + 1}题"
    def _find_info_by_question_num(self, question_num: int) -> SurveyQuestionMeta:
        for info in self.info:
            if not isinstance(info, SurveyQuestionMeta):
                continue
            try:
                current_num = int(info.num or 0)
            except Exception:
                current_num = 0
            if current_num == question_num:
                return info
        return ensure_survey_question_meta({}, index=question_num)
    @staticmethod
    def _format_question_num_list(question_nums: List[int]) -> str:
        normalized: List[int] = []
        seen = set()
        for raw in question_nums:
            try:
                value = int(raw)
            except Exception:
                continue
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if not normalized:
            return "后续题目"
        normalized.sort()
        labels = [f"第{num}题" for num in normalized]
        if len(labels) <= 4:
            return "、".join(labels)
        return f"{'、'.join(labels[:4])} 等{len(labels)}题"
    def _format_condition_option_text(self, source_info: Dict[str, Any], option_indices: List[Any]) -> str:
        option_texts = list(source_info.get("option_texts") or [])
        normalized_labels: List[str] = []
        seen = set()
        for raw in option_indices:
            try:
                option_index = int(raw)
            except Exception:
                continue
            if option_index < 0 or option_index in seen:
                continue
            seen.add(option_index)
            if option_index < len(option_texts):
                option_text = str(option_texts[option_index] or "").strip()
                if option_text:
                    normalized_labels.append(f"“{_shorten_text(option_text, 18)}”")
                    continue
            normalized_labels.append(f"第{option_index + 1}项")
        if not normalized_labels:
            return "指定选项"
        if len(normalized_labels) == 1:
            return normalized_labels[0]
        if len(normalized_labels) <= 3:
            return "、".join(normalized_labels)
        return f"以下任一项：{'、'.join(normalized_labels[:4])}"
    def _build_display_condition_summary(self, info_entry: Dict[str, Any]) -> str:
        conditions = info_entry.get("display_conditions") or []
        if not isinstance(conditions, list) or not conditions:
            return ""
        segments: List[str] = []
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            try:
                source_question_num = int(condition.get("condition_question_num") or 0)
            except Exception:
                source_question_num = 0
            if source_question_num <= 0:
                continue
            source_info = self._find_info_by_question_num(source_question_num)
            option_text = self._format_condition_option_text(
                source_info,
                list(condition.get("condition_option_indices") or []),
            )
            segments.append(f"第{source_question_num}题选中{option_text}")
        if not segments:
            return "⚠️ 这题不是每份问卷都会出现，只有满足前面题目的条件时才会显示。"
        return f"⚠️ 这题不是每份问卷都会出现。仅在满足以下条件时显示：{'；'.join(segments)}。"
    def _build_dependent_display_summary(self, info_entry: Dict[str, Any]) -> str:
        targets = info_entry.get("controls_display_targets") or []
        if not isinstance(targets, list) or not targets:
            return ""
        grouped: Dict[Tuple[int, ...], List[int]] = {}
        for item in targets:
            if not isinstance(item, dict):
                continue
            try:
                target_question_num = int(item.get("target_question_num") or 0)
            except Exception:
                target_question_num = 0
            if target_question_num <= 0:
                continue
            key_parts: List[int] = []
            seen = set()
            for raw in list(item.get("condition_option_indices") or []):
                try:
                    option_index = int(raw)
                except Exception:
                    continue
                if option_index < 0 or option_index in seen:
                    continue
                seen.add(option_index)
                key_parts.append(option_index)
            if not key_parts:
                continue
            grouped.setdefault(tuple(key_parts), []).append(target_question_num)
        if not grouped:
            return "⚠️ 这题会控制后续题是否出现，选项配比会直接影响后续题的触达率。"
        segments: List[str] = []
        for option_indices, target_nums in sorted(grouped.items(), key=lambda item: item[0]):
            option_text = self._format_condition_option_text(info_entry, list(option_indices))
            target_text = self._format_question_num_list(target_nums)
            segments.append(f"选中{option_text}时显示{target_text}")
        return f"⚠️ 这题会控制后续题是否出现：{'；'.join(segments)}。"
    def _show_validation_error(self, message: str, idx: int, focus_widget: Optional[QWidget] = None) -> None:
        self._navigate_to_question(idx, animate=True)
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
        for idx, mode in self.text_random_mode_map.items():
            if str(mode or "").strip().lower() != "integer":
                continue
            min_edit = self.text_random_int_min_edit_map.get(idx)
            max_edit = self.text_random_int_max_edit_map.get(idx)
            raw_range = [
                min_edit.text().strip() if min_edit is not None else "",
                max_edit.text().strip() if max_edit is not None else "",
            ]
            if try_parse_random_int_range(raw_range) is None:
                self._show_validation_error(
                    f"{self._format_question_label(idx)}的随机整数范围未填写完整，请输入最小值和最大值。",
                    idx,
                    min_edit or max_edit,
                )
                return False

        for idx, modes in self.get_multi_text_blank_modes().items():
            range_edits = self.multi_text_blank_integer_range_edits.get(idx, [])
            for blank_idx, mode in enumerate(modes):
                if str(mode or "").strip().lower() != "integer":
                    continue
                min_edit = range_edits[blank_idx][0] if blank_idx < len(range_edits) else None
                max_edit = range_edits[blank_idx][1] if blank_idx < len(range_edits) else None
                raw_range = [
                    min_edit.text().strip() if min_edit is not None else "",
                    max_edit.text().strip() if max_edit is not None else "",
                ]
                if try_parse_random_int_range(raw_range) is None:
                    self._show_validation_error(
                        f"{self._format_question_label(idx)}的填空{blank_idx + 1}随机整数范围未填写完整，请输入最小值和最大值。",
                        idx,
                        min_edit or max_edit,
                    )
                    return False

        for idx, option_states in self.option_fill_state_map.items():
            for option_idx, state in option_states.items():
                ai_cb = state.get("ai_cb")
                if ai_cb is not None and ai_cb.isChecked():
                    continue
                group = state.get("group")
                if group is None or group.checkedId() != 4:
                    continue
                min_edit = state.get("min_edit")
                max_edit = state.get("max_edit")
                raw_range = [
                    min_edit.text().strip() if min_edit is not None else "",
                    max_edit.text().strip() if max_edit is not None else "",
                ]
                if try_parse_random_int_range(raw_range) is None:
                    self._show_validation_error(
                        f"{self._format_question_label(idx)}的第{option_idx + 1}个附加填空随机整数范围未填写完整，请输入最小值和最大值。",
                        idx,
                        min_edit or max_edit,
                    )
                    return False
        return True
    def _validate_non_zero_weights(self) -> bool:
        for idx, sliders in self.slider_map.items():
            weights = [max(0, slider.value()) for slider in sliders]
            if weights and not any(weight > 0 for weight in weights):
                self._show_validation_error(
                    f"{self._format_question_label(idx)}的选项配比不能全为0，请至少保留一个大于0的值。",
                    idx,
                    sliders[0],
                )
                return False

        for idx, row_sliders in self.matrix_row_slider_map.items():
            info = self._get_entry_info(idx)
            row_texts = info.get("row_texts")
            for row_idx, row in enumerate(row_sliders):
                weights = [max(0, slider.value()) for slider in row]
                if not weights or any(weight > 0 for weight in weights):
                    continue
                row_name = f"第{row_idx + 1}行"
                if isinstance(row_texts, list) and row_idx < len(row_texts):
                    row_text = str(row_texts[row_idx] or "").strip()
                    if row_text:
                        row_name = f"{row_name}（{_shorten_text(row_text, 24)}）"
                self._show_validation_error(
                    f"{self._format_question_label(idx)}的{row_name}配比不能全为0，请至少保留一个大于0的值。",
                    idx,
                    row[0],
                )
                return False

        for idx, config_items in self.attached_select_slider_map.items():
            for item in config_items:
                sliders = item.get("sliders") or []
                if not sliders:
                    continue
                weights = [max(0, slider.value()) for slider in sliders]
                if any(weight > 0 for weight in weights):
                    continue
                option_text = str(item.get("option_text") or "").strip()
                if not option_text:
                    option_text = f"第{int(item.get('option_index', 0)) + 1}项"
                self._show_validation_error(
                    f"{self._format_question_label(idx)}里“{_shorten_text(option_text, 28)}”对应的嵌入式下拉配比不能全为0，请至少保留一个大于0的值。",
                    idx,
                    sliders[0],
                )
                return False

        return True
    def accept(self) -> None:
        if not self._validate_random_integer_inputs():
            return
        if not self._validate_non_zero_weights():
            return
        cast(Any, super()).accept()
    def _resolve_slider_bounds(self, idx: int, entry: QuestionEntry) -> tuple[int, int]:
        min_val = 0.0
        max_val = 10.0

        question_info = self._get_entry_info(idx)
        min_val = self._to_float(question_info.get("slider_min"), min_val)
        raw_max = question_info.get("slider_max")
        max_val = self._to_float(raw_max, 100.0 if raw_max is None else max_val)

        if max_val <= min_val:
            max_val = min_val + 100.0

        if isinstance(entry.custom_weights, (list, tuple)) and entry.custom_weights:
            current = self._to_float(entry.custom_weights[0], min_val)
            max_val = max(max_val, current)

        min_int = int(round(min_val))
        max_int = int(round(max_val))
        if max_int <= min_int:
            max_int = min_int + 1
        return (min_int, max_int)
    def _build_entry_card(self, idx: int, entry: QuestionEntry, container: QWidget, inner: QVBoxLayout) -> CardWidget:
        """构建单个题目的配置卡片。"""
        # 获取题目信息
        info_entry = self._get_entry_info(idx)
        qnum = ""
        title_text = ""
        option_texts: List[str] = []
        row_texts: List[str] = []
        multi_min_limit: Optional[int] = None
        multi_max_limit: Optional[int] = None
        qnum = str(info_entry.get("num") or "")
        title_text = str(info_entry.get("title") or "")
        opt_raw = info_entry.get("option_texts")
        if isinstance(opt_raw, list):
            option_texts = [str(x) for x in opt_raw]
        row_raw = info_entry.get("row_texts")
        if isinstance(row_raw, list):
            row_texts = [str(x) for x in row_raw]
        # 获取多选题的选择数量限制
        if entry.question_type == "multiple":
            multi_min_limit = info_entry.get("multi_min_limit")
            multi_max_limit = info_entry.get("multi_max_limit")

        # 题目卡片
        card = CardWidget(container)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)

        # 题目标题行
        header = QHBoxLayout()
        header.setSpacing(12)
        title = SubtitleLabel(f"第{qnum or idx + 1}题", card)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)
        type_label = BodyLabel(f"[{_get_entry_type_label(entry)}]", card)
        type_label.setStyleSheet("color: #0078d4; font-size: 12px;")
        header.addWidget(type_label)

        # 跳题逻辑警告徽标
        has_jump = bool(info_entry.get("has_jump"))
        if has_jump:
            jump_badge = BodyLabel("[含跳题逻辑]", card)
            jump_badge.setStyleSheet("font-size: 12px; font-weight: 500;")
            _apply_label_color(jump_badge, "#d97706", "#e5a00d")
            header.addWidget(jump_badge)
        has_dependent_display_logic = bool(info_entry.get("has_dependent_display_logic"))
        if has_dependent_display_logic:
            control_badge = BodyLabel("[控制后续显示]", card)
            control_badge.setStyleSheet("font-size: 12px; font-weight: 500;")
            _apply_label_color(control_badge, "#0f766e", "#34d399")
            header.addWidget(control_badge)
        has_display_condition = bool(info_entry.get("has_display_condition"))
        if has_display_condition:
            condition_badge = BodyLabel("[条件显示题]", card)
            condition_badge.setStyleSheet("font-size: 12px; font-weight: 500;")
            _apply_label_color(condition_badge, "#166534", "#4ade80")
            header.addWidget(condition_badge)

        header.addStretch(1)
        if entry.question_type == "slider":
            slider_note = BodyLabel("目标值会自动做小幅随机抖动，避免每份都填同一个数", card)
            slider_note.setStyleSheet("font-size: 12px;")
            slider_note.setWordWrap(False)
            slider_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            _apply_label_color(slider_note, "#777777", "#bfbfbf")
            header.addWidget(slider_note)
        if entry.question_type == "multiple":
            # 构建多选题提示文本
            multi_note_text = "每个选项被选中的概率相互独立，不要求总和100%"
            if multi_min_limit is not None or multi_max_limit is not None:
                limit_parts = []
                if multi_min_limit is not None and multi_max_limit is not None:
                    if multi_min_limit == multi_max_limit:
                        limit_parts.append(f"必须选择 {multi_min_limit} 项")
                    else:
                        limit_parts.append(f"最少 {multi_min_limit} 项，最多 {multi_max_limit} 项")
                elif multi_min_limit is not None:
                    limit_parts.append(f"最少选择 {multi_min_limit} 项")
                elif multi_max_limit is not None:
                    limit_parts.append(f"最多选择 {multi_max_limit} 项")
                if limit_parts:
                    multi_note_text += f"  |  {limit_parts[0]}"
            multi_note = BodyLabel(multi_note_text, card)
            multi_note.setStyleSheet("font-size: 12px;")
            multi_note.setWordWrap(False)
            multi_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            _apply_label_color(multi_note, "#777777", "#bfbfbf")
            header.addWidget(multi_note)
        card_layout.addLayout(header)

        # 题目描述
        if title_text:
            display_text = title_text
            # 多项填空题：在题目内容中标注填空项位置
            text_inputs = info_entry.get("text_inputs", 0)
            is_multi_text = info_entry.get("is_multi_text", False)
            if (is_multi_text or text_inputs > 1) and text_inputs > 0:
                # 将题目文本按空格分隔，为每个部分添加编号
                parts = title_text.split()
                if len(parts) >= text_inputs:
                    display_text = " ".join([f"{parts[i]}____(填空{i+1})" for i in range(text_inputs)])
            desc = BodyLabel(_shorten_text(display_text, 120), card)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-size: 12px; margin-bottom: 4px;")
            _apply_label_color(desc, "#555555", "#c8c8c8")
            card_layout.addWidget(desc)

        # 跳题逻辑风险提示
        if has_jump:
            jump_warn = BodyLabel(
                "⚠️ 此题包含跳题逻辑。若给跳题选项分配较高概率，"
                "可能导致大量样本提前结束或跳过后续题目，请谨慎设定配比。",
                card,
            )
            jump_warn.setWordWrap(True)
            jump_warn.setStyleSheet("font-size: 12px; padding: 4px 0;")
            _apply_label_color(jump_warn, "#b45309", "#e5a00d")
            card_layout.addWidget(jump_warn)

        if has_dependent_display_logic:
            display_control_warn = BodyLabel(self._build_dependent_display_summary(info_entry), card)
            display_control_warn.setWordWrap(True)
            display_control_warn.setStyleSheet("font-size: 12px; padding: 4px 0;")
            _apply_label_color(display_control_warn, "#0f766e", "#86efac")
            card_layout.addWidget(display_control_warn)

        if has_display_condition:
            display_condition_warn = BodyLabel(self._build_display_condition_summary(info_entry), card)
            display_condition_warn.setWordWrap(True)
            display_condition_warn.setStyleSheet("font-size: 12px; padding: 4px 0;")
            _apply_label_color(display_condition_warn, "#166534", "#86efac")
            card_layout.addWidget(display_condition_warn)

        # 根据题型构建不同的配置区域
        if entry.question_type in ("text", "multi_text"):
            self._build_text_section(idx, entry, card, card_layout)
        elif entry.question_type == "matrix":
            self._build_matrix_section(idx, entry, card, card_layout, option_texts, row_texts)
        elif entry.question_type == "order":
            self._build_order_section(card, card_layout, option_texts)
        else:
            self._build_slider_section(idx, entry, card, card_layout, option_texts)
        self._build_attached_select_section(idx, entry, card, card_layout)
        self._register_question_card_interaction_targets(card, idx)

        inner.addWidget(card)
        return card
    def _build_attached_select_section(self, idx: int, entry: QuestionEntry, card: CardWidget, card_layout: QVBoxLayout) -> None:
        raw_configs = getattr(entry, "attached_option_selects", None) or []
        if not isinstance(raw_configs, list) or not raw_configs:
            return

        stored_configs: List[Dict[str, Any]] = []
        separator = QFrame(card)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setStyleSheet("color: rgba(255, 255, 255, 0.16); margin-top: 6px; margin-bottom: 6px;")
        card_layout.addWidget(separator)

        section_title = BodyLabel("嵌入式下拉配比：", card)
        section_title.setStyleSheet("font-size: 12px; font-weight: 600; margin-top: 4px;")
        _apply_label_color(section_title, "#444444", "#e0e0e0")
        card_layout.addWidget(section_title)

        section_hint = BodyLabel("只有命中对应单选项时，下面这些嵌入式下拉权重才会生效；底部会自动换算成目标占比。", card)
        section_hint.setWordWrap(True)
        section_hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(section_hint, "#666666", "#bfbfbf")
        card_layout.addWidget(section_hint)

        for item in raw_configs:
            if not isinstance(item, dict):
                continue
            select_options_raw = item.get("select_options")
            if not isinstance(select_options_raw, list):
                continue
            select_options = [str(opt or "").strip() for opt in select_options_raw if str(opt or "").strip()]
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

            item_title = BodyLabel(f"当选择“{_shorten_text(option_text, 40)}”时：", card)
            item_title.setWordWrap(True)
            item_title.setStyleSheet("font-size: 12px; margin-top: 6px;")
            _apply_label_color(item_title, "#0f6cbd", "#63b3ff")
            card_layout.addWidget(item_title)

            sliders: List[NoWheelSlider] = []
            for opt_idx, select_text in enumerate(select_options):
                row_widget = QWidget(card)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 2, 0, 2)
                row_layout.setSpacing(12)

                num_label = BodyLabel(f"{opt_idx + 1}.", card)
                num_label.setFixedWidth(24)
                num_label.setStyleSheet("font-size: 12px;")
                _apply_label_color(num_label, "#888888", "#a6a6a6")
                row_layout.addWidget(num_label)

                text_label = BodyLabel(select_text, card)
                _configure_wrapped_text_label(text_label, 160)
                text_label.setStyleSheet("font-size: 13px;")
                row_layout.addWidget(text_label)

                slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
                slider.setRange(0, 100)
                slider.setValue(int(min(100, max(0, round(weights[opt_idx])))))
                slider.setMinimumWidth(200)
                row_layout.addWidget(slider, 1)

                value_input = LineEdit(card)
                value_input.setFixedWidth(60)
                value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
                value_input.setText(str(slider.value()))
                _bind_slider_input(slider, value_input)
                row_layout.addWidget(value_input)

                card_layout.addWidget(row_widget)
                sliders.append(slider)

            ratio_preview_label = BodyLabel("", card)
            ratio_preview_label.setWordWrap(True)
            ratio_preview_label.setStyleSheet("font-size: 12px; margin-bottom: 2px;")
            _apply_label_color(ratio_preview_label, "#666666", "#bfbfbf")
            card_layout.addWidget(ratio_preview_label)

            def _update_option_preview(_value: int = 0, _label=ratio_preview_label, _sliders=sliders, _options=select_options):
                self._refresh_ratio_preview_label(
                    _label,
                    _sliders,
                    _options,
                    "嵌入式下拉目标占比：",
                )

            for slider in sliders:
                slider.valueChanged.connect(_update_option_preview)
            _update_option_preview()

            stored_configs.append({
                "option_index": option_index,
                "option_text": option_text,
                "select_options": select_options,
                "sliders": sliders,
            })

        if stored_configs:
            self.attached_select_slider_map[idx] = stored_configs
    def _restore_entries(self) -> None:
        limit = min(len(self.entries), len(self._entry_snapshots))
        for idx in range(limit):
            snapshot = copy.deepcopy(self._entry_snapshots[idx])
            self.entries[idx].__dict__.update(snapshot.__dict__)
