from __future__ import annotations

from typing import Any

from src.services.jx3.group_binding import get_server_by_group
from src.infra.jx3api_get import get, idget


class CommandContextError(RuntimeError):
    def __init__(self, message: str, *, at_user: bool = False):
        super().__init__(message)
        self.message = message
        self.at_user = at_user


async def resolve_server_and_name(
    foo: tuple[Any, ...],
    *,
    group_id: str | int | None,
    require_group_binding: bool = True,
    group_binding_tip: str = "本群未绑定服务器，请先绑定服务器或指定服务器名称",
) -> tuple[str, str] | None:
    """
    从正则分组/群绑定解析 (server, name)；失败时直接回复并返回 None。

    约定：
    - foo[0] 为“仅输入角色名”的场景（未显式指定服务器）
    - foo[1], foo[2] 为“显式指定服务器 + 角色名”的场景
    """
    if len(foo) < 1:
        return None

    if foo[0] is None:
        if len(foo) < 3:
            return None
        server = foo[1]
        name = foo[2]
    else:
        name = foo[0]
        server = await get_server_by_group(group_id or "")
        if not server and require_group_binding:
            raise CommandContextError(group_binding_tip, at_user=False)

    if not await idget(server):
        raise CommandContextError("请输入正确的服务器！", at_user=True)

    return server, name


def api_error_text(items: Any) -> str:
    if isinstance(items, dict):
        if items.get("code") == 406:
            return "   查询结果:406错误，推栏接口等待更新！"
        msg = items.get("msg")
        if msg:
            return f"   查询结果:{msg}"
    return "   查询结果:未知错误"


async def fetch_jx3api_or_raise(
    *,
    url: str,
    server: str,
    name: str,
    token: str | None = None,
    ticket: str | None = None,
    zili: int | None = None,
) -> dict[str, Any] | None:
    """
    调用 infra.get 并统一处理失败；成功时返回响应 dict，否则抛出 CommandContextError。
    """
    items = await get(url=url, server=server, name=name, token=token, ticket=ticket, zili=zili)
    if isinstance(items, dict) and items.get("msg") == "success":
        return items

    raise CommandContextError(api_error_text(items), at_user=True)
