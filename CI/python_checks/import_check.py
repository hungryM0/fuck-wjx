#!/usr/bin/env python
"""模块导入全检。"""

from __future__ import annotations

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    iter_module_names,
    iter_python_files,
    print_issues,
    print_scan_targets,
    run_module_import_checks,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()
    python_files = iter_python_files()
    modules = iter_module_names(python_files)

    print_scan_targets(target_dirs)
    print(f"[INFO] Python files: {len(python_files)}")
    print(f"[INFO] Module import checks: {len(modules)}")

    issues = run_module_import_checks(modules)
    print(f"[INFO] Module import failures: {len(issues)}")
    if not issues:
        print("[PASS] Module import checks passed.")
        return 0

    print(f"[FAIL] Found {len(issues)} module import failure group(s):")
    print_issues("[Module import failures]", issues)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
