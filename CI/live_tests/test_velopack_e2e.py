"""Velopack 增量更新端到端测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_velopack_e2e() -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "CI.live_tests.run_velopack_e2e"],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=10800,
    )
    assert result.returncode == 0, (
        f"Velopack E2E failed.\nExit code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
