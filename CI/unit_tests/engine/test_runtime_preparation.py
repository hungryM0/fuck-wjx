from __future__ import annotations
import pytest
from unittest.mock import patch
from software.core.questions.config import QuestionEntry
from software.core.config.schema import RuntimeConfig
from software.core.reverse_fill.schema import ReverseFillSpec
from software.ui.controller.run_controller_parts.runtime_preparation import PreparedExecutionArtifacts, RuntimePreparationError, prepare_execution_artifacts

class _FakeHttpResponse:

    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class RuntimePreparationTests:

    def _build_config(self) -> RuntimeConfig:
        config = RuntimeConfig()
        config.url = 'https://wj.qq.com/s2/demo'
        config.survey_title = '测试问卷'
        config.survey_provider = 'qq'
        config.target = 5
        config.threads = 3
        config.answer_duration = (12, 20)
        config.answer_datetime_window = ("", "")
        config.submit_interval = (1, 2)
        config.random_ip_enabled = True
        config.random_ua_enabled = True
        config.random_ua_ratios = {'wechat': 20, 'mobile': 30, 'pc': 50}
        config.answer_rules = [{'num': 1, 'equals': [1]}]
        config.question_entries = [QuestionEntry(question_type='single', probabilities=[100.0, 0.0], option_count=2, question_num=1, survey_provider='qq', provider_question_id='q1', provider_page_id='p1')]
        config.questions_info = [{'num': 1, 'title': 'Q1', 'provider': 'qq', 'provider_question_id': 'q1', 'provider_page_id': 'p1', 'options': 2}]
        return config

    def test_prepare_execution_artifacts_rejects_empty_question_entries(self) -> None:
        config = RuntimeConfig()
        with pytest.raises(RuntimePreparationError) as cm:
            prepare_execution_artifacts(config)
        assert '未配置任何题目' in cm.value.user_message

    def test_prepare_execution_artifacts_rejects_validation_error(self) -> None:
        config = self._build_config()
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.validate_question_config', return_value='第1题配置冲突'):
            with pytest.raises(RuntimePreparationError) as cm:
                prepare_execution_artifacts(config)
        assert '题目配置存在冲突' in cm.value.user_message
        assert '第1题配置冲突' in cm.value.log_message

    def test_prepare_execution_artifacts_blocks_stopped_wjx_before_runtime(self) -> None:
        config = self._build_config()
        config.url = 'https://v.wjx.cn/vm/demo.aspx'
        config.survey_provider = 'wjx'
        config.question_entries[0].survey_provider = 'wjx'
        config.questions_info[0]['provider'] = 'wjx'
        html = "<html><body><div id='divWorkError'>此问卷处于停止状态，无法作答！</div></body></html>"
        with patch('software.network.http.get', return_value=_FakeHttpResponse(html)) as http_get, patch('software.ui.controller.run_controller_parts.runtime_preparation.validate_question_config', return_value=''):
            with pytest.raises(RuntimePreparationError) as cm:
                prepare_execution_artifacts(config)
        assert cm.value.user_message == '问卷已停止，无法作答'
        assert http_get.call_args.kwargs.get('proxies') == {}

    def test_prepare_execution_artifacts_blocks_enterprise_unavailable_wjx_before_runtime(self) -> None:
        config = self._build_config()
        config.url = 'https://v.wjx.cn/vm/demo.aspx'
        config.survey_provider = 'wjx'
        config.question_entries[0].survey_provider = 'wjx'
        config.questions_info[0]['provider'] = 'wjx'
        html = """
        <html><body>
          <div>问卷发布者还未购买企业标准版或企业标准版已到期，此问卷暂时不能被填写！</div>
          <div id="divQuestion"><fieldset><div topic="1" type="3">Q1</div></fieldset></div>
        </body></html>
        """
        with patch('software.network.http.get', return_value=_FakeHttpResponse(html)), patch('software.ui.controller.run_controller_parts.runtime_preparation.validate_question_config', return_value=''):
            with pytest.raises(RuntimePreparationError) as cm:
                prepare_execution_artifacts(config)
        assert cm.value.user_message == '问卷发布者企业标准版未购买或已到期，暂时不能填写'

    def test_prepare_execution_artifacts_marks_reverse_fill_error_as_detailed(self) -> None:
        config = self._build_config()
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', side_effect=RuntimeError('反填源文件损坏')):
            with pytest.raises(RuntimePreparationError) as cm:
                prepare_execution_artifacts(config)
        assert cm.value.detailed
        assert cm.value.user_message == '反填源文件损坏'

    def test_prepare_execution_artifacts_builds_template_and_questions_metadata(self) -> None:
        config = self._build_config()

        def fake_configure_probabilities(entries, *, ctx, reliability_mode_enabled: bool) -> None:
            assert len(entries) == 1
            assert reliability_mode_enabled
            ctx.single_prob = [[100.0, 0.0]]
            ctx.question_config_index_map = {1: ('single', 0)}
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', return_value=None), patch('software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities', side_effect=fake_configure_probabilities), patch('software.ui.controller.run_controller_parts.runtime_preparation.set_proxy_occupy_minute_by_answer_duration') as sync_proxy_duration:
            artifacts = prepare_execution_artifacts(config, fallback_survey_title='后备标题')
        assert isinstance(artifacts, PreparedExecutionArtifacts)
        assert artifacts.survey_provider == 'qq'
        assert artifacts.execution_config_template.survey_title == '测试问卷'
        assert artifacts.execution_config_template.target_num == 5
        assert artifacts.execution_config_template.num_threads == 3
        assert artifacts.execution_config_template.question_config_index_map == {1: ('single', 0)}
        assert artifacts.execution_config_template.questions_metadata[1].provider == 'qq'
        assert artifacts.execution_config_template.questions_metadata[1].title == 'Q1'
        assert artifacts.execution_config_template.provider_question_metadata_map == {
            'qq:p1:q1': artifacts.execution_config_template.questions_metadata[1]
        }
        assert artifacts.execution_config_template.answer_rules == [{'num': 1, 'equals': [1]}]
        assert artifacts.execution_config_template.answer_datetime_window_ms == (0, 0)
        assert artifacts.execution_config_template.proxy_ip_pool == []
        sync_proxy_duration.assert_called_once_with((12, 20), survey_provider='qq')

    def test_prepare_execution_artifacts_allows_missing_credamo_answer_datetime_window(self) -> None:
        config = self._build_config()
        config.url = "https://www.credamo.com/s/A73QR3ano"
        config.survey_provider = "credamo"
        config.question_entries[0].survey_provider = "credamo"
        config.questions_info[0]["provider"] = "credamo"
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', return_value=None), patch('software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities', return_value=None):
            artifacts = prepare_execution_artifacts(config)
        assert artifacts.execution_config_template.answer_datetime_window_ms == (0, 0)

    def test_prepare_execution_artifacts_rejects_partial_credamo_answer_datetime_window(self) -> None:
        config = self._build_config()
        config.url = "https://www.credamo.com/s/A73QR3ano"
        config.survey_provider = "credamo"
        config.question_entries[0].survey_provider = "credamo"
        config.questions_info[0]["provider"] = "credamo"
        config.answer_datetime_window = ("2026-02-10 09:00:00", "")
        with pytest.raises(RuntimePreparationError, match="未配完整"):
            prepare_execution_artifacts(config)

    def test_prepare_execution_artifacts_rejects_invalid_credamo_answer_datetime_window(self) -> None:
        config = self._build_config()
        config.url = "https://www.credamo.com/s/A73QR3ano"
        config.survey_provider = "credamo"
        config.question_entries[0].survey_provider = "credamo"
        config.questions_info[0]["provider"] = "credamo"
        config.answer_datetime_window = ("2026-02-10 10:00:00", "2026-02-10 09:00:00")
        with pytest.raises(RuntimePreparationError, match="必须晚于"):
            prepare_execution_artifacts(config)

    def test_prepare_execution_artifacts_rejects_narrow_credamo_answer_datetime_window(self) -> None:
        config = self._build_config()
        config.url = "https://www.credamo.com/s/A73QR3ano"
        config.survey_provider = "credamo"
        config.question_entries[0].survey_provider = "credamo"
        config.questions_info[0]["provider"] = "credamo"
        config.answer_datetime_window = ("2026-02-10 09:00:00", "2026-02-10 09:00:10")
        with pytest.raises(RuntimePreparationError, match="太窄"):
            prepare_execution_artifacts(config)

    def test_prepare_execution_artifacts_builds_credamo_answer_datetime_window_ms(self) -> None:
        config = self._build_config()
        config.url = "https://www.credamo.com/s/A73QR3ano"
        config.survey_provider = "credamo"
        config.question_entries[0].survey_provider = "credamo"
        config.questions_info[0]["provider"] = "credamo"
        config.answer_datetime_window = ("2026-02-10 09:00:00", "2026-02-10 10:00:00")
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', return_value=None), patch('software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities', return_value=None):
            artifacts = prepare_execution_artifacts(config)
        start_ms, end_ms = artifacts.execution_config_template.answer_datetime_window_ms
        assert end_ms > start_ms > 0

    def test_prepare_execution_artifacts_uses_fallback_title_when_config_title_blank(self) -> None:
        config = self._build_config()
        config.survey_title = ''
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', return_value=None), patch('software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities', return_value=None):
            artifacts = prepare_execution_artifacts(config, fallback_survey_title='解析得到的标题')
        assert artifacts.execution_config_template.survey_title == '解析得到的标题'
        assert artifacts.questions_info[0].provider == 'qq'
        assert artifacts.questions_info[0] is not config.questions_info[0]

    def test_prepare_execution_artifacts_clamps_threads_by_http_limit(self) -> None:
        config = self._build_config()
        config.threads = 99
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', return_value=None), patch('software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities', return_value=None):
            artifacts = prepare_execution_artifacts(config)
        assert artifacts.execution_config_template.num_threads == 64

    def test_prepare_execution_artifacts_uses_reverse_fill_sample_count_and_threads(self) -> None:
        config = self._build_config()
        config.target = 2
        config.threads = 8
        config.reverse_fill_threads = 3
        reverse_fill_spec = ReverseFillSpec(source_path='D:/demo.xlsx', selected_format='wjx_sequence', detected_format='wjx_sequence', start_row=1, total_samples=9, available_samples=9, target_num=9)
        with patch('software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec', return_value=reverse_fill_spec), patch('software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities', return_value=None):
            artifacts = prepare_execution_artifacts(config)
        assert artifacts.execution_config_template.target_num == 9
        assert artifacts.execution_config_template.num_threads == 3
