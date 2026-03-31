"""DashboardPage 拆分模块。"""

from .clipboard import DashboardClipboardMixin
from .entries import DashboardEntriesMixin
from .progress import DashboardProgressMixin
from .random_ip import DashboardRandomIPMixin

__all__ = [
    "DashboardClipboardMixin",
    "DashboardEntriesMixin",
    "DashboardProgressMixin",
    "DashboardRandomIPMixin",
]
