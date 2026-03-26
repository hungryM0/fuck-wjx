from __future__ import annotations

"""启动界面模块 - 使用 QFluentWidgets 的 SplashScreen 组件。"""

__all__ = ["BootSplash", "create_boot_splash", "get_boot_splash", "finish_boot_splash"]

from typing import Optional

import os

from PySide6.QtCore import Qt, QTimer, QSize, QThread
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import IndeterminateProgressBar, SplashScreen, isDarkTheme

from software.app.runtime_paths import get_resource_path
from software.app.version import __VERSION__


class BootSplash:
    """启动画面管理类"""

    def __init__(self, window: QWidget):
        self.window = window
        self._boot_icon = self._resolve_boot_icon(window)
        self.splash_screen = SplashScreen(self._boot_icon, window)
        self.splash_screen.setIconSize(QSize(64, 64))
        self._finish_timer: Optional[QTimer] = None
        self._icon_size = 64
        self._scale = 1.0

        # 根据主题设置颜色
        is_dark = isDarkTheme()
        self._title_color = "#ffffff" if is_dark else "#1f2937"
        self._version_color = "#a1a1aa" if is_dark else "#6b7280"
        self._badge_bg = "rgba(255, 255, 255, 0.1)" if is_dark else "rgba(0, 0, 0, 0.08)"

        # 添加应用名称标签
        self.title_label = QLabel("SurveyController", self.splash_screen)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 添加版本号徽章标签
        self.version_label = QLabel(f"v{__VERSION__}", self.splash_screen)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 添加不确定进度条
        self.progress_bar = IndeterminateProgressBar(self.splash_screen)
        self.progress_bar.start()
        self.title_label.show()
        self.version_label.show()
        self.progress_bar.show()
        self.update_layout(window.width(), window.height())
        self.splash_screen.raise_()

    def _resolve_boot_icon(self, window: QWidget) -> QIcon:
        """启动页优先使用高清 PNG 图标，避免 ico 在大尺寸下发虚发小。"""
        icon_path = get_resource_path(os.path.join("assets", "icon.png"))
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return window.windowIcon()

    def _apply_scale(self, width: int, height: int):
        """按窗口尺寸动态放大启动页元素，避免大窗口里内容显得过小。"""
        base_width, base_height = 1180, 780
        width = max(width, 900)
        height = max(height, 640)

        scale = min(width / base_width, height / base_height)
        self._scale = max(1.0, min(scale, 1.45))
        self._icon_size = int(220 * self._scale)
        self.splash_screen.setIconSize(QSize(self._icon_size, self._icon_size))

        title_font_size = int(28 * self._scale)
        version_font_size = int(14 * self._scale)
        badge_radius = max(12, int(13 * self._scale))
        pad_vertical = max(4, int(4 * self._scale))
        pad_horizontal = max(12, int(14 * self._scale))

        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {self._title_color};
                font-size: {title_font_size}px;
                font-weight: bold;
                font-family: 'Microsoft YaHei UI';
            }}
        """)
        self.title_label.adjustSize()

        self.version_label.setStyleSheet(f"""
            QLabel {{
                color: {self._version_color};
                font-size: {version_font_size}px;
                font-family: 'Microsoft YaHei UI';
                background-color: {self._badge_bg};
                border-radius: {badge_radius}px;
                padding: {pad_vertical}px {pad_horizontal}px;
            }}
        """)
        self.version_label.adjustSize()

    def update_layout(self, width: int, height: int):
        """调整启动页面组件位置"""
        self.splash_screen.resize(width, height)
        self._apply_scale(width, height)

        # 标题位置：图标下方居中
        icon_bottom = height // 2 + self._icon_size // 2 + int(18 * self._scale)
        title_width = self.title_label.width()
        self.title_label.move((width - title_width) // 2, icon_bottom)

        # 版本号徽章位置：标题下方居中
        title_bottom = icon_bottom + self.title_label.height() + int(10 * self._scale)
        badge_width = self.version_label.width()
        self.version_label.move((width - badge_width) // 2, title_bottom)

        # 进度条位置：底部
        bar_width = int(max(340, min(width * 0.34, 520)))
        bar_height = max(4, int(5 * self._scale))
        self.progress_bar.setGeometry(
            (width - bar_width) // 2,
            height - int(82 * self._scale),
            bar_width,
            bar_height
        )

    def finish(self):
        """隐藏启动页面并停止进度条"""
        self._stop_finish_timer()
        self._stop_progress_bar()
        try:
            self.splash_screen.finish()
        except Exception:
            pass

    def cleanup(self):
        """清理资源（在窗口关闭时调用）"""
        self._stop_finish_timer()
        self._stop_progress_bar()

    def _stop_finish_timer(self) -> None:
        timer = self._finish_timer
        self._finish_timer = None
        if timer is None:
            return
        try:
            if timer.thread() is QThread.currentThread() and timer.isActive():
                timer.stop()
        except Exception:
            pass
        try:
            timer.deleteLater()
        except Exception:
            pass

    def _stop_progress_bar(self) -> None:
        """只在进度条所属线程里调用 stop，避免 Qt 跨线程停计时器告警。"""
        try:
            if self.progress_bar.thread() is QThread.currentThread():
                self.progress_bar.stop()
        except Exception:
            pass


_boot_splash: Optional[BootSplash] = None


def create_boot_splash(window: QWidget) -> BootSplash:
    """创建启动画面"""
    global _boot_splash
    _boot_splash = BootSplash(window)
    return _boot_splash


def get_boot_splash() -> Optional[BootSplash]:
    """获取当前启动画面实例"""
    return _boot_splash


def finish_boot_splash(delay_ms: int = 1500):
    """延迟关闭启动画面"""
    if _boot_splash:
        # 绑定到启动页对象本身，避免应用退出时出现无主计时器的线程归属问题。
        _boot_splash._stop_finish_timer()
        _boot_splash._finish_timer = QTimer(_boot_splash.splash_screen)
        _boot_splash._finish_timer.setSingleShot(True)
        _boot_splash._finish_timer.timeout.connect(_boot_splash.finish)
        _boot_splash._finish_timer.start(delay_ms)

