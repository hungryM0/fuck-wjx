from __future__ import annotations

import threading
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

from software.core.config.schema import RuntimeConfig
from software.ui.controller.run_controller_parts.runtime_execution import (
    RunControllerExecutionMixin,
)
from software.ui.controller.run_controller_parts.runtime_preparation import (
    PreparedExecutionArtifacts,
)
import software.ui.controller.run_controller_parts.runtime_execution as controller_module


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeTimer:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _FakeSleepBlocker:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self) -> None:
        self.acquired += 1

    def release(self) -> None:
        self.released += 1


class _FakeCleanupRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, float]] = []

    def submit(self, callback, *, delay_seconds: float = 0.0) -> None:
        self.calls.append((callback, float(delay_seconds)))


class _FakeAdapter:
    def __init__(self) -> None:
        self.random_ip_enabled = False
        self.runtime_actions_bound = {}
        self.execution_state = None
        self.resume_calls = 0
        self.cleanup_calls = 0
        self.pause_reason = ""
        self.paused = False

    @property
    def random_ip_enabled_var(self):
        return SimpleNamespace(set=lambda value: setattr(self, "random_ip_enabled", bool(value)))

    def bind_runtime_actions(self, **kwargs) -> None:
        self.runtime_actions_bound = dict(kwargs)

    def is_random_ip_enabled(self) -> bool:
        return self.random_ip_enabled

    def resume_run(self) -> None:
        self.resume_calls += 1

    def cleanup_targets(self) -> None:
        self.cleanup_calls += 1

    def is_paused(self) -> bool:
        return self.paused

    def get_pause_reason(self) -> str:
        return self.pause_reason


class _FakeExecutionState:
    def __init__(self, *, target_num: int = 10, num_threads: int = 3) -> None:
        self.cur_num = 0
        self.cur_fail = 0
        self.device_quota_fail_count = 0
        self.config = SimpleNamespace(target_num=target_num, num_threads=num_threads)
        self.stop_event = threading.Event()
        self.ensure_calls: list[tuple[int, str]] = []
        self.reverse_fill_init_calls = 0
        self.snapshot_rows = [{"thread": "Slot-1"}]
        self.terminal_snapshot: tuple[str, str, str] = ("", "", "")
        self.mark_terminal_stop_calls: list[tuple[str, str, str]] = []

    def ensure_worker_threads(self, count: int, *, prefix: str) -> None:
        self.ensure_calls.append((int(count), str(prefix)))

    def initialize_reverse_fill_runtime(self) -> None:
        self.reverse_fill_init_calls += 1

    def snapshot_thread_progress(self):
        return list(self.snapshot_rows)

    def get_terminal_stop_snapshot(self):
        return self.terminal_snapshot

    def mark_terminal_stop(self, category: str, *, failure_reason: str, message: str) -> None:
        self.mark_terminal_stop_calls.append((category, failure_reason, message))


class _FakeRunFuture:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc

    def result(self):
        if self.exc is not None:
            raise self.exc
        return None


class _FakeEngineClient:
    def __init__(self) -> None:
        self.thread: Any = None
        self.start_calls = []
        self.stop_calls = 0
        self.resume_calls = 0
        self.shutdown_calls = []
        self.future = _FakeRunFuture()

    def start_run(self, execution_config, execution_state, *, runtime_bridge):
        self.start_calls.append((execution_config, execution_state, runtime_bridge))
        return self.future

    def stop_run(self) -> None:
        self.stop_calls += 1

    def resume_run(self) -> None:
        self.resume_calls += 1

    def shutdown(self, *, timeout: float) -> None:
        self.shutdown_calls.append(float(timeout))


class _FakeThread(threading.Thread):
    def __init__(self, *, alive: bool = False, name: str = "worker") -> None:
        super().__init__(target=lambda: None, name=name)
        self._alive = alive
        self.join_calls = []

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        self.join_calls.append(timeout)
        self._alive = False


class _FakeCloseLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _DummyExecutionController(RunControllerExecutionMixin):
    def __init__(self) -> None:
        self._engine_adapter_cls = self._build_adapter
        self._cleanup_runner = _FakeCleanupRunner()
        self._status_timer = _FakeTimer()
        self.runFailed = _FakeSignal()
        self.runStateChanged = _FakeSignal()
        self.statusUpdated = _FakeSignal()
        self.threadProgressUpdated = _FakeSignal()
        self.pauseStateChanged = _FakeSignal()
        self.cleanupFinished = _FakeSignal()
        self.quickBugReportSuggested = _FakeSignal()
        self.freeAiUnstableSuggested = _FakeSignal()
        self.quota_request_form_opener = lambda: True
        self.on_ip_counter = None
        self.on_random_ip_loading = None
        self.message_dialog_handler = None
        self.confirm_dialog_handler = None
        self.custom_confirm_dialog_handler = None
        self.stop_event = threading.Event()
        self.worker_threads: list[Any] = []
        self.adapter = _FakeAdapter()
        self.config = RuntimeConfig()
        self.config.target = 7
        self.config.threads = 2
        self.config.random_ip_enabled = False
        self.running = False
        self._init_gate_thread = None
        self._monitor_thread = None
        self._execution_state = None
        self._async_engine_client = _FakeEngineClient()
        self._sleep_blocker = _FakeSleepBlocker()
        self._close_shutdown_lock = _FakeCloseLock()
        self._close_shutdown_thread = None
        self.survey_provider = ""
        self.question_entries = []
        self.questions_info = []
        self.survey_title = "测试问卷"
        self._starting = False
        self._initializing = False
        self._paused_state = False
        self._stopping = False
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._init_stage_text = ""
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event = None
        self._prepared_execution_artifacts = None
        self._quick_feedback_prompt_emitted = False
        self.dispatched_async = []
        self.enqueued_callbacks = []
        self.synced_adapters = []
        self.sync_runtime_calls = []
        self.refresh_counter_calls = []
        self.toggle_calls = []
        self.random_ip_submission_calls = []
        self.start_init_gate_calls = []
        self.finish_initialization_calls = []
        self.build_logs = ["init-log"]
        self.ui_state = {"random_ip_enabled": False}

    def _build_adapter(self, *args, **kwargs):
        self.adapter_ctor_args = (args, kwargs)
        return _FakeAdapter()

    def _dispatch_to_ui_async(self, callback) -> None:
        self.dispatched_async.append(callback)
        callback()

    def _enqueue_ui_callback(self, callback) -> bool:
        self.enqueued_callbacks.append(callback)
        callback()
        return True

    def _sync_adapter_ui_bridge(self, adapter: Any = None) -> None:
        self.synced_adapters.append(adapter)

    def sync_runtime_ui_state_from_config(self, config: RuntimeConfig, *, emit: bool = True):
        self.sync_runtime_calls.append((config, emit))
        return {}, True

    def refresh_random_ip_counter(self, *, adapter: Any = None) -> None:
        self.refresh_counter_calls.append(adapter)

    def submit_toggle_random_ip(self, enabled: bool, *, adapter: Any = None) -> Any:
        self.toggle_calls.append((bool(enabled), adapter))
        future: Future[bool] = Future()
        future.set_result(bool(enabled))
        return future

    def handle_random_ip_submission(self, *, stop_signal=None, adapter: Any = None) -> None:
        self.random_ip_submission_calls.append((stop_signal, adapter))

    def _start_with_initialization_gate(self, config: RuntimeConfig, proxy_pool) -> None:
        self.start_init_gate_calls.append((config, list(proxy_pool)))

    def _prepare_engine_state(self, proxy_pool):
        execution_config = SimpleNamespace(
            num_threads=3,
            proxy_pool=list(proxy_pool),
        )
        execution_state = _FakeExecutionState(target_num=12, num_threads=3)
        self.prepared_engine_state = (execution_config, execution_state)
        return execution_config, execution_state

    def _reset_initialization_state(self) -> None:
        return None

    def _finish_initialization_idle_state(self, status_text: str) -> None:
        self.finish_initialization_calls.append(str(status_text))

    def _build_initialization_logs(self):
        return list(self.build_logs)

    def _emit_quick_bug_report_suggestion_if_needed(self) -> None:
        return RunControllerExecutionMixin._emit_quick_bug_report_suggestion_if_needed(self)

    def get_runtime_ui_state(self):
        return dict(self.ui_state)


class RunControllerExecutionTests:
    def test_create_adapter_binds_callbacks_and_random_ip_state(self) -> None:
        controller = _DummyExecutionController()
        stop_signal = threading.Event()
        controller.ui_state["random_ip_enabled"] = True
        adapter = controller._create_adapter(stop_signal, random_ip_enabled=True)

        assert isinstance(adapter, _FakeAdapter)
        assert adapter.random_ip_enabled is True
        assert controller.synced_adapters == [adapter]
        adapter.runtime_actions_bound["refresh_random_ip_counter"]()
        adapter.runtime_actions_bound["handle_random_ip_submission"]("stop")
        result = adapter.runtime_actions_bound["toggle_random_ip"](None)
        assert controller.refresh_counter_calls == [adapter]
        assert controller.random_ip_submission_calls == [("stop", adapter)]
        assert result is True

    def test_start_run_handles_duplicate_start_and_preparation_failure(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        controller.running = True
        controller.start_run(RuntimeConfig())
        assert controller.runFailed.calls == []

        controller.running = False

        prep_error = controller_module.RuntimePreparationError(
            "用户提示",
            log_message="日志提示",
            detailed=False,
        )
        monkeypatch.setattr(controller_module, "prepare_execution_artifacts", lambda *_args, **_kwargs: (_ for _ in ()).throw(prep_error))
        controller.start_run(RuntimeConfig())
        assert controller.runFailed.calls == [("用户提示",)]

    def test_start_run_stores_prepared_state_and_starts_gate(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        cfg = RuntimeConfig()
        cfg.target = 9
        cfg.threads = 4
        cfg.random_ip_enabled = True
        prepared = PreparedExecutionArtifacts(
            execution_config_template=SimpleNamespace(),
            survey_provider="wjx",
            question_entries=["q1"],
            questions_info=["info1"],
            reverse_fill_spec=None,
        )
        monkeypatch.setattr(controller_module, "prepare_execution_artifacts", lambda *_args, **_kwargs: prepared)

        controller.start_run(cfg)

        assert controller.config is cfg
        assert controller.survey_provider == "wjx"
        assert controller.question_entries == ["q1"]
        assert controller.questions_info == ["info1"]
        assert controller._prepared_execution_artifacts is prepared
        assert controller._starting is True
        assert controller._initializing is False
        assert controller.start_init_gate_calls == [(cfg, [])]

    def test_start_workers_with_proxy_pool_starts_engine_and_monitor(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        spawned = []

        class _SpawnedThread:
            def __init__(self, *, target=None, args=(), daemon=False, name="") -> None:
                self.target = target
                self.args = args
                self.daemon = daemon
                self.name = name
                self.started = False
                spawned.append(self)

            def start(self) -> None:
                self.started = True

        fake_runtime_thread = _SpawnedThread(name="Runtime")
        controller._async_engine_client.thread = fake_runtime_thread
        monkeypatch.setattr(controller_module.threading, "Thread", _SpawnedThread)
        controller._start_workers_with_proxy_pool(RuntimeConfig(), ["proxy-a"], emit_run_state=True)

        execution_config, execution_state = controller.prepared_engine_state
        assert execution_state.ensure_calls == [(3, "Slot")]
        assert execution_state.reverse_fill_init_calls == 1
        assert controller._execution_state is execution_state
        assert controller.adapter.execution_state is execution_state
        assert controller.running is True
        assert controller._starting is False
        assert controller.runStateChanged.calls == [(True,)]
        assert controller._status_timer.started == 1
        assert controller._async_engine_client.start_calls[0][0] is execution_config
        assert controller.worker_threads == [fake_runtime_thread]
        assert len(spawned) == 2
        assert spawned[-1].name == "Monitor"
        assert spawned[-1].started is True

    def test_start_workers_starts_engine_directly_without_ui_proxy_prefetch_thread(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        config = RuntimeConfig()
        events: list[str] = []

        def fake_start_run(*_args, **_kwargs):
            events.append("engine")
            return _FakeRunFuture()

        class _SpawnedThread:
            def __init__(self, *, target=None, args=(), daemon=False, name="") -> None:
                self.name = name
                self.started = False

            def start(self) -> None:
                self.started = True

        monkeypatch.setattr(controller._async_engine_client, "start_run", fake_start_run)
        monkeypatch.setattr(controller_module.threading, "Thread", _SpawnedThread)

        controller._start_workers_with_proxy_pool(config, [], emit_run_state=False)

        assert events == ["engine"]

    def test_wait_for_async_run_and_wait_for_threads_cleanup_monitor(self) -> None:
        controller = _DummyExecutionController()
        thread1 = _FakeThread(alive=True, name="A")
        thread2 = _FakeThread(alive=True, name="B")
        controller.worker_threads = [thread1, thread2]
        controller._monitor_thread = object()
        finished = []
        controller._on_run_finished = lambda adapter=None: finished.append(adapter)

        controller._wait_for_threads("adapter-a")
        assert thread1.join_calls == [None]
        assert thread2.join_calls == [None]
        assert finished == ["adapter-a"]
        assert controller._monitor_thread is None

        controller._monitor_thread = object()
        run_future = _FakeRunFuture(exc=RuntimeError("boom"))
        controller._wait_for_async_run(run_future, "adapter-b")
        assert controller.runFailed.calls == [("后台运行内核异常退出，请查看日志",)]
        assert finished[-1] == "adapter-b"
        assert controller._monitor_thread is None

    def test_on_run_finished_main_thread_path_and_background_handoff(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        cleanup = []
        controller._schedule_cleanup = lambda adapter=None: cleanup.append(adapter)
        controller._emit_status = lambda: cleanup.append("status")
        controller._execution_state = _FakeExecutionState()
        controller.running = True
        controller._stopping = True
        controller._initializing = False

        monkeypatch.setattr(controller_module.threading, "current_thread", lambda: controller_module.threading.main_thread())
        controller._on_run_finished("adapter-a")
        assert cleanup == ["adapter-a", "status"]
        assert controller._status_timer.stopped == 1
        assert controller._sleep_blocker.released == 1
        assert controller.running is False
        assert controller.runStateChanged.calls == [(False,)]

        controller2 = _DummyExecutionController()
        dispatched = []
        controller2._dispatch_to_ui_async = lambda callback: dispatched.append(callback)
        monkeypatch.setattr(controller_module.threading, "current_thread", lambda: object())
        monkeypatch.setattr(controller_module.threading, "main_thread", lambda: "main")
        controller2._on_run_finished("adapter-b")
        assert len(dispatched) == 1

    def test_submit_cleanup_and_schedule_cleanup(self) -> None:
        controller = _DummyExecutionController()
        controller._submit_cleanup_task(None, delay_seconds=1.5)
        callback, delay = controller._cleanup_runner.calls[-1]
        assert delay == 1.5
        callback()
        assert controller.adapter.cleanup_calls == 1
        assert controller.cleanupFinished.calls == [()]

        controller._cleanup_runner.calls.clear()
        controller._cleanup_scheduled = False
        controller._schedule_cleanup()
        assert len(controller._cleanup_runner.calls) == 1
        controller._schedule_cleanup()
        assert len(controller._cleanup_runner.calls) == 1

    def test_stop_run_covers_starting_initializing_and_running_paths(self) -> None:
        controller = _DummyExecutionController()
        controller._execution_state = _FakeExecutionState()
        controller._starting = True
        controller.running = False
        gate_stop = threading.Event()
        controller._init_gate_stop_event = gate_stop
        controller.stop_run()
        assert controller.stop_event.is_set()
        assert gate_stop.is_set()
        assert controller._prepared_execution_artifacts is None
        assert controller._starting is False
        assert controller._execution_state.mark_terminal_stop_calls[0][0] == "user_stopped"

        controller = _DummyExecutionController()
        controller._execution_state = _FakeExecutionState()
        controller.running = True
        controller._initializing = True
        controller.stop_run()
        assert controller.finish_initialization_calls == ["已停止"]

        controller = _DummyExecutionController()
        controller._execution_state = _FakeExecutionState()
        controller.running = True
        controller._paused_state = True
        statuses = []
        controller._emit_status = lambda: statuses.append("emit")
        cleanup = []
        controller._schedule_cleanup = lambda adapter=None: cleanup.append(adapter)
        controller.stop_run()
        assert controller._async_engine_client.stop_calls == 1
        assert controller._async_engine_client.resume_calls == 1
        assert controller.adapter.resume_calls == 1
        assert controller._status_timer.stopped == 1
        assert cleanup == [None]
        assert controller.pauseStateChanged.calls == [(False, "")]
        assert controller._stopping is True
        assert controller._stopped_by_stop_run is True
        assert statuses == ["emit"]

    def test_collect_shutdown_threads_and_shutdown_for_close(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        init_thread = _FakeThread(alive=True, name="init")
        worker_thread = _FakeThread(alive=True, name="worker")
        monitor_thread = _FakeThread(alive=True, name="monitor")
        controller._init_gate_thread = init_thread
        controller.worker_threads = [worker_thread, worker_thread]
        controller._monitor_thread = monitor_thread
        threads = controller._collect_shutdown_threads()
        assert threads == [init_thread, worker_thread, monitor_thread]

        controller = _DummyExecutionController()
        controller.adapter = _FakeAdapter()
        controller._async_engine_client = _FakeEngineClient()
        controller.worker_threads = [_FakeThread(alive=True, name="worker")]
        controller._monitor_thread = _FakeThread(alive=False, name="monitor")
        controller._init_gate_thread = _FakeThread(alive=False, name="init")
        stop_calls = []
        controller.stop_run = lambda: stop_calls.append("stop")
        process_calls = []
        monkeypatch.setattr(controller_module.QCoreApplication, "instance", lambda: SimpleNamespace(processEvents=lambda: process_calls.append("events")))
        monkeypatch.setattr(controller_module.threading, "current_thread", controller_module.threading.main_thread)
        assert controller.shutdown_for_close(timeout_seconds=0.2) is True
        assert stop_calls == ["stop"]
        assert controller.adapter.cleanup_calls == 1
        assert controller._async_engine_client.shutdown_calls
        assert controller.worker_threads == []
        assert controller._monitor_thread is None
        assert controller._init_gate_thread is None
        assert process_calls

    def test_request_shutdown_for_close_and_bug_report_suggestion_logic(self, monkeypatch) -> None:
        controller = _DummyExecutionController()
        started = []
        original_current_thread = controller_module.threading.current_thread

        class _SpawnedThread:
            current_instance = None

            def __init__(self, *, target=None, daemon=False, name="") -> None:
                self.target = target
                self.daemon = daemon
                self.name = name
                self.started = False
                self._alive = False

            def is_alive(self) -> bool:
                return self._alive

            def start(self) -> None:
                self.started = True
                self._alive = True
                started.append(self)
                _SpawnedThread.current_instance = self
                try:
                    self.target()
                finally:
                    self._alive = False
                    _SpawnedThread.current_instance = None

        monkeypatch.setattr(controller_module.threading, "Thread", _SpawnedThread)
        monkeypatch.setattr(
            controller_module.threading,
            "current_thread",
            lambda: _SpawnedThread.current_instance or original_current_thread(),
        )
        shutdown_calls = []
        controller.shutdown_for_close = lambda timeout_seconds=5.0: shutdown_calls.append(timeout_seconds) or True
        controller.request_shutdown_for_close(timeout_seconds=1.2)
        assert shutdown_calls == [1.2]
        assert controller._close_shutdown_thread is None

        controller._execution_state = _FakeExecutionState()
        controller._execution_state.terminal_snapshot = ("free_ai_unstable", "", "")
        controller._emit_quick_bug_report_suggestion_if_needed()
        assert controller.freeAiUnstableSuggested.calls == [()]

        controller = _DummyExecutionController()
        controller._execution_state = _FakeExecutionState()
        controller._execution_state.terminal_snapshot = ("runtime_failed", "other", "msg")
        controller._emit_quick_bug_report_suggestion_if_needed()
        assert controller.quickBugReportSuggested.calls == [()]

    def test_resume_run_and_emit_status(self) -> None:
        controller = _DummyExecutionController()
        controller.resume_run()
        assert controller._async_engine_client.resume_calls == 0

        controller.running = True
        controller._paused_state = True
        controller.resume_run()
        assert controller._async_engine_client.resume_calls == 1
        assert controller.adapter.resume_calls == 1
        assert controller.pauseStateChanged.calls == [(False, "")]

        controller = _DummyExecutionController()
        controller._initializing = True
        controller._paused_state = True
        controller._emit_status()
        assert controller.statusUpdated.calls == [("正在初始化", 0, 0)]
        assert controller.threadProgressUpdated.calls[-1][0]["initializing"] is True
        assert controller.pauseStateChanged.calls == [(False, "")]

        controller = _DummyExecutionController()
        ctx = _FakeExecutionState(target_num=10, num_threads=3)
        ctx.cur_num = 8
        ctx.cur_fail = 2
        ctx.device_quota_fail_count = 1
        ctx.terminal_snapshot = ("user_stopped", "", "")
        controller._execution_state = ctx
        controller.adapter.paused = True
        controller.adapter.pause_reason = "风控"
        controller.running = False
        controller._emit_status()
        status_text = controller.statusUpdated.calls[-1][0]
        assert "已暂停 8/10 份" in status_text
        assert "设备限制拦截 1 次" in status_text
        assert "风控" in status_text
        assert controller.threadProgressUpdated.calls[-1][0]["per_thread_target"] == 4
        assert controller.pauseStateChanged.calls == [(True, "风控")]

        controller = _DummyExecutionController()
        ctx = _FakeExecutionState(target_num=5, num_threads=2)
        ctx.cur_num = 5
        controller._execution_state = ctx
        scheduled = []
        controller._schedule_cleanup = lambda adapter=None: scheduled.append(adapter)
        controller._emit_status()
        assert scheduled == [None]
        assert controller._completion_cleanup_done is True

