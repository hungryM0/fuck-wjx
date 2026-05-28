from __future__ import annotations

from software.core.config.schema import RuntimeConfig
from software.providers.common import SURVEY_PROVIDER_WJX
from software.ui.controller.run_controller import RunController
from software.ui.controller.runtime_settings_state import RuntimeSettingsState


def test_runtime_settings_state_defaults() -> None:
    state = RuntimeSettingsState()
    cfg = RuntimeConfig()

    assert state.get() == {}
    assert state.sync_from_config(cfg) == (
        {
            "target": 1,
            "threads": 1,
            "random_ip_enabled": False,
            "survey_provider": SURVEY_PROVIDER_WJX,
            "proxy_source": "default",
            "submit_interval": (0, 0),
            "answer_duration": (60, 120),
            "answer_datetime_window": ("", ""),
        },
        True,
    )


def test_runtime_settings_state_writes_synced_defaults_to_config() -> None:
    cfg = RuntimeConfig(
        target=9,
        threads=3,
        random_ip_enabled=True,
        survey_provider="qq",
        proxy_source="custom",
        submit_interval=(2, 4),
        answer_duration=(5, 6),
        answer_datetime_window=("2026-02-10 09:00:00", "2026-02-10 10:00:00"),
    )

    state = RuntimeSettingsState()
    state.sync_from_config(RuntimeConfig())
    state.write_to_config(cfg)

    assert {
        "target": cfg.target,
        "threads": cfg.threads,
        "random_ip_enabled": cfg.random_ip_enabled,
        "survey_provider": cfg.survey_provider,
        "proxy_source": cfg.proxy_source,
        "submit_interval": cfg.submit_interval,
        "answer_duration": cfg.answer_duration,
        "answer_datetime_window": cfg.answer_datetime_window,
    } == {
        "target": 1,
        "threads": 1,
        "random_ip_enabled": False,
        "survey_provider": SURVEY_PROVIDER_WJX,
        "proxy_source": "default",
        "submit_interval": (0, 0),
        "answer_duration": (60, 120),
        "answer_datetime_window": ("", ""),
    }


def test_runtime_settings_state_normalizes_updates() -> None:
    state = RuntimeSettingsState()

    current, changed = state.update(
        target=0,
        threads="4",
        random_ip_enabled=1,
        proxy_source="CUSTOM",
        submit_interval=(3, 1),
        answer_duration=[2, 8],
        answer_datetime_window=("2026-02-10 09:00:00", "bad"),
    )

    assert changed is True
    assert current["target"] == 1
    assert current["threads"] == 4
    assert current["random_ip_enabled"] is True
    assert current["proxy_source"] == "custom"
    assert current["submit_interval"] == (3, 3)
    assert current["answer_duration"] == (2, 8)
    assert current["answer_datetime_window"] == ("2026-02-10 09:00:00", "")


def test_runtime_settings_state_expands_legacy_answer_duration_single_value() -> None:
    state = RuntimeSettingsState()

    current, changed = state.update(answer_duration=90)

    assert changed is True
    assert current["answer_duration"] == (81, 99)

    current, changed = state.update(answer_duration=(180, 180))

    assert changed is True
    assert current["answer_duration"] == (162, 198)


def test_runtime_settings_state_clamps_answer_duration_to_30_minutes() -> None:
    state = RuntimeSettingsState()

    current, changed = state.update(answer_duration=(1200, 9999))

    assert changed is True
    assert current["answer_duration"] == (1200, 1800)


def test_runtime_settings_state_keeps_threads_when_locked() -> None:
    state = RuntimeSettingsState()
    state.update(threads=3)

    current, changed = state.update(lock_threads=True, threads=9, target=6)

    assert changed is True
    assert current["threads"] == 3
    assert current["target"] == 6


def test_run_controller_keeps_threads_while_running(qapp) -> None:
    controller = RunController()
    controller.set_runtime_ui_state(emit=False, threads=5)

    controller.running = True
    current = controller.set_runtime_ui_state(emit=False, threads=8, target=7)

    assert current["threads"] == 5
    assert current["target"] == 7


def test_run_controller_writes_runtime_state_to_config(qapp) -> None:
    controller = RunController()
    controller.set_runtime_ui_state(
        emit=False,
        target=10,
        threads=3,
        random_ip_enabled=True,
        proxy_source="custom",
        submit_interval=(4, 2),
        answer_duration=(6, 9),
        answer_datetime_window=("2026-02-10 09:00:00", "2026-02-10 10:00:00"),
    )
    cfg = RuntimeConfig()

    controller.write_to_config(cfg)

    assert cfg.target == 10
    assert cfg.threads == 3
    assert cfg.random_ip_enabled is True
    assert cfg.proxy_source == "custom"
    assert cfg.submit_interval == (4, 4)
    assert cfg.answer_duration == (6, 9)
    assert cfg.answer_datetime_window == ("2026-02-10 09:00:00", "2026-02-10 10:00:00")


def test_runtime_settings_state_writes_to_config() -> None:
    state = RuntimeSettingsState()
    state.update(
        target=12,
        threads=4,
        random_ip_enabled=True,
        survey_provider="qq",
        proxy_source="benefit",
        submit_interval=(5, 1),
        answer_duration=(8, 10),
        answer_datetime_window=("2026-02-10 09:00:00", "2026-02-10 10:00:00"),
    )
    cfg = RuntimeConfig(url="https://example.test")

    returned = state.write_to_config(cfg)

    assert returned is cfg
    assert cfg.url == "https://example.test"
    assert cfg.target == 12
    assert cfg.threads == 4
    assert cfg.random_ip_enabled is True
    assert cfg.survey_provider == "qq"
    assert cfg.proxy_source == "benefit"
    assert cfg.submit_interval == (5, 5)
    assert cfg.answer_duration == (8, 10)
    assert cfg.answer_datetime_window == ("2026-02-10 09:00:00", "2026-02-10 10:00:00")
