from __future__ import annotations

from typing import Any, Awaitable, Callable

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment


def _prepare_template_data(
    rank_data: dict[str, Any], rank_type: str
) -> list[tuple[Any, Any, str, Any]]:
    if not rank_data or rank_type not in rank_data:
        return []
    sorted_list = rank_data[rank_type].get("list", [])
    if not sorted_list:
        return []
    valid_count = rank_data[rank_type].get("valid_count", 0)
    min_score = rank_data[rank_type].get("min_score")
    return [
        (k, v, f"{v / valid_count * 100:.1f}%" if valid_count > 0 else "0%", min_score)
        for k, v in sorted_list
    ]


async def render_combined_ranking_image(
    *,
    env: Environment,
    render_template_image: Callable[..., Awaitable[bytes]],
    current_season: Any,
    stats: dict[str, Any],
    week_info: str,
) -> dict[str, Any]:
    has_top_1000 = "top_1000" in stats
    scope_desc = "前200、前100、前50"
    if has_top_1000:
        scope_desc = "前1000、前200、前100、前50"

    image_bytes = await render_template_image(
        env,
        "竞技场心法排名统计.html",
        {
            "current_season": current_season,
            "week_info": week_info,
            "scope_desc": scope_desc,
            "top_1000_healer": _prepare_template_data(stats.get("top_1000", {}), "healer") if has_top_1000 else [],
            "top_1000_dps": _prepare_template_data(stats.get("top_1000", {}), "dps") if has_top_1000 else [],
            "top_200_healer": _prepare_template_data(stats.get("top_200", {}), "healer"),
            "top_200_dps": _prepare_template_data(stats.get("top_200", {}), "dps"),
            "top_100_healer": _prepare_template_data(stats.get("top_100", {}), "healer"),
            "top_100_dps": _prepare_template_data(stats.get("top_100", {}), "dps"),
            "top_50_healer": _prepare_template_data(stats.get("top_50", {}), "healer"),
            "top_50_dps": _prepare_template_data(stats.get("top_50", {}), "dps"),
            "has_top_1000": has_top_1000,
        },
        width=1120,
        height="ck",
    )

    processed_key = "top_1000" if has_top_1000 else "top_200"
    total_valid_data = (stats.get(processed_key, {}) or {}).get("total_valid_count", 0) or 0
    processed_label = "前1000名" if has_top_1000 else "前200名"

    return {
        "image_bytes": image_bytes,
        "total_valid_data": total_valid_data,
        "processed_label": processed_label,
        "scope_desc": scope_desc,
        "has_top_1000": has_top_1000,
    }


async def send_combined_ranking_image(
    bot: Bot,
    event: Event,
    *,
    env: Environment,
    render_template_image: Callable[..., Awaitable[bytes]],
    current_season: Any,
    stats: dict[str, Any],
    week_info: str,
) -> None:
    payload = await render_combined_ranking_image(
        env=env,
        render_template_image=render_template_image,
        current_season=current_season,
        stats=stats,
        week_info=week_info,
    )
    await bot.send(event, MessageSegment.image(payload["image_bytes"]))
    await bot.send(
        event,
        f"统计完成！共处理 {payload['total_valid_data']} 条有效数据（{payload['processed_label']}），统计范围：{payload['scope_desc']}",
    )


async def send_split_ranking_images(
    bot: Bot,
    event: Event,
    *,
    env: Environment,
    render_template_image: Callable[..., Awaitable[bytes]],
    current_season: Any,
    stats: dict[str, Any],
    week_info: str,
) -> None:
    has_top_1000 = "top_1000" in stats
    ranking_configs = []
    if has_top_1000:
        ranking_configs.extend(
            [
                {
                    "name": "前1000奶妈",
                    "template": "竞技场心法排名_前1000奶妈.html",
                    "data_key": "top_1000_healer",
                    "data": _prepare_template_data(stats.get("top_1000", {}), "healer"),
                },
                {
                    "name": "前1000DPS",
                    "template": "竞技场心法排名_前1000DPS.html",
                    "data_key": "top_1000_dps",
                    "data": _prepare_template_data(stats.get("top_1000", {}), "dps"),
                },
            ]
        )
    ranking_configs.extend(
        [
            {
                "name": "前200奶妈",
                "template": "竞技场心法排名_前200奶妈.html",
                "data_key": "top_200_healer",
                "data": _prepare_template_data(stats.get("top_200", {}), "healer"),
            },
            {
                "name": "前200DPS",
                "template": "竞技场心法排名_前200DPS.html",
                "data_key": "top_200_dps",
                "data": _prepare_template_data(stats.get("top_200", {}), "dps"),
            },
            {
                "name": "前100奶妈",
                "template": "竞技场心法排名_前100奶妈.html",
                "data_key": "top_100_healer",
                "data": _prepare_template_data(stats.get("top_100", {}), "healer"),
            },
            {
                "name": "前100DPS",
                "template": "竞技场心法排名_前100DPS.html",
                "data_key": "top_100_dps",
                "data": _prepare_template_data(stats.get("top_100", {}), "dps"),
            },
            {
                "name": "前50奶妈",
                "template": "竞技场心法排名_前50奶妈.html",
                "data_key": "top_50_healer",
                "data": _prepare_template_data(stats.get("top_50", {}), "healer"),
            },
            {
                "name": "前50DPS",
                "template": "竞技场心法排名_前50DPS.html",
                "data_key": "top_50_dps",
                "data": _prepare_template_data(stats.get("top_50", {}), "dps"),
            },
        ]
    )

    images_sent = 0
    for i, config in enumerate(ranking_configs, 1):
        try:
            image_bytes = await render_template_image(
                env,
                config["template"],
                {
                    "current_season": current_season,
                    "week_info": week_info,
                    config["data_key"]: config["data"],
                },
                width=800,
                height="ck",
            )
            await bot.send(event, MessageSegment.image(image_bytes))
            images_sent += 1
            if i < len(ranking_configs):
                import asyncio

                await asyncio.sleep(1)
        except Exception as exc:
            print(f"生成{config['name']}图片失败: {exc}")
            await bot.send(event, f"生成{config['name']}图片失败: {str(exc)}")

    processed_key = "top_1000" if has_top_1000 else "top_200"
    total_valid_data = (stats.get(processed_key, {}) or {}).get("total_valid_count", 0) or 0
    processed_label = "前1000名" if has_top_1000 else "前200名"

    await bot.send(
        event,
        f"拆分统计完成！共处理 {total_valid_data} 条有效数据（{processed_label}），已生成{images_sent}张详细排名图",
    )

