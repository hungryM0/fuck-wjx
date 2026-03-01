"""配置向导弹窗：用滑块快速设置权重/概率，编辑填空题答案。"""
import copy
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QButtonGroup,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    LineEdit,
    CheckBox,
    ComboBox,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider
from wjx.core.questions.config import QuestionEntry
from wjx.utils.app.config import DEFAULT_FILL_TEXT

from .constants import _get_entry_type_label
from .utils import _shorten_text, _apply_label_color
from .wizard_sections import WizardSectionsMixin, _TEXT_RANDOM_NONE


# ---------------------------------------------------------------------------
# QuestionWizardDialog — 主对话框
# ---------------------------------------------------------------------------

class QuestionWizardDialog(WizardSectionsMixin, QDialog):
    """配置向导：用滑块快速设置权重/概率，编辑填空题答案。"""

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

    def _resolve_slider_bounds(self, idx: int, entry: QuestionEntry) -> tuple[int, int]:
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
        return (min_int, max_int)

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
        self.reverse_check_map: Dict[int, CheckBox] = {}          # scale/score 用
        self.matrix_reverse_check_map: Dict[int, List[CheckBox]] = {}  # matrix 每行用
        self.text_container_map: Dict[int, QWidget] = {}
        self.text_add_btn_map: Dict[int, PushButton] = {}
        self.text_random_mode_map: Dict[int, str] = {}
        self.text_random_name_check_map: Dict[int, CheckBox] = {}
        self.text_random_mobile_check_map: Dict[int, CheckBox] = {}
        self.text_random_group_map: Dict[int, QButtonGroup] = {}
        # 潜变量模式配置映射表
        self.psycho_check_map: Dict[int, CheckBox] = {}
        self.psycho_bias_map: Dict[int, ComboBox] = {}
        self._entry_snapshots: List[QuestionEntry] = [copy.deepcopy(entry) for entry in entries]
        self._has_content = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 顶部说明
        intro = BodyLabel("配置各题目的选项权重/概率或填空答案", self)
        intro.setStyleSheet("font-size: 13px;")
        _apply_label_color(intro, "#666666", "#bfbfbf")
        layout.addWidget(intro)

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
    #  题目配置卡片                                                        #
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

        # 跳题逻辑警告徽标
        has_jump = False
        if idx < len(self.info):
            has_jump = bool(self.info[idx].get("has_jump"))
        if has_jump:
            jump_badge = BodyLabel("[含跳题逻辑]", card)
            jump_badge.setStyleSheet("font-size: 12px; font-weight: 500;")
            _apply_label_color(jump_badge, "#d97706", "#e5a00d")
            header.addWidget(jump_badge)

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

    def get_text_random_modes(self) -> Dict[int, str]:
        """获取填空题随机值模式（none/name/mobile）"""
        return {idx: mode for idx, mode in self.text_random_mode_map.items()}

    def get_ai_flags(self) -> Dict[int, bool]:
        """获取填空题是否启用 AI"""
        result: Dict[int, bool] = {}
        for idx, cb in self.ai_check_map.items():
            random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
            result[idx] = False if random_mode != _TEXT_RANDOM_NONE else cb.isChecked()
        return result

    def get_reverse_results(self) -> Dict[int, Any]:
        """获取反向题标记结果。
        - scale/score：{idx: bool}
        - matrix：{idx: List[bool]}（每行一个）
        """
        result: Dict[int, Any] = {}
        for idx, cb in self.reverse_check_map.items():
            result[idx] = cb.isChecked()
        for idx, cbs in self.matrix_reverse_check_map.items():
            result[idx] = [cb.isChecked() for cb in cbs]
        return result

    def get_psycho_results(self) -> Dict[int, Dict[str, Any]]:
        """获取潜变量模式配置结果"""
        from wjx.ui.pages.workbench.question.psycho_config import get_psycho_results
        return get_psycho_results(self.psycho_check_map, self.psycho_bias_map)
