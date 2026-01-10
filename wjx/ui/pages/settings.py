"""界面设置页面"""
import os
import sys
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    SwitchButton,
    InfoBar,
    InfoBarPosition,
    MessageBox,
)


class SettingsPage(ScrollArea):
    """界面设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(SubtitleLabel("界面设置", self))

        # 界面设置卡片
        settings_card = CardWidget(self.view)
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(12)

        # 侧边栏展开设置
        sidebar_row = QHBoxLayout()
        sidebar_label = BodyLabel("始终展开侧边栏", self)
        self.sidebar_switch = SwitchButton(self)
        self._pin_switch_label(self.sidebar_switch, "")
        self.sidebar_switch.setChecked(True)
        sidebar_row.addWidget(sidebar_label)
        sidebar_row.addStretch(1)
        sidebar_row.addWidget(self.sidebar_switch)
        settings_layout.addLayout(sidebar_row)

        # 重启程序按钮
        restart_row = QHBoxLayout()
        restart_label = BodyLabel("重新启动程序", self)
        self.restart_btn = PushButton("重启", self)
        restart_row.addWidget(restart_label)
        restart_row.addStretch(1)
        restart_row.addWidget(self.restart_btn)
        settings_layout.addLayout(restart_row)

        layout.addWidget(settings_card)
        layout.addStretch(1)

        # 绑定事件
        self.sidebar_switch.checkedChanged.connect(self._on_sidebar_toggled)
        self.restart_btn.clicked.connect(self._restart_program)

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
        nav = getattr(win, "navigationInterface", None)
        if nav is not None:
            try:
                if checked:
                    nav.setCollapsible(False)
                    nav.expand()
                else:
                    nav.setCollapsible(True)
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
                    setattr(win, '_skip_save_on_close', True)
                subprocess.Popen([sys.executable] + sys.argv)
                QApplication.quit()
            except Exception as exc:
                InfoBar.error("", f"重启失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
