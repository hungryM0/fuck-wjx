from __future__ import annotations
from software.core.config.codec import CURRENT_CONFIG_SCHEMA_VERSION, _ensure_supported_config_payload, build_runtime_config_snapshot, deserialize_runtime_config, serialize_runtime_config
from software.core.config.schema import RuntimeConfig
from software.core.questions.schema import QuestionEntry
from software.core.reverse_fill.schema import REVERSE_FILL_FORMAT_WJX_SEQUENCE
from software.providers.contracts import SurveyQuestionMeta

class ConfigCodecTests:

    def test_runtime_config_roundtrip_keeps_reverse_fill_fields(self) -> None:
        config = RuntimeConfig(reverse_fill_enabled=True, reverse_fill_source_path='D:/demo.xlsx', reverse_fill_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE, reverse_fill_start_row=3, reverse_fill_threads=4)
        payload = serialize_runtime_config(config)
        restored = deserialize_runtime_config(payload)
        assert payload['config_schema_version'] == CURRENT_CONFIG_SCHEMA_VERSION
        assert restored.reverse_fill_enabled
        assert restored.reverse_fill_source_path == 'D:/demo.xlsx'
        assert restored.reverse_fill_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE
        assert restored.reverse_fill_start_row == 3
        assert restored.reverse_fill_threads == 4

    def test_legacy_v4_payload_is_upgraded_to_v5_with_reverse_fill_defaults(self) -> None:
        upgraded = _ensure_supported_config_payload({'config_schema_version': 4, 'reverse_fill_enabled': True, 'reverse_fill_source_path': 'D:/legacy.xlsx', 'reverse_fill_format': 'unknown', 'reverse_fill_start_row': 0, 'threads': 6}, config_path='legacy.json')
        assert upgraded['config_schema_version'] == CURRENT_CONFIG_SCHEMA_VERSION
        assert upgraded['reverse_fill_enabled']
        assert upgraded['reverse_fill_source_path'] == 'D:/legacy.xlsx'
        assert upgraded['reverse_fill_format'] == 'auto'
        assert upgraded['reverse_fill_start_row'] == 1
        assert upgraded['reverse_fill_threads'] == 6

    def test_runtime_config_roundtrip_keeps_questions_info_provider_metadata(self) -> None:
        config = RuntimeConfig(survey_provider='qq', questions_info=[SurveyQuestionMeta(num=3, title='联系方式', type_code='1', provider='qq', provider_question_id='question-3', provider_page_id='page-2', provider_type='text', option_texts=['姓名', '电话'], required=True, logic_parse_status='unknown', question_media=[{'kind': 'image', 'scope': 'title', 'index': None, 'source_url': 'https://example.com/q3.png', 'label': '题干图'}])])
        payload = serialize_runtime_config(config)
        restored = deserialize_runtime_config(payload)
        assert payload['questions_info'][0]['provider_question_id'] == 'question-3'
        assert payload['questions_info'][0]['provider_page_id'] == 'page-2'
        assert payload['questions_info'][0]['provider_type'] == 'text'
        assert payload['questions_info'][0]['required']
        assert payload['questions_info'][0]['logic_parse_status'] == 'unknown'
        assert payload['questions_info'][0]['question_media'][0]['source_url'] == 'https://example.com/q3.png'
        assert len(restored.questions_info or []) == 1
        restored_info = restored.questions_info[0]
        assert restored_info.provider == 'qq'
        assert restored_info.provider_question_id == 'question-3'
        assert restored_info.provider_page_id == 'page-2'
        assert restored_info.provider_type == 'text'
        assert restored_info.required
        assert restored_info.logic_parse_status == 'unknown'
        assert restored_info.question_media[0]['label'] == '题干图'

    def test_build_runtime_config_snapshot_returns_detached_copies(self) -> None:
        config = RuntimeConfig(survey_provider='wjx', answer_rules=[{'question_num': 1, 'equals': [0]}], dimension_groups=['情绪维度'], question_entries=[QuestionEntry(question_type='single', probabilities=[60.0, 40.0], texts=['A', 'B'], option_count=2, question_num=1)], questions_info=[SurveyQuestionMeta(num=1, title='单选题', type_code='3', option_texts=['A', 'B'], provider_question_id='q1')])
        snapshot = build_runtime_config_snapshot(config)
        assert snapshot is not config
        assert snapshot.question_entries is not config.question_entries
        assert snapshot.questions_info is not config.questions_info
        assert snapshot.question_entries[0] is not config.question_entries[0]
        assert snapshot.questions_info[0] is not config.questions_info[0]
        snapshot.question_entries[0].texts[0] = '已修改'
        snapshot.questions_info[0].option_texts[0] = '已修改'
        snapshot.answer_rules[0]['equals'][0] = 9
        snapshot.dimension_groups[0] = '新维度'
        assert config.question_entries[0].texts[0] == 'A'
        assert config.questions_info[0].option_texts[0] == 'A'
        assert config.answer_rules[0]['equals'][0] == 0
        assert config.dimension_groups[0] == '情绪维度'
