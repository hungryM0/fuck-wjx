#!/usr/bin/env python
"""Run one real survey submission through AsyncRuntimeEngine."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from software.core.config.schema import RuntimeConfig  # noqa: E402
from software.core.engine.async_engine import AsyncEngineClient  # noqa: E402
from software.core.questions.config import build_default_question_entries  # noqa: E402
from software.core.task import ExecutionState  # noqa: E402
from software.providers.registry import parse_survey  # noqa: E402
from software.ui.controller.run_controller_parts.runtime_preparation import prepare_execution_artifacts  # noqa: E402


def _build_live_test_config(url: str) -> RuntimeConfig:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        raise ValueError("问卷链接为空")

    definition = asyncio.run(parse_survey(normalized_url))
    questions_info = [question for question in definition.questions if not question.is_description]
    question_entries = build_default_question_entries(
        questions_info,
        survey_url=normalized_url,
    )

    config = RuntimeConfig(
        url=normalized_url,
        survey_title=definition.title or "",
        survey_provider=definition.provider,
        target=1,
        threads=1,
        submit_interval=(0, 0),
        answer_duration=(0, 0),
        random_ip_enabled=False,
        random_ua_enabled=False,
        fail_stop_enabled=True,
        reliability_mode_enabled=True,
        reverse_fill_enabled=False,
    )
    config.questions_info = list(questions_info)
    config.question_entries = list(question_entries)
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = _build_live_test_config(args.url)

    prepared = prepare_execution_artifacts(config, fallback_survey_title=config.survey_title)
    execution_config = prepared.execution_config_template
    execution_config.target_num = 1
    execution_config.num_threads = 1
    execution_config.submit_interval_range_seconds = (0, 0)
    execution_config.answer_duration_range_seconds = (0, 0)
    execution_config.random_proxy_ip_enabled = False
    execution_config.random_user_agent_enabled = False
    state = ExecutionState(config=execution_config)
    state.initialize_reverse_fill_runtime()

    client = AsyncEngineClient()
    try:
        future = client.start_run(execution_config, state, runtime_bridge=None)
        future.result(timeout=max(1.0, float(args.timeout or 1.0)))
    finally:
        client.shutdown(timeout=15.0)

    print(
        f"provider={execution_config.survey_provider} cur_num={state.cur_num} "
        f"cur_fail={state.cur_fail} terminal={state.get_terminal_stop_snapshot()}"
    )
    return 0 if int(state.cur_num or 0) >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
