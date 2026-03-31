"""运行时钩子：macOS 下在 PySide6 加载前设置 Qt 插件路径

这个钩子在所有 Python import 之前执行。
macOS .app bundle 需要正确设置 Qt 插件搜索路径。
"""
import os
import sys

if getattr(sys, 'frozen', False):
    # macOS .app bundle 内 _MEIPASS 指向 Contents/Frameworks 或 Contents/MacOS
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))

    pyside6_dir = os.path.join(bundle_dir, 'PySide6')
    qt_dir = os.path.join(pyside6_dir, 'Qt')

    # 设置 Qt 插件路径
    # macOS bundle 中 Qt 插件可能在多个位置
    plugin_candidates = [
        os.path.join(qt_dir, 'plugins'),
        os.path.join(pyside6_dir, 'plugins'),
        os.path.join(pyside6_dir, 'Qt', 'plugins'),
    ]

    for plugins_dir in plugin_candidates:
        if os.path.isdir(plugins_dir):
            os.environ['QT_PLUGIN_PATH'] = plugins_dir
            break

    # 确保 DYLD_LIBRARY_PATH 和 DYLD_FRAMEWORK_PATH 包含必要路径
    lib_dirs = []
    if os.path.isdir(pyside6_dir):
        lib_dirs.append(pyside6_dir)
    if os.path.isdir(os.path.join(pyside6_dir, 'Qt', 'lib')):
        lib_dirs.append(os.path.join(pyside6_dir, 'Qt', 'lib'))
    if os.path.isdir(bundle_dir):
        lib_dirs.append(bundle_dir)

    if lib_dirs:
        existing_path = os.environ.get('DYLD_LIBRARY_PATH', '')
        new_path = os.pathsep.join(lib_dirs)
        if existing_path:
            new_path = new_path + os.pathsep + existing_path
        os.environ['DYLD_LIBRARY_PATH'] = new_path

    # 避免 macOS 上 Qt 尝试加载 Metal 渲染器时出现问题
    # 如果系统不支持，可以回退到 OpenGL
    if 'QT_QUICK_BACKEND' not in os.environ:
        os.environ['QT_QUICK_BACKEND'] = 'software'
