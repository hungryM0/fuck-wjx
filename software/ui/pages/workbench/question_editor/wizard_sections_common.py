"""向导题型配置共享状态与小部件辅助。"""
from html import escape
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, LineEdit, isDarkTheme

from software.core.questions.config import QuestionEntry
from software.core.questions.utils import OPTION_FILL_AI_TOKEN, parse_random_int_token, try_parse_random_int_range
from software.ui.helpers.ai_fill import ensure_ai_ready
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.widgets.no_wheel import NoWheelSlider

from .utils import _shorten_text

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

class WizardSectionsCommonMixin:
    if TYPE_CHECKING:
        text_container_map: Dict[int, QWidget]
        text_add_btn_map: Dict[int, Any]
        text_random_mode_map: Dict[int, str]
        ai_check_map: Dict[int, Any]
        ai_label_map: Dict[int, BodyLabel]
        text_random_list_radio_map: Dict[int, Any]
        text_random_name_check_map: Dict[int, Any]
        text_random_mobile_check_map: Dict[int, Any]
        text_random_id_card_check_map: Dict[int, Any]
        text_random_integer_check_map: Dict[int, Any]
        text_random_int_min_edit_map: Dict[int, LineEdit]
        text_random_int_max_edit_map: Dict[int, LineEdit]

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
        label.setToolTip(
            "这里显示的是目标占比。开启信效度优化后，量表/评分/下拉/矩阵题会优先按整批目标占比执行；其他题型仍可能受一致性和随机策略影响。"
        )
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
