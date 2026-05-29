from __future__ import annotations

from typing import Any, Dict


def event_payload(event_type: str, **payload: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {"type": str(event_type or "").strip()}
    data.update(payload)
    return data


__all__ = ["event_payload"]
