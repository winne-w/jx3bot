from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment, Message, GroupMessageEvent
from nonebot import on_regex, on_command
from typing import Any, Annotated, Dict, Optional
from nonebot.params import RegexGroup, CommandArg, EventPlainText, Matcher
from jinja2 import Environment, FileSystemLoader, Template
from src.utils.defget import get, time_ago_filter, suijitext, jietu, time_ago_fenzhong, timestamp_jjc, jjcdaxiaoxie,convert_number, jiaoyiget, mp_image, sum_specified_keys, get_image, idget, jx3web,download_json
from src.utils.tuilan_request import tuilan_request
import time
import random
import asyncio
import aiohttp
from typing import List, Dict, Any, Tuple
import os
import json

from datetime import datetime, timedelta
from nonebot.plugin import require
from src.utils.shared_data import user_sessions,SEARCH_RESULTS
from src.renderers.jx3.image import (
    apply_filters,
    render_and_send_template_image,
    render_template_image,
    send_image,
    send_text,
)
from src.services.jx3.command_context import (
    fetch_jx3api_or_reply_error,
    resolve_server_and_name,
)
from src.services.jx3.group_binding import load_groups
from src.plugins.jx3bot_handlers.baizhan import register as register_baizhan
from src.plugins.jx3bot_handlers.announcements import register as register_announcements
from src.plugins.jx3bot_handlers.exam import register as register_exam
from src.plugins.jx3bot_handlers.fraud import register as register_fraud
from src.plugins.jx3bot_handlers.cache_init import register as register_cache_init
from src.plugins.jx3bot_handlers.lifecycle import register as register_lifecycle
from src.plugins.jx3bot_handlers.help import register as register_help
from src.plugins.jx3bot_handlers.mingpian import register as register_mingpian
from src.plugins.jx3bot_handlers.queries import register as register_queries
from src.plugins.jx3bot_handlers.trade import register as register_trade
from src.plugins.jx3bot_handlers.zili import register as register_zili
from src.plugins.jx3bot_handlers.jjc_ranking import register as register_jjc_ranking
from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.kungfu import make_kungfu_resolver

# 导入配置文件
from config import TOKEN, TICKET, API_URLS, DEFAULT_SERVER, SESSION_TIMEOUT, REGEX_PATTERNS,NEWS_API_URL,SKILL_records_URL,IMAGE_CACHE_DIR,CURRENT_SEASON,CURRENT_SEASON_START,KUNGFU_META

KUNGFU_PINYIN_TO_CHINESE = {key: value["name"] for key, value in KUNGFU_META.items()}
KUNGFU_HEALER_LIST = [value["name"] for value in KUNGFU_META.values() if value.get("category") == "healer"]
KUNGFU_DPS_LIST = [value["name"] for value in KUNGFU_META.values() if value.get("category") == "dps"]

kf_resolver = make_kungfu_resolver(
    tuilan_request=tuilan_request, kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE
)

# 添加常量控制秘境分布的最大显示层数
MAX_DEPTH = 2  # 0是顶层，1是第一层子项目，2是第二层子项目，最多显示3层

env = Environment(loader=FileSystemLoader('templates'))
token_data = None
# 简单的全局字典用于存储用户会话状态

configid = None
from nonebot import get_driver
# 获取驱动器实例
driver = get_driver()
# 模块级全局变量
server_data_cache = None  # 存储服务器数据的全局缓存
SERVER_DATA_FILE = "server_data.json"  # 文件路径
GROUP_CONFIG_FILE = "groups.json"
# 竞技场排行榜缓存
JJC_RANKING_CACHE_DURATION = 7200  # 缓存时间2小时（秒）
JJC_RANKING_CACHE_FILE = "data/cache/jjc_ranking_cache.json"  # 缓存文件路径
KUNGFU_CACHE_DURATION = 7 * 24 * 60 * 60  # 心法缓存有效期一周（秒）


def _set_server_data_cache(value: Any) -> None:
    global server_data_cache
    server_data_cache = value


def _set_token_data(value: Any) -> None:
    global token_data
    token_data = value


register_cache_init(
    driver,
    download_json=download_json,
    jiaoyiget=jiaoyiget,
    token=TOKEN,
    server_data_file=SERVER_DATA_FILE,
    jjc_ranking_cache_file=JJC_RANKING_CACHE_FILE,
    jjc_ranking_cache_duration=JJC_RANKING_CACHE_DURATION,
    set_server_data_cache=_set_server_data_cache,
    set_token_data=_set_token_data,
)
jjc_ranking_service = JjcRankingService(
    token=TOKEN,
    ticket=TICKET,
    jjc_query_url=API_URLS["竞技查询"],
    arena_time_tag_url=API_URLS["竞技场时间查询"],
    arena_ranking_url=API_URLS["竞技场排行榜查询"],
    jjc_ranking_cache_file=JJC_RANKING_CACHE_FILE,
    jjc_ranking_cache_duration=JJC_RANKING_CACHE_DURATION,
    kungfu_cache_duration=KUNGFU_CACHE_DURATION,
    current_season=CURRENT_SEASON,
    current_season_start=CURRENT_SEASON_START,
    kungfu_healer_list=KUNGFU_HEALER_LIST,
    kungfu_dps_list=KUNGFU_DPS_LIST,
    kungfu_pinyin_to_chinese=KUNGFU_PINYIN_TO_CHINESE,
    tuilan_request=tuilan_request,
    defget_get=get,
    get_kungfu_by_role_info=kf_resolver,
    env=env,
    render_template_image=render_template_image,
)


# 兼容导出：供 src/plugins/status_monitor.py 等旧代码直接 import 使用
async def query_jjc_ranking() -> dict[str, Any]:
    return await jjc_ranking_service.query_jjc_ranking()


async def get_ranking_kuangfu_data(*, ranking_data: dict[str, Any]) -> dict[str, Any]:
    return await jjc_ranking_service.get_ranking_kuangfu_data(ranking_data)


def calculate_season_week_info(default_week: int, cache_time: Optional[float] = None) -> str:
    return jjc_ranking_service.calculate_season_week_info(default_week, cache_time)


async def render_combined_ranking_image(stats: dict[str, Any], week_info: str) -> dict[str, Any]:
    return await jjc_ranking_service.render_combined_ranking_image(stats, week_info)
# 使用配置文件中的正则表达式创建命令处理器
yanhua = on_regex(REGEX_PATTERNS["烟花查询"])
qiyu = on_regex(REGEX_PATTERNS["奇遇查询"])
zhuangfen = on_regex(REGEX_PATTERNS["装备查询"])
jjc = on_regex(REGEX_PATTERNS["竞技查询"])
fuben = on_regex(REGEX_PATTERNS["副本查询"])
jiayi = on_regex(REGEX_PATTERNS["交易行查询"])
pianzi = on_regex(REGEX_PATTERNS["骗子查询"])
keju = on_regex(REGEX_PATTERNS["科举答题"])
jigai = on_regex(REGEX_PATTERNS["技改"])
gengxin = on_regex(REGEX_PATTERNS["更新"])
huodong = on_regex(REGEX_PATTERNS["活动"])
mingpian = on_regex(REGEX_PATTERNS["名片查询"])
baizhan = on_regex(REGEX_PATTERNS["百战查询"])
zili = on_regex(REGEX_PATTERNS["资历查询"])
zili_choice = on_regex(REGEX_PATTERNS["资历选择"])
zhanji_ranking = on_regex(REGEX_PATTERNS["竞技排名"])

# 全局变量，记录机器人状态
BOT_STATUS = {
    "startup_time": 0,  # 启动时间
    "last_offline_time": 0,  # 上次离线时间
    "offline_duration": 0,  # 上次离线持续时间
    "connection_count": 0,  # 连接次数
    "last_connect_time": 0,  # 上次连接时间
    "status_file": "log.txt"  # 状态文件路径
}

register_lifecycle(driver, BOT_STATUS)


# 格式化时间段为可读形式
# 格式化时间段为可读形式
def format_time_duration(seconds):
    """将秒数转换为可读的时间格式 (天, 小时, 分钟, 秒)"""
    if seconds < 0:
        return "0秒"

    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}秒")

    return "".join(parts)

 
register_announcements(
    huodong,
    gengxin,
    jigai,
    jiaoyiget=jiaoyiget,
    skill_records_url=SKILL_records_URL,
)









# 查看帮助命令
help_cmd = on_regex(r"^帮助", priority=5)
register_help(
    help_cmd,
    env,
    group_config_file=GROUP_CONFIG_FILE,
    bot_status=BOT_STATUS,
    load_groups=load_groups,
    format_time_duration=format_time_duration,
)













register_exam(keju, jiaoyiget=jiaoyiget)

register_fraud(pianzi, get=get, token=TOKEN)

register_baizhan(baizhan, env)

register_queries(
    env=env,
    yanhua_matcher=yanhua,
    qiyu_matcher=qiyu,
    zhuangfen_matcher=zhuangfen,
    jjc_matcher=jjc,
    fuben_matcher=fuben,
    update_kuangfu_cache=lambda server, name, data: jjc_ranking_service.update_kuangfu_cache(
        server, name, data
    ),
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
