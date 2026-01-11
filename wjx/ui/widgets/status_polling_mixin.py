"""状态轮询 Mixin，用于对话框中的在线状态查询"""
from typing import Optional, Callable, Any

from PySide6.QtCore import QThread, QTimer

from wjx.ui.widgets.status_worker import StatusFetchWorker


class StatusPollingMixin:
    """状态轮询 Mixin，提供在线状态查询功能
    
    使用方法：
    1. 继承此 Mixin（同时继承 QDialog 或其他 QObject 子类）
    2. 在类中定义信号: _statusLoaded = Signal(str, str)
    3. 在 __init__ 中调用 _init_status_polling(fetcher, formatter)
    4. 实现 _on_status_loaded(text, color) 方法来更新 UI
    5. 在 closeEvent/reject/accept 中调用 _stop_status_polling()
    """
    
    _status_fetcher: Optional[Callable]
    _status_formatter: Optional[Callable]
    _worker_thread: Optional[QThread]
    _worker: Optional[StatusFetchWorker]
    _status_timer: Optional[QTimer]
    _polling_interval: int
    
    def _init_status_polling(
        self,
        status_fetcher: Optional[Callable],
        status_formatter: Optional[Callable],
        interval_ms: int = 5000
    ):
        """初始化状态轮询
        
        Args:
            status_fetcher: 获取状态的函数
            status_formatter: 格式化状态的函数，返回 (text, color) 元组
            interval_ms: 轮询间隔（毫秒）
        """
        self._status_fetcher = status_fetcher
        self._status_formatter = status_formatter
        self._worker_thread = None
        self._worker = None
        self._status_timer = None
        self._polling_interval = interval_ms
        
        # 连接信号（子类必须定义 _statusLoaded 信号）
        status_signal: Any = getattr(self, '_statusLoaded', None)
        if status_signal is not None:
            status_signal.connect(self._on_status_loaded)
    
    def _start_status_polling(self):
        """启动状态轮询"""
        if not callable(self._status_fetcher):
            self._on_status_loaded("作者当前在线状态：未知", "#666666")
            return
        
        # 立即执行一次查询
        self._fetch_status_once()
        
        # 设置定时器
        self._status_timer = QTimer(self)  # type: ignore[arg-type]
        self._status_timer.setInterval(self._polling_interval)
        self._status_timer.timeout.connect(self._fetch_status_once)
        self._status_timer.start()
    
    def _fetch_status_once(self):
        """执行一次状态查询"""
        # 如果上一次查询还在进行，跳过
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        
        # 创建新的 Worker 和 Thread
        self._worker_thread = QThread(self)  # type: ignore[arg-type]
        self._worker = StatusFetchWorker(self._status_fetcher, self._status_formatter)
        self._worker.moveToThread(self._worker_thread)
        
        # 连接信号
        status_signal: Any = getattr(self, '_statusLoaded', None)
        if status_signal is not None:
            self._worker.finished.connect(status_signal.emit)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.started.connect(self._worker.fetch)
        
        # 启动线程
        self._worker_thread.start()
    
    def _stop_status_polling(self):
        """停止状态轮询并安全清理线程"""
        # 停止定时器
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None
        
        # 停止 Worker
        if self._worker is not None:
            self._worker.stop()
        
        # 等待线程结束
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(1000)
            if self._worker_thread.isRunning():
                self._worker_thread.terminate()
        
        self._worker = None
        self._worker_thread = None
    
    def _on_status_loaded(self, text: str, color: str):
        """状态加载完成回调，子类应重写此方法来更新 UI"""
        raise NotImplementedError("子类必须实现 _on_status_loaded 方法")
