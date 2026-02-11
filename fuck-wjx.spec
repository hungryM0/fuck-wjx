# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_all
import os
import glob as _glob

binaries = []
binaries += collect_dynamic_libs('pyzbar')

# 收集 qfluentwidgets
qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all('qfluentwidgets')

# === PySide6 白名单：只打包实际用到的模块 ===
# 项目只用到 QtCore, QtGui, QtWidgets, QtNetwork
import PySide6
pyside6_dir = os.path.dirname(PySide6.__file__)

# 白名单 DLL 分两类：
# - .dll 文件放到根目录（exe 同目录），Windows 自动搜索
# - .pyd 文件放到 PySide6/ 子目录，Python import 需要
pyside6_root_dlls = {
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll',
    'Qt6Svg.dll', 'Qt6SvgWidgets.dll', 'Qt6Xml.dll',
    'Qt6Multimedia.dll', 'Qt6MultimediaWidgets.dll',
    'pyside6.abi3.dll',
}
pyside6_pyd_files = {
    'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtNetwork.pyd',
    'QtSvg.pyd', 'QtSvgWidgets.pyd', 'QtXml.pyd',
    'QtMultimedia.pyd', 'QtMultimediaWidgets.pyd',
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
    ('wjx/data', 'wjx/data'),
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
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
]
hiddenimports = qfw_hiddenimports + pyside6_modules + ['shiboken6']
binaries += qfw_binaries + pyside_binaries

a = Analysis(
    ['fuck-wjx.py'],
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
        "Pythonwin",
        "pyreadline3",
        # PySide6 黑名单：排除未使用的大模块（防止依赖分析拉回来）
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtPositioning",
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
        "PySide6.QtCharts",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtStateMachine",
    ],
    noarchive=True,
    optimize=2,
)

# === 在 Analysis 之后强制过滤掉不需要的 PySide6 DLL ===
# excludes 只对 Python import 有效，对二进制 DLL 无效
# 所以需要在这里手动过滤 a.binaries
_pyside6_keep = {
    # 根目录的 DLL
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll',
    'Qt6Svg.dll', 'Qt6SvgWidgets.dll', 'Qt6Xml.dll',
    'Qt6Multimedia.dll', 'Qt6MultimediaWidgets.dll',
    'pyside6.abi3.dll',
    # PySide6/ 目录的 PYD
    'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtNetwork.pyd',
    'QtSvg.pyd', 'QtSvgWidgets.pyd', 'QtXml.pyd',
    'QtMultimedia.pyd', 'QtMultimediaWidgets.pyd',
}

def _is_unwanted_pyside6(name):
    """判断是否为不需要的 PySide6 DLL"""
    basename = os.path.basename(name)
    # 保留白名单内的
    if basename in _pyside6_keep:
        return False
    # 过滤 PySide6 目录下的 Qt6*.dll 和 Qt*.pyd
    if 'PySide6' in name or 'pyside6' in name.lower():
        if basename.startswith('Qt6') and basename.endswith('.dll'):
            return True
        if basename.startswith('Qt') and basename.endswith('.pyd'):
            return True
        # 过滤 avcodec/avformat/avutil 等多媒体库
        if basename.startswith('av') and basename.endswith('.dll'):
            return True
        # 过滤 opengl32sw.dll（软件 OpenGL 渲染，20MB）
        if basename == 'opengl32sw.dll':
            return True
    return False

a.binaries = [b for b in a.binaries if not _is_unwanted_pyside6(b[0])]

# 同时过滤 datas 中不需要的 PySide6 子目录（qml、translations 等）
_pyside6_keep_data_dirs = {'plugins'}
def _is_unwanted_pyside6_data(name):
    """过滤不需要的 PySide6 数据文件"""
    if 'PySide6' in name:
        parts = name.replace('\\', '/').split('/')
        if len(parts) >= 2:
            subdir = parts[1] if parts[0] == 'PySide6' else None
            if subdir and subdir not in _pyside6_keep_data_dirs:
                # qml、translations 等子目录不需要
                if subdir in ('qml', 'translations', 'typesystems', 'glue'):
                    return True
    return False

a.datas = [d for d in a.datas if not _is_unwanted_pyside6_data(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    icon='icon.ico',
    name='fuck-wjx',
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
