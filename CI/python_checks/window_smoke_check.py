#!/usr/bin/env python
"""主窗口冒烟检查。"""

from __future__ import annotations

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    print_issues,
    print_scan_targets,
    run_window_smoke_check,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()

    print_scan_targets(target_dirs)
    issue = run_window_smoke_check()
    print(f"[INFO] Main window smoke failures: {1 if issue else 0}")
    if issue is None:
        print("[PASS] Main window smoke check passed.")
        return 0

    print("[FAIL] Main window smoke check failed:")
    print_issues("[Main window smoke failures]", [issue])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
