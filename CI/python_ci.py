#!/usr/bin/env python
"""聚合 Python CI 检查入口。"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    iter_compile_targets,
    iter_module_names,
    iter_python_files,
    print_issues,
    print_scan_targets,
    run_compile_checks,
    run_module_import_checks,
    run_pyright_check,
    run_ruff_check,
    run_window_smoke_check,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check syntax, static imports, and startup-chain issues in wjx, software, and tencent."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Enable module import and main window smoke checks. The default is quick mode.",
    )
    pyright_group = parser.add_mutually_exclusive_group()
    pyright_group.add_argument(
        "--pyright",
        dest="pyright_enabled",
        action="store_true",
        help="Enable Pyright diagnostics (enabled by default).",
    )
    pyright_group.add_argument(
        "--no-pyright",
        dest="pyright_enabled",
        action="store_false",
        help="Disable Pyright diagnostics and keep compile and Ruff checks only.",
    )
    parser.set_defaults(pyright_enabled=True)
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    start_time = time.perf_counter()

    target_dirs = ensure_target_dirs()
    python_files = iter_python_files()
    compile_targets = iter_compile_targets()
    modules = iter_module_names(python_files)
    quick_mode = not args.full
    pyright_mode = args.pyright_enabled

    print_scan_targets(target_dirs)
    print(f"[INFO] Check mode: {'quick' if quick_mode else 'full'}")
    print(f"[INFO] Python files: {len(python_files)}")
    print(f"[INFO] Compile targets: {len(compile_targets)}")
    if pyright_mode:
        print("[INFO] Pyright diagnostics: enabled")
    else:
        print("[INFO] Pyright diagnostics: disabled (--no-pyright)")
    if quick_mode:
        print("[INFO] Module import checks: skipped (use --full to enable)")
        print("[INFO] Main window smoke check: skipped (use --full to enable)")
    else:
        print(f"[INFO] Module import checks: {len(modules)}")
        print("[INFO] Main window smoke check: enabled")

    compile_issues = run_compile_checks(compile_targets)
    ruff_issues, ruff_error = run_ruff_check(target_dirs)
    pyright_issues, pyright_error = run_pyright_check(target_dirs) if pyright_mode else ([], None)
    import_issues = run_module_import_checks(modules) if args.full else []
    window_issue = run_window_smoke_check() if args.full else None

    if ruff_error:
        print(f"[ERROR] {ruff_error}")
        return 2
    if pyright_error:
        print(f"[ERROR] {pyright_error}")
        return 2

    total_issues = len(compile_issues) + len(ruff_issues) + len(pyright_issues) + len(import_issues) + (1 if window_issue else 0)
    elapsed = time.perf_counter() - start_time

    print(f"[INFO] Compile issues: {len(compile_issues)}")
    print(f"[INFO] Ruff diagnostics: {len(ruff_issues)}")
    if pyright_mode:
        print(f"[INFO] Pyright diagnostics: {len(pyright_issues)}")
    print(f"[INFO] Module import failures: {len(import_issues)}")
    print(f"[INFO] Main window smoke failures: {1 if window_issue else 0}")
    print(f"[INFO] Elapsed time: {elapsed:.2f}s")

    if total_issues == 0:
        if quick_mode:
            print("[PASS] Quick checks passed: compile, Ruff, and Pyright checks all succeeded.")
            print("[INFO] For import and main window smoke checks, run: python CI/python_ci.py --full")
        else:
            print("[PASS] Full checks passed: compile, Ruff, Pyright, module import, and main window smoke checks all succeeded.")
        return 0

    print(f"[FAIL] Found {total_issues} issue(s):")
    print_issues("[Compile failures]", compile_issues)
    print_issues("[Ruff diagnostics]", ruff_issues)
    if pyright_mode:
        print_issues("[Pyright diagnostics]", pyright_issues)
    print_issues("[Module import failures]", import_issues)
    if window_issue:
        print_issues("[Main window smoke failures]", [window_issue])

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
