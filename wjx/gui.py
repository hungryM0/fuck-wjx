import sys
import time

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from wjx.boot import preload_boot_splash, update_boot_splash, close_boot_splash
from wjx.utils.log_utils import setup_logging


def main():
    setup_logging()
    app = QApplication(sys.argv)
    
    # 显示启动画面
    preload_boot_splash(message="正在准备...")
    app.processEvents()
    
    # 模拟加载过程，逐步更新进度
    update_boot_splash(15, "正在加载界面组件...")
    app.processEvents()
    time.sleep(0.15)
    
    update_boot_splash(30, "正在初始化配置...")
    app.processEvents()
    time.sleep(0.15)
    
    # 导入主窗口模块（这是主要耗时操作）
    update_boot_splash(50, "正在加载主窗口...")
    app.processEvents()
    from wjx.ui.main_window import create_window
    
    update_boot_splash(70, "正在创建窗口...")
    app.processEvents()
    time.sleep(0.1)
    
    window = create_window()
    
    update_boot_splash(90, "即将完成...")
    app.processEvents()
    time.sleep(0.15)
    
    update_boot_splash(100, "启动完成！")
    app.processEvents()
    time.sleep(0.1)
    
    # 关闭启动画面，显示主窗口
    close_boot_splash()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
