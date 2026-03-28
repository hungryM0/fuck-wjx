"""应用程序设置页面"""
import sys
import subprocess
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    GroupHeaderCardWidget,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    ScrollArea,
)

from software.app.config import (
    DEFAULT_DOWNLOAD_SOURCE,
    DOWNLOAD_SOURCES,
    NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
    app_settings,
    get_bool_from_qsettings,
)
from software.logging.action_logger import bind_logged_action, log_action
from software.logging.log_utils import log_suppressed_exception
from software.ui.pages.settings.group_widgets import (
    ActionButtonGroupWidget,
    ComboBoxGroupWidget,
    SwitchGroupWidget,
)


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

        settings = app_settings()

        self.appearance_group = GroupHeaderCardWidget("界面外观", self.view)
        self.navigation_text_card = SwitchGroupWidget(self.appearance_group)
        self.navigation_text_card.setChecked(self._read_navigation_text_visible_setting())
        self.topmost_card = SwitchGroupWidget(self.appearance_group)
        self.topmost_card.setChecked(get_bool_from_qsettings(settings.value("window_topmost"), False))
        self.appearance_group.addGroup(
            FluentIcon.MENU,
            "显示选中导航名称",
            "开启后左侧导航会像微软商店一样显示当前选中项的文字标签",
            self.navigation_text_card,
        )
        self.appearance_group.addGroup(
            FluentIcon.PIN,
            "窗口置顶",
            "开启后程序窗口将始终保持在最上层",
            self.topmost_card,
        )
        layout.addWidget(self.appearance_group)

        self.behavior_group = GroupHeaderCardWidget("行为设置", self.view)
        self.ask_save_card = SwitchGroupWidget(self.behavior_group)
        self.ask_save_card.setChecked(get_bool_from_qsettings(settings.value("ask_save_on_close"), True))
        self.behavior_group.addGroup(
            FluentIcon.SAVE,
            "关闭前询问是否保存",
            "关闭窗口时提示是否保存当前配置",
            self.ask_save_card,
        )
        layout.addWidget(self.behavior_group)

        self.update_group = GroupHeaderCardWidget("软件更新", self.view)
        self.auto_update_card = SwitchGroupWidget(self.update_group)
        self.auto_update_card.setChecked(get_bool_from_qsettings(settings.value("auto_check_update"), True))
        self.download_source_card = ComboBoxGroupWidget(180, self.update_group)
        self.download_source_combo = self.download_source_card.comboBox
        for key, source in DOWNLOAD_SOURCES.items():
            self.download_source_combo.addItem(source["label"], userData=key)
        saved_source = str(settings.value("download_source", DEFAULT_DOWNLOAD_SOURCE)).strip()
        idx = self.download_source_combo.findData(saved_source)
        if idx >= 0:
            self.download_source_combo.setCurrentIndex(idx)
        self.update_group.addGroup(
            FluentIcon.UPDATE,
            "在应用程序启动时检查更新",
            "新版本将更加稳定并拥有更多功能（建议启用此选项）",
            self.auto_update_card,
        )
        self.update_group.addGroup(
            FluentIcon.DOWNLOAD,
            "下载源",
            "选择用于下载更新的源（如果下载速度较慢，可以尝试切换到其他源）",
            self.download_source_card,
        )
        layout.addWidget(self.update_group)

        self.tools_group = GroupHeaderCardWidget("系统工具", self.view)
        self.restart_card = ActionButtonGroupWidget("重启", self.tools_group)
        self.reset_ui_card = ActionButtonGroupWidget("恢复默认", self.tools_group)
        self.tools_group.addGroup(
            FluentIcon.SYNC,
            "重新启动程序",
            "重启程序以应用某些设置更改",
            self.restart_card,
        )
        self.tools_group.addGroup(
            FluentIcon.BROOM,
            "恢复默认设置",
            "恢复所有设置项的默认值",
            self.reset_ui_card,
        )
        layout.addWidget(self.tools_group)

        layout.addStretch(1)

        bind_logged_action(
            self.navigation_text_card.switchButton.checkedChanged,
            self._on_navigation_text_toggled,
            scope="CONFIG",
            event="toggle_navigation_text_visible",
            target="navigation_text_switch",
            page="settings",
            payload_factory=lambda checked: {"enabled": bool(checked)},
        )
        bind_logged_action(
            self.topmost_card.switchButton.checkedChanged,
            self._on_topmost_toggled,
            scope="CONFIG",
            event="toggle_window_topmost",
            target="topmost_switch",
            page="settings",
            payload_factory=lambda checked: {"enabled": bool(checked)},
        )
        bind_logged_action(
            self.ask_save_card.switchButton.checkedChanged,
            self._on_ask_save_on_close_toggled,
            scope="CONFIG",
            event="toggle_ask_save_on_close",
            target="ask_save_switch",
            page="settings",
            payload_factory=lambda checked: {"enabled": bool(checked)},
        )
        bind_logged_action(
            self.restart_card.clicked,
            self._restart_program,
            scope="UI",
            event="restart_program",
            target="restart_card",
            page="settings",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.reset_ui_card.clicked,
            self._on_reset_ui_settings,
            scope="CONFIG",
            event="reset_ui_settings",
            target="reset_ui_card",
            page="settings",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.auto_update_card.switchButton.checkedChanged,
            self._on_auto_update_toggled,
            scope="CONFIG",
            event="toggle_auto_update",
            target="auto_update_switch",
            page="settings",
            payload_factory=lambda checked: {"enabled": bool(checked)},
        )
        bind_logged_action(
            self.download_source_combo.currentIndexChanged,
            self._on_download_source_changed,
            scope="CONFIG",
            event="change_download_source",
            target="download_source_combo",
            page="settings",
            payload_factory=lambda _index: {"source": self.download_source_combo.currentData()},
            forward_signal_args=False,
        )

    def _set_switch_state(self, card, checked: bool):
        btn = getattr(card, "switchButton", None)
        if btn is None:
            return
        btn.blockSignals(True)
        card.setChecked(checked)
        btn.blockSignals(False)

    def _read_navigation_text_visible_setting(self) -> bool:
        settings = app_settings()
        value = settings.value(NAVIGATION_TEXT_VISIBLE_SETTING_KEY)
        return get_bool_from_qsettings(value, True)

    def _apply_navigation_text_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue(NAVIGATION_TEXT_VISIBLE_SETTING_KEY, checked)
        log_action(
            "CONFIG",
            "toggle_navigation_text_visible",
            "navigation_text_switch",
            "settings",
            result="changed",
            payload={"enabled": bool(checked), "persist": persist},
        )
        win = self.window()
        nav = getattr(win, "navigationInterface", None)
        if nav is not None:
            try:
                if hasattr(nav, "setSelectedTextVisible"):
                    nav.setSelectedTextVisible(bool(checked))
            except Exception as exc:
                log_suppressed_exception("_apply_navigation_text_state: nav.setSelectedTextVisible(bool(checked))", exc, level=logging.WARNING)

    def _apply_topmost_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("window_topmost", checked)
        log_action(
            "CONFIG",
            "toggle_window_topmost",
            "topmost_switch",
            "settings",
            result="changed",
            payload={"enabled": bool(checked), "persist": persist},
        )
        win = self.window()
        if win:
            win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
            win.show()

    def _apply_ask_save_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("ask_save_on_close", checked)
        log_action(
            "CONFIG",
            "toggle_ask_save_on_close",
            "ask_save_switch",
            "settings",
            result="changed",
            payload={"enabled": bool(checked), "persist": persist},
        )

    def _apply_auto_update_state(self, checked: bool, persist: bool = True):
        settings = app_settings()
        if persist:
            settings.setValue("auto_check_update", checked)
        log_action(
            "CONFIG",
            "toggle_auto_update",
            "auto_update_switch",
            "settings",
            result="changed",
            payload={"enabled": bool(checked), "persist": persist},
        )

    def _on_navigation_text_toggled(self, checked: bool):
        self._apply_navigation_text_state(checked)

    def _restart_program(self):
        box = MessageBox("重启程序", "确定要重新启动程序吗？\n未保存的配置将会丢失。", self.window() or self)
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if box.exec():
            log_action("UI", "restart_program", "restart_card", "settings", result="confirmed")
            try:
                win = self.window()
                if hasattr(win, "_skip_save_on_close"):
                    setattr(win, "_skip_save_on_close", True)
                subprocess.Popen([sys.executable] + sys.argv)
                log_action("UI", "restart_program", "restart_card", "settings", result="started")
                QApplication.quit()
            except Exception as exc:
                log_action(
                    "UI",
                    "restart_program",
                    "restart_card",
                    "settings",
                    result="failed",
                    level=logging.ERROR,
                    detail=exc,
                )
                InfoBar.error("", f"重启失败：{exc}", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
        else:
            log_action("UI", "restart_program", "restart_card", "settings", result="cancelled")

    def _on_auto_update_toggled(self, checked: bool):
        self._apply_auto_update_state(checked)

    def _on_topmost_toggled(self, checked: bool):
        self._apply_topmost_state(checked)

    def _on_ask_save_on_close_toggled(self, checked: bool):
        self._apply_ask_save_state(checked)

    def _on_reset_ui_settings(self):
        box = MessageBox("恢复默认设置", "确定要恢复默认设置吗？\n这将还原所有设置项到初始状态。", self.window() or self)
        box.yesButton.setText("恢复")
        box.cancelButton.setText("取消")
        if not box.exec():
            log_action("CONFIG", "reset_ui_settings", "reset_ui_card", "settings", result="cancelled")
            return
        log_action("CONFIG", "reset_ui_settings", "reset_ui_card", "settings", result="confirmed")

        settings = app_settings()
        for key in (
            NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
            "window_topmost",
            "ask_save_on_close",
            "auto_check_update",
        ):
            settings.remove(key)

        defaults = {
            NAVIGATION_TEXT_VISIBLE_SETTING_KEY: True,
            "window_topmost": False,
            "ask_save_on_close": True,
            "auto_check_update": True,
        }
        self._set_switch_state(self.navigation_text_card, defaults[NAVIGATION_TEXT_VISIBLE_SETTING_KEY])
        self._set_switch_state(self.topmost_card, defaults["window_topmost"])
        self._set_switch_state(self.ask_save_card, defaults["ask_save_on_close"])
        self._set_switch_state(self.auto_update_card, defaults["auto_check_update"])
        self._apply_navigation_text_state(defaults[NAVIGATION_TEXT_VISIBLE_SETTING_KEY], persist=False)
        self._apply_topmost_state(defaults["window_topmost"], persist=False)
        InfoBar.success("", "已恢复默认设置", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

        log_action("CONFIG", "reset_ui_settings", "reset_ui_card", "settings", result="success")

    def _on_download_source_changed(self):
        idx = self.download_source_combo.currentIndex()
        source_key = str(self.download_source_combo.itemData(idx)) if idx >= 0 else DEFAULT_DOWNLOAD_SOURCE
        settings = app_settings()
        settings.setValue("download_source", source_key)
        log_action(
            "CONFIG",
            "change_download_source",
            "download_source_combo",
            "settings",
            result="changed",
            payload={"source": source_key},
        )
