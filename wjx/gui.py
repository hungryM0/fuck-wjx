import sys

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from wjx.utils.log_utils import setup_logging

# 跨平台字体配置
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

def get_system_font() -> str:
    """根据平台返回合适的系统字体"""
    if IS_MACOS:
        # macOS 优先使用苹方字体
        for font_name in ["PingFang SC", "Hiragino Sans GB", ".AppleSystemUIFont", "Helvetica Neue"]:
            if QFontDatabase.hasFamily(font_name):
                return font_name
        return "Helvetica Neue"
    elif IS_WINDOWS:
        return "Microsoft YaHei UI"
    else:
        # Linux
        for font_name in ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "Sans"]:
            if QFontDatabase.hasFamily(font_name):
                return font_name
        return "Sans"


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
    
    # 设置默认字体 (跨平台)
    system_font = get_system_font()
    font_size = 13 if IS_MACOS else 9  # macOS 字体通常需要更大
    font = QFont(system_font, font_size)
    app.setFont(font)
    
    # 导入并创建主窗口（主窗口内部会显示 SplashScreen）
    from wjx.ui.main_window import create_window
    window = create_window()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
