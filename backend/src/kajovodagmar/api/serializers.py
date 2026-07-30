from __future__ import annotations

from typing import Any


def model_view(row: Any, *fields: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(row, field)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif hasattr(value, "hex") and value.__class__.__name__ == "UUID":
            value = str(value)
        result[field] = value
    return result
