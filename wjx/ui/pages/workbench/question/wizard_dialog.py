"""配置向导弹窗：用滑块快速设置权重/概率，编辑填空题答案。"""
import copy
from typing import List, Dict, Any, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    LineEdit,
    CheckBox,
    PillPushButton,
    TransparentPushButton,
    FluentIcon,
)
from qfluentwidgets import FlowLayout

from wjx.ui.widgets.no_wheel import NoWheelSlider
from wjx.core.questions.config import QuestionEntry
from wjx.utils.app.config import DEFAULT_FILL_TEXT, PRESET_DIMENSIONS, DIMENSION_UNGROUPED
from wjx.ui.helpers.ai_fill import ensure_ai_ready

from .constants import _get_entry_type_label
from .utils import _shorten_text, _apply_label_color, _bind_slider_input


# ---------------------------------------------------------------------------
# DimensionCard — 单个维度的卡片，内含 PillPushButton 多选过滤器
# ---------------------------------------------------------------------------

class DimensionCard(CardWidget):
    """一个维度的配置卡片，使用 PillPushButton 多选题目。"""

    dimensionChanged = Signal()   # 维度内容发生变化时发出
    removeRequested = Signal(object)  # 请求删除自身

    def __init__(
        self,
        dimension_name: str,
        question_labels: List[str],
        selected_indices: Set[int],
        parent=None,
    ):
        super().__init__(parent)
        self.dimension_name = dimension_name
        self._question_labels = question_labels
        self._pills: List[PillPushButton] = []

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 12, 16, 14)
        root_layout.setSpacing(10)

        # ---- 标题行 ----
        header = QHBoxLayout()
        header.setSpacing(8)

        self.name_edit = LineEdit(self)
        self.name_edit.setText(dimension_name)
        self.name_edit.setPlaceholderText("维度名称")
        self.name_edit.setMinimumWidth(120)
        self.name_edit.setMaximumWidth(240)
        self.name_edit.editingFinished.connect(self._on_name_edited)
        header.addWidget(self.name_edit)

        self.count_badge = CaptionLabel(self)
        self._update_count_badge(len(selected_indices))
        header.addWidget(self.count_badge)

        header.addStretch(1)

        # 全选 / 清空按钮
        select_all_btn = TransparentPushButton("全选", self)
        select_all_btn.setFixedHeight(28)
        select_all_btn.clicked.connect(self._select_all)
        header.addWidget(select_all_btn)

        clear_btn = TransparentPushButton("清空", self)
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._clear_all)
        header.addWidget(clear_btn)

        del_btn = TransparentPushButton(FluentIcon.DELETE, "删除维度", self)
        del_btn.setFixedHeight(28)
        del_btn.clicked.connect(lambda: self.removeRequested.emit(self))
        header.addWidget(del_btn)

        root_layout.addLayout(header)

        # ---- 多选过滤器区域 ----
        self.flow = FlowLayout(needAni=True, isTight=True)
        self.flow.setHorizontalSpacing(6)
        self.flow.setVerticalSpacing(6)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.flow.setAnimation(250)

        for i, label in enumerate(question_labels):
            pill = PillPushButton(label, self)
            pill.setCheckable(True)
            pill.setChecked(i in selected_indices)
            pill.setMinimumHeight(30)
            pill.clicked.connect(self._on_pill_toggled)
            self.flow.addWidget(pill)
            self._pills.append(pill)

        flow_container = QWidget(self)
        flow_container.setLayout(self.flow)
        root_layout.addWidget(flow_container)

    # -- 公开接口 --

    def get_name(self) -> str:
        return self.name_edit.text().strip() or self.dimension_name

    def get_selected_indices(self) -> Set[int]:
        return {i for i, pill in enumerate(self._pills) if pill.isChecked()}

    def set_pill_checked(self, idx: int, checked: bool, block_signal: bool = False):
        if 0 <= idx < len(self._pills):
            pill = self._pills[idx]
            if block_signal:
                pill.blockSignals(True)
            pill.setChecked(checked)
            if block_signal:
                pill.blockSignals(False)
        self._update_count_badge(len(self.get_selected_indices()))

    # -- 内部 --

    def _on_name_edited(self):
        text = self.name_edit.text().strip()
        if text:
            self.dimension_name = text
        self.dimensionChanged.emit()

    def _on_pill_toggled(self):
        self._update_count_badge(len(self.get_selected_indices()))
        self.dimensionChanged.emit()

    def _select_all(self):
        for pill in self._pills:
            pill.setChecked(True)
        self._update_count_badge(len(self._pills))
        self.dimensionChanged.emit()

    def _clear_all(self):
        for pill in self._pills:
            pill.setChecked(False)
        self._update_count_badge(0)
        self.dimensionChanged.emit()

    def _update_count_badge(self, count: int):
        total = len(self._pills)
        self.count_badge.setText(f"已选 {count}/{total} 题")
        color = "#0078d4" if count > 0 else "#888888"
        self.count_badge.setStyleSheet(f"color: {color}; font-size: 12px; margin-left: 4px;")


# ---------------------------------------------------------------------------
# QuestionWizardDialog — 主对话框
# ---------------------------------------------------------------------------

class QuestionWizardDialog(QDialog):
    """配置向导：用滑块快速设置权重/概率，编辑填空题答案。"""

    @staticmethod
    def _resolve_matrix_weights(entry: QuestionEntry, rows: int, columns: int) -> List[List[float]]:
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

    def _resolve_slider_bounds(self, idx: int, entry: QuestionEntry) -> List[int]:
        min_val = 0.0
        max_val = 10.0

        if idx < len(self.info):
            question_info = self.info[idx] or {}
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
        return [min_int, max_int]

    def __init__(self, entries: List[QuestionEntry], info: List[Dict[str, Any]], survey_title: Optional[str] = None, parent=None, reliability_mode_enabled: bool = True):
        super().__init__(parent)
        window_title = "配置向导"
        if survey_title:
            window_title = f"{window_title} - {_shorten_text(survey_title, 36)}"
        self.setWindowTitle(window_title)
        self.resize(900, 800)
        self.entries = entries
        self.info = info or []
        self.reliability_mode_enabled = reliability_mode_enabled
        self.slider_map: Dict[int, List[NoWheelSlider]] = {}
        self.matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]] = {}
        self.text_edit_map: Dict[int, List[LineEdit]] = {}
        self.ai_check_map: Dict[int, CheckBox] = {}
        self.text_container_map: Dict[int, QWidget] = {}
        self.text_add_btn_map: Dict[int, PushButton] = {}
        self._entry_snapshots: List[QuestionEntry] = [copy.deepcopy(entry) for entry in entries]
        self._has_content = False

        # 构建题目标签列表（供维度卡片使用）
        self._question_labels: List[str] = []
        for idx, entry in enumerate(entries):
            qnum = ""
            title_text = ""
            if idx < len(self.info):
                qnum = str(self.info[idx].get("num") or "")
                title_text = str(self.info[idx].get("title") or "")
            num_str = qnum or str(idx + 1)
            type_str = _get_entry_type_label(entry)
            short_title = _shorten_text(title_text, 20) if title_text else ""
            if short_title:
                label = f"Q{num_str} {short_title}"
            else:
                label = f"Q{num_str}({type_str})"
            self._question_labels.append(label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 顶部说明
        intro = BodyLabel("配置各题目的选项权重/概率或填空答案", self)
        intro.setStyleSheet("font-size: 13px;")
        _apply_label_color(intro, "#666666", "#bfbfbf")
        layout.addWidget(intro)

        # 维度设置区域（仅在信效度模式开启时显示）
        self._dimension_cards: List[DimensionCard] = []
        if self.reliability_mode_enabled:
            self._build_dimension_section(layout)

        # 滚动区域
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        container = QWidget(self)
        scroll.setWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(4, 4, 12, 4)
        inner.setSpacing(20)

        for idx, entry in enumerate(entries):
            self._build_entry_card(idx, entry, container, inner)

        if not self._has_content:
            empty_label = BodyLabel("当前无题目需要配置", container)
            empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inner.addWidget(empty_label)

        inner.addStretch(1)
        layout.addWidget(scroll, 3)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self)
        cancel_btn.setFixedWidth(80)
        ok_btn = PrimaryPushButton("保存", self)
        ok_btn.setFixedWidth(80)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------ #
    #  维度管理 — 新版 UI                                                  #
    # ------------------------------------------------------------------ #

    def _build_dimension_section(self, layout: QVBoxLayout) -> None:
        """构建维度管理区域：可添加多个维度卡片，每个卡片内用 PillPushButton 选择题目。"""
        section_card = CardWidget(self)
        section_layout = QVBoxLayout(section_card)
        section_layout.setContentsMargins(16, 12, 16, 14)
        section_layout.setSpacing(10)

        # 标题行
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(SubtitleLabel("维度设置", section_card))
        hint = BodyLabel("创建维度并用多选过滤器选择每个维度包含的题目", section_card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        header.addWidget(hint)
        header.addStretch(1)

        add_dim_btn = PushButton(FluentIcon.ADD, "添加维度", section_card)
        add_dim_btn.setFixedHeight(30)
        add_dim_btn.clicked.connect(self._add_dimension)
        header.addWidget(add_dim_btn)
        section_layout.addLayout(header)

        # 维度卡片容器（使用 ScrollArea 以防维度过多）
        self._dim_scroll = ScrollArea(section_card)
        self._dim_scroll.setWidgetResizable(True)
        self._dim_scroll.setMinimumHeight(80)
        self._dim_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._dim_scroll.enableTransparentBackground()

        dim_container = QWidget(section_card)
        self._dim_scroll.setWidget(dim_container)
        self._dim_container_layout = QVBoxLayout(dim_container)
        self._dim_container_layout.setContentsMargins(0, 0, 0, 0)
        self._dim_container_layout.setSpacing(10)

        # 从 entries 中收集已有维度
        existing_dims = self._collect_existing_dimensions()

        if existing_dims:
            for dim_name, indices in existing_dims.items():
                self._create_dimension_card(dim_name, indices)
        else:
            # 没有已有维度时自动创建一个空白维度
            pass  # 用户可以通过"添加维度"按钮添加

        self._dim_container_layout.addStretch(1)
        section_layout.addWidget(self._dim_scroll, 1)

        # 未分组提示
        self._ungrouped_label = CaptionLabel("", section_card)
        self._ungrouped_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(self._ungrouped_label, "#888888", "#a6a6a6")
        section_layout.addWidget(self._ungrouped_label)
        self._update_ungrouped_hint()

        layout.addWidget(section_card, 2)

    def _collect_existing_dimensions(self) -> Dict[str, Set[int]]:
        """从 entries 中收集已有的维度分组。"""
        dims: Dict[str, Set[int]] = {}
        for idx, entry in enumerate(self.entries):
            dim = getattr(entry, "dimension", None)
            if dim and dim != DIMENSION_UNGROUPED:
                dim = str(dim).strip()
                if dim:
                    if dim not in dims:
                        dims[dim] = set()
                    dims[dim].add(idx)
        return dims

    def _create_dimension_card(self, name: str, selected: Set[int]) -> DimensionCard:
        card = DimensionCard(name, self._question_labels, selected, parent=None)
        card.dimensionChanged.connect(self._on_dimension_data_changed)
        card.removeRequested.connect(self._remove_dimension_card)
        # 插入到 stretch 之前
        count = self._dim_container_layout.count()
        insert_pos = max(0, count - 1)  # 在 stretch 之前
        self._dim_container_layout.insertWidget(insert_pos, card)
        self._dimension_cards.append(card)
        self._update_ungrouped_hint()
        return card

    def _add_dimension(self) -> None:
        """添加一个新的空白维度。"""
        existing_names = {c.get_name() for c in self._dimension_cards}
        # 从预设维度中找一个未使用的名称
        new_name = ""
        for preset in PRESET_DIMENSIONS:
            if preset not in existing_names:
                new_name = preset
                break
        if not new_name:
            # 所有预设都用完了，生成一个编号名
            idx = len(self._dimension_cards) + 1
            while f"维度{idx}" in existing_names:
                idx += 1
            new_name = f"维度{idx}"
        self._create_dimension_card(new_name, set())

    def _remove_dimension_card(self, card: DimensionCard) -> None:
        if card in self._dimension_cards:
            self._dimension_cards.remove(card)
            self._dim_container_layout.removeWidget(card)
            card.deleteLater()
            self._update_ungrouped_hint()

    def _on_dimension_data_changed(self) -> None:
        """任何维度卡片的内容发生变化时更新未分组提示。"""
        self._update_ungrouped_hint()

    def _update_ungrouped_hint(self) -> None:
        """更新"未分组题目"提示文本。"""
        all_assigned: Set[int] = set()
        for card in self._dimension_cards:
            all_assigned |= card.get_selected_indices()
        total = len(self.entries)
        ungrouped_count = total - len(all_assigned)
        if ungrouped_count > 0:
            ungrouped_indices = sorted(set(range(total)) - all_assigned)
            if len(ungrouped_indices) <= 8:
                nums = ", ".join(f"Q{i+1}" for i in ungrouped_indices)
                self._ungrouped_label.setText(f"未分组的题目 ({ungrouped_count} 题)：{nums}")
            else:
                self._ungrouped_label.setText(f"未分组的题目：{ungrouped_count} 题")
        else:
            if total > 0:
                self._ungrouped_label.setText("✓ 所有题目均已分组")
            else:
                self._ungrouped_label.setText("")

    # ------------------------------------------------------------------ #
    #  题目配置卡片 — 保持与之前兼容（去掉每题的维度下拉框）                     #
    # ------------------------------------------------------------------ #

    def _build_entry_card(self, idx: int, entry: QuestionEntry, container: QWidget, inner: QVBoxLayout) -> None:
        """构建单个题目的配置卡片。"""
        # 获取题目信息
        qnum = ""
        title_text = ""
        option_texts: List[str] = []
        row_texts: List[str] = []
        multi_min_limit: Optional[int] = None
        multi_max_limit: Optional[int] = None
        if idx < len(self.info):
            qnum = str(self.info[idx].get("num") or "")
            title_text = str(self.info[idx].get("title") or "")
            opt_raw = self.info[idx].get("option_texts")
            if isinstance(opt_raw, list):
                option_texts = [str(x) for x in opt_raw]
            row_raw = self.info[idx].get("row_texts")
            if isinstance(row_raw, list):
                row_texts = [str(x) for x in row_raw]
            # 获取多选题的选择数量限制
            if entry.question_type == "multiple":
                multi_min_limit = self.info[idx].get("multi_min_limit")
                multi_max_limit = self.info[idx].get("multi_max_limit")

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
            multi_note_text = "每个滑块的值对应的是选项的命中概率（%）"
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
            desc = BodyLabel(_shorten_text(title_text, 120), card)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-size: 12px; margin-bottom: 4px;")
            _apply_label_color(desc, "#555555", "#c8c8c8")
            card_layout.addWidget(desc)

        # 根据题型构建不同的配置区域
        if entry.question_type in ("text", "multi_text"):
            self._build_text_section(idx, entry, card, card_layout)
        elif entry.question_type == "matrix":
            self._build_matrix_section(idx, entry, card, card_layout, option_texts, row_texts)
        elif entry.question_type == "order":
            self._build_order_section(card, card_layout, option_texts)
        else:
            self._build_slider_section(idx, entry, card, card_layout, option_texts)

        inner.addWidget(card)

    def _build_text_section(self, idx: int, entry: QuestionEntry, card: CardWidget, card_layout: QVBoxLayout) -> None:
        """构建填空题答案编辑区。"""
        self._has_content = True
        hint = BodyLabel("答案列表（随机选择一个填入）：", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        # 答案行容器
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

        # 添加按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = PushButton("+ 添加答案", card)
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(lambda checked=False, f=add_row_func: f(""))
        btn_row.addWidget(add_btn)
        self.text_container_map[idx] = text_rows_container
        self.text_add_btn_map[idx] = add_btn

        if entry.question_type == "text":
            ai_cb = CheckBox("启用 AI", card)
            ai_cb.setToolTip("运行时每次填空都会调用 AI")
            ai_cb.setChecked(bool(getattr(entry, "ai_enabled", False)))
            ai_cb.toggled.connect(lambda checked, i=idx: self._on_entry_ai_toggled(i, checked))
            btn_row.addWidget(ai_cb)
            self.ai_check_map[idx] = ai_cb
            self._set_text_answer_enabled(idx, not ai_cb.isChecked())

        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)

        self.text_edit_map[idx] = edits

    def _build_matrix_section(self, idx: int, entry: QuestionEntry, card: CardWidget,
                              card_layout: QVBoxLayout, option_texts: List[str], row_texts: List[str]) -> None:
        """构建矩阵量表题配置区。"""
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

            row_sliders = build_slider_rows(row_card, row_card_layout, per_row_values[row_idx])
            per_row_sliders.append(row_sliders)
            per_row_layout.addWidget(row_card)

        self.matrix_row_slider_map[idx] = per_row_sliders

    def _build_order_section(self, card: CardWidget, card_layout: QVBoxLayout, option_texts: List[str]) -> None:
        """构建排序题展示区。"""
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
        """构建选择题/滑块题的滑块配置区。"""
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

    def _on_entry_ai_toggled(self, idx: int, checked: bool) -> None:
        if checked and not ensure_ai_ready(self.window() or self):
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            self._set_text_answer_enabled(idx, True)
            return
        self._set_text_answer_enabled(idx, not checked)

    def _restore_entries(self) -> None:
        limit = min(len(self.entries), len(self._entry_snapshots))
        for idx in range(limit):
            snapshot = copy.deepcopy(self._entry_snapshots[idx])
            self.entries[idx].__dict__.update(snapshot.__dict__)

    def reject(self) -> None:
        self._restore_entries()
        super().reject()

    # ------------------------------------------------------------------ #
    #  结果获取接口                                                        #
    # ------------------------------------------------------------------ #

    def get_results(self) -> Dict[int, Any]:
        """获取滑块权重/概率结果"""
        result: Dict[int, Any] = {}
        for idx, sliders in self.slider_map.items():
            weights = [max(0, s.value()) for s in sliders]
            if all(w <= 0 for w in weights):
                weights = [1] * len(weights)
            result[idx] = weights

        for idx, row_sliders in self.matrix_row_slider_map.items():
            row_weights: List[List[int]] = []
            for row in row_sliders:
                weights = [max(0, s.value()) for s in row]
                if all(w <= 0 for w in weights):
                    weights = [1] * len(weights)
                row_weights.append(weights)
            result[idx] = row_weights
        return result

    def get_text_results(self) -> Dict[int, List[str]]:
        """获取填空题答案结果"""
        result: Dict[int, List[str]] = {}
        for idx, edits in self.text_edit_map.items():
            texts = [e.text().strip() for e in edits if e.text().strip()]
            if not texts:
                texts = [DEFAULT_FILL_TEXT]
            result[idx] = texts
        return result

    def get_ai_flags(self) -> Dict[int, bool]:
        """获取填空题是否启用 AI"""
        return {idx: cb.isChecked() for idx, cb in self.ai_check_map.items()}

    def get_dimension_results(self) -> Dict[int, str]:
        """获取维度/分组结果 — 从维度卡片的多选状态推导每个题目的维度归属。"""
        # 如果信效度模式未启用，所有题目都标记为未分组
        if not self.reliability_mode_enabled:
            return {idx: DIMENSION_UNGROUPED for idx in range(len(self.entries))}

        result: Dict[int, str] = {}
        total = len(self.entries)

        # 倒序遍历维度卡片，后创建的维度优先级更高（处理重复选中的情况）
        # 但一般用户不会重复选同一题到多个维度，如果重复则以第一个命中为准
        assigned: Set[int] = set()
        for card in self._dimension_cards:
            dim_name = card.get_name()
            for idx in card.get_selected_indices():
                if idx not in assigned and 0 <= idx < total:
                    result[idx] = dim_name
                    assigned.add(idx)

        # 未分组的题目设置为 DIMENSION_UNGROUPED
        for idx in range(total):
            if idx not in result:
                result[idx] = DIMENSION_UNGROUPED

        return result
