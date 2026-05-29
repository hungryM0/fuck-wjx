from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable, Optional

from software.core.config.schema import RuntimeConfig
from software.core.questions.config import build_default_question_entries
from software.providers.common import is_supported_survey_url
from software.providers.contracts import SurveyDefinition
from software.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)
from software.ui.controller.run_state_store import RunStateStore


class SurveyParseService:
    def __init__(
        self,
        *,
        async_engine_client: Any,
        state_store: RunStateStore,
        emit_event: Callable[[dict[str, Any]], Any],
        dispatch_async: Callable[[Callable[[], Any]], None],
    ) -> None:
        self._async_engine_client = async_engine_client
        self._state_store = state_store
        self._emit_event = emit_event
        self._dispatch_async = dispatch_async

    def parse_survey(self, url: str) -> None:
        normalized_url = str(url or "").strip()
        if not normalized_url:
            self._state_store.apply_survey_patch(
                {
                    "phase": "error",
                    "url": "",
                    "parse_error": "请填写问卷链接",
                }
            )
            return
        if not is_supported_survey_url(normalized_url):
            logging.warning("收到不支持的问卷链接：%r", normalized_url)
            self._state_store.apply_survey_patch(
                {
                    "phase": "error",
                    "url": normalized_url,
                    "parse_error": "仅支持问卷星、腾讯问卷与 Credamo 见数链接",
                }
            )
            return

        current_entries = self._state_store.get_survey_snapshot().get("question_entries") or []
        self._state_store.apply_survey_patch(
            {
                "phase": "parsing",
                "url": normalized_url,
                "parse_error": "",
            }
        )
        future = self._async_engine_client.parse_survey(normalized_url)

        def _apply_parse_success(definition: SurveyDefinition) -> None:
            info = [q for q in definition.questions if not q.is_description]
            title = definition.title
            provider = definition.provider
            entries = build_default_question_entries(
                info,
                survey_url=normalized_url,
                existing_entries=current_entries,
            )
            self._state_store.apply_survey_patch(
                {
                    "phase": "ready",
                    "url": normalized_url,
                    "survey_provider": provider,
                    "survey_title": title or "",
                    "questions_info": list(info or []),
                    "question_entries": list(entries or []),
                    "parse_error": "",
                }
            )
            self._state_store.update_runtime_settings(
                emit=True,
                survey_provider=provider,
            )

        def _apply_parse_failure(message: str) -> None:
            self._state_store.apply_survey_patch(
                {
                    "phase": "error",
                    "url": normalized_url,
                    "parse_error": str(message or "解析失败，请稍后重试"),
                }
            )

        def _on_done(done_future: concurrent.futures.Future[SurveyDefinition]) -> None:
            try:
                definition = done_future.result()
                self._dispatch_async(
                    lambda parsed_definition=definition: _apply_parse_success(parsed_definition)
                )
            except (
                SurveyPausedError,
                SurveyStoppedError,
                SurveyEnterpriseUnavailableError,
                SurveyNotOpenError,
            ) as exc:
                friendly = str(exc) or "解析失败，请稍后重试"
                logging.info("解析问卷被业务状态拦截，url=%r：%s", normalized_url, friendly)
                self._dispatch_async(lambda msg=friendly: _apply_parse_failure(msg))
            except Exception as exc:
                logging.exception("解析问卷流程失败，url=%r", normalized_url)
                friendly = str(exc) or "解析失败，请稍后重试"
                self._dispatch_async(lambda msg=friendly: _apply_parse_failure(msg))

        future.add_done_callback(_on_done)

    def hydrate_from_config(self, cfg: RuntimeConfig) -> None:
        self._state_store.hydrate_from_config(cfg)

    def replace_question_entries(self, entries: Any, *, questions_info: Any = None) -> None:
        self._state_store.replace_question_entries(entries, questions_info=questions_info)


__all__ = ["SurveyParseService"]
