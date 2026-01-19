# -*- coding: utf-8 -*-
"""
PyInstaller hook for pyzbar - ensures libzbar is found
"""
from PyInstaller.utils.hooks import collect_dynamic_libs
import os

# Collect pyzbar's dynamic libraries
binaries = collect_dynamic_libs('pyzbar')

# Add zbar from Homebrew
zbar_lib = '/opt/homebrew/lib/libzbar.0.dylib'
if os.path.exists(zbar_lib):
    binaries.append((zbar_lib, '.'))

# Also add the unversioned dylib
zbar_lib_unversioned = '/opt/homebrew/lib/libzbar.dylib'
if os.path.exists(zbar_lib_unversioned):
    binaries.append((zbar_lib_unversioned, '.'))

hiddenimports = ['pyzbar.pyzbar', 'pyzbar.wrapper', 'pyzbar.zbar_library']
