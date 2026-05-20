from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

import software.ui.dialogs.contact as contact_dialog_module
from software.ui.dialogs.contact import ContactDialog


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _FakeContactForm(QWidget):
    def __init__(self, _parent=None, **kwargs) -> None:
        super().__init__(_parent)
        self.kwargs = kwargs
        self.sendSucceeded = _FakeSignal()
        self.cancelRequested = _FakeSignal()
        self.pending_async = False
        self.pending_warning_calls = 0
        self.start_polling_calls = 0
        self.stop_polling_calls = 0

    def start_status_polling(self) -> None:
        self.start_polling_calls += 1

    def stop_status_polling(self) -> None:
        self.stop_polling_calls += 1

    def has_pending_async_work(self) -> bool:
        return self.pending_async

    def show_pending_async_warning(self) -> None:
        self.pending_warning_calls += 1


class _FakeParent(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1600, 1000)
        self._snapshot = "cfg"

    def _collect_current_config_snapshot(self):
        return self._snapshot


@pytest.fixture(scope="module", autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


class ContactDialogTests:
    def test_dialog_initializes_form_and_polling(self, monkeypatch) -> None:
        monkeypatch.setattr(contact_dialog_module, "ContactForm", _FakeContactForm)
        parent = _FakeParent()
        dialog = ContactDialog(parent=parent, default_type="额度申请", lock_message_type=True)
        form = cast(_FakeContactForm, dialog.form)
        assert isinstance(form, _FakeContactForm)
        assert form.kwargs["default_type"] == "额度申请"
        assert form.kwargs["lock_message_type"] is True
        assert form.kwargs["config_snapshot_provider"]() == "cfg"
        assert dialog.widget.width() == 760
        assert dialog.widget.height() == 620
        assert dialog.buttonGroup.isHidden()

        dialog._schedule_status_polling()
        assert dialog._status_poll_timer.isSingleShot()
        assert dialog._status_poll_timer.interval() == 700

    def test_show_event_and_start_status_polling_if_visible(self, monkeypatch) -> None:
        monkeypatch.setattr(contact_dialog_module, "ContactForm", _FakeContactForm)
        dialog = ContactDialog()
        form = cast(_FakeContactForm, dialog.form)
        dialog.show()
        dialog._start_status_polling_if_ready()
        assert form.start_polling_calls >= 1
        dialog.hide()
        before = form.start_polling_calls
        dialog._start_status_polling_if_ready()
        assert form.start_polling_calls == before

    def test_send_success_close_and_stop_polling(self, monkeypatch) -> None:
        monkeypatch.setattr(contact_dialog_module, "ContactForm", _FakeContactForm)
        calls = []
        monkeypatch.setattr(
            contact_dialog_module.QTimer,
            "singleShot",
            lambda delay, callback: calls.append(delay) or callback(),
        )
        dialog = ContactDialog()
        accepted = []
        dialog.accept = lambda: accepted.append("accepted")
        dialog._on_send_succeeded()
        assert calls == [2800]
        assert accepted == ["accepted"]

        dialog._stop_status_polling()
        assert cast(_FakeContactForm, dialog.form).stop_polling_calls == 1

    def test_close_reject_accept_block_on_pending_async_work(self, monkeypatch) -> None:
        monkeypatch.setattr(contact_dialog_module, "ContactForm", _FakeContactForm)
        dialog = ContactDialog()
        form = cast(_FakeContactForm, dialog.form)
        form.pending_async = True

        event = QCloseEvent()
        dialog.closeEvent(event)
        assert not event.isAccepted()
        assert form.pending_warning_calls == 1

        dialog.reject()
        dialog.accept()
        assert form.pending_warning_calls == 3

        form.pending_async = False
        dialog.reject()
        dialog.accept()
        assert form.stop_polling_calls >= 2
