from __future__ import annotations
import pytest

from software.core.config.codec import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    _ensure_supported_config_payload,
    _select_user_agent_from_ratios,
    build_runtime_config_snapshot,
    deserialize_question_entry,
    deserialize_runtime_config,
    normalize_runtime_config_payload,
    serialize_question_entry,
    serialize_runtime_config,
)
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

    def test_legacy_v3_payload_deduplicates_dimensions_and_invalid_versions_raise(self) -> None:
        upgraded = _ensure_supported_config_payload(
            {
                "config_schema_version": 3,
                "dimension_groups": ["体验", "未分组", "体验", "", "价格"],
                "reverse_fill_start_row": "bad",
                "reverse_fill_threads": "bad",
            },
            config_path="legacy-v3.json",
        )

        assert upgraded["config_schema_version"] == CURRENT_CONFIG_SCHEMA_VERSION
        assert upgraded["dimension_groups"] == ["体验", "价格"]
        assert upgraded["reverse_fill_start_row"] == 1
        assert upgraded["reverse_fill_threads"] == 1

        with pytest.raises(ValueError, match="已移除的旧字段"):
            _ensure_supported_config_payload({"random_proxy_api": "old"}, config_path="bad.json")
        with pytest.raises(ValueError, match="版本不受支持"):
            _ensure_supported_config_payload({"config_schema_version": 2}, config_path="bad.json")

    def test_question_entry_normalizes_text_modes_ranges_provider_and_dimensions(self) -> None:
        entry = deserialize_question_entry(
            {
                "question_type": "text",
                "probabilities": [],
                "texts": ["答案"],
                "rows": "2",
                "option_count": "0",
                "distribution_mode": "custom",
                "custom_weights": [0, "3"],
                "survey_provider": "unknown",
                "provider_question_id": " q1 ",
                "provider_page_id": " p1 ",
                "ai_enabled": True,
                "multi_text_blank_modes": ["name", "bad", "integer"],
                "multi_text_blank_ai_flags": [1, 0],
                "multi_text_blank_int_ranges": [[1, 3], "", ["bad"]],
                "text_random_mode": "integer",
                "text_random_int_range": ["5", "9"],
                "is_location": True,
                "location_parts": ["北京", "北京", "东城区"],
                "dimension": " 未分组 ",
                "psycho_bias": "bad",
            }
        )

        assert entry.probabilities == [0, "3"]
        assert entry.custom_weights == [0, "3"]
        assert entry.survey_provider == "wjx"
        assert entry.provider_question_id == "q1"
        assert entry.provider_page_id == "p1"
        assert entry.multi_text_blank_modes == ["name", "none", "integer"]
        assert entry.multi_text_blank_ai_flags == [True, False]
        assert entry.text_random_int_range == [5, 9]
        assert entry.is_location is True
        assert entry.location_parts == ["北京", "北京", "东城区"]
        assert entry.dimension is None
        assert entry.psycho_bias == "custom"

        payload = serialize_question_entry(entry)
        assert payload["dimension"] is None
        assert payload["text_random_int_range"] == [5, 9]
        assert payload["location_parts"] == ["北京", "北京", "东城区"]

    def test_normalize_runtime_config_payload_covers_boundaries_and_invalid_values(self) -> None:
        cfg = normalize_runtime_config_payload(
            {
                "url": "https://wjx.cn/vm/demo.aspx",
                "target": "bad",
                "threads": "4",
                "submit_interval": ["1", "3"],
                "answer_duration": ["bad"],
                "random_ip_enabled": "yes",
                "proxy_source": "bad",
                "custom_proxy_api": "https://proxy.example",
                "random_ua_keys": ["pc_web", "bad"],
                "random_ua_ratios": {"wechat": 20, "mobile": 20, "pc": 20},
                "reverse_fill_format": "bad",
                "reverse_fill_start_row": "-2",
                "reverse_fill_threads": "0",
                "dimension_groups": ["服务", "服务", "未分组"],
                "ai_mode": "bad",
                "questions_info": "bad",
                "question_entries": [{"question_type": "single", "rows": "bad"}],
            }
        )

        assert cfg.target == 1
        assert cfg.threads == 4
        assert cfg.submit_interval == (1, 3)
        assert cfg.answer_duration == (60, 120)
        assert cfg.random_ip_enabled is True
        assert cfg.proxy_source == "custom"
        assert cfg.random_ua_keys == ["pc_web"]
        assert cfg.random_ua_ratios == {"wechat": 33, "mobile": 33, "pc": 34}
        assert cfg.reverse_fill_format == "auto"
        assert cfg.reverse_fill_start_row == 1
        assert cfg.reverse_fill_threads == 1
        assert cfg.dimension_groups == ["服务"]
        assert cfg.ai_mode == "free"
        assert cfg.questions_info == []
        assert cfg.question_entries == []

    def test_random_ip_enabled_survives_official_proxy_sources(self) -> None:
        for source in ("default", "benefit", "custom"):
            cfg = normalize_runtime_config_payload(
                {
                    "random_ip_enabled": True,
                    "proxy_source": source,
                }
            )

            assert cfg.random_ip_enabled is True
            assert cfg.proxy_source == source

    def test_answer_duration_legacy_single_value_expands_to_10_percent_range(self) -> None:
        assert normalize_runtime_config_payload({"answer_duration": 90}).answer_duration == (81, 99)
        assert normalize_runtime_config_payload({"answer_duration": ["90"]}).answer_duration == (81, 99)
        assert normalize_runtime_config_payload({"answer_duration": [180, 180]}).answer_duration == (
            162,
            198,
        )
        assert normalize_runtime_config_payload({}).answer_duration == (60, 120)
        assert normalize_runtime_config_payload({"answer_duration": 9999}).answer_duration == (
            1620,
            1800,
        )
        assert normalize_runtime_config_payload({"answer_duration": [1200, 9999]}).answer_duration == (
            1200,
            1800,
        )

    def test_select_user_agent_from_ratios_handles_empty_unknown_and_valid_devices(self, monkeypatch) -> None:
        assert _select_user_agent_from_ratios({"wechat": 0, "mobile": 0}) == (None, None)
        monkeypatch.setattr("software.core.config.codec.random.choice", lambda values: values[0])
        ua, label = _select_user_agent_from_ratios({"pc": 1})
        assert ua
        assert label
        assert _select_user_agent_from_ratios({"unknown": 1}) == (None, None)
