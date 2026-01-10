"""关于页面"""
import os
import re
import sys
import threading
import subprocess
import webbrowser
from typing import Optional
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    PushButton,
    PrimaryPushButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    TextBrowser,
    ProgressBar,
)

from wjx.utils.load_save import get_runtime_directory
from wjx.utils.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO


def _convert_github_admonitions(text: str) -> str:
    """将 GitHub Flavored Markdown 的 admonition 语法转换为标准格式"""
    # 匹配 > [!NOTE], > [!TIP], > [!IMPORTANT], > [!WARNING], > [!CAUTION] 等
    admonition_map = {
        "NOTE": "**注意：**",
        "TIP": "**提示：**",
        "IMPORTANT": "**重要：**",
        "WARNING": "**警告：**",
        "CAUTION": "**警告：**",
    }
    
    def replace_admonition(match):
        admonition_type = match.group(1).upper()
        content = match.group(2).strip()
        prefix = admonition_map.get(admonition_type, f"**{admonition_type}：**")
        return f"{prefix} {content}"
    
    # 匹配多行 admonition: > [!TYPE]\n> content
    pattern = r'>\s*\[!(\w+)\]\s*\n((?:>.*\n?)*)'
    
    def replace_multiline(match):
        admonition_type = match.group(1).upper()
        content_lines = match.group(2)
        # 移除每行开头的 > 
        content = re.sub(r'^>\s?', '', content_lines, flags=re.MULTILINE).strip()
        prefix = admonition_map.get(admonition_type, f"**{admonition_type}：**")
        return f"{prefix}\n\n{content}"
    
    text = re.sub(pattern, replace_multiline, text)
    
    # 匹配单行 admonition: > [!TYPE] content
    single_pattern = r'>\s*\[!(\w+)\]\s*(.+)'
    text = re.sub(single_pattern, replace_admonition, text)
    
    return text


class DownloadProgressDialog(MessageBox):
    """下载进度对话框"""
    
    _progressUpdated = Signal(int, int)  # downloaded, total
    _downloadFinished = Signal(str)  # file_path or empty on error
    
    def __init__(self, parent=None):
        super().__init__("正在下载更新", "", parent)
        self._downloaded_file = None
        self._last_downloaded = 0
        self._last_time = datetime.now()
        self._speed = 0.0
        self._progressUpdated.connect(self._update_progress)
        self._downloadFinished.connect(self._on_download_finished)
        
        # 隐藏默认按钮和按钮区域
        self.yesButton.hide()
        self.cancelButton.hide()
        self.buttonGroup.hide()
        
        # 清除默认内容
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        
        # 进度信息
        self.status_label = BodyLabel("正在连接服务器...", self)
        self.textLayout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(400)
        self.textLayout.addWidget(self.progress_bar)
        
        # 进度文本
        self.progress_label = BodyLabel("0%", self)
        self.progress_label.setStyleSheet("color: #888;")
        self.textLayout.addWidget(self.progress_label)
        
        # 调整对话框高度
        self.widget.setFixedHeight(160)
    
    def _format_speed(self, speed: float) -> str:
        if speed >= 1024 * 1024:
            return f"{speed / 1024 / 1024:.1f} MB/s"
        elif speed >= 1024:
            return f"{speed / 1024:.1f} KB/s"
        return f"{speed:.0f} B/s"
    
    def _update_progress(self, downloaded: int, total: int):
        now = datetime.now()
        elapsed = (now - self._last_time).total_seconds()
        if elapsed >= 0.5:  # 每0.5秒更新一次速度
            self._speed = (downloaded - self._last_downloaded) / elapsed
            self._last_downloaded = downloaded
            self._last_time = now
        
        speed_str = self._format_speed(self._speed)
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.progress_bar.setValue(percent)
            self.progress_label.setText(f"{percent}% ({downloaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB)")
            self.status_label.setText(f"正在下载... {speed_str}")
        else:
            self.status_label.setText(f"正在下载... ({downloaded / 1024 / 1024:.1f} MB) {speed_str}")
    
    def _on_download_finished(self, file_path: str):
        self._downloaded_file = file_path
        if file_path:
            self.progress_bar.setValue(100)
            self.status_label.setText("下载完成！")
            self.progress_label.setText("100%")
        else:
            self.progress_bar.error()
            self.status_label.setText("下载失败")
        QTimer.singleShot(500, self.accept)
    
    def start_download(self, update_info: dict):
        """开始下载"""
        def _do_download():
            try:
                from wjx.utils.updater import UpdateManager
                file_path = UpdateManager.download_update(
                    update_info["download_url"],
                    update_info["file_name"],
                    progress_callback=lambda d, t: self._progressUpdated.emit(d, t)
                )
                self._downloadFinished.emit(file_path or "")
            except Exception:
                self._downloadFinished.emit("")
        
        threading.Thread(target=_do_download, daemon=True).start()
    
    def get_downloaded_file(self) -> Optional[str]:
        return self._downloaded_file


class UpdateDialog(MessageBox):
    """支持Markdown显示发行文档的更新对话框"""
    
    def __init__(self, current_version: str, new_version: str, release_notes: str, parent=None):
        super().__init__("检查到更新", "检测到新版本！", parent)
        self.yesButton.setText("立即更新")
        self.cancelButton.setText("稍后再说")
        
        # 清除默认内容，重新构建
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        
        # 版本信息
        version_label = BodyLabel(f"当前版本: v{current_version}\n新版本: v{new_version}", self)
        self.textLayout.addWidget(version_label)
        
        # 发行文档（Markdown）
        notes_label = BodyLabel("发行说明:", self)
        notes_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        self.textLayout.addWidget(notes_label)
        
        notes_browser = TextBrowser(self)
        processed_notes = _convert_github_admonitions(release_notes) if release_notes else "暂无更新说明"
        notes_browser.setMarkdown(processed_notes)
        notes_browser.setOpenExternalLinks(True)
        notes_browser.setFixedSize(450, 250)
        notes_browser.setStyleSheet("border: 1px solid #444; border-radius: 4px;")
        self.textLayout.addWidget(notes_browser)
        
        # 确认提示
        confirm_label = BodyLabel("\n是否立即更新？", self)
        self.textLayout.addWidget(confirm_label)


class AboutPage(ScrollArea):
    """关于页面，包含版本号、链接、检查更新等。"""

    _updateCheckFinished = Signal(object)  # update_info or None
    _updateCheckError = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updateCheckFinished.connect(self._on_update_result)
        self._updateCheckError.connect(self._on_update_error)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._checking_update = False
        self._progress_dlg: Optional[DownloadProgressDialog] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 软件信息
        layout.addWidget(SubtitleLabel("软件信息", self))
        version_text = BodyLabel(f"fuck-wjx（问卷星速填）\n当前版本：v{__VERSION__}", self)
        version_text.setWordWrap(True)
        layout.addWidget(version_text)

        # 检查更新按钮
        update_row = QHBoxLayout()
        update_row.setSpacing(8)
        self.update_btn = PrimaryPushButton("检查更新", self)
        self.update_spinner = IndeterminateProgressRing(self)
        self.update_spinner.setFixedSize(18, 18)
        self.update_spinner.setStrokeWidth(2)
        self.update_spinner.hide()
        update_row.addWidget(self.update_btn)
        update_row.addWidget(self.update_spinner)
        update_row.addStretch(1)
        layout.addLayout(update_row)

        layout.addSpacing(16)

        # 相关链接
        layout.addWidget(SubtitleLabel("相关链接", self))
        links_text = BodyLabel(
            f"GitHub: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"官网: https://www.hungrym0.top/fuck-wjx.html\n"
            f"邮箱: hungrym0@qq.com",
            self
        )
        links_text.setWordWrap(True)
        layout.addWidget(links_text)

        link_btn_row = QHBoxLayout()
        link_btn_row.setSpacing(10)
        self.github_btn = PushButton("访问 GitHub", self)
        self.website_btn = PushButton("访问官网", self)
        link_btn_row.addWidget(self.github_btn)
        link_btn_row.addWidget(self.website_btn)
        link_btn_row.addStretch(1)
        layout.addLayout(link_btn_row)

        layout.addStretch(1)

        # 版权信息
        copyright_text = BodyLabel("©2026 HUNGRY_M0 版权所有  MIT License", self)
        copyright_text.setStyleSheet("color: #888;")
        layout.addWidget(copyright_text)

        # 绑定事件
        self.update_btn.clicked.connect(self._check_updates)
        self.github_btn.clicked.connect(lambda: webbrowser.open(f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"))
        self.website_btn.clicked.connect(lambda: webbrowser.open("https://www.hungrym0.top/fuck-wjx.html"))

    def _set_update_loading(self, loading: bool):
        self._checking_update = loading
        self.update_btn.setEnabled(not loading)
        if loading:
            self.update_btn.setText("检查中...")
            self.update_spinner.show()
        else:
            self.update_btn.setText("检查更新")
            self.update_spinner.hide()

    def _on_update_result(self, update_info):
        """处理更新检查结果（在主线程中执行）"""
        self._set_update_loading(False)
        win = self.window()
        if update_info:
            if hasattr(win, 'update_info'):
                win.update_info = update_info  # type: ignore[union-attr]
            dlg = UpdateDialog(
                update_info['current_version'],
                update_info['version'],
                update_info.get('release_notes', ''),
                win
            )
            if dlg.exec():
                self._start_download(update_info)
        else:
            InfoBar.success("", f"当前已是最新版本 v{__VERSION__}", parent=win, position=InfoBarPosition.TOP, duration=3000)

    def _start_download(self, update_info: dict):
        """开始下载更新并显示进度"""
        win = self.window()
        self._progress_dlg = DownloadProgressDialog(win)
        self._progress_dlg.finished.connect(self._on_progress_dialog_closed)
        self._progress_dlg.start_download(update_info)
        self._progress_dlg.show()

    def _on_progress_dialog_closed(self):
        """进度对话框关闭后处理"""
        if self._progress_dlg is None:
            return
        self._downloaded_file_result = self._progress_dlg.get_downloaded_file()
        self._progress_dlg.deleteLater()
        self._progress_dlg = None
        
        # 延迟显示下一个对话框
        QTimer.singleShot(200, self._show_download_result_delayed)

    def _show_download_result_delayed(self):
        """延迟显示下载结果"""
        self._show_download_result(self._downloaded_file_result)

    def _show_download_result(self, downloaded_file: Optional[str]):
        """显示下载结果"""
        win = self.window()
        if downloaded_file:
            from wjx.utils.updater import UpdateManager
            box = MessageBox("更新完成", f"新版本已下载到:\n{downloaded_file}\n\n是否立即运行新版本？", win)
            box.yesButton.setText("立即运行")
            box.cancelButton.setText("稍后")
            UpdateManager.schedule_running_executable_deletion(downloaded_file)
            if box.exec():
                try:
                    subprocess.Popen([downloaded_file])
                    QApplication.quit()
                except Exception as exc:
                    InfoBar.error("", f"启动失败: {exc}", parent=win, position=InfoBarPosition.TOP, duration=3000)
        else:
            InfoBar.error("", "下载失败，请稍后重试", parent=win, position=InfoBarPosition.TOP, duration=3000)

    def _on_update_error(self, error_msg: str):
        """处理更新检查错误（在主线程中执行）"""
        self._set_update_loading(False)
        InfoBar.error("", f"检查更新失败：{error_msg}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _check_updates(self):
        if self._checking_update:
            return
        self._set_update_loading(True)
        
        def _do_check():
            try:
                from wjx.utils.updater import UpdateManager
                update_info = UpdateManager.check_updates()
                self._updateCheckFinished.emit(update_info)
            except Exception as exc:
                self._updateCheckError.emit(str(exc))
        
        threading.Thread(target=_do_check, daemon=True).start()
