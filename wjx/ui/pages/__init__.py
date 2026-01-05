"""UI 页面模块"""
from wjx.ui.pages.dashboard import DashboardPage
from wjx.ui.pages.settings import SettingsPage
from wjx.ui.pages.question import QuestionPage, QuestionWizardDialog
from wjx.ui.pages.log import LogPage
from wjx.ui.pages.help import HelpPage

__all__ = [
    "DashboardPage",
    "SettingsPage",
    "QuestionPage",
    "QuestionWizardDialog",
    "LogPage",
    "HelpPage",
]
