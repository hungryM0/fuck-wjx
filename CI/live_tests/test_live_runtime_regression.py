"""真实运行链路回归测试。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
LIVE_URL_ENV = "SURVEY_CONTROLLER_LIVE_TEST_URL"
INNER_TIMEOUT_SECONDS = "240"
OUTER_TIMEOUT_SECONDS = 300
TRANSIENT_EXTERNAL_FAILURE_PATTERNS = (
    re.compile(r"HTTP 页面未返回可解析题目"),
)


@dataclass(frozen=True)
class LiveSurveyCase:
    name: str
    url: str


DEFAULT_LIVE_SURVEY_CASES = (
    LiveSurveyCase("wjx", "https://v.wjx.cn/vm/ei3sVrE.aspx"),
    LiveSurveyCase("credamo", "https://www.credamo.com/s/A73QR3ano"),
    LiveSurveyCase("tencent", "https://wj.qq.com/s2/26070328/fa89/"),
)


def _resolve_live_survey_cases() -> list[LiveSurveyCase]:
    configured_url = str(os.environ.get(LIVE_URL_ENV, "") or "").strip()
    if not configured_url:
        return list(DEFAULT_LIVE_SURVEY_CASES)

    return [LiveSurveyCase("configured", configured_url)]


def _build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    root_path = str(ROOT_DIR)
    env["PYTHONPATH"] = root_path if not current_python_path else os.pathsep.join([root_path, current_python_path])
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    return env


def _format_output(stdout: str, stderr: str) -> str:
    stdout_text = (stdout or "").strip()
    stderr_text = (stderr or "").strip()
    chunks = [chunk for chunk in (stdout_text, stderr_text) if chunk]
    return "\n".join(chunks)


def _is_transient_external_failure(output: str) -> bool:
    return any(pattern.search(output or "") for pattern in TRANSIENT_EXTERNAL_FAILURE_PATTERNS)


@pytest.mark.parametrize("survey_case", _resolve_live_survey_cases(), ids=lambda case: case.name)
def test_live_runtime_regression(survey_case: LiveSurveyCase) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "CI.live_tests.run_async_engine_once",
            "--url",
            survey_case.url,
            "--timeout",
            INNER_TIMEOUT_SECONDS,
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_build_child_env(),
        timeout=OUTER_TIMEOUT_SECONDS,
    )
    output = _format_output(result.stdout, result.stderr)
    if result.returncode != 0 and _is_transient_external_failure(output):
        pytest.skip(
            f"Live survey returned an unparseable external page for {survey_case.name}.\n"
            f"Output:\n{output}"
        )

    assert result.returncode == 0, (
        f"Live runtime regression failed for {survey_case.name}.\n"
        f"Exit code: {result.returncode}\n"
        f"Output:\n{output}"
    )
    assert "cur_num=1" in output, (
        f"Live runtime regression did not report a successful submission for {survey_case.name}.\n"
        f"Output:\n{output}"
    )
