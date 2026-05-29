from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Optional

from software.core.config.codec import clone_question_entries, clone_questions_info
from software.core.config.schema import RuntimeConfig
from software.providers.common import detect_survey_provider, normalize_survey_provider
from software.ui.controller.runtime_settings_state import RuntimeSettingsState


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


class RunStateStore:
    """统一维护运行态/解析态快照，并在变化时通知外层。"""

    def __init__(
        self,
        *,
        on_runtime_snapshot_changed: Optional[Callable[[dict[str, Any]], Any]] = None,
        on_survey_snapshot_changed: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> None:
        self._runtime_settings_state = RuntimeSettingsState()
        self._runtime_snapshot = self._build_runtime_snapshot()
        self._survey_snapshot = self._build_survey_snapshot()
        self._on_runtime_snapshot_changed = on_runtime_snapshot_changed
        self._on_survey_snapshot_changed = on_survey_snapshot_changed

    @staticmethod
    def _build_runtime_snapshot() -> Dict[str, Any]:
        settings_state = {**RuntimeSettingsState.DEFAULTS}
        return {
            "phase": "idle",
            "running": False,
            "paused": False,
            "stopping": False,
            "status_text": "等待配置...",
            "progress": {
                "current": 0,
                "target": 0,
                "consecutive_failures": 0,
                "device_quota_fail_count": 0,
            },
            "threads": {
                "rows": [],
                "num_threads": 0,
                "per_thread_target": 0,
            },
            "initialization": {
                "active": False,
                "text": "",
                "logs": [],
            },
            "settings": dict(settings_state),
            "random_ip": {
                "enabled": bool(settings_state["random_ip_enabled"]),
                "loading": False,
                "loading_message": "",
                "used_quota": 0.0,
                "total_quota": 0.0,
                "custom_api": False,
            },
            "terminal_stop": {
                "category": "",
                "failure_reason": "",
                "message": "",
            },
        }

    @staticmethod
    def _build_survey_snapshot() -> Dict[str, Any]:
        return {
            "phase": "idle",
            "url": "",
            "survey_title": "",
            "survey_provider": "wjx",
            "questions_info": [],
            "question_entries": [],
            "parse_error": "",
            "has_question_entries": False,
        }

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        return deepcopy(self._runtime_snapshot)

    def get_survey_snapshot(self) -> Dict[str, Any]:
        return deepcopy(self._survey_snapshot)

    def runtime_settings(self) -> Dict[str, Any]:
        return dict(self._runtime_snapshot.get("settings") or {})

    def update_runtime_settings(
        self,
        *,
        emit: bool = True,
        lock_threads: bool = False,
        **updates: Any,
    ) -> Dict[str, Any]:
        state, changed = self._runtime_settings_state.update(
            lock_threads=lock_threads,
            **updates,
        )
        patch = {
            "settings": dict(state),
            "random_ip": {
                "enabled": bool(state.get("random_ip_enabled", False)),
            },
        }
        self._set_runtime_snapshot(_deep_merge(self._runtime_snapshot, patch), emit=emit and changed)
        return dict(state)

    def sync_runtime_settings_from_config(
        self,
        config: RuntimeConfig,
        *,
        emit: bool = True,
        lock_threads: bool = False,
    ) -> Dict[str, Any]:
        state, changed = self._runtime_settings_state.sync_from_config(
            config,
            lock_threads=lock_threads,
        )
        patch = {
            "settings": dict(state),
            "random_ip": {
                "enabled": bool(state.get("random_ip_enabled", False)),
            },
        }
        self._set_runtime_snapshot(_deep_merge(self._runtime_snapshot, patch), emit=emit and changed)
        return dict(state)

    def write_runtime_settings_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self._runtime_settings_state.write_to_config(config)

    def apply_runtime_patch(self, patch: Dict[str, Any], *, emit: bool = True) -> Dict[str, Any]:
        snapshot = _deep_merge(self._runtime_snapshot, patch)
        self._set_runtime_snapshot(snapshot, emit=emit)
        return self.get_runtime_snapshot()

    def apply_survey_patch(self, patch: Dict[str, Any], *, emit: bool = True) -> Dict[str, Any]:
        normalized_patch = dict(patch or {})
        if "questions_info" in normalized_patch:
            normalized_patch["questions_info"] = clone_questions_info(
                normalized_patch.get("questions_info"),
                default_provider=normalize_survey_provider(
                    normalized_patch.get(
                        "survey_provider",
                        self._survey_snapshot.get("survey_provider"),
                    ),
                    default="wjx",
                ),
            )
        if "question_entries" in normalized_patch:
            normalized_patch["question_entries"] = clone_question_entries(
                normalized_patch.get("question_entries")
            )
        snapshot = _deep_merge(self._survey_snapshot, normalized_patch)
        snapshot["has_question_entries"] = bool(snapshot.get("question_entries"))
        self._set_survey_snapshot(snapshot, emit=emit)
        return self.get_survey_snapshot()

    def hydrate_from_config(self, config: RuntimeConfig, *, emit: bool = True) -> None:
        self.sync_runtime_settings_from_config(config, emit=False)
        provider = normalize_survey_provider(
            getattr(config, "survey_provider", None),
            default=detect_survey_provider(getattr(config, "url", "")),
        )
        self.apply_survey_patch(
            {
                "phase": "ready" if list(getattr(config, "question_entries", []) or []) else "idle",
                "url": str(getattr(config, "url", "") or ""),
                "survey_title": str(getattr(config, "survey_title", "") or ""),
                "survey_provider": provider,
                "questions_info": list(getattr(config, "questions_info", []) or []),
                "question_entries": list(getattr(config, "question_entries", []) or []),
                "parse_error": "",
            },
            emit=False,
        )
        self.apply_runtime_patch(
            {
                "settings": dict(self._runtime_settings_state.get()),
                "random_ip": {
                    "enabled": bool(getattr(config, "random_ip_enabled", False)),
                },
            },
            emit=emit,
        )
        if emit:
            self._emit_survey_snapshot()

    def replace_question_entries(
        self,
        entries: Any,
        *,
        questions_info: Any = None,
        emit: bool = True,
    ) -> Dict[str, Any]:
        patch: Dict[str, Any] = {"question_entries": list(entries or [])}
        if questions_info is not None:
            patch["questions_info"] = list(questions_info or [])
        return self.apply_survey_patch(patch, emit=emit)

    def _set_runtime_snapshot(self, snapshot: Dict[str, Any], *, emit: bool) -> None:
        if snapshot == self._runtime_snapshot:
            return
        self._runtime_snapshot = snapshot
        if emit:
            self._emit_runtime_snapshot()

    def _set_survey_snapshot(self, snapshot: Dict[str, Any], *, emit: bool) -> None:
        if snapshot == self._survey_snapshot:
            return
        self._survey_snapshot = snapshot
        if emit:
            self._emit_survey_snapshot()

    def _emit_runtime_snapshot(self) -> None:
        callback = self._on_runtime_snapshot_changed
        if callable(callback):
            callback(self.get_runtime_snapshot())

    def _emit_survey_snapshot(self) -> None:
        callback = self._on_survey_snapshot_changed
        if callable(callback):
            callback(self.get_survey_snapshot())


__all__ = ["RunStateStore"]
