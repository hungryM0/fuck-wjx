from __future__ import annotations
from threading import Event
from software.core.task import ExecutionConfig
from software.core.config.schema import RuntimeConfig
from software.providers.contracts import SurveyQuestionMeta
from software.ui.controller.run_controller_parts.runtime_init_gate import RunControllerInitializationMixin
from software.ui.controller.run_controller_parts.runtime_preparation import PreparedExecutionArtifacts

class _DummyInitGate(RunControllerInitializationMixin):

    def __init__(self) -> None:
        self.stop_event = Event()
        self._initializing = True
        self._starting = True
        self.running = True
        self.worker_threads = [object()]
        self._execution_state = object()
        self._init_stage_text = '正在初始化'
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ''
        self._init_gate_stop_event = Event()
        self._status_timer = _FakeTimer()
        self._prepared_execution_artifacts = None
        self.started_workers: list[tuple[RuntimeConfig, list, bool]] = []
        self.dispatched_callbacks: list[object] = []
        self.emit_status_calls = 0
        self.survey_title = '测试问卷'
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

    def _start_workers_with_proxy_pool(self, config: RuntimeConfig, proxy_pool: list, *, emit_run_state: bool=True) -> None:
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

    def __init__(self, *, target=None, args=(), daemon: bool=False, name: str='') -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self) -> None:
        self.started = True

class RuntimeInitGateTests:

    def setup_method(self, _method) -> None:
        self.mixin = _DummyInitGate()

    def test_cancel_initialization_resets_ui_to_idle_state(self) -> None:
        self.mixin._cancel_initialization_startup()
        assert not self.mixin.running
        assert not self.mixin._starting
        assert not self.mixin._initializing
        assert self.mixin.worker_threads == []
        assert self.mixin._execution_state is None
        assert self.mixin._status_timer.stopped
        assert self.mixin.run_state_events == [False]
        assert self.mixin.status_events == [('已取消启动', 0, 0)]
        assert self.mixin.thread_progress_events[-1] == {'threads': [], 'target': 0, 'num_threads': 0, 'per_thread_target': 0, 'initializing': False}

    def test_build_initialization_logs_marks_stage_and_completion(self) -> None:
        self.mixin._init_stage_text = '正在检查运行时'
        self.mixin._init_steps = [{'key': 'probe', 'label': '运行时快检'}, {'key': 'warmup', 'label': '预热'}]
        self.mixin._init_completed_steps = {'probe'}
        self.mixin._init_current_step_key = 'warmup'
        lines = self.mixin._build_initialization_logs()
        assert lines == ['当前阶段：正在检查运行时', '[√] 运行时快检', '[>] 预热']

    def test_start_with_initialization_gate_bypasses_gate_for_single_thread(self) -> None:
        config = RuntimeConfig()
        config.threads = 1
        self.mixin._start_with_initialization_gate(config, proxy_pool=['proxy-a'])
        assert len(self.mixin.started_workers) == 1
        assert self.mixin.started_workers[0][1] == ['proxy-a']
        assert self.mixin.started_workers[0][2]

    def test_start_with_initialization_gate_starts_workers_directly(self) -> None:
        config = RuntimeConfig()
        config.threads = 2
        self.mixin._start_with_initialization_gate(config, proxy_pool=['proxy-a'])
        assert len(self.mixin.started_workers) == 1
        assert self.mixin.started_workers[0][1] == ['proxy-a']
        assert self.mixin.started_workers[0][2]

    def test_prepare_engine_state_clones_prepared_template_and_injects_proxy_pool(self) -> None:
        template = ExecutionConfig(survey_provider='qq', num_threads=3, random_proxy_ip_enabled=True, questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1')}, single_prob=[[1.0, 0.0]])
        self.mixin._prepared_execution_artifacts = PreparedExecutionArtifacts(execution_config_template=template, survey_provider='qq', question_entries=[], questions_info=[SurveyQuestionMeta(num=1, title='Q1')], reverse_fill_spec=None)
        execution_config, execution_state = self.mixin._prepare_engine_state(['proxy-a'])
        assert execution_config is not template
        assert execution_config.proxy_ip_pool == ['proxy-a']
        assert execution_config.questions_metadata[1].title == 'Q1'
        assert execution_state.config == execution_config
        template.single_prob[0][0] = 0.0
        assert execution_config.single_prob[0][0] == 1.0
