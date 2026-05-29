"""ReverseFillPage 交互动作。"""

from __future__ import annotations

import logging
import os
from typing import Any

from PySide6.QtWidgets import QApplication, QFileDialog

from software.logging.action_logger import log_action
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    detect_survey_provider,
    is_supported_survey_url,
    is_wjx_survey_url,
    normalize_survey_provider,
)
from software.providers.contracts import ensure_survey_question_metas
from software.ui.pages.workbench.reverse_fill.logic import (
    is_supported_excel_path,
    iter_supported_drop_paths,
)
from software.ui.pages.workbench.shared.run_feedback import (
    set_completion_notified,
    set_last_progress,
)


def bind_reverse_fill_events(page: Any) -> None:
    page.qr_btn.clicked.connect(page._on_qr_clicked)
    page.url_edit.returnPressed.connect(page._on_parse_clicked)
    page.parse_btn.clicked.connect(page._on_parse_clicked)
    page.url_edit.textChanged.connect(page._on_url_text_changed)
    page.file_edit.editingFinished.connect(page._refresh_preview)
    page.reverse_fill_threads_spin.valueChanged.connect(page._on_reverse_fill_threads_changed)
    page.random_ip_cb.toggled.connect(page._on_random_ip_toggled)
    page.browse_btn.clicked.connect(page._browse_excel_file)
    page.open_wizard_btn.clicked.connect(page._open_wizard)
    clipboard = QApplication.clipboard()
    clipboard.dataChanged.connect(page._on_clipboard_changed)
    page.start_btn.clicked.connect(page._on_start_clicked)
    page.resume_btn.clicked.connect(page._on_resume_clicked)
    page.stop_btn.clicked.connect(page.controller.stop_run)


def prepare_reverse_fill_start_target(page: Any) -> bool:
    if page._last_spec is None:
        page._refresh_preview()
    spec = page._last_spec
    if spec is None:
        message = page._last_error or "反填数据还没预检成功，暂时不能启动"
        page._toast(message, "error", duration=3200)
        return False
    effective_target = max(0, int(getattr(spec, "target_num", 0) or 0))
    if effective_target <= 0:
        page._toast(
            "当前 Excel 没有可提交的有效行，先检查起始行和表格内容",
            "warning",
            duration=3200,
        )
        return False
    coordinator = getattr(page, "_run_coordinator", None)
    if coordinator is not None:
        coordinator.set_reverse_fill_target(effective_target)
    return True


def validate_reverse_fill_start_url(page: Any) -> bool:
    url = page.url_edit.text().strip()
    if not url:
        page._toast("请先输入问卷链接或贴入二维码", "warning")
        return False
    if not is_supported_survey_url(url):
        page._toast(
            "仅支持问卷星、腾讯问卷与 Credamo 见数链接",
            "error",
            duration=3000,
        )
        return False
    if not is_wjx_survey_url(url):
        page._toast("Excel 反填目前只支持问卷星公开问卷链接", "error", duration=3000)
        return False
    if url != page._parsed_url:
        page._toast("反填链接已修改，请先按回车解析问卷结构", "warning", duration=3200)
        return False
    return True


def on_start_clicked(page: Any) -> None:
    coordinator = getattr(page, "_run_coordinator", None)
    if coordinator is None:
        page._toast("主页尚未完成初始化，暂时不能开始执行", "error", duration=3000)
        return
    if not validate_reverse_fill_start_url(page):
        return
    if not prepare_reverse_fill_start_target(page):
        return
    should_reset = bool(coordinator.is_completed_run())
    started = bool(coordinator.start_reverse_fill())
    if started and should_reset:
        page.progress_bar.setValue(0)
        page.progress_pct.setText("0%")
        set_last_progress(page, 0)
        set_completion_notified(page, False)


def browse_excel_file(page: Any) -> None:
    source_path = page.file_edit.text().strip()
    start_dir = os.path.dirname(source_path) if source_path else ""
    path, _ = QFileDialog.getOpenFileName(
        page,
        "选择源数据 Excel 文件",
        start_dir,
        "Excel 数据工作表 (*.xlsx);;所有包含的文件 (*.*)",
    )
    if not path:
        return
    apply_excel_source_path(page, path)


def on_reverse_fill_threads_changed(page: Any, value: int) -> None:
    page._reverse_fill_threads_value = max(1, int(value or 1))
    page._refresh_preview()


def mime_has_excel_file(event: Any) -> bool:
    mime_data = event.mimeData()
    if not mime_data or not mime_data.hasUrls():
        return False
    return bool(iter_supported_drop_paths(mime_data.urls()))


def extract_excel_path_from_drop(page: Any, event: Any) -> str:
    mime_data = event.mimeData()
    if not mime_data or not mime_data.hasUrls():
        return ""
    paths = iter_supported_drop_paths(mime_data.urls())
    if paths:
        return paths[0]
    page._toast("这里只支持拖入 .xlsx 表格文件", "warning", duration=2600)
    return ""


def apply_excel_source_path(page: Any, file_path: str) -> None:
    normalized = str(file_path or "").strip()
    if not is_supported_excel_path(normalized):
        page._toast("请选择 .xlsx 表格文件", "warning", duration=2600)
        return
    page.file_edit.setText(normalized)
    page._refresh_preview()


def on_parse_clicked(page: Any) -> None:
    url = page.url_edit.text().strip()
    if not url:
        page._toast("请先输入问卷链接或贴入二维码", "warning")
        return
    if not is_supported_survey_url(url):
        page._toast(
            "仅支持问卷星、腾讯问卷与 Credamo 见数链接",
            "error",
            duration=3000,
        )
        return
    provider = detect_survey_provider(url)
    if not (
        provider in {SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_CREDAMO} or is_wjx_survey_url(url)
    ):
        page._toast("链接不是可解析的公开问卷", "error", duration=3000)
        return

    page._parse_requested_from_reverse_fill = True
    page.surveyUrlChanged.emit(url)
    page._toast("正在解析问卷结构...", "info", duration=-1, show_progress=True)
    page.controller.parse_survey(url)
    log_action(
        "UI",
        "parse_survey",
        "url_edit",
        "reverse_fill",
        result="started",
        payload={"provider": provider},
    )


def on_url_text_changed(page: Any, text: str) -> None:
    page.surveyUrlChanged.emit(str(text or ""))
    page._refresh_preview()


def on_survey_parsed(page: Any, info: list, title: str) -> None:
    if not page._parse_requested_from_reverse_fill:
        return
    page._parse_requested_from_reverse_fill = False
    parsed_info = ensure_survey_question_metas(info or [])
    unsupported_count = sum(1 for item in parsed_info if bool(item.unsupported))
    page._survey_title = str(title or "").strip()
    page._parsed_url = page.url_edit.text().strip()
    page._survey_provider = normalize_survey_provider(
        page.controller.get_survey_snapshot().get("survey_provider")
        or detect_survey_provider(page.url_edit.text().strip(), default=""),
        default=page._survey_provider or "",
    )
    page._refresh_preview()
    if unsupported_count > 0:
        message = f"问卷已解析，发现 {unsupported_count} 道反填不能直接覆盖的题型"
        page._toast(
            message,
            "warning",
            duration=3600,
        )
        return
    page._toast(
        "问卷已解析，可以继续选择 Excel 做反填预检",
        "success",
        duration=2600,
    )


def on_survey_parse_failed(page: Any, error_msg: str) -> None:
    if not page._parse_requested_from_reverse_fill:
        return
    page._parse_requested_from_reverse_fill = False
    text = str(error_msg or "").strip() or "请确认链接有效且网络正常"
    if "问卷已停止" in text or "停止状态" in text:
        page._toast("问卷已停止，无法作答", "warning", duration=2200)
        return
    if "企业标准版" in text:
        page._toast("问卷发布者企业标准版未购买或已到期，暂时不能填写", "warning", duration=2200)
        return
    if "问卷已暂停" in text:
        page._toast("问卷已暂停，需要前往问卷星后台重新发布", "warning", duration=2200)
        return
    if "暂未开放" in text:
        page._toast(text, "warning", duration=2200)
        return
    page._toast(f"解析失败：{text}", "error", duration=3200)


def open_wizard(page: Any) -> None:
    if not callable(page._open_wizard_handler):
        page._toast(
            "目前无法直接导航至系统向导。您需优先在仪表盘主页完成问卷解析方可继续。",
            "warning",
        )
        return
    issue_question_nums = [int(num) for num in page._issue_question_nums if int(num) > 0]
    if not issue_question_nums:
        page._toast("当前没有需要处理的异常题目。", "warning")
        return
    try:
        page._open_wizard_handler(issue_question_nums)
    except Exception as exc:
        logging.info("打开配置向导异常崩溃", exc_info=True)
        page._toast(f"触发配置交互向导意外阻断：{exc}", "error")
