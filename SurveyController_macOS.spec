# -*- mode: python ; coding: utf-8 -*-
"""
macOS PyInstaller spec file for SurveyController
Produces a proper .app bundle for distribution via DMG
"""
from PyInstaller.utils.hooks import collect_all
import os
import sys

binaries = []

# 收集 qfluentwidgets
qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all('qfluentwidgets')

# === PySide6 macOS 构建 ===
import PySide6
pyside6_dir = os.path.dirname(PySide6.__file__)

# macOS 上不需要 DLL 白名单，使用 dylib/framework
# 收集必要的 Qt 插件
qt_plugins_dir = os.path.join(pyside6_dir, 'Qt', 'plugins')
if not os.path.isdir(qt_plugins_dir):
    qt_plugins_dir = os.path.join(pyside6_dir, 'plugins')

required_plugins = ['platforms', 'styles', 'imageformats', 'networkinformation', 'tls']
pyside_datas = []
for plugin in required_plugins:
    plugin_path = os.path.join(qt_plugins_dir, plugin)
    if os.path.isdir(plugin_path):
        pyside_datas.append((plugin_path, os.path.join('PySide6', 'Qt', 'plugins', plugin)))

# 使用相对路径，PyInstaller 会正确地将这些文件打包进 app bundle
datas = [
    ('assets', 'assets'),
    ('software/assets', 'software/assets'),  # 地区数据与法律文档
    ('software/ui/theme.json', 'software/ui'),  # 主题配置（深浅色适配）
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

# macOS 上 qframelesswindow 使用 pyobjc，不需要 pywin32
pyobjc_modules = [
    'objc',
    'AppKit',
    'Cocoa',
    'Foundation',
    'Quartz',
]

hiddenimports = qfw_hiddenimports + pyside6_modules + pyobjc_modules + [
    'shiboken6',
    # 主窗口模块位于 shell 子目录，显式保留该模块打包
    'software.ui.shell.main_window',
    # 腾讯问卷 runtime 在 registry 中为延迟导入，显式保留 provider 实现
    'tencent.provider.runtime',
]
binaries += qfw_binaries

a = Analysis(
    ['SurveyController.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_pyside6_macos.py'],
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
        # === 打包后不需要的工具链 ===
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
        "scipy",
        "pandas",
        # PySide6 黑名单：排除未使用的大模块
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
        # Windows 专属模块
        "win32api",
        "win32con",
        "win32gui",
        "win32print",
        "win32com",
        "Pythonwin",
        "win32traceutil",
        "winreg",
    ],
    noarchive=True,
    optimize=2,
)

# === macOS: 过滤不需要的 PySide6 数据 ===
_pyside6_keep_data_dirs = {'plugins', 'Qt'}
_pyside6_keep_plugins = {'platforms', 'styles', 'imageformats', 'networkinformation', 'tls'}

def _is_unwanted_pyside6_data(name):
    """过滤不需要的 PySide6 数据文件"""
    if 'PySide6' in name:
        parts = name.replace('\\', '/').split('/')
        if len(parts) >= 2:
            subdir = parts[1] if parts[0] == 'PySide6' else None
            if subdir and subdir not in _pyside6_keep_data_dirs:
                if subdir in ('qml', 'translations', 'typesystems', 'glue', 'support'):
                    return True
        # 过滤不需要的 Qt 插件子目录
        for i, part in enumerate(parts):
            if part == 'plugins' and i + 1 < len(parts):
                plugin_name = parts[i + 1]
                if plugin_name not in _pyside6_keep_plugins:
                    return True
    return False

a.datas = [d for d in a.datas if not _is_unwanted_pyside6_data(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SurveyController',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # macOS 上 strip 可以减小体积
    upx=False,   # macOS 上 UPX 可能导致签名问题
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    upx_exclude=[],
    name='SurveyController',
)

# macOS .app bundle
app = BUNDLE(
    coll,
    name='SurveyController.app',
    icon='icon.icns',
    bundle_identifier='top.hungrym0.surveycontroller',
    info_plist={
        'CFBundleName': 'SurveyController',
        'CFBundleDisplayName': 'SurveyController',
        'CFBundleShortVersionString': '3.0.0',
        'CFBundleVersion': '3.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'NSAppleEventsUsageDescription': 'SurveyController 需要自动化权限来控制浏览器。',
        'CFBundleDocumentTypes': [],
        'LSApplicationCategoryType': 'public.app-category.utilities',
        # macOS 暗黑模式支持
        'NSRequiresAquaSystemAppearance': False,
    },
)
