"""UI 页面模块"""
from wjx.ui.pages.workbench.dashboard import DashboardPage
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.ui.pages.account.settings import SettingsPage
from wjx.ui.pages.workbench.question import QuestionPage, QuestionWizardDialog
from wjx.ui.pages.workbench.log import LogPage
from wjx.ui.pages.workbench.result import ResultPage
from wjx.ui.pages.support.support import SupportPage
from wjx.ui.pages.account.account import AccountPage
from wjx.ui.pages.support.changelog import ChangelogPage

__all__ = [
    "DashboardPage",
    "RuntimePage",
    "SettingsPage",
    "QuestionPage",
    "QuestionWizardDialog",
    "LogPage",
    "ResultPage",
    "SupportPage",
    "AccountPage",
    "ChangelogPage",
]
