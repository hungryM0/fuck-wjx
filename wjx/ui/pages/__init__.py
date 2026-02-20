"""UI 页面模块"""
from wjx.ui.pages.workbench.dashboard import DashboardPage
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.ui.pages.settings.settings import SettingsPage
from wjx.ui.pages.workbench.question import QuestionPage, QuestionWizardDialog
from wjx.ui.pages.workbench.log import LogPage
from wjx.ui.pages.more.support import SupportPage
from wjx.ui.pages.account.account import AccountPage
from wjx.ui.pages.more.changelog import ChangelogPage

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
