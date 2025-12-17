from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment


@dataclass(frozen=True)
class JjcRankingService:
    token: str
    ticket: str
    jjc_query_url: str
    arena_time_tag_url: str
    arena_ranking_url: str
    jjc_ranking_cache_file: str
    jjc_ranking_cache_duration: int
    kungfu_cache_duration: int
    current_season: Any
    current_season_start: str
    kungfu_healer_list: list[str]
    kungfu_dps_list: list[str]
    kungfu_pinyin_to_chinese: dict[str, str]
    tuilan_request: Callable[[str, dict[str, Any]], Any]
    defget_get: Callable[..., Awaitable[dict[str, Any]]]
    get_kungfu_by_role_info: Callable[[str, str, str], Any]
    env: Any
    render_template_image: Callable[..., Awaitable[bytes]]

    def get_arena_time_tag(self, type_param: str = "role") -> dict[str, Any]:
        url = self.arena_time_tag_url
        params = {"type": type_param}

        print("正在请求竞技场时间标签...")
        print(f"请求地址: {url}")
        print(f"请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                print("❌ 竞技场时间标签请求失败: 返回None")
                return {"error": "请求返回None"}

            if "error" in result:
                print(f"❌ 竞技场时间标签请求失败: {result['error']}")
                return result

            print("✅ 竞技场时间标签请求成功")
            return result
        except Exception as exc:
            print(f"❌ 竞技场时间标签请求异常: {exc}")
            import traceback

            traceback.print_exc()
            return {"error": f"请求异常: {exc}"}

    def get_arena_ranking(self, tag: int) -> dict[str, Any]:
        url = self.arena_ranking_url
        params = {"typeName": "week", "heiMaBang": False, "tag": tag}

        print("正在请求竞技场排行榜...")
        print(f"请求地址: {url}")
        print(f"请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                print("❌ 竞技场排行榜请求失败: 返回None")
                return {"error": "请求返回None"}

            if "error" in result:
                print(f"❌ 竞技场排行榜请求失败: {result['error']}")
                return result

            print("✅ 竞技场排行榜请求成功")
            return result
        except Exception as exc:
            print(f"❌ 竞技场排行榜请求异常: {exc}")
            import traceback

            traceback.print_exc()
            return {"error": f"请求异常: {exc}"}

    async def query_jjc_ranking(self) -> dict[str, Any]:
        cache_dir = os.path.dirname(self.jjc_ranking_cache_file)
        os.makedirs(cache_dir, exist_ok=True)

        current_time = time.time()
        if os.path.exists(self.jjc_ranking_cache_file):
            try:
                with open(self.jjc_ranking_cache_file, "r", encoding="utf-8") as file_handle:
                    cached_data = json.load(file_handle)

                cache_time = cached_data.get("cache_time", 0)
                if current_time - cache_time < self.jjc_ranking_cache_duration:
                    print("使用文件缓存的竞技场排行榜数据")
                    return cached_data.get("data")
                print("文件缓存已过期")
            except Exception as exc:
                print(f"读取文件缓存失败: {exc}")

        print("正在查询竞技场排行榜数据...")

        try:
            print("第一步：获取竞技场时间标签...")
            time_tag_result = self.get_arena_time_tag()

            if time_tag_result.get("error"):
                print(f"获取时间标签失败: {time_tag_result}")
                return {
                    "error": True,
                    "message": f"获取时间标签失败: {time_tag_result.get('error', '未知错误')}",
                }

            if time_tag_result.get("code") != 0:
                print(f"获取时间标签失败: {time_tag_result}")
                return {
                    "error": True,
                    "message": f"获取时间标签失败: {time_tag_result.get('msg', '未知错误')}",
                }

            await asyncio.sleep(5.45)

            data = time_tag_result.get("data", {})
            default_week = int(data.get("defaultWeek") or 0)
            if default_week <= 0:
                return {
                    "error": True,
                    "message": f"获取时间标签失败: 缺少 defaultWeek 参数: {data}",
                }

            tag = default_week

            print(f"获取到 defaultWeek={default_week}, tag={tag}")
            print("第二步：获取竞技场排行榜...")
            ranking_result = self.get_arena_ranking(tag)

            if ranking_result.get("error"):
                return {"error": True, "message": f"获取竞技场排行榜失败: {ranking_result.get('error')}"}

            if ranking_result.get("code") != 0:
                return {
                    "error": True,
                    "message": f"获取竞技场排行榜失败: {ranking_result.get('msg', '未知错误')}",
                }

            ranking_result["defaultWeek"] = default_week
            ranking_result["cache_time"] = time.time()

            try:
                with open(self.jjc_ranking_cache_file, "w", encoding="utf-8") as file_handle:
                    json.dump(
                        {
                            "cache_time": ranking_result["cache_time"],
                            "data": ranking_result,
                        },
                        file_handle,
                        ensure_ascii=False,
                        indent=2,
                    )
                print(f"竞技场排行榜数据已保存到文件缓存: {self.jjc_ranking_cache_file}")
            except Exception as exc:
                print(f"保存文件缓存失败: {exc}")

            return ranking_result
        except Exception as exc:
            import traceback

            error_traceback = traceback.format_exc()
            print(f"查询竞技场排行榜失败: {error_traceback}")
            return {"error": True, "message": f"查询竞技场排行榜失败: {exc}"}

    async def update_kuangfu_cache(self, server: str, name: str, jjc_data: dict[str, Any]) -> None:
        cache_dir = "data/cache/kuangfu"
        cache_file = os.path.join(cache_dir, f"{server}_{name}.json")
        os.makedirs(cache_dir, exist_ok=True)

        print(f"优先使用心法查询接口更新 {server}_{name} 的心法信息")

        kuangfu_info = None
        try:
            ranking_result = await self.query_jjc_ranking()
            if ranking_result and not ranking_result.get("error") and ranking_result.get("code") == 0:
                ranking_data = ranking_result.get("data", [])
                for player in ranking_data:
                    person_info = player.get("personInfo", {})
                    player_server = person_info.get("server")
                    player_name = person_info.get("roleName")

                    if player_name and "·" in player_name:
                        player_name = player_name.split("·")[0]

                    if player_server == server and player_name == name:
                        game_role_id = person_info.get("gameRoleId")
                        zone = person_info.get("zone")

                        if game_role_id and zone:
                            print(
                                f"在排行榜中找到角色: {server}_{name}, 角色ID: {game_role_id}, 大区: {zone}"
                            )
                            kungfu_name = self.get_kungfu_by_role_info(game_role_id, zone, server)
                            if kungfu_name:
                                print(f"心法查询成功: {kungfu_name}")
                                kuangfu_info = kungfu_name
                                break
                            print("心法查询失败: 未找到心法信息")
                            break

                if not kuangfu_info:
                    print(f"在排行榜中未找到匹配的角色: {server}_{name}")
            else:
                print("获取排行榜数据失败，无法进行心法查询")
        except Exception as exc:
            print(f"心法查询过程中出错: {exc}")

        if not kuangfu_info:
            print("心法查询失败，从竞技场数据中提取心法信息作为备选方案...")
            history_data = jjc_data.get("data", {}).get("history", [])
            if history_data:
                for match in history_data:
                    if match.get("won"):
                        kuangfu_info = match.get("kungfu")
                        break

        result = {
            "server": server,
            "name": name,
            "kuangfu": kuangfu_info,
            "found": kuangfu_info is not None,
            "cache_time": time.time(),
        }

        if kuangfu_info:
            print(f"更新kuangfu缓存到文件: {cache_file}")
            try:
                with open(cache_file, "w", encoding="utf-8") as file_handle:
                    json.dump(result, file_handle, ensure_ascii=False, indent=2)
                print(f"kuangfu信息已更新缓存到: {cache_file}")
            except Exception as exc:
                print(f"更新缓存失败: {exc}")
        else:
            print(f"未找到心法信息，不保存缓存: {server}_{name}")

    async def get_user_kuangfu(self, server: str, name: str) -> dict[str, Any]:
        cache_dir = "data/cache/kuangfu"
        cache_file = os.path.join(cache_dir, f"{server}_{name}.json")
        os.makedirs(cache_dir, exist_ok=True)

        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as file_handle:
                    cached_data = json.load(file_handle)
                cache_time = cached_data.get("cache_time", 0)
                kungfu_value = cached_data.get("kuangfu")

                if kungfu_value not in [None, ""]:
                    current_time = time.time()
                    if cache_time and current_time - cache_time < self.kungfu_cache_duration:
                        return cached_data

                    cache_dt = (
                        datetime.fromtimestamp(cache_time).strftime("%Y-%m-%d %H:%M:%S")
                        if cache_time
                        else "未知"
                    )
                    print(
                        f"心法缓存已超过一周或缺少时间标记，重新请求数据: {server}_{name}（缓存时间: {cache_dt}）"
                    )
                else:
                    print(f"缓存 kuangfu 为空，重新请求数据: {server}_{name}")
            except Exception as exc:
                print(f"读取缓存文件失败: {exc}")

        delay = random.uniform(3, 5)
        print(f"等待 {delay:.2f} 秒后发起请求...")
        await asyncio.sleep(delay)

        print(f"优先使用心法查询接口查询 {server}_{name} 的心法信息")

        try:
            ranking_result = await self.query_jjc_ranking()
            if ranking_result and not ranking_result.get("error") and ranking_result.get("code") == 0:
                ranking_data = ranking_result.get("data", [])

                for player in ranking_data:
                    person_info = player.get("personInfo", {})
                    player_server = person_info.get("server")
                    player_name = person_info.get("roleName")

                    if player_name and "·" in player_name:
                        player_name = player_name.split("·")[0]

                    if player_server == server and player_name == name:
                        game_role_id = person_info.get("gameRoleId")
                        zone = person_info.get("zone")

                        if game_role_id and zone:
                            print(
                                f"在排行榜中找到角色: {server}_{name}, 角色ID: {game_role_id}, 大区: {zone}"
                            )

                            kungfu_name = self.get_kungfu_by_role_info(game_role_id, zone, server)
                            if kungfu_name:
                                print(f"心法查询成功: {kungfu_name}")
                                result = {
                                    "server": server,
                                    "name": name,
                                    "kuangfu": kungfu_name,
                                    "found": True,
                                    "cache_time": time.time(),
                                }
                                try:
                                    with open(cache_file, "w", encoding="utf-8") as file_handle:
                                        json.dump(result, file_handle, ensure_ascii=False, indent=2)
                                    print(f"心法信息已更新缓存到: {cache_file}")
                                except Exception as exc:
                                    print(f"更新缓存失败: {exc}")
                                return result

                            print("心法查询失败: 未找到心法信息")
                            break

                print(f"在排行榜中未找到匹配的角色: {server}_{name}")
            else:
                print("获取排行榜数据失败，无法进行心法查询")
        except Exception as exc:
            print(f"心法查询过程中出错: {exc}")

        print("心法查询失败，使用竞技场数据查询作为备选方案...")
        print(f"正在查询 {server}_{name} 的竞技场数据")
        jjc_data = await self.defget_get(
            url=self.jjc_query_url,
            server=server,
            name=name,
            token=self.token,
            ticket=self.ticket,
        )

        if jjc_data.get("error") or jjc_data.get("msg") != "success":
            print(f"获取竞技场数据失败: {jjc_data}")
            return {
                "error": True,
                "message": f"获取竞技场数据失败: {jjc_data.get('message', '未知错误')}",
                "server": server,
                "name": name,
            }

        await self.update_kuangfu_cache(server, name, jjc_data)

        kuangfu_info = None
        history_data = jjc_data.get("data", {}).get("history", [])
        if history_data:
            for match in history_data:
                if match.get("won") is True:
                    kuangfu_info = match.get("kungfu")
                    break

        return {
            "server": server,
            "name": name,
            "kuangfu": kuangfu_info,
            "found": kuangfu_info is not None,
            "cache_time": time.time(),
        }

    async def get_ranking_kuangfu_data(self, ranking_data: dict[str, Any]) -> dict[str, Any]:
        try:
            data_list = ranking_data.get("data", [])
            if not data_list:
                return {"error": True, "message": "排行榜数据为空"}

            kuangfu_results: list[dict[str, Any]] = []
            ranking_kungfu_lines: list[str] = []
            missing_kungfu_lines: list[str] = []

            total_players = len(data_list)
            print(f"竞技场排行榜总人数: {total_players}")

            for i, player in enumerate(data_list):
                person_info = player.get("personInfo", {})
                server = person_info.get("server", "未知")
                name = person_info.get("roleName", "未知")
                score = person_info.get("score")

                if name and "·" in name:
                    name = name.split("·")[0]

                kuangfu_info = await self.get_user_kuangfu(server, name)
                kuangfu_results.append(
                    {
                        "server": server,
                        "name": name,
                        "score": score,
                        "kuangfu": kuangfu_info.get("kuangfu"),
                        "found": kuangfu_info.get("found", False),
                    }
                )

                if kuangfu_info.get("found") and kuangfu_info.get("kuangfu"):
                    ranking_kungfu_lines.append(f"{i + 1}. {server} {name} - {kuangfu_info['kuangfu']}")
                else:
                    missing_kungfu_lines.append(f"{i + 1}. {server} {name}")

            def count_kuangfu_by_rank(player_data: list[dict[str, Any]], max_rank: int) -> dict[str, Any]:
                healer_kuangfu = self.kungfu_healer_list
                dps_kuangfu = self.kungfu_dps_list

                healer_count: dict[str, int] = {}
                dps_count: dict[str, int] = {}

                healer_valid_count = 0
                dps_valid_count = 0
                invalid_count = 0
                invalid_details: list[str] = []

                healer_first_rank: dict[str, int] = {}
                dps_first_rank: dict[str, int] = {}

                healer_min_score = None
                dps_min_score = None

                for kuangfu in healer_kuangfu:
                    healer_count[kuangfu] = 0
                for kuangfu in dps_kuangfu:
                    dps_count[kuangfu] = 0

                for i, player_item in enumerate(player_data[:max_rank]):
                    if player_item.get("found") and player_item.get("kuangfu"):
                        kuangfu = player_item["kuangfu"]
                        score = player_item.get("score")

                        if kuangfu in healer_kuangfu:
                            healer_count[kuangfu] = healer_count.get(kuangfu, 0) + 1
                            healer_valid_count += 1
                            if kuangfu not in healer_first_rank:
                                healer_first_rank[kuangfu] = i + 1
                            if score is not None and (
                                healer_min_score is None or score < healer_min_score
                            ):
                                healer_min_score = score
                        elif kuangfu in dps_kuangfu:
                            dps_count[kuangfu] = dps_count.get(kuangfu, 0) + 1
                            dps_valid_count += 1
                            if kuangfu not in dps_first_rank:
                                dps_first_rank[kuangfu] = i + 1
                            if score is not None and (dps_min_score is None or score < dps_min_score):
                                dps_min_score = score
                        else:
                            print(
                                f"⚠️ 发现未分类心法：第{i+1}名 {player_item.get('server', '未知')} "
                                f"{player_item.get('name', '未知')} - {kuangfu}"
                            )
                    else:
                        invalid_count += 1
                        invalid_details.append(
                            f"第{i+1}名：{player_item.get('server', '未知')} {player_item.get('name', '未知')}"
                        )

                for i, kuangfu in enumerate(healer_kuangfu):
                    if kuangfu not in healer_first_rank:
                        healer_first_rank[kuangfu] = 9999 + i
                for i, kuangfu in enumerate(dps_kuangfu):
                    if kuangfu not in dps_first_rank:
                        dps_first_rank[kuangfu] = 9999 + i

                sorted_healer = sorted(
                    healer_count.items(),
                    key=lambda x: (x[1], -healer_first_rank[x[0]]),
                    reverse=True,
                )
                sorted_dps = sorted(
                    dps_count.items(),
                    key=lambda x: (x[1], -dps_first_rank[x[0]]),
                    reverse=True,
                )

                if invalid_details:
                    print(f"\n⚠️ 前{max_rank}名中无效数据角色（共{len(invalid_details)}个）：")
                    for detail in invalid_details:
                        print(f"  {detail}")

                return {
                    "total_players": max_rank,
                    "healer": {
                        "valid_count": healer_valid_count,
                        "distribution": dict(sorted_healer),
                        "list": sorted_healer,
                        "min_score": healer_min_score,
                    },
                    "dps": {
                        "valid_count": dps_valid_count,
                        "distribution": dict(sorted_dps),
                        "list": sorted_dps,
                        "min_score": dps_min_score,
                    },
                    "total_valid_count": healer_valid_count + dps_valid_count,
                    "invalid_count": invalid_count,
                    "invalid_details": invalid_details,
                    "unclassified_count": max_rank - (healer_valid_count + dps_valid_count + invalid_count),
                }

            print("正在统计kuangfu分布...")
            kuangfu_stats: dict[str, Any] = {}
            if total_players >= 1000:
                print("检测到排行榜包含1000条数据，开始统计前1000心法分布...")
                kuangfu_stats["top_1000"] = count_kuangfu_by_rank(kuangfu_results, 1000)
            kuangfu_stats["top_200"] = count_kuangfu_by_rank(kuangfu_results, 200)
            kuangfu_stats["top_100"] = count_kuangfu_by_rank(kuangfu_results, 100)
            kuangfu_stats["top_50"] = count_kuangfu_by_rank(kuangfu_results, 50)

            result: dict[str, Any] = {
                "kuangfu_statistics": kuangfu_stats,
                "ranking_kungfu_lines": ranking_kungfu_lines,
                "missing_kungfu_lines": missing_kungfu_lines,
            }

            print("\n" + "=" * 80)
            print("KUANGFU统计结果 (奶妈/DPS分类)")
            print("=" * 80)

            for rank_range, stats in kuangfu_stats.items():
                print(
                    f"\n{rank_range.upper()} ({stats['total_players']}人，有效数据{stats['total_valid_count']}人，"
                    f"无效数据{stats['invalid_count']}人):"
                )
                print("=" * 60)

                print(f"\n【奶妈排名】({stats['healer']['valid_count']}人):")
                print("-" * 40)
                if stats["healer"]["list"]:
                    for kuangfu, count in stats["healer"]["list"]:
                        percentage = (
                            (count / stats["healer"]["valid_count"] * 100)
                            if stats["healer"]["valid_count"] > 0
                            else 0
                        )
                        print(f"  {kuangfu}: {count}人 ({percentage:.1f}%)")
                else:
                    print("  无奶妈数据")

                print(f"\n【DPS排名】({stats['dps']['valid_count']}人):")
                print("-" * 40)
                if stats["dps"]["list"]:
                    for kuangfu, count in stats["dps"]["list"]:
                        percentage = (
                            (count / stats["dps"]["valid_count"] * 100)
                            if stats["dps"]["valid_count"] > 0
                            else 0
                        )
                        print(f"  {kuangfu}: {count}人 ({percentage:.1f}%)")
                else:
                    print("  无DPS数据")

            print("=" * 80)

            return result
        except Exception as exc:
            import traceback

            error_traceback = traceback.format_exc()
            print(f"获取心法分布数据失败: {error_traceback}")
            return {"error": True, "message": f"获取心法分布数据失败: {exc}"}

    async def render_combined_ranking_image(self, stats: dict[str, Any], week_info: str) -> dict[str, Any]:
        def prepare_template_data(rank_data: dict[str, Any], rank_type: str) -> list[tuple[Any, Any, str, Any]]:
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

        has_top_1000 = "top_1000" in stats
        scope_desc = "前200、前100、前50"
        if has_top_1000:
            scope_desc = "前1000、前200、前100、前50"

        image_bytes = await self.render_template_image(
            self.env,
            "竞技场心法排名统计.html",
            {
                "current_season": self.current_season,
                "week_info": week_info,
                "scope_desc": scope_desc,
                "top_1000_healer": prepare_template_data(stats.get("top_1000", {}), "healer")
                if has_top_1000
                else [],
                "top_1000_dps": prepare_template_data(stats.get("top_1000", {}), "dps")
                if has_top_1000
                else [],
                "top_200_healer": prepare_template_data(stats.get("top_200", {}), "healer"),
                "top_200_dps": prepare_template_data(stats.get("top_200", {}), "dps"),
                "top_100_healer": prepare_template_data(stats.get("top_100", {}), "healer"),
                "top_100_dps": prepare_template_data(stats.get("top_100", {}), "dps"),
                "top_50_healer": prepare_template_data(stats.get("top_50", {}), "healer"),
                "top_50_dps": prepare_template_data(stats.get("top_50", {}), "dps"),
                "has_top_1000": has_top_1000,
            },
            width=1120,
            height="ck",
        )

        processed_key = "top_1000" if has_top_1000 else "top_200"
        total_valid_data = 0
        if stats:
            total_valid_data = stats.get(processed_key, {}).get("total_valid_count", 0) or 0
        processed_label = "前1000名" if has_top_1000 else "前200名"

        return {
            "image_bytes": image_bytes,
            "total_valid_data": total_valid_data,
            "processed_label": processed_label,
            "scope_desc": scope_desc,
            "has_top_1000": has_top_1000,
        }

    async def generate_combined_ranking_image(
        self, bot: Bot, event: Event, stats: dict[str, Any], week_info: str
    ) -> None:
        payload = await self.render_combined_ranking_image(stats, week_info)
        if not payload:
            await bot.send(event, "生成统计图片失败：返回数据为空")
            return

        await bot.send(event, MessageSegment.image(payload["image_bytes"]))
        await bot.send(
            event,
            f"统计完成！共处理 {payload['total_valid_data']} 条有效数据（{payload['processed_label']}），统计范围：{payload['scope_desc']}",
        )

    async def generate_split_ranking_images(
        self, bot: Bot, event: Event, stats: dict[str, Any], week_info: str
    ) -> None:
        def prepare_template_data(rank_data: dict[str, Any], rank_type: str) -> list[tuple[Any, Any, str, Any]]:
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

        has_top_1000 = "top_1000" in stats
        ranking_configs: list[dict[str, Any]] = []

        if has_top_1000:
            ranking_configs.extend(
                [
                    {
                        "name": "前1000奶妈",
                        "template": "竞技场心法排名_前1000奶妈.html",
                        "data_key": "top_1000_healer",
                        "data": prepare_template_data(stats.get("top_1000", {}), "healer"),
                    },
                    {
                        "name": "前1000DPS",
                        "template": "竞技场心法排名_前1000DPS.html",
                        "data_key": "top_1000_dps",
                        "data": prepare_template_data(stats.get("top_1000", {}), "dps"),
                    },
                ]
            )

        ranking_configs.extend(
            [
                {
                    "name": "前200奶妈",
                    "template": "竞技场心法排名_前200奶妈.html",
                    "data_key": "top_200_healer",
                    "data": prepare_template_data(stats.get("top_200", {}), "healer"),
                },
                {
                    "name": "前200DPS",
                    "template": "竞技场心法排名_前200DPS.html",
                    "data_key": "top_200_dps",
                    "data": prepare_template_data(stats.get("top_200", {}), "dps"),
                },
                {
                    "name": "前100奶妈",
                    "template": "竞技场心法排名_前100奶妈.html",
                    "data_key": "top_100_healer",
                    "data": prepare_template_data(stats.get("top_100", {}), "healer"),
                },
                {
                    "name": "前100DPS",
                    "template": "竞技场心法排名_前100DPS.html",
                    "data_key": "top_100_dps",
                    "data": prepare_template_data(stats.get("top_100", {}), "dps"),
                },
                {
                    "name": "前50奶妈",
                    "template": "竞技场心法排名_前50奶妈.html",
                    "data_key": "top_50_healer",
                    "data": prepare_template_data(stats.get("top_50", {}), "healer"),
                },
                {
                    "name": "前50DPS",
                    "template": "竞技场心法排名_前50DPS.html",
                    "data_key": "top_50_dps",
                    "data": prepare_template_data(stats.get("top_50", {}), "dps"),
                },
            ]
        )

        images_sent = 0
        for i, config in enumerate(ranking_configs, 1):
            try:
                image_bytes = await self.render_template_image(
                    self.env,
                    config["template"],
                    {
                        "current_season": self.current_season,
                        "week_info": week_info,
                        config["data_key"]: config["data"],
                    },
                    width=800,
                    height="ck",
                )
                await bot.send(event, MessageSegment.image(image_bytes))
                images_sent += 1
                if i < len(ranking_configs):
                    await asyncio.sleep(1)
            except Exception as exc:
                print(f"生成{config['name']}图片失败: {exc}")
                await bot.send(event, f"生成{config['name']}图片失败: {str(exc)}")

        processed_key = "top_1000" if has_top_1000 else "top_200"
        total_valid_data = 0
        if stats:
            total_valid_data = stats.get(processed_key, {}).get("total_valid_count", 0) or 0
        processed_label = "前1000名" if has_top_1000 else "前200名"

        await bot.send(
            event,
            f"拆分统计完成！共处理 {total_valid_data} 条有效数据（{processed_label}），已生成{images_sent}张详细排名图",
        )

    def calculate_season_week_info(self, default_week: int, cache_time: float | None = None) -> str:
        try:
            now = datetime.fromtimestamp(cache_time) if cache_time else datetime.now()
            season_start = datetime.strptime(self.current_season_start, "%Y-%m-%d")

            def week_monday(dt: datetime) -> datetime:
                monday = dt - timedelta(days=dt.weekday())
                return monday.replace(hour=0, minute=0, second=0, microsecond=0)

            season_anchor_monday = week_monday(season_start)
            current_monday = week_monday(now)
            season_week_now = max(1, ((current_monday - season_anchor_monday).days // 7) + 1)
            api_week = max(1, int(default_week))

            now_iso_year, now_iso_week, _ = now.isocalendar()
            api_year = now_iso_year
            week_gap = api_week - now_iso_week
            if week_gap > 26:
                api_year -= 1
            elif week_gap < -26:
                api_year += 1

            try:
                target_monday = datetime.fromisocalendar(api_year, api_week, 1)
            except ValueError:
                print(
                    f"calculate_season_week_info: defaultWeek={default_week} 生成ISO日期失败，使用当前周"
                )
                target_monday = current_monday

            season_week_from_api = max(
                1, ((target_monday - season_anchor_monday).days // 7) + 1
            )
            weekday_names = ["周1", "周2", "周3", "周4", "周5", "周6", "周7"]
            weekday_str = weekday_names[now.weekday()]
            time_str = now.strftime("%H:%M")

            print(
                f"defaultWeek={default_week} season_anchor_monday={season_anchor_monday} current_monday={current_monday} "
                f"season_week_now={season_week_now} api_week={api_week} target_monday={target_monday} "
                f"weekday_str={weekday_str} time_str={time_str}"
            )
            if target_monday < current_monday:
                return f"第{season_week_from_api}周 结算"

            if target_monday == current_monday:
                return f"第{season_week_now}周 {weekday_str} {time_str}"

            print(
                f"calculate_season_week_info: defaultWeek={api_week} 指向未来周，锚定赛季周 {season_week_from_api}"
            )
            return f"第{season_week_from_api}周 {weekday_str} {time_str}"

        except Exception as exc:
            print(f"计算赛季周信息失败: {exc}")
            return f"第{default_week}周"
