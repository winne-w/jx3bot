from typing import Any, Dict, List, Optional


def server_status_items(response: Any) -> List[Dict[str, Any]]:
    """Read valid status records without interpreting a failed query as empty state."""
    if not isinstance(response, dict) or response.get("error") or response.get("code") != 200:
        return []
    data = response.get("data")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("server")]


def select_server_status(response: Any, server: str) -> Optional[Dict[str, Any]]:
    return next((item for item in server_status_items(response) if item.get("server") == server), None)
