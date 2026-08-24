from __future__ import annotations

from typing import Any, Optional

import config as cfg
from jinja2 import Environment, FileSystemLoader

from src.infra.jx3api_get import get
from src.storage.mongo_repos.group_config_repo import GroupConfigRepo
from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService
from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.jjc_match_data_sync import JjcMatchDataSyncService, parse_season_start_timestamp
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo
from src.services.jx3.jjc_cache_repo import JjcCacheRepo
from src.services.jx3.kungfu import get_role_indicator
from src.services.jx3.match_history import MatchHistoryClient, PersonMatchHistoryClient
from src.services.jx3.match_detail import MatchDetailClient
from src.services.jx3.match_detail_identity_projection import MatchDetailIdentityProjectionService
from src.services.jx3.match_replay import MatchReplayClient
from src.services.jx3.role_indicator import RoleIndicatorClient
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo
from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
from src.services.jx3.match_detail_participant_projection import MatchDetailParticipantProjectionService
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

jjc_sync_repo = JjcSyncRepo()
role_identity_repo = RoleIdentityRepo()
match_participant_repo: Any = JjcMatchParticipantRepo()

match_detail_participant_projection_service: Any = MatchDetailParticipantProjectionService(
    participant_repo=match_participant_repo,
    sync_repo=jjc_sync_repo,
    current_season=cfg.CURRENT_SEASON,
    season_start_time=parse_season_start_timestamp(cfg.CURRENT_SEASON_START),
)


def _new_jjc_inspect_repo(snapshot_repo: Optional[JjcMatchSnapshotRepo] = None) -> JjcInspectRepo:
    kwargs: dict[str, Any] = {}
    if snapshot_repo is not None:
        kwargs["snapshot_repo"] = snapshot_repo
    kwargs["participant_repo"] = match_participant_repo
    return JjcInspectRepo(**kwargs)


match_detail_identity_projection_service = MatchDetailIdentityProjectionService(
    identity_repo=role_identity_repo,
    sync_repo=jjc_sync_repo,
    kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
)

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
    match_replay_url=cfg.API_URLS["竞技场战局回放"],
    match_detail_projection_service=match_detail_identity_projection_service,
    match_detail_participant_projection_service=match_detail_participant_projection_service,
)

match_detail_client = MatchDetailClient(
    match_detail_url=cfg.API_URLS["竞技场战局详情"],
    tuilan_request=tuilan_request,
)

match_history_client = MatchHistoryClient(
    match_history_url=cfg.API_URLS["竞技场战局历史"],
    tuilan_request=tuilan_request,
)

person_match_history_client = PersonMatchHistoryClient(
    person_match_history_url=cfg.API_URLS["竞技场个人战局历史"],
    tuilan_request=tuilan_request,
)

match_replay_client = MatchReplayClient(
    match_replay_url=cfg.API_URLS["竞技场战局回放"],
    tuilan_request=tuilan_request,
)

role_indicator_client = RoleIndicatorClient(
    role_indicator_url=cfg.API_URLS["推栏角色指标"],
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
    match_replay_client=match_replay_client,
    cache_repo=_new_jjc_inspect_repo(snapshot_repo=JjcMatchSnapshotRepo()),
    tuilan_request=tuilan_request,
    role_indicator_fetcher=get_role_indicator,
    kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
    match_detail_projection_service=match_detail_identity_projection_service,
    match_detail_participant_projection_service=match_detail_participant_projection_service,
    current_season=cfg.CURRENT_SEASON,
    season_start_time=parse_season_start_timestamp(cfg.CURRENT_SEASON_START),
    role_recent_ttl_seconds=86400,
)

jjc_match_data_sync_service = JjcMatchDataSyncService(
    repo=jjc_sync_repo,
    current_season=cfg.CURRENT_SEASON,
    current_season_start=cfg.CURRENT_SEASON_START,
    match_history_client=match_history_client,
    person_match_history_client=person_match_history_client,
    match_replay_client=match_replay_client,
    role_indicator_client=role_indicator_client,
    inspect_service=jjc_ranking_inspect_service,
    identity_repo=role_identity_repo,
    match_detail_projection_service=match_detail_identity_projection_service,
    match_detail_participant_projection_service=match_detail_participant_projection_service,
    dispatcher_idle_sleep=getattr(cfg, "JJC_SYNC_DISPATCHER_IDLE_SLEEP", 10),
    dispatcher_batch_size=getattr(cfg, "JJC_SYNC_DISPATCHER_BATCH_SIZE", 20),
    dispatcher_target_per_worker=getattr(cfg, "JJC_SYNC_DISPATCHER_TARGET_PER_WORKER", 3),
)
