#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剑网3竞技场数据查询脚本
使用与每日定时排名统计一致的逻辑（JjcRankingService）。
"""

import asyncio
import json
import sys
import argparse
import os
import time

from config import TOKEN, TICKET, API_URLS, CURRENT_SEASON, CURRENT_SEASON_START, KUNGFU_META, MONGO_URI
from src.infra.mongo import init_mongo, close_mongo
from src.services.jx3.jjc_ranking import JjcRankingService
from src.utils.tuilan_request import tuilan_request
from src.infra.jx3api_get import get as defget_get

KUNGFU_PINYIN_TO_CHINESE = {key: value["name"] for key, value in KUNGFU_META.items()}
KUNGFU_HEALER_LIST = [
    value["name"] for value in KUNGFU_META.values() if value.get("category") == "healer"
]
KUNGFU_DPS_LIST = [value["name"] for value in KUNGFU_META.values() if value.get("category") == "dps"]

JJC_RANKING_CACHE_DURATION = 7200
KUNGFU_CACHE_DURATION = 7 * 24 * 60 * 60


def _build_ranking_service(token=None, ticket=None):
    return JjcRankingService(
        token=token if token is not None else TOKEN,
        ticket=ticket if ticket is not None else TICKET,
        jjc_query_url=API_URLS["竞技查询"],
        arena_time_tag_url=API_URLS["竞技场时间查询"],
        arena_ranking_url=API_URLS["竞技场排行榜查询"],
        match_detail_url=API_URLS["竞技场战局详情"],
        jjc_ranking_cache_duration=JJC_RANKING_CACHE_DURATION,
        kungfu_cache_duration=KUNGFU_CACHE_DURATION,
        current_season=CURRENT_SEASON,
        current_season_start=CURRENT_SEASON_START,
        kungfu_healer_list=KUNGFU_HEALER_LIST,
        kungfu_dps_list=KUNGFU_DPS_LIST,
        kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
        tuilan_request=tuilan_request,
        defget_get=defget_get,
    )


async def query_ranking(token=None, ticket=None):
    await init_mongo(MONGO_URI)
    service = _build_ranking_service(token=token, ticket=ticket)

    ranking_result = await service.query_jjc_ranking()
    if ranking_result.get("error"):
        print(f"获取排行榜失败: {ranking_result.get('message', '未知错误')}", file=sys.stderr)
        return None

    default_week = ranking_result.get("defaultWeek")
    cache_time = ranking_result.get("cache_time")
    week_info = (
        service.calculate_season_week_info(default_week, cache_time)
        if default_week
        else "第12周"
    )

    print(f"排行榜获取成功，共 {len(ranking_result.get('data', []))} 条数据，{week_info}")

    kungfu_data = await service.get_ranking_kungfu_data(ranking_data=ranking_result)
    if kungfu_data.get("error"):
        print(f"获取心法数据失败: {kungfu_data.get('message', '未知错误')}", file=sys.stderr)
        return None

    stats = kungfu_data.get("kungfu_statistics", {})
    print_kungfu_stats(stats)
    print_ranking_details(kungfu_data)

    service.save_ranking_stats(
        ranking_result=ranking_result,
        stats=stats,
        week_info=week_info,
    )

    await close_mongo()
    return {
        "ranking": ranking_result,
        "kungfu_data": kungfu_data,
    }


async def query_player(server, name, token=None, ticket=None):
    url = API_URLS["竞技查询"]
    print(f"正在查询: 服务器={server}, 角色={name}")
    print(f"请求URL: {url}")
    print("-" * 50)

    data = await defget_get(
        url=url,
        server=server,
        name=name,
        token=token if token is not None else TOKEN,
        ticket=ticket if ticket is not None else TICKET,
    )

    if data.get("error") or data.get("msg") != "success":
        print(f"获取竞技场数据失败: {data}")
        return data

    print(f"查询成功")
    return data


def print_kungfu_stats(stats):
    print("\n" + "=" * 80)
    print("KUNGFU统计结果 (奶妈/DPS分类)")
    print("=" * 80)

    for rank_range, range_stats in stats.items():
        if not isinstance(range_stats, dict):
            continue
        print(f"\n{rank_range.upper()} ({range_stats['total_players']}人，有效数据{range_stats['total_valid_count']}人):")
        print("=" * 60)

        healer = range_stats.get("healer", {})
        dps = range_stats.get("dps", {})

        print(f"\n【奶妈排名】({healer.get('valid_count', 0)}人):")
        print("-" * 40)
        if healer.get("list"):
            for kungfu, count in healer["list"]:
                pct = (count / healer["valid_count"] * 100) if healer["valid_count"] > 0 else 0
                print(f"  {kungfu}: {count}人 ({pct:.1f}%)")
        else:
            print("  无奶妈数据")

        print(f"\n【DPS排名】({dps.get('valid_count', 0)}人):")
        print("-" * 40)
        if dps.get("list"):
            for kungfu, count in dps["list"]:
                pct = (count / dps["valid_count"] * 100) if dps["valid_count"] > 0 else 0
                print(f"  {kungfu}: {count}人 ({pct:.1f}%)")
        else:
            print("  无DPS数据")

    print("=" * 80)


def print_ranking_details(kungfu_data):
    ranking_lines = kungfu_data.get("ranking_kungfu_lines", [])
    missing_lines = kungfu_data.get("missing_kungfu_lines", [])

    print("\n" + "=" * 80)
    print("具体排名和KUNGFU信息")
    print("=" * 80)
    for line in ranking_lines:
        print(line)
    if missing_lines:
        print(f"\n未查询到心法的角色（共{len(missing_lines)}人）:")
        for line in missing_lines:
            print(line)
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description='剑网3竞技场数据查询工具')
    parser.add_argument('--ranking', action='store_true', help='查询竞技场排行榜数据')
    parser.add_argument('server', nargs='?', help='服务器名称 (例如: 梦江南)')
    parser.add_argument('name', nargs='?', help='角色名称')
    parser.add_argument('--token', help='API认证令牌（可选，默认从config文件获取）')
    parser.add_argument('--ticket', help='推栏cookie（可选，默认从config文件获取）')
    parser.add_argument('--pretty', action='store_true', help='格式化输出JSON (美化显示)')
    parser.add_argument('--output', help='输出到文件 (可选)')

    args = parser.parse_args()

    if args.ranking:
        result = asyncio.run(query_ranking(token=args.token, ticket=args.ticket))
        if result is None:
            sys.exit(1)
    else:
        if not args.server or not args.name:
            print("错误: 查询个人数据需要提供服务器名称和角色名称")
            print("用法: python jjc_query.py 服务器名 角色名")
            print("或者: python jjc_query.py --ranking (查询排行榜)")
            sys.exit(1)

        result = asyncio.run(query_player(args.server, args.name, token=args.token, ticket=args.ticket))

    json_str = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)

    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(json_str)
            print(f"结果已保存到文件: {args.output}")
        except Exception as e:
            print(f"保存文件失败: {e}")
            print(json_str)
    else:
        print(json_str)


if __name__ == "__main__":
    main()
