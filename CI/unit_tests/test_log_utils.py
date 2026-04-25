from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from software.logging.log_utils import log_deduped_message, reset_deduped_log_message


class LogUtilsTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_deduped_log_message("test_random_ip_sync_failure")

    def test_log_deduped_message_only_logs_same_message_once(self) -> None:
        with patch("software.logging.log_utils.logging.log") as mock_log:
            first = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)
            second = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)

        self.assertTrue(first)
        self.assertFalse(second)
        mock_log.assert_called_once_with(logging.INFO, "同步随机IP额度失败：网络超时")

    def test_reset_deduped_log_message_allows_same_message_to_log_again(self) -> None:
        with patch("software.logging.log_utils.logging.log") as mock_log:
            first = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)
            reset_deduped_log_message("test_random_ip_sync_failure")
            second = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(mock_log.call_count, 2)
