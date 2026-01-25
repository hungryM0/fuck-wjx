# -*- coding: utf-8 -*-
from PySide6.QtCore import QObject, Signal

from wjx.utils.integrations.ai_service import test_connection


class AITestWorker(QObject):
    finished = Signal(bool, str)

    def run(self):
        try:
            result = test_connection()
            success = result.startswith("连接成功")
            self.finished.emit(success, result)
        except Exception as exc:
            self.finished.emit(False, f"连接失败: {exc}")
