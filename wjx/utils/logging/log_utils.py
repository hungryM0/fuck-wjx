"""日志配置与工具函数 - 初始化日志系统、级别控制、缓冲区管理"""
import logging
import os
import re
import sys
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Deque, List, Optional

from wjx.utils.app.config import LOG_BUFFER_CAPACITY, LOG_FORMAT, LOG_DIR_NAME


ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
ORIGINAL_EXCEPTHOOK = sys.excepthook
_popup_handler: Optional[Callable[[str, str, str], Any]] = None


def log_suppressed_exception(
    context: str,
    exc: Optional[BaseException] = None,
    *,
    level: int = logging.DEBUG,
) -> None:
    """记录被吞掉的异常，默认只在调试级别输出。"""
    try:
        if exc is None:
            logging.log(level, "[Suppressed] %s", context)
        else:
            logging.log(level, "[Suppressed] %s: %s", context, exc, exc_info=True)
    except Exception:
        # 记录日志失败不应影响主流程
        pass


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
        self._buffer += text.replace("\r", "")
        if "\n" in self._buffer:
            parts = self._buffer.split("\n")
            self._buffer = parts.pop()
            for line in parts:
                self.logger.log(self.level, line)
        if self.stream:
            try:
                self.stream.write(message)
            except Exception:
                pass

    def flush(self):
        if self._buffer:
            self.logger.log(self.level, self._buffer)
            self._buffer = ""
        if self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass


@dataclass
class LogBufferEntry:
    text: str
    category: str


class LogBufferHandler(logging.Handler):
    # ANSI 转义序列正则表达式
    _ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*m')
    
    def __init__(self, capacity: int = LOG_BUFFER_CAPACITY):
        super().__init__()
        self.capacity = capacity
        self._lock = threading.Lock()
        self.records: Deque[LogBufferEntry] = deque(maxlen=capacity if capacity else None)
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        try:
            original_level = record.levelname
            message = self.format(record)
            # 清理 ANSI 转义序列
            message = self._strip_ansi_codes(message)
            # 过滤包含敏感信息的日志（只过滤特定服务）
            if self._should_filter_sensitive(message):
                return
            category = self._determine_category(record, message)
            display_text = self._apply_category_label(message, original_level, category)
            entry = LogBufferEntry(text=display_text, category=category)
            with self._lock:
                self.records.append(entry)
        except Exception:
            self.handleError(record)

    def get_records(self) -> List[LogBufferEntry]:
        with self._lock:
            return list(self.records)
    
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
        # 过滤特定服务的API请求日志（只过滤这一个域名）
        sensitive_patterns = [
            "service.ipzan.com",
            "userProduct-get",
            "20260112572376490874",
            "72FH7U4E0IG",
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


LOG_BUFFER_HANDLER = LogBufferHandler()
# 立即把缓冲处理器注册到根日志记录器，保证启动前的日志也能被收集
_root_logger = logging.getLogger()
if not any(isinstance(h, LogBufferHandler) for h in _root_logger.handlers):
    _root_logger.addHandler(LOG_BUFFER_HANDLER)
_root_logger.setLevel(logging.INFO)


def set_debug_mode(enabled: bool):
    """动态设置调试模式，开启/关闭 DEBUG 级别日志输出"""
    root_logger = logging.getLogger()
    level = logging.DEBUG if enabled else logging.INFO
    root_logger.setLevel(level)
    # 同时更新所有 handler 的级别
    for handler in root_logger.handlers:
        if not isinstance(handler, LogBufferHandler):  # BufferHandler 保持收集所有级别
            handler.setLevel(level)


def setup_logging():
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    root_logger.setLevel(logging.INFO)
    if not any(isinstance(handler, LogBufferHandler) for handler in root_logger.handlers):
        root_logger.addHandler(LOG_BUFFER_HANDLER)

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
            logging.debug("popup handler failed", exc_info=True)
    return default


def _ensure_logs_dir(runtime_directory: str) -> str:
    logs_dir = os.path.join(runtime_directory, LOG_DIR_NAME)
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def save_log_records_to_file(records: List[LogBufferEntry], runtime_directory: str) -> str:
    if not runtime_directory:
        raise ValueError("runtime_directory 不能为空")
    logs_dir = _ensure_logs_dir(runtime_directory)
    file_name = datetime.now().strftime("log_%Y%m%d_%H%M%S.txt")
    file_path = os.path.join(logs_dir, file_name)
    text_records = [entry.text for entry in (records or [])]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(text_records))
    return file_path


def dump_threads_to_file(tag: str, runtime_directory: str) -> Optional[str]:
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logs_dir = _ensure_logs_dir(runtime_directory)
        file_path = os.path.join(logs_dir, f"thread_dump_{tag}_{ts}.txt")
        frames = sys._current_frames()
        lines: List[str] = []
        for tid, frame in frames.items():
            thr = next((t for t in threading.enumerate() if t.ident == tid), None)
            name = thr.name if thr else "Unknown"
            lines.append(f"### Thread {name} (id={tid}) ###")
            lines.extend(traceback.format_stack(frame))
            lines.append("")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logging.info(f"[Debug] 线程堆栈已导出：{file_path}")
        return file_path
    except Exception as exc:
        logging.debug(f"导出线程堆栈失败: {exc}", exc_info=True)
        return None


def log_popup_info(title: str, message: str, **kwargs: Any):
    """Informational popup routed to the active UI handler (if any)."""
    return _dispatch_popup("info", title, message, default=True)


def log_popup_error(title: str, message: str, **kwargs: Any):
    """Error popup routed to the active UI handler (if any)."""
    return _dispatch_popup("error", title, message, default=False)


def log_popup_warning(title: str, message: str, **kwargs: Any):
    """Warning popup routed to the active UI handler (if any)."""
    return _dispatch_popup("warning", title, message, default=True)


def log_popup_confirm(title: str, message: str, **kwargs: Any) -> bool:
    """Confirmation dialog routed to the active UI handler (if any)."""
    return bool(_dispatch_popup("confirm", title, message, default=False))
