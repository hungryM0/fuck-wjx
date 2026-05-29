from __future__ import annotations

import threading

from software.ui.controller.engine_adapter import EngineGuiAdapter


class _FakeCleanupTarget:
    def __init__(self, name: str, events: list[str], on_quit=None) -> None:
        self.name = name
        self.events = events
        self.on_quit = on_quit
        self.cleaned = False

    def mark_cleanup_done(self) -> bool:
        if self.cleaned:
            return False
        self.cleaned = True
        return True

    def quit(self) -> None:
        self.events.append(self.name)
        if callable(self.on_quit):
            self.on_quit()


class _FakeManagedTarget(_FakeCleanupTarget):
    def __init__(self, name: str, events: list[str]) -> None:
        super().__init__(name, events)
        self.aclose_calls = 0

    async def aclose(self) -> None:
        self.aclose_calls += 1
        self.events.append(f"{self.name}:aclose")


class EngineGuiAdapterCleanupTests:
    def _build_adapter(self) -> EngineGuiAdapter:
        return EngineGuiAdapter(
            dispatcher=lambda callback: callback(),
            async_dispatcher=lambda callback: callback(),
            stop_signal=threading.Event(),
        )

    def test_cleanup_targets_uses_lifo_order(self) -> None:
        adapter = self._build_adapter()
        events: list[str] = []
        pool = _FakeCleanupTarget("pool", events)
        driver = _FakeCleanupTarget("driver", events)
        adapter.register_cleanup_target(pool)
        adapter.register_cleanup_target(driver)
        adapter.cleanup_targets()
        assert events == ["driver", "pool"]

    def test_cleanup_targets_drains_targets_added_during_cleanup(self) -> None:
        adapter = self._build_adapter()
        events: list[str] = []
        late = _FakeCleanupTarget("late", events)
        first = _FakeCleanupTarget(
            "first",
            events,
            on_quit=lambda: adapter.register_cleanup_target(late),
        )
        adapter.register_cleanup_target(first)
        adapter.cleanup_targets()
        assert events == ["first", "late"]
        assert adapter.active_drivers == []

    def test_runtime_actions_use_bound_callbacks(self) -> None:
        adapter = self._build_adapter()
        events: list[object] = []
        adapter.bind_runtime_actions(
            refresh_random_ip_counter=lambda: events.append(("refresh",)),
            toggle_random_ip=lambda enabled: events.append(("toggle", enabled)) or bool(enabled),
            handle_random_ip_submission=lambda stop_signal: events.append(("submit", stop_signal)),
        )

        adapter.refresh_random_ip_counter()
        assert adapter.toggle_random_ip(True) is True
        adapter.handle_random_ip_submission("stop")

        assert events == [("refresh",), ("toggle", True), ("submit", "stop")]

    def test_cleanup_targets_prefers_async_close_when_available(self) -> None:
        adapter = self._build_adapter()
        events: list[str] = []
        driver = _FakeManagedTarget("driver", events)

        adapter.register_cleanup_target(driver)
        adapter.cleanup_targets()

        assert events == ["driver:aclose"]
        assert driver.aclose_calls == 1
