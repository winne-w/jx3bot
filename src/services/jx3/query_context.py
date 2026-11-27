from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple, Union


@dataclass(frozen=True)
class RenderSpec:
    template_name: str
    context: Dict[str, Any]
    width: int
    height: Union[int, str] = "ck"
    filters: Optional[Dict[str, Callable[..., Any]]] = None
    prefix: Optional[str] = "   查询结果"
    at_user: bool = True


def build_yanhua_spec(
    *,
    data: Dict[str, Any],
    role_name: str,
    server: str,
    time_filter: Callable[..., Any],
    random_text: str,
) -> RenderSpec:
    items = data["data"]
    zcslist = len(items)
    csid = sum(1 for item in items if item.get("sender") == f"{role_name}")
    jieshou = zcslist - csid

    return RenderSpec(
        template_name="烟花查询.html",
        context={
            "items": items,
            "id": role_name,
            "zcslist": zcslist,
            "csid": csid,
            "jieshou": jieshou,
            "text": random_text,
            "qufu": server,
        },
        width=760,
        height="ck",
        filters={"time": time_filter},
    )


def build_qiyu_spec(
    *,
    data: Dict[str, Any],
    role_name: str,
    server: str,
    time_filter: Callable[..., Any],
    jjc_time_filter: Callable[..., Any],
    random_text: str,
) -> RenderSpec:
    items = data["data"]
    zcslist = len(items)
    ptqiyu = sum(1 for item in items if item.get("level") == 1)
    jsqiyu = sum(1 for item in items if item.get("level") == 2)
    cwqiyu = sum(1 for item in items if item.get("level") == 3)

    return RenderSpec(
        template_name="奇遇查询.html",
        context={
            "items": items,
            "id": role_name,
            "qufu": server,
            "zcslist": zcslist,
            "ptqiyu": ptqiyu,
            "jsqiyu": jsqiyu,
            "cwqiyu": cwqiyu,
            "text": random_text,
        },
        width=760,
        height="ck",
        filters={"time": time_filter, "timejjc": jjc_time_filter},
    )


def build_zhuangfen_spec(
    *,
    data: Dict[str, Any],
    role_name: str,
    server: str,
    random_text: str,
    mpimg: Any,
) -> RenderSpec:
    menpai = data.get("data", {}).get("panelList", {}).get("panel", [{}])[0].get("name")

    return RenderSpec(
        template_name="装备查询.html",
        context={
            "items": data["data"],
            "id": role_name,
            "qufu": server,
            "newpng": "名片",
            "text": random_text,
            "mpimg": mpimg,
            "menpai": menpai,
        },
        width=760,
        height="ck",
    )


def build_fuben_spec(
    *,
    data: Dict[str, Any],
    role_name: str,
    server: str,
    random_text: str,
) -> Optional[RenderSpec]:
    payload = data["data"]
    if not payload.get("data"):
        return None

    return RenderSpec(
        template_name="副本查询.html",
        context={"items": payload, "id": role_name, "qufu": server, "text": random_text},
        width=760,
        height="ck",
    )


def build_jjc_spec_or_text(
    *,
    data: Dict[str, Any],
    role_name: str,
    server: str,
    time_filter: Callable[..., Any],
    jjc_time_filter: Callable[..., Any],
    duration_filter: Callable[..., Any],
    random_text: str,
) -> Tuple[Optional[RenderSpec], Optional[str]]:
    payload = data["data"]
    performance = payload.get("performance", {})
    if not payload or (
        performance.get("2v2") == []
        and performance.get("3v3") == []
        and performance.get("5v5") == []
    ):
        return None, f"  => 查询失败\n未找到，{server}，{role_name}，的jjc记录，等待api更新！"

    return (
        RenderSpec(
            template_name="竞技查询.html",
            context={"items": payload, "id": role_name, "qufu": server, "text": random_text},
            width=760,
            height="ck",
            filters={"time": time_filter, "jjctime": jjc_time_filter, "duration": duration_filter},
        ),
        None,
    )


def build_baizhan_spec(*, result: Dict[str, Any], random_text: str) -> RenderSpec:
    return RenderSpec(
        template_name="百战查询.html",
        context={
            "start_date": result["start_date"],
            "end_date": result["end_date"],
            "items": result["items"],
            "text": random_text,
        },
        width=760,
        height="ck",
    )


def build_role_baizhan_spec(*, result: Dict[str, Any], random_text: str) -> RenderSpec:
    return RenderSpec(
        template_name="百战角色查询.html",
        context={
            "zone_name": result["zone_name"],
            "server_name": result["server_name"],
            "role_name": result["role_name"],
            "role_id": result["role_id"],
            "global_role_id": result["global_role_id"],
            "game_energy": result["game_energy"],
            "game_stamina": result["game_stamina"],
            "skill_count": result["skill_count"],
            "skills": result["skills"],
            "update_time": result["update_time"],
            "text": random_text,
        },
        width=760,
        height="ck",
    )
