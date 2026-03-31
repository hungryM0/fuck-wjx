"""RunController 配置持久化逻辑。"""
from __future__ import annotations

from typing import Optional

from software.io.config import RuntimeConfig, load_config, save_config


class RunControllerPersistenceMixin:
    # -------------------- Persistence --------------------
    def load_saved_config(self, path: Optional[str] = None, *, strict: bool = False) -> RuntimeConfig:
        cfg = load_config(path, strict=strict)
        self.config = cfg
        self.question_entries = cfg.question_entries
        self.questions_info = list(getattr(cfg, "questions_info", None) or [])
        self.survey_title = str(getattr(cfg, "survey_title", "") or "")
        self.survey_provider = str(getattr(cfg, "survey_provider", "wjx") or "wjx")
        return cfg

    def save_current_config(self, path: Optional[str] = None) -> str:
        entries = getattr(self.config, "question_entries", None)
        if entries is None:
            entries = self.question_entries
        self.question_entries = list(entries or [])
        self.config.question_entries = self.question_entries
        return save_config(self.config, path)


