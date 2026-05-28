"""RunController 运行前准备逻辑。"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, cast

from software.app.config import HTTP_MAX_THREADS
from software.core.config.answer_datetime_window import (
    answer_datetime_window_to_epoch_ms,
    normalize_answer_datetime_window,
    parse_answer_datetime_string,
)
from software.core.psychometrics.psychometric import normalize_target_alpha
from software.core.questions.config import (
    configure_probabilities,
    validate_question_config,
)
from software.core.reverse_fill import ReverseFillSpec
from software.core.reverse_fill.validation import (
    build_enabled_reverse_fill_spec,
)
from software.core.task import ExecutionConfig
from software.core.config.schema import RuntimeConfig
from software.core.config.codec import clone_questions_info
from software.network.proxy import set_proxy_occupy_minute_by_answer_duration
from software.providers.common import (
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    make_provider_question_key,
    normalize_survey_provider,
    supports_answer_datetime_window,
)
from software.providers.contracts import SurveyQuestionMeta
from software.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyStoppedError,
)
from wjx.provider.parser import (
    ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE,
    STOPPED_SURVEY_ERROR_MESSAGE,
    is_enterprise_unavailable_survey_page,
    is_stopped_survey_page,
)


@dataclass(frozen=True)
class PreparedExecutionArtifacts:
    """运行前准备完成后产出的只读启动资料。"""

    execution_config_template: ExecutionConfig
    survey_provider: str
    question_entries: List[Any]
    questions_info: List[SurveyQuestionMeta]
    reverse_fill_spec: Optional[ReverseFillSpec]


class RuntimePreparationError(Exception):
    """启动前准备失败，携带给 UI 的提示文案。"""

    def __init__(
        self,
        user_message: str,
        *,
        log_message: str = "",
        detailed: bool = False,
    ) -> None:
        super().__init__(str(user_message or "运行准备失败"))
        self.user_message = str(user_message or "运行准备失败")
        self.log_message = str(log_message or self.user_message)
        self.detailed = bool(detailed)


def _resolve_thread_limit(config: RuntimeConfig) -> int:
    del config
    return HTTP_MAX_THREADS


def _resolve_survey_provider(config: RuntimeConfig) -> str:
    return normalize_survey_provider(
        getattr(config, "survey_provider", None),
        default=detect_survey_provider(getattr(config, "url", "")) or SURVEY_PROVIDER_WJX,
    )


def _resolve_survey_title(config: RuntimeConfig, fallback_title: str) -> str:
    config_title = str(getattr(config, "survey_title", "") or "")
    return config_title or str(fallback_title or "")


def _resolve_proxy_answer_duration(config: RuntimeConfig) -> Tuple[int, int]:
    raw = getattr(config, "answer_duration", None) or (0, 0)
    return (int(raw[0]), int(raw[1]))


def _resolve_answer_datetime_window(config: RuntimeConfig) -> tuple[str, str]:
    return normalize_answer_datetime_window(getattr(config, "answer_datetime_window", ("", "")))


def _validate_answer_datetime_window(config: RuntimeConfig, survey_provider: str) -> None:
    if not supports_answer_datetime_window(survey_provider):
        return
    start_text, end_text = _resolve_answer_datetime_window(config)
    if not start_text and not end_text:
        return
    if not start_text or not end_text:
        raise RuntimePreparationError("见数作答时间窗未配完整，请先设置开始和结束日期时间")
    start_dt = parse_answer_datetime_string(start_text)
    end_dt = parse_answer_datetime_string(end_text)
    if start_dt is None or end_dt is None:
        raise RuntimePreparationError("见数作答时间窗格式无效，请重新选择日期时间")
    if end_dt <= start_dt:
        raise RuntimePreparationError("见数结束日期时间必须晚于开始日期时间")
    max_duration_seconds = max(0, int((getattr(config, "answer_duration", (0, 0))[1])))
    window_seconds = int((end_dt - start_dt).total_seconds())
    if window_seconds < max_duration_seconds:
        raise RuntimePreparationError("见数作答时间窗太窄，容不下当前最长作答时长")


def _verify_wjx_survey_is_answerable(config: RuntimeConfig, survey_provider: str) -> None:
    if survey_provider != SURVEY_PROVIDER_WJX:
        return
    url = str(getattr(config, "url", "") or "").strip()
    if not url:
        return
    try:
        import software.network.http as http_client
        from software.app.config import DEFAULT_HTTP_HEADERS

        response = http_client.get(url, timeout=8, headers=DEFAULT_HTTP_HEADERS, proxies={})
        response.raise_for_status()
    except Exception:
        logging.info("启动前问卷星状态复查失败，已放行到运行时处理", exc_info=True)
        return
    html = str(getattr(response, "text", "") or "")
    if is_stopped_survey_page(html):
        raise SurveyStoppedError(STOPPED_SURVEY_ERROR_MESSAGE)
    if is_enterprise_unavailable_survey_page(html):
        raise SurveyEnterpriseUnavailableError(ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE)


def _build_questions_metadata(
    questions_info: List[SurveyQuestionMeta],
) -> dict[int, SurveyQuestionMeta]:
    metadata: dict[int, SurveyQuestionMeta] = {}
    for item in questions_info:
        try:
            question_num = int(item.num or 0)
        except Exception:
            question_num = 0
        if question_num > 0:
            metadata[question_num] = item
    return metadata


def _build_provider_question_metadata(
    questions_info: List[SurveyQuestionMeta],
) -> dict[str, SurveyQuestionMeta]:
    metadata: dict[str, SurveyQuestionMeta] = {}
    for item in questions_info:
        provider_key = make_provider_question_key(
            getattr(item, "provider", None),
            getattr(item, "provider_page_id", None),
            getattr(item, "provider_question_id", None),
        )
        if provider_key and provider_key not in metadata:
            metadata[provider_key] = item
    return metadata


def _build_execution_config_template(
    config: RuntimeConfig,
    *,
    survey_title: str,
    survey_provider: str,
    reverse_fill_spec: Optional[ReverseFillSpec],
    questions_info: List[SurveyQuestionMeta],
) -> ExecutionConfig:
    try:
        psycho_target_alpha = normalize_target_alpha(getattr(config, "psycho_target_alpha", None))
    except Exception:
        psycho_target_alpha = normalize_target_alpha(None)

    thread_limit = _resolve_thread_limit(config)
    requested_target_num = max(1, int(getattr(config, "target", 1) or 1))
    requested_num_threads = max(1, int(getattr(config, "threads", 1) or 1))
    if reverse_fill_spec is not None:
        requested_target_num = max(1, int(getattr(reverse_fill_spec, "target_num", 0) or 1))
        requested_num_threads = max(
            1,
            int(
                getattr(
                    config,
                    "reverse_fill_threads",
                    getattr(config, "threads", 1),
                )
                or 1
            ),
        )
        requested_num_threads = min(requested_num_threads, requested_target_num)

    execution_config = ExecutionConfig(
        url=str(getattr(config, "url", "") or ""),
        survey_title=survey_title,
        survey_provider=survey_provider,
        target_num=requested_target_num,
        num_threads=max(1, min(thread_limit, requested_num_threads)),
        fail_threshold=5,
        submit_interval_range_seconds=(
            int(getattr(config, "submit_interval", (0, 0))[0]),
            int(getattr(config, "submit_interval", (0, 0))[1]),
        ),
        answer_duration_range_seconds=(
            int(getattr(config, "answer_duration", (0, 0))[0]),
            int(getattr(config, "answer_duration", (0, 0))[1]),
        ),
        answer_datetime_window_ms=answer_datetime_window_to_epoch_ms(
            getattr(config, "answer_datetime_window", ("", ""))
        ),
        random_proxy_ip_enabled=bool(getattr(config, "random_ip_enabled", False)),
        proxy_source=str(getattr(config, "proxy_source", "default") or "default").strip().lower(),
        proxy_ip_pool=[],
        random_user_agent_enabled=bool(getattr(config, "random_ua_enabled", False)),
        user_agent_ratios=copy.deepcopy(
            dict(
                getattr(
                    config,
                    "random_ua_ratios",
                    {"wechat": 33, "mobile": 33, "pc": 34},
                )
                or {}
            )
        ),
        pause_on_aliyun_captcha=bool(getattr(config, "pause_on_aliyun_captcha", True)),
        stop_on_fail_enabled=bool(getattr(config, "fail_stop_enabled", True)),
        answer_rules=copy.deepcopy(list(getattr(config, "answer_rules", []) or [])),
        reverse_fill_spec=copy.deepcopy(reverse_fill_spec),
        psycho_target_alpha=psycho_target_alpha,
    )
    execution_config.questions_metadata = _build_questions_metadata(questions_info)
    execution_config.provider_question_metadata_map = _build_provider_question_metadata(questions_info)
    return execution_config


def prepare_execution_artifacts(
    config: RuntimeConfig,
    *,
    fallback_survey_title: str = "",
) -> PreparedExecutionArtifacts:
    question_entries = list(getattr(config, "question_entries", []) or [])
    if not question_entries:
        raise RuntimePreparationError(
            '未配置任何题目，无法开始执行（请先在"题目配置"页添加/配置题目）',
            log_message="未配置任何题目，无法启动",
        )

    survey_provider = _resolve_survey_provider(config)
    _validate_answer_datetime_window(config, survey_provider)
    try:
        _verify_wjx_survey_is_answerable(config, survey_provider)
    except (SurveyStoppedError, SurveyEnterpriseUnavailableError) as exc:
        raise RuntimePreparationError(
            str(exc),
            log_message=f"启动前问卷状态检查失败：{exc}",
        ) from exc

    questions_info = clone_questions_info(
        getattr(config, "questions_info", []) or [],
        default_provider=survey_provider,
    )
    questions_info_inputs = cast(List[SurveyQuestionMeta | dict[str, Any]], list(questions_info))

    validation_error = validate_question_config(question_entries, questions_info_inputs)
    if validation_error:
        raise RuntimePreparationError(
            f"题目配置存在冲突，无法启动：\n\n{validation_error}",
            log_message=f"题目配置验证失败：{validation_error}",
        )

    try:
        reverse_fill_spec = build_enabled_reverse_fill_spec(
            config,
            questions_info_inputs,
            question_entries,
        )
    except Exception as exc:
        raise RuntimePreparationError(
            str(exc), log_message=f"反填配置验证失败：{exc}", detailed=True
        ) from exc

    try:
        set_proxy_occupy_minute_by_answer_duration(
            _resolve_proxy_answer_duration(config),
            survey_provider=survey_provider,
        )
    except Exception:
        logging.debug("同步随机IP占用时长失败", exc_info=True)

    execution_config = _build_execution_config_template(
        config,
        survey_title=_resolve_survey_title(config, fallback_survey_title),
        survey_provider=survey_provider,
        reverse_fill_spec=reverse_fill_spec,
        questions_info=questions_info,
    )

    try:
        configure_probabilities(
            question_entries,
            ctx=execution_config,
            reliability_mode_enabled=bool(getattr(config, "reliability_mode_enabled", True)),
        )
    except Exception as exc:
        raise RuntimePreparationError(str(exc), log_message=f"配置题目失败：{exc}") from exc

    return PreparedExecutionArtifacts(
        execution_config_template=execution_config,
        survey_provider=survey_provider,
        question_entries=list(question_entries),
        questions_info=questions_info,
        reverse_fill_spec=reverse_fill_spec,
    )
