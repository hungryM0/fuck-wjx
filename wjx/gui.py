import sys

from PySide6.QtWidgets import QApplication

from wjx.utils.log_utils import setup_logging


def main():
    setup_logging()
    app = QApplication(sys.argv)
    
    # 导入并创建主窗口（主窗口内部会显示 SplashScreen）
    from wjx.ui.main_window import create_window
    window = create_window()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
