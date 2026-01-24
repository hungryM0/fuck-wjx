"""UI 页面模块"""
from wjx.ui.pages.dashboard import DashboardPage
from wjx.ui.pages.runtime import RuntimePage
from wjx.ui.pages.settings import SettingsPage
from wjx.ui.pages.question import QuestionPage, QuestionWizardDialog
from wjx.ui.pages.log import LogPage
from wjx.ui.pages.support import SupportPage
from wjx.ui.pages.account import AccountPage
from wjx.ui.pages.changelog import ChangelogPage

__all__ = [
    "DashboardPage",
    "RuntimePage",
    "SettingsPage",
    "QuestionPage",
    "QuestionWizardDialog",
    "LogPage",
    "SupportPage",
    "AccountPage",
    "ChangelogPage",
]
