# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs
import os

binaries = []
binaries += collect_dynamic_libs('pyzbar')

# 使用相对路径，PyInstaller 会正确地将这些文件打包进 EXE
datas = [
    ('assets', 'assets'),
    ('.env', '.'),
    ('icon.ico', '.'),
]

a = Analysis(
    ['fuck-wjx.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
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
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    icon='icon.ico',
    name='fuck-wjx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
