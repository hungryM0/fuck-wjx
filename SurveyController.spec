# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

binaries = []

# 收集 qfluentwidgets
qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all('qfluentwidgets')

# === PySide6 白名单：只打包实际用到的模块 ===
import PySide6
pyside6_dir = os.path.dirname(PySide6.__file__)

# 白名单 DLL 分两类：
# - .dll 文件放到根目录（exe 同目录），Windows 自动搜索
# - .pyd 文件放到 PySide6/ 子目录，Python import 需要
pyside6_root_dlls = {
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll',
    'Qt6Svg.dll', 'Qt6SvgWidgets.dll', 'Qt6Xml.dll',
    'Qt6Charts.dll',
    # Qt6Charts.dll 的运行时依赖
    'Qt6OpenGL.dll', 'Qt6OpenGLWidgets.dll',
    'pyside6.abi3.dll',
}
pyside6_pyd_files = {
    'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtNetwork.pyd',
    'QtSvg.pyd', 'QtSvgWidgets.pyd', 'QtXml.pyd',
    'QtCharts.pyd',
}

# 收集白名单内的 PySide6 二进制文件
pyside_binaries = []
for f in os.listdir(pyside6_dir):
    if f in pyside6_root_dlls:
        # DLL 放根目录，Windows DLL 搜索自动找到
        pyside_binaries.append((os.path.join(pyside6_dir, f), '.'))
    elif f in pyside6_pyd_files:
        # PYD 放 PySide6/ 目录，Python import 需要
        pyside_binaries.append((os.path.join(pyside6_dir, f), 'PySide6'))

# 同时把 PySide6 目录下的 VC 运行时也放到根目录
for f in os.listdir(pyside6_dir):
    fl = f.lower()
    if (fl.startswith('msvcp') or fl.startswith('vcruntime') or fl.startswith('concrt')) and fl.endswith('.dll'):
        pyside_binaries.append((os.path.join(pyside6_dir, f), '.'))

# shiboken6 运行时放根目录
import shiboken6
shiboken6_dir = os.path.dirname(shiboken6.__file__)
for f in os.listdir(shiboken6_dir):
    if f.endswith(('.dll', '.pyd')):
        if f.endswith('.pyd'):
            pyside_binaries.append((os.path.join(shiboken6_dir, f), 'shiboken6'))
        else:
            pyside_binaries.append((os.path.join(shiboken6_dir, f), '.'))

# 收集必要的 Qt 插件
qt_plugins_dir = os.path.join(pyside6_dir, 'plugins')
required_plugins = ['platforms', 'styles', 'imageformats', 'networkinformation', 'tls']
pyside_datas = []
for plugin in required_plugins:
    plugin_path = os.path.join(qt_plugins_dir, plugin)
    if os.path.isdir(plugin_path):
        pyside_datas.append((plugin_path, os.path.join('PySide6', 'plugins', plugin)))

# 使用相对路径，PyInstaller 会正确地将这些文件打包进 EXE
datas = [
    ('assets', 'assets'),
    ('software/assets', 'software/assets'),  # 地区数据与法律文档
    ('software/ui/theme.json', 'software/ui'),  # 主题配置（深浅色适配）
    ('icon.ico', '.'),
] + qfw_datas + pyside_datas

pyside6_modules = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    # qfluentwidgets 额外依赖
    'PySide6.QtXml',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    # IP 使用记录页面折线图
    'PySide6.QtCharts',
]

# qframelesswindow 在 Windows 上需要的 pywin32 模块（经源码验证）
pywin32_modules = [
    'win32api',    # win32_utils.py, __init__.py, window_effect.py
    'win32con',    # win32_utils.py, __init__.py, window_effect.py
    'win32gui',    # win32_utils.py, __init__.py, window_effect.py
    'win32print',  # win32_utils.py
]

hiddenimports = qfw_hiddenimports + pyside6_modules + pywin32_modules + [
    'shiboken6',
    # 主窗口模块位于 shell 子目录，显式保留该模块打包
    'software.ui.shell.main_window',
    # 腾讯问卷 runtime 在 registry 中为延迟导入，显式保留 provider 实现
    'tencent.provider.runtime',
]
binaries += qfw_binaries + pyside_binaries

a = Analysis(
    ['SurveyController.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_pyside6.py'],
    excludes=[
        "cryptography",
        "OpenSSL",
        "urllib3.contrib.pyopenssl",
        "lxml",
        "PIL._avif",
        "PIL.AvifImagePlugin",
        "PIL._webp",
        "PIL.WebPImagePlugin",
        # 间接依赖的大垃圾（项目本身不用）
        "matplotlib",
        "mpl_toolkits",
        "pyreadline3",
        # === pywin32 可选组件（qframelesswindow 需要核心模块，只排除高级功能） ===
        "Pythonwin",  # GUI IDE 组件
        "win32com",   # COM 自动化
        "win32traceutil",  # 调试工具
        # === 打包后不需要的工具链（3.1 MB） ===
        "setuptools",
        "pkg_resources",
        "_distutils_hack",
        "distutils",
        "pip",
        # === 调试/测试模块（运行时不需要） ===
        "unittest",
        "doctest",
        "pdb",
        "pydoc",
        "pydoc_data",
        "test",
        # === 项目未使用的 stdlib / 第三方 ===
        "sqlite3",
        "_sqlite3",
        "click",
        "xmlrpc",
        "ftplib",
        "cgi",
        "socketserver",
        "tarfile",
        "pickletools",
        "difflib",
        "fileinput",
        "rlcompleter",
        "tty",
        "plistlib",
        "scipy",
        "pandas",
        # PySide6 黑名单：排除未使用的大模块（防止依赖分析拉回来）
        "PySide6.QtQuickWidgets",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtTest",
        "PySide6.QtSql",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DAnimation",
        "PySide6.QtDataVisualization",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtStateMachine",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
    ],
    noarchive=True,
    optimize=2,
)

# === 在 Analysis 之后强制过滤掉不需要的 PySide6 DLL ===
# excludes 只对 Python import 有效,对二进制 DLL 无效
# 所以需要在这里手动过滤 a.binaries
_pyside6_keep = {
    # 根目录的 DLL
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll',
    'Qt6Svg.dll', 'Qt6SvgWidgets.dll', 'Qt6Xml.dll',
    'Qt6Charts.dll',
    # Qt6Charts.dll 的运行时依赖
    'Qt6OpenGL.dll', 'Qt6OpenGLWidgets.dll',
    'pyside6.abi3.dll',
    # PySide6/ 目录的 PYD
    'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtNetwork.pyd',
    'QtSvg.pyd', 'QtSvgWidgets.pyd', 'QtXml.pyd',
    'QtCharts.pyd',
}

# 多媒体相关 DLL 黑名单（项目不需要音视频处理）。
_pyside6_multimedia_dlls = {
    'swresample-4.dll', 'swscale-7.dll',
}

def _is_unwanted_pyside6(name):
    """判断是否为不需要的 PySide6 DLL"""
    basename = os.path.basename(name)
    # 保留白名单内的
    if basename in _pyside6_keep:
        return False
    # 过滤已知不需要的多媒体 DLL
    if basename.lower() in {x.lower() for x in _pyside6_multimedia_dlls}:
        return True
    # 过滤 PySide6 目录下的 Qt6*.dll 和 Qt*.pyd
    if 'PySide6' in name or 'pyside6' in name.lower():
        if basename.startswith('Qt6') and basename.endswith('.dll'):
            return True
        if basename.startswith('Qt') and basename.endswith('.pyd'):
            return True
        # 过滤 avcodec/avformat/avutil 等多媒体库
        if basename.startswith('av') and basename.endswith('.dll'):
            return True
        # 过滤 PySide6 子目录中重复的 MSVC 运行时（根目录已有一份）
        if (basename.lower().startswith('msvcp') or
            basename.lower().startswith('vcruntime') or
            basename.lower().startswith('concrt')):
            return True
    return False

a.binaries = [b for b in a.binaries if not _is_unwanted_pyside6(b[0])]

# 同时过滤 datas 中不需要的 PySide6 子目录（qml、translations 等）
_pyside6_keep_data_dirs = {'plugins'}
# 只保留实际需要的 Qt 插件
_pyside6_keep_plugins = {'platforms', 'styles', 'imageformats', 'networkinformation', 'tls'}

def _is_unwanted_pyside6_data(name):
    """过滤不需要的 PySide6 数据文件"""
    if 'PySide6' in name:
        parts = name.replace('\\', '/').split('/')
        if len(parts) >= 2:
            subdir = parts[1] if parts[0] == 'PySide6' else None
            if subdir and subdir not in _pyside6_keep_data_dirs:
                # qml、translations、support 等子目录不需要
                if subdir in ('qml', 'translations', 'typesystems', 'glue', 'support'):
                    return True
        # 过滤不需要的 Qt 插件子目录（generic、iconengines、multimedia 等）
        if len(parts) >= 3 and parts[0] == 'PySide6' and parts[1] == 'plugins':
            plugin_name = parts[2]
            if plugin_name not in _pyside6_keep_plugins:
                return True
    return False

a.datas = [d for d in a.datas if not _is_unwanted_pyside6_data(d[0])]

# === 附加体积优化：清理收集进来的冗余依赖和无用文件 ===
def _cleanup_binaries(b_name):
    norm = b_name.replace('\\', '/')
    basename = os.path.basename(norm)
    # 1. 强制清理 PySide6 重复被放置在内层目录的 DLL (根目录已存在)
    if norm.startswith('PySide6/') and basename.endswith('.dll') and basename in pyside6_root_dlls:
        return True
    if norm.startswith('PySide6/') and basename == 'pyside6.abi3.dll':
        return True
    # 2. 清理 CV2 无用的视频编码依赖 (扫码只需图片处理)
    if basename.lower().startswith('opencv_videoio_ffmpeg'):
        return True
    return False

def _cleanup_datas(d_name):
    norm = d_name.replace('\\', '/')
    # 不要裁剪 playwright 的数据文件，避免误删运行时必需资源
    # （历史上这里删 *.json 会导致 Playwright 初始化异常）
    return False

a.binaries = [b for b in a.binaries if not _cleanup_binaries(b[0])]
a.datas = [d for d in a.datas if not _cleanup_datas(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    icon='icon.ico',
    name='SurveyController',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',  # 扁平化目录结构
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lib',
)

