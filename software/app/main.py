"""GUI 应用入口 - QApplication 初始化与主窗口启动"""
import faulthandler
import os
import sys

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from software.app.config import LOG_DIR_NAME
from software.app.runtime_paths import get_runtime_directory
from software.logging.log_utils import setup_logging
import software.network.http as http_client
from software.ui.helpers.qfluent_compat import install_qfluentwidgets_animation_guards


_FAULT_HANDLER_STREAM = None


def _enable_fault_handler() -> None:
    """为原生崩溃保留最基本的线程栈信息。"""
    global _FAULT_HANDLER_STREAM

    if faulthandler.is_enabled():
        return

    try:
        logs_dir = os.path.join(get_runtime_directory(), LOG_DIR_NAME)
        os.makedirs(logs_dir, exist_ok=True)
        fault_log_path = os.path.join(logs_dir, "fatal_crash.log")
        _FAULT_HANDLER_STREAM = open(fault_log_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(_FAULT_HANDLER_STREAM, all_threads=True)
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            _FAULT_HANDLER_STREAM = None


def _disable_fault_handler() -> None:
    global _FAULT_HANDLER_STREAM

    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass

    stream = _FAULT_HANDLER_STREAM
    _FAULT_HANDLER_STREAM = None
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass


def _qt_message_handler(mode, context, message):
    """过滤 Qt 警告消息"""
    if "QFont::setPointSize" in message:
        return
    if mode == QtMsgType.QtWarningMsg:
        print(f"Qt Warning: {message}")
    elif mode == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}")
    elif mode == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}")


def main():
    _enable_fault_handler()
    setup_logging()

    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(sys.argv)
    install_qfluentwidgets_animation_guards()

    # 设置默认字体（跨平台）
    import sys as _sys
    if _sys.platform == "darwin":
        font = QFont("PingFang SC", 13)  # macOS 默认中文字体，macOS 标准字号
    else:
        font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)

    # 在主线程预热 httpx/httpcore/ssl，避免首次后台请求触发原生层崩溃
    http_client.prewarm()

    # 导入并创建主窗口（主窗口内部会显示 SplashScreen）
    from software.ui.shell.main_window import create_window
    window = create_window()
    window.show()

    exit_code = app.exec()

    # 优雅关闭：停止日志系统后台线程
    from software.logging.log_utils import shutdown_logging
    shutdown_logging()
    _disable_fault_handler()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

