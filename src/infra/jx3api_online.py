from __future__ import annotations

from typing import Any

from src.infra.http_client import HttpClient
from src.infra.jx3api_compat import normalize_jx3api_response


async def fetch_role_online(*, url: str, server: str, name: str, token: str, ticket: str) -> dict[str, Any]:
    """Read current role status with the documented POST contract, without caching."""
    if not token or not ticket:
        return {"error": "missing_credentials", "msg": "在线查询未配置访问令牌或推栏登录标识"}
    client = HttpClient(timeout=15.0, retries=0)
    response = await client.arequest_json(
        "POST", url, headers={"token": token},
        json_body={"ticket": ticket, "query": [{"server": server, "name": name}]},
    )
    return normalize_jx3api_response(url, response)
