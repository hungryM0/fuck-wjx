#!/usr/bin/env python
"""使用 ruff 检查 wjx/ 目录下所有 Python 文件的语法错误和 import 问题。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
TARGET_DIR = ROOT_DIR / "wjx"

# 检查规则：
#   F    — Pyflakes：未使用的 import、未定义的名称、重复定义等
#   语法错误（原 E999）在 ruff 0.6+ 中已内置，无需显式选择，始终检查
RUFF_SELECT = "F"


def main() -> int:
    if not TARGET_DIR.exists():
        print(f"[ERROR] 目录不存在: {TARGET_DIR}")
        return 2

    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            str(TARGET_DIR),
            "--select", RUFF_SELECT,
            "--output-format", "json",
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )

    # ruff 返回码：0=无问题，1=有诊断，2=内部错误
    if result.returncode == 2:
        print(f"[ERROR] ruff 执行失败:\n{result.stderr.strip()}")
        return 2

    raw = result.stdout.strip()
    try:
        diagnostics: list[dict] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        print(f"[ERROR] 无法解析 ruff 输出:\n{raw}")
        return 2

    py_count = sum(1 for _ in TARGET_DIR.rglob("*.py") if "__pycache__" not in _.parts)
    print(f"[INFO] 扫描文件数: {py_count}")
    print(f"[INFO] 发现诊断数: {len(diagnostics)}")

    if not diagnostics:
        print("[PASS] 所有语法和 import 检查通过，没有报错。")
        return 0

    print(f"[FAIL] 发现 {len(diagnostics)} 处问题：")
    for index, item in enumerate(diagnostics, start=1):
        try:
            rel = Path(item["filename"]).relative_to(ROOT_DIR)
        except ValueError:
            rel = Path(item["filename"])
        row = item["location"]["row"]
        col = item["location"]["column"]
        code = item.get("code", "?")
        message = item.get("message", "")
        print(f"{index}. {rel}:{row}:{col}  [{code}]")
        print(f"   {message}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
