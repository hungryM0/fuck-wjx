"""Windows 安全存储：DPAPI + 注册表。"""
from __future__ import annotations

import base64
import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover
    winreg = None

_REGISTRY_PATH = r"Software\SurveyController\SecureStore"


@dataclass(frozen=True)
class SecretReadResult:
    value: str = ""
    exists: bool = False
    status: str = "not_found"
    error: str = ""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _crypt_protect_data(data: bytes) -> bytes:
    if not data:
        return b""
    in_buffer = ctypes.create_string_buffer(data, len(data))
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    result = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not result:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)  # type: ignore[attr-defined]


def _crypt_unprotect_data(data: bytes) -> bytes:
    if not data:
        return b""
    in_buffer = ctypes.create_string_buffer(data, len(data))
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    result = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not result:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)  # type: ignore[attr-defined]


def set_secret(key: str, value: Optional[str]) -> None:
    if winreg is None:
        return
    name = str(key or "").strip()
    if not name:
        return
    if value is None or value == "":
        delete_secret(name)
        return
    try:
        encrypted = _crypt_protect_data(str(value).encode("utf-8"))
        encoded = base64.b64encode(encrypted).decode("ascii")
        hkey = winreg.HKEY_CURRENT_USER
        reg_key = winreg.CreateKeyEx(hkey, _REGISTRY_PATH, 0, winreg.KEY_WRITE)
        try:
            winreg.SetValueEx(reg_key, name, 0, winreg.REG_SZ, encoded)
        finally:
            winreg.CloseKey(reg_key)
    except Exception as exc:
        logging.warning("安全存储写入失败：key=%s error=%s", name, exc)


def read_secret(key: str) -> SecretReadResult:
    if winreg is None:
        return SecretReadResult(status="unsupported")
    name = str(key or "").strip()
    if not name:
        return SecretReadResult(status="invalid_key")
    hkey = winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(hkey, _REGISTRY_PATH) as reg_key:
            encoded, _ = winreg.QueryValueEx(reg_key, name)
    except FileNotFoundError:
        return SecretReadResult(status="not_found")
    except Exception as exc:
        return SecretReadResult(status="open_failed", error=str(exc))
    encoded_text = str(encoded or "").strip()
    if not encoded_text:
        return SecretReadResult(exists=True, status="empty")
    try:
        encrypted = base64.b64decode(encoded_text)
        value = _crypt_unprotect_data(encrypted).decode("utf-8")
    except Exception as exc:
        return SecretReadResult(exists=True, status="decrypt_failed", error=str(exc))
    return SecretReadResult(value=value, exists=True, status="ok")


def delete_secret(key: str) -> None:
    if winreg is None:
        return
    name = str(key or "").strip()
    if not name:
        return
    hkey = winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(hkey, _REGISTRY_PATH, 0, winreg.KEY_SET_VALUE) as reg_key:
            winreg.DeleteValue(reg_key, name)
    except FileNotFoundError:
        return
    except OSError:
        return
    except Exception as exc:
        logging.warning("安全存储删除失败：key=%s error=%s", name, exc)
