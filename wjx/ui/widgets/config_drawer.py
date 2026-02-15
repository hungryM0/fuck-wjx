"""右侧配置抽屉，用于展示 configs 目录下的配置文件列表。"""
from __future__ import annotations
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


import os
from datetime import datetime
from typing import Callable, List, Optional

from PySide6.QtCore import QPoint, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    ListWidget,
    MessageBox,
    PrimaryPushButton,
    SubtitleLabel,
    TransparentToolButton,
    isDarkTheme,
)

from wjx.utils.io.load_save import get_runtime_directory


class _OverlayWidget(QWidget):
    """遮罩层组件，点击时关闭抽屉"""



    def __init__(self, parent=None, on_click: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self._on_click = on_click

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if self._on_click:
            self._on_click()
        super().mousePressEvent(event)


class ConfigDrawer(QWidget):
    """简单的右侧抽屉，点击配置项后回调加载。"""

    def __init__(self, parent=None, on_select: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self.setObjectName("configDrawer")
        self._on_select = on_select
        self._is_open = False
        self._is_closing = False
        self._close_connected = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(360)
        self._overlay = _OverlayWidget(parent, self.close_drawer)
        self._overlay.setObjectName("configDrawerOverlay")
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.card = CardWidget(self)
        self.card.setObjectName("configDrawerCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 16)
        card_layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("配置列表", self.card))
        header.addStretch(1)
        self.close_btn = TransparentToolButton(FluentIcon.CLOSE, self.card)
        self.close_btn.setToolTip("关闭")
        self.close_btn.setFixedSize(28, 28)
        header.addWidget(self.close_btn)
        card_layout.addLayout(header)

        link_row = QHBoxLayout()
        self.folder_btn = PrimaryPushButton(FluentIcon.FOLDER, "打开配置文件夹", self.card)
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.setFixedHeight(32)
        link_row.addWidget(self.folder_btn)
        link_row.addStretch(1)
        card_layout.addLayout(link_row)

        self.hint_label = BodyLabel("双击配置文件即可载入", self.card)
        self.hint_label.setStyleSheet("color: #6b6b6b;")
        card_layout.addWidget(self.hint_label)

        self.list_widget = ListWidget(self.card)
        card_layout.addWidget(self.list_widget, 1)

        self.empty_label = BodyLabel("configs 目录暂无配置文件", self.card)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #6b6b6b;")
        card_layout.addWidget(self.empty_label)

        main_layout.addWidget(self.card)

        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(220)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.close_btn.clicked.connect(self.close_drawer)
        self.folder_btn.clicked.connect(self._open_config_folder)
        self.list_widget.itemDoubleClicked.connect(self._handle_item_triggered)

        self._update_empty_state()
        self._apply_theme()
        self._overlay.hide()
        self.hide()

    def _update_empty_state(self):
        has_items = self.list_widget.count() > 0
        self.hint_label.setVisible(has_items)
        self.list_widget.setVisible(has_items)
        self.empty_label.setVisible(not has_items)

    def refresh(self):
        """重新扫描 configs 目录并刷新列表。"""
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)

        files: List[tuple] = []
        for name in os.listdir(configs_dir):
            path = os.path.join(configs_dir, name)
            if not os.path.isfile(path) or not name.lower().endswith(".json"):
                continue
            stat = os.stat(path)
            files.append((stat.st_mtime, name, path, stat.st_size))

        files.sort(key=lambda item: item[0], reverse=True)
        self.list_widget.clear()
        for mtime, name, path, size in files:
            time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            size_kb = size / 1024
            text = f"{name}    |    {time_str}    |    {size_kb:.1f} KB"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list_widget.addItem(item)

        self._update_empty_state()

    def _open_config_folder(self):
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)
        try:
            os.startfile(configs_dir)
        except Exception as exc:
            MessageBox("打开失败", f"无法打开配置文件夹：{exc}", self).exec()

    def _apply_theme(self):
        if isDarkTheme():
            panel_bg = "rgba(31, 31, 31, 0.7)"
            card_bg = "rgba(42, 42, 42, 0.7)"
            border = "#333333"
        else:
            panel_bg = "rgba(244, 244, 245, 0.7)"
            card_bg = "rgba(255, 255, 255, 0.7)"
            border = "#e5e7eb"
        self.setStyleSheet(f"""
            #configDrawer {{
                background-color: {panel_bg};
            }}
            #configDrawer QLabel {{
                background: transparent;
            }}
            #configDrawerOverlay {{
                background-color: rgba(0, 0, 0, 0.3);
            }}
        """)
        self.card.setStyleSheet(f"""
            #configDrawerCard {{
                background-color: {card_bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

    def open_drawer(self):
        """从右侧滑入显示抽屉。"""
        self.refresh()
        self._apply_theme()
        host = self.parentWidget()
        if host is None:
            return
        self._is_closing = False
        if self._close_connected:
            try:
                self._slide_anim.finished.disconnect(self._on_close_finished)
            except Exception as exc:
                log_suppressed_exception("open_drawer: self._slide_anim.finished.disconnect(self._on_close_finished)", exc, level=logging.WARNING)
            self._close_connected = False

        target_x = host.width() - self.width()
        target_y = 0

        self._overlay.setGeometry(0, 0, host.width(), host.height())
        self._overlay.show()
        self._overlay.raise_()

        self.setFixedHeight(host.height())
        self.setGeometry(host.width(), target_y, self.width(), host.height())
        self.show()
        self.raise_()

        self._slide_anim.stop()
        self._slide_anim.setStartValue(QPoint(host.width(), target_y))
        self._slide_anim.setEndValue(QPoint(target_x, target_y))
        self._slide_anim.start()
        self._is_open = True

    def close_drawer(self):
        """关闭抽屉，无动画或动画异常时兜底隐藏。"""
        if not self.isVisible():
            return
        host = self.parentWidget()
        if host is None:
            self.hide()
            self._overlay.hide()
            self._is_open = False
            return
        self._is_closing = True
        try:
            if self._close_connected:
                try:
                    self._slide_anim.finished.disconnect(self._on_close_finished)
                except Exception as exc:
                    log_suppressed_exception("close_drawer: self._slide_anim.finished.disconnect(self._on_close_finished)", exc, level=logging.WARNING)
                self._close_connected = False
            start_pos = self.pos()
            end_pos = QPoint(host.width(), start_pos.y())
            self._slide_anim.stop()
            self._slide_anim.setStartValue(start_pos)
            self._slide_anim.setEndValue(end_pos)
            self._slide_anim.finished.connect(self._on_close_finished)
            self._close_connected = True
            self._slide_anim.start()
        except Exception:
            self.hide()
            self._overlay.hide()
            self._is_closing = False
        self._is_open = False

    def sync_to_parent(self):
        """窗口尺寸变化时同步位置。"""
        host = self.parentWidget()
        if host is None:
            return
        self.setFixedHeight(host.height())
        self._overlay.setGeometry(0, 0, host.width(), host.height())
        if self._is_closing:
            return
        if not self.isVisible() and not self._is_open:
            return
        target_x = host.width() - self.width()
        target_y = 0
        self.move(max(0, target_x), target_y)

    def _on_close_finished(self):
        if self._close_connected:
            try:
                self._slide_anim.finished.disconnect(self._on_close_finished)
            except Exception as exc:
                log_suppressed_exception("_on_close_finished: self._slide_anim.finished.disconnect(self._on_close_finished)", exc, level=logging.WARNING)
            self._close_connected = False
        self._is_closing = False
        self._overlay.hide()
        self.hide()

    def _handle_item_triggered(self, item: QListWidgetItem):
        """双击/回车加载配置。"""
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path or not os.path.exists(path):
            return
        if self._on_select:
            self._on_select(path)
        self.close_drawer()
