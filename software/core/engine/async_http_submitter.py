"""异步运行槽位的 HTTP provider 调用。"""

from __future__ import annotations

from typing import Optional

from software.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    normalize_survey_provider,
)
from software.providers.http_logic import get_http_logic_fallback_reason
from software.providers.registry import fill_survey_http

HTTP_RUNTIME_PROVIDERS = {
    SURVEY_PROVIDER_WJX,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_CREDAMO,
}


class AsyncHttpSubmitter:
    """封装纯 HTTP 提交链路的 provider 调用和支持性判断。"""

    def __init__(self, *, config: ExecutionConfig, state: ExecutionState, slot_label: str) -> None:
        self.config = config
        self.state = state
        self.slot_label = slot_label

    def uses_http_runtime(self) -> bool:
        provider = normalize_survey_provider(self.config.survey_provider)
        if not bool(str(self.config.url or "").strip()) or provider not in HTTP_RUNTIME_PROVIDERS:
            return False
        questions = list((self.config.questions_metadata or {}).values())
        return not bool(get_http_logic_fallback_reason(questions))

    def resolve_block_reason(self) -> str:
        provider = normalize_survey_provider(self.config.survey_provider)
        if provider not in HTTP_RUNTIME_PROVIDERS:
            return ""
        url = str(self.config.url or "").strip()
        if not url:
            return "问卷链接为空，无法进入纯 HTTP 提交"
        questions = list((self.config.questions_metadata or {}).values())
        reason = str(get_http_logic_fallback_reason(questions) or "").strip()
        if reason:
            return reason
        return ""

    async def submit(
        self,
        *,
        stop_signal: StopSignalLike,
        proxy_address: Optional[str],
        user_agent: Optional[str],
    ) -> bool:
        return bool(
            await fill_survey_http(
                self.config,
                self.state,
                stop_signal=stop_signal,
                thread_name=self.slot_label,
                provider=self.config.survey_provider,
                proxy_address=proxy_address,
                user_agent=user_agent,
            )
        )


__all__ = ["AsyncHttpSubmitter", "HTTP_RUNTIME_PROVIDERS"]
