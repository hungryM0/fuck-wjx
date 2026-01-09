"""关于页面"""
import os
import re
import sys
import threading
import subprocess
import webbrowser
from typing import Optional, List, Dict, Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    SwitchButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    FluentIcon,
    TransparentToolButton,
    TextBrowser,
    Dialog,
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


class ReleaseCard(CardWidget):
    """单个发行版卡片，支持展开/折叠"""
    
    def __init__(self, version: str, date: str, body: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self._body = body
        self._build_ui(version, date)
        self.setExpanded(expanded)
    
    def _build_ui(self, version: str, date: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # 标题行
        header = QHBoxLayout()
        header.setSpacing(8)
        
        self.expand_btn = TransparentToolButton(FluentIcon.CHEVRON_RIGHT_MED, self)
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.clicked.connect(self._toggle)
        header.addWidget(self.expand_btn)
        
        title = BodyLabel(f"v{version}", self)
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title)
        
        date_label = BodyLabel(date, self)
        date_label.setStyleSheet("color: #888;")
        header.addWidget(date_label)
        header.addStretch(1)
        
        layout.addLayout(header)
        
        # 内容区域（支持 Markdown）
        self.content = TextBrowser(self)
        # 转换 GitHub Flavored Markdown 的 admonition 语法
        processed_body = _convert_github_admonitions(self._body) if self._body else "暂无更新说明"
        self.content.setMarkdown(processed_body)
        self.content.setOpenExternalLinks(True)
        self.content.setStyleSheet("border: none; background: transparent; padding-left: 32px;")
        self.content.setMinimumHeight(50)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.content)
    
    def _toggle(self):
        self.setExpanded(not self._expanded)
    
    def setExpanded(self, expanded: bool):
        self._expanded = expanded
        self.content.setVisible(expanded)
        icon = FluentIcon.CHEVRON_DOWN_MED if expanded else FluentIcon.CHEVRON_RIGHT_MED
        self.expand_btn.setIcon(icon)


class AboutPage(ScrollArea):
    """关于页面，包含版本号、链接、检查更新等。"""

    _updateCheckFinished = Signal(object)  # update_info or None
    _updateCheckError = Signal(str)  # error message
    _releasesLoaded = Signal(list)  # releases list

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updateCheckFinished.connect(self._on_update_result)
        self._updateCheckError.connect(self._on_update_error)
        self._releasesLoaded.connect(self._on_releases_loaded)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._checking_update = False
        self._progress_dlg: Optional[DownloadProgressDialog] = None
        self._build_ui()
        self._load_releases()

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

        # 界面设置卡片
        settings_card = CardWidget(self.view)
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(12)
        settings_layout.addWidget(SubtitleLabel("界面设置", self))
        
        # 侧边栏展开设置
        sidebar_row = QHBoxLayout()
        self.sidebar_switch = SwitchButton("始终展开侧边栏", self)
        self._pin_switch_label(self.sidebar_switch, "始终展开侧边栏")
        self.sidebar_switch.setChecked(True)
        sidebar_row.addWidget(self.sidebar_switch)
        sidebar_row.addStretch(1)
        settings_layout.addLayout(sidebar_row)
        
        # 重启程序按钮
        restart_row = QHBoxLayout()
        self.restart_btn = PushButton("重新启动程序", self)
        restart_row.addWidget(self.restart_btn)
        restart_row.addStretch(1)
        settings_layout.addLayout(restart_row)
        
        layout.addWidget(settings_card)
        layout.addSpacing(16)

        # 更新日志区域
        changelog_header = QHBoxLayout()
        changelog_header.setSpacing(8)
        layout.addWidget(SubtitleLabel("更新日志", self))
        
        self.changelog_spinner = IndeterminateProgressRing(self)
        self.changelog_spinner.setFixedSize(18, 18)
        self.changelog_spinner.setStrokeWidth(2)
        changelog_header.addWidget(self.changelog_spinner)
        changelog_header.addStretch(1)
        layout.addLayout(changelog_header)
        
        # 更新日志容器
        self.changelog_container = QVBoxLayout()
        self.changelog_container.setSpacing(8)
        layout.addLayout(self.changelog_container)
        
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
        self.sidebar_switch.checkedChanged.connect(self._on_sidebar_toggled)
        self.restart_btn.clicked.connect(self._restart_program)
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

    def _pin_switch_label(self, sw: SwitchButton, text: str):
        """保持开关两侧文本一致"""
        try:
            sw.setOnText(text)
            sw.setOffText(text)
            sw.setText(text)
        except Exception:
            sw.setText(text)

    def _on_sidebar_toggled(self, checked: bool):
        """侧边栏展开切换"""
        win = self.window()
        if hasattr(win, "navigationInterface"):
            try:
                if checked:
                    win.navigationInterface.setCollapsible(False)  # type: ignore[union-attr]
                    win.navigationInterface.expand()  # type: ignore[union-attr]
                else:
                    win.navigationInterface.setCollapsible(True)  # type: ignore[union-attr]
                InfoBar.success("", f"侧边栏已设置为{'始终展开' if checked else '可折叠'}", parent=win, position=InfoBarPosition.TOP, duration=2000)
            except Exception:
                pass

    def _restart_program(self):
        """重启程序"""
        box = MessageBox("重启程序", "确定要重新启动程序吗？\n未保存的配置将会丢失。", self.window() or self)
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if box.exec():
            try:
                win = self.window()
                if hasattr(win, '_skip_save_on_close'):
                    win._skip_save_on_close = True  # type: ignore[attr-defined]
                subprocess.Popen([sys.executable] + sys.argv)
                QApplication.quit()
            except Exception as exc:
                InfoBar.error("", f"重启失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    def _load_releases(self):
        """异步加载发行版列表"""
        def _do_load():
            try:
                from wjx.utils.updater import UpdateManager
                releases = UpdateManager.get_all_releases()
                self._releasesLoaded.emit(releases)
            except Exception:
                self._releasesLoaded.emit([])
        
        threading.Thread(target=_do_load, daemon=True).start()

    def _on_releases_loaded(self, releases: list):
        """处理发行版加载完成"""
        self.changelog_spinner.hide()
        
        if not releases:
            label = BodyLabel("暂无发行版信息", self)
            label.setStyleSheet("color: #888;")
            self.changelog_container.addWidget(label)
            return
        
        for i, release in enumerate(releases):
            version = release.get("version", "")
            body = release.get("body", "")
            published = release.get("published_at", "")
            
            # 格式化日期
            date_str = ""
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = published[:10] if len(published) >= 10 else published
            
            # 第一个版本默认展开
            card = ReleaseCard(version, date_str, body, expanded=(i == 0), parent=self.view)
            self.changelog_container.addWidget(card)
