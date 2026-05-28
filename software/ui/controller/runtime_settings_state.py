"""运行参数 UI 状态。"""

from __future__ import annotations

from typing import Any, Dict

from software.core.config.schema import RuntimeConfig

DEFAULT_ANSWER_DURATION_RANGE_SECONDS = (60, 120)
MAX_ANSWER_DURATION_SECONDS = 30 * 60


class RuntimeSettingsState:
    """集中管理运行参数当前值。"""

    DEFAULTS: Dict[str, Any] = {
        "target": 1,
        "threads": 1,
        "random_ip_enabled": False,
        "survey_provider": "wjx",
        "proxy_source": "default",
        "submit_interval": (0, 0),
        "answer_duration": DEFAULT_ANSWER_DURATION_RANGE_SECONDS,
    }

    def __init__(self) -> None:
        self._state: Dict[str, Any] = {}

    @staticmethod
    def normalize_value(key: str, value: Any) -> Any:
        if key in {"target", "threads"}:
            return max(1, int(value or 1))
        if key in {"random_ip_enabled"}:
            return bool(value)
        if key == "proxy_source":
            normalized = str(value or "default").strip().lower()
            return normalized if normalized in {"default", "benefit", "custom"} else "default"
        if key == "submit_interval":
            raw = value if isinstance(value, (list, tuple)) else (0, 0)
            low = max(0, int(raw[0] if len(raw) >= 1 else 0))
            high = max(low, int(raw[1] if len(raw) >= 2 else low))
            return (low, high)
        if key == "answer_duration":
            try:
                if value in (None, "", []):
                    return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
                if isinstance(value, (list, tuple)):
                    if len(value) >= 2:
                        low = min(MAX_ANSWER_DURATION_SECONDS, max(0, int(value[0])))
                        high = min(MAX_ANSWER_DURATION_SECONDS, max(low, int(value[1])))
                        if low == 0 and high == 0:
                            return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
                        return (low, high)
                    if len(value) == 1:
                        single = min(MAX_ANSWER_DURATION_SECONDS, max(0, int(value[0])))
                    else:
                        return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
                else:
                    single = min(MAX_ANSWER_DURATION_SECONDS, max(0, int(value)))
                if single <= 0:
                    return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
                low = max(0, int(round(single * 0.8)))
                high = min(MAX_ANSWER_DURATION_SECONDS, max(low, int(round(single * 1.2))))
                return (low, high)
            except Exception:
                return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
        return value

    def get(self) -> Dict[str, Any]:
        return dict(self._state)

    def update(
        self,
        *,
        lock_threads: bool = False,
        **updates: Any,
    ) -> tuple[Dict[str, Any], bool]:
        if lock_threads and "threads" in updates:
            updates = dict(updates)
            updates.pop("threads", None)
        normalized: Dict[str, Any] = {}
        changed = False
        for key, value in updates.items():
            normalized_value = self.normalize_value(key, value)
            normalized[key] = normalized_value
            if self._state.get(key) != normalized_value:
                changed = True
        if normalized:
            self._state.update(normalized)
        return dict(self._state), changed

    def sync_from_config(
        self,
        config: RuntimeConfig,
        *,
        preserve_threads: bool = False,
        lock_threads: bool = False,
    ) -> tuple[Dict[str, Any], bool]:
        updates: Dict[str, Any] = {
            "target": getattr(config, "target", 1),
            "random_ip_enabled": getattr(config, "random_ip_enabled", False),
            "survey_provider": getattr(config, "survey_provider", "wjx"),
            "proxy_source": getattr(config, "proxy_source", "default"),
            "submit_interval": getattr(config, "submit_interval", (0, 0)),
            "answer_duration": getattr(config, "answer_duration", (0, 0)),
        }
        if not (preserve_threads or lock_threads):
            updates["threads"] = getattr(config, "threads", 1)
        return self.update(**updates)

    def write_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        state = {**self.DEFAULTS, **self.get()}
        config.target = max(1, int(state["target"] or 1))
        config.threads = max(1, int(state["threads"] or 1))
        config.random_ip_enabled = bool(state["random_ip_enabled"])
        config.survey_provider = str(state["survey_provider"] or "wjx")
        config.proxy_source = str(state["proxy_source"] or "default")
        config.submit_interval = self.normalize_value(
            "submit_interval",
            state["submit_interval"],
        )
        config.answer_duration = self.normalize_value(
            "answer_duration",
            state["answer_duration"],
        )
        return config
