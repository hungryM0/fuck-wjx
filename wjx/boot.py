from __future__ import annotations

"""启动界面模块 - 使用 QFluentWidgets 的 SplashScreen 组件。"""

__all__ = ["BootSplash", "create_boot_splash", "get_boot_splash", "finish_boot_splash"]

from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QLabel
from qfluentwidgets import IndeterminateProgressBar, SplashScreen, isDarkTheme, FluentWindow

from wjx.utils.version import __VERSION__


class BootSplash:
    """启动画面管理类"""

    def __init__(self, window: "FluentWindow"):
        self.window = window
        self.splash_screen = SplashScreen(window.windowIcon(), window)
        self.splash_screen.setIconSize(QSize(128, 128))

        # 根据主题设置颜色
        is_dark = isDarkTheme()
        title_color = "#ffffff" if is_dark else "#1f2937"
        version_color = "#a1a1aa" if is_dark else "#6b7280"
        badge_bg = "rgba(255, 255, 255, 0.1)" if is_dark else "rgba(0, 0, 0, 0.08)"

        # 添加应用名称标签（加粗）
        self.title_label = QLabel("问卷星速填", self.splash_screen)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {title_color};
                font-size: 20px;
                font-weight: bold;
                font-family: 'Microsoft YaHei UI';
            }}
        """)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.adjustSize()

        # 添加版本号徽章标签
        self.version_label = QLabel(f"v{__VERSION__}", self.splash_screen)
        self.version_label.setStyleSheet(f"""
            QLabel {{
                color: {version_color};
                font-size: 12px;
                font-family: 'Microsoft YaHei UI';
                background-color: {badge_bg};
                border-radius: 11px;
                padding: 4px 12px;
            }}
        """)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.adjustSize()

        # 添加不确定进度条
        self.progress_bar = IndeterminateProgressBar(self.splash_screen)
        self.progress_bar.start()

    def update_layout(self, width: int, height: int):
        """调整启动页面组件位置"""
        # 标题位置：图标下方居中
        icon_bottom = height // 2 + 64 + 15
        title_width = self.title_label.width()
        self.title_label.move((width - title_width) // 2, icon_bottom)
        # 版本号徽章位置：标题下方居中
        title_bottom = icon_bottom + self.title_label.height() + 8
        badge_width = self.version_label.width()
        self.version_label.move((width - badge_width) // 2, title_bottom)
        # 进度条位置：底部
        bar_width = 300
        self.progress_bar.setGeometry(
            (width - bar_width) // 2,
            height - 80,
            bar_width,
            4
        )

    def finish(self):
        """隐藏启动页面并停止进度条"""
        self.progress_bar.stop()
        self.splash_screen.finish()


_boot_splash: Optional[BootSplash] = None


def create_boot_splash(window: "FluentWindow") -> BootSplash:
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
        QTimer.singleShot(delay_ms, _boot_splash.finish)
