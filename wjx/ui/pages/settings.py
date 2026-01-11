"""界面设置页面"""
import sys
import subprocess

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from qfluentwidgets import (
    ScrollArea,
    SettingCardGroup,
    PushSettingCard,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
)

from wjx.ui.pages.runtime import SwitchSettingCard


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

        # 界面设置组
        self.ui_group = SettingCardGroup("界面设置", self.view)

        # 侧边栏展开设置卡片
        self.sidebar_card = SwitchSettingCard(
            FluentIcon.MENU,
            "始终展开侧边栏",
            "开启后侧边栏将始终保持展开状态",
            self.ui_group
        )
        self.sidebar_card.setChecked(True)
        self.ui_group.addSettingCard(self.sidebar_card)

        # 重启程序设置卡片
        self.restart_card = PushSettingCard(
            text="重启",
            icon=FluentIcon.SYNC,
            title="重新启动程序",
            content="重启程序以应用某些设置更改",
            parent=self.ui_group
        )
        self.ui_group.addSettingCard(self.restart_card)

        layout.addWidget(self.ui_group)

        # 软件更新组
        self.update_group = SettingCardGroup("软件更新", self.view)

        # 启动时检查更新开关
        self.auto_update_card = SwitchSettingCard(
            FluentIcon.UPDATE,
            "在应用程序启动时检查更新",
            "新版本将更加稳定并拥有更多功能（建议启用此选项）",
            self.update_group
        )
        # 从设置中读取，默认开启
        settings = QSettings("FuckWjx", "Settings")
        self.auto_update_card.setChecked(settings.value("auto_check_update", True, type=bool))
        self.update_group.addSettingCard(self.auto_update_card)

        layout.addWidget(self.update_group)
        layout.addStretch(1)

        # 绑定事件
        self.sidebar_card.switchButton.checkedChanged.connect(self._on_sidebar_toggled)
        self.restart_card.clicked.connect(self._restart_program)
        self.auto_update_card.switchButton.checkedChanged.connect(self._on_auto_update_toggled)

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
                InfoBar.success(
                    "",
                    f"侧边栏已设置为{'始终展开' if checked else '可折叠'}",
                    parent=win,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
            except Exception:
                pass

    def _restart_program(self):
        """重启程序"""
        box = MessageBox(
            "重启程序",
            "确定要重新启动程序吗？\n未保存的配置将会丢失。",
            self.window() or self
        )
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
                InfoBar.error(
                    "",
                    f"重启失败：{exc}",
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=3000
                )

    def _on_auto_update_toggled(self, checked: bool):
        """自动检查更新开关切换"""
        settings = QSettings("FuckWjx", "Settings")
        settings.setValue("auto_check_update", checked)
        InfoBar.success(
            "",
            f"启动时检查更新已{'开启' if checked else '关闭'}",
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=2000
        )
