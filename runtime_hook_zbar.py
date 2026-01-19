# -*- coding: utf-8 -*-
"""
Runtime hook to patch pyzbar's library loading for PyInstaller on macOS
"""
import os
import sys
import ctypes
from ctypes.util import find_library as _original_find_library

# 获取应用程序的基础路径
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(__file__)

# 预加载 libzbar 并 patch find_library
zbar_path = os.path.join(base_path, 'libzbar.0.dylib')

def _patched_find_library(name):
    if name == 'zbar':
        if os.path.exists(zbar_path):
            return zbar_path
    return _original_find_library(name)

# Patch ctypes.util.find_library
import ctypes.util
ctypes.util.find_library = _patched_find_library

# 同时预加载库
if os.path.exists(zbar_path):
    try:
        ctypes.CDLL(zbar_path, mode=ctypes.RTLD_GLOBAL)
    except Exception:
        pass
