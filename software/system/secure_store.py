"""安全存储。Windows 用 DPAPI+注册表，macOS 用 Keychain。"""
from __future__ import annotations

import base64
import ctypes
import importlib
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Optional, cast

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover
    winreg = None

try:  # pragma: no cover - 缺依赖时走 unsupported
    keyring = importlib.import_module("keyring")
    _keyring_errors = importlib.import_module("keyring.errors")
    KeyringError = cast(type[Exception], getattr(_keyring_errors, "KeyringError"))
    PasswordDeleteError = cast(type[Exception], getattr(_keyring_errors, "PasswordDeleteError"))
except Exception:  # pragma: no cover
    keyring = None
    KeyringError = Exception
    PasswordDeleteError = Exception

_REGISTRY_PATH = r"Software\SurveyController\SecureStore"
_KEYRING_SERVICE = "SurveyController"


def _windows_dlls() -> Any:
    return cast(Any, ctypes).windll


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


def _normalize_key(key: str) -> str:
    return str(key or "").strip()


def _crypt_protect_data(data: bytes) -> bytes:
    if not data:
        return b""
    in_buffer = ctypes.create_string_buffer(data, len(data))
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    dlls = _windows_dlls()
    result = dlls.crypt32.CryptProtectData(
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
        dlls.kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect_data(data: bytes) -> bytes:
    if not data:
        return b""
    in_buffer = ctypes.create_string_buffer(data, len(data))
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    dlls = _windows_dlls()
    result = dlls.crypt32.CryptUnprotectData(
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
        dlls.kernel32.LocalFree(out_blob.pbData)


def _read_secret_windows(name: str) -> SecretReadResult:
    if winreg is None:
        return SecretReadResult(status="unsupported")
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
        return SecretReadResult(exists=True, status="not_found")
    try:
        encrypted = base64.b64decode(encoded_text)
        value = _crypt_unprotect_data(encrypted).decode("utf-8")
    except Exception as exc:
        return SecretReadResult(exists=True, status="backend_error", error=str(exc))
    return SecretReadResult(value=value, exists=True, status="ok")


def _set_secret_windows(name: str, value: str) -> None:
    if winreg is None:
        raise RuntimeError("unsupported")
    encrypted = _crypt_protect_data(str(value).encode("utf-8"))
    encoded = base64.b64encode(encrypted).decode("ascii")
    hkey = winreg.HKEY_CURRENT_USER
    reg_key = winreg.CreateKeyEx(hkey, _REGISTRY_PATH, 0, winreg.KEY_WRITE)
    try:
        winreg.SetValueEx(reg_key, name, 0, winreg.REG_SZ, encoded)
    finally:
        winreg.CloseKey(reg_key)


def _delete_secret_windows(name: str) -> None:
    if winreg is None:
        raise RuntimeError("unsupported")
    hkey = winreg.HKEY_CURRENT_USER
    with winreg.OpenKey(hkey, _REGISTRY_PATH, 0, winreg.KEY_SET_VALUE) as reg_key:
        winreg.DeleteValue(reg_key, name)


def _read_secret_macos(name: str) -> SecretReadResult:
    if keyring is None:
        return SecretReadResult(status="unsupported")
    try:
        value = keyring.get_password(_KEYRING_SERVICE, name)
    except KeyringError as exc:
        return SecretReadResult(status="open_failed", error=str(exc))
    except Exception as exc:
        return SecretReadResult(status="backend_error", error=str(exc))
    if value is None:
        return SecretReadResult(status="not_found")
    return SecretReadResult(value=str(value), exists=True, status="ok")


def _set_secret_macos(name: str, value: str) -> None:
    if keyring is None:
        raise RuntimeError("unsupported")
    keyring.set_password(_KEYRING_SERVICE, name, str(value))


def _delete_secret_macos(name: str) -> None:
    if keyring is None:
        raise RuntimeError("unsupported")
    keyring.delete_password(_KEYRING_SERVICE, name)


def set_secret(key: str, value: Optional[str]) -> None:
    name = _normalize_key(key)
    if not name:
        return
    if value is None or value == "":
        delete_secret(name)
        return
    try:
        if sys.platform == "win32":
            _set_secret_windows(name, str(value))
            return
        if sys.platform == "darwin":
            _set_secret_macos(name, str(value))
            return
    except KeyringError as exc:
        logging.warning("安全存储写入失败：key=%s status=write_failed error=%s", name, exc)
        return
    except Exception as exc:
        logging.warning("安全存储写入失败：key=%s status=backend_error error=%s", name, exc)
        return


def read_secret(key: str) -> SecretReadResult:
    name = _normalize_key(key)
    if not name:
        return SecretReadResult(status="invalid_key")
    if sys.platform == "win32":
        return _read_secret_windows(name)
    if sys.platform == "darwin":
        return _read_secret_macos(name)
    return SecretReadResult(status="unsupported")


def delete_secret(key: str) -> None:
    name = _normalize_key(key)
    if not name:
        return
    try:
        if sys.platform == "win32":
            _delete_secret_windows(name)
            return
        if sys.platform == "darwin":
            _delete_secret_macos(name)
            return
    except FileNotFoundError:
        return
    except PasswordDeleteError:
        return
    except KeyringError as exc:
        logging.warning("安全存储删除失败：key=%s status=delete_failed error=%s", name, exc)
    except OSError:
        return
    except Exception as exc:
        logging.warning("安全存储删除失败：key=%s status=backend_error error=%s", name, exc)
