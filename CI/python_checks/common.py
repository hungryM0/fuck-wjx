#!/usr/bin/env python
"""Python CI 检查的共享能力。"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[2]
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
UNIT_TEST_TIMEOUT_SECONDS = int(os.environ.get("SURVEY_CONTROLLER_UNIT_TEST_TIMEOUT_SECONDS", "120"))
PYRIGHT_TIMEOUT_SECONDS = int(os.environ.get("SURVEY_CONTROLLER_PYRIGHT_TIMEOUT_SECONDS", "90"))
UNICODE_SPACE_TRANSLATION = str.maketrans({
    "\u00a0": " ",
    "\u2000": " ",
    "\u2001": " ",
    "\u2002": " ",
    "\u2003": " ",
    "\u2004": " ",
    "\u2005": " ",
    "\u2006": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",
    "\u200a": " ",
    "\u202f": " ",
    "\u205f": " ",
    "\u3000": " ",
})

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


def configure_console_encoding() -> None:
    """在 Windows CI 的非 UTF-8 控制台中强制使用 UTF-8 输出，避免中文日志炸掉。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


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


def ensure_target_dirs() -> list[Path]:
    target_dirs = iter_target_dirs()
    if not target_dirs:
        print("[ERROR] No scan targets found. Expected at least one of wjx/, software/, or tencent/.")
        raise SystemExit(2)
    return target_dirs


def make_child_env() -> dict[str, str]:
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    root_path = str(ROOT_DIR)
    env["PYTHONPATH"] = root_path if not current_python_path else os.pathsep.join([root_path, current_python_path])
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("WJX_IMPORT_CHECK", "1")

    home_dir = (
        env.get("HOME")
        or env.get("USERPROFILE")
        or (
            f"{env.get('HOMEDRIVE', '')}{env.get('HOMEPATH', '')}"
            if env.get("HOMEDRIVE") and env.get("HOMEPATH")
            else ""
        )
    )
    if not home_dir:
        username = getpass.getuser().strip()
        if username:
            guessed_home = Path(env.get("SystemDrive", "C:")) / "Users" / username
            if guessed_home.exists():
                home_dir = str(guessed_home)
    if home_dir:
        env.setdefault("HOME", home_dir)
        env.setdefault("USERPROFILE", home_dir)

    env.setdefault(
        "PYRIGHT_PYTHON_CACHE_DIR",
        str(Path(tempfile.gettempdir()) / "SurveyController-pyright-cache"),
    )
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


def normalize_diagnostic_message(message: str) -> str:
    """Normalize uncommon whitespace in diagnostics for stable console output."""
    normalized = message.translate(UNICODE_SPACE_TRANSLATION)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def run_compile_checks(files: Iterable[Path]) -> list[dict]:
    issues: list[dict] = []
    for path in files:
        try:
            source = path.read_bytes()
            compile(source, str(path), "exec")
        except (SyntaxError, ValueError, TypeError, OSError) as exc:
            issues.append(
                {
                    "phase": "compile",
                    "path": format_path(path),
                    "message": str(exc).strip(),
                }
            )
    return issues


def run_ruff_check(target_dirs: Iterable[Path]) -> tuple[list[dict], str | None]:
    target_args = [str(path) for path in target_dirs]
    if not target_args:
        return [], "No target directories found for Ruff checks."

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
        message = result.stderr.strip() or result.stdout.strip() or "Ruff execution failed."
        return [], message

    raw = result.stdout.strip()
    try:
        diagnostics: list[dict] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return [], f"Failed to parse Ruff output: {raw}"

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


def run_pyright_check(target_dirs: Iterable[Path]) -> tuple[list[dict], str | None]:
    """Run Pyright diagnostics."""
    target_args = [str(path) for path in target_dirs]
    env = make_child_env()
    for entry_file in ENTRY_FILES:
        if entry_file.exists():
            target_args.append(str(entry_file))

    if not target_args:
        return [], "No target paths found for Pyright diagnostics."

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pyright",
                "--outputjson",
                *target_args,
            ],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=PYRIGHT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [], f"Pyright timed out (>{PYRIGHT_TIMEOUT_SECONDS}s)."

    stderr_text = (result.stderr or "").strip()
    if "No module named pyright" in stderr_text:
        return [], "Pyright is not installed, so Pyright diagnostics cannot run."

    raw = (result.stdout or "").strip()
    if not raw:
        if result.returncode == 0:
            return [], None
        message = stderr_text or "Pyright failed without producing parseable output."
        return [], message

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [], f"Failed to parse Pyright output: {raw}"

    diagnostics = payload.get("generalDiagnostics", [])
    issues: list[dict] = []
    for item in diagnostics:
        range_start = item.get("range", {}).get("start", {})
        file_name = item.get("file", "")
        severity = item.get("severity", "error")
        rule = item.get("rule") or "pyright"
        issues.append(
            {
                "phase": "pyright",
                "path": format_path(file_name) if file_name else Path("<unknown>"),
                "row": int(range_start.get("line", 0)) + 1,
                "column": int(range_start.get("character", 0)) + 1,
                "severity": severity,
                "code": rule,
                "message": normalize_diagnostic_message(item.get("message", "")),
            }
        )

    # Pyright exit codes: 0=no issues, 1=diagnostics found, 2=execution error
    if result.returncode == 2 and not issues:
        summary = payload.get("summary", {})
        message = summary.get("errorMessage") or stderr_text or "Pyright execution error."
        return [], str(message)

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
            signature = ("TimeoutError", f"Import timed out (>{IMPORT_TIMEOUT_SECONDS}s).", "")
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
        message = payload.get("message") or fallback_message or "Module import failed."
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
            "message": f"Main window creation timed out (>{WINDOW_SMOKE_TIMEOUT_SECONDS}s).",
        }

    payload = extract_child_payload(result.stdout, result.stderr) or {}
    if payload.get("kind") == "window_smoke" and payload.get("ok") is True:
        return None

    fallback_message = summarize_child_output(result.stdout, result.stderr)
    return {
        "phase": "window",
        "message": payload.get("message") or fallback_message or "Main window creation failed.",
        "error_type": payload.get("error_type", "RuntimeError"),
        "traceback": payload.get("traceback", "").strip(),
    }


def run_unit_tests() -> dict | None:
    env = make_child_env()
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "CI/unit_tests",
                "-t",
                ".",
                "-v",
            ],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=UNIT_TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "phase": "unit",
            "message": f"Unit tests timed out (>{UNIT_TEST_TIMEOUT_SECONDS}s).",
        }

    if result.returncode == 0:
        return None

    summary = summarize_child_output(result.stdout, result.stderr) or "Unit tests failed."
    return {
        "phase": "unit",
        "message": summary,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
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
                print("   Import traceback:")
                for line in traceback_text.splitlines():
                    print(f"   {line}")
            continue

        if phase == "window":
            error_type = item.get("error_type", "RuntimeError")
            print(f"{index}. Main window creation  [{error_type}]")
            print(f"   {item['message']}")
            traceback_text = item.get("traceback")
            if traceback_text:
                print("   Runtime traceback:")
                for line in traceback_text.splitlines():
                    print(f"   {line}")
            continue

        if phase == "unit":
            print(f"{index}. Unit tests")
            print(f"   {item['message']}")
            stdout_text = item.get("stdout")
            stderr_text = item.get("stderr")
            if stdout_text:
                print("   unittest stdout:")
                for line in stdout_text.splitlines()[-12:]:
                    print(f"   {line}")
            if stderr_text:
                print("   unittest stderr:")
                for line in stderr_text.splitlines()[-12:]:
                    print(f"   {line}")
            continue

        if phase == "pyright":
            print(
                f"{index}. {item['path']}:{item['row']}:{item['column']}  "
                f"[{item.get('severity', 'error')}/{item.get('code', 'pyright')}]"
            )
            message_lines = str(item.get("message", "")).splitlines() or [""]
            print(f"   {message_lines[0]}")
            for line in message_lines[1:]:
                print(f"   {line}")


def print_scan_targets(target_dirs: Iterable[Path]) -> None:
    print(f"[INFO] Scan targets: {', '.join(str(path.relative_to(ROOT_DIR)) for path in target_dirs)}")
