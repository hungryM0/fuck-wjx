"""状态轮询 Mixin，用于界面中的在线状态查询。"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from software.app.config import DEFAULT_HTTP_HEADERS, PROXY_STATUS_TIMEOUT_SECONDS


class StatusPollingMixin:
    """使用 Qt 异步网络请求轮询在线状态。"""

    _status_endpoint: str
    _status_formatter: Optional[Callable]
    _status_timer: Optional[QTimer]
    _polling_interval: int
    _status_fetch_in_progress: bool
    _status_session_id: int
    _status_manager: Optional[QNetworkAccessManager]
    _status_reply: Optional[QNetworkReply]

    def _init_status_polling(
        self,
        status_endpoint: str = "",
        status_formatter: Optional[Callable] = None,
        interval_ms: int = 5000,
    ):
        self._status_endpoint = (status_endpoint or "").strip()
        self._status_formatter = status_formatter
        self._status_timer = None
        self._polling_interval = interval_ms
        self._status_fetch_in_progress = False
        self._status_session_id = 0
        self._status_manager = None
        self._status_reply = None

        status_signal: Any = getattr(self, "_statusLoaded", None)
        if status_signal is not None:
            status_signal.connect(self._on_status_loaded)

    def _ensure_status_manager(self) -> QNetworkAccessManager:
        if self._status_manager is None:
            self._status_manager = QNetworkAccessManager(self)  # type: ignore[arg-type]
        return self._status_manager

    def _ensure_status_timer(self) -> QTimer:
        if self._status_timer is None:
            self._status_timer = QTimer(self)  # type: ignore[arg-type]
            self._status_timer.setInterval(self._polling_interval)
            self._status_timer.timeout.connect(self._fetch_status_once)
        return self._status_timer

    def _start_status_polling(self):
        if not self._status_endpoint:
            self._emit_status_loaded("未知：状态接口未配置", "#666666")
            return

        self._status_session_id += 1
        self._status_fetch_in_progress = False
        self._abort_status_reply()
        self._fetch_status_once()
        self._ensure_status_timer().start()

    def _fetch_status_once(self):
        if not self._status_endpoint or self._status_fetch_in_progress:
            return
        if self._status_reply is not None and self._status_reply.isRunning():
            return

        request = QNetworkRequest(QUrl(self._status_endpoint))
        for key, value in DEFAULT_HTTP_HEADERS.items():
            request.setRawHeader(str(key).encode("utf-8"), str(value).encode("utf-8"))
        try:
            request.setTransferTimeout(int(PROXY_STATUS_TIMEOUT_SECONDS * 1000))
        except AttributeError:
            pass

        self._status_fetch_in_progress = True
        session_id = self._status_session_id
        reply = self._ensure_status_manager().get(request)
        self._status_reply = reply
        reply.finished.connect(
            lambda sid=session_id, current_reply=reply: self._handle_status_reply_finished(sid, current_reply)
        )

    def _handle_status_reply_finished(self, session_id: int, reply: QNetworkReply):
        is_current_reply = self._status_reply is reply
        if is_current_reply:
            self._status_reply = None
            self._status_fetch_in_progress = False

        text, color = self._parse_status_reply(reply)
        self._release_status_reply(reply)

        if session_id != self._status_session_id:
            return
        self._emit_status_loaded(text, color)

    def _parse_status_reply(self, reply: QNetworkReply) -> tuple[str, str]:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return "未知：状态获取失败", "#666666"

        status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            parsed_status_code = int(status_code) if status_code is not None else 0
        except (TypeError, ValueError):
            parsed_status_code = 0
        if parsed_status_code >= 400:
            return "未知：状态获取失败", "#666666"

        raw_bytes = bytes(reply.readAll().data())
        if not raw_bytes:
            return "未知：状态未知", "#666666"

        try:
            payload = json.loads(raw_bytes.decode("utf-8", errors="replace"))
        except Exception:
            return "未知：状态未知", "#666666"

        return self._format_status_payload(payload)

    def _format_status_payload(self, payload: Any) -> tuple[str, str]:
        if callable(self._status_formatter):
            try:
                result = self._status_formatter(payload)
                if isinstance(result, tuple) and len(result) >= 2:
                    return str(result[0]), str(result[1])
            except Exception:
                pass

        if isinstance(payload, dict):
            online = payload.get("online", None)
            message = str(payload.get("message") or "").strip()
            if not message:
                if online is True:
                    message = "系统正常运行中"
                elif online is False:
                    message = "系统当前不在线"
                else:
                    message = "状态未知"
            if online is True:
                return f"在线：{message}", "#228B22"
            if online is False:
                return f"离线：{message}", "#cc0000"
            return f"未知：{message}", "#666666"

        return "未知：状态未知", "#666666"

    def _release_status_reply(self, reply: QNetworkReply):
        try:
            reply.finished.disconnect()
        except Exception:
            pass
        try:
            reply.deleteLater()
        except Exception:
            pass

    def _abort_status_reply(self):
        reply = self._status_reply
        self._status_reply = None
        if reply is None:
            return

        try:
            reply.finished.disconnect()
        except Exception:
            pass
        try:
            reply.abort()
        except Exception:
            pass
        try:
            reply.deleteLater()
        except Exception:
            pass

    def _stop_status_polling(self):
        if self._status_timer is not None:
            self._status_timer.stop()

        self._status_session_id += 1
        self._status_fetch_in_progress = False
        self._abort_status_reply()

    def _emit_status_loaded(self, text: str, color: str):
        status_signal: Any = getattr(self, "_statusLoaded", None)
        if status_signal is not None:
            status_signal.emit(text, color)
            return
        self._on_status_loaded(text, color)

    def _on_status_loaded(self, text: str, color: str):
        raise NotImplementedError("子类必须实现 _on_status_loaded 方法")

