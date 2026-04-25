from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from credamo.provider import parser, runtime
from software.core.questions.default_builder import build_default_question_entries
from software.core.questions.normalization import configure_probabilities
from software.core.questions.schema import QuestionEntry


class CredamoRuntimeTests(unittest.TestCase):
    class _FakeQuestionRoot:
        def __init__(self, question_num: int) -> None:
            self.question_num = question_num

    class _FakeChoiceElement:
        def __init__(self, text: str = "") -> None:
            self.checked = False
            self.text = text

        def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
            return None

        def click(self, timeout: int = 0) -> None:
            self.checked = True

        def text_content(self, timeout: int = 0) -> str:
            return self.text

    class _FakeDropdownInput:
        def __init__(self) -> None:
            self.value = ""

        def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
            return None

        def click(self, timeout: int = 0) -> None:
            return None

        def focus(self) -> None:
            return None

    class _FakeDropdownLocator:
        def __init__(self, count_value: int) -> None:
            self._count_value = count_value

        def count(self) -> int:
            return self._count_value

    def test_click_submit_waits_until_dynamic_button_appears(self) -> None:
        attempts = iter([False, False, True])

        with patch("credamo.provider.runtime._click_submit_once", side_effect=lambda _page: next(attempts)), \
             patch("credamo.provider.runtime.time.sleep") as sleep_mock:
            clicked = runtime._click_submit(object(), timeout_ms=2000)

        self.assertTrue(clicked)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_click_submit_stops_waiting_when_abort_requested(self) -> None:
        stop_signal = threading.Event()

        def abort_after_first_wait(_seconds: float | None = None) -> bool:
            stop_signal.set()
            return True

        with patch("credamo.provider.runtime._click_submit_once", return_value=False):
            setattr(stop_signal, "wait", abort_after_first_wait)
            clicked = runtime._click_submit(object(), stop_signal, timeout_ms=2000)

        self.assertFalse(clicked)

    def test_brush_credamo_walks_next_pages_before_submit(self) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        config = SimpleNamespace(
            question_config_index_map={
                1: ("single", 0),
                2: ("dropdown", 0),
                3: ("order", -1),
            },
            single_prob=[-1],
            droplist_prob=[-1],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        driver = SimpleNamespace(page=object())
        roots_page1 = [self._FakeQuestionRoot(1), self._FakeQuestionRoot(2)]
        roots_page2 = [self._FakeQuestionRoot(3)]

        with patch("credamo.provider.runtime._wait_for_question_roots", side_effect=[roots_page1, roots_page2]), \
             patch("credamo.provider.runtime._wait_for_dynamic_question_roots", side_effect=[roots_page1, roots_page2]), \
             patch("credamo.provider.runtime._question_number_from_root", side_effect=lambda _page, root, _fallback: root.question_num), \
             patch("credamo.provider.runtime._root_text", side_effect=lambda _page, root: f"Q{root.question_num}"), \
             patch("credamo.provider.runtime._navigation_action", side_effect=["next", "submit"]), \
             patch("credamo.provider.runtime._question_signature", side_effect=[(("question-1", "page1"),)]), \
             patch("credamo.provider.runtime._wait_for_page_change", return_value=True), \
             patch("credamo.provider.runtime._click_navigation", return_value=True) as click_navigation_mock, \
             patch("credamo.provider.runtime._click_submit", return_value=True) as click_submit_mock, \
             patch("credamo.provider.runtime._answer_single_like", return_value=True) as single_mock, \
             patch("credamo.provider.runtime._answer_dropdown", return_value=True) as dropdown_mock, \
             patch("credamo.provider.runtime._answer_order", return_value=True) as order_mock, \
             patch("credamo.provider.runtime.simulate_answer_duration_delay", return_value=False), \
             patch("credamo.provider.runtime.time.sleep"):
            result = runtime.brush_credamo(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name="Worker-1",
            )

        self.assertTrue(result)
        self.assertEqual(single_mock.call_count, 1)
        self.assertEqual(dropdown_mock.call_count, 1)
        self.assertEqual(order_mock.call_count, 1)
        click_navigation_mock.assert_called_once_with(driver.page, "next")
        click_submit_mock.assert_called_once_with(driver.page, stop_signal)

    def test_brush_credamo_answers_questions_revealed_on_same_page(self) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        config = SimpleNamespace(
            question_config_index_map={
                8: ("single", 0),
                9: ("scale", 0),
            },
            single_prob=[[0.0, 1.0, 0.0, 0.0]],
            droplist_prob=[],
            scale_prob=[[100.0, 0.0, 0.0, 0.0, 0.0]],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        driver = SimpleNamespace(page=object())
        q8 = self._FakeQuestionRoot(8)
        q9 = self._FakeQuestionRoot(9)
        roots_initial = [q8]
        roots_after_reveal = [q8, q9]

        with patch("credamo.provider.runtime._wait_for_question_roots", return_value=roots_initial), \
             patch("credamo.provider.runtime._wait_for_dynamic_question_roots", side_effect=[roots_after_reveal, roots_after_reveal]), \
             patch("credamo.provider.runtime._question_number_from_root", side_effect=lambda _page, root, _fallback: root.question_num), \
             patch("credamo.provider.runtime._root_text", side_effect=lambda _page, root: f"Q{root.question_num}"), \
             patch("credamo.provider.runtime._navigation_action", return_value="submit"), \
             patch("credamo.provider.runtime._click_submit", return_value=True), \
             patch("credamo.provider.runtime._answer_single_like", return_value=True) as single_mock, \
             patch("credamo.provider.runtime._answer_scale", return_value=True) as scale_mock, \
             patch("credamo.provider.runtime.simulate_answer_duration_delay", return_value=False), \
             patch("credamo.provider.runtime.time.sleep"):
            result = runtime.brush_credamo(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name="Worker-1",
            )

        self.assertTrue(result)
        self.assertEqual(single_mock.call_count, 1)
        self.assertEqual(scale_mock.call_count, 1)

    def test_answer_single_like_does_not_report_success_when_target_stays_unchecked(self) -> None:
        input_element = self._FakeChoiceElement()
        root = SimpleNamespace()
        page = SimpleNamespace(
            evaluate=lambda script, element: bool(getattr(element, "checked", False)),
        )

        with patch("credamo.provider.runtime._option_inputs", return_value=[input_element]), \
             patch("credamo.provider.runtime._option_click_targets", return_value=[]), \
             patch("credamo.provider.runtime._click_element", return_value=True), \
             patch("credamo.provider.runtime.normalize_droplist_probs", return_value=[100.0]), \
             patch("credamo.provider.runtime.weighted_index", return_value=0):
            answered = runtime._answer_single_like(page, root, [100.0], 1)

        self.assertFalse(answered)

    def test_answer_single_like_prefers_forced_text_match_over_weight_index(self) -> None:
        wrong = self._FakeChoiceElement("300")
        correct = self._FakeChoiceElement("200")
        root = SimpleNamespace()
        page = SimpleNamespace(
            evaluate=lambda script, element: bool(getattr(element, "checked", False)),
        )

        with patch("credamo.provider.runtime._option_inputs", return_value=[wrong, correct]), \
             patch("credamo.provider.runtime._option_click_targets", return_value=[]), \
             patch("credamo.provider.runtime._resolve_forced_choice_index", return_value=1), \
             patch("credamo.provider.runtime.normalize_droplist_probs", return_value=[100.0, 0.0]), \
             patch("credamo.provider.runtime.weighted_index", return_value=0):
            answered = runtime._answer_single_like(page, root, [100.0, 0.0], 2)

        self.assertTrue(answered)
        self.assertFalse(wrong.checked)
        self.assertTrue(correct.checked)

    def test_answer_dropdown_uses_keyboard_selection_for_credamo_select(self) -> None:
        trigger = self._FakeDropdownInput()
        value_input = self._FakeDropdownInput()
        locator = self._FakeDropdownLocator(4)

        class _FakeKeyboard:
            def __init__(self, input_element: "CredamoRuntimeTests._FakeDropdownInput") -> None:
                self.input_element = input_element
                self.arrow_down_count = 0

            def press(self, key: str) -> None:
                if key == "ArrowDown":
                    self.arrow_down_count += 1
                elif key == "Enter" and self.arrow_down_count > 0:
                    self.input_element.value = f"选项 {self.arrow_down_count}"

        class _FakeRoot:
            def query_selector(self, selector: str):
                if selector in {".pc-dropdown .el-input", ".el-input"}:
                    return trigger
                if selector == ".el-input__inner":
                    return value_input
                return None

        def _evaluate(script: str, element) -> object:
            if "el.value" in script:
                return getattr(element, "value", "")
            return True

        page = SimpleNamespace(
            evaluate=_evaluate,
            wait_for_timeout=lambda _ms: None,
            locator=lambda _selector: locator,
            keyboard=_FakeKeyboard(value_input),
        )

        with patch("credamo.provider.runtime._click_element", return_value=True), \
             patch("credamo.provider.runtime.normalize_droplist_probs", return_value=[0.0, 100.0, 0.0, 0.0]), \
             patch("credamo.provider.runtime.weighted_index", return_value=1):
            answered = runtime._answer_dropdown(page, _FakeRoot(), [0.0, 100.0, 0.0, 0.0])

        self.assertTrue(answered)
        self.assertEqual(value_input.value, "选项 2")


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
