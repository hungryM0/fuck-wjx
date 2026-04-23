#!/usr/bin/env python
"""真实问卷链接解析回归测试。"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Tuple

from tencent.provider.parser import parse_qq_survey
from wjx.provider.parser import parse_wjx_survey

WJX_SURVEY_URL = "https://v.wjx.cn/vm/tgRSrWd.aspx"
QQ_SURVEY_URL = "https://wj.qq.com/s2/26070328/fa89/"


def _question_by_num(questions: list[dict], question_num: int) -> dict:
    for item in questions:
        if int(item.get("num") or 0) == int(question_num):
            return item
    raise AssertionError(f"未找到第 {question_num} 题")


class LiveSurveyParserRegressionTests(unittest.TestCase):
    maxDiff = None

    def _run_with_retry(self, parser, url: str, attempts: int = 2) -> Tuple[list[dict], str]:
        last_error: Exception | None = None
        for _ in range(max(1, attempts)):
            try:
                return parser(url)
            except Exception as exc:  # pragma: no cover - 真实网络失败仅用于重试
                last_error = exc
        if last_error is not None:
            raise last_error
        raise AssertionError("解析器未返回结果")

    def test_wjx_live_parser_regression(self) -> None:
        questions, title = self._run_with_retry(parse_wjx_survey, WJX_SURVEY_URL)

        self.assertEqual(title, "example")
        self.assertEqual(len(questions), 11)

        q1 = _question_by_num(questions, 1)
        self.assertEqual(q1["type_code"], "3")
        self.assertEqual(q1["options"], 2)
        self.assertTrue(q1["has_jump"])
        self.assertEqual(q1["jump_rules"][0]["jumpto"], 5)
        self.assertEqual(len(q1["option_texts"]), 2)
        self.assertTrue(str(q1["option_texts"][0] or "").strip())
        self.assertEqual(q1["option_texts"][1], "我才是B")

        q2 = _question_by_num(questions, 2)
        self.assertEqual(q2["type_code"], "11")
        self.assertEqual(q2["options"], 5)

        q3 = _question_by_num(questions, 3)
        self.assertEqual(q3["type_code"], "5")
        self.assertEqual(q3["options"], 11)
        self.assertEqual(q3["option_texts"][0], "不可能")
        self.assertEqual(q3["option_texts"][-1], "极有可能")

        q4 = _question_by_num(questions, 4)
        self.assertEqual(q4["type_code"], "1")
        self.assertTrue(q4["is_text_like"])
        self.assertEqual(q4["text_inputs"], 1)

        q6 = _question_by_num(questions, 6)
        self.assertEqual(q6["type_code"], "6")
        self.assertEqual(q6["rows"], 2)
        self.assertEqual(q6["row_texts"], ["外观", "功能"])

        q8 = _question_by_num(questions, 8)
        self.assertEqual(q8["type_code"], "5")
        self.assertTrue(q8["is_rating"])
        self.assertEqual(q8["rating_max"], 5)
        self.assertEqual(q8["text_inputs"], 5)

        q9 = _question_by_num(questions, 9)
        self.assertEqual(q9["forced_option_index"], 0)
        self.assertEqual(q9["forced_option_text"], "A")

        q11 = _question_by_num(questions, 11)
        self.assertEqual(q11["type_code"], "9")
        self.assertTrue(q11["is_multi_text"])
        self.assertTrue(q11["is_text_like"])
        self.assertEqual(q11["text_input_labels"], ["填空1", "填空2", "填空3"])

    def test_qq_live_parser_regression(self) -> None:
        questions, title = self._run_with_retry(parse_qq_survey, QQ_SURVEY_URL)

        self.assertEqual(title, "大学生就业意向调研问卷")
        self.assertEqual(len(questions), 17)

        q1 = _question_by_num(questions, 1)
        self.assertEqual(q1["type_code"], "3")
        self.assertEqual(q1["provider_type"], "radio")
        self.assertEqual(q1["options"], 3)
        self.assertEqual(q1["page"], 1)

        q2 = _question_by_num(questions, 2)
        self.assertEqual(q2["type_code"], "7")
        self.assertEqual(q2["provider_type"], "select")
        self.assertEqual(q2["options"], 10)

        q4 = _question_by_num(questions, 4)
        self.assertEqual(q4["type_code"], "6")
        self.assertEqual(q4["provider_type"], "matrix_star")
        self.assertEqual(q4["options"], 5)
        self.assertEqual(q4["rows"], 5)
        self.assertEqual(q4["row_texts"][0], "薪资福利")

        q5 = _question_by_num(questions, 5)
        self.assertEqual(q5["type_code"], "4")
        self.assertEqual(q5["provider_type"], "checkbox")
        self.assertEqual(q5["multi_min_limit"], 1)
        self.assertEqual(q5["options"], 7)

        q7 = _question_by_num(questions, 7)
        self.assertEqual(q7["type_code"], "1")
        self.assertTrue(q7["is_text_like"])
        self.assertEqual(q7["provider_type"], "text")

        q8 = _question_by_num(questions, 8)
        self.assertEqual(q8["type_code"], "5")
        self.assertTrue(q8["is_rating"])
        self.assertEqual(q8["provider_type"], "nps")
        self.assertEqual(q8["options"], 11)

        q9 = _question_by_num(questions, 9)
        self.assertEqual(q9["type_code"], "6")
        self.assertEqual(q9["provider_type"], "matrix_radio")
        self.assertEqual(q9["rows"], 5)
        self.assertEqual(q9["options"], 4)

        q12 = _question_by_num(questions, 12)
        self.assertEqual(q12["page"], 2)
        self.assertEqual(q12["provider_page_id"], "p-2-xIOc")
        self.assertEqual(q12["multi_min_limit"], 1)

        q13 = _question_by_num(questions, 13)
        self.assertEqual(q13["provider_type"], "textarea")
        self.assertEqual(q13["type_code"], "1")
        self.assertTrue(q13["is_text_like"])

        q16 = _question_by_num(questions, 16)
        self.assertEqual(q16["provider_type"], "nps")
        self.assertEqual(q16["options"], 11)
        self.assertEqual(q16["page"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
