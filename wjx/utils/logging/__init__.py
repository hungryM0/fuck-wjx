"""日志相关工具"""
from wjx.utils.logging.log_utils import (
    setup_logging,
    log_popup_info,
    log_popup_error,
    log_popup_warning,
    log_popup_confirm,
    LOG_BUFFER_HANDLER,
    register_popup_handler,
    save_log_records_to_file,
    dump_threads_to_file,
)

__all__ = [
    "setup_logging",
    "log_popup_info",
    "log_popup_error",
    "log_popup_warning",
    "log_popup_confirm",
    "LOG_BUFFER_HANDLER",
    "register_popup_handler",
    "save_log_records_to_file",
    "dump_threads_to_file",
]
