# -*- mode: python ; coding: utf-8 -*-
"""
macOS 打包配置文件
使用方法: pyinstaller fuck-wjx-macos.spec
"""

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_all
import os
import sys

# 确保在 macOS 上运行
if sys.platform != 'darwin':
    print("警告: 此 spec 文件专为 macOS 设计")

binaries = []
binaries += collect_dynamic_libs('pyzbar')

# 手动添加 zbar 库 (brew install zbar)
zbar_lib_path = '/opt/homebrew/lib/libzbar.0.dylib'
if os.path.exists(zbar_lib_path):
    binaries.append((zbar_lib_path, '.'))

# 收集 qfluentwidgets 的所有资源
qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all('qfluentwidgets')

pyside_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui', 
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
]

# 数据文件
datas = [
    ('assets', 'assets'),
    ('icon.ico', '.'),
] + qfw_datas

hiddenimports = qfw_hiddenimports + pyside_hiddenimports + [
    'wjx',
    'wjx.core',
    'wjx.network',
    'wjx.utils',
    'wjx.modes',
    'wjx.ui',
]

binaries += qfw_binaries

a = Analysis(
    ['fuck-wjx.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['runtime_hook_zbar.py'],
    excludes=[
        "numpy",
        "cryptography",
        "OpenSSL",
        "urllib3.contrib.pyopenssl",
        "lxml",
        "PIL._avif",
        "PIL.AvifImagePlugin",
        "PIL._webp",
        "PIL.WebPImagePlugin",
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='fuck-wjx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # macOS 不建议使用 UPX
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
    strip=False,
    upx=False,
    upx_exclude=[],
    name='fuck-wjx',
)

# macOS 应用程序包 (.app)
app = BUNDLE(
    coll,
    name='问卷星速填.app',
    icon='icon.ico',  # PyInstaller 会自动转换为 icns，或者可以准备 icon.icns
    bundle_identifier='com.fuckwjx.app',
    info_plist={
        'CFBundleName': '问卷星速填',
        'CFBundleDisplayName': '问卷星速填',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,  # 支持深色模式
        'LSMinimumSystemVersion': '10.15.0',
        'CFBundleDocumentTypes': [],
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
    },
)
