from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from software.ui.widgets.contact_form.message_builder import (
    build_contact_message,
    build_contact_request_fields,
)
from software.ui.widgets.contact_form.status_polling import StatusPollingMixin


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _Bytes:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def data(self) -> bytes:
        return self._data


class _Finished:
    def __init__(self) -> None:
        self.connected = []
        self.disconnect_calls = 0

    def connect(self, callback) -> None:
        self.connected.append(callback)

    def disconnect(self) -> None:
        self.disconnect_calls += 1


class _Reply:
    def __init__(
        self,
        *,
        error=QNetworkReply.NetworkError.NoError,
        status=200,
        body=b'{"online": true}',
        running=False,
        disconnect_raises=False,
    ) -> None:
        self._error = error
        self._status = status
        self._body = body
        self._running = running
        self._properties = {}
        self.finished = _Finished()
        self.disconnect_raises = disconnect_raises
        self.abort_calls = 0
        self.delete_calls = 0

    def error(self):
        return self._error

    def attribute(self, attr):
        if attr == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self._status
        return None

    def readAll(self):
        return _Bytes(self._body)

    def isRunning(self) -> bool:
        return self._running

    def setProperty(self, name: str, value) -> None:
        self._properties[name] = value

    def property(self, name: str):
        return self._properties.get(name)

    def abort(self) -> None:
        self.abort_calls += 1

    def deleteLater(self) -> None:
        self.delete_calls += 1


class _Manager:
    def __init__(self, reply: _Reply) -> None:
        self.reply = reply
        self.requests = []

    def get(self, request):
        self.requests.append(request)
        return self.reply


class _Timer:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _Host(StatusPollingMixin, QObject):
    def __init__(self) -> None:
        super().__init__()
        self.loaded: list[tuple[str, str]] = []
        self._statusLoaded = _Signal()
        self._init_status_polling()

    def _on_status_loaded(self, text: str, color: str):
        self.loaded.append((text, color))


def test_contact_message_builder_feedback_and_quota_payloads() -> None:
    feedback = build_contact_message(
        version_str="1.2.3",
        message_type="报错反馈",
        issue_title="按钮坏了",
        email="a@example.com",
        donated=False,
        random_ip_user_id=99,
        message="打不开",
        request_payment_method="",
        request_amount_text="",
        request_quota_text="",
        request_urgency_text="",
    )
    assert "来源：SurveyController v1.2.3" in feedback
    assert "反馈标题： 按钮坏了" in feedback
    assert "随机IP用户ID：99" in feedback
    assert feedback.endswith("消息：打不开")

    quota = build_contact_message(
        version_str="1.2.3",
        message_type="额度申请",
        issue_title="忽略",
        email="",
        donated=True,
        random_ip_user_id=0,
        message="",
        request_payment_method="微信",
        request_amount_text="11.45",
        request_quota_text="1500",
        request_urgency_text="",
    )
    assert "已支付：是" in quota
    assert "支付方式：微信" in quota
    assert "紧急程度：中" in quota
    assert "补充说明：未填写" in quota

    fields = build_contact_request_fields(
        message="msg",
        message_type="报错反馈",
        issue_title="title",
        timestamp="now",
        random_ip_user_id=7,
        files_payload=[("file1", ("a.txt", b"a", "text/plain"))],
    )
    assert fields[:3] == [
        ("message", (None, "msg")),
        ("messageType", (None, "报错反馈")),
        ("timestamp", (None, "now")),
    ]
    assert ("issueTitle", (None, "title")) in fields
    assert ("userId", (None, "7")) in fields
    assert fields[-1][0] == "file1"


def test_status_polling_start_fetch_stop_and_abort(monkeypatch) -> None:
    host = _Host()
    host._status_endpoint = ""
    host._start_status_polling()
    assert host.loaded[-1] == ("未知：状态接口未配置", "#666666")

    reply = _Reply(body=b'{"online": true, "message": "ok"}')
    manager = _Manager(reply)
    timer = _Timer()
    host._status_endpoint = "https://example.test/status"
    monkeypatch.setattr(host, "_ensure_status_manager", lambda: manager)
    monkeypatch.setattr(host, "_ensure_status_timer", lambda: timer)

    host._start_status_polling()

    assert host._status_fetch_in_progress is True
    assert host._status_reply is reply
    assert reply.property("_status_session_id") == host._status_session_id
    assert len(reply.finished.connected) == 1
    assert timer.started == 1

    host._fetch_status_once()
    assert len(manager.requests) == 1

    host._handle_status_reply_finished(host._status_session_id, reply)
    assert host.loaded[-1] == ("在线：ok", "#228B22")
    assert host._status_fetch_in_progress is False
    assert reply.delete_calls == 1

    running_reply = _Reply(running=True)
    host._status_reply = running_reply
    host._status_fetch_in_progress = False
    host._fetch_status_once()
    assert len(manager.requests) == 1

    host._status_timer = timer
    host._status_reply = running_reply
    host._stop_status_polling()
    assert timer.stopped == 1
    assert running_reply.abort_calls == 1
    assert running_reply.delete_calls == 1


def test_status_polling_parse_and_format_payloads() -> None:
    host = _Host()

    assert host._parse_status_reply(_Reply(error=QNetworkReply.NetworkError.ConnectionRefusedError)) == (
        "未知：状态获取失败",
        "#666666",
    )
    assert host._parse_status_reply(_Reply(status=500)) == ("未知：状态获取失败", "#666666")
    assert host._parse_status_reply(_Reply(body=b"")) == ("未知：状态未知", "#666666")
    assert host._parse_status_reply(_Reply(body=b"{bad")) == ("未知：状态未知", "#666666")
    assert host._parse_status_reply(_Reply(body=b'{"online": false}')) == (
        "离线：系统当前不在线",
        "#cc0000",
    )
    assert host._parse_status_reply(_Reply(body=b'{"message": "maybe"}')) == (
        "未知：maybe",
        "#666666",
    )
    assert host._format_status_payload(["bad"]) == ("未知：状态未知", "#666666")

    host._status_formatter = lambda payload: ("自定义", "#123456")
    assert host._format_status_payload({"online": True}) == ("自定义", "#123456")

    host._status_formatter = lambda _payload: (_ for _ in ()).throw(RuntimeError("bad"))
    assert host._format_status_payload({"online": True}) == ("在线：系统正常运行中", "#228B22")

    host._status_formatter = lambda _payload: "bad"
    assert host._format_status_payload({"online": False, "message": "down"}) == (
        "离线：down",
        "#cc0000",
    )


def test_status_polling_release_abort_and_signal_fallback() -> None:
    host = _Host()
    reply = _Reply()
    host._release_status_reply(reply)
    assert reply.finished.disconnect_calls == 1
    assert reply.delete_calls == 1

    reply = _Reply()
    host._status_reply = reply
    host._abort_status_reply()
    assert host._status_reply is None
    assert reply.abort_calls == 1
    assert reply.delete_calls == 1

    host._statusLoaded = None
    host._emit_status_loaded("text", "#000")
    assert host.loaded[-1] == ("text", "#000")

    host._status_reply = _Reply(body=b'{"online": true}')
    old_session = host._status_session_id - 1
    before = list(host.loaded)
    host._handle_status_reply_finished(old_session, host._status_reply)
    assert host.loaded == before
