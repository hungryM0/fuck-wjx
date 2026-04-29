from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from credamo.provider import parser
from software.core.questions.default_builder import build_default_question_entries
from software.core.questions.normalization import configure_probabilities
from software.core.questions.schema import QuestionEntry


class CredamoParserTests(unittest.TestCase):
    class _FakeButton:
        def __init__(self, text: str, visible: bool) -> None:
            self.text = text
            self.visible = visible

        def is_visible(self, timeout: int = 0) -> bool:
            return self.visible

        def text_content(self, timeout: int = 0) -> str:
            return self.text

        def get_attribute(self, _name: str) -> str:
            return ""

    class _FakeLocator:
        def __init__(self, items: list["CredamoParserTests._FakeButton"]) -> None:
            self.items = items

        def count(self) -> int:
            return len(self.items)

        def nth(self, index: int) -> "CredamoParserTests._FakeButton":
            return self.items[index]

    class _FakePage:
        def __init__(self, buttons: list["CredamoParserTests._FakeButton"]) -> None:
            self.buttons = buttons

        def locator(self, _selector: str) -> "CredamoParserTests._FakeLocator":
            return CredamoParserTests._FakeLocator(self.buttons)

    def test_infer_type_code_uses_page_block_kind(self) -> None:
        self.assertEqual(parser._infer_type_code({"question_kind": "dropdown"}), "7")
        self.assertEqual(parser._infer_type_code({"question_kind": "scale"}), "5")
        self.assertEqual(parser._infer_type_code({"question_kind": "order"}), "11")
        self.assertEqual(parser._infer_type_code({"question_kind": "multiple"}), "4")

    def test_detect_navigation_action_ignores_hidden_submit_button(self) -> None:
        page = self._FakePage([
            self._FakeButton("提交", False),
            self._FakeButton("下一页", True),
        ])

        self.assertEqual(parser._detect_navigation_action(page), "next")

    def test_normalize_question_keeps_credamo_specific_type(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q3",
                "title": "Q3",
                "question_kind": "dropdown",
                "provider_type": "dropdown",
                "option_texts": ["选项 1", "选项 2", "选项 3"],
                "text_inputs": 0,
                "page": 2,
                "question_id": "question-2",
            },
            fallback_num=3,
        )

        self.assertEqual(question["num"], 3)
        self.assertEqual(question["type_code"], "7")
        self.assertEqual(question["provider_type"], "dropdown")
        self.assertEqual(question["provider_page_id"], "2")
        self.assertEqual(question["options"], 3)

    def test_normalize_question_detects_force_select_instruction(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q7",
                "title": "Q7 本题检测是否认真作答，请选 非常不满意",
                "title_text": "本题检测是否认真作答，请选 非常不满意",
                "question_kind": "single",
                "provider_type": "single",
                "option_texts": ["非常不满意", "不满意", "满意", "非常满意"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-7",
            },
            fallback_num=7,
        )

        self.assertEqual(question["num"], 7)
        self.assertEqual(question["forced_option_index"], 0)
        self.assertEqual(question["forced_option_text"], "非常不满意")

    def test_normalize_question_detects_arithmetic_trap_answer(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q8",
                "title": "Q8 请问100+100等于多少",
                "question_kind": "single",
                "provider_type": "single",
                "option_texts": ["300", "200", "500", "600"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-8",
            },
            fallback_num=8,
        )

        self.assertEqual(question["forced_option_index"], 1)
        self.assertEqual(question["forced_option_text"], "200")

    def test_normalize_question_detects_forced_text_answer(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q10",
                "title": "Q10 本题检测是否认真作答，请输入：“你好”（仅输入引号内文字）",
                "question_kind": "text",
                "provider_type": "text",
                "option_texts": [],
                "text_inputs": 1,
                "page": 1,
                "question_id": "question-10",
            },
            fallback_num=10,
        )

        self.assertEqual(question["forced_texts"], ["你好"])

    def test_normalize_question_detects_title_max_multi_select_limit(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q17",
                "title": "Q17 正餐替代时，你最看重的3个属性？ [至多选3项]",
                "title_text": "正餐替代时，你最看重的3个属性？",
                "tip_text": "[至多选3项]",
                "question_kind": "multiple",
                "provider_type": "multiple",
                "option_texts": ["分量足", "方便", "便宜", "口味好", "可宿舍煮"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-17",
            },
            fallback_num=17,
        )

        self.assertIsNone(question["multi_min_limit"])
        self.assertEqual(question["multi_max_limit"], 3)

    def test_normalize_question_detects_title_min_multi_select_limit(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q30",
                "title": "Q30 哪种周边会让你更想集体购买？ [至少选2项]",
                "title_text": "哪种周边会让你更想集体购买？",
                "tip_text": "[至少选2项]",
                "question_kind": "multiple",
                "provider_type": "multiple",
                "option_texts": ["宿舍小煮锅", "超大分享碗", "非遗文创", "趣味贴纸"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-30",
            },
            fallback_num=30,
        )

        self.assertEqual(question["multi_min_limit"], 2)
        self.assertIsNone(question["multi_max_limit"])

    def test_normalize_question_ignores_multi_select_limit_for_single_choice(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q31",
                "title": "Q31 单选题示例 [至多选2项]",
                "question_kind": "single",
                "provider_type": "single",
                "option_texts": ["愿意", "不愿意", "无所谓"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-31",
            },
            fallback_num=31,
        )

        self.assertIsNone(question["multi_min_limit"])
        self.assertIsNone(question["multi_max_limit"])

    def test_normalize_question_does_not_treat_plain_select_prompt_as_forced_choice(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q2",
                "title": "Q2 请选择你的年龄段",
                "title_text": "请选择你的年龄段",
                "body_text": "请选择你的年龄段 1. 15-25岁 2. 26-35岁 3. 36-45岁 4. 46-55岁 5. 56-65岁 6. 65岁以上",
                "question_kind": "single",
                "provider_type": "single",
                "option_texts": ["15-25岁", "26-35岁", "36-45岁", "46-55岁", "56-65岁", "65岁以上"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-2",
            },
            fallback_num=2,
        )

        self.assertIsNone(question["forced_option_index"])
        self.assertIsNone(question["forced_option_text"])

    def test_normalize_question_does_not_match_option_from_body_text_only(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q5",
                "title": "Q5 请选择你的职业类型",
                "title_text": "请选择你的职业类型",
                "body_text": "请选择你的职业类型 1. 学生 2. 国有企业 3. 事业单位 4. 公务员 5. 民营企业/个体工商户 6. 外资企业 7. 退休人员",
                "question_kind": "single",
                "provider_type": "single",
                "option_texts": ["学生", "国有企业", "事业单位", "公务员", "民营企业/个体工商户", "外资企业", "退休人员"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-5",
            },
            fallback_num=5,
        )

        self.assertIsNone(question["forced_option_index"])
        self.assertIsNone(question["forced_option_text"])

    def test_normalize_question_prefers_full_title_text_and_strips_type_tag(self) -> None:
        question = parser._normalize_question(
            {
                "question_num": "Q7",
                "title": "本题检测是否认真作答",
                "title_full_text": "Q7 [单选题] 本题检测是否认真作答，请选 非常不满意",
                "title_text": "本题检测是否认真作答",
                "question_kind": "single",
                "provider_type": "single",
                "option_texts": ["非常不满意", "不满意", "满意", "非常满意"],
                "text_inputs": 0,
                "page": 1,
                "question_id": "question-7",
            },
            fallback_num=7,
        )

        self.assertEqual(question["num"], 7)
        self.assertEqual(question["title"], "本题检测是否认真作答，请选 非常不满意")
        self.assertEqual(question["forced_option_index"], 0)
        self.assertEqual(question["forced_option_text"], "非常不满意")

    def test_default_builder_locks_credamo_force_select_question(self) -> None:
        entries = build_default_question_entries(
            [
                {
                    "num": 7,
                    "title": "本题检测是否认真作答，请选 非常不满意",
                    "type_code": "3",
                    "options": 4,
                    "option_texts": ["非常不满意", "不满意", "满意", "非常满意"],
                    "provider": "credamo",
                    "provider_question_id": "question-7",
                    "provider_page_id": "1",
                    "forced_option_index": 0,
                    "forced_option_text": "非常不满意",
                }
            ],
            survey_url="https://www.credamo.com/answer.html#/s/demo",
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].question_num, 7)
        self.assertEqual(entries[0].question_type, "single")
        self.assertEqual(entries[0].distribution_mode, "custom")
        self.assertEqual(entries[0].probabilities, [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(entries[0].custom_weights, [1.0, 0.0, 0.0, 0.0])

    def test_default_builder_locks_credamo_forced_text_question(self) -> None:
        entries = build_default_question_entries(
            [
                {
                    "num": 10,
                    "title": "本题检测是否认真作答，请输入：你好",
                    "type_code": "1",
                    "options": 1,
                    "provider": "credamo",
                    "provider_question_id": "question-10",
                    "provider_page_id": "1",
                    "forced_texts": ["你好"],
                    "is_text_like": True,
                    "text_inputs": 1,
                }
            ],
            survey_url="https://www.credamo.com/answer.html#/s/demo",
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].question_num, 10)
        self.assertEqual(entries[0].question_type, "text")
        self.assertEqual(entries[0].texts, ["你好"])

    def test_collect_current_page_until_stable_keeps_revealed_questions(self) -> None:
        q8 = {"provider_question_id": "question-8", "num": 8, "title": "Q8"}
        q9 = {"provider_question_id": "question-9", "num": 9, "title": "Q9"}
        page = object()

        def fake_prime(_page, questions, primed_keys=None):
            primed = primed_keys if primed_keys is not None else set()
            count = 0
            for question in questions:
                key = parser._question_dedupe_key(question)
                if key in primed:
                    continue
                primed.add(key)
                count += 1
            return count

        with patch("credamo.provider.parser._extract_questions_from_current_page", side_effect=[[q8], [q8, q9]]), \
             patch("credamo.provider.parser._prime_page_for_next", side_effect=fake_prime), \
             patch("credamo.provider.parser._wait_for_dynamic_questions", side_effect=[[q8, q9], [q8, q9]]):
            current, discovered = parser._collect_current_page_until_stable(page, page_number=1)

        self.assertEqual([question["num"] for question in current], [8, 9])
        self.assertEqual([question["num"] for question in discovered], [8, 9])

    def test_question_dedupe_key_does_not_trust_reused_credamo_dom_id(self) -> None:
        q8 = {
            "provider_page_id": "2",
            "provider_question_id": "question-0",
            "num": 8,
            "title": "请问100+100等于多少",
        }
        q10 = {
            "provider_page_id": "4",
            "provider_question_id": "question-0",
            "num": 10,
            "title": "本题检测是否认真作答，请输入：你好",
        }

        self.assertNotEqual(parser._question_dedupe_key(q8), parser._question_dedupe_key(q10))

    def test_prime_question_uses_forced_scale_answer(self) -> None:
        page = object()
        root = object()
        question = {
            "provider_type": "scale",
            "options": 7,
            "forced_option_index": 0,
        }

        with patch("credamo.provider.runtime._answer_scale", return_value=True) as scale_mock:
            parser._prime_question_for_next(page, root, question)

        scale_mock.assert_called_once_with(page, root, [100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_order_entry_is_exposed_to_runtime_mapping(self) -> None:
        entry = QuestionEntry(
            question_type="order",
            probabilities=-1,
            option_count=4,
            question_num=6,
            question_title="排序题",
            survey_provider="credamo",
        )
        ctx = SimpleNamespace()

        configure_probabilities([entry], ctx)

        self.assertEqual(ctx.question_config_index_map[6], ("order", -1))


if __name__ == "__main__":
    unittest.main()
