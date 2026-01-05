"""关于页面"""
import os
import sys
import threading
import subprocess
import webbrowser
from typing import Optional

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
    CardWidget,
    PushButton,
    PrimaryPushButton,
    SwitchButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    MessageBox,
)

from wjx.utils.load_save import get_runtime_directory
from wjx.utils.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO


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
            msg = (
                f"检测到新版本！\n\n"
                f"当前版本: v{update_info['current_version']}\n"
                f"新版本: v{update_info['version']}\n\n"
                f"是否立即更新？"
            )
            dlg = MessageBox("检查到更新", msg, win)
            dlg.yesButton.setText("立即更新")
            dlg.cancelButton.setText("稍后再说")
            if dlg.exec():
                from wjx.utils.updater import perform_update
                perform_update(win)
        else:
            InfoBar.success("", f"当前已是最新版本 v{__VERSION__}", parent=win, position=InfoBarPosition.TOP, duration=3000)

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
