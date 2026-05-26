"""应用程序设置页面"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    MessageBox,
    PrimaryPushSettingCard,
    PushSettingCard,
    ScrollArea,
    SettingCardGroup,
)

from software.app.config import (
    AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY,
    AUTO_SAVE_LOG_RETENTION_OPTIONS,
    AUTO_SAVE_LOGS_SETTING_KEY,
    CONFIG_DIRECTORY_SETTING_KEY,
    DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT,
    DEFAULT_AUTO_SAVE_LOGS,
    NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
    TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY,
    app_settings,
    get_bool_from_qsettings,
    get_int_from_qsettings,
)
from software.app.user_paths import (
    get_default_user_config_directory,
    resolve_user_config_directory,
)
from software.integrations.ai import reset_ai_settings
from software.logging.action_logger import bind_logged_action, log_action
from software.logging.log_utils import log_suppressed_exception
from software.providers.survey_cache import clear_survey_parse_cache
from software.ui.helpers.message_bar import show_message_bar
from software.ui.pages.settings.definitions import (
    APPEARANCE_SWITCHES,
    BEHAVIOR_SWITCHES,
    UPDATE_SWITCHES,
    SwitchCardDefinition,
)
from software.ui.widgets.setting_cards import (
    ExpandComboSwitchSettingCard,
    SwitchSettingCard,
)

if TYPE_CHECKING:
    from qfluentwidgets import ComboBox


class SettingsPage(ScrollArea):
    """应用程序设置页面"""
    view: QWidget
    appearance_group: SettingCardGroup
    behavior_group: SettingCardGroup
    update_group: SettingCardGroup
    tools_group: SettingCardGroup
    navigation_text_card: SwitchSettingCard
    topmost_card: SwitchSettingCard
    ask_save_card: SwitchSettingCard
    prevent_sleep_card: SwitchSettingCard
    task_result_notification_card: SwitchSettingCard
    auto_update_card: SwitchSettingCard
    auto_save_logs_card: ExpandComboSwitchSettingCard
    auto_save_logs_combo: "ComboBox"
    reset_ui_card: PrimaryPushSettingCard
    config_directory_card: PushSettingCard
    clear_survey_cache_card: PushSettingCard

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._settings = app_settings()
        self._defaults = self._build_defaults()
        self._build_ui()

    def _build_defaults(self) -> dict[str, Any]:
        return {
            NAVIGATION_TEXT_VISIBLE_SETTING_KEY: True,
            "window_topmost": False,
            "ask_save_on_close": True,
            "prevent_sleep_during_run": True,
            TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY: True,
            AUTO_SAVE_LOGS_SETTING_KEY: DEFAULT_AUTO_SAVE_LOGS,
            AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY: DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT,
            "auto_check_update": True,
            CONFIG_DIRECTORY_SETTING_KEY: get_default_user_config_directory(),
        }

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        self.appearance_group = self._build_switch_group("界面外观", APPEARANCE_SWITCHES)
        layout.addWidget(self.appearance_group)

        self.behavior_group = self._build_switch_group("行为设置", BEHAVIOR_SWITCHES)
        self._build_auto_save_logs_card()
        self.behavior_group.addSettingCard(self.auto_save_logs_card)
        layout.addWidget(self.behavior_group)

        self.update_group = self._build_switch_group("软件更新", UPDATE_SWITCHES)
        layout.addWidget(self.update_group)

        self.tools_group = SettingCardGroup("系统工具", self.view)
        self.reset_ui_card = PrimaryPushSettingCard(
            "恢复默认",
            FluentIcon.BROOM,
            "恢复默认设置",
            "恢复所有设置项的默认值",
            self.tools_group,
        )
        self.config_directory_card = PushSettingCard(
            "选择目录",
            FluentIcon.FOLDER,
            "配置文件目录",
            "",
            self.tools_group,
        )
        self._refresh_config_directory_card_content()
        self.clear_survey_cache_card = PushSettingCard(
            "删除缓存",
            FluentIcon.DELETE,
            "删除问卷解析缓存",
            "清空本地问卷解析缓存，下次解析时会重新抓取问卷结构",
            self.tools_group,
        )
        for card in (
            self.reset_ui_card,
            self.config_directory_card,
            self.clear_survey_cache_card,
        ):
            self.tools_group.addSettingCard(card)
        layout.addWidget(self.tools_group)
        layout.addStretch(1)

        self._bind_switch_actions(APPEARANCE_SWITCHES + BEHAVIOR_SWITCHES + UPDATE_SWITCHES)
        self._bind_static_actions()

    def _build_switch_group(
        self,
        title: str,
        definitions: tuple[SwitchCardDefinition, ...],
    ) -> SettingCardGroup:
        group = SettingCardGroup(title, self.view)
        for definition in definitions:
            card = SwitchSettingCard(
                definition.icon,
                definition.title,
                definition.content,
                group,
            )
            card.setChecked(self._read_bool_setting(definition.setting_key, definition.default))
            setattr(self, definition.attr_name, card)
            group.addSettingCard(card)
        return group

    def _build_auto_save_logs_card(self) -> None:
        self.auto_save_logs_card = ExpandComboSwitchSettingCard(
            FluentIcon.DOCUMENT,
            "自动保存日志",
            "关闭程序后自动保留本次运行日志，并只留下最近几份历史记录",
            "保留最近日志文件数：",
            combo_min_width=140,
            combo_suffix="份",
            parent=self.behavior_group,
        )
        self.auto_save_logs_card.setChecked(
            self._read_bool_setting(
                AUTO_SAVE_LOGS_SETTING_KEY,
                DEFAULT_AUTO_SAVE_LOGS,
            )
        )
        self.auto_save_logs_combo = self.auto_save_logs_card.comboBox
        for count in AUTO_SAVE_LOG_RETENTION_OPTIONS:
            self.auto_save_logs_combo.addItem(str(count), userData=int(count))
        keep_count = get_int_from_qsettings(
            self._settings.value(AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY),
            DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT,
            minimum=1,
            maximum=max(AUTO_SAVE_LOG_RETENTION_OPTIONS),
        )
        self._set_auto_save_retention_index(keep_count)
        self.auto_save_logs_card.setContentEnabled(self.auto_save_logs_card.isChecked())

    def _bind_switch_actions(
        self,
        definitions: tuple[SwitchCardDefinition, ...],
    ) -> None:
        for definition in definitions:
            card = cast(SwitchSettingCard, getattr(self, definition.attr_name))
            bind_logged_action(
                card.switchButton.checkedChanged,
                getattr(self, definition.handler_name),
                scope="CONFIG",
                event=definition.event,
                target=definition.target,
                page="settings",
                payload_factory=lambda checked: {"enabled": bool(checked)},
            )

        bind_logged_action(
            self.auto_save_logs_card.switchButton.checkedChanged,
            self._on_auto_save_logs_toggled,
            scope="CONFIG",
            event="toggle_auto_save_logs",
            target="auto_save_logs_switch",
            page="settings",
            payload_factory=lambda checked: {"enabled": bool(checked)},
        )
        bind_logged_action(
            self.auto_save_logs_combo.currentIndexChanged,
            self._on_auto_save_log_retention_changed,
            scope="CONFIG",
            event="change_auto_save_log_retention",
            target="auto_save_log_retention_combo",
            page="settings",
            payload_factory=lambda _index: {
                "keep_count": self.auto_save_logs_combo.currentData()
            },
            forward_signal_args=False,
        )

    def _bind_static_actions(self) -> None:
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
            self.config_directory_card.clicked,
            self._on_config_directory_clicked,
            scope="CONFIG",
            event="change_config_directory",
            target="config_directory_card",
            page="settings",
            payload_factory=lambda: {"path": self._current_config_directory()},
            forward_signal_args=False,
        )
        bind_logged_action(
            self.clear_survey_cache_card.clicked,
            self._on_clear_survey_parse_cache,
            scope="CONFIG",
            event="clear_survey_parse_cache",
            target="clear_survey_cache_card",
            page="settings",
            forward_signal_args=False,
        )

    def _window_parent(self):
        return self.window() or self

    def _show_bar(self, message: str, level: str, duration: int) -> None:
        show_message_bar(
            parent=self._window_parent(),
            title="",
            message=message,
            level=level,
            duration=duration,
        )

    def _read_bool_setting(self, key: str, default: bool) -> bool:
        return get_bool_from_qsettings(self._settings.value(key), default)

    def _current_config_directory(self) -> str:
        return resolve_user_config_directory(self._settings)

    def _set_config_directory_content(self, directory: str) -> None:
        normalized = os.path.abspath(os.path.expanduser(directory))
        self.config_directory_card.setContent(normalized)
        self.config_directory_card.contentLabel.setToolTip(normalized)

    def _refresh_config_directory_card_content(self) -> None:
        self._set_config_directory_content(self._current_config_directory())

    def _set_switch_state(self, card, checked: bool):
        button = getattr(card, "switchButton", None)
        if button is None:
            return
        button.blockSignals(True)
        card.setChecked(bool(checked))
        button.blockSignals(False)

    def _set_auto_save_retention_index(self, keep_count: int) -> None:
        index = self.auto_save_logs_combo.findData(int(keep_count))
        if index < 0:
            index = self.auto_save_logs_combo.findData(DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT)
        if index >= 0:
            self.auto_save_logs_combo.blockSignals(True)
            self.auto_save_logs_combo.setCurrentIndex(index)
            self.auto_save_logs_combo.blockSignals(False)

    def _persist_bool_setting(
        self,
        *,
        key: str,
        checked: bool,
        event: str,
        target: str,
        persist: bool = True,
    ) -> None:
        if persist:
            self._settings.setValue(key, checked)
        log_action(
            "CONFIG",
            event,
            target,
            "settings",
            result="changed",
            payload={"enabled": bool(checked), "persist": persist},
        )

    def _apply_navigation_text_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key=NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
            checked=checked,
            event="toggle_navigation_text_visible",
            target="navigation_text_switch",
            persist=persist,
        )
        nav = getattr(self.window(), "navigationInterface", None)
        if nav is None:
            return
        try:
            if hasattr(nav, "setSelectedTextVisible"):
                nav.setSelectedTextVisible(bool(checked))
        except Exception as exc:
            log_suppressed_exception(
                "_apply_navigation_text_state: nav.setSelectedTextVisible(bool(checked))",
                exc,
                level=logging.WARNING,
            )

    def _apply_topmost_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key="window_topmost",
            checked=checked,
            event="toggle_window_topmost",
            target="topmost_switch",
            persist=persist,
        )
        win = self.window()
        if win is None:
            return
        handler = getattr(win, "apply_topmost_state", None)
        if callable(handler):
            cast(Any, handler)(checked, show=True)
            return
        win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        win.show()

    def _apply_ask_save_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key="ask_save_on_close",
            checked=checked,
            event="toggle_ask_save_on_close",
            target="ask_save_switch",
            persist=persist,
        )

    def _apply_prevent_sleep_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key="prevent_sleep_during_run",
            checked=checked,
            event="toggle_prevent_sleep_during_run",
            target="prevent_sleep_switch",
            persist=persist,
        )

    def _apply_task_result_notification_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key=TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY,
            checked=checked,
            event="toggle_task_result_windows_notification",
            target="task_result_notification_switch",
            persist=persist,
        )

    def _apply_auto_save_logs_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key=AUTO_SAVE_LOGS_SETTING_KEY,
            checked=checked,
            event="toggle_auto_save_logs",
            target="auto_save_logs_switch",
            persist=persist,
        )
        self.auto_save_logs_card.setContentEnabled(bool(checked))

    def _apply_auto_save_log_retention_count(self, keep_count: int, persist: bool = True):
        normalized = int(keep_count)
        if persist:
            self._settings.setValue(AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY, normalized)
        log_action(
            "CONFIG",
            "change_auto_save_log_retention",
            "auto_save_log_retention_combo",
            "settings",
            result="changed",
            payload={"keep_count": normalized, "persist": persist},
        )

    def _apply_auto_update_state(self, checked: bool, persist: bool = True):
        self._persist_bool_setting(
            key="auto_check_update",
            checked=checked,
            event="toggle_auto_update",
            target="auto_update_switch",
            persist=persist,
        )

    def _apply_config_directory_state(self, directory: str, persist: bool = True) -> str:
        normalized = os.path.abspath(os.path.expanduser(directory))
        os.makedirs(normalized, exist_ok=True)
        if persist:
            self._settings.setValue(CONFIG_DIRECTORY_SETTING_KEY, normalized)
            self._settings.sync()
        self._set_config_directory_content(normalized)
        log_action(
            "CONFIG",
            "change_config_directory",
            "config_directory_card",
            "settings",
            result="changed",
            payload={"path": normalized, "persist": persist},
        )
        return normalized

    def _on_navigation_text_toggled(self, checked: bool):
        self._apply_navigation_text_state(checked)

    def _on_topmost_toggled(self, checked: bool):
        self._apply_topmost_state(checked)

    def _on_ask_save_on_close_toggled(self, checked: bool):
        self._apply_ask_save_state(checked)

    def _on_prevent_sleep_toggled(self, checked: bool):
        self._apply_prevent_sleep_state(checked)

    def _on_task_result_notification_toggled(self, checked: bool):
        self._apply_task_result_notification_state(checked)

    def _on_auto_save_logs_toggled(self, checked: bool):
        self._apply_auto_save_logs_state(checked)

    def _on_auto_save_log_retention_changed(self):
        keep_count = self.auto_save_logs_combo.currentData()
        if keep_count is None:
            keep_count = DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT
        self._apply_auto_save_log_retention_count(int(keep_count))

    def _on_auto_update_toggled(self, checked: bool):
        self._apply_auto_update_state(checked)

    def _on_config_directory_clicked(self):
        current_directory = self._current_config_directory()
        selected_directory = QFileDialog.getExistingDirectory(
            self._window_parent(),
            "选择配置文件目录",
            current_directory,
        )
        if not selected_directory:
            log_action(
                "CONFIG",
                "change_config_directory",
                "config_directory_card",
                "settings",
                result="cancelled",
            )
            return

        normalized = self._apply_config_directory_state(selected_directory)
        self._show_bar(f"配置文件目录已更新：{normalized}", "success", 2500)

    def _reset_all_settings(self) -> None:
        self._settings.clear()
        self._settings.sync()
        reset_ai_settings()

        self._set_switch_state(self.navigation_text_card, self._defaults[NAVIGATION_TEXT_VISIBLE_SETTING_KEY])
        self._set_switch_state(self.topmost_card, self._defaults["window_topmost"])
        self._set_switch_state(self.ask_save_card, self._defaults["ask_save_on_close"])
        self._set_switch_state(
            self.prevent_sleep_card,
            self._defaults["prevent_sleep_during_run"],
        )
        self._set_switch_state(
            self.task_result_notification_card,
            self._defaults[TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY],
        )
        self._set_switch_state(self.auto_save_logs_card, self._defaults[AUTO_SAVE_LOGS_SETTING_KEY])
        self._set_auto_save_retention_index(
            self._defaults[AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY]
        )
        self._set_switch_state(self.auto_update_card, self._defaults["auto_check_update"])
        self._set_config_directory_content(self._defaults[CONFIG_DIRECTORY_SETTING_KEY])

        self._apply_navigation_text_state(
            self._defaults[NAVIGATION_TEXT_VISIBLE_SETTING_KEY],
            persist=False,
        )
        self._apply_topmost_state(self._defaults["window_topmost"], persist=False)
        self._apply_ask_save_state(self._defaults["ask_save_on_close"], persist=False)
        self._apply_prevent_sleep_state(
            self._defaults["prevent_sleep_during_run"],
            persist=False,
        )
        self._apply_task_result_notification_state(
            self._defaults[TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY],
            persist=False,
        )
        self._apply_auto_save_logs_state(
            self._defaults[AUTO_SAVE_LOGS_SETTING_KEY],
            persist=False,
        )
        self._apply_auto_save_log_retention_count(
            self._defaults[AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY],
            persist=False,
        )
        self._apply_auto_update_state(self._defaults["auto_check_update"], persist=False)
        self._apply_config_directory_state(
            self._defaults[CONFIG_DIRECTORY_SETTING_KEY],
            persist=False,
        )

    def _on_reset_ui_settings(self):
        box = MessageBox(
            "恢复默认设置",
            "确定要恢复默认设置吗？\n这将还原所有设置项到初始状态。",
            self._window_parent(),
        )
        box.yesButton.setText("恢复")
        box.cancelButton.setText("取消")
        if not box.exec():
            log_action(
                "CONFIG",
                "reset_ui_settings",
                "reset_ui_card",
                "settings",
                result="cancelled",
            )
            return

        log_action(
            "CONFIG",
            "reset_ui_settings",
            "reset_ui_card",
            "settings",
            result="confirmed",
        )
        self._reset_all_settings()
        self._show_bar("已恢复默认设置", "success", 2000)
        log_action(
            "CONFIG",
            "reset_ui_settings",
            "reset_ui_card",
            "settings",
            result="success",
        )

    def _on_clear_survey_parse_cache(self):
        box = MessageBox(
            "删除问卷解析缓存",
            "确定要删除本地问卷解析缓存吗？\n删除后下次解析会重新请求问卷数据。",
            self._window_parent(),
        )
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if not box.exec():
            log_action(
                "CONFIG",
                "clear_survey_parse_cache",
                "clear_survey_cache_card",
                "settings",
                result="cancelled",
            )
            return

        log_action(
            "CONFIG",
            "clear_survey_parse_cache",
            "clear_survey_cache_card",
            "settings",
            result="confirmed",
        )
        try:
            removed_count = clear_survey_parse_cache()
        except Exception as exc:
            log_action(
                "CONFIG",
                "clear_survey_parse_cache",
                "clear_survey_cache_card",
                "settings",
                result="failed",
                level=logging.ERROR,
                detail=exc,
            )
            log_suppressed_exception(
                "_on_clear_survey_parse_cache: clear_survey_parse_cache()",
                exc,
                level=logging.ERROR,
            )
            self._show_bar(f"删除问卷解析缓存失败：{exc}", "error", 3000)
            return

        message = (
            "没有可删除的问卷解析缓存"
            if removed_count <= 0
            else f"已删除 {removed_count} 项问卷解析缓存"
        )
        self._show_bar(message, "success", 2500)
        log_action(
            "CONFIG",
            "clear_survey_parse_cache",
            "clear_survey_cache_card",
            "settings",
            result="success",
            payload={"removed_count": removed_count},
        )
