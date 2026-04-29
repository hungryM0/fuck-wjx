import random
import unittest

from credamo.provider import runtime_answerers, runtime_dom


class _FakePage:
    def evaluate(self, _script, _root):
        return "  第 1 题   测试题面  "


class _FakeRoot:
    def __init__(self, attrs):
        self._attrs = dict(attrs)

    def get_attribute(self, name):
        return self._attrs.get(name)


class CredamoRuntimeHelperTests(unittest.TestCase):
    def test_loading_shell_detection_covers_empty_answer_page(self):
        self.assertTrue(runtime_dom._looks_like_loading_shell("答卷", ""))
        self.assertTrue(runtime_dom._looks_like_loading_shell("答卷", "载入中..."))
        self.assertFalse(runtime_dom._looks_like_loading_shell("答卷", "第 1 题 请选择一个最符合你的选项并继续作答"))

    def test_runtime_question_key_prefers_stable_dom_id(self):
        root = _FakeRoot({"id": "q-123"})

        self.assertEqual(runtime_dom._runtime_question_key(_FakePage(), root, 1), "id:q-123")

    def test_runtime_question_key_falls_back_to_number_and_text(self):
        root = _FakeRoot({})

        self.assertEqual(
            runtime_dom._runtime_question_key(_FakePage(), root, 3),
            "num:3|text:  第 1 题   测试题面  ",
        )

    def test_positive_multiple_indexes_never_returns_empty_selection(self):
        random.seed(1)

        selected = runtime_answerers._positive_multiple_indexes([0, 0, 0], 3)

        self.assertEqual(len(selected), 1)
        self.assertTrue(0 <= selected[0] < 3)

    def test_positive_multiple_indexes_uses_positive_weights(self):
        random.seed(2)

        selected = runtime_answerers._positive_multiple_indexes([0, 100, 0], 3)

        self.assertEqual(selected, [1])


if __name__ == "__main__":
    unittest.main()
