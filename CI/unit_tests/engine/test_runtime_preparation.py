from __future__ import annotations

import unittest
from unittest.mock import patch

from software.core.questions.config import QuestionEntry
from software.io.config import RuntimeConfig
from software.providers.contracts import SurveyQuestionMeta
from software.ui.controller.run_controller_parts.runtime_preparation import (
    PreparedExecutionArtifacts,
    RuntimePreparationError,
    prepare_execution_artifacts,
)


class RuntimePreparationTests(unittest.TestCase):
    def _build_config(self) -> RuntimeConfig:
        config = RuntimeConfig()
        config.url = "https://wj.qq.com/s2/demo"
        config.survey_title = "测试问卷"
        config.survey_provider = "qq"
        config.target = 5
        config.threads = 3
        config.answer_duration = (12, 20)
        config.submit_interval = (1, 2)
        config.random_ip_enabled = True
        config.random_ua_enabled = True
        config.random_ua_ratios = {"wechat": 20, "mobile": 30, "pc": 50}
        config.answer_rules = [{"num": 1, "equals": [1]}]
        config.question_entries = [
            QuestionEntry(
                question_type="single",
                probabilities=[100.0, 0.0],
                option_count=2,
                question_num=1,
                survey_provider="qq",
                provider_question_id="q1",
                provider_page_id="p1",
            )
        ]
        config.questions_info = [
            {
                "num": 1,
                "title": "Q1",
                "provider": "qq",
                "provider_question_id": "q1",
                "provider_page_id": "p1",
                "options": 2,
            }
        ]
        return config

    def test_prepare_execution_artifacts_rejects_empty_question_entries(self) -> None:
        config = RuntimeConfig()

        with self.assertRaises(RuntimePreparationError) as cm:
            prepare_execution_artifacts(config)

        self.assertIn("未配置任何题目", cm.exception.user_message)

    def test_prepare_execution_artifacts_rejects_validation_error(self) -> None:
        config = self._build_config()

        with patch(
            "software.ui.controller.run_controller_parts.runtime_preparation.validate_question_config",
            return_value="第1题配置冲突",
        ):
            with self.assertRaises(RuntimePreparationError) as cm:
                prepare_execution_artifacts(config)

        self.assertIn("题目配置存在冲突", cm.exception.user_message)
        self.assertIn("第1题配置冲突", cm.exception.log_message)

    def test_prepare_execution_artifacts_marks_reverse_fill_error_as_detailed(self) -> None:
        config = self._build_config()

        with patch(
            "software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec",
            side_effect=RuntimeError("反填源文件损坏"),
        ):
            with self.assertRaises(RuntimePreparationError) as cm:
                prepare_execution_artifacts(config)

        self.assertTrue(cm.exception.detailed)
        self.assertEqual(cm.exception.user_message, "反填源文件损坏")

    def test_prepare_execution_artifacts_builds_template_and_questions_metadata(self) -> None:
        config = self._build_config()

        def fake_configure_probabilities(entries, *, ctx, reliability_mode_enabled: bool) -> None:
            self.assertEqual(len(entries), 1)
            self.assertTrue(reliability_mode_enabled)
            ctx.single_prob = [[100.0, 0.0]]
            ctx.question_config_index_map = {1: ("single", 0)}

        with (
            patch(
                "software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec",
                return_value=None,
            ),
            patch(
                "software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities",
                side_effect=fake_configure_probabilities,
            ),
            patch(
                "software.ui.controller.run_controller_parts.runtime_preparation.set_proxy_occupy_minute_by_answer_duration",
            ) as sync_proxy_duration,
        ):
            artifacts = prepare_execution_artifacts(config, fallback_survey_title="后备标题")

        self.assertIsInstance(artifacts, PreparedExecutionArtifacts)
        self.assertEqual(artifacts.survey_provider, "qq")
        self.assertEqual(artifacts.execution_config_template.survey_title, "测试问卷")
        self.assertEqual(artifacts.execution_config_template.target_num, 5)
        self.assertEqual(artifacts.execution_config_template.num_threads, 3)
        self.assertEqual(artifacts.execution_config_template.question_config_index_map, {1: ("single", 0)})
        self.assertEqual(artifacts.execution_config_template.questions_metadata[1].provider, "qq")
        self.assertEqual(artifacts.execution_config_template.questions_metadata[1].title, "Q1")
        self.assertEqual(artifacts.execution_config_template.answer_rules, [{"num": 1, "equals": [1]}])
        self.assertEqual(artifacts.execution_config_template.proxy_ip_pool, [])
        sync_proxy_duration.assert_called_once_with((12, 20))

    def test_prepare_execution_artifacts_uses_fallback_title_when_config_title_blank(self) -> None:
        config = self._build_config()
        config.survey_title = ""

        with (
            patch(
                "software.ui.controller.run_controller_parts.runtime_preparation.build_enabled_reverse_fill_spec",
                return_value=None,
            ),
            patch(
                "software.ui.controller.run_controller_parts.runtime_preparation.configure_probabilities",
                return_value=None,
            ),
        ):
            artifacts = prepare_execution_artifacts(config, fallback_survey_title="解析得到的标题")

        self.assertEqual(artifacts.execution_config_template.survey_title, "解析得到的标题")
        self.assertEqual(artifacts.questions_info[0].provider, "qq")
        self.assertIsNot(artifacts.questions_info[0], config.questions_info[0])


if __name__ == "__main__":
    unittest.main()
