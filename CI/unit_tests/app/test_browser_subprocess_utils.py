from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from software.app.browser_probe import _kill_process_tree
from software.network.browser.session import PlaywrightDriver
from software.network.browser.subprocess_utils import build_local_text_subprocess_kwargs
from software.network.browser.transient import list_browser_pids


class _RunningProcess:
    pid = 4321

    def __init__(self) -> None:
        self.killed = False

    def poll(self):
        return None

    def kill(self) -> None:
        self.killed = True


class BrowserSubprocessUtilsTests(unittest.TestCase):
    def test_build_local_text_subprocess_kwargs_prefers_locale_encoding(self) -> None:
        with patch("software.network.browser.subprocess_utils.locale.getencoding", return_value="cp936"), \
             patch("software.network.browser.subprocess_utils.locale.getpreferredencoding", return_value="utf-8"):
            kwargs = build_local_text_subprocess_kwargs()

        self.assertEqual(kwargs["text"], True)
        self.assertEqual(kwargs["errors"], "replace")
        self.assertEqual(kwargs["encoding"], "cp936")

    def test_kill_process_tree_uses_local_text_decode_settings(self) -> None:
        process = _RunningProcess()

        with patch("software.app.browser_probe.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run_mock, \
             patch("software.app.browser_probe.build_local_text_subprocess_kwargs", return_value={"text": True, "encoding": "cp936", "errors": "replace"}):
            _kill_process_tree(process)

        self.assertTrue(process.killed)
        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs["encoding"], "cp936")
        self.assertEqual(kwargs["errors"], "replace")
        self.assertEqual(kwargs["text"], True)

    def test_list_browser_pids_uses_local_text_decode_settings(self) -> None:
        tasklist_output = '"msedge.exe","1234","Console","1","12,000 K"\n'

        with patch("software.network.browser.transient.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=tasklist_output, stderr="")) as run_mock, \
             patch("software.network.browser.transient.build_local_text_subprocess_kwargs", return_value={"text": True, "encoding": "cp936", "errors": "replace"}):
            pids = list_browser_pids()

        self.assertEqual(pids, {1234})
        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs["encoding"], "cp936")
        self.assertEqual(kwargs["errors"], "replace")
        self.assertEqual(kwargs["text"], True)

    def test_force_terminate_browser_process_tree_uses_local_text_decode_settings(self) -> None:
        driver = object.__new__(PlaywrightDriver)
        driver.browser_pids = {2468}
        driver._browser = None

        with patch("software.network.browser.session.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run_mock, \
             patch("software.network.browser.session.build_local_text_subprocess_kwargs", return_value={"text": True, "encoding": "cp936", "errors": "replace"}):
            terminated = PlaywrightDriver._force_terminate_browser_process_tree(driver)

        self.assertTrue(terminated)
        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs["encoding"], "cp936")
        self.assertEqual(kwargs["errors"], "replace")
        self.assertEqual(kwargs["text"], True)


if __name__ == "__main__":
    unittest.main()
