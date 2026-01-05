"""日志页面"""
import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit
from qfluentwidgets import (
    SubtitleLabel,
    PushButton,
    PrimaryPushButton,
    InfoBar,
    InfoBarPosition,
)

from wjx.utils.log_utils import LOG_BUFFER_HANDLER, save_log_records_to_file
from wjx.utils.load_save import get_runtime_directory


class LogPage(QWidget):
    """独立的日志页，放在侧边栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("日志", self))
        header.addStretch(1)
        self.refresh_btn = PushButton("刷新", self)
        self.clear_btn = PushButton("清空", self)
        self.save_btn = PrimaryPushButton("保存到文件", self)
        header.addWidget(self.refresh_btn)
        header.addWidget(self.clear_btn)
        header.addWidget(self.save_btn)
        layout.addLayout(header)

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.log_view.setPlaceholderText("日志输出会显示在这里，便于排查问题。")
        layout.addWidget(self.log_view, 1)

    def _bind_events(self):
        self.refresh_btn.clicked.connect(self.refresh_logs)
        self.clear_btn.clicked.connect(self.clear_logs)
        self.save_btn.clicked.connect(self.save_logs)

    def refresh_logs(self):
        # 如果用户正在选择文本，跳过自动刷新
        cursor = self.log_view.textCursor()
        if cursor.hasSelection():
            return
        
        records = LOG_BUFFER_HANDLER.get_records()
        # 保存当前滚动位置
        scrollbar = self.log_view.verticalScrollBar()
        old_scroll_value = scrollbar.value()
        was_at_bottom = old_scroll_value >= scrollbar.maximum() - 10
        
        self.log_view.clear()
        cursor = self.log_view.textCursor()
        for entry in records:
            level = str(getattr(entry, "level", getattr(entry, "category", "")) or "").upper()
            if level.startswith("ERROR"):
                color = "#dc2626"  # red-600
            elif level.startswith("WARN"):
                color = "#ca8a04"  # amber-600
            elif level.startswith("INFO"):
                color = "#2563eb"  # blue-600
            else:
                color = "#6b7280"  # gray-500
            cursor.insertHtml(f'<span style="color:{color};">{entry.text}</span><br>')
        
        # 恢复滚动位置
        if was_at_bottom:
            # 只有在用户原本就在底部时才自动滚动到底部
            self.log_view.moveCursor(cursor.MoveOperation.End)
        else:
            # 恢复原来的滚动位置
            scrollbar.setValue(old_scroll_value)

    def clear_logs(self):
        try:
            LOG_BUFFER_HANDLER.records.clear()
        except Exception:
            pass
        self.refresh_logs()

    def save_logs(self):
        try:
            file_path = save_log_records_to_file(LOG_BUFFER_HANDLER.get_records(), get_runtime_directory())
            InfoBar.success("", f"日志已保存：{file_path}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
        except Exception as exc:
            InfoBar.error("", f"保存失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

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
