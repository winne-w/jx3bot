#!/usr/bin/env python3
"""命令行工具：单独同步某个角色的竞技场对局数据。

用法:
    python sync_single_jjc.py <服务器> <角色名> [--global_role_id=...] [--role_id=...] [--zone=...] [--force]

示例:
    python sync_single_jjc.py 梦江南 某角色名
    python sync_single_jjc.py 电信一区 某角色名 --global_role_id=abc123 --zone=zone1
    python sync_single_jjc.py 梦江南 某角色名 --force
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# 确保能从项目根目录导入 config 和 src.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 日志配置 ----
class _BraceFallbackFormatter(logging.Formatter):
    """兼容 nonebot.logger 的 {} 格式化 fallback。"""
    def format(self, record):
        if record.args and '{}' in str(record.msg):
            try:
                record.msg = str(record.msg).format(*record.args)
                record.args = ()
            except (ValueError, TypeError, KeyError, IndexError):
                pass
        return super().format(record)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_single_jjc")


def _fix_root_handlers():
    """将所有 root logger handler 替换为兼容 {} 格式化的 formatter。"""
    for handler in logging.getLogger().handlers:
        if not isinstance(handler.formatter, _BraceFallbackFormatter):
            handler.setFormatter(_BraceFallbackFormatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))


# ---- 配置 ----
import config as cfg  # noqa: E402
from src.infra.mongo import init_mongo  # noqa: E402

# ---- 复用 singletons.py 的装配逻辑 ----
from src.infra.jx3api_get import get  # noqa: E402
from src.services.jx3.jjc_ranking import JjcRankingService  # noqa: E402
from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService  # noqa: E402
from src.services.jx3.jjc_match_data_sync import JjcMatchDataSyncService  # noqa: E402
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo  # noqa: E402
from src.services.jx3.jjc_cache_repo import JjcCacheRepo  # noqa: E402
from src.services.jx3.kungfu import get_role_indicator  # noqa: E402
from src.services.jx3.match_history import MatchHistoryClient, PersonMatchHistoryClient  # noqa: E402
from src.services.jx3.match_detail import MatchDetailClient  # noqa: E402
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo  # noqa: E402
from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo  # noqa: E402
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo  # noqa: E402
from src.utils.tuilan_request import tuilan_request  # noqa: E402


def build_ranking_service() -> JjcRankingService:
    KUNGFU_PINYIN_TO_CHINESE = {key: value["name"] for key, value in cfg.KUNGFU_META.items()}
    KUNGFU_HEALER_LIST = [
        value["name"] for value in cfg.KUNGFU_META.values() if value.get("category") == "healer"
    ]
    KUNGFU_DPS_LIST = [
        value["name"] for value in cfg.KUNGFU_META.values() if value.get("category") == "dps"
    ]
    return JjcRankingService(
        token=cfg.TOKEN,
        ticket=cfg.TICKET,
        jjc_query_url=cfg.API_URLS["竞技查询"],
        arena_time_tag_url=cfg.API_URLS["竞技场时间查询"],
        arena_ranking_url=cfg.API_URLS["竞技场排行榜查询"],
        match_detail_url=cfg.API_URLS["竞技场战局详情"],
        jjc_ranking_cache_duration=7200,
        kungfu_cache_duration=7 * 24 * 60 * 60,
        current_season=cfg.CURRENT_SEASON,
        current_season_start=cfg.CURRENT_SEASON_START,
        kungfu_healer_list=KUNGFU_HEALER_LIST,
        kungfu_dps_list=KUNGFU_DPS_LIST,
        kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
        tuilan_request=tuilan_request,
        defget_get=get,
    )


def build_inspect_service(ranking_service: JjcRankingService) -> JjcRankingInspectService:
    KUNGFU_PINYIN_TO_CHINESE = {key: value["name"] for key, value in cfg.KUNGFU_META.items()}
    return JjcRankingInspectService(
        ranking_service=ranking_service,
        kungfu_cache_repo=JjcCacheRepo(
            jjc_ranking_cache_duration=7200,
            kungfu_cache_duration=7 * 24 * 60 * 60,
        ),
        match_history_client=MatchHistoryClient(
            match_history_url=cfg.API_URLS["竞技场战局历史"],
            tuilan_request=tuilan_request,
        ),
        match_detail_client=MatchDetailClient(
            match_detail_url=cfg.API_URLS["竞技场战局详情"],
            tuilan_request=tuilan_request,
        ),
        cache_repo=JjcInspectRepo(snapshot_repo=JjcMatchSnapshotRepo()),
        tuilan_request=tuilan_request,
        role_indicator_fetcher=get_role_indicator,
        kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
        role_recent_ttl_seconds=600,
    )


def build_sync_service(inspect_service: JjcRankingInspectService) -> JjcMatchDataSyncService:
    return JjcMatchDataSyncService(
        repo=JjcSyncRepo(),
        current_season=cfg.CURRENT_SEASON,
        current_season_start=cfg.CURRENT_SEASON_START,
        match_history_client=MatchHistoryClient(
            match_history_url=cfg.API_URLS["竞技场战局历史"],
            tuilan_request=tuilan_request,
        ),
        person_match_history_client=PersonMatchHistoryClient(
            person_match_history_url=cfg.API_URLS["竞技场个人战局历史"],
            tuilan_request=tuilan_request,
        ),
        inspect_service=inspect_service,
        identity_repo=RoleIdentityRepo(),
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="单独同步某个角色的 JJC 对局数据")
    parser.add_argument("server", help="服务器名称")
    parser.add_argument("name", help="角色名")
    parser.add_argument("--global_role_id", default=None, help="全局角色 ID")
    parser.add_argument("--role_id", default=None, help="角色 ID")
    parser.add_argument("--zone", default=None, help="区服 zone")
    parser.add_argument("--force", action="store_true", help="强制同步，跳过冷却限制")
    args = parser.parse_args()

    _fix_root_handlers()
    logger.info("初始化 MongoDB: %s", cfg.MONGO_URI)
    await init_mongo(cfg.MONGO_URI)

    logger.info("构建服务依赖...")
    ranking_service = build_ranking_service()
    inspect_service = build_inspect_service(ranking_service)
    sync_service = build_sync_service(inspect_service)

    if args.force:
        reset_result = await sync_service.reset_role(server=args.server, name=args.name)
        if reset_result.get("error"):
            logger.warning("强制重置失败（可能角色不存在）: %s", reset_result.get("message"))
        else:
            logger.info("已重置角色冷却状态")

    logger.info("开始同步: server=%s name=%s", args.server, args.name)
    result = await sync_service.sync_single_role(
        server=args.server,
        name=args.name,
        global_role_id=args.global_role_id,
        role_id=args.role_id,
        zone=args.zone,
    )

    if result.get("error"):
        logger.error("同步失败: %s", result.get("message", "unknown_error"))
        sys.exit(1)

    logger.info("同步完成")
    print(f"角色: {args.server}/{args.name}")
    print(f"发现对局: {result.get('discovered_matches', 0)}")
    print(f"保存详情: {result.get('saved_details', 0)}")
    print(f"跳过详情: {result.get('skipped_details', 0)}")
    print(f"详情失败: {result.get('failed_details', 0)}")
    print(f"详情不可用: {result.get('unavailable_details', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
