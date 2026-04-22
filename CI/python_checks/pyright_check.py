#!/usr/bin/env python
"""Pyright 静态检查。"""

from __future__ import annotations

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    print_issues,
    print_scan_targets,
    run_pyright_check,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()

    print_scan_targets(target_dirs)
    issues, error = run_pyright_check(target_dirs)
    if error:
        print(f"[ERROR] {error}")
        return 2

    print(f"[INFO] Pyright diagnostics: {len(issues)}")
    if not issues:
        print("[PASS] Pyright checks passed.")
        return 0

    print(f"[FAIL] Found {len(issues)} Pyright diagnostic(s):")
    print_issues("[Pyright diagnostics]", issues)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
