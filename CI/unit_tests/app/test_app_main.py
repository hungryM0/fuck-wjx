from __future__ import annotations

from types import SimpleNamespace

import software.app.main as main_module


class _FakeApp:
    def __init__(self, argv) -> None:
        self.argv = list(argv)
        self.font = None
        self.exec_calls = 0

    def setFont(self, font) -> None:
        self.font = font

    def exec(self) -> int:
        self.exec_calls += 1
        return 7


class _FakeWindow:
    def __init__(self) -> None:
        self.shown = 0

    def show(self) -> None:
        self.shown += 1


def test_main_returns_exit_code_and_avoids_hard_exit(monkeypatch) -> None:
    events: list[str] = []
    fake_window = _FakeWindow()

    monkeypatch.setattr(main_module, "_run_velopack_startup", lambda: events.append("velopack"))
    monkeypatch.setattr(main_module, "_is_velopack_lifecycle_hook", lambda _argv: False)
    monkeypatch.setattr(main_module, "_should_run_update_test_probe", lambda: False)
    monkeypatch.setattr(
        main_module,
        "configure_qt_application_metadata",
        lambda: events.append("metadata"),
    )
    monkeypatch.setattr(
        main_module,
        "ensure_user_data_directories",
        lambda: events.append("dirs"),
    )
    monkeypatch.setattr(main_module, "_enable_fault_handler", lambda: events.append("fault_on"))
    monkeypatch.setattr(main_module, "setup_logging", lambda: events.append("logging_on"))
    monkeypatch.setattr(main_module, "qInstallMessageHandler", lambda _handler: events.append("qt_msg"))
    monkeypatch.setattr(
        main_module,
        "install_qfluentwidgets_animation_guards",
        lambda: events.append("guards"),
    )
    monkeypatch.setattr(
        main_module.http_client,
        "prewarm",
        lambda: events.append("prewarm"),
    )
    monkeypatch.setattr(main_module, "_disable_fault_handler", lambda: events.append("fault_off"))
    monkeypatch.setattr(
        main_module.os,
        "_exit",
        lambda _code: (_ for _ in ()).throw(AssertionError("不该调用 os._exit")),
    )

    fake_app = _FakeApp(main_module.sys.argv)
    monkeypatch.setattr(main_module, "QApplication", lambda argv: fake_app)
    monkeypatch.setattr(main_module, "QFont", lambda family, size: (family, size))
    monkeypatch.setitem(
        main_module.sys.modules,
        "software.ui.shell.main_window",
        SimpleNamespace(create_window=lambda: fake_window),
    )
    monkeypatch.setitem(
        main_module.sys.modules,
        "software.logging.log_utils",
        SimpleNamespace(shutdown_logging=lambda: events.append("logging_off")),
    )

    exit_code = main_module.main()

    assert exit_code == 7
    assert fake_app.exec_calls == 1
    assert fake_window.shown == 1
    assert events == [
        "velopack",
        "metadata",
        "dirs",
        "fault_on",
        "logging_on",
        "qt_msg",
        "guards",
        "prewarm",
        "logging_off",
        "fault_off",
    ]


def test_main_returns_zero_for_velopack_hook(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "_run_velopack_startup", lambda: None)
    monkeypatch.setattr(main_module, "_is_velopack_lifecycle_hook", lambda _argv: True)

    assert main_module.main() == 0
