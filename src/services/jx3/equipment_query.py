"""Equipment command parsing and exact collected-loadout selection."""
import asyncio
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config as cfg
from src.services.jx3.kungfu_aliases import KungfuAliasError, resolve_kungfu_alias

QUERY_TIMEOUT_SECONDS = 45.0
_TYPE_ALIASES = {"pve": "秘境挑战", "pvp": "竞技对抗", "秘境挑战": "秘境挑战",
                 "竞技对抗": "竞技对抗", "休闲": "休闲", "通用": "通用"}
_USAGE = "用法：装备 [服务器] 角色名 [心法或别名] [PVE/PVP/休闲/通用]；也可用 心法=奶秀 类型=PVP"


class EquipmentQueryError(ValueError):
    pass


@dataclass(frozen=True)
class EquipmentCommand:
    server: Optional[str]
    name: str
    kungfu: Optional[str] = None
    equip_type: Optional[str] = None

    def identity_groups(self):
        return (None, self.server, self.name) if self.server else (self.name, None, None)


def equipment_server_names():
    from src.infra.jx3api_get import list_server_catalog_items
    return tuple(item["server"] for item in list_server_catalog_items())


def parse_equipment_command(raw: str, *, server_names: Iterable[str] = ()) -> EquipmentCommand:
    tokens = raw.split() if isinstance(raw, str) else []
    if not tokens or len(tokens) > 8:
        raise EquipmentQueryError(_USAGE)
    def resolve(value):
        try:
            return resolve_kungfu_alias(value)
        except KungfuAliasError as exc:
            raise EquipmentQueryError(str(exc)) from None
    options = {}
    identity = []

    def put(key, value):
        if key in options:
            raise EquipmentQueryError("心法或类型参数重复，请只指定一次。" + _USAGE)
        if key == "equip_type":
            value = _TYPE_ALIASES.get(value.lower())
            if value is None:
                raise EquipmentQueryError("配装类型仅支持 PVE/PVP/秘境挑战/竞技对抗/休闲/通用")
        else:
            resolved = resolve(value)
            if resolved is None:
                raise EquipmentQueryError("未知心法或别名，例如可用：云裳心经、奶秀、冰心、bx。" + _USAGE)
            value = resolved
        options[key] = value

    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            key = {"心法": "kungfu", "kungfu": "kungfu", "类型": "equip_type", "type": "equip_type"}.get(key.lower())
            if key is None or not value:
                raise EquipmentQueryError(_USAGE)
            put(key, value)
        else:
            identity.append(token)
    known_servers = set(server_names)
    minimum = 2 if identity and identity[0] in known_servers else 1
    while len(identity) > minimum:
        value = identity[-1]
        if value.lower() in _TYPE_ALIASES:
            put("equip_type", value)
        elif resolve(value) is not None:
            put("kungfu", value)
        else:
            break
        identity.pop()
    if len(identity) == 1:
        server, name = None, identity[0]
    elif len(identity) == 2:
        if options and known_servers and identity[0] not in known_servers:
            raise EquipmentQueryError("筛选查询请使用完整服务器名称，以及有效心法名或别名。" + _USAGE)
        server, name = identity
    else:
        raise EquipmentQueryError(_USAGE)
    return EquipmentCommand(server, name, **options)


def _positive_time(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def select_equipment_combination(rows, *, kungfu=None, equip_type=None) -> Tuple[str, str]:
    candidates = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = row.get("kungfuName")
        kind = row.get("equipType")
        if not isinstance(name, str) or not name or kind not in _TYPE_ALIASES.values():
            continue
        if (kungfu and name != kungfu) or (equip_type and kind != equip_type):
            continue
        candidates.setdefault((name, kind), []).append(_positive_time(row.get("cacheTime")))
    if not candidates:
        raise EquipmentQueryError("未收录符合条件的配装，请核对心法和类型；不会使用当前配装替代。")
    if len(candidates) == 1:
        return next(iter(candidates))
    choices = "；".join("{} {}".format(*pair) for pair in sorted(candidates)[:8])
    if any(value is None for values in candidates.values() for value in values):
        raise EquipmentQueryError("无法确定最新配装，请补齐心法和类型。可选：" + choices)
    newest = {pair: max(values) for pair, values in candidates.items()}
    highest = max(newest.values())
    winners = [pair for pair, timestamp in newest.items() if timestamp == highest]
    if len(winners) != 1:
        raise EquipmentQueryError("存在同时间的多套配装，请补齐心法和类型。可选：" + choices)
    return winners[0]


def _query_url(key, **options):
    base = cfg.API_URLS.get(key)
    if not base:
        raise EquipmentQueryError("{}接口未配置".format(key))
    parts = urlsplit(base)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update(options)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _payload(response):
    if not isinstance(response, dict) or response.get("error") or response.get("msg") != "success":
        message = response.get("msg") if isinstance(response, dict) else None
        raise EquipmentQueryError("配装查询失败：{}".format(message or "接口响应异常"))
    payload = response.get("data")
    if not isinstance(payload, dict):
        raise EquipmentQueryError("配装查询响应格式异常")
    return payload


def _check_identity(payload, server, name):
    if payload.get("serverName") and payload["serverName"] != server:
        raise EquipmentQueryError("返回的配装服务器不一致，请稍后重试")
    if payload.get("roleName") and payload["roleName"] != name:
        raise EquipmentQueryError("返回的配装角色不一致，请稍后重试")


async def fetch_equipment_query(*, server: str, name: str, kungfu=None, equip_type=None, fetch: Optional[Callable[..., Any]] = None):
    if fetch is None:
        from src.services.jx3.command_context import fetch_jx3api_or_raise
        fetch = fetch_jx3api_or_raise
    if equip_type is not None:
        equip_type = _TYPE_ALIASES.get(str(equip_type).lower())
        if equip_type is None:
            raise EquipmentQueryError("不支持的配装类型")
    async def run():
        if not kungfu and not equip_type:
            return await fetch(url=cfg.API_URLS["装备查询"], server=server, name=name, token=cfg.TOKEN)
        selected_kungfu, selected_type = kungfu, equip_type
        if not (selected_kungfu and selected_type):
            response = await fetch(url=_query_url("装备历史查询"), server=server, name=name, token=cfg.TOKEN)
            payload = _payload(response)
            _check_identity(payload, server, name)
            rows = payload.get("equipList", [])
            if not isinstance(rows, list):
                raise EquipmentQueryError("配装历史响应格式异常")
            selected_kungfu, selected_type = select_equipment_combination(rows, kungfu=kungfu, equip_type=equip_type)
        response = await fetch(url=_query_url("装备详情查询", kungfu=selected_kungfu, type=selected_type, format="calcd"),
                               server=server, name=name, token=cfg.TOKEN)
        payload = _payload(response)
        _check_identity(payload, server, name)
        if payload.get("kungfuName") != selected_kungfu or payload.get("equipType") != selected_type:
            raise EquipmentQueryError("详情缺少或返回了不一致的心法/类型，无法确认指定配装，请稍后重试。")
        return response
    try:
        return await asyncio.wait_for(run(), timeout=QUERY_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise EquipmentQueryError("配装查询超时，请稍后重试") from None
