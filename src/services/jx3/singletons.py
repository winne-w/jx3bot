from __future__ import annotations

import config as cfg
from jinja2 import Environment, FileSystemLoader

from src.infra.jx3api_get import get
from src.services.jx3.group_config_repo import GroupConfigRepo
from src.services.jx3.jjc_ranking import JjcRankingService
from src.utils.tuilan_request import tuilan_request

env = Environment(loader=FileSystemLoader("templates"))
group_config_repo = GroupConfigRepo(path="groups.json")

KUNGFU_PINYIN_TO_CHINESE = {key: value["name"] for key, value in cfg.KUNGFU_META.items()}
KUNGFU_HEALER_LIST = [
    value["name"] for value in cfg.KUNGFU_META.values() if value.get("category") == "healer"
]
KUNGFU_DPS_LIST = [value["name"] for value in cfg.KUNGFU_META.values() if value.get("category") == "dps"]

JJC_RANKING_CACHE_DURATION = 7200  # 缓存时间2小时（秒）
JJC_RANKING_CACHE_FILE = "data/cache/jjc_ranking_cache.json"
KUNGFU_CACHE_DURATION = 7 * 24 * 60 * 60  # 心法缓存有效期一周（秒）

jjc_ranking_service = JjcRankingService(
    token=cfg.TOKEN,
    ticket=cfg.TICKET,
    jjc_query_url=cfg.API_URLS["竞技查询"],
    arena_time_tag_url=cfg.API_URLS["竞技场时间查询"],
    arena_ranking_url=cfg.API_URLS["竞技场排行榜查询"],
    jjc_ranking_cache_file=JJC_RANKING_CACHE_FILE,
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
