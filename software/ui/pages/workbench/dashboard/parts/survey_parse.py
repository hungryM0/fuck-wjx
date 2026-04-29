"""DashboardPage 问卷解析流程。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.providers.contracts import ensure_survey_question_metas

from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    detect_survey_provider,
    is_supported_survey_url,
    is_wjx_survey_url,
)

_QQ_LOGIN_REQUIRED_MESSAGE = "作答该问卷需要登录，请自行在后台开放访问权限"


class DashboardSurveyParseMixin:
    if TYPE_CHECKING:
        controller: Any
        url_edit: Any
        _open_wizard_after_parse: bool
        _progress_infobar: Any

        def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False) -> Any: ...

    def _on_parse_clicked(self):
        url = self.url_edit.text().strip()
        if not url:
            log_action(
                "UI",
                "parse_survey",
                "parse_btn",
                "dashboard",
                result="blocked",
                level=logging.WARNING,
                payload={"reason": "empty_url"},
            )
            self._toast("请粘贴问卷链接", "warning")
            return
        # 第一层检测：是否为受支持的问卷平台
        if not is_supported_survey_url(url):
            log_action(
                "UI",
                "parse_survey",
                "parse_btn",
                "dashboard",
                result="blocked",
                level=logging.WARNING,
                payload={"reason": "unsupported_platform"},
            )
            self._toast("仅支持问卷星、腾讯问卷与 Credamo 见数链接", "error")
            return
        # 第二层检测：是否为具体的问卷链接（排除问卷星投票/考试等）
        provider = detect_survey_provider(url)
        if not (provider in {SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_CREDAMO} or is_wjx_survey_url(url)):
            log_action(
                "UI",
                "parse_survey",
                "parse_btn",
                "dashboard",
                result="blocked",
                level=logging.WARNING,
                payload={"reason": "invalid_survey_url"},
            )
            self._toast("链接不是可解析的公开问卷", "error")
            return
        # 使用进度消息条显示解析状态，duration=-1 表示不自动关闭
        self._toast("正在解析问卷...", "info", duration=-1, show_progress=True)
        self._open_wizard_after_parse = True
        self.controller.parse_survey(url)
        log_action(
            "UI",
            "parse_survey",
            "parse_btn",
            "dashboard",
            result="started",
            payload={"provider": detect_survey_provider(url)},
        )
    def _on_survey_parsed(self, info: list, title: str):
        """问卷解析成功的处理（仅负责关闭进度条和记录结果，向导弹出由 MainWindow 处理）"""
        # 关闭进度消息条
        if self._progress_infobar:
            try:
                self._progress_infobar.close()
            except Exception as exc:
                log_suppressed_exception("_on_survey_parsed: self._progress_infobar.close()", exc, level=logging.WARNING)
            self._progress_infobar = None

        count = len(info) if info else 0
        unsupported_count = sum(1 for item in ensure_survey_question_metas(info or []) if bool(item.unsupported))
        if unsupported_count > 0:
            log_action(
                "UI",
                "parse_survey",
                "parse_btn",
                "dashboard",
                result="unsupported",
                level=logging.WARNING,
                payload={"question_count": count, "unsupported_count": unsupported_count},
            )
            return

        log_action(
            "UI",
            "parse_survey",
            "parse_btn",
            "dashboard",
            result="success",
            payload={"question_count": count},
        )
    def _on_survey_parse_failed(self, error_msg: str):
        """问卷解析失败的处理"""
        # 关闭进度消息条
        if self._progress_infobar:
            try:
                self._progress_infobar.close()
            except Exception as exc:
                log_suppressed_exception("_on_survey_parse_failed: self._progress_infobar.close()", exc, level=logging.WARNING)
            self._progress_infobar = None

        text = str(error_msg or "").strip()
        if text == _QQ_LOGIN_REQUIRED_MESSAGE:
            self._toast(text, "warning", duration=4500)
        elif "问卷已暂停" in text:
            self._toast("问卷已暂停，需要前往问卷星后台重新发布", "warning", duration=4500)
        elif "暂未开放" in text:
            self._toast(text, "warning", duration=5000)
        else:
            # 显示解析失败消息
            self._toast(f"解析失败：{text or '请确认链接有效且网络正常'}", "error", duration=3000)
        self._open_wizard_after_parse = False
