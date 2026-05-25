from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from software.core.ai.runtime import AIRuntimeError
from software.core.engine.async_events import AsyncRunContext
from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ExecutionState
import software.core.engine.async_runtime_loop as runtime_loop
from software.network.browser import ProxyConnectionError
from software.network.browser.async_owner_pool import _route_runtime_resource
from software.network.browser.startup import BrowserStartupErrorInfo, BrowserStartupRuntimeError
from software.providers.contracts import SurveyQuestionMeta


class _FakeScheduler:
    def __init__(self, acquire_values=None) -> None:
        self.acquire_values = list(acquire_values or [1])
        self.release_calls: list[dict[str, object]] = []

    async def acquire(self):
        if not self.acquire_values:
            return None
        return self.acquire_values.pop(0)

    async def release(self, token_id, **kwargs):
        self.release_calls.append({"token_id": token_id, **kwargs})
        return None


class _FakeSession:
    def __init__(self, driver=None) -> None:
        self.driver = driver or SimpleNamespace()
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _FakeBrowserPool:
    def __init__(self, session=None) -> None:
        self.session = session or _FakeSession()
        self.open_calls: list[dict[str, object]] = []
        self.ensure_ready_calls = 0

    async def open_session(self, **kwargs):
        self.open_calls.append(kwargs)
        return self.session

    async def ensure_ready(self):
        self.ensure_ready_calls += 1
        return "edge"


class _FakeStopPolicy:
    def __init__(self, state: ExecutionState | None = None) -> None:
        self.state = state
        self.failure_calls: list[dict[str, object]] = []
        self.success_calls: list[dict[str, object]] = []
        self.proxy_threshold = 3

    def record_failure(self, stop_signal, **kwargs):
        self.failure_calls.append({"stop_signal": stop_signal, **kwargs})
        return bool(kwargs.get("threshold_override") == 1 or kwargs.get("failure_reason") == FailureReason.DEVICE_QUOTA_LIMIT)

    def record_success(self, stop_signal, **kwargs):
        self.success_calls.append({"stop_signal": stop_signal, **kwargs})
        return False

    def trigger_target_reached_stop(self, stop_signal):
        if self.state is not None:
            self.state.mark_terminal_stop("target_reached", message="目标份数已达成")
        stop_signal.set()

    def proxy_unavailable_threshold(self):
        return self.proxy_threshold


def _build_runner(*, config: ExecutionConfig | None = None, state: ExecutionState | None = None, stop_set: bool = False):
    loop = asyncio.get_running_loop()
    config = config or ExecutionConfig(target_num=3, submit_interval_range_seconds=[1, 3], survey_provider="wjx")
    state = state or ExecutionState(config=config)
    state.update_thread_status = lambda *_args, **_kwargs: None
    state.update_thread_step = lambda *_args, **_kwargs: None
    stop_event = asyncio.Event()
    if stop_set:
        stop_event.set()
    run_context = AsyncRunContext(
        state=state,
        stop_event=stop_event,
        pause_event=asyncio.Event(),
    )
    scheduler = _FakeScheduler()
    runner = AsyncSlotRunner(
        slot_id=1,
        config=config,
        state=state,
        run_context=run_context,
        scheduler=scheduler,
        browser_pool=_FakeBrowserPool(),
        gui_instance=SimpleNamespace(active_drivers=[]),
    )
    runner.stop_policy = _FakeStopPolicy(state)
    runner.submission_service = SimpleNamespace(finalize_after_submit=lambda *_args, **_kwargs: None)
    return runner, state, run_context, loop, scheduler


class AsyncRuntimeLoopLargeTests:
    @pytest.mark.asyncio
    async def test_should_stop_loop_honors_stop_event(self) -> None:
        runner, _state, _ctx, _loop, _scheduler = _build_runner(stop_set=True)

        assert await runner._should_stop_loop() is True

    @pytest.mark.asyncio
    async def test_should_stop_loop_honors_target_num(self) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config, cur_num=2)
        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert await runner._should_stop_loop() is True

    @pytest.mark.asyncio
    async def test_sleep_or_stop_handles_zero_delay_and_timeout(self) -> None:
        runner, _state, _ctx, _loop, _scheduler = _build_runner()

        assert await runner._sleep_or_stop(0) is False
        assert await runner._sleep_or_stop(0.001) is False

    @pytest.mark.asyncio
    async def test_resolve_dispatch_delay_seconds_covers_zero_fixed_and_random(self, monkeypatch) -> None:
        config = ExecutionConfig(submit_interval_range_seconds=[0, 0], survey_provider="wjx")
        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config)
        assert runner._resolve_dispatch_delay_seconds() == 0.0

        config.submit_interval_range_seconds = [2, 2]
        assert runner._resolve_dispatch_delay_seconds() == 2.0

        config.submit_interval_range_seconds = [1, 3]
        monkeypatch.setattr(runtime_loop.random, "uniform", lambda _a, _b: 2.5)
        assert runner._resolve_dispatch_delay_seconds() == 2.5

    @pytest.mark.asyncio
    async def test_prepare_round_context_returns_false_when_stop_requested(self) -> None:
        runner, _state, ctx, _loop, _scheduler = _build_runner(stop_set=True)

        assert await runner._prepare_round_context() is False
        assert ctx.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_prepare_round_context_waits_for_joint_sample_then_acquires_reverse_fill(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        statuses = iter(["acquired", "acquired"])
        reserve_values = iter([None, 0])
        released: list[str] = []
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: next(reserve_values)
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(
            status=next(statuses),
            sample=SimpleNamespace(data_row_number=1, worksheet_row_number=2),
        )
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: released.append("reverse")
        monkeypatch.setattr(runtime_loop, "ensure_joint_psychometric_answer_plan", lambda _config: SimpleNamespace(sample_count=2))
        real_sleep = asyncio.sleep
        monkeypatch.setattr(runtime_loop.asyncio, "sleep", lambda _seconds: real_sleep(0))
        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert await runner._prepare_round_context() is True
        assert released == ["reverse"]

    @pytest.mark.asyncio
    async def test_prepare_round_context_finishes_idle_slot_when_joint_slots_allocated(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: None
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(
            status="acquired",
            sample=SimpleNamespace(data_row_number=1, worksheet_row_number=2),
        )
        state.is_joint_sample_quota_exhausted = lambda *_args, **_kwargs: False
        expire_calls: list[str] = []
        state.expire_stale_joint_sample_reservations = lambda *_args, **_kwargs: expire_calls.append("expire") or 0
        released: list[bool] = []
        state.release_reverse_fill_sample = lambda *_args, **kwargs: released.append(bool(kwargs.get("requeue")))
        terminal: list[tuple[str, str]] = []
        state.mark_terminal_stop = lambda category, *, message, **_kwargs: terminal.append((category, message))
        monkeypatch.setattr(runtime_loop, "ensure_joint_psychometric_answer_plan", lambda _config: SimpleNamespace(sample_count=2))
        real_sleep = asyncio.sleep
        sleep_calls = 0

        async def fake_sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                ctx.stop_event.set()
            await real_sleep(0)

        monkeypatch.setattr(runtime_loop.asyncio, "sleep", fake_sleep)
        runner, _state, ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert await runner._prepare_round_context() is False
        assert released == [True, True]
        assert terminal == []
        assert expire_calls == ["expire", "expire"]
        assert ctx.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_prepare_round_context_stops_when_joint_slots_exhausted(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: None
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(status="waiting", sample=None)
        state.is_joint_sample_quota_exhausted = lambda *_args, **_kwargs: True
        terminal: list[tuple[str, str]] = []
        state.mark_terminal_stop = lambda category, *, message, **_kwargs: terminal.append((category, message))
        monkeypatch.setattr(runtime_loop, "ensure_joint_psychometric_answer_plan", lambda _config: SimpleNamespace(sample_count=2))
        runner, _state, ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert await runner._prepare_round_context() is False
        assert terminal == [("target_reached", "联合信效度样本槽位已全部完成")]
        assert ctx.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_prepare_round_context_stops_when_target_already_reached_while_waiting_joint_slot(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=11, survey_provider="wjx")
        state = ExecutionState(config=config, cur_num=11)
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: None
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(status="acquired", sample=SimpleNamespace())
        monkeypatch.setattr(runtime_loop, "ensure_joint_psychometric_answer_plan", lambda _config: SimpleNamespace(sample_count=11))
        runner, _state, ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert await runner._prepare_round_context() is False
        assert state.get_terminal_stop_snapshot()[0] == "target_reached"
        await asyncio.sleep(0)
        assert ctx.stop_event.is_set()
        assert runner._resolve_finished_status_text() == "已完成"

    @pytest.mark.asyncio
    async def test_prepare_round_context_marks_terminal_stop_when_reverse_fill_exhausted(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: 0
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(status="exhausted", sample=None)
        terminal: list[tuple[str, str, str]] = []
        state.mark_terminal_stop = lambda category, *, failure_reason, message: terminal.append((category, failure_reason, message))
        state.release_joint_sample = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runtime_loop, "ensure_joint_psychometric_answer_plan", lambda _config: SimpleNamespace(sample_count=2))
        runner, _state, ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert await runner._prepare_round_context() is False
        assert terminal[0][0] == "reverse_fill_exhausted"
        assert ctx.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_select_session_proxy_and_ua_handles_unresponsive_proxy(self, monkeypatch) -> None:
        config = ExecutionConfig(random_proxy_ip_enabled=True, survey_provider="wjx")
        state = ExecutionState(config=config)
        released: list[str] = []
        state.release_proxy_in_use = lambda thread_name: released.append(thread_name)
        async def fake_select_proxy_for_session_async(*_args, **_kwargs):
            return "http://1.1.1.1:80"
        monkeypatch.setattr(runtime_loop, "_select_proxy_for_session_async", fake_select_proxy_for_session_async)
        monkeypatch.setattr(runtime_loop, "_record_bad_proxy_and_maybe_pause", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(runtime_loop, "is_proxy_responsive_async", lambda proxy: asyncio.sleep(0, result=False))
        monkeypatch.setattr(runtime_loop, "_discard_unresponsive_proxy", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime_loop, "_select_user_agent_for_session", lambda *_args, **_kwargs: ("UA", None))
        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        proxy, ua = await runner._select_session_proxy_and_ua()
        assert (proxy, ua) == (None, None)
        assert released == ["Slot-1"]

    @pytest.mark.asyncio
    async def test_open_session_sets_driver_metadata(self, monkeypatch) -> None:
        session = _FakeSession(driver=SimpleNamespace())
        browser_pool = _FakeBrowserPool(session=session)
        runner, state, _ctx, _loop, _scheduler = _build_runner()
        runner.browser_pool = browser_pool
        async def fake_select_session_proxy_and_ua():
            return ("http://1.1.1.1:80", "UA")
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", fake_select_session_proxy_and_ua)

        opened = await runner._open_session()
        assert opened is session
        assert browser_pool.ensure_ready_calls == 0
        assert session.driver.thread_name == "Slot-1"
        assert session.driver.session_state is state
        assert session.driver.session_proxy_address == "http://1.1.1.1:80"

    @pytest.mark.asyncio
    async def test_close_session_releases_proxy_and_resets_address(self) -> None:
        runner, state, _ctx, _loop, _scheduler = _build_runner()
        released: list[str] = []
        state.release_proxy_in_use = lambda thread_name: released.append(thread_name)
        runner.proxy_address = "http://1.1.1.1:80"
        session = _FakeSession()

        await runner._close_session(session)
        assert session.close_calls == 1
        assert released == ["Slot-1"]
        assert runner.proxy_address is None

    @pytest.mark.asyncio
    async def test_load_survey_or_record_failure_covers_timed_mode_and_normal_failure(self, monkeypatch) -> None:
        config = ExecutionConfig(timed_mode_enabled=True, survey_provider="wjx")
        runner, _state, ctx, _loop, _scheduler = _build_runner(config=config)
        session = _FakeSession(driver=SimpleNamespace())

        monkeypatch.setattr(asyncio, "to_thread", lambda func, *args, **kwargs: asyncio.sleep(0, result=func(*args, **kwargs)))
        monkeypatch.setattr(runtime_loop.timed_mode, "wait_until_open", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        assert await runner._load_survey_or_record_failure(session) is True

        config.timed_mode_enabled = False
        monkeypatch.setattr(runtime_loop, "_load_survey_page", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(runtime_loop, "_page_load_exception_summary", lambda exc: f"summary:{exc}")
        assert await runner._load_survey_or_record_failure(session) is False
        assert runner.stop_policy.failure_calls[-1]["failure_reason"] == FailureReason.PAGE_LOAD_FAILED
        assert not ctx.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_handle_device_quota_limit_updates_status_and_optional_gui_handler(self, monkeypatch) -> None:
        config = ExecutionConfig(random_proxy_ip_enabled=True, survey_provider="wjx")
        gui_calls: list[object] = []
        runner, _state, ctx, _loop, _scheduler = _build_runner(config=config)
        runner.gui_instance = SimpleNamespace(handle_random_ip_submission=lambda stop_signal: gui_calls.append(stop_signal))
        monkeypatch.setattr(runtime_loop, "_provider_is_device_quota_limit_page", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))

        assert await runner._handle_device_quota_limit(_FakeSession()) is True
        assert ctx.stop_event.is_set()
        assert gui_calls == []

        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config)
        runner.stop_policy = _FakeStopPolicy()
        runner.stop_policy.record_failure = lambda *_args, **_kwargs: False
        runner.gui_instance = SimpleNamespace(handle_random_ip_submission=lambda stop_signal: gui_calls.append(stop_signal))
        monkeypatch.setattr(runtime_loop, "_provider_is_device_quota_limit_page", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        assert await runner._handle_device_quota_limit(_FakeSession()) is True
        assert len(gui_calls) >= 1

    @pytest.mark.asyncio
    async def test_wait_for_next_unique_proxy_and_handle_proxy_unavailable(self, monkeypatch) -> None:
        config = ExecutionConfig(random_proxy_ip_enabled=True, fail_threshold=2, num_threads=4, survey_provider="wjx")
        state = ExecutionState(config=config)
        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config, state=state)
        state.wait_for_runtime_change = lambda **_kwargs: False

        assert await runner._wait_for_next_unique_proxy() is True
        assert runner._handle_proxy_unavailable(status_text="代理不可用", log_message="bad proxy") is False

        runner.stop_policy.proxy_threshold = 1
        assert runner._handle_proxy_unavailable(status_text="代理不可用", log_message="bad proxy") is True

    @pytest.mark.asyncio
    async def test_handle_proxy_connection_error_and_ai_runtime_error_delegate_to_handlers(self, monkeypatch) -> None:
        runner, _state, _ctx, _loop, _scheduler = _build_runner()
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            runtime_loop,
            "_handle_proxy_connection_error_impl",
            lambda holder, *_args, **_kwargs: captured.setdefault("proxy", holder.proxy_address) or True,
        )
        runner.proxy_address = "http://1.1.1.1:80"
        assert runner._handle_proxy_connection_error(None) == "http://1.1.1.1:80"

        monkeypatch.setattr(runtime_loop, "_handle_ai_runtime_error_impl", lambda exc, *_args, **_kwargs: str(exc) == "ai boom")
        assert await runner._handle_ai_runtime_error(AIRuntimeError("ai boom")) is True

    @pytest.mark.asyncio
    async def test_run_finishes_cleanly_when_scheduler_returns_none(self) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [None]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        finished: list[tuple[str, str]] = []
        state.mark_thread_finished = lambda thread_name, *, status_text: finished.append((thread_name, status_text))

        await runner.run()

        assert scheduler.release_calls == []
        assert finished == [("Slot-1", "已停止")]

    @pytest.mark.asyncio
    async def test_uses_http_runtime_respects_logic_parse_status(self) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        config.questions_metadata = {
            1: SurveyQuestionMeta(
                num=1,
                title="Q1",
                has_jump=True,
                logic_parse_status="complete",
                jump_rules=[{"option_index": 0, "jumpto": 2}],
            ),
            2: SurveyQuestionMeta(num=2, title="Q2"),
        }
        state = ExecutionState(config=config)
        runner, _state, _ctx, _loop, _scheduler = _build_runner(config=config, state=state)

        assert runner._uses_http_runtime() is True

        config.questions_metadata = {
            1: SurveyQuestionMeta(num=1, title="Q1", has_jump=True, logic_parse_status="unknown"),
            2: SurveyQuestionMeta(num=2, title="Q2"),
        }

        assert runner._uses_http_runtime() is False

    @pytest.mark.asyncio
    async def test_run_marks_thread_completed_when_target_reached(self) -> None:
        runner, state, ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [None]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_terminal_stop("target_reached", message="目标份数已达成")
        ctx.stop_event.set()
        finished: list[tuple[str, str]] = []
        state.mark_thread_finished = lambda thread_name, *, status_text: finished.append((thread_name, status_text))

        await runner.run()

        assert finished == [("Slot-1", "已完成")]

    @pytest.mark.asyncio
    async def test_run_requeues_when_joint_pre_answer_step_times_out(self, monkeypatch) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [8, None]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))

        async def fake_open_session():
            runner._joint_pre_answer_timed_out = True
            return None

        monkeypatch.setattr(runner, "_open_session", fake_open_session)

        await runner.run()

        assert scheduler.release_calls[0]["token_id"] == 8
        assert scheduler.release_calls[0]["requeue"] is True
        assert scheduler.release_calls[0]["delay_seconds"] == runtime_loop.JOINT_PRE_ANSWER_ATTEMPT_REQUEUE_DELAY_SECONDS

    @pytest.mark.asyncio
    async def test_run_success_path_requeues_scheduler_with_delay(self, monkeypatch) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [7, None]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runtime_loop, "fill_survey", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        session = _FakeSession(driver=SimpleNamespace())
        monkeypatch.setattr(runner, "_open_session", lambda: asyncio.sleep(0, result=session))
        monkeypatch.setattr(runner, "_load_survey_or_record_failure", lambda _session: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_handle_device_quota_limit", lambda _session: asyncio.sleep(0, result=False))
        monkeypatch.setattr(runner, "_finalize_after_submit", lambda _session: asyncio.sleep(0, result=SimpleNamespace(status="success", should_rotate_proxy=False, should_stop=False)))
        monkeypatch.setattr(runner, "_resolve_dispatch_delay_seconds", lambda: 1.5)

        await runner.run()

        assert scheduler.release_calls[0]["token_id"] == 7
        assert scheduler.release_calls[0]["requeue"] is True
        assert scheduler.release_calls[0]["delay_seconds"] == 1.5
        assert session.close_calls == 1

    @pytest.mark.asyncio
    async def test_run_no_submit_path_skips_finalize_after_submit(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=1, submit_enabled=False, survey_provider="wjx")
        runner, state, _ctx, _loop, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [7]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runtime_loop, "fill_survey", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        session = _FakeSession(driver=SimpleNamespace())
        monkeypatch.setattr(runner, "_open_session", lambda: asyncio.sleep(0, result=session))
        monkeypatch.setattr(runner, "_load_survey_or_record_failure", lambda _session: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_handle_device_quota_limit", lambda _session: asyncio.sleep(0, result=False))
        success_calls: list[dict[str, object]] = []
        runner.stop_policy.record_success = lambda stop_signal, **kwargs: success_calls.append({"stop_signal": stop_signal, **kwargs}) or True

        async def fail_finalize(_session):
            raise AssertionError("不提交单测不应进入提交收尾")

        monkeypatch.setattr(runner, "_finalize_after_submit", fail_finalize)

        await runner.run()

        assert success_calls[0]["status_text"] == "单测完成"
        assert scheduler.release_calls[0]["requeue"] is False
        assert session.close_calls == 0

    @pytest.mark.asyncio
    async def test_run_aborted_finalize_breaks_without_requeue(self, monkeypatch) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [3]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runtime_loop, "fill_survey", lambda *_args, **_kwargs: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_open_session", lambda: asyncio.sleep(0, result=_FakeSession(driver=SimpleNamespace())))
        monkeypatch.setattr(runner, "_load_survey_or_record_failure", lambda _session: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_handle_device_quota_limit", lambda _session: asyncio.sleep(0, result=False))
        release_flags: list[bool] = []
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))
        monkeypatch.setattr(runner, "_finalize_after_submit", lambda _session: asyncio.sleep(0, result=SimpleNamespace(status="aborted", should_rotate_proxy=False, should_stop=True)))

        await runner.run()

        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is False

    @pytest.mark.asyncio
    async def test_run_airuntime_error_releases_resources_and_requeues(self, monkeypatch) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [5, None]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runtime_loop, "fill_survey", lambda *_args, **_kwargs: (_ for _ in ()).throw(AIRuntimeError("ai bad")))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_open_session", lambda: asyncio.sleep(0, result=_FakeSession(driver=SimpleNamespace())))
        monkeypatch.setattr(runner, "_load_survey_or_record_failure", lambda _session: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_handle_device_quota_limit", lambda _session: asyncio.sleep(0, result=False))
        monkeypatch.setattr(runner, "_handle_ai_runtime_error", lambda exc: asyncio.sleep(0, result=False))
        release_flags: list[bool] = []
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))

        await runner.run()

        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True

    @pytest.mark.asyncio
    async def test_run_proxy_connection_error_breaks_when_handler_requests_stop(self, monkeypatch) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [9]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_open_session", lambda: asyncio.sleep(0, result=_FakeSession(driver=SimpleNamespace())))
        monkeypatch.setattr(runner, "_load_survey_or_record_failure", lambda _session: (_ for _ in ()).throw(ProxyConnectionError("proxy bad")))
        monkeypatch.setattr(runner, "_handle_proxy_connection_error", lambda _session: True)

        await runner.run()

        assert scheduler.release_calls[0]["requeue"] is False

    @pytest.mark.asyncio
    async def test_run_browser_startup_error_stops_without_requeue(self, monkeypatch) -> None:
        runner, state, ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [12]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        exc = BrowserStartupRuntimeError(
            "AsyncBrowserOwner 无法启动 Microsoft Edge: driver closed",
            info=BrowserStartupErrorInfo("launch_failed", "driver closed", False),
        )
        monkeypatch.setattr(runner, "_open_session", lambda: (_ for _ in ()).throw(exc))
        release_flags: list[bool] = []
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))

        await runner.run()

        assert ctx.stop_event.is_set()
        assert scheduler.release_calls[0]["requeue"] is False
        assert state.get_terminal_stop_snapshot()[0] == "browser_start_failed"
        assert release_flags == []

    @pytest.mark.asyncio
    async def test_run_generic_exception_records_failure_and_requeues(self, monkeypatch) -> None:
        runner, state, _ctx, _loop, scheduler = _build_runner()
        scheduler.acquire_values = [11, None]
        state.release_joint_sample = lambda *_args, **_kwargs: None
        state.release_reverse_fill_sample = lambda *_args, **_kwargs: None
        state.mark_thread_finished = lambda *_args, **_kwargs: None
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        release_flags: list[bool] = []
        logged: list[str] = []
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))
        runner.stop_policy.record_failure = lambda *_args, **_kwargs: False
        monkeypatch.setattr(runtime_loop.logging, "exception", lambda message, *args, **_kwargs: logged.append(message % args))

        await runner.run()

        assert logged == ["异步会话[Slot-1]运行异常"]
        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True


class AsyncOwnerPoolLargeTests:
    @pytest.mark.asyncio
    async def test_route_runtime_resource_passes_through_processjq_and_aborts_heavy_assets(self) -> None:
        actions: list[str] = []

        class _Route:
            async def abort(self):
                actions.append("abort")

            async def continue_(self):
                actions.append("continue")

            async def fallback(self):
                actions.append("fallback")

        await _route_runtime_resource(_Route(), SimpleNamespace(url="https://www.wjx.cn/joinnew/processjq.ashx?id=1", resource_type="xhr"))
        await _route_runtime_resource(_Route(), SimpleNamespace(url="https://example.com/logo.png", resource_type="image"))
        await _route_runtime_resource(_Route(), SimpleNamespace(url="https://hm.baidu.com/x.js", resource_type="script"))
        await _route_runtime_resource(_Route(), SimpleNamespace(url="https://example.com/app.js", resource_type="script"))

        assert actions == ["fallback", "abort", "abort", "fallback"]

    @pytest.mark.asyncio
    async def test_async_browser_owner_pool_retries_on_disconnected_owner(self, monkeypatch) -> None:
        import software.network.browser.async_owner_pool as async_owner_pool_module
        from software.network.browser.async_owner_pool import AsyncBrowserOwnerPool, BrowserPoolConfig

        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=True,
        )
        disconnected = RuntimeError("Target page, context or browser has been closed")
        monkeypatch.setattr(pool._owners[0], "open_session", lambda **_kwargs: (_ for _ in ()).throw(disconnected))
        monkeypatch.setattr(pool._owners[1], "open_session", lambda **_kwargs: asyncio.sleep(0, result=SimpleNamespace(owner_id=2, browser_name="edge")))
        monkeypatch.setattr(async_owner_pool_module, "_is_browser_disconnected_error", lambda exc: "closed" in str(exc).lower())

        session = await pool.open_session(proxy_address=None, user_agent=None)
        assert session.owner_id == 2
