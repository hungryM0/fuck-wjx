#!/usr/bin/env python
"""多层检查核心目录 Python 文件的语法、静态导入和运行时导入问题。"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parent
TARGET_DIRS = [
    ROOT_DIR / "wjx",
    ROOT_DIR / "software",
    ROOT_DIR / "tencent",
]
ENTRY_FILES = [ROOT_DIR / "SurveyController.py"]

# Ruff 规则：
#   F    - Pyflakes：未使用的 import、未定义的名称、重复定义等
#   语法错误在 Ruff 新版本中会直接报告，无需额外开启 E999
RUFF_SELECT = "F"
CHILD_RESULT_PREFIX = "__WJX_CHECK__"
IMPORT_TIMEOUT_SECONDS = 12
WINDOW_SMOKE_TIMEOUT_SECONDS = 25

IMPORT_SMOKE_CODE = r"""
import importlib
import json
import os
import sys
import traceback

PREFIX = "__WJX_CHECK__"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WJX_IMPORT_CHECK", "1")

module_name = sys.argv[1]

try:
    importlib.import_module(module_name)
except BaseException as exc:
    payload = {
        "ok": False,
        "kind": "module_import",
        "module": module_name,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }
    print(PREFIX + json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)

print(PREFIX + json.dumps({"ok": True, "kind": "module_import", "module": module_name}, ensure_ascii=False))
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

WINDOW_SMOKE_CODE = r"""
import json
import os
import sys
import traceback

PREFIX = "__WJX_CHECK__"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WJX_IMPORT_CHECK", "1")

try:
    from PySide6.QtWidgets import QApplication

    from software.ui.shell.main_window import create_window

    app = QApplication.instance() or QApplication([])
    create_window()
except BaseException as exc:
    payload = {
        "ok": False,
        "kind": "window_smoke",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }
    print(PREFIX + json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)

print(PREFIX + json.dumps({"ok": True, "kind": "window_smoke"}, ensure_ascii=False))
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""


def iter_target_dirs() -> list[Path]:
    return [path for path in TARGET_DIRS if path.exists()]


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for target_dir in iter_target_dirs():
        files.extend(
            path for path in target_dir.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(set(files))


def iter_compile_targets() -> list[Path]:
    files = iter_python_files()
    for entry_file in ENTRY_FILES:
        if entry_file.exists():
            files.append(entry_file)
    return sorted(files)


def iter_module_names(files: Iterable[Path]) -> list[str]:
    modules: list[str] = []
    for path in files:
        rel = path.relative_to(ROOT_DIR).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        module_name = ".".join(parts)
        if module_name:
            modules.append(module_name)
    return sorted(set(modules), key=lambda name: (name.count("."), name))


def make_child_env() -> dict[str, str]:
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    root_path = str(ROOT_DIR)
    env["PYTHONPATH"] = root_path if not current_python_path else os.pathsep.join([root_path, current_python_path])
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("WJX_IMPORT_CHECK", "1")
    return env


def format_path(path_str: str | Path) -> Path:
    path = Path(path_str)
    try:
        return path.relative_to(ROOT_DIR)
    except ValueError:
        return path


def extract_child_payload(stdout: str, stderr: str) -> dict | None:
    lines = stdout.splitlines() + stderr.splitlines()
    for line in reversed(lines):
        if line.startswith(CHILD_RESULT_PREFIX):
            payload_raw = line[len(CHILD_RESULT_PREFIX):]
            try:
                return json.loads(payload_raw)
            except json.JSONDecodeError:
                return {"ok": False, "message": payload_raw}
    return None


def summarize_child_output(stdout: str, stderr: str) -> str:
    chunks: list[str] = []
    stdout_text = stdout.strip()
    stderr_text = stderr.strip()
    if stdout_text:
        chunks.append(f"stdout: {stdout_text.splitlines()[-1]}")
    if stderr_text:
        chunks.append(f"stderr: {stderr_text.splitlines()[-1]}")
    return " | ".join(chunks)


def run_compile_checks(files: Iterable[Path]) -> list[dict]:
    issues: list[dict] = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            issues.append(
                {
                    "phase": "compile",
                    "path": format_path(path),
                    "message": exc.msg.strip(),
                }
            )
    return issues


def run_ruff_check(target_dirs: Iterable[Path]) -> tuple[list[dict], str | None]:
    target_args = [str(path) for path in target_dirs]
    if not target_args:
        return [], "未找到可执行 Ruff 检查的目标目录"

    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            *target_args,
            "--select", RUFF_SELECT,
            "--output-format", "json",
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )

    if result.returncode == 2:
        message = result.stderr.strip() or result.stdout.strip() or "ruff 执行失败"
        return [], message

    raw = result.stdout.strip()
    try:
        diagnostics: list[dict] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return [], f"无法解析 ruff 输出: {raw}"

    issues: list[dict] = []
    for item in diagnostics:
        issues.append(
            {
                "phase": "ruff",
                "path": format_path(item["filename"]),
                "row": item["location"]["row"],
                "column": item["location"]["column"],
                "code": item.get("code", "?"),
                "message": item.get("message", ""),
            }
        )
    return issues, None


def run_module_import_checks(modules: Iterable[str]) -> list[dict]:
    issues_by_signature: dict[tuple[str, str, str], dict] = {}
    env = make_child_env()

    for module_name in modules:
        try:
            result = subprocess.run(
                [sys.executable, "-c", IMPORT_SMOKE_CODE, module_name],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                env=env,
                timeout=IMPORT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            signature = ("TimeoutError", f"导入超时（>{IMPORT_TIMEOUT_SECONDS} 秒）", "")
            issue = issues_by_signature.setdefault(
                signature,
                {
                    "phase": "import",
                    "modules": [],
                    "message": signature[1],
                    "error_type": signature[0],
                    "traceback": signature[2],
                }
            )
            issue["modules"].append(module_name)
            continue

        payload = extract_child_payload(result.stdout, result.stderr) or {}
        if result.returncode == 0 and payload.get("ok"):
            continue

        error_type = payload.get("error_type", "ImportError")
        fallback_message = summarize_child_output(result.stdout, result.stderr)
        message = payload.get("message") or fallback_message or "模块导入失败"
        traceback_text = payload.get("traceback", "").strip()
        signature = (error_type, message, traceback_text)
        issue = issues_by_signature.setdefault(
            signature,
            {
                "phase": "import",
                "modules": [],
                "message": message,
                "error_type": error_type,
                "traceback": traceback_text,
            }
        )
        issue["modules"].append(module_name)

    return list(issues_by_signature.values())


def run_window_smoke_check() -> dict | None:
    env = make_child_env()
    try:
        result = subprocess.run(
            [sys.executable, "-c", WINDOW_SMOKE_CODE],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            env=env,
            timeout=WINDOW_SMOKE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "phase": "window",
            "message": f"主窗口创建超时（>{WINDOW_SMOKE_TIMEOUT_SECONDS} 秒）",
        }

    payload = extract_child_payload(result.stdout, result.stderr) or {}
    # 在 Windows + Qt 场景下，子进程偶发非 0 退出码，但已明确输出成功 payload。
    # 这里优先信任结构化结果，避免主窗口冒烟误报。
    if payload.get("kind") == "window_smoke" and payload.get("ok") is True:
        return None

    fallback_message = summarize_child_output(result.stdout, result.stderr)
    return {
        "phase": "window",
        "message": payload.get("message") or fallback_message or "主窗口创建失败",
        "error_type": payload.get("error_type", "RuntimeError"),
        "traceback": payload.get("traceback", "").strip(),
    }


def print_issues(title: str, issues: Iterable[dict]) -> None:
    issue_list = list(issues)
    if not issue_list:
        return

    print(title)
    for index, item in enumerate(issue_list, start=1):
        phase = item["phase"]
        if phase == "ruff":
            print(
                f"{index}. {item['path']}:{item['row']}:{item['column']}  "
                f"[{item.get('code', '?')}]"
            )
            print(f"   {item['message']}")
            continue

        if phase == "compile":
            print(f"{index}. {item['path']}")
            print(f"   {item['message']}")
            continue

        if phase == "import":
            error_type = item.get("error_type", "ImportError")
            modules_text = ", ".join(item.get("modules", []))
            print(f"{index}. {modules_text}  [{error_type}]")
            print(f"   {item['message']}")
            traceback_text = item.get("traceback")
            if traceback_text:
                print("   导入堆栈：")
                for line in traceback_text.splitlines():
                    print(f"   {line}")
            continue

        if phase == "window":
            error_type = item.get("error_type", "RuntimeError")
            print(f"{index}. 主窗口创建  [{error_type}]")
            print(f"   {item['message']}")
            traceback_text = item.get("traceback")
            if traceback_text:
                print("   运行堆栈：")
                for line in traceback_text.splitlines():
                    print(f"   {line}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查 wjx、software、tencent 目录下 Python 文件的语法、静态导入和启动链问题。"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="启用全量模块导入检查。默认仅执行快检模式。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    target_dirs = iter_target_dirs()
    if not target_dirs:
        print("[ERROR] 未找到可扫描目录（期望存在 wjx/、software/、tencent/ 至少一个）")
        return 2

    start_time = time.perf_counter()
    python_files = iter_python_files()
    compile_targets = iter_compile_targets()
    modules = iter_module_names(python_files)
    quick_mode = not args.full

    print(f"[INFO] 扫描目录: {', '.join(str(path.relative_to(ROOT_DIR)) for path in target_dirs)}")
    print(f"[INFO] 检查模式: {'快检' if quick_mode else '完整'}")
    print(f"[INFO] Python 文件数: {len(python_files)}")
    print(f"[INFO] 编译目标数: {len(compile_targets)}")
    if quick_mode:
        print("[INFO] 模块导入检查数: 已跳过（使用 --full 可启用）")
    else:
        print(f"[INFO] 模块导入检查数: {len(modules)}")

    compile_issues = run_compile_checks(compile_targets)
    ruff_issues, ruff_error = run_ruff_check(target_dirs)
    import_issues = run_module_import_checks(modules) if args.full else []
    window_issue = run_window_smoke_check()

    if ruff_error:
        print(f"[ERROR] {ruff_error}")
        return 2

    total_issues = len(compile_issues) + len(ruff_issues) + len(import_issues) + (1 if window_issue else 0)
    elapsed = time.perf_counter() - start_time

    print(f"[INFO] 编译问题数: {len(compile_issues)}")
    print(f"[INFO] Ruff 诊断数: {len(ruff_issues)}")
    print(f"[INFO] 模块导入失败数: {len(import_issues)}")
    print(f"[INFO] 主窗口冒烟失败数: {1 if window_issue else 0}")
    print(f"[INFO] 总耗时: {elapsed:.2f} 秒")

    if total_issues == 0:
        if quick_mode:
            print("[PASS] 快检通过：语法编译、Ruff 静态检查和主窗口冒烟全部通过。")
            print("[INFO] 如需额外检查包级循环导入等问题，请运行: python test_imports.py --full")
        else:
            print("[PASS] 完整检查通过：语法编译、Ruff 静态检查、模块导入和主窗口冒烟全部通过。")
        return 0

    print(f"[FAIL] 发现 {total_issues} 处问题：")
    print_issues("【语法编译失败】", compile_issues)
    print_issues("【Ruff 静态诊断】", ruff_issues)
    print_issues("【模块导入失败】", import_issues)
    if window_issue:
        print_issues("【主窗口冒烟失败】", [window_issue])

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

