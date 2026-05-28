from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from software.core.config.schema import RuntimeConfig
from software.core.questions.config import QuestionEntry
from software.app.config import HTTP_MAX_THREADS
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.dashboard.page import DashboardPage
from software.ui.pages.workbench.reverse_fill.page import ReverseFillPage
from software.ui.pages.workbench.runtime_panel.main import RuntimePage
from software.ui.pages.workbench.session import WorkbenchState
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage


class _FakeController(QObject):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    runtimeUiStateChanged = Signal(dict)
    runStateChanged = Signal(bool)
    randomIpLoadingChanged = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.running = False
        self._starting = False
        self.adapter = object()
        self.survey_provider = "wjx"
        self.state = {
            "target": 10,
            "threads": 2,
            "random_ip_enabled": False,
            "proxy_source": "default",
            "answer_duration": (60, 120),
            "answer_datetime_window": ("", ""),
        }
        self.runtime_updates: list[dict] = []
        self.parse_calls: list[str] = []
        self.stop_calls = 0
        self.resume_calls = 0

    def get_runtime_ui_state(self):
        return dict(self.state)

    def set_runtime_ui_state(self, emit: bool = True, **updates):
        self.state.update(updates)
        self.runtime_updates.append(dict(updates))
        if emit:
            self.runtimeUiStateChanged.emit(dict(self.state))
        return dict(self.state)

    def sync_runtime_ui_state_from_config(self, cfg: RuntimeConfig, *, emit: bool = True):
        self.state.update(
            {
                "target": cfg.target,
                "threads": cfg.threads,
                "random_ip_enabled": cfg.random_ip_enabled,
                "proxy_source": cfg.proxy_source,
                "answer_duration": cfg.answer_duration,
                "answer_datetime_window": cfg.answer_datetime_window,
            }
        )
        if emit:
            self.runtimeUiStateChanged.emit(dict(self.state))
        return dict(self.state)

    def is_initializing(self) -> bool:
        return False

    def request_toggle_random_ip(self, enabled: bool, **_kwargs) -> bool:
        self.set_runtime_ui_state(random_ip_enabled=bool(enabled))
        return True

    def parse_survey(self, url: str) -> None:
        self.parse_calls.append(url)

    def stop_run(self) -> None:
        self.stop_calls += 1

    def resume_run(self) -> None:
        self.resume_calls += 1

    def refresh_random_ip_counter(self, **_kwargs) -> None:
        return None


def _patch_page_dependencies(monkeypatch) -> None:
    import software.ui.pages.workbench.dashboard.page as dashboard_module
    import software.ui.pages.workbench.dashboard.parts.progress as progress_module
    import software.ui.pages.workbench.dashboard.parts.random_ip as dash_random_ip
    import software.ui.pages.workbench.runtime_panel.ai as ai_module
    import software.ui.pages.workbench.runtime_panel.proxy_sync as runtime_proxy_sync
    import software.ui.pages.workbench.runtime_panel.random_ip_card as random_ip_card
    import software.ui.pages.workbench.shared.clipboard as clipboard_module

    monkeypatch.setattr(
        random_ip_card,
        "load_area_codes",
        lambda supported_only=True: [
            {"code": "110000", "name": "北京", "cities": [{"code": "110100", "name": "北京"}]}
        ],
    )
    monkeypatch.setattr(random_ip_card, "load_supported_area_codes", lambda: ({"110000", "110100"}, False))
    monkeypatch.setattr(random_ip_card, "load_benefit_supported_areas", lambda force_refresh=False: [])
    proxy_settings = SimpleNamespace(
        source="default",
        custom_api_url="",
        default_area_code="",
        benefit_area_code="",
    )
    monkeypatch.setattr(random_ip_card, "get_proxy_settings", lambda: proxy_settings)
    monkeypatch.setattr(random_ip_card, "apply_proxy_area_code", lambda _code: None)
    monkeypatch.setattr(random_ip_card, "apply_custom_proxy_api", lambda _url: None)
    monkeypatch.setattr(random_ip_card, "test_custom_proxy_api", lambda _url: (True, "", []))

    monkeypatch.setattr(ai_module, "get_ai_settings", lambda: {"ai_mode": "free"})
    monkeypatch.setattr(ai_module, "save_ai_settings", lambda **_kwargs: None)
    monkeypatch.setattr(ai_module, "get_default_system_prompt", lambda _mode="free": "默认提示")
    monkeypatch.setattr(runtime_proxy_sync, "apply_proxy_source_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_proxy_sync, "apply_custom_proxy_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_proxy_sync, "get_proxy_minute_by_answer_seconds", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(dashboard_module, "load_shop_icon", lambda: None)
    monkeypatch.setattr(dash_random_ip, "load_shop_icon", lambda: None)
    monkeypatch.setattr(dash_random_ip, "get_session_snapshot", lambda: {"authenticated": False})
    monkeypatch.setattr(dash_random_ip, "has_authenticated_session", lambda: False)
    monkeypatch.setattr(dash_random_ip, "get_random_ip_counter_snapshot_local", lambda: (0, 0, False))
    monkeypatch.setattr(DashboardPage, "_init_random_ip_status_refresh", lambda self: None)
    monkeypatch.setattr(clipboard_module.SurveyClipboardMixin, "_on_clipboard_changed", lambda self: None)
    monkeypatch.setattr(progress_module, "log_action", lambda *_args, **_kwargs: None)


def test_runtime_page_builds_and_syncs_config_without_network(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()

    page = RuntimePage(controller)
    qtbot.addWidget(page)

    cfg = RuntimeConfig(target=7, threads=99, random_ip_enabled=True)
    page.apply_config(cfg)
    page.update_config(cfg)

    assert page.target_card.spinBox.value() == 7
    assert page.thread_card.slider.slider.maximum() == HTTP_MAX_THREADS
    assert cfg.target == 7
    assert cfg.threads <= HTTP_MAX_THREADS
    assert cfg.answer_datetime_window == ("", "")
    assert cfg.ai_system_prompt


def test_strategy_page_builds_rules_and_dimension_sections(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    page = QuestionStrategyPage()
    qtbot.addWidget(page)

    info = [
        SurveyQuestionMeta(num=1, title="性别", type_code="3", option_texts=["男", "女"]),
        SurveyQuestionMeta(num=2, title="满意度", type_code="3", option_texts=["高", "低"]),
    ]
    page.set_questions_info(info)
    page.set_rules(
        [
            {
                "condition_question_num": 1,
                "condition_option_indices": [0],
                "target_question_num": 2,
                "target_option_indices": [1],
                "condition_mode": "selected",
                "action_mode": "must_select",
            }
        ]
    )
    page.set_entries([QuestionEntry("single", [1, 1], question_num=1, dimension="体验")], info)
    page.set_dimension_groups(["体验", "未分组", "体验"])
    page._on_segment_changed("dimensions")

    assert page.rule_panel.table.rowCount() == 1
    assert page.rule_panel.table.item(0, 0).text().startswith("第1题")
    assert page.get_dimension_groups() == ["体验"]
    assert page.stack.currentWidget() is page.dimension_panel


def test_reverse_fill_page_builds_and_updates_config(monkeypatch, qtbot, tmp_path) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    page = ReverseFillPage(controller)
    qtbot.addWidget(page)
    xlsx = tmp_path / "data.xlsx"
    xlsx.write_text("placeholder", encoding="utf-8")

    page.url_edit.setText("https://www.wjx.cn/vm/demo.aspx")
    page.parse_btn.click()
    page._parsed_url = page.url_edit.text()
    page.set_question_context(
        [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"])],
        [QuestionEntry("single", [1, 1], question_num=1)],
        survey_provider="wjx",
    )
    page.file_edit.setText(str(xlsx))
    page._last_spec = SimpleNamespace(target_num=3)

    cfg = RuntimeConfig(target=1, threads=1)
    page.update_config(cfg)
    page.on_run_state_changed(True)
    page.update_status("正在初始化", 0, 3)
    page.update_status("运行中", 2, 3)
    page.on_run_state_changed(False)

    assert page.parse_btn.text() == "解析"
    assert controller.parse_calls == ["https://www.wjx.cn/vm/demo.aspx"]
    assert cfg.reverse_fill_enabled is True
    assert cfg.reverse_fill_source_path == str(xlsx)
    assert cfg.threads == cfg.reverse_fill_threads
    assert page.stop_btn.isEnabled() is False


def test_dashboard_page_builds_and_updates_core_state(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    runtime_page = RuntimePage(controller)
    strategy_page = QuestionStrategyPage()
    state = WorkbenchState()
    state.set_entries(
        [QuestionEntry("single", [1, 1], question_num=1, question_title="Q1")],
        [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"])],
    )
    page = DashboardPage(controller, state, runtime_page, strategy_page)
    qtbot.addWidget(runtime_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)

    page._refresh_entry_table()
    page.update_status("已提交 1/2 份", 1, 2)
    page.update_thread_progress(
        {
            "target": 4,
            "num_threads": 2,
            "threads": [
                {
                    "thread_name": "Worker-1",
                    "thread_display_name": "会话 1",
                    "status_text": "提交中",
                    "success_count": 1,
                    "fail_count": 0,
                    "step_current": 1,
                    "step_total": 2,
                    "running": True,
                }
            ],
        }
    )
    assert "Worker-1" in page._thread_progress_rows
    page.on_run_state_changed(True)
    page.on_pause_state_changed(True, "手动暂停")
    page.on_pause_state_changed(False, "")
    page.on_run_state_changed(False)

    assert page.entry_table.rowCount() == 1
    assert page.progress_pct.text() == "50%"
    assert page.start_btn.text() in {"开始执行", "重新开始"}


def test_dashboard_thread_progress_rows_keep_visible_after_update(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    runtime_page = RuntimePage(controller)
    strategy_page = QuestionStrategyPage()
    state = WorkbenchState()
    page = DashboardPage(controller, state, runtime_page, strategy_page)
    qtbot.addWidget(runtime_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)
    page.show()

    controller.running = True
    page.update_thread_progress(
        {
            "target": 4,
            "num_threads": 2,
            "threads": [
                {
                    "thread_name": "Slot-1",
                    "thread_display_name": "会话 1",
                    "status_text": "构造答案",
                    "success_count": 1,
                    "fail_count": 0,
                    "step_current": 2,
                    "step_total": 4,
                    "running": True,
                }
            ],
        }
    )
    qtbot.wait(50)

    row = page._thread_progress_rows["Slot-1"]
    assert page.thread_view_stack.currentWidget() is page.thread_view_progress_card
    assert page.thread_progress_rows_layout.count() == 1
    assert row["status"].text() == "构造答案"
    assert row["step_bar"].isHidden() is False
    assert row["step_busy_bar"].isHidden() is True
    qtbot.wait(160)
    assert row["step_bar"].value() == 50
    assert row["widget"].sizeHint().height() > 0
    assert page.thread_progress_rows_container.sizeHint().height() > 0


def test_dashboard_thread_progress_shows_indeterminate_bar_while_fetching_proxy(
    monkeypatch,
    qtbot,
) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    runtime_page = RuntimePage(controller)
    strategy_page = QuestionStrategyPage()
    state = WorkbenchState()
    page = DashboardPage(controller, state, runtime_page, strategy_page)
    qtbot.addWidget(runtime_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)
    page.show()

    controller.running = True
    page.update_thread_progress(
        {
            "target": 4,
            "num_threads": 2,
            "threads": [
                {
                    "thread_name": "Slot-1",
                    "thread_display_name": "会话 1",
                    "status_text": "获取代理",
                    "success_count": 1,
                    "fail_count": 0,
                    "step_current": 0,
                    "step_total": 0,
                    "running": True,
                }
            ],
        }
    )
    qtbot.wait(50)

    row = page._thread_progress_rows["Slot-1"]
    assert row["step_bar"].isHidden() is True
    assert row["step_busy_bar"].isVisible() is True


def test_dashboard_thread_progress_keeps_previous_step_briefly_before_switch(
    monkeypatch,
    qtbot,
) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    runtime_page = RuntimePage(controller)
    strategy_page = QuestionStrategyPage()
    state = WorkbenchState()
    page = DashboardPage(controller, state, runtime_page, strategy_page)
    qtbot.addWidget(runtime_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)
    page.show()

    controller.running = True
    page.update_thread_progress(
        {
            "target": 4,
            "num_threads": 2,
            "threads": [
                {
                    "thread_name": "Slot-1",
                    "thread_display_name": "会话 1",
                    "status_text": "构造答案",
                    "success_count": 1,
                    "fail_count": 0,
                    "step_current": 2,
                    "step_total": 4,
                    "running": True,
                }
            ],
        }
    )
    row = page._thread_progress_rows["Slot-1"]
    assert row["status"].text() == "构造答案"

    page.update_thread_progress(
        {
            "target": 4,
            "num_threads": 2,
            "threads": [
                {
                    "thread_name": "Slot-1",
                    "thread_display_name": "会话 1",
                    "status_text": "提交问卷",
                    "success_count": 1,
                    "fail_count": 0,
                    "step_current": 3,
                    "step_total": 4,
                    "running": True,
                }
            ],
        }
    )

    assert row["status"].text() == "构造答案"
    assert row["displayed_status_text"] == "构造答案"
    qtbot.wait(130)
    assert row["status"].text() == "提交问卷"
    assert row["displayed_status_text"] == "提交问卷"
    assert row["step_bar"].isHidden() is True
    assert row["step_busy_bar"].isVisible() is True


def test_dashboard_thread_progress_shows_progress_bar_after_thread_finishes(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    runtime_page = RuntimePage(controller)
    strategy_page = QuestionStrategyPage()
    state = WorkbenchState()
    page = DashboardPage(controller, state, runtime_page, strategy_page)
    qtbot.addWidget(runtime_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)
    page.show()

    controller.running = False
    page.update_thread_progress(
        {
            "target": 4,
            "num_threads": 2,
            "threads": [
                {
                    "thread_name": "Slot-1",
                    "thread_display_name": "会话 1",
                    "status_text": "已完成",
                    "success_count": 1,
                    "fail_count": 0,
                    "step_current": 4,
                    "step_total": 4,
                    "running": False,
                }
            ],
        }
    )
    row = page._thread_progress_rows["Slot-1"]
    qtbot.wait(160)

    assert row["status"].text() == "已完成"
    assert row["step_busy_bar"].isHidden() is True
    assert row["step_bar"].isHidden() is False
    assert row["step_bar"].value() >= 99
