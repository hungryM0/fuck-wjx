"""浏览器环境快速检查子进程入口与父进程调用封装。"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional

from software.network.browser import classify_playwright_startup_error, create_playwright_driver
from software.network.browser.subprocess_utils import build_local_text_subprocess_kwargs


BROWSER_PROBE_ARG = "--sc-browser-probe"
_NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


@dataclass
class BrowserProbeRequest:
    """浏览器快检输入。"""

    headless: bool = True
    browser_preference: List[str] = field(default_factory=list)

    def to_token(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def from_token(cls, token: str) -> "BrowserProbeRequest":
        text = str(token or "").strip()
        if not text:
            raise ValueError("浏览器快检参数为空")
        padding = "=" * (-len(text) % 4)
        decoded = base64.urlsafe_b64decode(f"{text}{padding}".encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
        browsers = payload.get("browser_preference") or []
        if not isinstance(browsers, list):
            browsers = []
        return cls(
            headless=bool(payload.get("headless", True)),
            browser_preference=[str(item).strip() for item in browsers if str(item or "").strip()],
        )


@dataclass
class BrowserProbeResult:
    """浏览器快检输出。"""

    ok: bool
    browser: str = ""
    error_kind: str = ""
    message: str = ""
    elapsed_ms: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "BrowserProbeResult":
        payload = json.loads(str(raw or "").strip())
        return cls(
            ok=bool(payload.get("ok", False)),
            browser=str(payload.get("browser") or "").strip(),
            error_kind=str(payload.get("error_kind") or "").strip(),
            message=str(payload.get("message") or "").strip(),
            elapsed_ms=max(0, int(payload.get("elapsed_ms", 0) or 0)),
        )


def _parse_probe_stdout(stdout: str) -> Optional[BrowserProbeResult]:
    lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return BrowserProbeResult.from_json(line)
        except Exception:
            continue
    return None


def _decode_probe_output(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _kill_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                creationflags=_NO_WINDOW_FLAG,
                **build_local_text_subprocess_kwargs(),
            )
        except Exception:
            logging.info("结束浏览器快检子进程树失败，准备回退到 kill", exc_info=True)
    try:
        process.kill()
    except Exception:
        pass


def _get_dev_entry_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "SurveyController.py"


def _build_probe_command(request: BrowserProbeRequest) -> List[str]:
    token = request.to_token()
    if getattr(sys, "frozen", False):
        return [sys.executable, BROWSER_PROBE_ARG, token]
    return [sys.executable, str(_get_dev_entry_script_path()), BROWSER_PROBE_ARG, token]


def probe_browser_environment(request: BrowserProbeRequest) -> BrowserProbeResult:
    start_time = time.monotonic()
    driver = None
    browser_name = ""
    try:
        driver, browser_name = create_playwright_driver(
            headless=bool(request.headless),
            prefer_browsers=list(request.browser_preference or []),
            persistent_browser=False,
            transient_launch=True,
        )
        return BrowserProbeResult(
            ok=True,
            browser=str(browser_name or "").strip(),
            message="浏览器环境快速检查通过",
            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
        )
    except Exception as exc:
        error_info = classify_playwright_startup_error(exc)
        return BrowserProbeResult(
            ok=False,
            error_kind=error_info.kind,
            message=error_info.message or "浏览器环境快速检查失败",
            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
        )
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                logging.info("浏览器快检关闭临时 driver 失败", exc_info=True)


def run_browser_probe_cli_from_argv(argv: Iterable[str]) -> Optional[int]:
    args = list(argv or [])
    if not args or args[0] != BROWSER_PROBE_ARG:
        return None

    start_time = time.monotonic()
    try:
        request = BrowserProbeRequest.from_token(args[1] if len(args) > 1 else "")
    except Exception as exc:
        result = BrowserProbeResult(
            ok=False,
            error_kind="invalid_request",
            message=f"浏览器快检参数无效：{exc}",
            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
        )
        print(result.to_json(), flush=True)
        return 2

    result = probe_browser_environment(request)
    print(result.to_json(), flush=True)
    return 0 if result.ok else 1


def run_browser_probe_subprocess(
    *,
    headless: bool,
    browser_preference: Optional[Iterable[str]] = None,
    timeout_seconds: float,
    cancel_event: Optional[object] = None,
) -> BrowserProbeResult:
    start_time = time.monotonic()
    request = BrowserProbeRequest(
        headless=bool(headless),
        browser_preference=[str(item).strip() for item in list(browser_preference or []) if str(item or "").strip()],
    )
    command = _build_probe_command(request)

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_NO_WINDOW_FLAG,
        )
    except Exception as exc:
        return BrowserProbeResult(
            ok=False,
            error_kind="spawn_failed",
            message=f"浏览器环境快速检查进程启动失败：{exc}",
            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
        )

    stdout = ""
    stderr = ""
    deadline = time.monotonic() + max(0.1, float(timeout_seconds or 0.0))
    try:
        while True:
            if cancel_event is not None:
                try:
                    is_set = getattr(cancel_event, "is_set", None)
                    if callable(is_set) and bool(is_set()):
                        _kill_process_tree(process)
                        return BrowserProbeResult(
                            ok=False,
                            error_kind="cancelled",
                            message="浏览器环境快速检查已取消",
                            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
                        )
                except Exception:
                    logging.info("检查浏览器快检取消状态失败", exc_info=True)

            if process.poll() is not None:
                raw_stdout, raw_stderr = process.communicate(timeout=1)
                stdout = _decode_probe_output(raw_stdout)
                stderr = _decode_probe_output(raw_stderr)
                break

            if time.monotonic() >= deadline:
                _kill_process_tree(process)
                return BrowserProbeResult(
                    ok=False,
                    error_kind="timeout",
                    message=f"浏览器环境快速检查超过 {max(1, int(timeout_seconds))} 秒仍未完成，已中止",
                    elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
                )
            time.sleep(0.1)
    except Exception as exc:
        _kill_process_tree(process)
        return BrowserProbeResult(
            ok=False,
            error_kind="probe_failed",
            message=f"浏览器环境快速检查执行失败：{exc}",
            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
        )

    result = _parse_probe_stdout(stdout)
    if result is None:
        stderr_text = str(stderr or "").strip()
        detail = stderr_text or "子进程没有返回可解析结果"
        return BrowserProbeResult(
            ok=False,
            error_kind="invalid_response",
            message=f"浏览器环境快速检查返回无效：{detail}",
            elapsed_ms=max(0, int((time.monotonic() - start_time) * 1000)),
        )

    if result.elapsed_ms <= 0:
        result.elapsed_ms = max(0, int((time.monotonic() - start_time) * 1000))
    return result
