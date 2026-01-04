# type: ignore
from __future__ import annotations

"""
现代化启动界面模块。
使用 Qt 实现美观的启动画面，支持系统主题色自适应。
"""

from typing import Optional

from wjx.utils.config import APP_ICON_RELATIVE_PATH
from wjx.engine import _get_resource_path
from wjx.utils.version import __VERSION__

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import (
        QColor,
        QFont,
        QGuiApplication,
        QIcon,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPixmap,
        QPalette,
    )
    from PySide6.QtWidgets import QSplashScreen, QApplication

    _HAS_QT = True
except Exception:
    _HAS_QT = False
    QSplashScreen = None  # type: ignore[misc]


def _is_dark_mode() -> bool:
    """检测系统是否为深色模式。"""
    if not _HAS_QT:
        return True
    try:
        app = QApplication.instance()
        if app:
            palette = app.palette()  # type: ignore[union-attr]
            bg_color = palette.color(QPalette.ColorRole.Window)
            # 计算亮度，低于 128 认为是深色模式
            brightness = (bg_color.red() * 299 + bg_color.green() * 587 + bg_color.blue() * 114) / 1000
            return brightness < 128
    except Exception:
        pass
    return True  # 默认深色


class LoadingSplash:
    """现代化启动画面，带渐变背景、图标、进度条和状态文字，支持主题自适应。"""

    WIDTH = 480
    HEIGHT = 320
    RADIUS = 20

    def __init__(
        self,
        title: str = "问卷星速填",
        message: str = "正在启动...",
    ):
        self.progress_value = 0
        self.message = message
        self.title = title
        self._splash = None
        self._icon_pixmap = None
        self._is_dark = True

        if not _HAS_QT:
            return

        # 检测系统主题
        self._is_dark = _is_dark_mode()
        
        # 根据主题设置颜色
        if self._is_dark:
            # 深色模式：现代简约深灰黑
            self._bg_start = QColor("#18181b")
            self._bg_end = QColor("#09090b")
            self._text_color = QColor(250, 250, 250)
            self._text_secondary = QColor(161, 161, 170)
            self._text_hint = QColor(212, 212, 216)
            self._border_color = QColor(63, 63, 70, 60)
            self._bar_bg = QColor(255, 255, 255, 20)
            self._glow_color = QColor(59, 130, 246, 60)
        else:
            # 浅色模式：简约白灰
            self._bg_start = QColor("#ffffff")
            self._bg_end = QColor("#f4f4f5")
            self._text_color = QColor(24, 24, 27)
            self._text_secondary = QColor(113, 113, 122)
            self._text_hint = QColor(63, 63, 70)
            self._border_color = QColor(228, 228, 231)
            self._bar_bg = QColor(0, 0, 0, 8)
            self._glow_color = QColor(59, 130, 246, 40)
        
        # 主题色：简洁蓝色
        self._accent_start = QColor("#3b82f6")
        self._accent_end = QColor("#2563eb")

        # 加载图标
        try:
            icon_path = _get_resource_path(APP_ICON_RELATIVE_PATH)
            self._icon_pixmap = QPixmap(icon_path)
            if self._icon_pixmap.isNull():
                self._icon_pixmap = None
            else:
                self._icon_pixmap = self._icon_pixmap.scaled(
                    64, 64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        except Exception:
            self._icon_pixmap = None

        # 创建启动画面
        pixmap = self._render_splash()
        self._splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self._splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        try:
            icon_path = _get_resource_path(APP_ICON_RELATIVE_PATH)
            self._splash.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    def _render_splash(self) -> "QPixmap":
        """渲染启动画面到 QPixmap。"""
        pixmap = QPixmap(self.WIDTH, self.HEIGHT)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制圆角背景路径
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.WIDTH, self.HEIGHT, self.RADIUS, self.RADIUS)

        # 主渐变背景
        gradient = QLinearGradient(0, 0, self.WIDTH, self.HEIGHT)
        gradient.setColorAt(0, self._bg_start)
        gradient.setColorAt(1, self._bg_end)
        painter.fillPath(path, gradient)

        # 径向渐变光晕叠加（更柔和）
        from PySide6.QtGui import QRadialGradient
        radial = QRadialGradient(self.WIDTH // 2, self.HEIGHT // 3, self.WIDTH * 0.6)
        radial.setColorAt(0, QColor(59, 130, 246, 15))
        radial.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setClipPath(path)
        painter.fillRect(0, 0, self.WIDTH, self.HEIGHT, radial)
        painter.setClipping(False)

        # 绘制边框
        from PySide6.QtGui import QPen
        pen = QPen(self._border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)

        # 图标区域
        icon_y = 60
        icon_size = 72
        
        if self._icon_pixmap:
            icon_x = (self.WIDTH - icon_size) // 2
            
            # 绘制图标光晕
            glow_radius = icon_size // 2 + 20
            glow_radial = QRadialGradient(icon_x + icon_size // 2, icon_y + icon_size // 2, glow_radius)
            glow_radial.setColorAt(0, self._glow_color)
            glow_radial.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(icon_x - 20, icon_y - 20, icon_size + 40, icon_size + 40, glow_radial)
            
            # 绘制图标
            scaled_icon = self._icon_pixmap.scaled(
                icon_size, icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(icon_x, icon_y, scaled_icon)

        # 绘制标题
        title_font = QFont("Microsoft YaHei UI", 22, QFont.Weight.Bold)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        painter.setFont(title_font)
        painter.setPen(self._text_color)
        painter.drawText(0, icon_y + 95, self.WIDTH, 35, Qt.AlignmentFlag.AlignCenter, self.title)

        # 绘制版本号徽章
        version_text = f"v{__VERSION__}"
        version_font = QFont("Microsoft YaHei UI", 9, QFont.Weight.Medium)
        painter.setFont(version_font)
        
        from PySide6.QtGui import QFontMetrics
        metrics = QFontMetrics(version_font)
        version_width = metrics.horizontalAdvance(version_text) + 16
        version_height = 22
        badge_x = (self.WIDTH - version_width) // 2
        badge_y = icon_y + 130
        
        # 徽章背景
        badge_path = QPainterPath()
        badge_path.addRoundedRect(badge_x, badge_y, version_width, version_height, 11, 11)
        painter.fillPath(badge_path, QColor(255, 255, 255, 20))
        
        # 徽章文字
        painter.setPen(self._text_secondary)
        painter.drawText(badge_x, badge_y, version_width, version_height, Qt.AlignmentFlag.AlignCenter, version_text)

        # 进度条
        bar_width = 320
        bar_height = 8
        bar_x = (self.WIDTH - bar_width) // 2
        bar_y = 230

        # 进度条背景
        bar_bg_path = QPainterPath()
        bar_bg_path.addRoundedRect(bar_x, bar_y, bar_width, bar_height, 4, 4)
        painter.fillPath(bar_bg_path, self._bar_bg)

        # 进度条填充
        if self.progress_value > 0:
            progress_width = int(bar_width * min(100, self.progress_value) / 100)
            if progress_width > 6:
                bar_fg_path = QPainterPath()
                bar_fg_path.addRoundedRect(bar_x, bar_y, progress_width, bar_height, 4, 4)
                
                # 渐变进度条
                bar_gradient = QLinearGradient(bar_x, bar_y, bar_x + progress_width, bar_y)
                bar_gradient.setColorAt(0, self._accent_start)
                bar_gradient.setColorAt(1, self._accent_end)
                painter.fillPath(bar_fg_path, bar_gradient)

        # 百分比文字（在进度条右侧，垂直居中）
        percent_font = QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold)
        painter.setFont(percent_font)
        painter.setPen(self._accent_start)
        percent_text = f"{self.progress_value}%"
        # 计算垂直居中位置：进度条中心 - 文字高度的一半
        percent_y = bar_y + bar_height // 2 - 10
        painter.drawText(bar_x + bar_width + 12, percent_y, 50, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, percent_text)

        # 状态文字
        msg_font = QFont("Microsoft YaHei UI", 10)
        painter.setFont(msg_font)
        painter.setPen(self._text_hint)
        painter.drawText(0, bar_y + 20, self.WIDTH, 28, Qt.AlignmentFlag.AlignCenter, self.message)

        painter.end()
        return pixmap

    def show(self) -> None:
        if self._splash:
            self._splash.show()
            QGuiApplication.processEvents()

    def update_progress(self, percent: int, message: Optional[str] = None) -> None:
        self.progress_value = min(100, max(0, int(percent)))
        if message:
            self.message = message
        self._refresh()

    def update_message(self, message: str) -> None:
        self.message = message
        self._refresh()

    def _refresh(self) -> None:
        if self._splash:
            pixmap = self._render_splash()
            self._splash.setPixmap(pixmap)
            QGuiApplication.processEvents()

    def close(self) -> None:
        if self._splash:
            self._splash.close()


_boot_root: Optional[object] = None
_boot_splash: Optional[LoadingSplash] = None


def preload_boot_splash(
    *,
    title: str = "问卷星速填",
    message: str = "正在准备...",
) -> None:
    """创建并显示启动画面。"""
    global _boot_splash
    if _boot_splash is not None:
        return
    try:
        _boot_splash = LoadingSplash(title=title, message=message)
        _boot_splash.show()
        _boot_splash.update_progress(5, "正在加载核心模块...")
    except Exception:
        _boot_splash = None


def update_boot_splash(percent: int, message: Optional[str] = None) -> None:
    if _boot_splash:
        try:
            _boot_splash.update_progress(percent, message)
        except Exception:
            pass


def get_boot_root() -> Optional[object]:
    return _boot_root


def get_boot_splash() -> Optional[LoadingSplash]:
    return _boot_splash


def close_boot_splash() -> None:
    global _boot_splash
    if _boot_splash:
        try:
            _boot_splash.close()
        except Exception:
            pass
    _boot_splash = None
