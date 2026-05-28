"""设置页静态定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from qfluentwidgets import FluentIcon

if TYPE_CHECKING:
    from qfluentwidgets.common.icon import FluentIconBase

from software.app.config import (
    NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
    TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY,
)


@dataclass(frozen=True)
class SwitchCardDefinition:
    attr_name: str
    icon: "FluentIconBase"
    title: str
    content: str
    setting_key: str
    default: bool
    event: str
    target: str
    handler_name: str


APPEARANCE_SWITCHES = (
    SwitchCardDefinition(
        attr_name="navigation_text_card",
        icon=FluentIcon.MENU,
        title="显示选中导航名称",
        content="开启后左侧导航会像微软商店一样显示当前选中项的文字标签",
        setting_key=NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
        default=True,
        event="toggle_navigation_text_visible",
        target="navigation_text_switch",
        handler_name="_on_navigation_text_toggled",
    ),
    SwitchCardDefinition(
        attr_name="topmost_card",
        icon=FluentIcon.PIN,
        title="窗口置顶",
        content="开启后程序窗口将始终保持在最上层",
        setting_key="window_topmost",
        default=False,
        event="toggle_window_topmost",
        target="topmost_switch",
        handler_name="_on_topmost_toggled",
    ),
)


BEHAVIOR_SWITCHES = (
    SwitchCardDefinition(
        attr_name="ask_save_card",
        icon=FluentIcon.SAVE,
        title="关闭前询问是否保存",
        content="关闭窗口时提示是否保存当前配置",
        setting_key="ask_save_on_close",
        default=True,
        event="toggle_ask_save_on_close",
        target="ask_save_switch",
        handler_name="_on_ask_save_on_close_toggled",
    ),
    SwitchCardDefinition(
        attr_name="prevent_sleep_card",
        icon=FluentIcon.HISTORY,
        title="执行期间阻止自动休眠",
        content="任务运行时阻止电脑因为长时间无操作而自动休眠，任务结束后会自动恢复",
        setting_key="prevent_sleep_during_run",
        default=True,
        event="toggle_prevent_sleep_during_run",
        target="prevent_sleep_switch",
        handler_name="_on_prevent_sleep_toggled",
    ),
    SwitchCardDefinition(
        attr_name="task_result_notification_card",
        icon=FluentIcon.INFO,
        title="后台任务完成/失败时通知",
        content="当程序不在前台时，任务完成或失败会弹出系统通知",
        setting_key=TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY,
        default=True,
        event="toggle_task_result_windows_notification",
        target="task_result_notification_switch",
        handler_name="_on_task_result_notification_toggled",
    ),
)


UPDATE_SWITCHES = (
    SwitchCardDefinition(
        attr_name="auto_update_card",
        icon=FluentIcon.UPDATE,
        title="在应用程序启动时检查更新",
        content="新版本将更加稳定并拥有更多功能（建议启用此选项）",
        setting_key="auto_check_update",
        default=True,
        event="toggle_auto_update",
        target="auto_update_switch",
        handler_name="_on_auto_update_toggled",
    ),
)
