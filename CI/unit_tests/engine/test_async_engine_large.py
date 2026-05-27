from __future__ import annotations

import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest

import software.core.engine.async_engine as async_engine
from software.core.engine.async_engine import AsyncEngineClient, AsyncRuntimeEngine
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease


class _FakeLoop:
    def __init__(self) -> None:
        self.stopped = False
        self.closed = False
        self.threadsafe_calls: list[tuple[object, tuple[object, ...]]] = []
        self.run_forever_calls = 0
        self.run_until_complete_calls: list[object] = []
        self.shutdown_asyncgens_calls = 0

    def run_forever(self) -> None:
        self.run_forever_calls += 1

    def run_until_complete(self, awaitable) -> None:
        self.run_until_complete_calls.append(awaitable)
        if asyncio.iscoroutine(awaitable):
            asyncio.run(awaitable)

    async def shutdown_asyncgens(self) -> None:
        self.shutdown_asyncgens_calls += 1

    def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def call_soon_threadsafe(self, callback, *args) -> None:
        self.threadsafe_calls.append((callback, args))
        callback(*args)

    def stop(self) -> None:
        self.stopped = True


class _FakeThread:
    created: list["_FakeThread"] = []

    def __init__(self, *, target, daemon: bool, name: str) -> None:
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.join_calls: list[float | None] = []
        _FakeThread.created.append(self)

    def start(self) -> None:
        self.started = True
        self.target()

    def is_alive(self) -> bool:
        return self.started

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)


class _DoneFuture:
    def __init__(self, *, done: bool = True, result_value=None, result_error: Exception | None = None) -> None:
        self._done = done
        self._result_value = result_value
        self._result_error = result_error
        self.result_calls: list[float | None] = []

    def done(self) -> bool:
        return self._done

    def result(self, timeout: float | None = None):
        self.result_calls.append(timeout)
        if self._result_error is not None:
            raise self._result_error
        return self._result_value


def _build_engine() -> AsyncRuntimeEngine:
    return AsyncRuntimeEngine(status_bus=SimpleNamespace(emit=lambda _event: None))


class AsyncRuntimeEngineLargeTests:
    def test_start_reuses_live_thread_and_submit_requires_loop(self, monkeypatch) -> None:
        engine = _build_engine()
        alive_thread = SimpleNamespace(is_alive=lambda: True)
        engine._thread = alive_thread
        engine._loop_ready.set()

        engine.start()
        assert engine.thread is alive_thread

        engine._thread = None
        engine._loop = None
        monkeypatch.setattr(engine, "start", lambda: None)
        coro = asyncio.sleep(0)

        with pytest.raises(RuntimeError, match="未启动"):
            engine._submit(coro)
        coro.close()

    def test_start_initializes_background_loop_and_shutdown_clears_handles(self, monkeypatch) -> None:
        engine = _build_engine()
        fake_loop = _FakeLoop()
        real_all_tasks = asyncio.all_tasks
        monkeypatch.setattr(asyncio, "new_event_loop", lambda: fake_loop)
        monkeypatch.setattr(asyncio, "set_event_loop", lambda loop: None)
        monkeypatch.setattr(asyncio, "all_tasks", lambda loop=None: set() if loop is fake_loop else real_all_tasks(loop))
        monkeypatch.setattr(async_engine.threading, "Thread", _FakeThread)
        _FakeThread.created.clear()

        engine.start()

        assert engine.thread is _FakeThread.created[0]
        assert engine._loop is fake_loop
        assert fake_loop.run_forever_calls == 1
        assert fake_loop.shutdown_asyncgens_calls == 1
        assert fake_loop.closed is True

        engine.shutdown(timeout=1.5)

        assert engine.thread is None
        assert engine._loop is None

    def test_start_run_stop_pause_resume_parse_and_submit_ui_task(self, monkeypatch) -> None:
        engine = _build_engine()
        config = ExecutionConfig(num_threads=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        submitted: list[object] = []
        run_future = _DoneFuture(done=False)
        parse_future = _DoneFuture(result_value="parsed")
        ui_future = _DoneFuture(result_value="ui-ok")
        returned_futures = [run_future, parse_future, ui_future]
        loop = _FakeLoop()
        engine._loop = loop
        engine._run_future = _DoneFuture(done=True)
        stop_event = SimpleNamespace(set=lambda: submitted.append("stop-event"))
        pause_event = SimpleNamespace(set=lambda: submitted.append("pause"), clear=lambda: submitted.append("resume"))
        engine._stop_event = stop_event
        engine._pause_event = pause_event
        engine._state = state

        def _fake_submit(coro):
            submitted.append(coro)
            return returned_futures.pop(0)

        monkeypatch.setattr(engine, "_submit", _fake_submit)
        monkeypatch.setattr(async_engine, "parse_survey", lambda url: asyncio.sleep(0, result=f"parsed:{url}"))

        future = engine.start_run(config=config, state=state, runtime_bridge=None)
        assert future is run_future
        assert engine._run_future is run_future

        with pytest.raises(RuntimeError, match="运行中"):
            engine._run_future = _DoneFuture(done=False)
            engine.start_run(config=config, state=state)

        engine._run_future = _DoneFuture(done=True)
        engine.stop_run()
        engine.pause_run("reason")
        engine.resume_run()
        parse_result = engine.parse_survey("https://example.com")
        ui_result = engine.submit_ui_task("task", lambda: asyncio.sleep(0, result="ui-ok"))

        for item in submitted:
            if asyncio.iscoroutine(item):
                item.close()
        assert asyncio.iscoroutine(submitted[0])
        assert "stop-event" in submitted
        assert "pause" in submitted
        assert "resume" in submitted
        assert parse_result is parse_future
        assert ui_result is ui_future
        assert state.stop_event.is_set()
        assert engine._run_future is None
        assert any(call[0] == stop_event.set for call in loop.threadsafe_calls)
        assert any(call[0] == pause_event.set for call in loop.threadsafe_calls)
        assert any(call[0] == pause_event.clear for call in loop.threadsafe_calls)

    @pytest.mark.asyncio
    async def test_run_starts_slots_and_closes_scheduler_when_runner_fails(self, monkeypatch) -> None:
        engine = _build_engine()
        config = ExecutionConfig(num_threads=2, target_num=5, survey_provider="wjx")
        state = ExecutionState(config=config)
        bus_events: list[dict[str, object]] = []
        engine._status_bus = SimpleNamespace(emit=lambda event: bus_events.append(event))
        created_runners: list[SimpleNamespace] = []
        created_schedulers: list[SimpleNamespace] = []

        class _FakeRunner:
            def __init__(self, **kwargs) -> None:
                self.slot_id = kwargs["slot_id"]
                self.cancelled = False
                created_runners.append(self)

            async def run(self) -> None:
                if self.slot_id == 2:
                    raise RuntimeError("slot boom")
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency
                self.close_calls = 0
                created_schedulers.append(self)

            async def close(self) -> None:
                self.close_calls += 1

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncRunContext", lambda **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)

        with pytest.raises(RuntimeError, match="slot boom"):
            await engine._run(config=config, state=state, runtime_bridge=None)

        assert len(created_runners) == 2
        assert created_runners[0].slot_id == 1
        assert created_runners[1].slot_id == 2
        assert created_runners[0].cancelled is True
        assert created_schedulers[0].close_calls == 1
        assert state.stop_event.is_set()
        assert engine._stop_event is None
        assert engine._pause_event is None
        assert engine._state is None

    @pytest.mark.asyncio
    async def test_run_starts_async_proxy_prefetch_without_blocking_slots(self, monkeypatch) -> None:
        engine = _build_engine()
        config = ExecutionConfig(
            num_threads=2,
            target_num=5,
            random_proxy_ip_enabled=True,
            survey_provider="wjx",
        )
        state = ExecutionState(config=config)
        events: list[str] = []
        loading_calls: list[tuple[bool, str]] = []

        class _FakeRunner:
            def __init__(self, **kwargs) -> None:
                self.slot_id = kwargs["slot_id"]

            async def run(self) -> None:
                events.append(f"slot-{self.slot_id}")

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency

            async def close(self) -> None:
                events.append("scheduler-close")

        class _FakeBridge:
            def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
                loading_calls.append((bool(loading), str(message or "")))

        async def fake_fetch_proxy_batch_async(**kwargs):
            events.append(f"fetch-{kwargs['expected_count']}")
            await asyncio.sleep(0)
            return [
                ProxyLease(address="http://1.1.1.1:8000"),
                ProxyLease(address="http://2.2.2.2:8000"),
            ]

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)
        monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fake_fetch_proxy_batch_async)

        await engine._run(config=config, state=state, runtime_bridge=_FakeBridge())

        assert "slot-1" in events
        assert "slot-2" in events
        assert "fetch-4" in events
        assert [lease.address for lease in state.config.proxy_ip_pool] == [
            "http://1.1.1.1:8000",
            "http://2.2.2.2:8000",
        ]
        assert loading_calls[0] == (True, "正在准备代理 0/4")
        assert loading_calls[-1] == (False, "")

    @pytest.mark.asyncio
    async def test_run_async_proxy_prefetch_does_not_write_after_stop(self, monkeypatch) -> None:
        engine = _build_engine()
        config = ExecutionConfig(
            num_threads=1,
            target_num=3,
            random_proxy_ip_enabled=True,
            survey_provider="wjx",
        )
        state = ExecutionState(config=config)

        class _FakeRunner:
            def __init__(self, **_kwargs) -> None:
                pass

            async def run(self) -> None:
                state.stop_event.set()

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency

            async def close(self) -> None:
                return None

        async def fake_fetch_proxy_batch_async(**_kwargs):
            state.stop_event.set()
            return [ProxyLease(address="http://1.1.1.1:8000")]

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)
        monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fake_fetch_proxy_batch_async)

        await engine._run(config=config, state=state, runtime_bridge=None)

        assert list(state.config.proxy_ip_pool) == []

    def test_shutdown_handles_future_errors_and_stops_loop(self) -> None:
        engine = _build_engine()
        engine._closed = False
        run_future = _DoneFuture(done=False, result_error=RuntimeError("future boom"))
        engine._run_future = run_future
        engine._loop = _FakeLoop()
        thread = _FakeThread(target=lambda: None, daemon=True, name="AsyncRuntimeEngine")
        thread.started = True
        engine._thread = thread

        engine.shutdown(timeout=2.5)

        assert engine._closed is True
        assert run_future.result_calls == [2.5]
        assert engine._loop is None
        assert engine._thread is None
        assert thread.join_calls == [2.5]

    def test_async_engine_client_forwards_all_calls(self) -> None:
        calls: list[tuple[str, object]] = []
        future = concurrent.futures.Future()
        future.set_result("ok")
        engine = SimpleNamespace(
            thread="thread",
            start_run=lambda **kwargs: calls.append(("start_run", kwargs)) or future,
            stop_run=lambda: calls.append(("stop_run", None)),
            pause_run=lambda reason="": calls.append(("pause_run", reason)),
            resume_run=lambda: calls.append(("resume_run", None)),
            parse_survey=lambda url: calls.append(("parse_survey", url)) or future,
            submit_ui_task=lambda task_name, coro_factory: calls.append(("submit_ui_task", task_name)) or future,
            shutdown=lambda timeout=5.0: calls.append(("shutdown", timeout)),
        )
        client = AsyncEngineClient(engine=engine)
        config = ExecutionConfig(survey_provider="wjx")
        state = ExecutionState(config=config)

        assert client.thread == "thread"
        assert client.start_run(config, state) is future
        client.stop_run()
        client.pause_run("pause")
        client.resume_run()
        assert client.parse_survey("https://example.com") is future
        assert client.submit_ui_task("task", lambda: asyncio.sleep(0)) is future
        client.shutdown(timeout=1.2)

        assert [name for name, _value in calls] == [
            "start_run",
            "stop_run",
            "pause_run",
            "resume_run",
            "parse_survey",
            "submit_ui_task",
            "shutdown",
        ]
