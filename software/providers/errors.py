"""Provider 通用业务异常。"""

from __future__ import annotations


class SurveyProviderStatusError(RuntimeError):
    """问卷状态导致解析或运行不可继续。"""


class SurveyPausedError(SurveyProviderStatusError):
    """问卷已暂停。"""


class SurveyStoppedError(SurveyProviderStatusError):
    """问卷已停止。"""


class SurveyEnterpriseUnavailableError(SurveyProviderStatusError):
    """问卷发布者企业版本不可用。"""


class SurveyNotOpenError(SurveyProviderStatusError):
    """问卷尚未开放。"""


class SubmissionVerificationRequiredError(RuntimeError):
    """提交被平台智能验证拦截。"""


class SurveyProviderUnavailableAtRuntimeError(SurveyProviderStatusError):
    """运行时发现问卷状态不可继续。"""


__all__ = [
    "SubmissionVerificationRequiredError",
    "SurveyEnterpriseUnavailableError",
    "SurveyNotOpenError",
    "SurveyPausedError",
    "SurveyProviderStatusError",
    "SurveyProviderUnavailableAtRuntimeError",
    "SurveyStoppedError",
]
