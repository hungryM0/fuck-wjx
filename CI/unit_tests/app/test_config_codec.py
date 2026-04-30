from __future__ import annotations

import unittest

from software.core.config.codec import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    _ensure_supported_config_payload,
    build_runtime_config_snapshot,
    deserialize_runtime_config,
    serialize_runtime_config,
)
from software.core.config.schema import RuntimeConfig
from software.core.questions.schema import QuestionEntry
from software.core.reverse_fill.schema import REVERSE_FILL_FORMAT_WJX_SEQUENCE
from software.providers.contracts import SurveyQuestionMeta


class ConfigCodecTests(unittest.TestCase):
    def test_runtime_config_roundtrip_keeps_reverse_fill_fields(self) -> None:
        config = RuntimeConfig(
            reverse_fill_enabled=True,
            reverse_fill_source_path="D:/demo.xlsx",
            reverse_fill_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
            reverse_fill_start_row=3,
        )

        payload = serialize_runtime_config(config)
        restored = deserialize_runtime_config(payload)

        self.assertEqual(payload["config_schema_version"], CURRENT_CONFIG_SCHEMA_VERSION)
        self.assertTrue(restored.reverse_fill_enabled)
        self.assertEqual(restored.reverse_fill_source_path, "D:/demo.xlsx")
        self.assertEqual(restored.reverse_fill_format, REVERSE_FILL_FORMAT_WJX_SEQUENCE)
        self.assertEqual(restored.reverse_fill_start_row, 3)

    def test_legacy_v4_payload_is_upgraded_to_v5_with_reverse_fill_defaults(self) -> None:
        upgraded = _ensure_supported_config_payload(
            {
                "config_schema_version": 4,
                "reverse_fill_enabled": True,
                "reverse_fill_source_path": "D:/legacy.xlsx",
                "reverse_fill_format": "unknown",
                "reverse_fill_start_row": 0,
            },
            config_path="legacy.json",
        )

        self.assertEqual(upgraded["config_schema_version"], CURRENT_CONFIG_SCHEMA_VERSION)
        self.assertTrue(upgraded["reverse_fill_enabled"])
        self.assertEqual(upgraded["reverse_fill_source_path"], "D:/legacy.xlsx")
        self.assertEqual(upgraded["reverse_fill_format"], "auto")
        self.assertEqual(upgraded["reverse_fill_start_row"], 1)

    def test_runtime_config_roundtrip_keeps_questions_info_provider_metadata(self) -> None:
        config = RuntimeConfig(
            survey_provider="qq",
            questions_info=[
                SurveyQuestionMeta(
                    num=3,
                    title="联系方式",
                    type_code="1",
                    provider="qq",
                    provider_question_id="question-3",
                    provider_page_id="page-2",
                    provider_type="text",
                    option_texts=["姓名", "电话"],
                    required=True,
                )
            ],
        )

        payload = serialize_runtime_config(config)
        restored = deserialize_runtime_config(payload)

        self.assertEqual(payload["questions_info"][0]["provider_question_id"], "question-3")
        self.assertEqual(payload["questions_info"][0]["provider_page_id"], "page-2")
        self.assertEqual(payload["questions_info"][0]["provider_type"], "text")
        self.assertTrue(payload["questions_info"][0]["required"])
        self.assertEqual(len(restored.questions_info or []), 1)
        restored_info = restored.questions_info[0]
        self.assertEqual(restored_info.provider, "qq")
        self.assertEqual(restored_info.provider_question_id, "question-3")
        self.assertEqual(restored_info.provider_page_id, "page-2")
        self.assertEqual(restored_info.provider_type, "text")
        self.assertTrue(restored_info.required)

    def test_build_runtime_config_snapshot_returns_detached_copies(self) -> None:
        config = RuntimeConfig(
            survey_provider="wjx",
            answer_rules=[{"question_num": 1, "equals": [0]}],
            dimension_groups=["情绪维度"],
            question_entries=[
                QuestionEntry(
                    question_type="single",
                    probabilities=[60.0, 40.0],
                    texts=["A", "B"],
                    option_count=2,
                    question_num=1,
                )
            ],
            questions_info=[
                SurveyQuestionMeta(
                    num=1,
                    title="单选题",
                    type_code="3",
                    option_texts=["A", "B"],
                    provider_question_id="q1",
                )
            ],
        )

        snapshot = build_runtime_config_snapshot(config)
        self.assertIsNot(snapshot, config)
        self.assertIsNot(snapshot.question_entries, config.question_entries)
        self.assertIsNot(snapshot.questions_info, config.questions_info)
        self.assertIsNot(snapshot.question_entries[0], config.question_entries[0])
        self.assertIsNot(snapshot.questions_info[0], config.questions_info[0])

        snapshot.question_entries[0].texts[0] = "已修改"
        snapshot.questions_info[0].option_texts[0] = "已修改"
        snapshot.answer_rules[0]["equals"][0] = 9
        snapshot.dimension_groups[0] = "新维度"

        self.assertEqual(config.question_entries[0].texts[0], "A")
        self.assertEqual(config.questions_info[0].option_texts[0], "A")
        self.assertEqual(config.answer_rules[0]["equals"][0], 0)
        self.assertEqual(config.dimension_groups[0], "情绪维度")


if __name__ == "__main__":
    unittest.main()
