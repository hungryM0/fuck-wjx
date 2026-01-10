"""日志页面 - 参考UniGetUI设计"""
import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QApplication
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from qfluentwidgets import (
    SubtitleLabel,
    PushButton,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
)

from wjx.utils.log_utils import LOG_BUFFER_HANDLER, save_log_records_to_file
from wjx.utils.load_save import get_runtime_directory


# 日志级别颜色配置（参考UniGetUI）
LOG_COLORS = {
    "ERROR": "#ef4444",   # 红色
    "WARN": "#eab308",    # 黄色
    "WARNING": "#eab308", # 黄色
    "INFO": "#d1d5db",    # 浅灰色（普通信息）
    "DEBUG": "#6b7280",   # 深灰色
    "DEFAULT": "#9ca3af", # 默认灰色
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
        self._build_ui()
        self._bind_events()
        self._load_last_session_logs()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1200)
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

        self.copy_btn = PushButton("复制到剪贴板", self, FIF.COPY)
        self.save_btn = PushButton("导出到文件", self, FIF.SAVE)

        # 日志级别筛选
        self.level_combo = ComboBox(self)
        self.level_combo.setMinimumWidth(120)
        for text, _ in LOG_LEVELS:
            self.level_combo.addItem(text)

        self.refresh_btn = PushButton("重载日志", self, FIF.SYNC)

        toolbar.addWidget(self.copy_btn)
        toolbar.addWidget(self.save_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.level_combo)
        toolbar.addWidget(self.refresh_btn)
        layout.addLayout(toolbar)

        # 日志显示区域（深色终端风格）
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | 
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.log_view.setPlaceholderText("日志输出会显示在这里...")
        
        # 设置深色终端风格
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
        
        # 设置等宽字体
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(font)
        
        layout.addWidget(self.log_view, 1)

    def _bind_events(self):
        self.refresh_btn.clicked.connect(self.refresh_logs)
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        self.save_btn.clicked.connect(self.save_logs)
        self.level_combo.currentIndexChanged.connect(self._on_filter_changed)

    def _on_filter_changed(self, index):
        """日志级别筛选变化"""
        self._current_filter = LOG_LEVELS[index][1] if index < len(LOG_LEVELS) else None
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
        # 如果用户正在选择文本，跳过自动刷新
        cursor = self.log_view.textCursor()
        if cursor.hasSelection():
            return

        records = LOG_BUFFER_HANDLER.get_records()

        # 保存滚动位置
        scrollbar = self.log_view.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 10

        self.log_view.clear()
        cursor = self.log_view.textCursor()

        for entry in records:
            level = self._get_log_level(entry)
            if not self._should_show(level):
                continue

            color = LOG_COLORS.get(level, LOG_COLORS["DEFAULT"])
            
            # 使用HTML插入带颜色的文本
            text = entry.text if hasattr(entry, 'text') else str(entry)
            cursor.insertHtml(f'<span style="color:{color};">{text}</span><br>')

        # 恢复滚动位置
        if was_at_bottom:
            self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _copy_to_clipboard(self):
        """复制日志到剪贴板"""
        text = self.log_view.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            InfoBar.success(
                "", "已复制到剪贴板",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=2000
            )

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

    def _load_last_session_logs(self):
        """加载上次会话的日志"""
        try:
            log_path = os.path.join(get_runtime_directory(), "logs", "last_session.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    self.log_view.setPlainText(content)
        except Exception:
            pass
