"""日志配置与工具函数 - 初始化日志系统、级别控制、缓冲区管理"""
import atexit
import logging
import os
import queue
import re
import shutil
import sys
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Deque, List, Optional

from software.app.config import LOG_BUFFER_CAPACITY, LOG_FORMAT
from software.app.config import (
    AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY,
    AUTO_SAVE_LOG_RETENTION_OPTIONS,
    AUTO_SAVE_LOGS_SETTING_KEY,
    DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT,
    DEFAULT_AUTO_SAVE_LOGS,
    app_settings,
    get_bool_from_qsettings,
    get_int_from_qsettings,
)
from software.app.user_paths import get_user_logs_directory


ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
ORIGINAL_EXCEPTHOOK = sys.excepthook
_popup_handler: Optional[Callable[[str, str, str], Any]] = None
_NOISY_LOG_PATTERNS = (
    "QFluentWidgets Pro is now released",
    "https://qfluentwidgets.com/pages/pro",
)
_DEDUPED_LOG_STATE: dict[str, str] = {}
_DEDUPED_LOG_LOCK = threading.Lock()
_SESSION_LOG_HANDLER: Optional[logging.Handler] = None
_SESSION_LOG_PATH = ""
_SESSION_LOG_LOCK = threading.Lock()
_SESSION_LOG_BACKFILLED = False
_DELETE_SESSION_LOG_ON_SHUTDOWN = False
_LOG_LISTENER_ID = 0


def _should_filter_noise(message: str) -> bool:
    """过滤第三方库广告和无意义空行。"""
    if message is None:
        return True
    text = str(message)
    if not text.strip():
        return True
    return any(pattern in text for pattern in _NOISY_LOG_PATTERNS)


def _safe_internal_log(message: str, exc: Optional[BaseException] = None) -> None:
    """在日志系统内部安全输出，避免递归调用 logging。"""
    try:
        ORIGINAL_STDERR.write(f"[LogInternal] {message}\n")
        if exc is not None:
            ORIGINAL_STDERR.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        ORIGINAL_STDERR.flush()
    except Exception:
        try:
            ORIGINAL_STDERR.write("[LogInternal] safe log failed\n")
            ORIGINAL_STDERR.flush()
        except Exception:
            return


def log_suppressed_exception(
    context: str,
    exc: Optional[BaseException] = None,
    *,
    level: int = logging.INFO,
) -> None:
    """记录被吞掉的异常，默认按 INFO 级别输出。"""
    try:
        if exc is None:
            logging.log(level, "[Suppressed] %s", context)
        else:
            logging.log(level, "[Suppressed] %s: %s", context, exc, exc_info=True)
    except Exception as inner_exc:
        # 记录日志失败不应影响主流程
        _safe_internal_log("log_suppressed_exception failed", inner_exc)


def log_deduped_message(
    key: str,
    message: str,
    *,
    level: int = logging.INFO,
) -> bool:
    """同一 key 下只记录内容发生变化的日志，避免后台任务刷屏。"""
    normalized_key = str(key or "").strip()
    normalized_message = str(message or "").strip()
    if not normalized_key or not normalized_message:
        return False
    try:
        with _DEDUPED_LOG_LOCK:
            if _DEDUPED_LOG_STATE.get(normalized_key) == normalized_message:
                return False
            _DEDUPED_LOG_STATE[normalized_key] = normalized_message
        logging.log(level, normalized_message)
        return True
    except Exception as inner_exc:
        _safe_internal_log("log_deduped_message failed", inner_exc)
        return False


def reset_deduped_log_message(key: str) -> None:
    """清空去重状态，让后续同类问题重新输出一次。"""
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return
    try:
        with _DEDUPED_LOG_LOCK:
            _DEDUPED_LOG_STATE.pop(normalized_key, None)
    except Exception as inner_exc:
        _safe_internal_log("reset_deduped_log_message failed", inner_exc)


class StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int, stream=None):
        self.logger = logger
        self.level = level
        self.stream = stream
        self._buffer = ""

    def write(self, message: str):
        if message is None:
            return
        text = str(message)
        if _should_filter_noise(text):
            if self.stream:
                try:
                    self.stream.write(message)
                except Exception as exc:
                    _safe_internal_log("StreamToLogger.write failed", exc)
            return
        self._buffer += text.replace("\r", "")
        if "\n" in self._buffer:
            parts = self._buffer.split("\n")
            self._buffer = parts.pop()
            for line in parts:
                if _should_filter_noise(line):
                    continue
                self.logger.log(self.level, line)
        if self.stream:
            try:
                self.stream.write(message)
            except Exception as exc:
                _safe_internal_log("StreamToLogger.write failed", exc)

    def flush(self):
        if self._buffer and not _should_filter_noise(self._buffer):
            self.logger.log(self.level, self._buffer)
        self._buffer = ""
        if self.stream:
            try:
                self.stream.flush()
            except Exception as exc:
                _safe_internal_log("StreamToLogger.flush failed", exc)


@dataclass
class LogBufferEntry:
    text: str
    category: str


class LogBufferHandler(logging.Handler):
    """完全异步的日志缓冲处理器

    优化策略：
    1. 使用无锁队列（queue.Queue）接收日志
    2. 后台线程负责处理日志（格式化、分类、存储）
    3. 主线程写入日志时完全无阻塞
    4. 读取时使用版本号检测变化，避免无效拷贝
    """

    # ANSI 转义序列正则表达式
    _ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*m')

    def __init__(self, capacity: int = LOG_BUFFER_CAPACITY):
        super().__init__()
        self.capacity = capacity

        # 使用队列接收日志，避免业务线程做格式化和 UI 相关工作
        self._queue: queue.Queue = queue.Queue(maxsize=max(1000, int(capacity or 0) * 4))

        # 处理后的日志记录（只在后台线程中修改）
        self._records: Deque[LogBufferEntry] = deque(maxlen=capacity if capacity else None)
        self._records_lock = threading.RLock()

        # 版本号：每次 _records 变化时递增，用于检测变化
        self._version = 0
        self._version_lock = threading.Lock()
        self._listeners: dict[int, Callable[[int], None]] = {}
        self._listeners_lock = threading.Lock()

        # 后台处理线程
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

        # 启动后台处理线程
        self._start_worker()

    def _start_worker(self):
        """启动后台日志处理线程"""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="LogBufferWorker"
        )
        self._worker_thread.start()

    def _worker_loop(self):
        """后台线程：处理日志队列"""
        while not self._stop_event.is_set():
            try:
                # 批量处理：一次最多处理 100 条日志
                batch = []
                try:
                    # 阻塞等待第一条日志（最多 0.1 秒）
                    record = self._queue.get(timeout=0.1)
                    batch.append(record)

                    # 非阻塞获取更多日志（批量处理）
                    while len(batch) < 100:
                        try:
                            record = self._queue.get_nowait()
                            batch.append(record)
                        except queue.Empty:
                            break
                except queue.Empty:
                    continue

                # 处理批量日志
                for record in batch:
                    self._process_record(record)

                # 更新版本号（表示有新日志）
                with self._version_lock:
                    self._version += 1
                    current_version = self._version
                self._notify_listeners(current_version)

            except Exception as exc:
                # 后台线程不应崩溃
                _safe_internal_log("LogBufferHandler worker loop failed", exc)

    def _process_record(self, record: logging.LogRecord):
        """处理单条日志记录（在后台线程中执行）"""
        try:
            original_level = record.levelname
            message = self.format(record)

            # 过滤包含敏感信息的日志
            if self._should_filter_sensitive(message):
                return
            # 过滤无意义噪声日志（广告、空行）
            if _should_filter_noise(message):
                return

            # 清理 ANSI 转义序列
            message = self._strip_ansi_codes(message)

            # 判断日志类别
            category = self._determine_category(record, message)

            # 应用类别标签
            display_text = self._apply_category_label(message, original_level, category)

            # 构造日志条目并添加到缓冲区
            entry = LogBufferEntry(text=display_text, category=category)
            with self._records_lock:
                self._records.append(entry)

        except Exception as exc:
            # 处理失败不应影响其他日志
            _safe_internal_log("LogBufferHandler process_record failed", exc)

    def emit(self, record: logging.LogRecord):
        """接收日志记录（完全无阻塞）"""
        try:
            # 直接放入队列，不做任何处理
            self._queue.put_nowait(record)
        except queue.Full:
            # 队列满时丢弃日志（极端情况）
            _safe_internal_log("LogBufferHandler queue full, dropping log")
        except Exception:
            self.handleError(record)

    def get_records(self, _try_lock: bool = False) -> List[LogBufferEntry]:
        """获取日志记录"""
        with self._records_lock:
            return list(self._records)

    def get_version(self) -> int:
        """获取当前版本号（用于检测变化）"""
        with self._version_lock:
            return self._version

    def add_listener(self, listener: Callable[[int], None]) -> int:
        """注册日志变化监听。监听函数必须自己切回 UI 线程。"""
        global _LOG_LISTENER_ID
        if not callable(listener):
            return 0
        with self._listeners_lock:
            _LOG_LISTENER_ID += 1
            listener_id = _LOG_LISTENER_ID
            self._listeners[listener_id] = listener
            return listener_id

    def remove_listener(self, listener_id: int) -> None:
        if not listener_id:
            return
        with self._listeners_lock:
            self._listeners.pop(int(listener_id), None)

    def _notify_listeners(self, version: int) -> None:
        with self._listeners_lock:
            listeners = list(self._listeners.values())
        for listener in listeners:
            try:
                listener(version)
            except Exception as exc:
                _safe_internal_log("LogBufferHandler listener failed", exc)

    def stop(self):
        """停止后台处理线程"""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)

    def flush_remaining(self):
        """刷新队列中剩余的日志（在关闭前调用）"""
        try:
            processed = False
            # 处理队列中剩余的所有日志
            while not self._queue.empty():
                try:
                    record = self._queue.get_nowait()
                    self._process_record(record)
                    processed = True
                except queue.Empty:
                    break
            if processed:
                with self._version_lock:
                    self._version += 1
                    current_version = self._version
                self._notify_listeners(current_version)
        except Exception as exc:
            _safe_internal_log("LogBufferHandler flush_remaining failed", exc)

    @staticmethod
    def _strip_ansi_codes(text: str) -> str:
        """移除 ANSI 转义序列"""
        if not text:
            return text
        return LogBufferHandler._ANSI_ESCAPE_PATTERN.sub('', text)

    @staticmethod
    def _should_filter_sensitive(message: str) -> bool:
        """检查是否应过滤包含敏感信息的日志"""
        if not message:
            return False
        sensitive_patterns = [
            "Authorization: Bearer ",
            "refresh_token",
            "access_token",
        ]
        return any(pattern in message for pattern in sensitive_patterns)

    @staticmethod
    def _determine_category(record: logging.LogRecord, message: str) -> str:
        custom_category = getattr(record, "log_category", None)
        if isinstance(custom_category, str):
            normalized = custom_category.strip().upper()
            if normalized in {"INFO", "OK", "WARNING", "ERROR"}:
                return normalized

        level = record.levelname.upper()
        if level in {"ERROR", "CRITICAL"}:
            return "ERROR"
        if level == "WARNING":
            return "WARNING"
        if level in {"OK", "SUCCESS"}:
            return "OK"

        normalized_message = message.upper()
        ok_markers = ("[OK]", "[SUCCESS]", "✅", "✔")
        ok_keywords = (
            "成功",
            "已完成",
            "解析完成",
            "填写完成",
            "填写成功",
            "提交成功",
            "保存成功",
            "恢复成功",
            "加载上次配置",
            "已加载上次配置",
            "加载完成",
        )
        negative_keywords = ("未成功", "未完成", "失败", "错误", "异常")
        if any(marker in message for marker in ok_markers):
            return "OK"
        if normalized_message.startswith("OK"):
            return "OK"
        if any(keyword in message for keyword in ok_keywords):
            if not any(neg in message for neg in negative_keywords):
                return "OK"

        return "INFO"

    @staticmethod
    def _apply_category_label(message: str, original_level: str, category: str) -> str:
        if not message or not original_level:
            return message
        original_label = f"[{original_level.upper()}]"
        replacement_label = f"[{category.upper()}]"

        deduped = LogBufferHandler._collapse_adjacent_label(message, original_label, replacement_label)
        if deduped is not None:
            return deduped

        if category.upper() == original_level.upper():
            return message
        if original_label in message:
            return message.replace(original_label, replacement_label, 1)
        return message

    @staticmethod
    def _collapse_adjacent_label(message: str, original_label: str, target_label: str) -> Optional[str]:
        if not message or not original_label or not target_label:
            return None
        index = message.find(original_label)
        if index == -1:
            return None
        remainder = message[index + len(original_label):]
        trimmed = remainder.lstrip()
        if not trimmed.startswith(target_label):
            return None
        whitespace = remainder[: len(remainder) - len(trimmed)]
        suffix = trimmed[len(target_label):]
        return f"{message[:index]}{target_label}{whitespace}{suffix}"


class AsyncFileHandler(logging.Handler):
    """后台批量写文件，避免日志落盘拖慢业务线程。"""

    _STOP = object()

    def __init__(self, filename: str, *, encoding: str = "utf-8", batch_size: int = 200):
        super().__init__()
        self.baseFilename = os.path.abspath(filename)
        self.encoding = encoding
        self._batch_size = max(1, int(batch_size or 1))
        self._queue: queue.Queue = queue.Queue(maxsize=10000)
        self._closed = False
        self._write_lock = threading.Lock()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="SessionLogFileWriter",
        )
        self._worker_thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            _safe_internal_log("AsyncFileHandler queue full, dropping log")
        except Exception:
            self.handleError(record)

    def _worker_loop(self) -> None:
        try:
            with open(self.baseFilename, "a", encoding=self.encoding) as stream:
                while True:
                    item = self._queue.get()
                    if item is self._STOP:
                        break
                    batch = [item]
                    while len(batch) < self._batch_size:
                        try:
                            next_item = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        if next_item is self._STOP:
                            self._queue.put_nowait(self._STOP)
                            break
                        batch.append(next_item)
                    with self._write_lock:
                        for record in batch:
                            try:
                                stream.write(self.format(record))
                                stream.write("\n")
                            except Exception as exc:
                                _safe_internal_log("AsyncFileHandler write failed", exc)
                        stream.flush()
        except Exception as exc:
            _safe_internal_log("AsyncFileHandler worker failed", exc)

    def flush(self) -> None:
        deadline = datetime.now().timestamp() + 2.0
        while not self._queue.empty() and datetime.now().timestamp() < deadline:
            threading.Event().wait(0.01)
        with self._write_lock:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(self._STOP)
        except Exception:
            pass
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        super().close()


LOG_BUFFER_HANDLER = LogBufferHandler()
# 立即把缓冲处理器注册到根日志记录器，保证启动前的日志也能被收集
_root_logger = logging.getLogger()
if not any(isinstance(h, LogBufferHandler) for h in _root_logger.handlers):
    _root_logger.addHandler(LOG_BUFFER_HANDLER)
_root_logger.setLevel(logging.INFO)
atexit.register(lambda: shutdown_logging())


def _create_session_log_file_path() -> str:
    logs_dir = get_user_logs_directory()
    os.makedirs(logs_dir, exist_ok=True)
    file_name = datetime.now().strftime("session_%Y%m%d_%H%M%S.log")
    return os.path.join(logs_dir, file_name)


def _backfill_session_log_from_buffer() -> None:
    global _SESSION_LOG_BACKFILLED
    if _SESSION_LOG_BACKFILLED or not _SESSION_LOG_PATH:
        return
    records = LOG_BUFFER_HANDLER.get_records()
    if not records:
        _SESSION_LOG_BACKFILLED = True
        return
    try:
        with open(_SESSION_LOG_PATH, "a", encoding="utf-8") as file:
            for entry in records:
                text = str(getattr(entry, "text", "") or "")
                if text:
                    file.write(text)
                    file.write("\n")
        _SESSION_LOG_BACKFILLED = True
    except Exception as exc:
        _safe_internal_log("backfill session log from buffer failed", exc)


def _ensure_session_log_handler(root_logger: Optional[logging.Logger] = None) -> str:
    global _SESSION_LOG_HANDLER, _SESSION_LOG_PATH

    logger = root_logger or logging.getLogger()
    with _SESSION_LOG_LOCK:
        if _SESSION_LOG_HANDLER is not None and _SESSION_LOG_PATH:
            return _SESSION_LOG_PATH

        session_log_path = _create_session_log_file_path()
        handler = AsyncFileHandler(session_log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        _SESSION_LOG_HANDLER = handler
        _SESSION_LOG_PATH = session_log_path
        _backfill_session_log_from_buffer()
        return session_log_path


def flush_session_log_file() -> None:
    handler = _SESSION_LOG_HANDLER
    if handler is None:
        return
    with _SESSION_LOG_LOCK:
        try:
            handler.flush()
        except Exception as exc:
            _safe_internal_log("flush_session_log_file failed", exc)


def get_current_session_log_path() -> str:
    return str(_SESSION_LOG_PATH or "")


def setup_logging():
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    root_logger.setLevel(logging.INFO)
    if not any(isinstance(handler, LogBufferHandler) for handler in root_logger.handlers):
        root_logger.addHandler(LOG_BUFFER_HANDLER)
    _ensure_session_log_handler(root_logger)

    # HTTP 客户端在 INFO 会记录每个成功请求，日志页会被无诊断价值的 2xx 请求刷屏。
    for noisy_logger in ("urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    if not getattr(setup_logging, "_streams_hooked", False):
        stdout_logger = StreamToLogger(root_logger, logging.INFO, stream=ORIGINAL_STDOUT)
        stderr_logger = StreamToLogger(root_logger, logging.ERROR, stream=ORIGINAL_STDERR)
        sys.stdout = stdout_logger
        sys.stderr = stderr_logger

        def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                if ORIGINAL_EXCEPTHOOK:
                    ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
                return
            root_logger.error("未处理的异常", exc_info=(exc_type, exc_value, exc_traceback))
            if ORIGINAL_EXCEPTHOOK:
                ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

        sys.excepthook = _handle_unhandled_exception
        setattr(setup_logging, "_streams_hooked", True)


def register_popup_handler(handler: Optional[Callable[[str, str, str], Any]]) -> None:
    """Register a UI callback used to surface popup messages in a GUI-friendly way."""
    global _popup_handler
    _popup_handler = handler


def _dispatch_popup(kind: str, title: str, message: str, default: Any = None) -> Any:
    """
    Send popup requests to the registered handler. Falls back to logging only
    when no UI handler is available to keep engine code decoupled from GUI/Qt.
    """
    logging.log(
        logging.INFO if kind in {"info", "confirm"} else logging.ERROR if kind == "error" else logging.WARNING,
        f"[Popup {kind.upper()}] {title} | {message}",
    )
    if _popup_handler:
        try:
            return _popup_handler(kind, title, message)
        except Exception:  # pragma: no cover - UI handler errors shouldn't crash engine
            logging.info("popup handler failed", exc_info=True)
    return default


def _ensure_logs_dir(runtime_directory: str) -> str:
    normalized = os.path.abspath(str(runtime_directory or "").strip())
    if not normalized:
        raise ValueError("runtime_directory 不能为空")

    candidate_name = os.path.basename(normalized).lower()
    if candidate_name == "logs":
        logs_dir = normalized
    else:
        logs_dir = os.path.join(normalized, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def get_auto_save_log_settings() -> tuple[bool, int]:
    """读取日志自动保存开关与保留份数。"""
    settings = app_settings()
    enabled = get_bool_from_qsettings(settings.value(AUTO_SAVE_LOGS_SETTING_KEY), DEFAULT_AUTO_SAVE_LOGS)
    max_keep = max(AUTO_SAVE_LOG_RETENTION_OPTIONS) if AUTO_SAVE_LOG_RETENTION_OPTIONS else DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT
    keep_count = get_int_from_qsettings(
        settings.value(AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY),
        DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT,
        minimum=1,
        maximum=max_keep,
    )
    return bool(enabled), int(keep_count)


def prune_session_log_files(runtime_directory: str, keep_count: int) -> int:
    """只保留最近 keep_count 份自动会话日志。"""
    logs_dir = _ensure_logs_dir(runtime_directory)
    keep_count = max(1, int(keep_count))
    candidates: list[tuple[float, str]] = []
    for name in os.listdir(logs_dir):
        if not (name.startswith("session_") and name.endswith(".log")):
            continue
        path = os.path.join(logs_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            candidates.append((os.path.getmtime(path), path))
        except OSError:
            continue
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    removed = 0
    for _mtime, path in candidates[keep_count:]:
        try:
            os.remove(path)
            removed += 1
        except OSError as exc:
            _safe_internal_log(f"prune_session_log_files failed: {path}", exc)
    return removed


def finalize_session_log_persistence(runtime_directory: str) -> None:
    """按用户设置决定是否保留本次会话日志，并清理历史文件。"""
    global _DELETE_SESSION_LOG_ON_SHUTDOWN

    enabled, keep_count = get_auto_save_log_settings()
    logs_dir = _ensure_logs_dir(runtime_directory)
    last_session_path = os.path.join(logs_dir, "last_session.log")

    if enabled:
        export_full_log_to_file(
            runtime_directory,
            last_session_path,
            fallback_records=LOG_BUFFER_HANDLER.get_records(),
        )
        prune_session_log_files(runtime_directory, keep_count)
        _DELETE_SESSION_LOG_ON_SHUTDOWN = False
        return

    _DELETE_SESSION_LOG_ON_SHUTDOWN = True
    try:
        if os.path.isfile(last_session_path):
            os.remove(last_session_path)
    except OSError as exc:
        _safe_internal_log("finalize_session_log_persistence failed to remove last_session.log", exc)


def save_log_records_to_file(
    records: List[LogBufferEntry],
    runtime_directory: str,
    file_path: Optional[str] = None,
) -> str:
    if not runtime_directory:
        raise ValueError("runtime_directory 不能为空")
    if file_path:
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
    else:
        logs_dir = _ensure_logs_dir(runtime_directory)
        file_name = datetime.now().strftime("log_%Y%m%d_%H%M%S.txt")
        file_path = os.path.join(logs_dir, file_name)
    text_records = [entry.text for entry in (records or [])]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(text_records))
    return file_path


def export_full_log_to_file(
    runtime_directory: str,
    file_path: Optional[str] = None,
    *,
    fallback_records: Optional[List[LogBufferEntry]] = None,
) -> str:
    if not runtime_directory:
        raise ValueError("runtime_directory 不能为空")
    if file_path:
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
    else:
        logs_dir = _ensure_logs_dir(runtime_directory)
        file_name = datetime.now().strftime("log_%Y%m%d_%H%M%S.txt")
        file_path = os.path.join(logs_dir, file_name)

    session_log_path = get_current_session_log_path()
    if session_log_path and os.path.isfile(session_log_path):
        flush_session_log_file()
        src = os.path.abspath(session_log_path)
        dst = os.path.abspath(file_path)
        if os.path.normcase(src) == os.path.normcase(dst):
            return file_path
        try:
            with open(src, "r", encoding="utf-8") as source, open(dst, "w", encoding="utf-8") as target:
                shutil.copyfileobj(source, target)
            return file_path
        except Exception as exc:
            _safe_internal_log("export_full_log_to_file fallback to buffer failed to read session log", exc)

    records = fallback_records if fallback_records is not None else LOG_BUFFER_HANDLER.get_records()
    return save_log_records_to_file(records, runtime_directory, file_path)


def log_popup_error(title: str, message: str, **kwargs: Any):
    """Error popup routed to the active UI handler (if any)."""
    _ = kwargs
    return _dispatch_popup("error", title, message, default=False)


def log_popup_warning(title: str, message: str, **kwargs: Any):
    """Warning popup routed to the active UI handler (if any)."""
    _ = kwargs
    return _dispatch_popup("warning", title, message, default=True)


def log_popup_confirm(title: str, message: str, **kwargs: Any) -> bool:
    """Confirmation dialog routed to the active UI handler (if any)."""
    _ = kwargs
    return bool(_dispatch_popup("confirm", title, message, default=False))


def shutdown_logging():
    """优雅关闭日志系统（在程序退出前调用）"""
    try:
        session_log_path = str(_SESSION_LOG_PATH or "")
        # 1. 刷新剩余日志
        LOG_BUFFER_HANDLER.flush_remaining()
        flush_session_log_file()

        # 2. 停止后台线程
        LOG_BUFFER_HANDLER.stop()

        # 3. 恢复标准流（避免守护线程在解释器关闭时写入）
        sys.stdout = ORIGINAL_STDOUT
        sys.stderr = ORIGINAL_STDERR

        # 4. 移除所有 handler（避免在解释器关闭时触发）
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            try:
                handler.close()
                root_logger.removeHandler(handler)
            except Exception:
                pass
        if _DELETE_SESSION_LOG_ON_SHUTDOWN and session_log_path and os.path.isfile(session_log_path):
            try:
                os.remove(session_log_path)
            except OSError as exc:
                _safe_internal_log("shutdown_logging failed to remove session log", exc)
    except Exception as exc:
        _safe_internal_log("shutdown_logging failed", exc)


