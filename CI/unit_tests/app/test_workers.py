from __future__ import annotations
import types
from unittest.mock import patch
from software.ui.workers.ai_test_worker import AITestWorker
from software.ui.workers.update_worker import UpdateCheckWorker

class WorkerTests:

    def test_update_check_worker_emits_success_result(self) -> None:
        worker = UpdateCheckWorker()
        received: list[tuple[bool, dict]] = []
        worker.finished.connect(lambda has_update, payload: received.append((has_update, payload)))
        fake_module = types.SimpleNamespace(UpdateManager=types.SimpleNamespace(check_updates=lambda: {'has_update': True, 'status': 'ok', 'version': '1.2.3'}))
        with patch.dict('sys.modules', {'software.update.updater': fake_module}):
            worker.run()
        assert received == [(True, {'has_update': True, 'status': 'ok', 'version': '1.2.3'})]

    def test_update_check_worker_uses_fallback_when_dependency_returns_none(self) -> None:
        worker = UpdateCheckWorker()
        received: list[tuple[bool, dict]] = []
        worker.finished.connect(lambda has_update, payload: received.append((has_update, payload)))
        fake_module = types.SimpleNamespace(UpdateManager=types.SimpleNamespace(check_updates=lambda: None))
        with patch.dict('sys.modules', {'software.update.updater': fake_module}):
            worker.run()
        assert received == [(False, {'has_update': False, 'status': 'unknown'})]

    def test_update_check_worker_emits_safe_fallback_on_exception(self) -> None:
        worker = UpdateCheckWorker()
        received: list[tuple[bool, dict]] = []
        worker.finished.connect(lambda has_update, payload: received.append((has_update, payload)))
        fake_module = types.SimpleNamespace(UpdateManager=types.SimpleNamespace(check_updates=lambda: (_ for _ in ()).throw(RuntimeError('network down'))))
        with patch.dict('sys.modules', {'software.update.updater': fake_module}):
            worker.run()
        assert received == [(False, {'has_update': False, 'status': 'unknown'})]

    def test_update_check_worker_skips_emit_when_thread_interrupted(self) -> None:
        worker = UpdateCheckWorker()
        received: list[tuple[bool, dict]] = []
        worker.finished.connect(lambda has_update, payload: received.append((has_update, payload)))
        fake_thread = types.SimpleNamespace(isInterruptionRequested=lambda: True)
        fake_module = types.SimpleNamespace(
            UpdateManager=types.SimpleNamespace(
                check_updates=lambda: {'has_update': True, 'status': 'ok', 'version': '1.2.3'}
            )
        )
        with (
            patch.object(worker, 'thread', return_value=fake_thread),
            patch.dict('sys.modules', {'software.update.updater': fake_module}),
        ):
            worker.run()
        assert received == []

    def test_ai_test_worker_treats_connection_success_prefix_as_success(self) -> None:
        worker = AITestWorker()
        received: list[tuple[bool, str]] = []
        worker.finished.connect(lambda success, message: received.append((success, message)))
        with patch('software.ui.workers.ai_test_worker.atest_connection', return_value='连接成功：延迟 120ms'):
            worker.run()
        assert received == [(True, '连接成功：延迟 120ms')]

    def test_ai_test_worker_treats_non_success_result_as_failure(self) -> None:
        worker = AITestWorker()
        received: list[tuple[bool, str]] = []
        worker.finished.connect(lambda success, message: received.append((success, message)))
        with patch('software.ui.workers.ai_test_worker.atest_connection', return_value='服务暂时不可用'):
            worker.run()
        assert received == [(False, '服务暂时不可用')]

    def test_ai_test_worker_emits_readable_error_when_dependency_raises(self) -> None:
        worker = AITestWorker()
        received: list[tuple[bool, str]] = []
        worker.finished.connect(lambda success, message: received.append((success, message)))
        with patch('software.ui.workers.ai_test_worker.atest_connection', side_effect=RuntimeError('timeout')):
            worker.run()
        assert received == [(False, '连接失败: timeout')]
