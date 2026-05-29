from __future__ import annotations

import threading

from software.ui.controller.run_runtime_port import RunRuntimePort


class _FakeSubmissionHandler:
    def __init__(self) -> None:
        self.calls: list[threading.Event | None] = []

    def __call__(self, *, stop_signal: threading.Event | None = None) -> None:
        self.calls.append(stop_signal)


def test_random_ip_submission_forwards_stop_signal_as_keyword() -> None:
    stop_signal = threading.Event()
    handler = _FakeSubmissionHandler()
    port = RunRuntimePort(
        stop_signal=threading.Event(),
        notify_random_ip_loading=lambda *_args, **_kwargs: None,
        handle_random_ip_submission=handler,
    )

    port.on_random_ip_submission(stop_signal)

    assert handler.calls == [stop_signal]
