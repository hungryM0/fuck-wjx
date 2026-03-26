"""配置向导弹窗：用滑块快速设置权重/概率，编辑填空题答案。"""
import copy
from typing import List, Dict, Any, Optional, Tuple, Union, cast

from PySide6.QtCore import Qt, QEvent, QPropertyAnimation, QEasingCurve, QPointF, QTimer, QSize, QModelIndex, QPersistentModelIndex, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QButtonGroup,
    QFrame,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QListWidget,
    QAbstractItemView,
    QStyle,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    VerticalPipsPager,
    PushButton,
    PrimaryPushButton,
    LineEdit,
    CheckBox,
    SwitchButton,
    SegmentedWidget,
    MessageBox,
    isDarkTheme,
    themeColor,
)
from qfluentwidgets.components.widgets.tool_tip import ItemViewToolTipDelegate, ItemViewToolTipType
from qfluentwidgets.components.widgets.pips_pager import PipsScrollButtonDisplayMode

from software.core.questions.utils import serialize_random_int_range, try_parse_random_int_range
from software.ui.helpers.qfluent_compat import install_tooltip_filters
from software.ui.widgets.no_wheel import NoWheelSlider
from software.core.questions.config import QuestionEntry
from software.app.config import DEFAULT_FILL_TEXT

from .constants import _get_entry_type_label
from .utils import _shorten_text, _apply_label_color, _bind_slider_input, build_entry_info_list
from .wizard_sections import WizardSectionsMixin, _TEXT_RANDOM_NONE, _get_segmented_route_key
from .psycho_config import BIAS_PRESET_CHOICES


# ---------------------------------------------------------------------------
# QuestionWizardDialog — 主对话框
# ---------------------------------------------------------------------------


def _color_with_alpha(color: QColor, alpha: int) -> QColor:
    copied = QColor(color)
    copied.setAlpha(max(0, min(255, int(alpha))))
    return copied


class WizardPipsDelegate(QStyledItemDelegate):
    """带 ItemViewToolTipDelegate 的分页点绘制。"""

    def __init__(self, parent: Optional[QAbstractItemView] = None):
        super().__init__(parent)
        self.hoveredRow = -1
        self.pressedRow = -1
        if parent is None:
            raise ValueError("WizardPipsDelegate 需要 QAbstractItemView 作为父对象")
        self._view_parent = parent
        self.tooltipDelegate = ItemViewToolTipDelegate(parent, 200, ItemViewToolTipType.LIST)
        self.tooltipDelegate.setToolTipDuration(1200)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        row = index.row()
        is_hover = row == self.hoveredRow
        is_pressed = row == self.pressedRow
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        question_number = row + 1

        center_x = option.rect.right() - 9
        center_y = option.rect.center().y()
        accent = QColor(themeColor())
        if isDarkTheme():
            idle_color = QColor(255, 255, 255, 150)
            hover_color = QColor(255, 255, 255, 218)
            hover_halo = QColor(255, 255, 255, 56)
            active_halo = _color_with_alpha(accent, 92)
            label_color = QColor(255, 255, 255, 235)
            active_label_color = QColor(255, 255, 255, 255)
            label_fill = QColor(255, 255, 255, 42)
            active_label_fill = _color_with_alpha(accent, 96)
        else:
            idle_color = QColor(0, 0, 0, 122)
            hover_color = QColor(0, 0, 0, 176)
            hover_halo = QColor(0, 0, 0, 34)
            active_halo = _color_with_alpha(accent, 70)
            label_color = QColor(73, 73, 73, 230)
            active_label_color = QColor(22, 22, 22, 255)
            label_fill = QColor(255, 255, 255, 236)
            active_label_fill = _color_with_alpha(accent, 72)

        if question_number % 5 == 0:
            badge_rect = QRectF(option.rect.x() + 1, option.rect.center().y() - 7, 14, 14)
            painter.setBrush(active_label_fill if is_selected else label_fill)
            painter.drawRoundedRect(badge_rect, 5, 5)
            painter.setPen(active_label_color if is_selected else label_color)
            number_font = QFont(painter.font())
            number_font.setPixelSize(10)
            number_font.setBold(True)
            painter.setFont(number_font)
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignCenter,
                str(question_number),
            )
            painter.setPen(Qt.PenStyle.NoPen)

        center_point = QPointF(center_x, center_y)
        if is_selected:
            painter.setBrush(active_halo)
            painter.drawEllipse(center_point, 8, 8)
            painter.setBrush(accent)
            painter.drawEllipse(center_point, 4.5, 4.5)
            painter.setBrush(QColor(255, 255, 255, 245))
            painter.drawEllipse(center_point, 1.6, 1.6)
        elif is_pressed or is_hover:
            painter.setBrush(hover_halo)
            painter.drawEllipse(center_point, 6.2, 6.2)
            painter.setBrush(hover_color)
            painter.drawEllipse(center_point, 3.6, 3.6)
        else:
            painter.setBrush(idle_color)
            painter.drawEllipse(center_point, 3.2, 3.2)
        painter.restore()

    def setPressedRow(self, row: int) -> None:
        self.pressedRow = row
        self._view_parent.viewport().update()

    def setHoveredRow(self, row: int) -> None:
        self.hoveredRow = row
        self._view_parent.viewport().update()

    def helpEvent(self, event, view, option, index):
        return self.tooltipDelegate.helpEvent(event, view, option, index)


class StableVerticalPipsPager(VerticalPipsPager):
    """稳定版竖向分页器：保留 PipsPager 行为，放大命中范围并接 ToolTipFilter 链路。"""

    _ARROW_STEP = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tooltip_texts: List[str] = []
        self._cell_width = 26
        self._dot_span = 18
        self._cell_gap = 10
        self.delegate = WizardPipsDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent; border: none;")
        self.setViewportMargins(0, 14, 0, 14)
        self._apply_grid_metrics()

    def _apply_grid_metrics(self) -> None:
        grid_size = QSize(self._cell_width, self._dot_span + self._cell_gap)
        self.setGridSize(grid_size)
        self.setFixedWidth(self._cell_width)
        for idx in range(self.count()):
            item = self.item(idx)
            if item is not None:
                item.setSizeHint(grid_size)
        self.adjustSize()

    def setSpacing(self, spacing: int) -> None:
        self._cell_gap = max(0, int(spacing))
        self._apply_grid_metrics()

    def spacing(self) -> int:
        return self._cell_gap

    def setToolTipTexts(self, texts: List[str]) -> None:
        self._tooltip_texts = [str(text or "").strip() for text in texts]
        for idx in range(self.count()):
            item = self.item(idx)
            if item is None:
                continue
            tip = self._tooltip_texts[idx] if idx < len(self._tooltip_texts) else f"第{idx + 1}题"
            item.setToolTip(tip)

    def setPageNumber(self, n: int):
        super().setPageNumber(n)
        self._apply_grid_metrics()
        if self._tooltip_texts:
            self.setToolTipTexts(self._tooltip_texts)

    def _setPressedItem(self, item) -> None:
        try:
            row = self.row(item)
        except RuntimeError:
            return
        if row < 0:
            return
        self.delegate.setPressedRow(row)
        self.setCurrentIndex(row)

    def _setHoveredItem(self, item) -> None:
        try:
            row = self.row(item)
        except RuntimeError:
            return
        self.delegate.setHoveredRow(row)

    def leaveEvent(self, e):
        self.delegate.setHoveredRow(-1)
        super().leaveEvent(e)

    def setCurrentIndex(self, index: int):
        if not 0 <= index < self.count():
            return
        try:
            item = self.item(index)
        except RuntimeError:
            return
        if item is None:
            return
        self.clearSelection()
        item.setSelected(False)
        self.currentIndexChanged.emit(index)
        QListWidget.setCurrentItem(self, item)
        self._updateScrollButtonVisibility()

    def scrollNext(self) -> None:
        self.setCurrentIndex(min(self.count() - 1, self.currentIndex() + self._ARROW_STEP))

    def scrollPrevious(self) -> None:
        self.setCurrentIndex(max(0, self.currentIndex() - self._ARROW_STEP))


class FloatingPagerShell(QWidget):
    """透明外壳：只负责把分页器摆在左侧空白带中间。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pager = StableVerticalPipsPager(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pager.setCursor(Qt.CursorShape.PointingHandCursor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        pager_width = self.pager.width()
        pager_height = min(self.height(), self.pager.height())
        self.pager.setGeometry(
            (self.width() - pager_width) // 2,
            max(0, (self.height() - pager_height) // 2),
            pager_width,
            pager_height,
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        rect = self.rect().adjusted(5, 4, -5, -4)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)

        if isDarkTheme():
            fill_color = QColor(24, 24, 24, 164)
            border_color = QColor(255, 255, 255, 34)
            rail_color = QColor(255, 255, 255, 42)
        else:
            fill_color = QColor(248, 249, 251, 238)
            border_color = QColor(0, 0, 0, 18)
            rail_color = QColor(0, 0, 0, 28)

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(QRectF(rect), rect.width() / 2, rect.width() / 2)

        if self.pager.count() > 1:
            line_pen = QPen(rail_color, 1)
            line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(line_pen)
            center_x = rect.center().x()
            painter.drawLine(
                QPointF(center_x, rect.top() + 16),
                QPointF(center_x, rect.bottom() - 16),
            )

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        local_y = event.position().toPoint().y() - self.pager.y()
        index = self._resolve_index_from_y(local_y)
        if index is not None:
            self.pager.setCurrentIndex(index)

    def _resolve_index_from_y(self, local_y: int) -> Optional[int]:
        if self.pager.count() <= 0:
            return None
        nearest_index = 0
        nearest_distance = None
        for idx in range(self.pager.count()):
            item = self.pager.item(idx)
            if item is None:
                continue
            rect = self.pager.visualItemRect(item)
            center_y = rect.center().y()
            distance = abs(local_y - center_y)
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_index = idx
        return nearest_index


class QuestionWizardDialog(WizardSectionsMixin, QDialog):
    """配置向导：用滑块快速设置权重/概率，编辑填空题答案。"""

    _QUESTION_INDEX_PROPERTY = "_wizard_question_index"

    TextEditsValue = Union[List[LineEdit], List[List[LineEdit]]]

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

    def _get_entry_info(self, idx: int) -> Dict[str, Any]:
        if 0 <= idx < len(self.info):
            info = self.info[idx]
            if isinstance(info, dict):
                return info
        return {}

    def _format_question_label(self, idx: int) -> str:
        info = self._get_entry_info(idx)
        qnum = str(info.get("num") or "").strip()
        return f"第{qnum or idx + 1}题"

    def _show_validation_error(self, message: str, idx: int, focus_widget: Optional[QWidget] = None) -> None:
        self._navigate_to_question(idx, animate=True)
        box = MessageBox("保存失败", message, self)
        box.yesButton.setText("知道了")
        box.cancelButton.hide()
        box.exec()
        if focus_widget is not None:
            QTimer.singleShot(0, focus_widget.setFocus)

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
        return True

    def accept(self) -> None:
        if not self._validate_random_integer_inputs():
            return
        super().accept()

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
        self.text_edit_map: Dict[int, QuestionWizardDialog.TextEditsValue] = {}
        self.ai_check_map: Dict[int, SwitchButton] = {}
        self.text_container_map: Dict[int, QWidget] = {}
        self.text_add_btn_map: Dict[int, PushButton] = {}
        self.text_random_mode_map: Dict[int, str] = {}
        self.text_random_name_check_map: Dict[int, CheckBox] = {}
        self.text_random_mobile_check_map: Dict[int, CheckBox] = {}
        self.text_random_id_card_check_map: Dict[int, CheckBox] = {}
        self.text_random_integer_check_map: Dict[int, CheckBox] = {}
        self.text_random_int_min_edit_map: Dict[int, LineEdit] = {}
        self.text_random_int_max_edit_map: Dict[int, LineEdit] = {}
        self.text_random_group_map: Dict[int, QButtonGroup] = {}
        self.multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]] = {}
        self.bias_preset_map: Dict[int, Any] = {}
        self.attached_select_slider_map: Dict[int, List[Dict[str, Any]]] = {}
        self.option_fill_edit_map: Dict[int, Dict[int, LineEdit]] = {}
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
            if _get_segmented_route_key(_master_seg) != "custom":
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

    def _build_navigation_shell(self, parent: QWidget) -> FloatingPagerShell:
        shell = FloatingPagerShell(parent)
        shell.pager.currentIndexChanged.connect(self._on_question_pager_changed)
        shell.raise_()
        return shell

    def _configure_navigation_pager(self, total: int) -> None:
        if self._question_pager is None:
            return
        normalized_total = max(1, int(total))
        visible_number = min(normalized_total, 11)
        if self._navigation_item_count == normalized_total:
            self._question_pager.setVisibleNumber(visible_number)
            self._question_pager.setToolTipTexts(self._build_navigation_tooltips())
            display_mode = (
                PipsScrollButtonDisplayMode.ON_HOVER
                if normalized_total > visible_number
                else PipsScrollButtonDisplayMode.NEVER
            )
            self._question_pager.setPreviousButtonDisplayMode(display_mode)
            self._question_pager.setNextButtonDisplayMode(display_mode)
            return
        self._navigation_item_count = normalized_total
        self._question_pager.blockSignals(True)
        self._question_pager.setPageNumber(normalized_total)
        self._question_pager.setVisibleNumber(visible_number)
        self._question_pager.blockSignals(False)
        self._question_pager.setToolTipTexts(self._build_navigation_tooltips())
        display_mode = (
            PipsScrollButtonDisplayMode.ON_HOVER
            if normalized_total > visible_number
            else PipsScrollButtonDisplayMode.NEVER
        )
        self._question_pager.setPreviousButtonDisplayMode(display_mode)
        self._question_pager.setNextButtonDisplayMode(display_mode)
        self._question_pager.preButton.setToolTip("上一题")
        self._question_pager.nextButton.setToolTip("下一题")
        install_tooltip_filters((self._question_pager.preButton, self._question_pager.nextButton))

    def _build_navigation_tooltips(self) -> List[str]:
        labels: List[str] = []
        for idx in range(len(self._question_cards)):
            qnum = str(self._get_entry_info(idx).get("num") or "").strip()
            labels.append(f"第{qnum or idx + 1}题")
        return labels

    def _update_navigation_pager_geometry(self) -> None:
        if self._question_shell is None or self._scroll_area is None:
            return
        scroll_geo = self._scroll_area.geometry()
        if self._question_pager is not None:
            total = max(1, len(self._question_cards))
            preferred_spacing = 12
            if total >= 10:
                preferred_spacing = 10
            if total >= 18:
                preferred_spacing = 8
            if total >= 28:
                preferred_spacing = 6
            available_height = max(96, scroll_geo.height() - 72)
            max_spacing = 0
            if total > 1:
                visible_total = max(1, min(total, self._question_pager.getVisibleNumber()))
                max_spacing = max(0, (available_height - 12 - visible_total * 18) // (visible_total - 1))
            spacing = min(preferred_spacing, max_spacing)
            self._question_pager.setSpacing(spacing)
            shell_height = min(available_height, max(92, self._question_pager.height() + 16))
        else:
            shell_height = max(92, min(scroll_geo.height() - 72, 144))
        shell_width = 30
        x = max(0, scroll_geo.left() + max(0, (self._navigation_lane_width - shell_width) // 2))
        y = scroll_geo.top() + max(12, (scroll_geo.height() - shell_height) // 2)
        self._question_shell.setGeometry(x, y, shell_width, shell_height)
        self._question_shell.raise_()

    def _on_question_pager_changed(self, question_idx: int) -> None:
        self._navigate_to_question(question_idx, animate=True)

    def _navigate_to_question(self, question_idx: int, animate: bool) -> None:
        total = len(self._question_cards)
        if total <= 0:
            self._current_question_idx = 0
            self._refresh_navigation_state(0)
            self._scroll_to_question(None, animate=False)
            return

        clamped = max(0, min(question_idx, total - 1))
        self._current_question_idx = clamped
        self._refresh_navigation_state(total)
        self._scroll_to_question(clamped, animate=animate)

    def _refresh_navigation_state(self, total: int) -> None:
        if self._question_pager is not None:
            self._question_pager.blockSignals(True)
            current = max(0, min(self._current_question_idx, max(total - 1, 0)))
            if self._question_pager.currentIndex() != current:
                self._question_pager.setCurrentIndex(current)
            self._question_pager.setEnabled(total > 1)
            self._question_pager.blockSignals(False)

    def _scroll_to_question(self, question_idx: Optional[int], animate: bool) -> None:
        if self._scroll_area is None or self._content_layout is None or self._content_container is None:
            return
        scroll_bar = self._scroll_area.verticalScrollBar()
        if question_idx is None or not (0 <= question_idx < len(self._question_cards)):
            scroll_bar.setValue(0)
            return
        card = self._question_cards[question_idx]
        target_value = max(0, min(card.y() - 12, scroll_bar.maximum()))
        if not animate:
            self._stop_scroll_animation()
            scroll_bar.setValue(target_value)
            return
        self._animate_scroll_to(target_value)

    def _animate_scroll_to(self, target_value: int) -> None:
        if self._scroll_area is None:
            return
        scroll_bar = self._scroll_area.verticalScrollBar()
        start_value = scroll_bar.value()
        if abs(target_value - start_value) <= 1:
            scroll_bar.setValue(target_value)
            return

        self._stop_scroll_animation()
        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
        curve.addCubicBezierSegment(QPointF(0.215, 0.61), QPointF(0.355, 1.0), QPointF(1.0, 1.0))

        self._scroll_animation = QPropertyAnimation(scroll_bar, b"value", self)
        self._scroll_animation.setStartValue(start_value)
        self._scroll_animation.setEndValue(target_value)
        self._scroll_animation.setDuration(self._resolve_scroll_duration(start_value, target_value))
        self._scroll_animation.setEasingCurve(curve)
        self._is_animating_scroll = True
        self._scroll_animation.finished.connect(self._on_scroll_animation_finished)
        self._scroll_animation.start()

    @staticmethod
    def _resolve_scroll_duration(start_value: int, target_value: int) -> int:
        distance = abs(int(target_value) - int(start_value))
        return max(160, min(420, 160 + int(distance * 0.11)))

    def _stop_scroll_animation(self) -> None:
        if self._scroll_animation is None:
            return
        try:
            self._scroll_animation.stop()
        except Exception:
            pass
        self._scroll_animation.deleteLater()
        self._scroll_animation = None
        self._is_animating_scroll = False

    def _on_scroll_animation_finished(self) -> None:
        self._is_animating_scroll = False
        if self._scroll_animation is not None:
            self._scroll_animation.deleteLater()
            self._scroll_animation = None
        self._sync_current_question_from_scroll()

    def _on_scroll_value_changed(self, _value: int) -> None:
        if self._is_animating_scroll:
            return
        self._sync_current_question_from_scroll()

    def _set_current_question_idx(self, question_idx: int) -> None:
        if not self._question_cards:
            self._current_question_idx = 0
            return
        clamped = max(0, min(int(question_idx), len(self._question_cards) - 1))
        if clamped == self._current_question_idx:
            return
        self._current_question_idx = clamped
        self._refresh_navigation_state(len(self._question_cards))

    def _register_question_card_interaction_targets(self, card: CardWidget, idx: int) -> None:
        widgets = [card, *card.findChildren(QWidget)]
        for widget in widgets:
            try:
                widget.setProperty(self._QUESTION_INDEX_PROPERTY, idx)
                widget.installEventFilter(self)
            except Exception:
                continue

    def eventFilter(self, watched, event):
        if event is not None and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
            QEvent.Type.Wheel,
        ):
            try:
                idx = watched.property(self._QUESTION_INDEX_PROPERTY)
            except Exception:
                idx = None
            if idx is not None:
                try:
                    self._set_current_question_idx(int(idx))
                except Exception:
                    pass
        return super().eventFilter(watched, event)

    def _resolve_current_question_idx_from_scroll(self) -> int:
        if self._scroll_area is None or not self._question_cards:
            return 0

        scroll_bar = self._scroll_area.verticalScrollBar()
        viewport_height = max(1, self._scroll_area.viewport().height())
        visible_top = int(scroll_bar.value())
        visible_bottom = visible_top + viewport_height

        best_idx = max(0, min(self._current_question_idx, len(self._question_cards) - 1))
        best_visible_height = -1

        # 以“当前视口内哪张卡片占得最多”为准，而不是盯着某个固定锚点。
        # 这样面对高矮差异很大的题目卡片时，不会因为第二张卡片刚冒头就过早切题。
        for idx, card in enumerate(self._question_cards):
            card_top = int(card.y())
            card_bottom = card_top + int(card.height())
            visible_height = min(card_bottom, visible_bottom) - max(card_top, visible_top)
            if visible_height <= 0:
                continue

            if visible_height > best_visible_height:
                best_visible_height = visible_height
                best_idx = idx
                continue

            if visible_height != best_visible_height:
                continue

            if idx == self._current_question_idx:
                best_idx = idx
                continue

            if best_idx == self._current_question_idx:
                continue

            current_anchor = visible_top + min(96, max(32, viewport_height // 3))
            best_distance = abs(int(self._question_cards[best_idx].y()) - current_anchor)
            candidate_distance = abs(card_top - current_anchor)
            if candidate_distance < best_distance:
                best_idx = idx

        return best_idx

    def _sync_current_question_from_scroll(self) -> None:
        if self._is_animating_scroll or self._scroll_area is None or not self._question_cards:
            return
        scroll_bar = self._scroll_area.verticalScrollBar()
        if scroll_bar.value() <= 2:
            self._set_current_question_idx(0)
            return
        if scroll_bar.value() >= max(0, scroll_bar.maximum() - 2):
            self._set_current_question_idx(len(self._question_cards) - 1)
            return
        current_idx = self._resolve_current_question_idx_from_scroll()
        self._set_current_question_idx(current_idx)

    # ------------------------------------------------------------------ #
    #  题目配置卡片                                                        #
    # ------------------------------------------------------------------ #

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

                text_label = BodyLabel(_shorten_text(select_text, 40), card)
                text_label.setFixedWidth(160)
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

    def reject(self) -> None:
        self._restore_entries()
        super().reject()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_navigation_pager_geometry()

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
        from software.core.questions.types.text import MULTI_TEXT_DELIMITER
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
        for idx, edit_map in self.option_fill_edit_map.items():
            if not edit_map:
                continue
            info = self._get_entry_info(idx)
            option_count = int(info.get("options") or 0)
            max_index = max(edit_map.keys()) if edit_map else -1
            normalized_count = max(option_count, max_index + 1, 0)
            values: List[Optional[str]] = [None] * normalized_count
            for option_index, edit in edit_map.items():
                text = edit.text().strip()
                if 0 <= option_index < normalized_count:
                    values[option_index] = text or None
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
                    weights = [1] * len(weights)
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
                result[idx] = [_get_segmented_route_key(s) for s in seg]
            else:
                result[idx] = _get_segmented_route_key(seg)
        return result

