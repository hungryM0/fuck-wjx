import unittest
from unittest.mock import patch

from credamo.provider import submission


class _FakeDriver:
    def __init__(self, body_text: str = "") -> None:
        self.body_text = body_text

    def execute_script(self, script: str):
        if "document.body ? document.body.innerText" in script:
            return self.body_text
        return ""


class CredamoSubmissionTests(unittest.TestCase):
    def test_submission_requires_verification_ignores_selection_validation_feedback(self) -> None:
        driver = _FakeDriver(body_text="问卷正文")

        with patch(
            "credamo.provider.submission._visible_feedback_text",
            return_value="本题至少选择2项后才能继续",
        ):
            self.assertFalse(submission.submission_requires_verification(driver))

    def test_submission_requires_verification_detects_real_verification_feedback(self) -> None:
        driver = _FakeDriver(body_text="问卷正文")

        with patch(
            "credamo.provider.submission._visible_feedback_text",
            return_value="请完成验证码验证后继续提交",
        ):
            self.assertTrue(submission.submission_requires_verification(driver))

    def test_submission_requires_verification_can_fall_back_to_body_text(self) -> None:
        driver = _FakeDriver(body_text="系统提示：请先完成滑块验证")

        with patch("credamo.provider.submission._visible_feedback_text", return_value=""):
            self.assertTrue(submission.submission_requires_verification(driver))


if __name__ == "__main__":
    unittest.main()
