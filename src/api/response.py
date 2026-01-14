from __future__ import annotations

from typing import Any, Optional


def success_response(data: Any) -> dict[str, Any]:
    return {"status_code": 0, "status_msg": "success", "data": data}


def error_response(message: str, *, data: Optional[Any] = None, status_code: int = 1) -> dict[str, Any]:
    return {"status_code": status_code, "status_msg": message, "data": data or {}}
