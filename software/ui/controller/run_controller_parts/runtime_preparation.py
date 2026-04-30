"""RunController 运行前准备逻辑。"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, cast

from software.core.psychometrics.psychometric import normalize_target_alpha
from software.core.questions.config import configure_probabilities, validate_question_config
from software.core.reverse_fill import ReverseFillSpec
from software.core.reverse_fill.validation import build_enabled_reverse_fill_spec
from software.core.task import ExecutionConfig
from software.io.config import RuntimeConfig, clone_questions_info
from software.network.proxy import set_proxy_occupy_minute_by_answer_duration
from software.providers.common import SURVEY_PROVIDER_WJX, detect_survey_provider, normalize_survey_provider
from software.providers.contracts import SurveyQuestionMeta


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

    def __init__(self, user_message: str, *, log_message: str = "", detailed: bool = False) -> None:
        super().__init__(str(user_message or "运行准备失败"))
        self.user_message = str(user_message or "运行准备失败")
        self.log_message = str(log_message or self.user_message)
        self.detailed = bool(detailed)


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
    if bool(getattr(config, "timed_mode_enabled", False)):
        return (0, 0)
    return (int(raw[0]), int(raw[1]))


def _build_questions_metadata(questions_info: List[SurveyQuestionMeta]) -> dict[int, SurveyQuestionMeta]:
    metadata: dict[int, SurveyQuestionMeta] = {}
    for item in questions_info:
        try:
            question_num = int(item.num or 0)
        except Exception:
            question_num = 0
        if question_num > 0:
            metadata[question_num] = item
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

    execution_config = ExecutionConfig(
        url=str(getattr(config, "url", "") or ""),
        survey_title=survey_title,
        survey_provider=survey_provider,
        target_num=max(1, int(getattr(config, "target", 1) or 1)),
        num_threads=max(1, int(getattr(config, "threads", 1) or 1)),
        headless_mode=bool(getattr(config, "headless_mode", False)),
        browser_preference=copy.deepcopy(list(getattr(config, "browser_preference", []) or [])),
        fail_threshold=5,
        submit_interval_range_seconds=(
            int(getattr(config, "submit_interval", (0, 0))[0]),
            int(getattr(config, "submit_interval", (0, 0))[1]),
        ),
        answer_duration_range_seconds=(
            int(getattr(config, "answer_duration", (0, 0))[0]),
            int(getattr(config, "answer_duration", (0, 0))[1]),
        ),
        timed_mode_enabled=bool(getattr(config, "timed_mode_enabled", False)),
        timed_mode_refresh_interval=float(getattr(config, "timed_mode_interval", 3.0) or 3.0),
        random_proxy_ip_enabled=bool(getattr(config, "random_ip_enabled", False)),
        proxy_ip_pool=[],
        random_user_agent_enabled=bool(getattr(config, "random_ua_enabled", False)),
        user_agent_ratios=copy.deepcopy(
            dict(getattr(config, "random_ua_ratios", {"wechat": 33, "mobile": 33, "pc": 34}) or {})
        ),
        pause_on_aliyun_captcha=bool(getattr(config, "pause_on_aliyun_captcha", True)),
        stop_on_fail_enabled=bool(getattr(config, "fail_stop_enabled", True)),
        answer_rules=copy.deepcopy(list(getattr(config, "answer_rules", []) or [])),
        reverse_fill_spec=copy.deepcopy(reverse_fill_spec),
        psycho_target_alpha=psycho_target_alpha,
    )
    execution_config.questions_metadata = _build_questions_metadata(questions_info)
    return execution_config


def prepare_execution_artifacts(
    config: RuntimeConfig,
    *,
    fallback_survey_title: str = "",
) -> PreparedExecutionArtifacts:
    question_entries = list(getattr(config, "question_entries", []) or [])
    if not question_entries:
        raise RuntimePreparationError('未配置任何题目，无法开始执行（请先在"题目配置"页添加/配置题目）', log_message="未配置任何题目，无法启动")

    survey_provider = _resolve_survey_provider(config)
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
        raise RuntimePreparationError(str(exc), log_message=f"反填配置验证失败：{exc}", detailed=True) from exc

    try:
        set_proxy_occupy_minute_by_answer_duration(_resolve_proxy_answer_duration(config))
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
