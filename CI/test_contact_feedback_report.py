"""报错反馈表单自动附件最小回归测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WJX_IMPORT_CHECK", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from software.core.config.schema import RuntimeConfig
from software.ui.widgets.contact_form import ContactForm


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bug_report_auto_attachment_checkboxes() -> None:
    app = _app()
    form = ContactForm(
        default_type="报错反馈",
        manage_polling=False,
        auto_clear_on_success=True,
        config_snapshot_provider=lambda: RuntimeConfig(),
    )
    form.show()
    app.processEvents()

    if not form.auto_attach_config_checkbox.isVisible():
        raise AssertionError("报错反馈应显示“上传当前运行配置”复选框")
    if not form.auto_attach_log_checkbox.isVisible():
        raise AssertionError("报错反馈应显示“上传当前日志”复选框")
    if not form.auto_attach_config_checkbox.isChecked():
        raise AssertionError("“上传当前运行配置”默认应为勾选")
    if not form.auto_attach_log_checkbox.isChecked():
        raise AssertionError("“上传当前日志”默认应为勾选")

    chat_index = form.type_combo.findText("纯聊天")
    if chat_index < 0:
        raise AssertionError("测试前提失败：缺少“纯聊天”消息类型")
    form.type_combo.setCurrentIndex(chat_index)
    app.processEvents()

    if form.auto_attach_config_checkbox.isVisible() or form.auto_attach_log_checkbox.isVisible():
        raise AssertionError("非报错反馈类型不应显示自动附件复选框")

    bug_index = form.type_combo.findText("报错反馈")
    if bug_index < 0:
        raise AssertionError("测试前提失败：缺少“报错反馈”消息类型")
    form.type_combo.setCurrentIndex(bug_index)
    app.processEvents()

    if not form.auto_attach_config_checkbox.isVisible() or not form.auto_attach_log_checkbox.isVisible():
        raise AssertionError("切回报错反馈后应重新显示自动附件复选框")

    form.auto_attach_config_checkbox.setChecked(False)
    form.auto_attach_log_checkbox.setChecked(False)
    form._current_message_type = "报错反馈"
    form._on_send_finished(True, "")
    app.processEvents()

    if not form.auto_attach_config_checkbox.isChecked():
        raise AssertionError("发送成功清空表单后，应恢复“上传当前运行配置”默认勾选")
    if not form.auto_attach_log_checkbox.isChecked():
        raise AssertionError("发送成功清空表单后，应恢复“上传当前日志”默认勾选")

    form.close()


def main() -> None:
    test_bug_report_auto_attachment_checkboxes()
    print("contact feedback report tests passed")


if __name__ == "__main__":
    main()
