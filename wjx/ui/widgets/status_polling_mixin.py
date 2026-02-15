"""状态轮询 Mixin，用于对话框中的在线状态查询"""
import threading
from typing import Optional, Callable, Any

from PySide6.QtCore import QTimer


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
    _status_timer: Optional[QTimer]
    _polling_interval: int
    _status_lock: threading.Lock
    _status_fetch_in_progress: bool
    _status_stop_event: threading.Event
    _status_session_id: int
    
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
        self._status_timer = None
        self._polling_interval = interval_ms
        self._status_lock = threading.Lock()
        self._status_fetch_in_progress = False
        self._status_stop_event = threading.Event()
        self._status_session_id = 0
        
        # 连接信号（子类必须定义 _statusLoaded 信号）
        status_signal: Any = getattr(self, '_statusLoaded', None)
        if status_signal is not None:
            status_signal.connect(self._on_status_loaded)
    
    def _start_status_polling(self):
        """启动状态轮询"""
        if not callable(self._status_fetcher):
            self._on_status_loaded("未知：状态获取器未配置", "#666666")
            return

        with self._status_lock:
            self._status_session_id += 1
            self._status_stop_event = threading.Event()
            self._status_fetch_in_progress = False
        
        # 立即执行一次查询
        self._fetch_status_once()
        
        # 设置定时器
        self._status_timer = QTimer(self)  # type: ignore[arg-type]
        self._status_timer.setInterval(self._polling_interval)
        self._status_timer.timeout.connect(self._fetch_status_once)
        self._status_timer.start()
    
    def _fetch_status_once(self):
        """执行一次状态查询"""
        with self._status_lock:
            # 若当前轮询已停止，直接跳过
            if self._status_stop_event.is_set():
                return
            # 如果上一次查询还在进行，跳过
            if self._status_fetch_in_progress:
                return
            self._status_fetch_in_progress = True
            session_id = self._status_session_id
            stop_event = self._status_stop_event

        thread = threading.Thread(
            target=self._run_status_fetch,
            args=(session_id, stop_event),
            daemon=True,
            name="StatusFetchWorker",
        )
        thread.start()

    def _run_status_fetch(self, session_id: int, stop_event: threading.Event):
        """后台线程：执行状态查询并通过信号回到 UI 线程。"""
        text = "未知：状态未知"
        color = "#666666"
        try:
            if stop_event.is_set():
                return
            result = self._status_fetcher() if callable(self._status_fetcher) else None
            if stop_event.is_set():
                return
            if callable(self._status_formatter):
                fmt_result = self._status_formatter(result)
                if isinstance(fmt_result, tuple) and len(fmt_result) >= 2:
                    text, color = str(fmt_result[0]), str(fmt_result[1])
            else:
                if isinstance(result, dict):
                    online = result.get("online", None)
                    message = str(result.get("message") or "").strip()
                    if not message:
                        if online is True:
                            message = "系统正常运行中"
                        elif online is False:
                            message = "系统当前不在线"
                        else:
                            message = "状态未知"
                    if online is True:
                        text = f"在线：{message}"
                    elif online is False:
                        text = f"离线：{message}"
                    else:
                        text = f"未知：{message}"
                    color = "#228B22" if online is True else ("#cc0000" if online is False else "#666666")
                else:
                    text = "未知：返回数据格式异常"
                    color = "#666666"
        except Exception:
            text = "未知：状态获取失败"
            color = "#666666"
        finally:
            should_emit = False
            with self._status_lock:
                # 只处理当前会话，避免旧线程覆盖新会话状态
                if session_id == self._status_session_id:
                    self._status_fetch_in_progress = False
                    should_emit = not stop_event.is_set()
            if should_emit:
                status_signal: Any = getattr(self, "_statusLoaded", None)
                if status_signal is not None:
                    status_signal.emit(text, color)

    def _stop_status_polling(self):
        """停止状态轮询并异步清理后台任务。"""
        # 停止定时器
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None

        with self._status_lock:
            self._status_stop_event.set()
            self._status_fetch_in_progress = False
            # 会话号自增，用于失效所有旧查询结果
            self._status_session_id += 1

    def _on_status_loaded(self, text: str, color: str):
        """状态加载完成回调，子类应重写此方法来更新 UI"""
        raise NotImplementedError("子类必须实现 _on_status_loaded 方法")
