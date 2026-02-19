"""MainWindow 更新检查与下载提示相关方法。"""
from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    IndeterminateProgressBar,
    IndeterminateProgressRing,
    InfoBadge,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    ProgressBar,
)

from wjx.utils.app.config import GITHUB_MIRROR_SOURCES, get_bool_from_qsettings
from wjx.utils.app.version import __VERSION__


class MainWindowUpdateMixin:
    """主窗口更新模块方法集合。"""

    if TYPE_CHECKING:
        from typing import Any
        titleBar: Any
        updateAvailable: Any
        isLatestVersion: Any
        downloadProgress: Any
        _toast: Any
        _log_popup_confirm: Any
        _log_popup_error: Any
        close: Any
        _settings_page: Any

    def _check_update_on_startup(self):
        """根据设置在启动时检查更新（后台异步执行）"""
        settings = QSettings("FuckWjx", "Settings")
        if get_bool_from_qsettings(settings.value("auto_check_update"), True):
            from wjx.ui.workers.update_worker import UpdateCheckWorker

            self._show_update_checking_placeholder()

            # 创建后台Worker
            self._update_worker = UpdateCheckWorker(self)
            self._update_worker.update_checked.connect(self._on_update_checked)
            self._update_worker.check_failed.connect(self._on_update_check_failed)
            self._update_worker.start()

            logging.debug("已启动后台更新检查")

    def _on_update_checked(self, has_update: bool, update_info: dict):
        """更新检查完成的回调"""
        self._clear_update_checking_placeholder()
        self._check_preview_version()
        if has_update:
            self.update_info = update_info
            self._show_update_notification()
        else:
            self._show_latest_version_badge()

    def _on_update_check_failed(self, error_message: str):
        """更新检查失败的回调"""
        self._clear_update_checking_placeholder()
        self._check_preview_version()
        logging.debug(f"更新检查失败: {error_message}")
        # 失败时不显示任何通知，静默处理

    def _show_update_checking_placeholder(self):
        """更新检查期间在标题栏徽章位置显示转圈占位。"""
        if self._update_checking_spinner:
            return
        for attr in ("_latest_badge", "_outdated_badge", "_preview_badge"):
            badge = getattr(self, attr, None)
            if badge is None:
                continue
            try:
                self.titleBar.hBoxLayout.removeWidget(badge)
                badge.deleteLater()
            except Exception:
                logging.debug("移除旧徽章失败", exc_info=True)
            setattr(self, attr, None)
        try:
            spinner = IndeterminateProgressRing(parent=self.titleBar)
            spinner.setFixedSize(16, 16)
            spinner.setStrokeWidth(2)
            self.titleBar.hBoxLayout.insertWidget(2, spinner, 0, Qt.AlignmentFlag.AlignVCenter)
            self._update_checking_spinner = spinner
        except Exception:
            logging.debug("显示更新检查占位失败", exc_info=True)

    def _clear_update_checking_placeholder(self):
        spinner = self._update_checking_spinner
        if spinner is None:
            return
        try:
            self.titleBar.hBoxLayout.removeWidget(spinner)
            spinner.deleteLater()
        except Exception:
            logging.debug("清理更新检查占位失败", exc_info=True)
        self._update_checking_spinner = None

    def _show_update_notification(self):
        """显示更新通知（从后台线程安全调用）"""
        self.updateAvailable.emit()

    def _do_show_update_notification(self):
        """实际显示更新通知（使用简单纯文本样式）"""
        if not getattr(self, "update_info", None):
            return
        from wjx.utils.update.updater import show_update_notification

        show_update_notification(self)

    def _show_latest_version_badge(self):
        """在标题栏显示最新版本徽章"""
        # 如果是预览版本，不显示"最新"徽章（预览版本优先显示"预览"）
        if self._preview_badge:
            return
        if self._latest_badge:
            return
        try:
            # 在标题栏添加彩色徽章（绿色）
            self._latest_badge = InfoBadge.custom(
                "最新",
                QColor("#10b981"),  # 浅色主题背景
                QColor("#34d399"),  # 深色主题背景（更亮的绿色）
                parent=self.titleBar,
            )
            # 将徽章添加到标题栏布局
            self.titleBar.hBoxLayout.insertWidget(2, self._latest_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            logging.debug("显示最新版徽章失败", exc_info=True)

    def _show_outdated_badge(self):
        """在标题栏显示过时版本徽章（红色）"""
        if self._outdated_badge:
            return
        # 如果有预览徽章，先移除它（过时优先级更高）
        if self._preview_badge:
            try:
                self.titleBar.hBoxLayout.removeWidget(self._preview_badge)
                self._preview_badge.deleteLater()
                self._preview_badge = None
            except Exception:
                logging.debug("清理预览版徽章失败", exc_info=True)
        try:
            # 在标题栏添加红色徽章
            self._outdated_badge = InfoBadge.custom(
                "过时",
                QColor("#ef4444"),  # 浅色主题背景（红色）
                QColor("#fd3c3c"),  # 深色主题背景（更亮的红色）
                parent=self.titleBar,
            )
            # 将徽章添加到标题栏布局
            self.titleBar.hBoxLayout.insertWidget(2, self._outdated_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            logging.debug("显示可更新徽章失败", exc_info=True)

    def _check_preview_version(self):
        """检查是否为预览版本，如果是则显示预览徽章"""
        if "pre" in __VERSION__.lower():
            self._show_preview_badge()

    def _show_preview_badge(self):
        """在标题栏显示预览版本徽章（黄色）"""
        if self._preview_badge:
            return
        try:
            # 在标题栏添加黄色徽章
            self._preview_badge = InfoBadge.custom(
                "预览",
                QColor("#f59e0b"),  # 浅色主题背景（黄色）
                QColor("#fbbf24"),  # 深色主题背景（更亮的黄色）
                parent=self.titleBar,
            )
            # 将徽章添加到标题栏布局
            self.titleBar.hBoxLayout.insertWidget(2, self._preview_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            logging.debug("显示预览版徽章失败", exc_info=True)

    def _notify_latest_version(self):
        """通知已是最新版本（从后台线程安全调用）"""
        self.isLatestVersion.emit()

    def _show_download_toast(self, total_size: int = 0, show_spinner: bool = False):
        """显示下载进度Toast（右下角）"""
        if self._download_infobar:
            return

        self._download_indeterminate = show_spinner or total_size == 0

        # 创建右下角InfoBar（使用蓝色主题色）
        self._download_infobar = InfoBar(
            icon=InfoBarIcon.INFORMATION,
            title="",
            content="正在下载文件中，请稍候...",
            orient=Qt.Orientation.Vertical,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=-1,
            parent=self,
        )
        self._download_infobar.closeButton.clicked.connect(self._cancel_download)

        # 创建容器
        self._download_container = QWidget()
        self._download_layout = QVBoxLayout(self._download_container)
        self._download_layout.setContentsMargins(0, 4, 0, 0)
        self._download_layout.setSpacing(4)

        # 进度详情标签
        self._download_detail_label = CaptionLabel("正在连接服务器...")
        self._download_detail_label.setStyleSheet("color: gray;")
        self._download_layout.addWidget(self._download_detail_label)

        if self._download_indeterminate:
            # 不确定进度条（加载动画）
            self._download_indeterminate_bar = IndeterminateProgressBar()
            self._download_indeterminate_bar.setFixedSize(220, 4)
            self._download_layout.addWidget(self._download_indeterminate_bar)
            self._download_progress_bar = None
        else:
            # 确定进度条
            self._download_indeterminate_bar = None
            self._download_progress_bar = ProgressBar()
            self._download_progress_bar.setFixedSize(220, 4)
            self._download_progress_bar.setRange(0, 100)
            self._download_progress_bar.setValue(0)
            self._download_progress_bar.setTextVisible(False)
            self._download_layout.addWidget(self._download_progress_bar)

        self._download_infobar.addWidget(self._download_container)
        self._download_infobar.show()

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def _format_speed(self, speed: float) -> str:
        """格式化下载速度"""
        if speed < 1024:
            return f"{speed:.0f} B/s"
        if speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        return f"{speed / (1024 * 1024):.1f} MB/s"

    def _update_download_progress(self, downloaded: int, total: int, speed: float = 0):
        """更新下载进度"""
        if not self._download_infobar:
            self._show_download_toast(total)

        # 如果当前是不确定进度条，切换到确定进度条
        if total > 0 and getattr(self, "_download_indeterminate", False):
            self._switch_to_determinate_progress()

        if total > 0 and self._download_progress_bar:
            percent = int((downloaded / total) * 100)
            self._download_progress_bar.setValue(percent)

        # 更新详情标签
        if hasattr(self, "_download_detail_label") and self._download_detail_label:
            detail = f"{self._format_size(downloaded)} / {self._format_size(total)}"
            if speed > 0:
                detail += f" | {self._format_speed(speed)}"
            self._download_detail_label.setText(detail)

        # 下载完成时延迟关闭Toast并显示成功提示
        if downloaded >= total and total > 0:
            QTimer.singleShot(100, self._on_download_complete)

    def _on_download_complete(self):
        """下载完成时关闭进度Toast并显示成功提示"""
        self._close_download_toast()
        self._toast("下载完成", "success")

    def _switch_to_determinate_progress(self):
        """从不确定进度条切换到确定进度条"""
        self._download_indeterminate = False

        # 移除不确定进度条
        if hasattr(self, "_download_indeterminate_bar") and self._download_indeterminate_bar:
            self._download_layout.removeWidget(self._download_indeterminate_bar)
            self._download_indeterminate_bar.deleteLater()
            self._download_indeterminate_bar = None

        # 添加确定进度条
        self._download_progress_bar = ProgressBar()
        self._download_progress_bar.setFixedSize(220, 4)
        self._download_progress_bar.setRange(0, 100)
        self._download_progress_bar.setValue(0)
        self._download_progress_bar.setTextVisible(False)
        self._download_layout.addWidget(self._download_progress_bar)

    def _on_download_started(self):
        """下载开始时显示转圈动画"""
        self._show_download_toast(0, show_spinner=True)

    def _cancel_download(self):
        """取消下载"""
        self._download_cancelled = True
        self._close_download_toast()
        self._toast("下载已取消", "warning")

    def _close_download_toast(self):
        """安全关闭下载进度Toast"""
        if self._download_infobar:
            try:
                self._download_infobar.close()
            except Exception:
                logging.debug("关闭下载进度提示失败", exc_info=True)
            self._download_infobar = None
            self._download_progress_bar = None
            self._download_detail_label = None
            self._download_indeterminate_bar = None
            self._download_indeterminate = False

    def _emit_download_progress(self, downloaded: int, total: int, speed: float = 0):
        """从后台线程安全地发送下载进度信号"""
        self.downloadProgress.emit(downloaded, total, speed)

    def _on_download_finished(self, downloaded_file: str):
        """下载完成后在主线程显示弹窗"""
        from wjx.utils.update.updater import UpdateManager

        should_launch = self._log_popup_confirm(
            "更新完成",
            f"新版本已下载到:\n{downloaded_file}\n\n是否立即运行新版本？",
        )
        UpdateManager.schedule_running_executable_deletion(downloaded_file)
        if should_launch:
            try:
                subprocess.Popen([downloaded_file])
                self._skip_save_on_close = True
                self.close()
            except Exception as exc:
                logging.error("[Action Log] Failed to launch downloaded update")
                self._log_popup_error("启动失败", f"无法启动新版本: {exc}")
        else:
            logging.debug("[Action Log] Deferred launching downloaded update")

    def _on_download_failed(self, error_msg: str):
        """下载失败后在主线程显示弹窗"""
        if not getattr(self, "_download_cancelled", False):
            self._log_popup_error("更新失败", error_msg)

    def _on_mirror_switched(self, new_mirror_key: str):
        """镜像源切换时更新设置页面的下拉框"""
        try:
            # 更新设置页面的下拉框
            if hasattr(self, "_settings_page") and self._settings_page and hasattr(self._settings_page, "mirror_combo"):
                idx = self._settings_page.mirror_combo.findData(new_mirror_key)
                if idx >= 0:
                    self._settings_page.mirror_combo.blockSignals(True)
                    self._settings_page.mirror_combo.setCurrentIndex(idx)
                    self._settings_page.mirror_combo.blockSignals(False)
            # 显示提示
            mirror_label = GITHUB_MIRROR_SOURCES.get(new_mirror_key, {}).get("label", new_mirror_key)
            self._toast(f"已自动切换到镜像源: {mirror_label}", "info")
        except Exception:
            logging.warning("切换镜像源后同步 UI 状态失败", exc_info=True)
