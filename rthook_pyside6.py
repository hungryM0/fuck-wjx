"""运行时钩子：在 PySide6 加载前设置 DLL 搜索路径

这个钩子在所有 Python import 之前执行。
由于使用 contents_directory='.'（扁平化目录），需要手动设置 PySide6 的 DLL 路径。
"""
import os
import sys

if getattr(sys, 'frozen', False):
    # 冻结模式下，sys._MEIPASS 是 PyInstaller 解包的临时目录
    # 但 contents_directory='.' 时，所有文件直接在 exe 同目录
    app_dir = os.path.dirname(sys.executable)

    pyside6_dir = os.path.join(app_dir, 'PySide6')
    shiboken6_dir = os.path.join(app_dir, 'shiboken6')

    # 1. 添加到 PATH（必须在 PySide6.__init__ 之前）
    dirs_to_add = []
    if os.path.isdir(pyside6_dir):
        dirs_to_add.append(pyside6_dir)
    if os.path.isdir(shiboken6_dir):
        dirs_to_add.append(shiboken6_dir)

    if dirs_to_add:
        os.environ['PATH'] = os.pathsep.join(dirs_to_add) + os.pathsep + os.environ.get('PATH', '')

    # 2. 使用 os.add_dll_directory（Python 3.8+ / Windows 10 1607+）
    if hasattr(os, 'add_dll_directory'):
        for d in dirs_to_add:
            try:
                os.add_dll_directory(d)
            except OSError:
                pass

    # 3. 设置 Qt 插件路径
    plugins_dir = os.path.join(pyside6_dir, 'plugins')
    if os.path.isdir(plugins_dir):
        os.environ['QT_PLUGIN_PATH'] = plugins_dir
