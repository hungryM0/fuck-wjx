#!/usr/bin/env python
"""使用 vulture 检查 wjx/ 目录下所有 Python 文件的未引用死代码。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
TARGET_DIR = ROOT_DIR / "wjx"

# 最小置信度：80 可过滤掉大量误报（如协议方法、Qt 槽函数等）
MIN_CONFIDENCE = 80


def main() -> int:
    if not TARGET_DIR.exists():
        print(f"[ERROR] 目录不存在: {TARGET_DIR}")
        return 2

    result = subprocess.run(
        [
            sys.executable, "-m", "vulture",
            str(TARGET_DIR),
            "--min-confidence", str(MIN_CONFIDENCE),
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )

    # 只有 stdout 无内容且 stderr 有报错才视为执行失败（vulture 不同版本退出码不一致）
    if not result.stdout.strip() and result.stderr.strip():
        print(f"[ERROR] vulture 执行失败:\n{result.stderr.strip()}")
        return 2
    if not result.stdout.strip() and not result.stderr.strip() and result.returncode not in (0, 1):
        print("[ERROR] vulture 执行失败（无输出，请确认已安装：pip install vulture）")
        return 2

    lines = [l for l in result.stdout.splitlines() if l.strip()]
    py_count = sum(1 for _ in TARGET_DIR.rglob("*.py") if "__pycache__" not in _.parts)
    print(f"[INFO] 扫描文件数: {py_count}")
    print(f"[INFO] 发现死代码数: {len(lines)}")

    if not lines:
        print("[PASS] 未发现死代码（置信度 >= {MIN_CONFIDENCE}%）。")
        return 0

    print(f"[FAIL] 发现 {len(lines)} 处疑似死代码（置信度 >= {MIN_CONFIDENCE}%）：")
    for i, line in enumerate(lines, 1):
        # 将绝对路径转为相对路径，方便阅读
        try:
            rel_line = line.replace(str(ROOT_DIR) + "\\", "").replace(str(ROOT_DIR) + "/", "")
        except Exception:
            rel_line = line
        print(f"{i}. {rel_line}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
