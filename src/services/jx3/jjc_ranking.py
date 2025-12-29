from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from nonebot import logger

from src.services.jx3.kungfu import get_kungfu_detail_by_role_info
from src.services.jx3.jjc_api_client import JjcApiClient
from src.services.jx3.jjc_cache_repo import JjcCacheRepo


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

    def _api(self) -> JjcApiClient:
        return JjcApiClient(
            arena_time_tag_url=self.arena_time_tag_url,
            arena_ranking_url=self.arena_ranking_url,
            tuilan_request=self.tuilan_request,
        )

    def _cache(self) -> JjcCacheRepo:
        return JjcCacheRepo(
            jjc_ranking_cache_file=self.jjc_ranking_cache_file,
            jjc_ranking_cache_duration=self.jjc_ranking_cache_duration,
            kungfu_cache_duration=self.kungfu_cache_duration,
        )

    @staticmethod
    def _coerce_score(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                return int(float(value))
            except ValueError:
                return None
        return None

    @classmethod
    def _extract_score(cls, player: dict[str, Any], person_info: dict[str, Any]) -> int | None:
        candidates = [
            person_info.get("score"),
            player.get("score"),
            person_info.get("rating"),
            player.get("rating"),
            person_info.get("pvpScore"),
            player.get("pvpScore"),
            person_info.get("totalScore"),
            player.get("totalScore"),
            person_info.get("avgGrade"),
            player.get("avgGrade"),
            person_info.get("grade"),
            player.get("grade"),
        ]
        for item in candidates:
            score = cls._coerce_score(item)
            if score is not None:
                return score
        return None

    async def query_jjc_ranking(self) -> dict[str, Any]:
        logger.info("开始查询竞技场排行榜数据")

        try:
            logger.info("获取竞技场时间标签")
            time_tag_result = await asyncio.to_thread(self._api().get_arena_time_tag)

            if time_tag_result.get("error"):
                logger.warning(f"获取竞技场时间标签失败: {time_tag_result}")
                return {
                    "error": True,
                    "message": f"获取时间标签失败: {time_tag_result.get('error', '未知错误')}",
                }

            if time_tag_result.get("code") != 0:
                logger.warning(f"获取竞技场时间标签失败: {time_tag_result}")
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

            logger.info(f"获取竞技场时间标签成功: defaultWeek={default_week} tag={tag}")
            logger.info("获取竞技场排行榜")
            ranking_result = await asyncio.to_thread(self._api().get_arena_ranking, tag)

            if ranking_result.get("error"):
                return {"error": True, "message": f"获取竞技场排行榜失败: {ranking_result.get('error')}"}

            if ranking_result.get("code") != 0:
                return {
                    "error": True,
                    "message": f"获取竞技场排行榜失败: {ranking_result.get('msg', '未知错误')}",
                }

            ranking_result["defaultWeek"] = default_week
            ranking_result["cache_time"] = time.time()

            return ranking_result
        except Exception as exc:
            logger.exception(f"查询竞技场排行榜失败: {exc}")
            return {"error": True, "message": f"查询竞技场排行榜失败: {exc}"}

    async def update_kungfu_cache(self, server: str, name: str, jjc_data: dict[str, Any]) -> None:
        logger.info(f"优先使用心法查询接口更新心法信息: server={server} name={name}")

        kungfu_info = None
        kungfu_detail: dict[str, Any] | None = None
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
                            logger.info(
                                f"在排行榜中找到角色: server={server} name={name} role_id={game_role_id} zone={zone}"
                            )
                            kungfu_detail = await asyncio.to_thread(
                                get_kungfu_detail_by_role_info,
                                game_role_id,
                                zone,
                                server,
                                tuilan_request=self.tuilan_request,
                                kungfu_pinyin_to_chinese=self.kungfu_pinyin_to_chinese,
                            )
                            kungfu_name = (kungfu_detail or {}).get("kungfu")
                            if kungfu_name:
                                logger.info(f"心法查询成功: server={server} name={name} kungfu={kungfu_name}")
                                kungfu_info = kungfu_name
                                break
                            logger.info("心法查询失败: 未找到心法信息")
                            break

                if not kungfu_info:
                    logger.info(f"在排行榜中未找到匹配的角色: server={server} name={name}")
            else:
                logger.warning("获取排行榜数据失败，无法进行心法查询")
        except Exception as exc:
            logger.warning(f"心法查询过程中出错: {exc}")

        if not kungfu_info:
            logger.info("心法查询失败，从竞技场数据中提取心法信息作为备选方案")
            history_data = jjc_data.get("data", {}).get("history", [])
            if history_data:
                for match in history_data:
                    if match.get("won"):
                        kungfu_info = match.get("kungfu")
                        break

        result: dict[str, Any] = {
            "server": server,
            "name": name,
            "kungfu": kungfu_info,
            "found": kungfu_info is not None,
            "cache_time": time.time(),
        }
        if kungfu_detail:
            result.update(kungfu_detail)

        self._cache().save_kungfu_cache(server, name, result)

    def save_ranking_stats(
        self,
        ranking_result: dict[str, Any],
        stats: dict[str, Any],
        week_info: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        stats_dir = os.path.join("data", "jjc_ranking_stats")
        ranking_timestamp = int(ranking_result.get("cache_time") or time.time())
        stats_path = os.path.join(stats_dir, f"{ranking_timestamp}.json")
        try:
            os.makedirs(stats_dir, exist_ok=True)
            stats_payload = {
                "generated_at": time.time(),
                "ranking_cache_time": ranking_result.get("cache_time"),
                "default_week": ranking_result.get("defaultWeek"),
                "current_season": self.current_season,
                "week_info": week_info,
                "kungfu_statistics": stats,
            }
            with open(stats_path, "w", encoding="utf-8") as file_handle:
                json.dump(stats_payload, file_handle, ensure_ascii=False, indent=2)
            logger.info("保存竞技场统计结果: {}", stats_path)
        except Exception as exc:
            logger.warning("保存竞技场统计结果失败: {}", exc)

    async def get_user_kungfu(
        self,
        server: str,
        name: str,
        ranking_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cached = self._cache().load_kungfu_cache(server, name)
        if cached:
            return cached

        delay = random.uniform(3, 5)
        logger.info(f"等待 {delay:.2f} 秒后发起请求")
        await asyncio.sleep(delay)

        logger.info(f"优先使用心法查询接口查询心法信息: server={server} name={name}")

        try:
            ranking_result = ranking_data
            if not ranking_result:
                ranking_result = await self.query_jjc_ranking()
            if ranking_result and not ranking_result.get("error") and ranking_result.get("code") == 0:
                ranking_list = ranking_result.get("data", [])

                for player in ranking_list:
                    person_info = player.get("personInfo", {})
                    player_server = person_info.get("server")
                    player_name = person_info.get("roleName")

                    if player_name and "·" in player_name:
                        player_name = player_name.split("·")[0]

                    if player_server == server and player_name == name:
                        game_role_id = person_info.get("gameRoleId")
                        zone = person_info.get("zone")

                        if game_role_id and zone:
                            logger.info(
                                f"在排行榜中找到角色: server={server} name={name} role_id={game_role_id} zone={zone}"
                            )

                            kungfu_detail = await asyncio.to_thread(
                                get_kungfu_detail_by_role_info,
                                game_role_id,
                                zone,
                                server,
                                tuilan_request=self.tuilan_request,
                                kungfu_pinyin_to_chinese=self.kungfu_pinyin_to_chinese,
                            )
                            kungfu_name = (kungfu_detail or {}).get("kungfu")

                            if kungfu_name:
                                logger.info(f"心法查询成功: server={server} name={name} kungfu={kungfu_name}")

                            result = {
                                "server": server,
                                "name": name,
                                "cache_time": time.time(),
                                **(kungfu_detail or {}),
                            }
                            result["found"] = result.get("kungfu") is not None

                            self._cache().save_kungfu_cache(server, name, result)
                            if result["found"]:
                                return result

                            logger.info("心法查询失败: 未找到心法信息")
                            break

                logger.info(f"在排行榜中未找到匹配的角色: server={server} name={name}")
            else:
                logger.warning("获取排行榜数据失败，无法进行心法查询")
        except Exception as exc:
            logger.warning(f"心法查询过程中出错: {exc}")

        logger.info("心法查询失败，使用竞技场数据查询作为备选方案")
        logger.info(f"正在查询竞技场数据: server={server} name={name}")
        jjc_data = await self.defget_get(
            url=self.jjc_query_url,
            server=server,
            name=name,
            token=self.token,
            ticket=self.ticket,
        )

        if jjc_data.get("error") or jjc_data.get("msg") != "success":
            logger.warning(f"获取竞技场数据失败: {jjc_data}")
            return {
                "error": True,
                "message": f"获取竞技场数据失败: {jjc_data.get('message', '未知错误')}",
                "server": server,
                "name": name,
            }

        await self.update_kungfu_cache(server, name, jjc_data)

        kungfu_info = None
        history_data = jjc_data.get("data", {}).get("history", [])
        if history_data:
            for match in history_data:
                if match.get("won") is True:
                    kungfu_info = match.get("kungfu")
                    break

        result = {
            "server": server,
            "name": name,
            "kungfu": kungfu_info,
            "found": kungfu_info is not None,
            "cache_time": time.time(),
        }
        cached = self._cache().load_kungfu_cache(server, name)
        if cached:
            cached.update(result)
            result = cached
        self._cache().save_kungfu_cache(server, name, result)
        return result

    async def get_ranking_kungfu_data(self, ranking_data: dict[str, Any]) -> dict[str, Any]:
        try:
            data_list = ranking_data.get("data", [])
            if not data_list:
                return {"error": True, "message": "排行榜数据为空"}

            kungfu_results: list[dict[str, Any]] = []
            ranking_kungfu_lines: list[str] = []
            missing_kungfu_lines: list[str] = []

            total_players = len(data_list)
            logger.info(f"竞技场排行榜总人数: {total_players}")

            for i, player in enumerate(data_list):
                person_info = player.get("personInfo", {})
                server = person_info.get("server", "未知")
                name = person_info.get("roleName", "未知")
                score = self._extract_score(player, person_info)

                if name and "·" in name:
                    name = name.split("·")[0]

                kungfu_info = await self.get_user_kungfu(server, name, ranking_data=ranking_data)
                indicator_kungfu = kungfu_info.get("kungfu_indicator")
                match_history_kungfu = kungfu_info.get("kungfu_match_history")
                if (
                    indicator_kungfu
                    and match_history_kungfu
                    and indicator_kungfu != match_history_kungfu
                ):
                    logger.warning(
                        "心法不一致(排名): rank={} score={} server={} name={} role_id={} global_role_id={} "
                        "indicator={} match_history={} selected={} source={} checked={} win_samples={}",
                        i + 1,
                        score,
                        server,
                        name,
                        kungfu_info.get("role_id"),
                        kungfu_info.get("global_role_id"),
                        indicator_kungfu,
                        match_history_kungfu,
                        kungfu_info.get("kungfu"),
                        kungfu_info.get("kungfu_selected_source"),
                        kungfu_info.get("match_history_checked"),
                        kungfu_info.get("match_history_win_samples"),
                    )
                kungfu_results.append(
                    {
                        "server": server,
                        "name": name,
                        "score": score,
                        "kungfu": kungfu_info.get("kungfu"),
                        "found": kungfu_info.get("found", False),
                    }
                )

                if kungfu_info.get("found") and kungfu_info.get("kungfu"):
                    ranking_kungfu_lines.append(f"{i + 1}. {server} {name} - {kungfu_info['kungfu']}")
                else:
                    missing_kungfu_lines.append(f"{i + 1}. {server} {name}")

            def count_kungfu_by_rank(player_data: list[dict[str, Any]], max_rank: int) -> dict[str, Any]:
                healer_kungfu = self.kungfu_healer_list
                dps_kungfu = self.kungfu_dps_list

                healer_count: dict[str, int] = {}
                dps_count: dict[str, int] = {}

                healer_valid_count = 0
                dps_valid_count = 0
                invalid_count = 0
                invalid_details: list[str] = []

                healer_first_rank: dict[str, int] = {}
                dps_first_rank: dict[str, int] = {}

                overall_min_score = None

                for kungfu in healer_kungfu:
                    healer_count[kungfu] = 0
                for kungfu in dps_kungfu:
                    dps_count[kungfu] = 0

                for player_item in player_data[:max_rank]:
                    score = self._coerce_score(player_item.get("score"))
                    if score is not None and (overall_min_score is None or score < overall_min_score):
                        overall_min_score = score
                if overall_min_score is None:
                    logger.warning(f"前{max_rank}名范围内未找到可用分数字段，最低分将无法展示")

                for i, player_item in enumerate(player_data[:max_rank]):
                    if player_item.get("found") and player_item.get("kungfu"):
                        kungfu = player_item["kungfu"]
                        score = self._coerce_score(player_item.get("score"))

                        if kungfu in healer_kungfu:
                            healer_count[kungfu] = healer_count.get(kungfu, 0) + 1
                            healer_valid_count += 1
                            if kungfu not in healer_first_rank:
                                healer_first_rank[kungfu] = i + 1
                        elif kungfu in dps_kungfu:
                            dps_count[kungfu] = dps_count.get(kungfu, 0) + 1
                            dps_valid_count += 1
                            if kungfu not in dps_first_rank:
                                dps_first_rank[kungfu] = i + 1
                        else:
                            logger.info(
                                f"⚠️ 发现未分类心法：第{i+1}名 {player_item.get('server', '未知')} "
                                f"{player_item.get('name', '未知')} - {kungfu}"
                            )
                    else:
                        invalid_count += 1
                        invalid_details.append(
                            f"第{i+1}名：{player_item.get('server', '未知')} {player_item.get('name', '未知')}"
                        )

                for i, kungfu in enumerate(healer_kungfu):
                    if kungfu not in healer_first_rank:
                        healer_first_rank[kungfu] = 9999 + i
                for i, kungfu in enumerate(dps_kungfu):
                    if kungfu not in dps_first_rank:
                        dps_first_rank[kungfu] = 9999 + i

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
                    logger.info(f"前{max_rank}名中无效数据角色（共{len(invalid_details)}个）")
                    for detail in invalid_details:
                        logger.info(f"invalid: {detail}")

                return {
                    "total_players": max_rank,
                    "healer": {
                        "valid_count": healer_valid_count,
                        "distribution": dict(sorted_healer),
                        "list": sorted_healer,
                        "min_score": overall_min_score,
                    },
                    "dps": {
                        "valid_count": dps_valid_count,
                        "distribution": dict(sorted_dps),
                        "list": sorted_dps,
                        "min_score": overall_min_score,
                    },
                    "total_valid_count": healer_valid_count + dps_valid_count,
                    "invalid_count": invalid_count,
                    "invalid_details": invalid_details,
                    "unclassified_count": max_rank - (healer_valid_count + dps_valid_count + invalid_count),
                }

            logger.info("正在统计kungfu分布")
            kungfu_stats: dict[str, Any] = {}
            if total_players >= 1000:
                logger.info("检测到排行榜包含1000条数据，开始统计前1000心法分布")
                kungfu_stats["top_1000"] = count_kungfu_by_rank(kungfu_results, 1000)
            kungfu_stats["top_200"] = count_kungfu_by_rank(kungfu_results, 200)
            kungfu_stats["top_100"] = count_kungfu_by_rank(kungfu_results, 100)
            kungfu_stats["top_50"] = count_kungfu_by_rank(kungfu_results, 50)

            result: dict[str, Any] = {
                "kungfu_statistics": kungfu_stats,
                "ranking_kungfu_lines": ranking_kungfu_lines,
                "missing_kungfu_lines": missing_kungfu_lines,
            }

            logger.info("=" * 80)
            logger.info("KUNGFU统计结果 (奶妈/DPS分类)")
            logger.info("=" * 80)

            for rank_range, stats in kungfu_stats.items():
                logger.info(
                    f"\n{rank_range.upper()} ({stats['total_players']}人，有效数据{stats['total_valid_count']}人，"
                    f"无效数据{stats['invalid_count']}人):"
                )
                logger.info("=" * 60)

                logger.info(f"奶妈排名（{stats['healer']['valid_count']}人）")
                logger.info("-" * 40)
                if stats["healer"]["list"]:
                    for kungfu, count in stats["healer"]["list"]:
                        percentage = (
                            (count / stats["healer"]["valid_count"] * 100)
                            if stats["healer"]["valid_count"] > 0
                            else 0
                        )
                        logger.info(f"{kungfu}: {count}人 ({percentage:.1f}%)")
                else:
                    logger.info("无奶妈数据")

                logger.info(f"DPS排名（{stats['dps']['valid_count']}人）")
                logger.info("-" * 40)
                if stats["dps"]["list"]:
                    for kungfu, count in stats["dps"]["list"]:
                        percentage = (
                            (count / stats["dps"]["valid_count"] * 100)
                            if stats["dps"]["valid_count"] > 0
                            else 0
                        )
                        logger.info(f"{kungfu}: {count}人 ({percentage:.1f}%)")
                else:
                    logger.info("无DPS数据")

            logger.info("=" * 80)

            return result
        except Exception as exc:
            logger.exception(f"获取心法分布数据失败: {exc}")
            return {"error": True, "message": f"获取心法分布数据失败: {exc}"}

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
                logger.info(f"calculate_season_week_info: defaultWeek={default_week} 生成ISO日期失败，使用当前周")
                target_monday = current_monday

            season_week_from_api = max(
                1, ((target_monday - season_anchor_monday).days // 7) + 1
            )
            weekday_names = ["周1", "周2", "周3", "周4", "周5", "周6", "周7"]
            weekday_str = weekday_names[now.weekday()]
            time_str = now.strftime("%H:%M")

            logger.info(
                f"defaultWeek={default_week} season_anchor_monday={season_anchor_monday} current_monday={current_monday} "
                f"season_week_now={season_week_now} api_week={api_week} target_monday={target_monday} "
                f"weekday_str={weekday_str} time_str={time_str}"
            )
            if target_monday < current_monday:
                return f"第{season_week_from_api}周 结算"

            if target_monday == current_monday:
                return f"第{season_week_now}周 {weekday_str} {time_str}"

            logger.info(f"calculate_season_week_info: defaultWeek={api_week} 指向未来周，锚定赛季周 {season_week_from_api}")
            return f"第{season_week_from_api}周 {weekday_str} {time_str}"

        except Exception as exc:
            logger.warning(f"计算赛季周信息失败: {exc}")
            return f"第{default_week}周"
