# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_all
import os

binaries = []
binaries += collect_dynamic_libs('pyzbar')
qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all('qfluentwidgets')
pyside_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui', 
    'PySide6.QtWidgets',
]

# 使用相对路径，PyInstaller 会正确地将这些文件打包进 EXE
datas = [
    ('assets', 'assets'),
    ('wjx/data', 'wjx/data'),
    ('icon.ico', '.'),
] + qfw_datas
hiddenimports = qfw_hiddenimports + pyside_hiddenimports
binaries += qfw_binaries

a = Analysis(
    ['fuck-wjx.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    noarchive=True,
    optimize=2,
)
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
    contents_directory='.',
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
