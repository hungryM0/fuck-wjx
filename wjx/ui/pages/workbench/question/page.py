"""题目配置主页面，包含表格展示和按钮操作。"""
import logging
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QTableWidgetItem,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    PushButton,
    PrimaryPushButton,
    TableWidget,
    InfoBar,
    InfoBarPosition,
    FluentIcon,
)

from wjx.core.questions.config import QuestionEntry
from wjx.utils.integrations.ai_service import generate_answer
from wjx.ui.helpers.ai_fill import ensure_ai_ready

from .constants import _get_entry_type_label
from .add_dialog import QuestionAddDialog

logger = logging.getLogger(__name__)


class QuestionPage(ScrollArea):
    """题目配置页，支持简单编辑。"""

    entriesChanged = Signal(int)  # 当前题目配置条目数

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[QuestionEntry] = []
        self.questions_info: List[Dict[str, Any]] = []
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(SubtitleLabel("题目配置", self))
        layout.addWidget(BodyLabel("双击单元格即可编辑；自定义配比用逗号分隔，例如 3,2,1", self))

        self.table = TableWidget(self.view)
        self.table.setRowCount(0)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["题号", "类型", "选项数", "配置详情"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.add_btn = PrimaryPushButton("新增题目", self.view)
        self.del_btn = PushButton("删除选中", self.view)
        self.reset_btn = PushButton("恢复默认", self.view)
        self.ai_btn = PushButton(FluentIcon.ROBOT, "AI 生成答案", self.view)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addWidget(self.ai_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._add_entry)
        self.del_btn.clicked.connect(self._delete_selected)
        self.reset_btn.clicked.connect(self._reset_from_source)
        self.ai_btn.clicked.connect(self._generate_ai_answers)

    # ---------- data helpers ----------
    def set_questions(self, info: List[Dict[str, Any]], entries: List[QuestionEntry]):
        self.questions_info = info or []
        self.set_entries(entries, info)

    def set_entries(self, entries: List[QuestionEntry], info: Optional[List[Dict[str, Any]]] = None):
        self.questions_info = info or self.questions_info
        self.entries = list(entries or [])
        if self.questions_info:
            for idx, entry in enumerate(self.entries):
                if getattr(entry, "question_title", None):
                    continue
                if idx < len(self.questions_info):
                    title = self.questions_info[idx].get("title")
                    if title:
                        entry.question_title = str(title).strip()
        self._refresh_table()

    def get_entries(self) -> List[QuestionEntry]:
        result: List[QuestionEntry] = []
        for row in range(self.table.rowCount()):
            entry = self._entry_from_row(row)
            result.append(entry)
        return result

    # ---------- UI actions ----------
    def _reset_from_source(self):
        self._refresh_table()

    def _add_entry(self):
        """显示新增题目的交互式弹窗"""
        dialog = QuestionAddDialog(self.entries, self.window() or self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_entry = dialog.get_entry()
            if new_entry:
                self.entries.append(new_entry)
                self._refresh_table()

    def _delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            InfoBar.warning("", "请先选择要删除的题目", parent=self.window(), position=InfoBarPosition.TOP, duration=1800)
            return
        for row in rows:
            if 0 <= row < len(self.entries):
                self.entries.pop(row)
        self._refresh_table()

    def _generate_ai_answers(self):
        """使用 AI 为填空题生成答案"""
        if not ensure_ai_ready(self.window() or self):
            return

        # 找出所有填空题
        text_questions = []
        for idx, entry in enumerate(self.entries):
            if entry.question_type == "text":
                info = self.questions_info[idx] if idx < len(self.questions_info) else {}
                title = info.get("title", f"第{idx + 1}题")
                text_questions.append((idx, entry, title))

        if not text_questions:
            InfoBar.info("", "当前没有填空题需要生成答案", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)
            return

        InfoBar.info("", f"正在为 {len(text_questions)} 道填空题生成答案...", parent=self.window(), position=InfoBarPosition.TOP, duration=2000)

        success_count = 0
        fail_count = 0
        for idx, entry, title in text_questions:
            try:
                answer = generate_answer(title)
                if answer:
                    entry.texts = [answer]
                    success_count += 1
                else:
                    fail_count += 1
                    logger.warning(f"AI 生成答案失败 (题目 {idx+1}: {title}): 返回空答案")
            except Exception as e:
                fail_count += 1
                logger.warning(f"AI 生成答案失败 (题目 {idx+1}: {title}): {e}", exc_info=True)

        self._refresh_table()

        if fail_count == 0:
            InfoBar.success("", f"成功为 {success_count} 道填空题生成答案", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
        else:
            InfoBar.warning("", f"生成完成：成功 {success_count} 道，失败 {fail_count} 道", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)

    # ---------- table helpers ----------
    def _refresh_table(self):
        self.table.setRowCount(0)
        for idx, entry in enumerate(self.entries):
            self._insert_row(idx, entry)
        self.table.resizeColumnsToContents()
        try:
            self.entriesChanged.emit(int(self.table.rowCount()))
        except Exception as e:
            logger.debug(f"发送 entriesChanged 信号失败: {e}")

    def _insert_row(self, row: int, entry: QuestionEntry):
        self.table.insertRow(row)
        info = self.questions_info[row] if row < len(self.questions_info) else {}
        qnum = str(info.get("num") or entry.question_num or row + 1)
        num_item = QTableWidgetItem(qnum)
        num_item.setData(Qt.ItemDataRole.UserRole, qnum)
        self.table.setItem(row, 0, num_item)

        # 类型
        type_label = _get_entry_type_label(entry)
        self.table.setItem(row, 1, QTableWidgetItem(type_label))

        # 选项数
        option_count = max(1, int(entry.option_count or 1))
        self.table.setItem(row, 2, QTableWidgetItem(str(option_count)))

        # 配置详情 - 显示有意义的摘要
        detail = self._build_detail_text(entry)
        self.table.setItem(row, 3, QTableWidgetItem(detail))

    def _build_detail_text(self, entry: QuestionEntry) -> str:
        """构建配置详情摘要文本。"""
        if entry.question_type in ("text", "multi_text"):
            texts = entry.texts or []
            if texts:
                detail = f"答案: {' | '.join(texts[:3])}"
                if len(texts) > 3:
                    detail += f" (+{len(texts)-3})"
            else:
                detail = "答案: 无"
            if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
                detail += " | AI"
            return detail
        if entry.question_type == "matrix":
            rows = max(1, int(entry.rows or 1))
            cols = max(1, int(entry.option_count or 1))
            if isinstance(entry.custom_weights, list) or isinstance(entry.probabilities, list):
                return f"{rows} 行 × {cols} 列 | 按行配比"
            return f"{rows} 行 × {cols} 列 | 完全随机"
        if entry.question_type == "order":
            return "排序题 | 自动随机排序"
        if entry.custom_weights:
            weights = entry.custom_weights
            if entry.question_type == "multiple":
                detail = f"自定义概率: {','.join(f'{int(w)}%' for w in weights[:5])}"
            else:
                detail = f"自定义配比: {','.join(str(int(w)) for w in weights[:5])}"
            if len(weights) > 5:
                detail += "..."
            return detail
        strategy = entry.distribution_mode or "random"
        if strategy not in ("random", "custom"):
            strategy = "random"
        if getattr(entry, "probabilities", None) == -1:
            strategy = "random"
        if entry.question_type == "multiple":
            return "完全随机" if strategy == "random" else "自定义概率"
        return "完全随机" if strategy == "random" else "自定义配比"

    def _entry_from_row(self, row: int) -> QuestionEntry:
        # 表格现在是只读显示，直接返回 entries 中的条目
        if row < len(self.entries):
            return self.entries[row]
        # 兜底：返回一个默认条目
        return QuestionEntry(
            question_type="single",
            probabilities=-1,
            texts=None,
            rows=1,
            option_count=4,
            distribution_mode="random",
            custom_weights=None,
            question_num=str(row + 1),
        )
