from __future__ import annotations

from typing import Any

import config as cfg
from nonebot import get_driver, on_regex

from src.plugins.jx3bot_handlers.announcements import register as register_announcements
from src.plugins.jx3bot_handlers.baizhan import register as register_baizhan
from src.plugins.jx3bot_handlers.cache_init import register as register_cache_init
from src.plugins.jx3bot_handlers.exam import register as register_exam
from src.plugins.jx3bot_handlers.fraud import register as register_fraud
from src.plugins.jx3bot_handlers.help import register as register_help
from src.plugins.jx3bot_handlers.jjc_ranking import register as register_jjc_ranking
from src.plugins.jx3bot_handlers.lifecycle import register as register_lifecycle
from src.plugins.jx3bot_handlers.mingpian import register as register_mingpian
from src.plugins.jx3bot_handlers.queries import register as register_queries
from src.plugins.jx3bot_handlers.trade import register as register_trade
from src.plugins.jx3bot_handlers.zili import register as register_zili
from src.services.jx3.singletons import (
    env,
    group_config_repo,
    jjc_ranking_service,
)
from src.utils.defget import download_json, fetch_json, get
from src.utils.time_format import format_time_duration

MAX_DEPTH = 2  # 0是顶层，1是第一层子项目，2是第二层子项目，最多显示3层

driver = get_driver()

SERVER_DATA_FILE = "server_data.json"
GROUP_CONFIG_FILE = "groups.json"


def _set_server_data_cache(value: Any) -> None:
    if hasattr(driver, "state"):
        driver.state.jx3_server_data_cache = value
    else:
        setattr(driver, "jx3_server_data_cache", value)


def _set_token_data(value: Any) -> None:
    if hasattr(driver, "state"):
        driver.state.jx3_token_data = value
    else:
        setattr(driver, "jx3_token_data", value)


register_cache_init(
    driver,
    download_json=download_json,
    jiaoyiget=fetch_json,
    token=cfg.TOKEN,
    server_data_file=SERVER_DATA_FILE,
    jjc_ranking_cache_file=jjc_ranking_service.jjc_ranking_cache_file,
    jjc_ranking_cache_duration=jjc_ranking_service.jjc_ranking_cache_duration,
    set_server_data_cache=_set_server_data_cache,
    set_token_data=_set_token_data,
)


yanhua = on_regex(cfg.REGEX_PATTERNS["烟花查询"])
qiyu = on_regex(cfg.REGEX_PATTERNS["奇遇查询"])
zhuangfen = on_regex(cfg.REGEX_PATTERNS["装备查询"])
jjc = on_regex(cfg.REGEX_PATTERNS["竞技查询"])
fuben = on_regex(cfg.REGEX_PATTERNS["副本查询"])
jiayi = on_regex(cfg.REGEX_PATTERNS["交易行查询"])
pianzi = on_regex(cfg.REGEX_PATTERNS["骗子查询"])
keju = on_regex(cfg.REGEX_PATTERNS["科举答题"])
jigai = on_regex(cfg.REGEX_PATTERNS["技改"])
gengxin = on_regex(cfg.REGEX_PATTERNS["更新"])
huodong = on_regex(cfg.REGEX_PATTERNS["活动"])
mingpian = on_regex(cfg.REGEX_PATTERNS["名片查询"])
baizhan = on_regex(cfg.REGEX_PATTERNS["百战查询"])
zili = on_regex(cfg.REGEX_PATTERNS["资历查询"])
zili_choice = on_regex(cfg.REGEX_PATTERNS["资历选择"])
zhanji_ranking = on_regex(cfg.REGEX_PATTERNS["竞技排名"])

BOT_STATUS = {
    "startup_time": 0,
    "last_offline_time": 0,
    "offline_duration": 0,
    "connection_count": 0,
    "last_connect_time": 0,
    "status_file": "log.txt",
}

register_lifecycle(driver, BOT_STATUS)

register_announcements(
    huodong,
    gengxin,
    jigai,
    jiaoyiget=fetch_json,
    skill_records_url=cfg.SKILL_records_URL,
)

help_cmd = on_regex(r"^帮助", priority=5)
register_help(
    help_cmd,
    env,
    group_config_file=GROUP_CONFIG_FILE,
    bot_status=BOT_STATUS,
    load_groups=group_config_repo.load,
    format_time_duration=format_time_duration,
)

register_exam(keju, jiaoyiget=fetch_json)
register_fraud(pianzi, get=get, token=cfg.TOKEN)
register_baizhan(baizhan, env)

register_queries(
    env=env,
    yanhua_matcher=yanhua,
    qiyu_matcher=qiyu,
    zhuangfen_matcher=zhuangfen,
    jjc_matcher=jjc,
    fuben_matcher=fuben,
    update_kuangfu_cache=jjc_ranking_service.update_kuangfu_cache,
)

register_mingpian(mingpian)
register_trade(jiayi, env)
register_zili(zili, zili_choice, env, max_depth=MAX_DEPTH)

register_jjc_ranking(
    zhanji_ranking,
    query_jjc_ranking=jjc_ranking_service.query_jjc_ranking,
    calculate_season_week_info=jjc_ranking_service.calculate_season_week_info,
    get_ranking_kuangfu_data=jjc_ranking_service.get_ranking_kuangfu_data,
    generate_split_ranking_images=jjc_ranking_service.generate_split_ranking_images,
    generate_combined_ranking_image=jjc_ranking_service.generate_combined_ranking_image,
)
