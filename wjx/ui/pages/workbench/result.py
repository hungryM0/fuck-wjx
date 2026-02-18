"""结果分析页面 - 展示作答统计与信效度分析"""

import os
import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, QObject, Signal, QSettings
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    TitleLabel,
    BodyLabel,
    CaptionLabel,
    StrongBodyLabel,
    SimpleCardWidget,
    PushButton,
    ProgressBar,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
    ComboBox,
    isDarkTheme,
)

from wjx.core.stats.collector import stats_collector
from wjx.core.stats.models import SurveyStats, QuestionStats
from wjx.core.stats.persistence import save_stats, list_stats_files, load_stats, _ensure_stats_dir
from wjx.core.stats.raw_storage import raw_data_storage
from wjx.core.stats.analysis import AnalysisResult, run_analysis
from wjx.utils.logging.log_utils import log_suppressed_exception


# ── 题型中文映射 ──────────────────────────────────────────────
_TYPE_LABELS = {
    "single": "单选题",
    "multiple": "多选题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "score": "评分题",
    "text": "填空题",
    "dropdown": "下拉题",
    "slider": "滑块题",
}


# ── 后台分析 Worker ──────────────────────────────────────────

class _AnalysisWorker(QObject):
    """后台线程中执行统计分析，避免阻塞 GUI"""
    finished = Signal(object)  # AnalysisResult

    def __init__(self, jsonl_path: str) -> None:
        super().__init__()
        self._path = jsonl_path

    def run(self) -> None:
        result = run_analysis(self._path)
        self.finished.emit(result)


# ── 辅助组件 ──────────────────────────────────────────────────

class _Divider(QFrame):
    """1px 水平分割线"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(128,128,128,0.15); border: none;")


class _VerticalDivider(QFrame):
    """1px 垂直分割线"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedWidth(1)
        self.setStyleSheet("background: rgba(128,128,128,0.15); border: none;")


class _StatNumberWidget(QWidget):
    """概览区的单个统计数字块"""

    def __init__(self, title: str, value: str = "0",
                 color: Optional[str] = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._title_label = CaptionLabel(title, self)
        self._title_label.setStyleSheet("color: rgba(128,128,128,0.9);")

        self._value_label = TitleLabel(value, self)
        if color:
            self._value_label.setStyleSheet(
                f"font-size: 28px; font-weight: 700; color: {color};"
            )
        else:
            self._value_label.setStyleSheet("font-size: 28px; font-weight: 700;")

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)

    def setValue(self, text: str) -> None:
        self._value_label.setText(text)

    def setColor(self, color: str) -> None:
        self._value_label.setStyleSheet(
            f"font-size: 28px; font-weight: 700; color: {color};"
        )


class _BarRow(QWidget):
    """选项统计的一行：名称 | 进度条 | 次数 / 占比"""

    def __init__(self, name: str, count: int, percentage: float, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        # 选项名（固定宽度，右对齐）
        name_label = BodyLabel(name, self)
        name_label.setFixedWidth(120)
        name_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(name_label)

        # 进度条
        bar = ProgressBar(self)
        bar.setValue(min(100, int(percentage)))
        bar.setFixedHeight(14)
        bar.setMinimumWidth(80)
        h.addWidget(bar, 1)

        # 次数 + 占比
        stat_text = f"{count} 次  ({percentage:.1f}%)"
        stat_label = CaptionLabel(stat_text, self)
        stat_label.setFixedWidth(120)
        stat_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(stat_label)


class _TextAnswerRow(QWidget):
    """填空题答案行：答案文本 + 次数"""

    def __init__(self, text: str, count: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)

        h = QHBoxLayout(self)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(12)

        display = text[:80] + "…" if len(text) > 80 else text
        text_label = BodyLabel(display, self)
        h.addWidget(text_label, 1)

        count_label = CaptionLabel(f"× {count}", self)
        count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        count_label.setFixedWidth(60)
        h.addWidget(count_label)


class _MatrixCell(QWidget):
    """矩阵题热力格子"""

    def __init__(self, value: int, max_val: int, parent=None):
        super().__init__(parent)
        self._value = value
        self._max_val = max(max_val, 1)
        self.setFixedSize(48, 32)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ratio = self._value / self._max_val if self._max_val > 0 else 0

        if isDarkTheme():
            bg = QColor(0, 120, 212, int(30 + ratio * 180))
            text_color = QColor(255, 255, 255)
        else:
            bg = QColor(0, 120, 212, int(20 + ratio * 180))
            text_color = QColor(0, 0, 0) if ratio < 0.5 else QColor(255, 255, 255)

        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)

        painter.setPen(QPen(text_color))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._value))
        painter.end()


# ── 信效度指标组件 ──────────────────────────────────────────────

class _MetricWidget(QWidget):
    """信效度分析卡片中的单个指标展示

    显示结构：
        指标名
        数值（带颜色）
        解释文字
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._title_label = CaptionLabel(title, self)
        self._title_label.setStyleSheet("color: rgba(128,128,128,0.9);")

        self._value_label = StrongBodyLabel("--", self)
        self._value_label.setStyleSheet("font-size: 20px;")

        self._desc_label = CaptionLabel("", self)
        self._desc_label.setStyleSheet("color: rgba(128,128,128,0.7);")
        self._desc_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)
        layout.addWidget(self._desc_label)

    def set_value(self, text: str, color: str, description: str) -> None:
        self._value_label.setText(text)
        self._value_label.setStyleSheet(f"font-size: 20px; color: {color};")
        self._desc_label.setText(description)

    def set_unavailable(self, reason: str = "") -> None:
        self._value_label.setText("--")
        self._value_label.setStyleSheet("font-size: 20px; color: rgba(128,128,128,0.5);")
        self._desc_label.setText(reason)


# ── 主页面 ────────────────────────────────────────────────────

class ResultPage(QWidget):
    """结果分析页面：展示作答统计与信效度分析"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._current_stats: Optional[SurveyStats] = None
        self._question_cards: list = []
        self._analysis_thread: Optional[QThread] = None
        self._analysis_worker: Optional[_AnalysisWorker] = None
        self._last_infobar_submission_count: int = -1  # 记录上次显示 InfoBar 时的提交次数
        self._build_ui()
        self._bind_events()
        self._connect_stats_signal()

    # ── 界面搭建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 12)
        root.setSpacing(16)

        # ─── 顶部标题栏 ───
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(SubtitleLabel("结果分析", self))
        header.addStretch(1)

        self.history_combo = ComboBox(self)
        self.history_combo.setPlaceholderText("选择历史统计…")
        self.history_combo.setMinimumWidth(260)
        header.addWidget(self.history_combo)

        self.open_folder_btn = PushButton("打开统计文件夹", self, FluentIcon.FOLDER)
        header.addWidget(self.open_folder_btn)

        self.export_btn = PushButton("导出统计", self, FluentIcon.SAVE)
        header.addWidget(self.export_btn)
        root.addLayout(header)

        # ─── 信效度分析卡片 ───
        self._analysis_card = self._build_analysis_card()
        root.addWidget(self._analysis_card)

        # ─── 滚动区域（题目卡片） ───
        self._question_list_card = SimpleCardWidget(self)
        question_list_card_layout = QVBoxLayout(self._question_list_card)
        question_list_card_layout.setContentsMargins(0, 0, 0, 0)
        question_list_card_layout.setSpacing(0)

        scroll = ScrollArea(self._question_list_card)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; border: none; }"
        )

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(12)
        scroll.setWidget(self._scroll_content)
        question_list_card_layout.addWidget(scroll)
        root.addWidget(self._question_list_card, 1)

        # 初始占位提示
        self._show_placeholder()

    def _build_analysis_card(self) -> SimpleCardWidget:
        """信效度分析卡片：Cronbach's Alpha / KMO / Bartlett"""
        card = SimpleCardWidget(self)
        v = QVBoxLayout(card)
        v.setContentsMargins(28, 16, 28, 16)
        v.setSpacing(12)

        # 标题行
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = StrongBodyLabel("信效度分析", card)
        title_row.addWidget(title_label)

        analysis_tip_label = CaptionLabel("⚠ 仅供参考，具体以 SPSS 分析结果为准", card)
        analysis_tip_label.setStyleSheet("color: #b45309; font-size: 13px; font-weight: 600;")
        title_row.addWidget(analysis_tip_label)

        self._analysis_status_label = CaptionLabel("", card)
        self._analysis_status_label.setStyleSheet("color: rgba(128,128,128,0.6);")
        title_row.addWidget(self._analysis_status_label)
        title_row.addStretch(1)

        # 样本信息
        self._analysis_sample_label = CaptionLabel("", card)
        self._analysis_sample_label.setStyleSheet("color: rgba(128,128,128,0.7);")
        title_row.addWidget(self._analysis_sample_label)

        v.addLayout(title_row)

        self._analysis_notice_label = CaptionLabel("", card)
        self._analysis_notice_label.setStyleSheet("color: rgba(128,128,128,0.6);")
        self._analysis_notice_label.setVisible(False)
        v.addWidget(self._analysis_notice_label)

        v.addWidget(_Divider(card))

        # 三个指标水平排列
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(18)

        self._metric_alpha = _MetricWidget("Cronbach's α系数", card)
        self._metric_kmo = _MetricWidget("KMO 检验", card)
        self._metric_bartlett = _MetricWidget("Bartlett 球形检验", card)

        metrics_layout.addWidget(self._metric_alpha, 1)
        metrics_layout.addWidget(_VerticalDivider(card))
        metrics_layout.addWidget(self._metric_kmo, 1)
        metrics_layout.addWidget(_VerticalDivider(card))
        metrics_layout.addWidget(self._metric_bartlett, 1)

        v.addLayout(metrics_layout)

        # 初始状态
        self._reset_analysis_card()

        return card

    def _reset_analysis_card(self) -> None:
        """重置信效度分析卡片到初始状态"""
        self._analysis_status_label.setText("")
        self._analysis_sample_label.setText("")
        self._analysis_notice_label.setText("")
        self._analysis_notice_label.setVisible(False)
        self._metric_alpha.set_unavailable("等待数据...")
        self._metric_kmo.set_unavailable("等待数据...")
        self._metric_bartlett.set_unavailable("等待数据...")

    def _show_analysis_notice(self, text: str) -> None:
        self._analysis_status_label.setText("")
        self._analysis_notice_label.setText(text)
        self._analysis_notice_label.setVisible(True)

    def _hide_analysis_notice(self) -> None:
        self._analysis_notice_label.setText("")
        self._analysis_notice_label.setVisible(False)

    # ── 题目卡片构造 ──────────────────────────────────────────

    def _build_question_card(self, q: QuestionStats) -> SimpleCardWidget:
        """为单道题构建统计卡片"""
        card = SimpleCardWidget(self)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        # ─── 标题行 ───
        type_text = _TYPE_LABELS.get(q.question_type, q.question_type)
        title = f"第 {q.question_num} 题 ({type_text})"

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = StrongBodyLabel(title, card)
        title_row.addWidget(title_label)
        title_row.addStretch(1)
        v.addLayout(title_row)

        # 题目内容单独展示，避免与标题挤在一行被截断
        if q.question_title:
            question_text_label = BodyLabel(str(q.question_title), card)
            question_text_label.setWordWrap(True)
            question_text_label.setStyleSheet("color: rgba(128,128,128,0.85);")
            v.addWidget(question_text_label)

        v.addWidget(_Divider(card))

        # ─── 内容区 ───
        if q.question_type in ("single", "multiple", "scale", "score", "dropdown"):
            self._add_option_bars(v, q, card)
        elif q.question_type == "slider":
            self._add_slider_bars(v, q, card)
        elif q.question_type == "matrix":
            self._add_matrix_grid(v, q, card)
        elif q.question_type == "text":
            self._add_text_answers(v, q, card)
        else:
            v.addWidget(BodyLabel(f"暂不支持的题型: {q.question_type}", card))

        return card

    def _add_option_bars(self, layout: QVBoxLayout,
                         q: QuestionStats, parent: QWidget) -> None:
        """选择类题目——选项柱状行"""
        # 使用配置的选项总数来显示所有选项，即使某些未被选择
        option_count = q.option_count if q.option_count else max(q.options.keys(), default=0) + 1

        for idx in range(option_count):
            opt = q.options.get(idx)
            count = opt.count if opt else 0
            # 优先使用选项文本，如果没有则根据题型决定显示格式
            if opt and opt.option_text:
                name = opt.option_text
            elif q.question_type == "scale":
                # 量表题：直接显示索引值（0、1、2...），不加1
                name = f"选项 {idx}"
            else:
                # 其他题型：显示 idx + 1（选项 1、选项 2...）
                name = f"选项 {idx + 1}"
            pct = q.get_option_percentage(idx)
            layout.addWidget(_BarRow(name, count, pct, parent))

    def _add_slider_bars(self, layout: QVBoxLayout,
                         q: QuestionStats, parent: QWidget) -> None:
        """滑块题——按值排序展示"""
        # 滑块题由于值范围不固定，只显示有统计数据的值
        sorted_opts = sorted(q.options.items(), key=lambda x: x[0])
        for idx, opt in sorted_opts:
            name = f"值 {idx}"
            pct = q.get_option_percentage(idx)
            layout.addWidget(_BarRow(name, opt.count, pct, parent))

    def _add_matrix_grid(self, layout: QVBoxLayout,
                         q: QuestionStats, parent: QWidget) -> None:
        """矩阵题——热力网格"""
        # 使用配置的行列数来显示完整矩阵，即使某些单元格未被选择
        if q.matrix_rows is None or q.matrix_cols is None:
            # 降级：从实际数据中推断（尽可能智能）
            if not q.rows:
                layout.addWidget(BodyLabel("暂无矩阵数据", parent))
                return

            # 推断行数：找到最大行索引+1
            max_row = max(q.rows.keys())
            rows = list(range(max_row + 1))

            # 推断列数：从所有行中找到最大列索引+1
            all_cols = set()
            for row_data in q.rows.values():
                all_cols.update(row_data.keys())
            if not all_cols:
                layout.addWidget(BodyLabel("矩阵数据不完整", parent))
                return
            max_col = max(all_cols)
            cols = list(range(max_col + 1))
        else:
            # 使用配置元数据
            rows = list(range(q.matrix_rows))
            cols = list(range(q.matrix_cols))

        # 找最大值用于调色（包括0计数）
        max_val = 1
        if q.rows:
            max_val = max(
                (cnt for rd in q.rows.values() for cnt in rd.values()), default=1
            )

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setContentsMargins(0, 4, 0, 4)

        # 列头
        grid.addWidget(QWidget(), 0, 0)  # 左上角空白
        for ci, c in enumerate(cols):
            h = CaptionLabel(f"列 {c + 1}", parent)
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(h, 0, ci + 1)

        # 数据行
        for ri, r in enumerate(rows):
            row_label = CaptionLabel(f"行 {r + 1}", parent)
            row_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row_label.setFixedWidth(48)
            grid.addWidget(row_label, ri + 1, 0)

            # 获取该行的数据（如果存在）
            col_data = q.rows.get(r, {}) if q.rows else {}

            for ci, c in enumerate(cols):
                cnt = col_data.get(c, 0)
                cell = _MatrixCell(cnt, max_val, parent)
                grid.addWidget(cell, ri + 1, ci + 1)

        layout.addLayout(grid)

    def _add_text_answers(self, layout: QVBoxLayout,
                          q: QuestionStats, parent: QWidget) -> None:
        """填空题——答案列表"""
        if not q.text_answers:
            layout.addWidget(BodyLabel("暂无填空数据", parent))
            return

        sorted_ans = sorted(q.text_answers.items(), key=lambda x: -x[1])
        for text, count in sorted_ans[:30]:  # 最多 30 条
            layout.addWidget(_TextAnswerRow(text, count, parent))

        if len(sorted_ans) > 30:
            more = CaptionLabel(f"…还有 {len(sorted_ans) - 30} 条答案未显示", parent)
            more.setStyleSheet("color: rgba(128,128,128,0.7);")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(more)

    # ── 占位与刷新逻辑 ────────────────────────────────────────

    def _show_placeholder(self) -> None:
        holder = QWidget(self._scroll_content)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(16, 48, 16, 48)
        holder_layout.setSpacing(8)

        title = StrongBodyLabel("暂无统计数据", holder)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc = BodyLabel("开始执行任务后将在此显示统计信息", holder)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: rgba(128,128,128,0.62);")

        holder_layout.addWidget(title)
        holder_layout.addWidget(desc)

        self._scroll_layout.addStretch(1)
        self._scroll_layout.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)
        self._scroll_layout.addStretch(1)

    def _clear_scroll(self) -> None:
        while self._scroll_layout.count() > 0:
            item = self._scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._question_cards.clear()

    # ── 事件绑定 ──────────────────────────────────────────────

    def _bind_events(self) -> None:
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        self.export_btn.clicked.connect(self._on_export)
        self.history_combo.currentIndexChanged.connect(self._on_history_selected)

    def _connect_stats_signal(self) -> None:
        """连接统计更新信号（强制 QueuedConnection 确保在主线程执行刷新）"""
        stats_collector.signals.stats_updated.connect(
            self._on_stats_updated, Qt.ConnectionType.QueuedConnection
        )

    def _on_stats_updated(self) -> None:
        """统计数据更新时的回调（每完成1份问卷后触发）"""
        # 只有在查看"当前会话"时才自动刷新
        if self.history_combo.currentIndex() <= 0:
            self.refresh_stats()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_history_list()
        if self.history_combo.currentIndex() <= 0:
            self.refresh_stats()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)

    # ── 数据刷新 ──────────────────────────────────────────────

    def refresh_stats(self) -> None:
        stats = stats_collector.get_current_stats()
        self._current_stats = stats

        # 当前会话为空：清空历史残留并显示占位
        if stats is None:
            self._clear_scroll()
            self._show_placeholder()
            self._reset_analysis_card()
            self._show_analysis_notice("当前会话暂无数据")
            return

        self._update_question_cards(stats)

        # 当前会话还没产生题目统计：同样重置分析区，避免残留历史结果
        if not stats.questions:
            self._reset_analysis_card()
            self._analysis_status_label.setText("当前会话暂无原始数据")
            return

        self._trigger_analysis()

    def _update_question_cards(self, stats: SurveyStats) -> None:
        self._clear_scroll()

        if not stats.questions:
            self._show_placeholder()
            return

        for q_num in sorted(stats.questions.keys()):
            card = self._build_question_card(stats.questions[q_num])
            self._question_cards.append(card)
            self._scroll_layout.addWidget(card)

        self._scroll_layout.addStretch(1)

    # ── 信效度分析（异步） ────────────────────────────────────

    def _trigger_analysis(self) -> None:
        """触发后台信效度分析"""
        self._hide_analysis_notice()
        jsonl_path = raw_data_storage.get_file_path()
        if not jsonl_path or not os.path.exists(jsonl_path):
            self._reset_analysis_card()
            self._analysis_status_label.setText("暂无原始数据")
            return

        # 若分析仍在执行，直接返回，避免主线程同步等待导致卡顿
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            self._analysis_status_label.setText("分析中...")
            self._analysis_status_label.setStyleSheet("color: #f59e0b;")
            return

        self._cleanup_analysis_thread()

        self._analysis_status_label.setText("分析中...")
        self._analysis_status_label.setStyleSheet("color: #f59e0b;")

        # 在后台线程执行分析
        self._analysis_thread = QThread()
        self._analysis_worker = _AnalysisWorker(jsonl_path)
        self._analysis_worker.moveToThread(self._analysis_thread)

        self._analysis_thread.started.connect(self._analysis_worker.run)
        self._analysis_worker.finished.connect(self._on_analysis_finished)
        self._analysis_worker.finished.connect(self._analysis_thread.quit)

        self._analysis_thread.start()

    def _cleanup_analysis_thread(self) -> None:
        """清理旧的分析线程"""
        if self._analysis_thread is not None:
            try:
                self._analysis_thread.finished.connect(self._analysis_thread.deleteLater)
            except Exception:
                pass
            if self._analysis_thread.isRunning():
                self._analysis_thread.quit()
        self._analysis_thread = None
        self._analysis_worker = None

    def _on_analysis_finished(self, result: AnalysisResult) -> None:
        """分析完成的回调（在主线程执行）"""
        self._hide_analysis_notice()
        if result.error:
            self._analysis_status_label.setText(result.error)
            self._analysis_status_label.setStyleSheet("color: rgba(128,128,128,0.6);")
            self._metric_alpha.set_unavailable(result.error)
            self._metric_kmo.set_unavailable(result.error)
            self._metric_bartlett.set_unavailable(result.error)
            return

        self._analysis_status_label.setText("")
        self._analysis_sample_label.setText(
            f"{result.sample_count} 份样本 / {result.item_count} 道题"
        )

        # 将分析结果保存到当前统计数据中
        self._save_analysis_to_stats(result)

        # 静默更新，不再弹出提示（避免每提交一份就弹一次）
        # 用户可以在需要时手动点击"导出统计"按钮

        # ── Cronbach's Alpha ──
        if result.cronbach_alpha is not None:
            alpha = result.cronbach_alpha
            if alpha >= 0.9:
                color, desc = "#22c55e", "优秀"
            elif alpha >= 0.8:
                color, desc = "#22c55e", "良好"
            elif alpha >= 0.7:
                color, desc = "#f59e0b", "可接受"
            elif alpha >= 0.6:
                color, desc = "#f59e0b", "勉强可接受"
            else:
                color, desc = "#ef4444", "较差"

            self._metric_alpha.set_value(f"{alpha:.3f}", color, desc)
        else:
            self._metric_alpha.set_unavailable("数据不足，无法计算")

        # ── KMO ──
        if result.kmo_value is not None:
            kmo = result.kmo_value
            if kmo >= 0.9:
                color, desc = "#22c55e", "非常适合因子分析"
            elif kmo >= 0.8:
                color, desc = "#22c55e", "适合因子分析"
            elif kmo >= 0.7:
                color, desc = "#3b82f6", "中等适合"
            elif kmo >= 0.6:
                color, desc = "#f59e0b", "勉强适合"
            else:
                color, desc = "#ef4444", "不适合因子分析"

            self._metric_kmo.set_value(f"{kmo:.3f}", color, desc)
        else:
            self._metric_kmo.set_unavailable("数据不足，无法计算")

        # ── Bartlett ──
        if result.bartlett_p is not None:
            p = result.bartlett_p
            chi2 = result.bartlett_chi2

            if p < 0.001:
                color, desc = "#22c55e", "显著（适合因子分析）"
                p_text = "< 0.001"
            elif p < 0.01:
                color, desc = "#22c55e", "显著（适合因子分析）"
                p_text = f"{p:.4f}"
            elif p < 0.05:
                color, desc = "#f59e0b", "边缘显著"
                p_text = f"{p:.4f}"
            else:
                color, desc = "#ef4444", "不显著（不适合因子分析）"
                p_text = f"{p:.4f}"

            display_text = f"p = {p_text}"
            self._metric_bartlett.set_value(display_text, color, desc)
        else:
            self._metric_bartlett.set_unavailable("数据不足，无法计算")

    def _save_analysis_to_stats(self, result: AnalysisResult) -> None:
        """将信效度分析结果保存到统计数据中

        Args:
            result: 分析结果对象
        """
        # 获取当前统计数据（优先使用当前显示的，否则从收集器获取）
        stats = self._current_stats or stats_collector.get_current_stats()
        if stats is None:
            return

        # 构建信效度分析结果字典
        reliability_validity = {
            "cronbach_alpha": result.cronbach_alpha,
            "kmo_value": result.kmo_value,
            "bartlett_chi2": result.bartlett_chi2,
            "bartlett_p": result.bartlett_p,
            "sample_count": result.sample_count,
            "item_count": result.item_count,
            "item_columns": result.item_columns,
            "error": result.error,
        }

        # 保存到统计数据对象
        stats.reliability_validity = reliability_validity

        # 如果是当前运行的统计，也更新收集器中的数据
        if self._current_stats is None:
            current = stats_collector.get_current_stats()
            if current is not None:
                current.reliability_validity = reliability_validity

    def _display_saved_analysis(self, reliability_validity: dict) -> None:
        """显示已保存的信效度分析结果

        Args:
            reliability_validity: 从统计文件加载的信效度分析结果字典
        """
        self._hide_analysis_notice()

        # 如果有错误信息，显示错误
        error = reliability_validity.get("error")
        if error:
            self._analysis_status_label.setText(error)
            self._analysis_status_label.setStyleSheet("color: rgba(128,128,128,0.6);")
            self._metric_alpha.set_unavailable(error)
            self._metric_kmo.set_unavailable(error)
            self._metric_bartlett.set_unavailable(error)
            return

        # 显示样本和题目数
        sample_count = reliability_validity.get("sample_count", 0)
        item_count = reliability_validity.get("item_count", 0)
        self._analysis_status_label.setText("")
        self._analysis_sample_label.setText(
            f"{sample_count} 份样本 / {item_count} 道题"
        )

        # ── Cronbach's Alpha ──
        alpha = reliability_validity.get("cronbach_alpha")
        if alpha is not None:
            if alpha >= 0.9:
                color, desc = "#22c55e", "优秀"
            elif alpha >= 0.8:
                color, desc = "#22c55e", "良好"
            elif alpha >= 0.7:
                color, desc = "#f59e0b", "可接受"
            elif alpha >= 0.6:
                color, desc = "#f59e0b", "勉强可接受"
            else:
                color, desc = "#ef4444", "较差"

            self._metric_alpha.set_value(f"{alpha:.3f}", color, desc)
        else:
            self._metric_alpha.set_unavailable("数据不足，无法计算")

        # ── KMO ──
        kmo = reliability_validity.get("kmo_value")
        if kmo is not None:
            if kmo >= 0.9:
                color, desc = "#22c55e", "非常适合因子分析"
            elif kmo >= 0.8:
                color, desc = "#22c55e", "适合因子分析"
            elif kmo >= 0.7:
                color, desc = "#3b82f6", "中等适合"
            elif kmo >= 0.6:
                color, desc = "#f59e0b", "勉强适合"
            else:
                color, desc = "#ef4444", "不适合因子分析"

            self._metric_kmo.set_value(f"{kmo:.3f}", color, desc)
        else:
            self._metric_kmo.set_unavailable("数据不足，无法计算")

        # ── Bartlett ──
        p = reliability_validity.get("bartlett_p")
        chi2 = reliability_validity.get("bartlett_chi2")
        if p is not None:
            if p < 0.001:
                color, desc = "#22c55e", "显著（适合因子分析）"
                p_text = "< 0.001"
            elif p < 0.01:
                color, desc = "#22c55e", "显著（适合因子分析）"
                p_text = f"{p:.4f}"
            elif p < 0.05:
                color, desc = "#f59e0b", "边缘显著"
                p_text = f"{p:.4f}"
            else:
                color, desc = "#ef4444", "不显著（不适合因子分析）"
                p_text = f"{p:.4f}"

            display_text = f"p = {p_text}"
            self._metric_bartlett.set_value(display_text, color, desc)
        else:
            self._metric_bartlett.set_unavailable("数据不足，无法计算")

    # ── 导出 ──────────────────────────────────────────────────

    def _on_open_folder(self) -> None:
        """打开统计文件夹"""
        try:
            stats_dir = _ensure_stats_dir()
            os.startfile(stats_dir)
        except Exception as exc:
            InfoBar.error(
                "", f"无法打开统计文件夹: {exc}",
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=3000,
            )

    def _on_export(self) -> None:
        stats = self._current_stats or stats_collector.get_current_stats()
        if stats is None:
            InfoBar.warning(
                "", "暂无统计数据可导出",
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=2000,
            )
            return
        try:
            path = save_stats(stats)
            # 检查是否包含信效度数据，优化提示信息
            has_reliability = stats.reliability_validity is not None
            message = f"统计已导出: {os.path.basename(path)}"
            if has_reliability:
                message += " (含信效度分析)"
            
            InfoBar.success(
                "", message,
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=3000,
            )
            self._load_history_list()
        except Exception as exc:
            InfoBar.error(
                "", f"导出失败: {exc}",
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=3000,
            )

    # ── 历史记录 ──────────────────────────────────────────────

    def _load_history_list(self) -> None:
        try:
            self.history_combo.currentIndexChanged.disconnect(self._on_history_selected)
        except Exception as exc:
            log_suppressed_exception(
                "ResultPage._load_history_list: disconnect currentIndexChanged failed",
                exc,
                level=logging.WARNING,
            )

        try:
            self.history_combo.clear()
            self.history_combo.addItem("当前会话")
            self.history_combo.setItemData(0, None)

            for idx, path in enumerate(list_stats_files()[:20], start=1):
                self.history_combo.addItem(os.path.basename(path))
                self.history_combo.setItemData(idx, path)
        finally:
            self.history_combo.currentIndexChanged.connect(self._on_history_selected)

    def _on_history_selected(self, index: int) -> None:
        if index <= 0:
            self.refresh_stats()
            return

        path = self.history_combo.itemData(index)
        if not path:
            InfoBar.warning(
                "", f"未找到文件路径 (index={index})",
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=2000,
            )
            return

        try:
            stats = load_stats(path)
            if not stats or not hasattr(stats, "total_submissions"):
                InfoBar.warning(
                    "", "文件加载失败或数据为空",
                    parent=self.window(),
                    position=InfoBarPosition.TOP, duration=2000,
                )
                return

            self._current_stats = stats
            self._update_question_cards(stats)

            # 如果历史数据中保存了信效度分析结果，则显示
            if stats.reliability_validity:
                self._display_saved_analysis(stats.reliability_validity)
            else:
                # 历史数据没有信效度分析结果
                self._reset_analysis_card()
                self._analysis_status_label.setText("该统计文件未包含信效度分析结果")
        except Exception as exc:
            InfoBar.error(
                "", f"加载失败: {str(exc)[:50]}",
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=3000,
            )

