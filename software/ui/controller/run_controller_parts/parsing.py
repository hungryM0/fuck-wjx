"""RunController 解析与题目默认配置相关逻辑。"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any, List

from software.core.questions.config import (
    QuestionEntry,
    build_default_question_entries,
)
from software.providers.common import is_supported_survey_url
from software.providers.contracts import SurveyDefinition, SurveyQuestionMeta
from software.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)

if TYPE_CHECKING:
    from software.core.config.schema import RuntimeConfig


class RunControllerParsingMixin:
    if TYPE_CHECKING:
        surveyParsed: Any
        surveyParseFailed: Any
        config: RuntimeConfig
        questions_info: List[SurveyQuestionMeta]
        question_entries: List[QuestionEntry]
        survey_title: str
        survey_provider: str
        _async_engine_client: Any

        def _dispatch_to_ui_async(self, callback: Any) -> None: ...

    # -------------------- Parsing --------------------
    def parse_survey(self, url: str):
        """通过异步引擎解析问卷结构。"""
        if not url:
            self.surveyParseFailed.emit("请填写问卷链接")
            return
        normalized_url = str(url or "").strip()
        if not is_supported_survey_url(normalized_url):
            logging.warning("收到不支持的问卷链接：%r", normalized_url)
            self.surveyParseFailed.emit("仅支持问卷星、腾讯问卷与 Credamo 见数链接")
            return

        def _apply_parse_success(definition: SurveyDefinition) -> None:
            info = [q for q in definition.questions if not q.is_description]
            title = definition.title
            provider = definition.provider
            self.questions_info = info
            self.question_entries = build_default_question_entries(
                info,
                survey_url=normalized_url,
                existing_entries=self.question_entries,
            )
            self.config.url = normalized_url
            self.config.survey_provider = provider
            self.config.survey_title = title or ""
            self.config.questions_info = list(info or [])
            self.config.question_entries = list(self.question_entries or [])
            self.survey_title = title or ""
            self.survey_provider = provider
            sync_runtime_state = getattr(self, "set_runtime_ui_state", None)
            if callable(sync_runtime_state):
                sync_runtime_state(survey_provider=provider)
            self.surveyParsed.emit(info, title or "")

        def _apply_parse_failure(message: str) -> None:
            self.surveyParseFailed.emit(str(message or "解析失败，请稍后重试"))

        future = self._async_engine_client.parse_survey(normalized_url)

        def _on_done(done_future: concurrent.futures.Future[SurveyDefinition]) -> None:
            try:
                definition = done_future.result()
                self._dispatch_to_ui_async(
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
                self._dispatch_to_ui_async(lambda msg=friendly: _apply_parse_failure(msg))
            except Exception as exc:
                logging.exception("解析问卷流程失败，url=%r", normalized_url)
                friendly = str(exc) or "解析失败，请稍后重试"
                self._dispatch_to_ui_async(lambda msg=friendly: _apply_parse_failure(msg))

        future.add_done_callback(_on_done)
