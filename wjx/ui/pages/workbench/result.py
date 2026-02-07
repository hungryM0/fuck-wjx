"""结果页面 - 展示作答统计"""

import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSizePolicy,
    QFrame,
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
from wjx.core.stats.persistence import save_stats, list_stats_files, load_stats


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


# ── 辅助组件 ──────────────────────────────────────────────────

class _Divider(QFrame):
    """1px 水平分割线"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
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
        name_label.setToolTip(name)
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
        text_label.setToolTip(text)
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
        self.setToolTip(f"{value} 次")

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


# ── 主页面 ────────────────────────────────────────────────────

class ResultPage(QWidget):
    """结果页面：展示作答统计信息"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_stats: Optional[SurveyStats] = None
        self._question_cards: list = []
        self._build_ui()
        self._bind_events()
        self._setup_refresh_timer()

    # ── 界面搭建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 12)
        root.setSpacing(16)

        # ─── 顶部标题栏 ───
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(SubtitleLabel("执行结果与统计", self))
        header.addStretch(1)

        self.history_combo = ComboBox(self)
        self.history_combo.setPlaceholderText("选择历史统计…")
        self.history_combo.setMinimumWidth(260)
        header.addWidget(self.history_combo)

        self.export_btn = PushButton("导出统计", self, FluentIcon.SAVE)
        header.addWidget(self.export_btn)
        root.addLayout(header)

        # ─── 概览卡片 ───
        self._overview_card = self._build_overview_card()
        root.addWidget(self._overview_card)

        # ─── 滚动区域（题目卡片） ───
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(12)
        scroll.setWidget(self._scroll_content)
        root.addWidget(scroll, 1)

        # 初始占位提示
        self._show_placeholder()

    def _build_overview_card(self) -> SimpleCardWidget:
        """概览卡片：四个数字指标水平排列"""
        card = SimpleCardWidget(self)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(48)

        self._stat_total = _StatNumberWidget("总提交", "0")
        self._stat_success = _StatNumberWidget("成功", "0", "#22c55e")
        self._stat_fail = _StatNumberWidget("失败", "0", "#ef4444")
        self._stat_rate = _StatNumberWidget("成功率", "0%")

        layout.addWidget(self._stat_total)
        layout.addWidget(self._stat_success)
        layout.addWidget(self._stat_fail)
        layout.addWidget(self._stat_rate)
        layout.addStretch(1)
        return card

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
        if q.question_title:
            title += f"：{q.question_title[:60]}"

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = StrongBodyLabel(title, card)
        title_row.addWidget(title_label)
        title_row.addStretch(1)

        # 总作答次数小徽标
        resp_label = CaptionLabel(f"共 {q.total_responses} 次作答", card)
        resp_label.setStyleSheet("color: rgba(128,128,128,0.75);")
        title_row.addWidget(resp_label)
        v.addLayout(title_row)

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
            name = (opt.option_text if opt and opt.option_text else f"选项 {idx + 1}")
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
        p = BodyLabel("暂无统计数据，开始执行任务后将在此显示统计信息", self)
        p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p.setStyleSheet("color: rgba(128,128,128,0.6); padding: 40px 0;")
        self._scroll_layout.addWidget(p)
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
        self.export_btn.clicked.connect(self._on_export)
        self.history_combo.currentIndexChanged.connect(self._on_history_selected)

    def _setup_refresh_timer(self) -> None:
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._auto_refresh)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_history_list()
        if self.history_combo.currentIndex() <= 0:
            self.refresh_stats()
        self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._refresh_timer.stop()

    def _auto_refresh(self) -> None:
        if self.history_combo.currentIndex() <= 0:
            self.refresh_stats()

    # ── 数据刷新 ──────────────────────────────────────────────

    def refresh_stats(self) -> None:
        stats = stats_collector.get_current_stats()
        if stats is None:
            return
        self._current_stats = stats
        self._update_overview(stats)
        self._update_question_cards(stats)

    def _update_overview(self, stats: SurveyStats) -> None:
        total = stats.total_submissions + stats.failed_submissions
        success = stats.total_submissions
        fail = stats.failed_submissions
        rate = (success / total * 100) if total > 0 else 0

        self._stat_total.setValue(str(total))
        self._stat_success.setValue(str(success))
        self._stat_fail.setValue(str(fail))
        self._stat_rate.setValue(f"{rate:.1f}%")

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

    # ── 导出 ──────────────────────────────────────────────────

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
            InfoBar.success(
                "", f"统计已导出: {os.path.basename(path)}",
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
        except Exception:
            pass

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
            self._update_overview(stats)
            self._update_question_cards(stats)
        except Exception as exc:
            InfoBar.error(
                "", f"加载失败: {str(exc)[:50]}",
                parent=self.window(),
                position=InfoBarPosition.TOP, duration=3000,
            )
