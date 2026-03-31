"""题目配置数据容器。"""
import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QDialog
from qfluentwidgets import ScrollArea

from software.core.questions.config import QuestionEntry

from .add_dialog import QuestionAddDialog
from .utils import build_entry_info_list

logger = logging.getLogger(__name__)


class QuestionStore(QObject):
    """题目配置共享状态仓库。"""

    entriesChanged = Signal(int)  # 当前题目配置条目数

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[QuestionEntry] = []
        self._questions_info: List[Dict[str, Any]] = []
        self._entry_questions_info: List[Dict[str, Any]] = []

    @property
    def entries(self) -> List[QuestionEntry]:
        return self._entries

    @property
    def questions_info(self) -> List[Dict[str, Any]]:
        return self._questions_info

    @property
    def entry_questions_info(self) -> List[Dict[str, Any]]:
        return self._entry_questions_info

    def set_questions(self, info: List[Dict[str, Any]], entries: List[QuestionEntry]):
        self._questions_info = info or []
        self.set_entries(entries, info)

    def set_entries(self, entries: List[QuestionEntry], info: Optional[List[Dict[str, Any]]] = None):
        self._questions_info = info or self._questions_info
        self._entries = list(entries or [])
        self._entry_questions_info = build_entry_info_list(self._entries, self._questions_info)
        for idx, entry in enumerate(self._entries):
            if getattr(entry, "question_title", None):
                continue
            if idx < len(self._entry_questions_info):
                title = self._entry_questions_info[idx].get("title")
                if title:
                    entry.question_title = str(title).strip()
        self._refresh_data()

    def get_entries(self) -> List[QuestionEntry]:
        return list(self._entries)

    def append_entry(self, entry: QuestionEntry) -> None:
        if not entry:
            return
        self._entries.append(entry)
        self._entry_questions_info = build_entry_info_list(self._entries, self._questions_info)
        self._refresh_data()

    def _refresh_data(self):
        try:
            self.entriesChanged.emit(int(len(self._entries)))
        except Exception as exc:
            logger.info(f"发送 entriesChanged 信号失败: {exc}")


class QuestionPage(ScrollArea):
    """隐藏页面壳：内部使用 QuestionStore 维护题目状态。"""

    entriesChanged = Signal(int)  # 当前题目配置条目数

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = QuestionStore(self)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()
        self.store.entriesChanged.connect(self.entriesChanged.emit)

    def _build_ui(self):
        QVBoxLayout(self.view).setContentsMargins(0, 0, 0, 0)

    @property
    def entries(self) -> List[QuestionEntry]:
        return self.store.entries

    @property
    def questions_info(self) -> List[Dict[str, Any]]:
        return self.store.questions_info

    @property
    def entry_questions_info(self) -> List[Dict[str, Any]]:
        return self.store.entry_questions_info

    def get_entries(self) -> List[QuestionEntry]:
        return self.store.get_entries()

    # ---------- data helpers ----------
    def set_questions(self, info: List[Dict[str, Any]], entries: List[QuestionEntry]):
        self.store.set_questions(info, entries)

    def set_entries(self, entries: List[QuestionEntry], info: Optional[List[Dict[str, Any]]] = None):
        self.store.set_entries(entries, info)

    # ---------- UI actions ----------
    def _add_entry(self):
        """显示新增题目的交互式弹窗。"""
        dialog = QuestionAddDialog(self.store.entries, self.window() or self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_entry = dialog.get_entry()
            if new_entry:
                self.store.append_entry(new_entry)


