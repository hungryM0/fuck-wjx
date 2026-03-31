"""后台更新检查 Worker 对象。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot


class UpdateCheckWorker(QObject):
    """在独立 QThread 中执行更新检查，避免主线程卡顿。"""

    finished = Signal(bool, dict)

    @Slot()
    def run(self) -> None:
        try:
            from software.update.updater import UpdateManager

            logging.info("后台检查更新开始...")
            update_info = UpdateManager.check_updates() or {"has_update": False, "status": "unknown"}
            has_update = bool(update_info.get("has_update", False))
            status = str(update_info.get("status", "unknown"))

            if has_update:
                logging.info("发现新版本: %s", update_info.get("version", "unknown"))
            else:
                logging.info("更新检查状态: %s", status)

            self.finished.emit(has_update, update_info)
        except Exception as exc:
            logging.warning("检查更新失败: %s", exc)
            self.finished.emit(False, {"has_update": False, "status": "unknown"})

