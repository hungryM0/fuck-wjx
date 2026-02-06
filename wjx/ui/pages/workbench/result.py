"""结果页面 - 展示作答统计"""

import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    StrongBodyLabel,
    CardWidget,
    PushButton,
    TableWidget,
    ProgressBar,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
    ComboBox,
)

from wjx.core.stats.collector import stats_collector
from wjx.core.stats.models import SurveyStats, QuestionStats
from wjx.core.stats.persistence import save_stats, list_stats_files, load_stats


class ResultPage(QWidget):
    """结果页面：展示作答统计信息"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_stats: Optional[SurveyStats] = None
        self._question_cards: list = []
        self._build_ui()
        self._bind_events()
        self._setup_refresh_timer()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题栏
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("执行结果与统计", self))
        header.addStretch(1)

        # 历史记录选择
        self.history_combo = ComboBox(self)
        self.history_combo.setPlaceholderText("选择历史统计...")
        self.history_combo.setMinimumWidth(200)
        header.addWidget(self.history_combo)

        # 导出按钮
        self.export_btn = PushButton("导出统计", self, FluentIcon.SAVE)
        header.addWidget(self.export_btn)

        layout.addLayout(header)

        # 概览卡片
        self.overview_card = self._build_overview_card()
        layout.addWidget(self.overview_card)

        # 滚动区域
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # 初始占位提示
        placeholder = BodyLabel("暂无统计数据，开始执行任务后将在此显示统计信息", self)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_layout.addWidget(placeholder)
        self.scroll_layout.addStretch(1)

    def _build_overview_card(self) -> CardWidget:
        """构建概览卡片"""
        card = CardWidget(self)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(32)

        # 总提交数
        self.total_widget, self.total_value_label = self._create_stat_item("总提交", "0")
        layout.addWidget(self.total_widget)

        # 成功数
        self.success_widget, self.success_value_label = self._create_stat_item("成功", "0", "#22c55e")
        layout.addWidget(self.success_widget)

        # 失败数
        self.fail_widget, self.fail_value_label = self._create_stat_item("失败", "0", "#ef4444")
        layout.addWidget(self.fail_widget)

        # 成功率
        self.rate_widget, self.rate_value_label = self._create_stat_item("成功率", "0%")
        layout.addWidget(self.rate_widget)

        layout.addStretch(1)
        return card

    def _create_stat_item(self, title: str, value: str, color: Optional[str] = None) -> tuple:
        """创建统计项，返回 (widget, value_label)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = BodyLabel(title)
        title_label.setStyleSheet("color: #6b7280;")
        layout.addWidget(title_label)

        value_label = StrongBodyLabel(value)
        if color:
            value_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")
        else:
            value_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(value_label)

        return widget, value_label

    def _build_question_card(self, q_stats: QuestionStats) -> CardWidget:
        """为单道题目构建统计卡片"""
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 题目标题
        type_labels = {
            "single": "单选题",
            "multiple": "多选题",
            "matrix": "矩阵题",
            "scale": "量表题",
            "score": "评分题",
            "text": "填空题",
            "dropdown": "下拉题",
            "slider": "滑块题",
        }
        type_text = type_labels.get(q_stats.question_type, q_stats.question_type)
        title = f"第 {q_stats.question_num} 题 ({type_text})"
        if q_stats.question_title:
            title += f": {q_stats.question_title[:50]}"
        layout.addWidget(StrongBodyLabel(title))

        # 根据题型选择展示方式
        if q_stats.question_type in ("single", "multiple", "scale", "score", "dropdown", "slider"):
            table = self._build_options_table(q_stats)
            layout.addWidget(table)
        elif q_stats.question_type == "matrix":
            widget = self._build_matrix_table(q_stats)
            layout.addWidget(widget)
        elif q_stats.question_type == "text":
            widget = self._build_text_table(q_stats)
            layout.addWidget(widget)

        return card

    def _build_options_table(self, q_stats: QuestionStats) -> TableWidget:
        """构建选项统计表格"""
        table = TableWidget(self)
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["选项", "次数", "占比", ""])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(1, 80)
        table.setColumnWidth(2, 80)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        # 排序选项
        sorted_options = sorted(q_stats.options.items(), key=lambda x: x[0])
        table.setRowCount(len(sorted_options))

        for row, (idx, opt) in enumerate(sorted_options):
            # 选项名
            option_name = opt.option_text if opt.option_text else f"选项 {idx + 1}"
            table.setItem(row, 0, QTableWidgetItem(option_name))

            # 次数
            table.setItem(row, 1, QTableWidgetItem(str(opt.count)))

            # 占比
            percentage = q_stats.get_option_percentage(idx)
            table.setItem(row, 2, QTableWidgetItem(f"{percentage:.1f}%"))

            # 进度条
            progress = ProgressBar()
            progress.setValue(int(percentage))
            progress.setMaximumHeight(16)
            table.setCellWidget(row, 3, progress)

        table.setMaximumHeight(min(300, 40 + len(sorted_options) * 35))
        return table

    def _build_matrix_table(self, q_stats: QuestionStats) -> QWidget:
        """构建矩阵题统计表格"""
        if not q_stats.rows:
            label = BodyLabel("暂无矩阵数据")
            return label

        # 找出所有列
        all_cols = set()
        for row_data in q_stats.rows.values():
            all_cols.update(row_data.keys())
        cols = sorted(all_cols)

        table = TableWidget(self)
        table.setColumnCount(len(cols) + 1)
        headers = ["行"] + [f"列{c+1}" for c in cols]
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(q_stats.rows))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        for row_idx, (r, col_data) in enumerate(sorted(q_stats.rows.items())):
            table.setItem(row_idx, 0, QTableWidgetItem(f"行 {r+1}"))
            for col_offset, c in enumerate(cols):
                count = col_data.get(c, 0)
                table.setItem(row_idx, col_offset + 1, QTableWidgetItem(str(count)))

        table.setMaximumHeight(min(300, 40 + len(q_stats.rows) * 35))
        return table

    def _build_text_table(self, q_stats: QuestionStats) -> QWidget:
        """构建填空题统计表格"""
        if not q_stats.text_answers:
            label = BodyLabel("暂无填空数据")
            return label

        table = TableWidget(self)
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["答案内容", "次数"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 80)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        sorted_answers = sorted(q_stats.text_answers.items(), key=lambda x: -x[1])
        table.setRowCount(min(20, len(sorted_answers)))  # 最多显示20条

        for row, (text, count) in enumerate(sorted_answers[:20]):
            display_text = text[:100] + "..." if len(text) > 100 else text
            table.setItem(row, 0, QTableWidgetItem(display_text))
            table.setItem(row, 1, QTableWidgetItem(str(count)))

        table.setMaximumHeight(min(300, 40 + min(20, len(sorted_answers)) * 35))
        return table

    def _bind_events(self) -> None:
        self.export_btn.clicked.connect(self._on_export)
        self.history_combo.currentIndexChanged.connect(self._on_history_selected)

    def _setup_refresh_timer(self) -> None:
        """设置自动刷新定时器"""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)  # 2秒刷新一次
        self._refresh_timer.timeout.connect(self._auto_refresh)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 先加载历史列表
        self._load_history_list()
        # 再刷新当前统计（仅当选中"当前会话"时）
        if self.history_combo.currentIndex() <= 0:
            self.refresh_stats()
        # 最后启动定时器
        self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._refresh_timer.stop()

    def _auto_refresh(self) -> None:
        """自动刷新（仅当选中"当前会话"时）"""
        if self.history_combo.currentIndex() <= 0:
            self.refresh_stats()

    def refresh_stats(self) -> None:
        """刷新统计数据"""
        stats = stats_collector.get_current_stats()
        if stats is None:
            return

        self._current_stats = stats
        self._update_overview(stats)
        self._update_question_cards(stats)

    def _update_overview(self, stats: SurveyStats) -> None:
        """更新概览数据"""
        total = stats.total_submissions + stats.failed_submissions
        success = stats.total_submissions
        fail = stats.failed_submissions
        rate = (success / total * 100) if total > 0 else 0

        self.total_value_label.setText(str(total))
        self.success_value_label.setText(str(success))
        self.fail_value_label.setText(str(fail))
        self.rate_value_label.setText(f"{rate:.1f}%")

    def _update_question_cards(self, stats: SurveyStats) -> None:
        """更新题目统计卡片"""
        # 清除所有旧内容
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._question_cards.clear()

        if not stats.questions:
            # 重新创建 placeholder
            placeholder = BodyLabel("暂无统计数据，开始执行任务后将在此显示统计信息", self)
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scroll_layout.addWidget(placeholder)
            self.scroll_layout.addStretch(1)
            return

        # 按题号排序添加卡片
        for q_num in sorted(stats.questions.keys()):
            q_stats = stats.questions[q_num]
            card = self._build_question_card(q_stats)
            self._question_cards.append(card)
            self.scroll_layout.addWidget(card)

        self.scroll_layout.addStretch(1)

    def _on_export(self) -> None:
        """导出统计数据"""
        stats = self._current_stats or stats_collector.get_current_stats()
        if stats is None:
            InfoBar.warning(
                "",
                "暂无统计数据可导出",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return
        try:
            path = save_stats(stats)
            InfoBar.success(
                "",
                f"统计已导出: {os.path.basename(path)}",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            self._load_history_list()
        except Exception as exc:
            InfoBar.error(
                "",
                f"导出失败: {exc}",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _load_history_list(self) -> None:
        """加载历史统计列表"""
        # 临时断开信号连接，避免在填充列表时触发回调
        try:
            self.history_combo.currentIndexChanged.disconnect(self._on_history_selected)
        except:
            pass  # 如果没有连接，忽略错误
        
        try:
            self.history_combo.clear()
            self.history_combo.addItem("当前会话")
            self.history_combo.setItemData(0, None)  # 明确设置第一项的 data 为 None
            
            files = list_stats_files()
            print(f"[DEBUG] 找到 {len(files)} 个统计文件")
            for idx, path in enumerate(files[:20], start=1):  # 最多显示20条，从索引1开始
                filename = os.path.basename(path)
                self.history_combo.addItem(filename)
                self.history_combo.setItemData(idx, path)  # 单独设置 userData
                print(f"[DEBUG] 添加项: index={idx}, {filename} -> {path}")
        except Exception as e:
            print(f"[DEBUG] 加载历史列表失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 重新连接信号
            self.history_combo.currentIndexChanged.connect(self._on_history_selected)

    def _on_history_selected(self, index: int) -> None:
        """选择历史记录"""
        print(f"[DEBUG] 选择历史记录，index={index}")
        
        # 选择"当前会话"，刷新当前统计
        if index <= 0:
            print(f"[DEBUG] 刷新当前会话")
            self.refresh_stats()
            return
        
        # 获取选中文件的路径
        path = self.history_combo.itemData(index)
        print(f"[DEBUG] 文件路径: {path}")
        
        if not path:
            InfoBar.warning(
                "",
                f"未找到文件路径 (index={index})",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return
            
        try:
            # 加载统计文件
            stats = load_stats(path)
            if not stats:
                InfoBar.warning(
                    "",
                    "文件加载失败或数据为空",
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            
            # 验证数据
            if not hasattr(stats, 'total_submissions'):
                InfoBar.error(
                    "",
                    "数据格式错误",
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
                
            # 更新界面
            self._current_stats = stats
            self._update_overview(stats)
            self._update_question_cards(stats)
            
            # 强制重绘界面
            self.update()
            
        except Exception as exc:
            import traceback
            traceback.print_exc()
            InfoBar.error(
                "",
                f"加载失败: {str(exc)[:50]}",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )
