from __future__ import annotations

import config as cfg
from jinja2 import Environment, FileSystemLoader

from src.infra.jx3api_get import get
from src.storage.mongo_repos.group_config_repo import GroupConfigRepo
from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService
from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.jjc_cache_repo import JjcCacheRepo
from src.services.jx3.kungfu import get_role_indicator
from src.services.jx3.match_history import MatchHistoryClient
from src.services.jx3.match_detail import MatchDetailClient
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo
from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo
from src.utils.tuilan_request import tuilan_request

env = Environment(loader=FileSystemLoader("templates"))
group_config_repo = GroupConfigRepo()

KUNGFU_PINYIN_TO_CHINESE = {key: value["name"] for key, value in cfg.KUNGFU_META.items()}
KUNGFU_HEALER_LIST = [
    value["name"] for value in cfg.KUNGFU_META.values() if value.get("category") == "healer"
]
KUNGFU_DPS_LIST = [value["name"] for value in cfg.KUNGFU_META.values() if value.get("category") == "dps"]

JJC_RANKING_CACHE_DURATION = 7200  # 缓存时间2小时（秒）
KUNGFU_CACHE_DURATION = 7 * 24 * 60 * 60  # 心法缓存有效期一周（秒）

jjc_ranking_service = JjcRankingService(
    token=cfg.TOKEN,
    ticket=cfg.TICKET,
    jjc_query_url=cfg.API_URLS["竞技查询"],
    arena_time_tag_url=cfg.API_URLS["竞技场时间查询"],
    arena_ranking_url=cfg.API_URLS["竞技场排行榜查询"],
    match_detail_url=cfg.API_URLS["竞技场战局详情"],
    jjc_ranking_cache_duration=JJC_RANKING_CACHE_DURATION,
    kungfu_cache_duration=KUNGFU_CACHE_DURATION,
    current_season=cfg.CURRENT_SEASON,
    current_season_start=cfg.CURRENT_SEASON_START,
    kungfu_healer_list=KUNGFU_HEALER_LIST,
    kungfu_dps_list=KUNGFU_DPS_LIST,
    kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
    tuilan_request=tuilan_request,
    defget_get=get,
)

match_detail_client = MatchDetailClient(
    match_detail_url=cfg.API_URLS["竞技场战局详情"],
    tuilan_request=tuilan_request,
)

match_history_client = MatchHistoryClient(
    match_history_url=cfg.API_URLS["竞技场战局历史"],
    tuilan_request=tuilan_request,
)

jjc_ranking_inspect_service = JjcRankingInspectService(
    ranking_service=jjc_ranking_service,
    kungfu_cache_repo=JjcCacheRepo(
        jjc_ranking_cache_duration=JJC_RANKING_CACHE_DURATION,
        kungfu_cache_duration=KUNGFU_CACHE_DURATION,
    ),
    match_history_client=match_history_client,
    match_detail_client=match_detail_client,
    cache_repo=JjcInspectRepo(snapshot_repo=JjcMatchSnapshotRepo()),
    tuilan_request=tuilan_request,
    role_indicator_fetcher=get_role_indicator,
    kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
    role_recent_ttl_seconds=600,
)
