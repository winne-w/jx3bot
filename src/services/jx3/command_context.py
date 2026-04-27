from __future__ import annotations

from typing import Any

from nonebot import logger

from src.services.jx3.group_binding import get_server_by_group
from src.services.jx3.server_resolver import resolve_master_server_name
from src.infra.jx3api_get import get, has_server_catalog, idget


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
        logger.warning("resolve_server_and_name 参数不足: foo={} group_id={}", foo, group_id)
        return None

    if foo[0] is None:
        if len(foo) < 3:
            logger.warning("resolve_server_and_name 显式区服参数不足: foo={} group_id={}", foo, group_id)
            return None
        server = foo[1]
        name = foo[2]
        logger.info(
            "resolve_server_and_name 使用显式区服: group_id={} raw_server={} role_name={}",
            group_id,
            server,
            name,
        )
    else:
        name = foo[0]
        server = await get_server_by_group(group_id or "")
        logger.info(
            "resolve_server_and_name 使用群绑定区服: group_id={} bound_server={} role_name={}",
            group_id,
            server,
            name,
        )
        if not server and require_group_binding:
            logger.warning(
                "resolve_server_and_name 群未绑定区服: group_id={} role_name={} require_group_binding={}",
                group_id,
                name,
                require_group_binding,
            )
            raise CommandContextError(group_binding_tip, at_user=False)

    if not await has_server_catalog():
        logger.warning(
            "resolve_server_and_name 区服文件不可用，直接使用输入区服: group_id={} server={} role_name={}",
            group_id,
            server,
            name,
        )
        return server, name

    if not await idget(server):
        logger.info(
            "resolve_server_and_name 区服首次校验失败，尝试主服解析: group_id={} raw_server={} role_name={}",
            group_id,
            server,
            name,
        )
        resolved_server = await resolve_master_server_name(server)
        if resolved_server != server:
            logger.info(
                "resolve_server_and_name 主服解析命中: group_id={} raw_server={} resolved_server={} role_name={}",
                group_id,
                server,
                resolved_server,
                name,
            )
            server = resolved_server
        else:
            logger.warning(
                "resolve_server_and_name 主服解析未命中: group_id={} raw_server={} role_name={}",
                group_id,
                server,
                name,
            )

    if not await idget(server):
        logger.warning(
            "resolve_server_and_name 区服校验最终失败: group_id={} final_server={} role_name={} foo={}",
            group_id,
            server,
            name,
            foo,
        )
        raise CommandContextError("请输入正确的服务器！", at_user=True)

    logger.info(
        "resolve_server_and_name 区服解析成功: group_id={} final_server={} role_name={}",
        group_id,
        server,
        name,
    )
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
