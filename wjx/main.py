"""GUI 应用入口 - QApplication 初始化与主窗口启动"""
import sys

from PySide6.QtCore import qInstallMessageHandler, QtMsgType, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from wjx.utils.logging.log_utils import setup_logging, set_debug_mode
from wjx.utils.app.config import get_bool_from_qsettings


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
    setup_logging()

    # 应用保存的调试模式设置
    settings = QSettings("FuckWjx", "Settings")
    debug_mode = get_bool_from_qsettings(settings.value("debug_mode"), False)
    set_debug_mode(debug_mode)

    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(sys.argv)
    
    # 设置默认字体
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    
    # 导入并创建主窗口（主窗口内部会显示 SplashScreen）
    from wjx.ui.main_window import create_window
    window = create_window()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
