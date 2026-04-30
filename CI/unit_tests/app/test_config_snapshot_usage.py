from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from software.core.config.schema import RuntimeConfig
from software.core.questions.schema import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.dashboard.parts.config_io import DashboardConfigIOMixin
from software.ui.pages.workbench.dashboard.parts.run_actions import DashboardRunActionsMixin
from software.ui.shell.main_window_parts.lifecycle import MainWindowLifecycleMixin


class _DummyProgressBar:
    def setValue(self, _value: int) -> None:
        pass


class _DummyLabel:
    def setText(self, _value: str) -> None:
        pass


class _FakeQuestionPage:
    def __init__(self) -> None:
        self._entries = [
            QuestionEntry(
                question_type="single",
                probabilities=[100.0],
                texts=["A"],
                option_count=1,
                question_num=1,
            )
        ]
        self.questions_info = [
            SurveyQuestionMeta(
                num=1,
                title="题目一",
                type_code="3",
                provider_question_id="q1",
            )
        ]

    def get_entries(self):
        return list(self._entries)


class _FakeRunController:
    def __init__(self) -> None:
        self.running = False
        self.started_config = None
        self.config = None
        self.saved_path = None

    def stop_run(self) -> None:
        pass

    def start_run(self, config: RuntimeConfig) -> None:
        self.started_config = config

    def save_current_config(self, path: str) -> str:
        self.saved_path = path
        return path


class _FakeRunActionsHost(DashboardRunActionsMixin):
    def __init__(self) -> None:
        self.controller = _FakeRunController()
        self.question_page = _FakeQuestionPage()
        self.runtime_page = SimpleNamespace()
        self.strategy_page = SimpleNamespace()
        self.target_spin = SimpleNamespace()
        self.thread_spin = SimpleNamespace()
        self.random_ip_cb = SimpleNamespace()
        self.progress_bar = _DummyProgressBar()
        self.progress_pct = _DummyLabel()
        self.status_label = _DummyLabel()
        self.count_label = _DummyLabel()
        self.title_label = _DummyLabel()
        self.url_edit = SimpleNamespace()
        self._survey_title = "测试问卷"
        self._completion_notified = False
        self._last_progress = 0

    def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False):
        del text, level, duration, show_progress
        return None

    def _sync_start_button_state(self, running: bool | None = None) -> None:
        del running

    def _refresh_entry_table(self) -> None:
        pass

    def _refresh_ip_cost_infobar(self) -> None:
        pass

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        del enabled

    def window(self):
        return None

    def _build_config(self) -> RuntimeConfig:
        return RuntimeConfig(target=2, threads=1)


class _FakeConfigIOHost(DashboardConfigIOMixin):
    def __init__(self) -> None:
        self.controller = _FakeRunController()
        self.question_page = _FakeQuestionPage()
        self.strategy_page = SimpleNamespace()
        self.runtime_page = SimpleNamespace()
        self.config_drawer = SimpleNamespace()
        self._survey_title = "测试问卷"

    def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False):
        del text, level, duration, show_progress
        return None

    def apply_config(self, cfg: RuntimeConfig) -> None:
        del cfg

    def _build_config(self) -> RuntimeConfig:
        return RuntimeConfig(target=3, threads=1)

    def _refresh_entry_table(self) -> None:
        pass

    def update_question_meta(self, title: str, count: int) -> None:
        del title, count

    def _sync_start_button_state(self, running: bool | None = None) -> None:
        del running


class _FakeLifecycleHost(MainWindowLifecycleMixin):
    def __init__(self) -> None:
        self.dashboard = SimpleNamespace(_build_config=lambda: RuntimeConfig(target=4, threads=2))
        self.question_page = _FakeQuestionPage()
        self.controller = _FakeRunController()


class ConfigSnapshotUsageTests(unittest.TestCase):
    def test_run_actions_start_uses_shared_snapshot_helper(self) -> None:
        host = _FakeRunActionsHost()
        snapshot = RuntimeConfig(target=2, threads=1, question_entries=host.question_page.get_entries(), questions_info=host.question_page.questions_info)

        with patch(
            "software.ui.pages.workbench.dashboard.parts.run_actions.build_runtime_config_snapshot",
            return_value=snapshot,
        ) as snapshot_helper:
            host._on_start_clicked()

        self.assertIs(host.controller.started_config, snapshot)
        self.assertEqual(snapshot_helper.call_count, 1)
        self.assertEqual(snapshot_helper.call_args.kwargs["question_entries"], host.question_page.get_entries())
        self.assertEqual(snapshot_helper.call_args.kwargs["questions_info"], host.question_page.questions_info)

    def test_config_save_uses_shared_snapshot_helper(self) -> None:
        host = _FakeConfigIOHost()
        snapshot = RuntimeConfig(target=3, threads=1, question_entries=host.question_page.get_entries(), questions_info=host.question_page.questions_info)

        with patch(
            "software.ui.pages.workbench.dashboard.parts.config_io.build_runtime_config_snapshot",
            return_value=snapshot,
        ) as snapshot_helper, patch(
            "software.ui.pages.workbench.dashboard.parts.config_io.QFileDialog.getSaveFileName",
            return_value=("D:/demo.json", "JSON 文件 (*.json)"),
        ):
            host._on_save_config()

        self.assertIs(host.controller.config, snapshot)
        self.assertEqual(host.controller.saved_path, "D:/demo.json")
        self.assertEqual(snapshot_helper.call_count, 1)
        self.assertEqual(snapshot_helper.call_args.kwargs["question_entries"], host.question_page.get_entries())
        self.assertEqual(snapshot_helper.call_args.kwargs["questions_info"], host.question_page.questions_info)

    def test_lifecycle_snapshot_collection_uses_shared_snapshot_helper(self) -> None:
        host = _FakeLifecycleHost()
        snapshot = RuntimeConfig(target=4, threads=2, question_entries=host.question_page.get_entries(), questions_info=host.question_page.questions_info)

        with patch(
            "software.ui.shell.main_window_parts.lifecycle.build_runtime_config_snapshot",
            return_value=snapshot,
        ) as snapshot_helper:
            result = host._collect_current_config_snapshot()

        self.assertIs(result, snapshot)
        self.assertIs(host.controller.config, snapshot)
        self.assertEqual(snapshot_helper.call_count, 1)
        self.assertEqual(snapshot_helper.call_args.kwargs["question_entries"], host.question_page.get_entries())
        self.assertEqual(snapshot_helper.call_args.kwargs["questions_info"], host.question_page.questions_info)


if __name__ == "__main__":
    unittest.main()
