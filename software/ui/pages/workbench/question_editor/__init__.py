"""题目配置页面导出。"""

from .constants import _get_entry_type_label
from .page import QuestionPage
from .wizard_dialog import QuestionWizardDialog

__all__ = [
    "_get_entry_type_label",
    "QuestionWizardDialog",
    "QuestionPage",
]
