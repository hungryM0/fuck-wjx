from __future__ import annotations
import logging
import os
import tempfile
from unittest.mock import patch
import software.logging.log_utils as log_utils
from software.logging.log_utils import LogBufferEntry, export_full_log_to_file, finalize_session_log_persistence, get_auto_save_log_settings, log_deduped_message, prune_session_log_files, reset_deduped_log_message

class LogUtilsTests:

    def teardown_method(self, _method) -> None:
        reset_deduped_log_message('test_random_ip_sync_failure')
        handler = getattr(log_utils, '_SESSION_LOG_HANDLER', None)
        if handler is not None:
            try:
                handler.close()
            except Exception:
                pass
        log_utils._SESSION_LOG_HANDLER = None
        log_utils._SESSION_LOG_PATH = ''
        log_utils._DELETE_SESSION_LOG_ON_SHUTDOWN = False

    def test_log_deduped_message_only_logs_same_message_once(self) -> None:
        with patch('software.logging.log_utils.logging.log') as mock_log:
            first = log_deduped_message('test_random_ip_sync_failure', '同步随机IP额度失败：网络超时', level=logging.INFO)
            second = log_deduped_message('test_random_ip_sync_failure', '同步随机IP额度失败：网络超时', level=logging.INFO)
        assert first
        assert not second
        mock_log.assert_called_once_with(logging.INFO, '同步随机IP额度失败：网络超时')

    def test_reset_deduped_log_message_allows_same_message_to_log_again(self) -> None:
        with patch('software.logging.log_utils.logging.log') as mock_log:
            first = log_deduped_message('test_random_ip_sync_failure', '同步随机IP额度失败：网络超时', level=logging.INFO)
            reset_deduped_log_message('test_random_ip_sync_failure')
            second = log_deduped_message('test_random_ip_sync_failure', '同步随机IP额度失败：网络超时', level=logging.INFO)
        assert first
        assert second
        assert mock_log.call_count == 2

    def test_should_filter_runtime_probe_noise_messages(self) -> None:
        assert log_utils._should_filter_noise(
            "2026-05-07 00:07:55 [INFO] WJX 页面题目快照刷新：reason=question_2_expected_visible_miss count=8 elapsed=0.004s"
        )
        assert log_utils._should_filter_noise(
            "2026-05-07 00:07:57 [INFO] 随机代理首载：探测页面可用性 timeout=2500ms interval=0.25s"
        )
        assert log_utils._should_filter_noise(
            "2026-05-07 00:07:58 [INFO] WJX 题目处理耗时：question=5 type=4 elapsed=2.259s"
        )
        assert not log_utils._should_filter_noise("2026-05-07 00:07:59 [INFO] 提交成功")

    def test_export_full_log_to_file_prefers_session_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, 'session.log')
            target_path = os.path.join(temp_dir, 'exported.log')
            handler = logging.FileHandler(source_path, mode='a', encoding='utf-8')
            try:
                handler.stream.write('第一行\n第二行\n')
                handler.flush()
                log_utils._SESSION_LOG_HANDLER = handler
                log_utils._SESSION_LOG_PATH = source_path
                exported_path = export_full_log_to_file(temp_dir, target_path, fallback_records=[LogBufferEntry(text='缓冲区内容', category='INFO')])
                assert exported_path == target_path
                with open(target_path, 'r', encoding='utf-8') as file:
                    assert file.read() == '第一行\n第二行\n'
            finally:
                handler.close()
                log_utils._SESSION_LOG_HANDLER = None
                log_utils._SESSION_LOG_PATH = ''

    def test_export_full_log_to_file_falls_back_to_buffer_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = os.path.join(temp_dir, 'buffer.log')
            exported_path = export_full_log_to_file(temp_dir, target_path, fallback_records=[LogBufferEntry(text='缓冲一', category='INFO'), LogBufferEntry(text='缓冲二', category='WARNING')])
            assert exported_path == target_path
            with open(target_path, 'r', encoding='utf-8') as file:
                assert file.read() == '缓冲一\n缓冲二'

    def test_get_auto_save_log_settings_returns_defaults_when_values_missing(self) -> None:

        class _StubSettings:

            @staticmethod
            def value(_key):
                return None
        with patch('software.logging.log_utils.app_settings', return_value=_StubSettings()):
            enabled, keep_count = get_auto_save_log_settings()
        assert enabled
        assert keep_count == 10

    def test_prune_session_log_files_keeps_recent_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = os.path.join(temp_dir, 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            retained_names = []
            for index in range(3):
                name = f'session_20250101_00000{index}.log'
                path = os.path.join(logs_dir, name)
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(name)
                os.utime(path, (100 + index, 100 + index))
                retained_names.append(name)
            removed_count = prune_session_log_files(temp_dir, 2)
            assert removed_count == 1
            assert not os.path.exists(os.path.join(logs_dir, retained_names[0]))
            assert os.path.exists(os.path.join(logs_dir, retained_names[1]))
            assert os.path.exists(os.path.join(logs_dir, retained_names[2]))

    def test_finalize_session_log_persistence_exports_last_session_and_prunes_history_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = os.path.join(temp_dir, 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            source_path = os.path.join(logs_dir, 'session_20250101_000003.log')
            handler = logging.FileHandler(source_path, mode='a', encoding='utf-8')
            try:
                handler.stream.write('本次日志\n')
                handler.flush()
                log_utils._SESSION_LOG_HANDLER = handler
                log_utils._SESSION_LOG_PATH = source_path
                stale_paths = []
                for index in range(2):
                    stale_path = os.path.join(logs_dir, f'session_20250101_00000{index}.log')
                    with open(stale_path, 'w', encoding='utf-8') as file:
                        file.write('旧日志\n')
                    os.utime(stale_path, (100 + index, 100 + index))
                    stale_paths.append(stale_path)
                os.utime(source_path, (200, 200))
                with patch('software.logging.log_utils.get_auto_save_log_settings', return_value=(True, 2)):
                    finalize_session_log_persistence(temp_dir)
                last_session_path = os.path.join(logs_dir, 'last_session.log')
                assert os.path.exists(last_session_path)
                with open(last_session_path, 'r', encoding='utf-8') as file:
                    assert file.read() == '本次日志\n'
                assert os.path.exists(source_path)
                assert os.path.exists(stale_paths[1])
                assert not os.path.exists(stale_paths[0])
                assert not log_utils._DELETE_SESSION_LOG_ON_SHUTDOWN
            finally:
                handler.close()
                log_utils._SESSION_LOG_HANDLER = None
                log_utils._SESSION_LOG_PATH = ''

    def test_finalize_session_log_persistence_marks_session_for_deletion_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = os.path.join(temp_dir, 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            last_session_path = os.path.join(logs_dir, 'last_session.log')
            with open(last_session_path, 'w', encoding='utf-8') as file:
                file.write('旧的上次日志\n')
            with patch('software.logging.log_utils.get_auto_save_log_settings', return_value=(False, 10)):
                finalize_session_log_persistence(temp_dir)
            assert not os.path.exists(last_session_path)
            assert log_utils._DELETE_SESSION_LOG_ON_SHUTDOWN
