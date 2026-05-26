"""Velopack CI 端到端更新探针。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize_update_info(update_info: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = (
        "has_update",
        "status",
        "version",
        "latest_version",
        "current_version",
        "package_size",
        "manual_only",
        "manual_release_url",
    )
    return {key: update_info[key] for key in allowed_keys if key in update_info}


def run() -> int:
    result_path_raw = str(os.environ.get("SURVEYCONTROLLER_UPDATE_TEST_RESULT", "") or "").strip()
    if not result_path_raw:
        return 2

    result_path = Path(result_path_raw)
    from software.app.version import __VERSION__
    from software.update.updater import UpdateManager

    expected_version = str(os.environ.get("SURVEYCONTROLLER_UPDATE_EXPECTED_VERSION", "") or "").strip()
    restart_marker = str(os.environ.get("SURVEYCONTROLLER_UPDATE_TEST_RESTARTED", "") or "").strip() == "1"
    start_time = time.time()

    try:
        if restart_marker:
            payload = {
                "status": "restarted",
                "version": str(__VERSION__ or "").strip(),
                "expected_version": expected_version,
                "timestamp": start_time,
                "pid": os.getpid(),
                "argv": sys.argv[1:],
            }
            if expected_version and payload["version"] != expected_version:
                payload["status"] = "unexpected-version"
            _write_result(result_path, payload)
            return 0

        update_info = UpdateManager.check_updates()
        payload = {
            "status": "checked",
            "current_version": str(__VERSION__ or "").strip(),
            "update_info": _summarize_update_info(update_info),
            "timestamp": start_time,
            "pid": os.getpid(),
        }
        if not update_info.get("has_update"):
            payload["status"] = "no-update"
            _write_result(result_path, payload)
            return 0

        velopack_update = update_info.get("_velopack_update")
        if velopack_update is None:
            payload["status"] = "missing-velopack-update"
            _write_result(result_path, payload)
            return 1

        UpdateManager.download_update(velopack_update)
        payload["status"] = "downloaded"
        _write_result(result_path, payload)
        UpdateManager.apply_downloaded_update(velopack_update)
        return 0
    except Exception as exc:
        _write_result(
            result_path,
            {
                "status": "error",
                "current_version": str(__VERSION__ or "").strip(),
                "expected_version": expected_version,
                "timestamp": start_time,
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        return 1
