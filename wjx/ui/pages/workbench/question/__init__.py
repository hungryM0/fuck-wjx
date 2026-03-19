"""题目配置页面模块

重构自原 question.py，按职责拆分为模块化结构。

模块结构:
    constants.py      - TYPE_CHOICES、STRATEGY_CHOICES 等常量与标签函数
    utils.py          - _shorten_text、_apply_label_color、_bind_slider_input 等辅助函数
    wizard_dialog.py  - QuestionWizardDialog 配置向导弹窗
    add_dialog.py     - QuestionAddDialog 新增题目弹窗
    page.py           - QuestionPage 题目配置主页面
"""

from .constants import (
    TYPE_CHOICES,
    STRATEGY_CHOICES,
    TYPE_LABEL_MAP,
    _get_entry_type_label,
    _get_type_label,
)
from .utils import _shorten_text, _apply_label_color, _bind_slider_input
from .wizard_dialog import QuestionWizardDialog
from .add_dialog import QuestionAddDialog
from .page import QuestionPage

__all__ = [
    # 常量
    "TYPE_CHOICES",
    "STRATEGY_CHOICES",
    "TYPE_LABEL_MAP",
    # 标签函数
    "_get_entry_type_label",
    "_get_type_label",
    # 辅助函数
    "_shorten_text",
    "_apply_label_color",
    "_bind_slider_input",
    # 对话框
    "QuestionWizardDialog",
    "QuestionAddDialog",
    # 主页面
    "QuestionPage",
]
