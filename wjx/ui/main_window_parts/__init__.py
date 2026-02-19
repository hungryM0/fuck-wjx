"""MainWindow 拆分模块。"""

from .lazy_pages import MainWindowLazyPagesMixin
from .popup_compat import MainWindowPopupCompatMixin
from .update import MainWindowUpdateMixin

__all__ = [
    "MainWindowLazyPagesMixin",
    "MainWindowPopupCompatMixin",
    "MainWindowUpdateMixin",
]
