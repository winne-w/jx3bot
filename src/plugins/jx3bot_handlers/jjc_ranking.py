from __future__ import annotations

from typing import Any, Awaitable, Callable

from nonebot.adapters.onebot.v11 import Bot, Event


def register(
    zhanji_ranking_matcher: Any,
    *,
    query_jjc_ranking: Callable[[], Awaitable[dict]],
    calculate_season_week_info: Callable[[int, float | None], str],
    get_ranking_kuangfu_data: Callable[[dict], Awaitable[dict]],
    generate_split_ranking_images: Callable[[Bot, Event, dict, str], Awaitable[None]],
    generate_combined_ranking_image: Callable[[Bot, Event, dict, str], Awaitable[None]],
) -> None:
    @zhanji_ranking_matcher.handle()
    async def zhanji_ranking_to_image(bot: Bot, event: Event) -> None:
        try:
            message_text = event.get_plaintext().strip()
            message_text_lower = message_text.lower()
            is_split_mode = "拆分" in message_text
            is_debug_mode = "debug" in message_text_lower

            if is_split_mode:
                await bot.send(event, "正在统计竞技场心法排名（拆分模式），请稍候...")
            else:
                await bot.send(event, "正在统计竞技场心法排名，请稍候...")

            ranking_result = await query_jjc_ranking()
            if ranking_result is None:
                await bot.send(event, "获取竞技场排行榜数据失败：返回数据为空")
                return

            if ranking_result.get("error"):
                await bot.send(
                    event,
                    f"获取竞技场排行榜数据失败：{ranking_result.get('message', '未知错误')}",
                )
                return

            if ranking_result.get("code") != 0:
                await bot.send(
                    event,
                    f"获取竞技场排行榜数据失败：API返回错误码 {ranking_result.get('code')}",
                )
                return

            default_week = ranking_result.get("defaultWeek")
            cache_time = ranking_result.get("cache_time")
            week_info = (
                calculate_season_week_info(default_week, cache_time)
                if default_week
                else "第12周"
            )

            result = await get_ranking_kuangfu_data(ranking_data=ranking_result)
            if result is None:
                await bot.send(event, "获取心法分布数据失败：返回数据为空")
                return

            if result.get("error"):
                await bot.send(
                    event,
                    f"获取心法分布数据失败：{result.get('message', '未知错误')}",
                )
                return

            stats = result.get("kuangfu_statistics", {})
            if not stats:
                await bot.send(event, "心法统计数据为空，无法生成统计图片")
                return

            if is_split_mode:
                await generate_split_ranking_images(bot, event, stats, week_info)
            else:
                await generate_combined_ranking_image(bot, event, stats, week_info)

            ranking_kungfu_lines = result.get("ranking_kungfu_lines", [])
            missing_kungfu_lines = result.get("missing_kungfu_lines", [])

            if is_debug_mode and ranking_kungfu_lines:
                chunk_size = 200
                total_lines = len(ranking_kungfu_lines)
                for start in range(0, total_lines, chunk_size):
                    end = min(start + chunk_size, total_lines)
                    chunk_header = f"竞技场心法排名（第{start + 1}-{end}名）"
                    chunk_message = "\n".join(ranking_kungfu_lines[start:end])
                    await bot.send(event, f"{chunk_header}\n{chunk_message}")
            elif missing_kungfu_lines:
                chunk_size = 100
                total_lines = len(missing_kungfu_lines)
                for start in range(0, total_lines, chunk_size):
                    end = min(start + chunk_size, total_lines)
                    chunk_header = f"未查询到心法的角色（共{total_lines}人，第{start + 1}-{end}名）"
                    chunk_message = "\n".join(missing_kungfu_lines[start:end])
                    await bot.send(event, f"{chunk_header}\n{chunk_message}")

        except Exception as exc:
            import traceback

            error_traceback = traceback.format_exc()
            print(f"战绩排名统计详细错误：{error_traceback}")
            await bot.send(event, f"战绩排名统计失败：{str(exc)}")

