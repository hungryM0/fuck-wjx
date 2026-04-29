"""Windows 本地命令子进程参数辅助。"""

from __future__ import annotations

import locale
from typing import Any


def build_local_text_subprocess_kwargs() -> dict[str, Any]:
    """为读取本机命令输出构建更稳妥的文本模式参数。

    Windows 上应用可能开启 UTF-8 模式，但 taskkill/tasklist 这类系统命令
    仍可能按本地代码页输出。这里优先使用 locale.getencoding()，并开启
    replace 兜底，避免后台 reader 线程因解码失败直接炸掉。
    """

    kwargs: dict[str, Any] = {
        "text": True,
        "errors": "replace",
    }

    encoding = ""
    getencoding = getattr(locale, "getencoding", None)
    if callable(getencoding):
        try:
            encoding = str(getencoding() or "").strip()
        except Exception:
            encoding = ""

    if not encoding:
        try:
            encoding = str(locale.getpreferredencoding(False) or "").strip()
        except Exception:
            encoding = ""

    if encoding:
        kwargs["encoding"] = encoding
    return kwargs


__all__ = ["build_local_text_subprocess_kwargs"]
