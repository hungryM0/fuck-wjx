from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QApplication, QLayout, QScrollArea, QWidget
from qfluentwidgets import ScrollArea as FluentScrollArea
from qfluentwidgets import Slider, SpinBox

from CI.unit_tests.app.test_workbench_pages_smoke import _FakeController, _patch_page_dependencies
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.dashboard.page import DashboardPage
from software.ui.pages.workbench.reverse_fill.page import ReverseFillPage
from software.ui.pages.workbench.runtime_panel.main import RuntimePage
from software.ui.pages.workbench.session import WorkbenchState
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage
from software.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox


PROJECT_ROOT = Path(__file__).resolve().parents[3]
UI_ROOT = PROJECT_ROOT / "software" / "ui"

FORBIDDEN_NATIVE_CONTROLS = {
    "QCheckBox",
    "QComboBox",
    "QDoubleSpinBox",
    "QLineEdit",
    "QPlainTextEdit",
    "QProgressBar",
    "QPushButton",
    "QRadioButton",
    "QSlider",
    "QSpinBox",
    "QTableWidget",
    "QTextEdit",
}


def _iter_feature_ui_files() -> list[Path]:
    roots = [
        UI_ROOT / "pages",
        UI_ROOT / "dialogs",
    ]
    return sorted(
        path
        for root in roots
        for path in root.rglob("*.py")
        if path.name
        in {
            "page.py",
            "ui_builder.py",
            "cards.py",
            "add_dialog.py",
            "rule_dialog.py",
            "question_selector_dialog.py",
            "contact.py",
            "quota_redeem.py",
            "terms_of_service.py",
        }
    )


def _qtwidgets_import_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "PySide6.QtWidgets":
            for alias in node.names:
                if alias.name in FORBIDDEN_NATIVE_CONTROLS:
                    violations.append(alias.name)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "QtWidgets"
            and node.attr in FORBIDDEN_NATIVE_CONTROLS
        ):
            violations.append(node.attr)
    return sorted(set(violations))


def _assert_layout_items_do_not_overlap(root: QWidget) -> None:
    problems: list[str] = []
    for parent in root.findChildren(QWidget):
        layout = parent.layout()
        if layout is None:
            continue
        rects = _visible_layout_widget_rects(layout)
        for left_index, left_rect in enumerate(rects):
            for right_rect in rects[left_index + 1 :]:
                intersection = left_rect.intersected(right_rect)
                if intersection.isValid() and intersection.width() > 1 and intersection.height() > 1:
                    problems.append(f"{parent.__class__.__name__}: {left_rect} overlaps {right_rect}")

    assert problems == []


def _visible_layout_widget_rects(layout: QLayout) -> list[QRect]:
    if isinstance(layout.parentWidget(), QScrollArea):
        return []

    rects: list[QRect] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        if widget is None or not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
            continue
        rects.append(widget.geometry())
    return rects


def _assert_no_horizontal_scrollbar(page: QWidget) -> None:
    scroll_areas: list[FluentScrollArea] = []
    if isinstance(page, FluentScrollArea):
        scroll_areas.append(page)
    scroll_areas.extend(page.findChildren(FluentScrollArea))

    overflowing = [
        f"{area.objectName() or area.__class__.__name__}: {area.horizontalScrollBar().maximum()}"
        for area in scroll_areas
        if area.isVisible() and area.horizontalScrollBar().maximum() > 0
    ]
    assert overflowing == []


def _show_at_guarded_size(qtbot, widget: QWidget) -> None:
    qtbot.addWidget(widget)
    widget.resize(900, 640)
    widget.show()
    if widget.layout() is not None:
        widget.layout().activate()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    QApplication.processEvents()
    qtbot.wait(80)


def test_feature_pages_do_not_import_native_qt_controls_directly() -> None:
    violations = {
        str(path.relative_to(PROJECT_ROOT)): names
        for path in _iter_feature_ui_files()
        if (names := _qtwidgets_import_violations(path))
    }

    assert violations == {}


def test_no_wheel_inputs_keep_qfluentwidgets_control_base() -> None:
    assert issubclass(NoWheelSpinBox, SpinBox)
    assert issubclass(NoWheelSlider, Slider)


def test_workbench_pages_fit_minimum_window_width_without_horizontal_overflow(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    runtime_page = RuntimePage(controller)
    strategy_page = QuestionStrategyPage()
    reverse_fill_page = ReverseFillPage(controller)

    state = WorkbenchState()
    state.set_entries([], [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"])])
    dashboard_page = DashboardPage(controller, state, runtime_page, strategy_page)

    for page in (runtime_page, strategy_page, reverse_fill_page, dashboard_page):
        _show_at_guarded_size(qtbot, page)
        _assert_no_horizontal_scrollbar(page)
        _assert_layout_items_do_not_overlap(page)


def test_workbench_pages_survive_125_percent_dpi_subprocess() -> None:
    script = textwrap.dedent(
        """
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication

        from CI.unit_tests.app.test_ui_layout_contracts import (
            _assert_layout_items_do_not_overlap,
            _assert_no_horizontal_scrollbar,
        )
        from CI.unit_tests.app.test_workbench_pages_smoke import _FakeController
        from software.ui.pages.workbench.runtime_panel.main import RuntimePage

        import software.ui.pages.workbench.runtime_panel.ai as ai_module
        import software.ui.pages.workbench.runtime_panel.proxy_sync as runtime_proxy_sync
        import software.ui.pages.workbench.runtime_panel.random_ip_card as random_ip_card

        random_ip_card.load_area_codes = lambda supported_only=True: [
            {"code": "110000", "name": "北京", "cities": [{"code": "110100", "name": "北京"}]}
        ]
        random_ip_card.load_supported_area_codes = lambda: ({"110000", "110100"}, False)
        random_ip_card.load_benefit_supported_areas = lambda force_refresh=False: []
        random_ip_card.apply_proxy_area_code = lambda _code: None
        random_ip_card.apply_custom_proxy_api = lambda _url: None
        random_ip_card.test_custom_proxy_api = lambda _url: (True, "", [])
        ai_module.get_ai_settings = lambda: {"ai_mode": "free"}
        ai_module.save_ai_settings = lambda **_kwargs: None
        ai_module.get_default_system_prompt = lambda _mode="free": "默认提示"
        runtime_proxy_sync.apply_proxy_source_settings = lambda *_args, **_kwargs: None
        runtime_proxy_sync.apply_custom_proxy_api = lambda *_args, **_kwargs: None
        runtime_proxy_sync.get_proxy_minute_by_answer_seconds = lambda *_args, **_kwargs: 1

        app = QApplication([])
        page = RuntimePage(_FakeController())
        page.resize(900, 640)
        page.show()
        if page.layout() is not None:
            page.layout().activate()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        app.processEvents()

        ratio = app.primaryScreen().devicePixelRatio()
        assert ratio >= 1.24, ratio
        _assert_no_horizontal_scrollbar(page)
        _assert_layout_items_do_not_overlap(page)

        page.close()
        page.deleteLater()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        """
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_SCALE_FACTOR"] = "1.25"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
