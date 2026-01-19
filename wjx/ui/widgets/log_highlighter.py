from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat


class LogHighlighter(QSyntaxHighlighter):
    TRACEBACK_STATE = 1

    def __init__(self, document, colors: Optional[Dict[str, str]] = None):
        super().__init__(document)
        self._colors = colors or {}
        self._formats: Dict[str, QTextCharFormat] = {}
        self._log_prefix = QRegularExpression(
            r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\["
        )
        self._update_formats()

    def set_colors(self, colors: Dict[str, str]) -> None:
        self._colors = colors or {}
        self._update_formats()
        self.rehighlight()

    def _update_formats(self) -> None:
        self._formats.clear()
        for key, value in (self._colors or {}).items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(value))
            self._formats[key.upper()] = fmt

    def _apply_format(self, level: str, text: str) -> None:
        if not text:
            return
        fmt = self._formats.get(level.upper()) or self._formats.get("DEFAULT")
        if fmt:
            self.setFormat(0, len(text), fmt)

    @staticmethod
    def _extract_level(text: str) -> Optional[str]:
        upper = text.upper()
        if "[ERROR]" in upper or "[CRITICAL]" in upper:
            return "ERROR"
        if "[WARNING]" in upper:
            return "WARNING"
        if "[WARN]" in upper:
            return "WARN"
        if "[OK]" in upper or "[SUCCESS]" in upper:
            return "OK"
        if "[DEBUG]" in upper:
            return "DEBUG"
        if "[INFO]" in upper:
            return "INFO"
        if "TRACEBACK (MOST RECENT CALL LAST)" in upper:
            return "ERROR"
        return None

    def _looks_like_log_line(self, text: str) -> bool:
        return self._log_prefix.match(text).hasMatch()

    def highlightBlock(self, text: str) -> None:
        if not text:
            self.setCurrentBlockState(0)
            return

        level = self._extract_level(text)
        if level:
            self._apply_format(level, text)
            if level == "ERROR" and "TRACEBACK (MOST RECENT CALL LAST)" in text.upper():
                self.setCurrentBlockState(self.TRACEBACK_STATE)
            else:
                self.setCurrentBlockState(
                    self.TRACEBACK_STATE
                    if level == "ERROR" and self.previousBlockState() == self.TRACEBACK_STATE
                    else 0
                )
            return

        if self.previousBlockState() == self.TRACEBACK_STATE and not self._looks_like_log_line(text):
            self._apply_format("ERROR", text)
            self.setCurrentBlockState(self.TRACEBACK_STATE)
            return

        self._apply_format("DEFAULT", text)
        self.setCurrentBlockState(0)
