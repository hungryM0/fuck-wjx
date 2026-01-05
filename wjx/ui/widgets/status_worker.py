"""状态查询 Worker，运行在独立 QThread 中。"""
from PySide6.QtCore import QObject, Signal


class StatusFetchWorker(QObject):
    """状态查询 Worker，运行在独立 QThread 中，确保线程安全。"""
    finished = Signal(str, str)  # text, color
    
    def __init__(self, fetcher, formatter):
        super().__init__()
        self.fetcher = fetcher
        self.formatter = formatter
        self._stopped = False
    
    def stop(self):
        """标记停止，防止后续操作"""
        self._stopped = True
    
    def fetch(self):
        """执行状态查询，完成后发送 finished 信号"""
        if self._stopped:
            return
        text = "作者当前在线状态：未知"
        color = "#666666"
        try:
            if self._stopped:
                return
            result = self.fetcher()
            if self._stopped:
                return
            if callable(self.formatter):
                fmt_result = self.formatter(result)
                if isinstance(fmt_result, tuple) and len(fmt_result) >= 2:
                    text, color = str(fmt_result[0]), str(fmt_result[1])
            else:
                online = bool(result.get("online")) if isinstance(result, dict) else True
                text = f"作者当前在线状态：{'在线' if online else '离线'}"
                color = "#228B22" if online else "#cc0000"
        except Exception:
            text = "作者当前在线状态：未知"
            color = "#666666"
        
        if not self._stopped:
            self.finished.emit(text, color)
