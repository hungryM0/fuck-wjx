"""日志页面"""
import os
import logging
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit
from PySide6.QtGui import QFont, QTextCursor
from qfluentwidgets import (
    SubtitleLabel,
    PushButton,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
    isDarkTheme,
    qconfig,
)
from wjx.utils.logging.log_utils import LOG_BUFFER_HANDLER, save_log_records_to_file, log_suppressed_exception
from wjx.utils.app.config import LOG_BUFFER_CAPACITY, LOG_REFRESH_INTERVAL_MS
from wjx.utils.io.load_save import get_runtime_directory
from wjx.ui.widgets.log_highlighter import LogHighlighter


# 日志级别颜色配置（深色/浅色主题）
LOG_COLORS_DARK = {
    "ERROR": "#ef4444",   # 红色
    "WARN": "#eab308",    # 黄色
    "WARNING": "#eab308", # 黄色
    "INFO": "#d1d5db",    # 浅灰色
    "OK": "#22c55e",      # 绿色
    "DEBUG": "#6b7280",   # 深灰色
    "DEFAULT": "#9ca3af", # 默认灰色
}

LOG_COLORS_LIGHT = {
    "ERROR": "#dc2626",   # 深红色
    "WARN": "#ca8a04",    # 深黄色
    "WARNING": "#ca8a04", # 深黄色
    "INFO": "#374151",    # 深灰色
    "OK": "#15803d",      # 深绿
    "DEBUG": "#6b7280",   # 中灰色
    "DEFAULT": "#4b5563", # 默认深灰
}

# 日志级别筛选选项
LOG_LEVELS = [
    ("全部", None),
    ("仅错误", "ERROR"),
    ("警告及以上", "WARN"),
    ("信息及以上", "INFO"),
    ("调试", "DEBUG"),
]


class LogPage(QWidget):
    """独立的日志页，放在侧边栏。"""



    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_filter = None
        self._force_full_refresh = True
        self._last_seen_record = None
        self._stick_to_bottom = True  # 用户是否希望自动跟随最新日志
        self._last_version = -1  # 上次读取的日志版本号
        self._build_ui()
        self._bind_events()
        self._load_last_session_logs()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(LOG_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.refresh_logs)
        self._refresh_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        layout.addWidget(SubtitleLabel("日志", self))

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.save_btn = PushButton("导出到文件", self, FIF.SAVE)

        # 日志级别筛选
        self.level_combo = ComboBox(self)
        self.level_combo.setMinimumWidth(120)
        for text, _ in LOG_LEVELS:
            self.level_combo.addItem(text)

        toolbar.addWidget(self.save_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.level_combo)
        layout.addLayout(toolbar)

        # 日志显示区域
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | 
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.log_view.setPlaceholderText("日志输出会显示在这里...")
        
        # 设置等宽字体
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(font)
        self.log_view.verticalScrollBar().valueChanged.connect(self._on_scrollbar_value_changed)
        try:
            if LOG_BUFFER_CAPACITY and int(LOG_BUFFER_CAPACITY) > 0:
                self.log_view.document().setMaximumBlockCount(int(LOG_BUFFER_CAPACITY))
        except Exception as exc:
            log_suppressed_exception("_build_ui: if LOG_BUFFER_CAPACITY and int(LOG_BUFFER_CAPACITY) > 0: self.log_view.docume...", exc, level=logging.WARNING)
        self._highlighter = LogHighlighter(
            self.log_view.document(),
            colors=self._resolve_log_colors(),
        )
        
        # 应用主题样式
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)
        
        layout.addWidget(self.log_view, 1)

    def _bind_events(self):
        self.save_btn.clicked.connect(self.save_logs)
        self.level_combo.currentIndexChanged.connect(self._on_filter_changed)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()
        QTimer.singleShot(0, self.refresh_logs)

    def _on_filter_changed(self, index):
        """日志级别筛选变化"""
        self._current_filter = LOG_LEVELS[index][1] if index < len(LOG_LEVELS) else None
        self._force_full_refresh = True
        self.refresh_logs()

    def _get_log_level(self, entry):
        """获取日志级别"""
        level = str(getattr(entry, "level", getattr(entry, "category", "")) or "").upper()
        if level.startswith("ERROR"):
            return "ERROR"
        elif level.startswith("WARN"):
            return "WARN"
        elif level.startswith("INFO"):
            return "INFO"
        elif level.startswith("DEBUG"):
            return "DEBUG"
        return "DEFAULT"

    def _should_show(self, level):
        """根据筛选条件判断是否显示"""
        if self._current_filter is None:
            return True
        priority = {"ERROR": 4, "WARN": 3, "WARNING": 3, "INFO": 2, "DEBUG": 1, "DEFAULT": 0}
        filter_priority = priority.get(self._current_filter, 0)
        level_priority = priority.get(level, 0)
        return level_priority >= filter_priority

    def refresh_logs(self):
        """完全异步的日志刷新：版本号检测 + 无锁读取

        优化策略：
        1. 先检查版本号，没有变化则跳过（避免无效拷贝）
        2. 使用无锁队列，读取时完全不阻塞
        3. 增量更新时批量渲染，减少 GUI 开销
        """
        # 不在当前可见页面时，跳过自动刷新，避免后台重绘拖慢主窗口
        if not self.isVisible():
            return
        # 如果用户正在选择文本，跳过自动刷新
        cursor = self.log_view.textCursor()
        if cursor.hasSelection():
            return

        # 【优化 1】先检查版本号，没有变化则跳过
        current_version = LOG_BUFFER_HANDLER.get_version()
        if current_version == self._last_version and not self._force_full_refresh:
            return  # 没有新日志，直接返回

        scrollbar = self.log_view.verticalScrollBar()
        old_value = scrollbar.value()
        old_max = scrollbar.maximum()
        stick_to_bottom = self._stick_to_bottom

        # 【优化 2】无锁读取日志（异步模式下无需 try_lock）
        records = LOG_BUFFER_HANDLER.get_records()
        if not records:
            if self._force_full_refresh:
                self.log_view.clear()
                self._force_full_refresh = False
            self._last_seen_record = None
            self._last_version = current_version
            return

        # 增量更新：只追加新日志
        if not self._force_full_refresh and self._last_seen_record is not None:
            last_index = -1
            for idx, entry in enumerate(records):
                if entry is self._last_seen_record:
                    last_index = idx
                    break
            if last_index != -1 and last_index < len(records) - 1:
                new_entries = records[last_index + 1 :]

                # 【优化 3】批量渲染：先拼接字符串，再一次性追加
                new_lines = []
                for entry in new_entries:
                    level = self._get_log_level(entry)
                    if not self._should_show(level):
                        continue
                    text = entry.text if hasattr(entry, "text") else str(entry)
                    new_lines.append(text)

                if new_lines:
                    # 一次性追加所有新日志（比循环 appendPlainText 快得多）
                    self.log_view.appendPlainText("\n".join(new_lines))

                self._last_seen_record = records[-1]
                self._last_version = current_version

                if stick_to_bottom:
                    self.log_view.moveCursor(QTextCursor.MoveOperation.End)
                else:
                    self._restore_scroll_position(scrollbar, old_value, old_max)
                return

        # 全量刷新：重新渲染所有日志
        lines = []
        for entry in records:
            level = self._get_log_level(entry)
            if not self._should_show(level):
                continue
            text = entry.text if hasattr(entry, "text") else str(entry)
            lines.append(text)

        self.log_view.setPlainText("\n".join(lines))
        self._last_seen_record = records[-1] if records else None
        self._last_version = current_version
        self._force_full_refresh = False

        # 恢复滚动位置
        if stick_to_bottom:
            self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self._restore_scroll_position(scrollbar, old_value, old_max)

    def save_logs(self):
        try:
            file_path = save_log_records_to_file(
                LOG_BUFFER_HANDLER.get_records(),
                get_runtime_directory()
            )
            InfoBar.success(
                "", f"日志已保存：{file_path}",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=3000
            )
        except Exception as exc:
            InfoBar.error(
                "", f"保存失败：{exc}",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=3000
            )

    def _apply_theme(self):
        """根据主题应用样式"""
        if isDarkTheme():
            self.log_view.setStyleSheet("""
                QPlainTextEdit {
                    background-color: #1a1a1a;
                    color: #d1d5db;
                    border: 1px solid #333;
                    border-radius: 6px;
                    padding: 8px;
                    selection-background-color: #3b82f6;
                }
            """)
        else:
            self.log_view.setStyleSheet("""
                QPlainTextEdit {
                    background-color: #f8f9fa;
                    color: #1f2937;
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                    padding: 8px;
                    selection-background-color: #3b82f6;
                }
            """)
        if hasattr(self, "_highlighter"):
            self._highlighter.set_colors(self._resolve_log_colors())

    @staticmethod
    def _resolve_log_colors():
        return LOG_COLORS_DARK if isDarkTheme() else LOG_COLORS_LIGHT

    def _on_scrollbar_value_changed(self, value):
        """记录用户是否滚到最底部，决定是否自动跟随新日志"""
        scrollbar = self.log_view.verticalScrollBar()
        self._stick_to_bottom = value >= scrollbar.maximum() - 2

    @staticmethod
    def _restore_scroll_position(scrollbar, old_value, old_max):
        """在非自动跟随时，尽量保持当前阅读位置"""
        new_max = scrollbar.maximum()
        if new_max < old_max:
            # 有截断（比如达到最大行数），等比例向上补偿
            target = max(0, old_value - (old_max - new_max))
        else:
            # 只追加了新日志，保持当前位置不要被拖到底
            target = old_value
        scrollbar.setValue(min(max(target, 0), new_max))

    def _load_last_session_logs(self):
        """加载上次会话的日志"""
        try:
            log_path = os.path.join(get_runtime_directory(), "logs", "last_session.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    self.log_view.setPlainText(content)
        except Exception as exc:
            log_suppressed_exception("_load_last_session_logs: log_path = os.path.join(get_runtime_directory(), \"logs\", \"last_session.log\")", exc, level=logging.WARNING)
