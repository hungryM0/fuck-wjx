#!/usr/bin/env python
"""Python 编译快检。"""

from __future__ import annotations

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    iter_compile_targets,
    print_issues,
    print_scan_targets,
    run_compile_checks,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()
    compile_targets = iter_compile_targets()

    print_scan_targets(target_dirs)
    print(f"[INFO] Compile targets: {len(compile_targets)}")

    issues = run_compile_checks(compile_targets)
    print(f"[INFO] Compile issues: {len(issues)}")
    if not issues:
        print("[PASS] Compile checks passed.")
        return 0

    print(f"[FAIL] Found {len(issues)} compile issue(s):")
    print_issues("[Compile failures]", issues)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
