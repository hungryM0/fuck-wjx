"""工具类模块"""
from wjx.utils.app.config import (
    DEFAULT_HTTP_HEADERS,
    BROWSER_PREFERENCE,
    QUESTION_TYPE_LABELS,
    DEFAULT_FILL_TEXT,
)
from wjx.utils.app.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO
from wjx.utils.logging.log_utils import (
    setup_logging,
    log_popup_info,
    log_popup_error,
    log_popup_warning,
    log_popup_confirm,
    LOG_BUFFER_HANDLER,
    register_popup_handler,
    save_log_records_to_file,
)
from wjx.utils.io.load_save import ConfigPersistenceMixin
from wjx.utils.update.updater import check_for_updates, perform_update
from wjx.utils.system.registry_manager import RegistryManager
from wjx.utils.event_bus import (
    bus as event_bus,
    EventBus,
    EVENT_TASK_STARTED,
    EVENT_TASK_STOPPED,
    EVENT_TASK_PAUSED,
    EVENT_TASK_RESUMED,
    EVENT_TARGET_REACHED,
    EVENT_CAPTCHA_DETECTED,
    EVENT_SUBMIT_SUCCESS,
    EVENT_SUBMIT_FAILURE,
)

__all__ = [
    "DEFAULT_HTTP_HEADERS",
    "BROWSER_PREFERENCE",
    "QUESTION_TYPE_LABELS",
    "DEFAULT_FILL_TEXT",
    "__VERSION__",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "setup_logging",
    "log_popup_info",
    "log_popup_error",
    "log_popup_warning",
    "log_popup_confirm",
    "LOG_BUFFER_HANDLER",
    "register_popup_handler",
    "save_log_records_to_file",
    "ConfigPersistenceMixin",
    "check_for_updates",
    "perform_update",
    "RegistryManager",
    # event_bus
    "event_bus",
    "EventBus",
    "EVENT_TASK_STARTED",
    "EVENT_TASK_STOPPED",
    "EVENT_TASK_PAUSED",
    "EVENT_TASK_RESUMED",
    "EVENT_TARGET_REACHED",
    "EVENT_CAPTCHA_DETECTED",
    "EVENT_SUBMIT_SUCCESS",
    "EVENT_SUBMIT_FAILURE",
]
