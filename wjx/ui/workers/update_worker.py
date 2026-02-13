"""后台更新检查Worker"""
from PySide6.QtCore import QThread, Signal
import logging
from typing import Optional, Dict, Any


class UpdateCheckWorker(QThread):
    """后台检查更新的Worker线程"""

    # 信号：更新检查完成 (has_update: bool, update_info: dict)
    update_checked = Signal(bool, dict)
    # 信号：检查失败 (error_message: str)
    check_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent

    def run(self):
        """在后台线程执行更新检查"""
        try:
            from wjx.utils.update.updater import UpdateManager

            logging.debug("后台检查更新开始...")
            update_info = UpdateManager.check_updates()

            if update_info:
                has_update = True
                logging.info(f"发现新版本: {update_info.get('version', 'unknown')}")
            else:
                has_update = False
                update_info = {}
                logging.debug("当前已是最新版本")

            # 发送结果信号
            self.update_checked.emit(has_update, update_info)

        except Exception as exc:
            error_msg = f"检查更新失败: {exc}"
            logging.warning(error_msg)
            self.check_failed.emit(error_msg)
