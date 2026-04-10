"""配置向导弹窗：用滑块快速设置权重/概率，编辑填空题答案。"""
import copy
from typing import Any, Dict, List, Optional, Tuple, cast

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QButtonGroup, QDialog, QHBoxLayout, QListWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    ScrollArea,
    SearchLineEdit,
    SegmentedWidget,
    SwitchButton,
)

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.config import QuestionEntry
from software.core.questions.utils import OPTION_FILL_AI_TOKEN, build_random_int_token, serialize_random_int_range
from software.ui.widgets.no_wheel import NoWheelSlider

from .psycho_config import BIAS_PRESET_CHOICES
from .utils import _apply_label_color, _shorten_text, build_entry_info_list
from .wizard_cards import WizardCardsMixin
from .wizard_navigation import FloatingPagerShell, StableVerticalPipsPager, WizardNavigationMixin
from .wizard_search import WizardSearchMixin
from .wizard_sections import (
    WizardSectionsMixin,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
)

TextEditsValue = List[LineEdit] | List[List[LineEdit]]


class QuestionWizardDialog(
    WizardSearchMixin,
    WizardNavigationMixin,
    WizardCardsMixin,
    WizardSectionsMixin,
    QDialog,
):
    """配置向导：用滑块快速设置权重/概率，编辑填空题答案。"""
    def __init__(
        self,
        entries: List[QuestionEntry],
        info: List[Dict[str, Any]],
        survey_title: Optional[str] = None,
        parent=None,
        reliability_mode_enabled: bool = True,
    ):
        super().__init__(parent)
        window_title = "配置向导"
        if survey_title:
            window_title = f"{window_title} - {_shorten_text(survey_title, 36)}"
        self.setWindowTitle(window_title)
        self.resize(1060, 820)
        self.entries = entries
        raw_info = list(info or [])
        # 右侧配置卡片必须和可配置题目一一对应，不能直接拿原始解析结果按下标硬对。
        self.info = build_entry_info_list(self.entries, raw_info)
        self.reliability_mode_enabled = reliability_mode_enabled
        self.slider_map: Dict[int, List[NoWheelSlider]] = {}
        self.matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]] = {}
        self.text_edit_map: Dict[int, TextEditsValue] = {}
        self.ai_check_map: Dict[int, SwitchButton] = {}
        self.ai_label_map: Dict[int, BodyLabel] = {}
        self.text_container_map: Dict[int, QWidget] = {}
        self.text_add_btn_map: Dict[int, PushButton] = {}
        self.text_random_mode_map: Dict[int, str] = {}
        self.text_random_list_radio_map: Dict[int, RadioButton] = {}
        self.text_random_name_check_map: Dict[int, RadioButton] = {}
        self.text_random_mobile_check_map: Dict[int, RadioButton] = {}
        self.text_random_id_card_check_map: Dict[int, RadioButton] = {}
        self.text_random_integer_check_map: Dict[int, RadioButton] = {}
        self.text_random_int_min_edit_map: Dict[int, LineEdit] = {}
        self.text_random_int_max_edit_map: Dict[int, LineEdit] = {}
        self.text_random_group_map: Dict[int, QButtonGroup] = {}
        self.multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]] = {}
        self.bias_preset_map: Dict[int, Any] = {}
        self.attached_select_slider_map: Dict[int, List[Dict[str, Any]]] = {}
        self.option_fill_edit_map: Dict[int, Dict[int, LineEdit]] = {}
        self.option_fill_state_map: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._question_search_cache: Dict[int, str] = {}
        self._search_match_indices: List[int] = []
        self._last_search_keyword = ""
        self._last_search_match_cursor = -1
        self._entry_snapshots: List[QuestionEntry] = [copy.deepcopy(entry) for entry in entries]
        self._has_content = False
        self._current_question_idx = 0
        self._question_cards: List[CardWidget] = []
        self._scroll_area: Optional[ScrollArea] = None
        self._content_container: Optional[QWidget] = None
        self._content_layout: Optional[QVBoxLayout] = None
        self._navigation_host: Optional[QWidget] = None
        self._question_shell: Optional[FloatingPagerShell] = None
        self._question_pager: Optional[StableVerticalPipsPager] = None
        self._navigation_item_count = 0
        self._navigation_lane_width = 26
        self._scroll_animation: Optional[QPropertyAnimation] = None
        self._is_animating_scroll = False
        self._search_edit: Optional[SearchLineEdit] = None
        self._search_status_label: Optional[BodyLabel] = None
        self._search_popup: Optional[QListWidget] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        intro = BodyLabel("配置各题目的选项权重/概率或填空答案", self)
        intro.setStyleSheet("font-size: 13px;")
        _apply_label_color(intro, "#666666", "#bfbfbf")
        layout.addWidget(intro)

        right_panel = QWidget(self)
        self._navigation_host = right_panel
        layout.addWidget(right_panel, 1)

        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(0)
        search_edit = SearchLineEdit(right_panel)
        search_edit.setPlaceholderText("搜索题干 / 选项内容")
        search_edit.setFixedWidth(440)
        self._configure_search_popup(search_edit)
        search_edit.returnPressed.connect(self._handle_search_return_pressed)
        search_edit.searchSignal.connect(self._handle_question_search)
        search_edit.clearSignal.connect(self._clear_question_search)
        search_edit.textChanged.connect(self._on_search_text_changed)
        search_row.addStretch(1)
        search_row.addWidget(search_edit, 0, Qt.AlignmentFlag.AlignCenter)
        search_row.addStretch(1)
        right_layout.addLayout(search_row)
        self._search_edit = search_edit

        scroll = ScrollArea(right_panel)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        scroll.setViewportMargins(self._navigation_lane_width, 0, 0, 0)
        self._scroll_area = scroll
        container = QWidget(right_panel)
        scroll.setWidget(container)
        self._content_container = container
        inner = QVBoxLayout(container)
        inner.setContentsMargins(4, 4, 12, 4)
        inner.setSpacing(20)
        self._content_layout = inner
        right_layout.addWidget(scroll, 1)

        # 批量倾向预设（在滚动区内最顶部）
        master_row = QHBoxLayout()
        master_row.setSpacing(8)
        master_lbl = BodyLabel("批量倾向预设：", container)
        master_lbl.setStyleSheet("font-size: 13px;")
        _apply_label_color(master_lbl, "#444444", "#e0e0e0")
        master_row.addWidget(master_lbl)
        _master_seg = SegmentedWidget(container)
        for _v, _t in BIAS_PRESET_CHOICES:
            _master_seg.addItem(routeKey=_v, text=_t)
        _master_seg.setCurrentItem("custom")
        master_row.addWidget(_master_seg)
        master_row.addStretch(1)
        inner.addLayout(master_row)

        for idx, entry in enumerate(self.entries):
            self._question_cards.append(self._build_entry_card(idx, entry, container, inner))

        self._master_applying = False

        def _on_master_preset(route_key: str):
            if route_key == "custom":
                return
            self._master_applying = True
            for seg in self.bias_preset_map.values():
                if isinstance(seg, list):
                    for s in seg:
                        s.setCurrentItem(route_key)
                else:
                    seg.setCurrentItem(route_key)
            self._master_applying = False
        _master_seg.currentItemChanged.connect(_on_master_preset)

        def _reset_master(_=None):
            if self._master_applying:
                return
            if _master_seg.currentRouteKey() != "custom":
                _master_seg.setCurrentItem("custom")
        for seg in self.bias_preset_map.values():
            if isinstance(seg, list):
                for s in seg:
                    s.currentItemChanged.connect(_reset_master)
            else:
                seg.currentItemChanged.connect(_reset_master)

        if not self._has_content:
            empty_label = BodyLabel("当前无题目需要配置", container)
            empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inner.addWidget(empty_label)

        inner.addStretch(1)
        self._question_shell = self._build_navigation_shell(right_panel)
        self._question_pager = self._question_shell.pager
        self._configure_navigation_pager(len(self._question_cards))
        self._refresh_navigation_state(len(self._question_cards))
        self._navigate_to_question(0, animate=False)
        scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        QTimer.singleShot(0, self._update_navigation_pager_geometry)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", right_panel)
        cancel_btn.setFixedWidth(80)
        ok_btn = PrimaryPushButton("保存", right_panel)
        ok_btn.setFixedWidth(80)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        right_layout.addLayout(btn_row)

        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
    def get_results(self) -> Dict[int, Any]:
        """获取滑块权重/概率结果"""
        result: Dict[int, Any] = {}
        for idx, sliders in self.slider_map.items():
            weights = [max(0, s.value()) for s in sliders]
            if weights and not any(weight > 0 for weight in weights):
                raise ValueError(f"{self._format_question_label(idx)}的选项配比不能全为0。")
            result[idx] = weights

        for idx, row_sliders in self.matrix_row_slider_map.items():
            row_weights: List[List[int]] = []
            for row_idx, row in enumerate(row_sliders):
                weights = [max(0, s.value()) for s in row]
                if weights and not any(weight > 0 for weight in weights):
                    raise ValueError(f"{self._format_question_label(idx)}的第{row_idx + 1}行配比不能全为0。")
                row_weights.append(weights)
            result[idx] = row_weights
        return result
    def get_text_results(self) -> Dict[int, List[str]]:
        """获取填空题答案结果"""
        from software.core.questions.text_shared import MULTI_TEXT_DELIMITER
        result: Dict[int, List[str]] = {}
        for idx, edits in self.text_edit_map.items():
            if edits and isinstance(edits[0], list):
                # 多项填空题：二维列表
                texts = []
                matrix_edits = cast(List[List[LineEdit]], edits)
                for row_edits in matrix_edits:
                    row_values = [edit.text().strip() for edit in row_edits]
                    merged = MULTI_TEXT_DELIMITER.join(row_values)
                    if merged:
                        texts.append(merged)
            else:
                # 普通填空题：一维列表
                flat_edits = cast(List[LineEdit], edits)
                texts = [e.text().strip() for e in flat_edits if e.text().strip()]
            if not texts:
                texts = [DEFAULT_FILL_TEXT]
            result[idx] = texts
        return result
    def get_option_fill_results(self) -> Dict[int, List[Optional[str]]]:
        """获取选择题中“其他请填空”等附加输入框的配置结果。"""
        result: Dict[int, List[Optional[str]]] = {}
        for idx, state_map in self.option_fill_state_map.items():
            if not state_map:
                continue
            info = self._get_entry_info(idx)
            option_count = int(info.get("options") or 0)
            max_index = max(state_map.keys()) if state_map else -1
            normalized_count = max(option_count, max_index + 1, 0)
            values: List[Optional[str]] = [None] * normalized_count
            for option_index, state in state_map.items():
                ai_cb = state.get("ai_cb")
                if ai_cb is not None and ai_cb.isChecked():
                    text: Optional[str] = OPTION_FILL_AI_TOKEN
                else:
                    group = state.get("group")
                    checked_id = group.checkedId() if group is not None else 0
                    if checked_id == 1:
                        text = _TEXT_RANDOM_NAME_TOKEN
                    elif checked_id == 2:
                        text = _TEXT_RANDOM_MOBILE_TOKEN
                    elif checked_id == 3:
                        text = _TEXT_RANDOM_ID_CARD_TOKEN
                    elif checked_id == 4:
                        min_edit = state.get("min_edit")
                        max_edit = state.get("max_edit")
                        text = build_random_int_token(
                            min_edit.text().strip() if min_edit is not None else "",
                            max_edit.text().strip() if max_edit is not None else "",
                        )
                    else:
                        edit = state.get("edit")
                        raw_text = edit.text().strip() if edit is not None else ""
                        text = raw_text or None
                if 0 <= option_index < normalized_count:
                    values[option_index] = text
            result[idx] = values
        return result
    def get_text_random_modes(self) -> Dict[int, str]:
        """获取填空题随机值模式（none/name/mobile/integer）"""
        return {idx: mode for idx, mode in self.text_random_mode_map.items()}
    def get_text_random_int_ranges(self) -> Dict[int, List[int]]:
        """获取填空题随机整数范围。"""
        result: Dict[int, List[int]] = {}
        for idx, min_edit in self.text_random_int_min_edit_map.items():
            max_edit = self.text_random_int_max_edit_map.get(idx)
            raw_range = [min_edit.text().strip(), max_edit.text().strip() if max_edit else ""]
            result[idx] = serialize_random_int_range(raw_range)
        return result
    def get_multi_text_blank_modes(self) -> Dict[int, List[str]]:
        """获取多项填空题每个填空项的随机模式"""
        from .wizard_sections import _TEXT_RANDOM_NONE, _TEXT_RANDOM_NAME, _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_ID_CARD, _TEXT_RANDOM_INTEGER
        result: Dict[int, List[str]] = {}
        if not hasattr(self, "multi_text_blank_radio_groups"):
            return result
        for idx, groups in self.multi_text_blank_radio_groups.items():
            modes: List[str] = []
            for group in groups:
                checked_id = group.checkedId()
                if checked_id == 1:
                    modes.append(_TEXT_RANDOM_NAME)
                elif checked_id == 2:
                    modes.append(_TEXT_RANDOM_MOBILE)
                elif checked_id == 3:
                    modes.append(_TEXT_RANDOM_ID_CARD)
                elif checked_id == 4:
                    modes.append(_TEXT_RANDOM_INTEGER)
                else:
                    modes.append(_TEXT_RANDOM_NONE)
            result[idx] = modes
        return result
    def get_multi_text_blank_int_ranges(self) -> Dict[int, List[List[int]]]:
        """获取多项填空题每个填空项的随机整数范围。"""
        result: Dict[int, List[List[int]]] = {}
        for idx, edit_pairs in self.multi_text_blank_integer_range_edits.items():
            ranges: List[List[int]] = []
            for min_edit, max_edit in edit_pairs:
                ranges.append(serialize_random_int_range([min_edit.text().strip(), max_edit.text().strip()]))
            result[idx] = ranges
        return result
    def get_multi_text_blank_ai_flags(self) -> Dict[int, List[bool]]:
        """获取多项填空题每个填空项的AI标志"""
        result: Dict[int, List[bool]] = {}
        if not hasattr(self, "multi_text_blank_ai_checkboxes"):
            return result
        for idx, checkboxes in self.multi_text_blank_ai_checkboxes.items():
            result[idx] = [cb.isChecked() for cb in checkboxes]
        return result
    def get_ai_flags(self) -> Dict[int, bool]:
        """获取填空题是否启用 AI"""
        result: Dict[int, bool] = {}
        for idx, cb in self.ai_check_map.items():
            random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
            result[idx] = False if random_mode != _TEXT_RANDOM_NONE else cb.isChecked()
        return result
    def get_attached_select_results(self) -> Dict[int, List[Dict[str, Any]]]:
        result: Dict[int, List[Dict[str, Any]]] = {}
        for idx, config_items in self.attached_select_slider_map.items():
            serialized_items: List[Dict[str, Any]] = []
            for item in config_items:
                sliders = item.get("sliders") or []
                weights = [max(0, slider.value()) for slider in sliders]
                if weights and not any(weight > 0 for weight in weights):
                    option_text = str(item.get("option_text") or "").strip()
                    if not option_text:
                        option_text = f"第{int(item.get('option_index', 0)) + 1}项"
                    raise ValueError(
                        f"{self._format_question_label(idx)}里“{option_text}”对应的嵌入式下拉配比不能全为0。"
                    )
                serialized_items.append({
                    "option_index": int(item.get("option_index", 0)),
                    "option_text": str(item.get("option_text") or "").strip(),
                    "select_options": list(item.get("select_options") or []),
                    "weights": weights,
                })
            result[idx] = serialized_items
        return result
    def get_bias_presets(self) -> Dict[int, Any]:
        """获取每个题目的倾向预设值（矩阵题返回列表）"""
        result: Dict[int, Any] = {}
        for idx, seg in self.bias_preset_map.items():
            if isinstance(seg, list):
                result[idx] = [str(s.currentRouteKey() or "custom") for s in seg]
            else:
                result[idx] = str(seg.currentRouteKey() or "custom")
        return result
    def get_dimensions(self) -> Dict[int, Optional[str]]:
        """获取题目的当前维度配置。"""
        result: Dict[int, Optional[str]] = {}
        for idx, entry in enumerate(self.entries):
            try:
                raw = str(getattr(entry, "dimension", "") or "").strip()
            except Exception:
                raw = ""
            result[idx] = raw or None
        return result
