"""Velopack 增量更新端到端测试入口。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT_DIR / "software" / "app" / "version.py"
RESULT_WAIT_SECONDS = 240


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 1800) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd or ROOT_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"命令失败: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _set_version_text(version_text: str) -> None:
    content = VERSION_FILE.read_text(encoding="utf-8")
    original = '__VERSION__ = "'
    start = content.find(original)
    if start < 0:
        raise RuntimeError("找不到 __VERSION__")
    end = content.find('"', start + len(original))
    updated = f'{content[:start]}{original}{version_text}{content[end:]}'
    VERSION_FILE.write_text(updated, encoding="utf-8")


def _backup_version_file() -> str:
    return VERSION_FILE.read_text(encoding="utf-8")


def _restore_version_file(content: str) -> None:
    VERSION_FILE.write_text(content, encoding="utf-8")


def _build_release(version_text: str, release_dir: Path, output_dir: Path) -> None:
    _run(
        [
            "powershell",
            "-ExecutionPolicy",
            "ByPass",
            "-File",
            str(ROOT_DIR / "Setup" / "build-release-installer.ps1"),
            "-OutputDir",
            str(output_dir),
            "-ReleaseDir",
            str(release_dir),
            "-Channel",
            "stable",
            "-PackVersion",
            version_text,
            "-SkipSync",
            "-KeepFullVersions",
            "6",
        ],
        timeout=7200,
    )


def _wait_for_file(path: Path, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(2)
    raise TimeoutError(f"等待文件超时: {path}")


def _install_old_version(setup_path: Path, install_dir: Path, log_path: Path) -> None:
    _run(
        [
            str(setup_path),
            "--silent",
            "--log",
            str(log_path),
            "--installto",
            str(install_dir),
        ],
        timeout=900,
    )


def _resolve_installed_app_exe(install_dir: Path) -> Path:
    candidates = [
        install_dir / "SurveyController.exe",
        install_dir / "current" / "SurveyController.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"安装后的程序不存在: {candidates}")


def _launch_update_probe(app_exe: Path, feed_dir: Path, result_path: Path, expected_version: str) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["SURVEYCONTROLLER_VELOPACK_FEED_URL"] = str(feed_dir)
    env["SURVEYCONTROLLER_VELOPACK_CHANNEL"] = "stable"
    env["SURVEYCONTROLLER_UPDATE_TEST_RESULT"] = str(result_path)
    env["SURVEYCONTROLLER_UPDATE_EXPECTED_VERSION"] = expected_version
    env["SURVEYCONTROLLER_UPDATE_TEST_MODE"] = "1"
    return subprocess.Popen(
        [
            str(app_exe),
            "--ci-update-probe",
        ],
        cwd=str(app_exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _read_result(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Velopack E2E update test.")
    parser.add_argument("--old-version", default="9.9.1")
    parser.add_argument("--new-version", default="9.9.2")
    args = parser.parse_args()

    backup = _backup_version_file()
    workspace = Path(tempfile.mkdtemp(prefix="surveycontroller-velopack-e2e-"))
    old_release_dir = workspace / "Releases-old"
    new_release_dir = workspace / "Releases-new"
    old_output_dir = workspace / "dist-old"
    new_output_dir = workspace / "dist-new"
    install_dir = workspace / "InstallRoot"
    result_path = workspace / "probe-result.json"
    setup_log_path = workspace / "setup.log"

    try:
        _set_version_text(args.old_version)
        _build_release(args.old_version, old_release_dir, old_output_dir)

        _set_version_text(args.new_version)
        if new_release_dir.exists():
            shutil.rmtree(new_release_dir)
        shutil.copytree(old_release_dir, new_release_dir)
        _build_release(args.new_version, new_release_dir, new_output_dir)

        setup_path = old_release_dir / f"SurveyController_v{args.old_version}_setup.exe"
        if not setup_path.exists():
            raise FileNotFoundError(f"旧版安装器不存在: {setup_path}")
        _install_old_version(setup_path, install_dir, setup_log_path)

        app_exe = _resolve_installed_app_exe(install_dir)

        process = _launch_update_probe(app_exe, new_release_dir, result_path, args.new_version)
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            raise TimeoutError("旧版探针进程未在 90 秒内结束")

        _wait_for_file(result_path, timeout_seconds=RESULT_WAIT_SECONDS)
        payload = _read_result(result_path)
        if payload.get("status") != "restarted":
            raise RuntimeError(f"更新未完成重启: {json.dumps(payload, ensure_ascii=False)}")
        if str(payload.get("version", "")).strip() != args.new_version:
            raise RuntimeError(f"更新后版本不对: {json.dumps(payload, ensure_ascii=False)}")
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    finally:
        _restore_version_file(backup)


if __name__ == "__main__":
    raise SystemExit(main())
