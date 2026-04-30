from __future__ import annotations

import unittest
from threading import Event, Lock
from unittest.mock import patch

from software.app.browser_probe import BrowserProbeResult
from software.core.task import ExecutionConfig
from software.io.config import RuntimeConfig
from software.providers.contracts import SurveyQuestionMeta
from software.ui.controller.run_controller_parts.runtime_init_gate import (
    RunControllerInitializationMixin,
    _extract_startup_service_warnings,
    _parse_status_page_monitor_names,
)
from software.ui.controller.run_controller_parts.runtime_preparation import PreparedExecutionArtifacts


class _DummyInitGate(RunControllerInitializationMixin):
    def __init__(self) -> None:
        self.stop_event = Event()
        self._initializing = True
        self._starting = True
        self.running = True
        self.worker_threads = [object()]
        self._execution_state = object()
        self._init_stage_text = "正在初始化"
        self._init_steps = [{"key": "playwright", "label": "初始化浏览器环境（快速检查）"}]
        self._init_completed_steps = {"playwright"}
        self._init_current_step_key = "playwright"
        self._init_gate_stop_event = Event()
        self._status_timer = _FakeTimer()
        self._prepared_execution_artifacts = None
        self._startup_status_check_lock = Lock()
        self._startup_status_check_active = False
        self._startup_service_warnings: list[str] = []
        self.started_workers: list[tuple[RuntimeConfig, list, bool]] = []
        self.dispatched_callbacks: list[object] = []
        self.emit_status_calls = 0
        self.startup_hint_events: list[tuple[str, str, int]] = []
        self.survey_title = "测试问卷"
        self.custom_confirm_dialog_handler = None
        self.confirm_dialog_handler = None
        self.run_state_events: list[bool] = []
        self.status_events: list[tuple[str, int, int]] = []
        self.thread_progress_events: list[dict] = []
        self.run_failed_events: list[str] = []
        self.runStateChanged = _FakeSignal(self.run_state_events)
        self.statusUpdated = _FakeSignal(self.status_events)
        self.threadProgressUpdated = _FakeSignal(self.thread_progress_events)
        self.runFailed = _FakeSignal(self.run_failed_events)
        self.startupHintEmitted = _FakeSignal(self.startup_hint_events)

    def _start_workers_with_proxy_pool(self, config: RuntimeConfig, proxy_pool: list, *, emit_run_state: bool = True) -> None:
        self.started_workers.append((config, list(proxy_pool), emit_run_state))

    def _emit_status(self) -> None:
        self.emit_status_calls += 1

    def _dispatch_to_ui_async(self, callback) -> None:
        self.dispatched_callbacks.append(callback)
        callback()


class _FakeSignal:
    def __init__(self, events: list) -> None:
        self.events = events

    def emit(self, *args) -> None:
        if len(args) == 1:
            self.events.append(args[0])
        else:
            self.events.append(args)


class _FakeTimer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeThread:
    def __init__(self, *, target=None, args=(), daemon: bool = False, name: str = "") -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self) -> None:
        self.started = True


class RuntimeInitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mixin = _DummyInitGate()

    def test_gate_only_enabled_for_headless_multi_thread(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2
        self.assertTrue(self.mixin._should_use_initialization_gate(config))

        config.threads = 1
        self.assertFalse(self.mixin._should_use_initialization_gate(config))

        config.headless_mode = False
        config.threads = 3
        self.assertFalse(self.mixin._should_use_initialization_gate(config))

    def test_initialization_plan_only_keeps_browser_quick_check(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2

        self.assertEqual(
            self.mixin._build_initialization_plan(config),
            [{"key": "playwright", "label": "初始化浏览器环境（快速检查）"}],
        )

        config.threads = 1
        self.assertEqual(self.mixin._build_initialization_plan(config), [])

    def test_cancel_initialization_resets_ui_to_idle_state(self) -> None:
        self.mixin._cancel_initialization_startup()

        self.assertFalse(self.mixin.running)
        self.assertFalse(self.mixin._starting)
        self.assertFalse(self.mixin._initializing)
        self.assertEqual(self.mixin.worker_threads, [])
        self.assertIsNone(self.mixin._execution_state)
        self.assertTrue(self.mixin._status_timer.stopped)
        self.assertEqual(self.mixin.run_state_events, [False])
        self.assertEqual(self.mixin.status_events, [("已取消启动", 0, 0)])
        self.assertEqual(
            self.mixin.thread_progress_events[-1],
            {
                "threads": [],
                "target": 0,
                "num_threads": 0,
                "per_thread_target": 0,
                "initializing": False,
            },
        )

    def test_parse_status_page_monitor_names_reads_public_group_monitors(self) -> None:
        payload = {
            "publicGroupList": [
                {
                    "monitorList": [
                        {"id": 12, "name": "随机ip提取"},
                        {"id": 13, "name": "免费AI填空"},
                    ]
                }
            ]
        }
        self.assertEqual(
            _parse_status_page_monitor_names(payload),
            {12: "随机ip提取", 13: "免费AI填空"},
        )

    def test_extract_startup_service_warnings_only_flags_non_ok_status(self) -> None:
        payload = {
            "heartbeatList": {
                "12": [{"status": 0, "msg": "接口超时", "time": "2026-04-23 11:00:00"}],
                "13": [{"status": 1, "msg": "", "time": "2026-04-23 11:00:30"}],
            }
        }
        warnings = _extract_startup_service_warnings(
            payload,
            {12: "随机IP提取", 13: "免费AI填空"},
            {12: "随机ip提取", 13: "免费AI填空"},
        )
        self.assertEqual(
            warnings,
            ["随机ip提取 当前状态异常（接口超时；最近时间：2026-04-23 11:00:00）"],
        )

    def test_build_initialization_logs_marks_stage_and_completion(self) -> None:
        self.mixin._init_stage_text = "正在检查浏览器"
        self.mixin._init_steps = [
            {"key": "probe", "label": "浏览器快检"},
            {"key": "warmup", "label": "预热"},
        ]
        self.mixin._init_completed_steps = {"probe"}
        self.mixin._init_current_step_key = "warmup"

        lines = self.mixin._build_initialization_logs()

        self.assertEqual(
            lines,
            ["当前阶段：正在检查浏览器", "[√] 浏览器快检", "[>] 预热"],
        )

    def test_build_browser_probe_failure_message_includes_warning_snapshot(self) -> None:
        self.mixin._startup_service_warnings = ["免费AI填空 当前状态异常"]

        message = self.mixin._build_browser_probe_failure_message(
            BrowserProbeResult(
                ok=False,
                browser="edge",
                message="启动失败",
                elapsed_ms=123,
            )
        )

        self.assertIn("启动失败", message)
        self.assertIn("检查耗时：123 ms", message)
        self.assertIn("已尝试浏览器：edge", message)
        self.assertIn("免费AI填空 当前状态异常", message)

    def test_start_with_initialization_gate_bypasses_gate_for_single_thread(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 1

        self.mixin._start_with_initialization_gate(config, proxy_pool=["proxy-a"])

        self.assertEqual(len(self.mixin.started_workers), 1)
        self.assertEqual(self.mixin.started_workers[0][1], ["proxy-a"])
        self.assertTrue(self.mixin.started_workers[0][2])

    def test_start_with_initialization_gate_sets_up_background_thread(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2
        created_threads: list[_FakeThread] = []

        def build_thread(*, target=None, args=(), daemon: bool = False, name: str = "") -> _FakeThread:
            thread = _FakeThread(target=target, args=args, daemon=daemon, name=name)
            created_threads.append(thread)
            return thread

        with patch("software.ui.controller.run_controller_parts.runtime_init_gate.threading.Thread", side_effect=build_thread):
            self.mixin._start_with_initialization_gate(config, proxy_pool=["proxy-a"])

        self.assertTrue(self.mixin.running)
        self.assertFalse(self.mixin._starting)
        self.assertTrue(self.mixin._initializing)
        self.assertEqual(self.mixin.run_state_events, [True])
        self.assertTrue(self.mixin._status_timer.started)
        self.assertEqual(self.mixin.emit_status_calls, 1)
        self.assertEqual(len(created_threads), 1)
        self.assertTrue(created_threads[0].started)
        self.assertEqual(created_threads[0].name, "InitGate")

    def test_prepare_engine_state_clones_prepared_template_and_injects_proxy_pool(self) -> None:
        template = ExecutionConfig(
            survey_provider="qq",
            num_threads=3,
            random_proxy_ip_enabled=True,
            questions_metadata={1: SurveyQuestionMeta(num=1, title="Q1")},
            single_prob=[[1.0, 0.0]],
        )
        self.mixin._prepared_execution_artifacts = PreparedExecutionArtifacts(
            execution_config_template=template,
            survey_provider="qq",
            question_entries=[],
            questions_info=[SurveyQuestionMeta(num=1, title="Q1")],
            reverse_fill_spec=None,
        )

        execution_config, execution_state = self.mixin._prepare_engine_state(["proxy-a"])

        self.assertIsNot(execution_config, template)
        self.assertEqual(execution_config.proxy_ip_pool, ["proxy-a"])
        self.assertEqual(execution_config.questions_metadata[1].title, "Q1")
        self.assertEqual(execution_state.config, execution_config)

        template.single_prob[0][0] = 0.0
        self.assertEqual(execution_config.single_prob[0][0], 1.0)

    def test_run_initialization_gate_dispatches_success_callback(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2

        with patch(
            "software.ui.controller.run_controller_parts.runtime_init_gate.run_browser_probe_subprocess",
            return_value=BrowserProbeResult(ok=True, browser="edge"),
        ):
            self.mixin._run_initialization_gate(config, ["proxy-a"], Event())

        self.assertEqual(len(self.mixin.dispatched_callbacks), 1)
        self.assertEqual(len(self.mixin.started_workers), 1)
        self.assertEqual(self.mixin.started_workers[0][1], ["proxy-a"])
        self.assertFalse(self.mixin.started_workers[0][2])

    def test_handle_browser_probe_failure_cancels_startup_when_user_declines(self) -> None:
        config = RuntimeConfig()

        self.mixin._handle_browser_probe_failure(
            config,
            ["proxy-a"],
            BrowserProbeResult(ok=False, browser="edge", message="启动失败", elapsed_ms=12),
        )

        self.assertFalse(self.mixin.running)
        self.assertEqual(self.mixin.status_events[-1], ("已取消启动", 0, 0))


if __name__ == "__main__":
    unittest.main()
