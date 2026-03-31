"""MainWindow 更新检查与下载提示相关方法。"""
from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
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

from software.app.config import app_settings, get_bool_from_qsettings
from software.app.version import __VERSION__
from software.logging.action_logger import log_action


class MainWindowUpdateMixin:
    """主窗口更新模块方法集合。"""

    if TYPE_CHECKING:
        from typing import Any
        titleBar: Any
        downloadProgress: Any
        _toast: Any
        show_confirm_dialog: Any
        show_message_dialog: Any
        close: Any
        _settings_page: Any
        _update_check_thread: Any
        _update_check_worker: Any

    def _check_update_on_startup(self):
        """根据设置在启动时检查更新（后台异步执行）"""
        settings = app_settings()
        if get_bool_from_qsettings(settings.value("auto_check_update"), True):
            from software.ui.workers.update_worker import UpdateCheckWorker

            from typing import cast
            from PySide6.QtCore import QObject
            self._show_update_checking_placeholder()
            self._stop_update_check_worker()
            worker = UpdateCheckWorker()
            thread = QThread(cast(QObject, self))
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(self._on_update_checked)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(self._clear_update_check_worker_refs)
            self._update_check_worker = worker
            self._update_check_thread = thread
            thread.start()

            logging.info("已启动后台更新检查")

    def _clear_update_check_worker_refs(self):
        self._update_check_thread = None
        self._update_check_worker = None

    def _stop_update_check_worker(self):
        thread = getattr(self, "_update_check_thread", None)
        if thread is None:
            return
        try:
            thread.quit()
            thread.wait(1500)
        except Exception:
            logging.info("停止后台更新检查线程失败", exc_info=True)
        finally:
            self._clear_update_check_worker_refs()

    def _on_update_checked(self, has_update: bool, update_info: dict):
        """更新检查完成的回调"""
        self._clear_update_checking_placeholder()
        status = update_info.get("status", "unknown") if update_info else "unknown"
        if has_update:
            self.update_info = update_info
            self._show_update_notification()
        else:
            self._apply_version_status_badge(status)

    def _apply_version_status_badge(self, status: str):
        """根据版本状态显示对应徽章（latest/preview/unknown）"""
        if status == "latest":
            self._check_preview_version()
            self._show_latest_version_badge()
        elif status == "preview":
            self._show_preview_badge()
        else:
            # unknown：网络失败或无法判断
            self._check_preview_version()
            self._show_unknown_badge()

    def _ensure_title_bar_status_container(self) -> QWidget | None:
        """在标题文字后面准备一个固定状态位，别再把主布局插得像坨屎。"""
        container = getattr(self, "_title_bar_status_container", None)
        if container is not None:
            return container

        title_bar = getattr(self, "titleBar", None)
        layout = getattr(title_bar, "hBoxLayout", None)
        if title_bar is None or layout is None:
            return None

        container = QWidget(title_bar)
        container.hide()
        host_layout = QHBoxLayout(container)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        # InfoBadge 自带的文字基线比标题标签略高一点，底对齐后视觉上才在一条线上。
        host_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        title_label = getattr(title_bar, "titleLabel", None)
        if title_label is not None:
            title_height = max(int(title_label.height() or 0), int(title_label.sizeHint().height() or 0))
            if title_height > 0:
                container.setFixedHeight(title_height)
        insert_index = layout.indexOf(title_label) + 1 if title_label is not None else -1
        if insert_index <= 0:
            insert_index = max(layout.count() - 1, 0)
        layout.insertWidget(insert_index, container, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._title_bar_status_container = container
        self._title_bar_status_layout = host_layout
        return container

    def _mount_title_bar_status_widget(self, widget: QWidget) -> bool:
        """把徽章/转圈统一挂到标题后面的状态位。"""
        container = self._ensure_title_bar_status_container()
        host_layout = getattr(self, "_title_bar_status_layout", None)
        if container is None or host_layout is None:
            return False

        if widget.parent() is not container:
            widget.setParent(container)
        if host_layout.indexOf(widget) < 0:
            host_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        container.show()
        return True

    def _clear_title_bar_status_widget(self, widget: QWidget | None) -> None:
        """从标题状态位移除控件。"""
        if widget is None:
            return

        host_layout = getattr(self, "_title_bar_status_layout", None)
        if host_layout is None:
            return

        host_layout.removeWidget(widget)
        widget.deleteLater()

        container = getattr(self, "_title_bar_status_container", None)
        if container is not None and host_layout.count() == 0:
            container.hide()

    def _show_update_checking_placeholder(self):
        """更新检查期间在标题栏徽章位置显示转圈占位。"""
        if self._update_checking_spinner:
            return
        for attr in ("_latest_badge", "_outdated_badge", "_preview_badge", "_unknown_badge"):
            badge = getattr(self, attr, None)
            if badge is None:
                continue
            try:
                self._clear_title_bar_status_widget(badge)
            except Exception:
                logging.info("移除旧徽章失败", exc_info=True)
            setattr(self, attr, None)
        try:
            spinner = IndeterminateProgressRing(parent=self._ensure_title_bar_status_container() or self.titleBar)
            spinner.setFixedSize(16, 16)
            spinner.setStrokeWidth(2)
            if not self._mount_title_bar_status_widget(spinner):
                spinner.deleteLater()
                return
            self._update_checking_spinner = spinner
        except Exception:
            logging.info("显示更新检查占位失败", exc_info=True)

    def _clear_update_checking_placeholder(self):
        spinner = self._update_checking_spinner
        if spinner is None:
            return
        try:
            self._clear_title_bar_status_widget(spinner)
        except Exception:
            logging.info("清理更新检查占位失败", exc_info=True)
        self._update_checking_spinner = None

    def _show_update_notification(self):
        """显示更新通知并更新标题栏徽章。"""
        self._show_outdated_badge()
        self._do_show_update_notification()

    def _do_show_update_notification(self):
        """实际显示更新通知（使用简单纯文本样式）"""
        if not getattr(self, "update_info", None):
            return
        from software.update.updater import show_update_notification

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
                parent=self._ensure_title_bar_status_container() or self.titleBar,
            )
            if not self._mount_title_bar_status_widget(self._latest_badge):
                self._latest_badge.deleteLater()
                self._latest_badge = None
        except Exception:
            logging.info("显示最新版徽章失败", exc_info=True)

    def _show_unknown_badge(self):
        """在标题栏显示未知状态徽章（灰色，网络失败时使用）"""
        # 预览版优先，不覆盖
        if self._preview_badge:
            return
        if getattr(self, "_unknown_badge", None):
            return
        try:
            self._unknown_badge = InfoBadge.custom(
                "未知",
                QColor("#6b7280"),  # 浅色主题背景（灰色）
                QColor("#9ca3af"),  # 深色主题背景（更亮的灰色）
                parent=self._ensure_title_bar_status_container() or self.titleBar,
            )
            if not self._mount_title_bar_status_widget(self._unknown_badge):
                self._unknown_badge.deleteLater()
                self._unknown_badge = None
        except Exception:
            logging.info("显示未知状态徽章失败", exc_info=True)

    def _show_outdated_badge(self):
        """在标题栏显示过时版本徽章（红色）"""
        if self._outdated_badge:
            return
        # 如果有预览徽章，先移除它（过时优先级更高）
        if self._preview_badge:
            try:
                self._clear_title_bar_status_widget(self._preview_badge)
                self._preview_badge = None
            except Exception:
                logging.info("清理预览版徽章失败", exc_info=True)
        try:
            # 在标题栏添加红色徽章
            self._outdated_badge = InfoBadge.custom(
                "过时",
                QColor("#ef4444"),  # 浅色主题背景（红色）
                QColor("#fd3c3c"),  # 深色主题背景（更亮的红色）
                parent=self._ensure_title_bar_status_container() or self.titleBar,
            )
            if not self._mount_title_bar_status_widget(self._outdated_badge):
                self._outdated_badge.deleteLater()
                self._outdated_badge = None
        except Exception:
            logging.info("显示可更新徽章失败", exc_info=True)

    def _check_preview_version(self):
        """检查是否为预览版本，如果是则显示预览徽章"""
        if "pre" in __VERSION__.lower():
            self._show_preview_badge()

    def _show_preview_badge(self):
        """在标题栏显示预览版本徽章（黄色）"""
        if self._preview_badge:
            if self._update_checking_spinner:
                self._clear_update_checking_placeholder()
            return
        try:
            # 预览徽章优先贴在标题后面，别让更新检测转圈把它顶到右边去。
            if self._update_checking_spinner:
                self._clear_update_checking_placeholder()
            # 在标题栏添加黄色徽章
            self._preview_badge = InfoBadge.custom(
                "预览",
                QColor("#f59e0b"),  # 浅色主题背景（黄色）
                QColor("#fbbf24"),  # 深色主题背景（更亮的黄色）
                parent=self._ensure_title_bar_status_container() or self.titleBar,
            )
            if not self._mount_title_bar_status_widget(self._preview_badge):
                self._preview_badge.deleteLater()
                self._preview_badge = None
        except Exception:
            logging.info("显示预览版徽章失败", exc_info=True)

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
        log_action("UPDATE", "download_update", "download_toast", "main_window", result="cancelled")
        self._close_download_toast()
        self._toast("下载已取消", "warning")

    def _close_download_toast(self):
        """安全关闭下载进度Toast"""
        if self._download_infobar:
            try:
                self._download_infobar.close()
            except Exception:
                logging.info("关闭下载进度提示失败", exc_info=True)
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
        from software.update.updater import UpdateManager

        should_launch = self.show_confirm_dialog(
            "更新完成",
            f"新版本已下载到:\n{downloaded_file}\n\n是否立即安装新版本？",
        )
        UpdateManager.schedule_running_executable_deletion(downloaded_file)
        if should_launch:
            log_action(
                "UPDATE",
                "launch_downloaded_update",
                "downloaded_update",
                "main_window",
                result="confirmed",
                payload={"file": downloaded_file},
            )
            try:
                import sys
                if sys.platform == "darwin":
                    # macOS: 用 open 命令打开 DMG/ZIP
                    subprocess.Popen(["open", downloaded_file])
                else:
                    subprocess.Popen([downloaded_file])
                self._skip_save_on_close = True
                log_action(
                    "UPDATE",
                    "launch_downloaded_update",
                    "downloaded_update",
                    "main_window",
                    result="started",
                    payload={"file": downloaded_file},
                )
                self.close()
            except Exception as exc:
                logging.error("[UPDATE] failed to launch downloaded update")
                log_action(
                    "UPDATE",
                    "launch_downloaded_update",
                    "downloaded_update",
                    "main_window",
                    result="failed",
                    level=logging.ERROR,
                    payload={"file": downloaded_file},
                    detail=exc,
                )
                self.show_message_dialog("启动失败", f"无法启动新版本: {exc}", level="error")
        else:
            log_action(
                "UPDATE",
                "launch_downloaded_update",
                "downloaded_update",
                "main_window",
                result="deferred",
                payload={"file": downloaded_file},
            )

    def _on_download_failed(self, error_msg: str):
        """下载失败后在主线程显示弹窗"""
        if not getattr(self, "_download_cancelled", False):
            self.show_message_dialog("更新失败", error_msg, level="error")

    def _on_download_source_switched(self, new_source_key: str):
        """下载源切换时更新设置页面的下拉框"""
        try:
            # 更新设置页面的下拉框
            if hasattr(self, "_settings_page") and self._settings_page and hasattr(self._settings_page, "download_source_combo"):
                idx = self._settings_page.download_source_combo.findData(new_source_key)
                if idx >= 0:
                    self._settings_page.download_source_combo.blockSignals(True)
                    self._settings_page.download_source_combo.setCurrentIndex(idx)
                    self._settings_page.download_source_combo.blockSignals(False)
        except Exception:
            logging.warning("切换下载源后同步 UI 状态失败", exc_info=True)


