import logging
import os
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Any

from .config import LOG_BUFFER_CAPACITY, LOG_FORMAT, LOG_DIR_NAME


LOG_LIGHT_THEME = {
    "background": "#ffffff",
    "foreground": "#1e1e1e",
    "insert": "#1e1e1e",
    "select_bg": "#cfe8ff",
    "select_fg": "#1e1e1e",
    "highlight_bg": "#d9d9d9",
    "highlight_color": "#a6a6a6",
    "info_color": "#1e1e1e",
}

LOG_DARK_THEME = {
    "background": "#292929",
    "foreground": "#ffffff",
    "insert": "#ffffff",
    "select_bg": "#333333",
    "select_fg": "#ffffff",
    "highlight_bg": "#1e1e1e",
    "highlight_color": "#3c3c3c",
    "info_color": "#f0f0f0",
}


ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
ORIGINAL_EXCEPTHOOK = sys.excepthook


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
    def __init__(self, capacity: int = LOG_BUFFER_CAPACITY):
        super().__init__()
        self.capacity = capacity
        self.records: List[LogBufferEntry] = []
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        try:
            original_level = record.levelname
            message = self.format(record)
            category = self._determine_category(record, message)
            display_text = self._apply_category_label(message, original_level, category)
            self.records.append(LogBufferEntry(text=display_text, category=category))
            if self.capacity and len(self.records) > self.capacity:
                self.records.pop(0)
        except Exception:
            self.handleError(record)

    def get_records(self) -> List[LogBufferEntry]:
        return list(self.records)

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
    logging.info(f"[Popup Info] {title} | {message}")
    from tkinter import messagebox

    return messagebox.showinfo(title, message, **kwargs)


def log_popup_error(title: str, message: str, **kwargs: Any):
    logging.error(f"[Popup Error] {title} | {message}")
    from tkinter import messagebox

    return messagebox.showerror(title, message, **kwargs)


def log_popup_warning(title: str, message: str, **kwargs: Any):
    logging.warning(f"[Popup Warning] {title} | {message}")
    from tkinter import messagebox

    return messagebox.showwarning(title, message, **kwargs)


def log_popup_confirm(title: str, message: str, **kwargs: Any) -> bool:
    logging.info(f"[Popup Confirm] {title} | {message}")
    from tkinter import messagebox

    return bool(messagebox.askyesno(title, message, **kwargs))
