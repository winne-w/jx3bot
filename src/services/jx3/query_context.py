from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RenderSpec:
    template_name: str
    context: dict[str, Any]
    width: int
    height: int | str = "ck"
    filters: dict[str, Callable[..., Any]] | None = None
    prefix: str | None = "   查询结果"
    at_user: bool = True


def build_yanhua_spec(
    *,
    data: dict[str, Any],
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
        width=1194,
        height="ck",
        filters={"time": time_filter},
    )


def build_qiyu_spec(
    *,
    data: dict[str, Any],
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
        width=870,
        height="ck",
        filters={"time": time_filter, "timejjc": jjc_time_filter},
    )


def build_latest_match_equipment_spec(
    *,
    snapshot: dict[str, Any],
    random_text: str,
    time_filter: Callable[..., Any],
) -> RenderSpec:
    """Build the template context for a latest-3v3 equipment snapshot."""
    match_time = _match_time(snapshot.get("match_time"))
    try:
        formatted_time = time_filter(match_time, "%Y年%m月%d日 %H:%M:%S")
    except TypeError:
        formatted_time = time_filter(match_time)

    render_snapshot = dict(snapshot)
    for collection_name in ("armors", "metrics", "body_qualities"):
        if not isinstance(render_snapshot.get(collection_name), list):
            render_snapshot[collection_name] = []
    total_score = _score(snapshot.get("equip_score"))
    strength_score = _score(snapshot.get("equip_strength_score"))
    stone_score = _score(snapshot.get("stone_score"))
    render_snapshot["total_score"] = total_score
    render_snapshot["equipment_score"] = total_score - strength_score - stone_score

    return RenderSpec(
        template_name="装备查询.html",
        context={
            "title": "最近 3v3 对局装备快照",
            "snapshot": render_snapshot,
            "match_time_label": "对局时间：{}".format(formatted_time),
            "text": random_text,
        },
        width=1180,
        height="ck",
    )


def _score(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _match_time(value: Any) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError("最近 3v3 装备快照缺少有效对局时间")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("最近 3v3 装备快照缺少有效对局时间") from exc


def build_fuben_spec(
    *,
    data: dict[str, Any],
    role_name: str,
    server: str,
    random_text: str,
) -> RenderSpec | None:
    payload = data["data"]
    if not payload.get("data"):
        return None

    return RenderSpec(
        template_name="副本查询.html",
        context={"items": payload, "id": role_name, "qufu": server, "text": random_text},
        width=800,
        height="ck",
    )


def build_jjc_spec_or_text(
    *,
    data: dict[str, Any],
    role_name: str,
    server: str,
    time_filter: Callable[..., Any],
    jjc_time_filter: Callable[..., Any],
    duration_filter: Callable[..., Any],
    random_text: str,
) -> tuple[RenderSpec | None, str | None]:
    payload = data["data"]
    performance = payload.get("performance", {})
    if (
        performance.get("2v2") == []
        and performance.get("3v3") == []
        and performance.get("5v5") == []
    ):
        return None, f"  => 查询失败\n未找到，{server}，{role_name}，的jjc记录，等待api更新！"

    return (
        RenderSpec(
            template_name="竞技查询.html",
            context={"items": payload, "id": role_name, "qufu": server, "text": random_text},
            width=955,
            height="ck",
            filters={"time": time_filter, "jjctime": jjc_time_filter, "duration": duration_filter},
        ),
        None,
    )


def build_baizhan_spec(*, result: dict[str, Any], random_text: str) -> RenderSpec:
    return RenderSpec(
        template_name="百战查询.html",
        context={
            "start_date": result["start_date"],
            "end_date": result["end_date"],
            "items": result["items"],
            "text": random_text,
        },
        width=1500,
        height="ck",
    )


def build_role_baizhan_spec(*, result: dict[str, Any], random_text: str) -> RenderSpec:
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
        width=640,
        height="ck",
    )
