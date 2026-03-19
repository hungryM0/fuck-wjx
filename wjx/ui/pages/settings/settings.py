"""应用程序设置页面"""
import sys
import subprocess
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from qfluentwidgets import (
    ScrollArea,
    SettingCardGroup,
    SettingCard,
    PushSettingCard,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    ComboBox,
)

from wjx.ui.widgets.setting_cards import SwitchSettingCard
from wjx.utils.app.config import DOWNLOAD_SOURCES, DEFAULT_DOWNLOAD_SOURCE, app_settings, get_bool_from_qsettings


class SettingsPage(ScrollArea):
    """应用程序设置页面"""



    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 从设置中读取配置
        settings = app_settings()

        # 界面外观组
        self.appearance_group = SettingCardGroup("界面外观", self.view)

        # 侧边栏展开设置卡片
        self.sidebar_card = SwitchSettingCard(
            FluentIcon.MENU,
            "始终展开侧边栏",
            "开启后侧边栏将始终保持展开状态",
            self.appearance_group
        )
        self.sidebar_card.setChecked(get_bool_from_qsettings(settings.value("sidebar_always_expand"), True))
        self.appearance_group.addSettingCard(self.sidebar_card)

        # 窗口置顶设置卡片
        self.topmost_card = SwitchSettingCard(
            FluentIcon.PIN,
            "窗口置顶",
            "开启后程序窗口将始终保持在最上层",
            self.appearance_group
        )
        self.topmost_card.setChecked(get_bool_from_qsettings(settings.value("window_topmost"), False))
        self.appearance_group.addSettingCard(self.topmost_card)

        layout.addWidget(self.appearance_group)

        # 行为设置组
        self.behavior_group = SettingCardGroup("行为设置", self.view)

        # 关闭前询问保存设置卡片
        self.ask_save_card = SwitchSettingCard(
            FluentIcon.SAVE,
            "关闭前询问是否保存",
            "关闭窗口时提示是否保存当前配置",
            self.behavior_group
        )
        self.ask_save_card.setChecked(get_bool_from_qsettings(settings.value("ask_save_on_close"), True))
        self.behavior_group.addSettingCard(self.ask_save_card)

        layout.addWidget(self.behavior_group)

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
        settings = app_settings()
        self.auto_update_card.setChecked(get_bool_from_qsettings(settings.value("auto_check_update"), True))
        self.update_group.addSettingCard(self.auto_update_card)

        # 下载源选择
        self.download_source_card = SettingCard(
            FluentIcon.DOWNLOAD,
            "下载源",
            "选择用于下载更新的源（如果下载速度较慢，可以尝试切换到其他源）",
            self.update_group
        )
        self.download_source_combo = ComboBox(self.download_source_card)
        self.download_source_combo.setMinimumWidth(180)
        for key, source in DOWNLOAD_SOURCES.items():
            self.download_source_combo.addItem(source["label"], userData=key)
        saved_source = str(settings.value("download_source", DEFAULT_DOWNLOAD_SOURCE)).strip()
        idx = self.download_source_combo.findData(saved_source)
        if idx >= 0:
            self.download_source_combo.setCurrentIndex(idx)
        self.download_source_card.hBoxLayout.addWidget(self.download_source_combo, 0, Qt.AlignmentFlag.AlignRight)
        self.download_source_card.hBoxLayout.addSpacing(16)
        self.update_group.addSettingCard(self.download_source_card)

        layout.addWidget(self.update_group)

        # 系统工具组
        self.tools_group = SettingCardGroup("系统工具", self.view)

        # 重启程序设置卡片
        self.restart_card = PushSettingCard(
            text="重启",
            icon=FluentIcon.SYNC,
            title="重新启动程序",
            content="重启程序以应用某些设置更改",
            parent=self.tools_group
        )
        self.tools_group.addSettingCard(self.restart_card)

        # 恢复默认设置卡片
        self.reset_ui_card = PushSettingCard(
            text="恢复默认",
            icon=FluentIcon.BROOM,
            title="恢复默认设置",
            content="恢复所有设置项的默认值",
            parent=self.tools_group
        )
        self.tools_group.addSettingCard(self.reset_ui_card)

        layout.addWidget(self.tools_group)

        layout.addStretch(1)

        # 绑定事件
        self.sidebar_card.switchButton.checkedChanged.connect(self._on_sidebar_toggled)
        self.topmost_card.switchButton.checkedChanged.connect(self._on_topmost_toggled)
        self.ask_save_card.switchButton.checkedChanged.connect(self._on_ask_save_on_close_toggled)
        self.restart_card.clicked.connect(self._restart_program)
        self.reset_ui_card.clicked.connect(self._on_reset_ui_settings)
        self.auto_update_card.switchButton.checkedChanged.connect(self._on_auto_update_toggled)
        self.download_source_combo.currentIndexChanged.connect(self._on_download_source_changed)

    def _set_switch_state(self, card: SwitchSettingCard, checked: bool):
        btn = getattr(card, "switchButton", None)
        if btn is None:
            return
        btn.blockSignals(True)
        card.setChecked(checked)
        btn.blockSignals(False)

    def _apply_sidebar_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("sidebar_always_expand", checked)
        win = self.window()
        nav = getattr(win, "navigationInterface", None)
        if nav is not None:
            try:
                if checked:
                    nav.setCollapsible(False)
                    nav.expand()
                else:
                    nav.setCollapsible(True)
                    if hasattr(nav, "panel"):
                        nav.panel.collapse()
            except Exception as exc:
                log_suppressed_exception("_apply_sidebar_state: if checked: nav.setCollapsible(False) nav.expand() else: nav.setCollapsible(T...", exc, level=logging.WARNING)

    def _apply_topmost_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("window_topmost", checked)
        win = self.window()
        if win:
            win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
            win.show()

    def _apply_ask_save_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("ask_save_on_close", checked)

    def _apply_auto_update_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("auto_check_update", checked)

    def _on_sidebar_toggled(self, checked: bool):
        """侧边栏展开切换"""
        self._apply_sidebar_state(checked)

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
        self._apply_auto_update_state(checked)

    def _on_topmost_toggled(self, checked: bool):
        """窗口置顶切换"""
        self._apply_topmost_state(checked)

    def _on_ask_save_on_close_toggled(self, checked: bool):
        """关闭前询问保存切换"""
        self._apply_ask_save_state(checked)

    def _on_reset_ui_settings(self):
        """恢复默认设置"""
        box = MessageBox(
            "恢复默认设置",
            "确定要恢复默认设置吗？\n这将还原所有设置项到初始状态。",
            self.window() or self
        )
        box.yesButton.setText("恢复")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        settings = app_settings()
        for key in ("sidebar_always_expand", "window_topmost", "ask_save_on_close", "auto_check_update"):
            settings.remove(key)

        defaults = {
            "sidebar_always_expand": True,
            "window_topmost": False,
            "ask_save_on_close": True,
            "auto_check_update": True,
        }
        self._set_switch_state(self.sidebar_card, defaults["sidebar_always_expand"])
        self._set_switch_state(self.topmost_card, defaults["window_topmost"])
        self._set_switch_state(self.ask_save_card, defaults["ask_save_on_close"])
        self._set_switch_state(self.auto_update_card, defaults["auto_check_update"])
        self._apply_sidebar_state(defaults["sidebar_always_expand"], persist=False)
        self._apply_topmost_state(defaults["window_topmost"], persist=False)
        InfoBar.success(
            "",
            "已恢复默认设置",
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=2000
        )

    def _on_download_source_changed(self):
        """下载源选择变化"""
        idx = self.download_source_combo.currentIndex()
        source_key = str(self.download_source_combo.itemData(idx)) if idx >= 0 else DEFAULT_DOWNLOAD_SOURCE
        settings = app_settings()
        settings.setValue("download_source", source_key)

