import sys

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from wjx.utils.log_utils import setup_logging


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
