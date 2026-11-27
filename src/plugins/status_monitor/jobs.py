from src.infra.group_delivery import send_group_msg
import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import config as cfg
import httpx
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_apscheduler import scheduler

from src.services.jx3.jjc_peak_score_ranking import JjcPeakScoreRankingService
from src.services.jx3.singletons import jjc_ranking_service
from src.services.jx3.singletons import group_config_repo
from src.services.jx3.singletons import env
from src.renderers.jx3.image import render_template_image
from src.renderers.jx3.jjc_ranking import render_combined_ranking_image

from .notify import get_NapCat_data, send_email_via_163
from .storage import CacheManager, load_id_set, save_id_set
from src.infra.jx3api_compat import normalize_jx3api_response
from src.services.jx3.server_status import server_status_items

try:
    from config import (
        NEWS_API_URL,
        NEWS_records_time,
        SKILL_records_URL,
        STATUS_check_API,
        STATUS_check_time,
        calendar_URL,
        calendar_time,
        jx3box_URL,
    )
except Exception:
    NEWS_records_time = 30
    STATUS_check_time = 3
    calendar_time = 9
    STATUS_check_API = ""
    NEWS_API_URL = ""
    SKILL_records_URL = ""
    calendar_URL = ""
    jx3box_URL = ""


def _resolve_daily_gte_hour(value: Any, default: int = 9) -> int:
    if isinstance(value, (bool, float)):
        logger.warning("status_monitor 非法 calendar_time 配置 {!r}，回退默认值 {}", value, default)
        return default
    try:
        hour = int(value)
    except (TypeError, ValueError):
        logger.warning("status_monitor 非法 calendar_time 配置 {!r}，回退默认值 {}", value, default)
        return default
    if 0 <= hour <= 23:
        return hour
    logger.warning("status_monitor calendar_time 超出 0-23 范围 ({!r})，回退默认值 {}", value, default)
    return default


_DAILY_GTE_HOUR = _resolve_daily_gte_hour(calendar_time)


BOT_INITIALIZED = False
previous_status = {}
previous_news_ids = set()
previous_records_ids = set()
previous_codes_ids = set()
last_status_ok = True
_napcat_monitor_started_at = time.monotonic()
_napcat_consecutive_failures = 0
_napcat_offline_alert_sent = False
jjc_peak_score_ranking_service = JjcPeakScoreRankingService()


def set_bot_initialized(value: bool) -> None:
    global BOT_INITIALIZED
    BOT_INITIALIZED = value


def reset_napcat_monitor_start() -> None:
    global _napcat_monitor_started_at
    _napcat_monitor_started_at = time.monotonic()


def _get_admin_qq_list() -> List[int]:
    raw_admins = getattr(cfg, "ADMIN_QQ", None)
    if raw_admins is None:
        return []
    if isinstance(raw_admins, (int, str)):
        candidates = [raw_admins]
    else:
        try:
            candidates = list(raw_admins)
        except TypeError:
            logger.warning("status_monitor ADMIN_QQ 配置不可迭代: {!r}", raw_admins)
            return []

    admins: List[int] = []
    seen = set()
    for item in candidates:
        try:
            qq = int(str(item).strip())
        except (TypeError, ValueError):
            logger.warning("status_monitor 忽略非法 ADMIN_QQ 配置项: {!r}", item)
            continue
        if qq not in seen:
            seen.add(qq)
            admins.append(qq)
    return admins


async def notify_jjc_ranking_failure(bot, detail: str) -> None:
    message = f"竞技排名定时任务统计失败：{detail}"
    if bot is None:
        bot = next(iter(get_driver().bots.values()), None)
    if bot is None:
        logger.warning("status_monitor QQ 未连接，无法私聊管理员: {}", message)
        return
    admin_qqs = _get_admin_qq_list()
    if not admin_qqs:
        logger.warning("status_monitor 未配置有效 ADMIN_QQ，无法私聊管理员: {}", message)
        return
    for admin_qq in admin_qqs:
        try:
            await bot.send_private_msg(user_id=admin_qq, message=message)
        except Exception as exc:
            logger.warning(
                "status_monitor 通知竞技排名统计失败给管理员{}时出错: {}",
                admin_qq,
                exc,
            )


async def notify_jjc_ranking_missing_kungfu(
    bot, missing_kungfu_lines, week_info: Optional[str] = None
) -> None:
    if not missing_kungfu_lines:
        return
    if bot is None:
        bot = next(iter(get_driver().bots.values()), None)
    if bot is None:
        logger.warning("status_monitor QQ 未连接，无法私聊管理员未查询到心法的角色")
        return

    admin_qqs = _get_admin_qq_list()
    if not admin_qqs:
        logger.warning(
            "status_monitor 未配置有效 ADMIN_QQ，无法私聊未查询到心法的角色（共{}人）",
            len(missing_kungfu_lines),
        )
        return

    prefix = f"【每日竞技排名定时任务（{week_info}）】" if week_info else "【每日竞技排名定时任务】"
    chunk_size = 100
    total_lines = len(missing_kungfu_lines)
    chunks: List[str] = []
    for start in range(0, total_lines, chunk_size):
        end = min(start + chunk_size, total_lines)
        chunk_header = f"{prefix}未查询到心法的角色（共{total_lines}人，第{start + 1}-{end}名）"
        chunk_message = "\n".join(missing_kungfu_lines[start:end])
        chunks.append(f"{chunk_header}\n{chunk_message}")

    total_admins = len(admin_qqs)
    total_chunks = len(chunks)
    for admin_idx, admin_qq in enumerate(admin_qqs):
        for chunk_idx, chunk in enumerate(chunks, start=1):
            try:
                await bot.send_private_msg(user_id=admin_qq, message=chunk)
            except Exception as exc:
                logger.warning(
                    "status_monitor 通知未查询到心法的角色给管理员{}（第{}/{}片）时出错: {}",
                    admin_qq,
                    chunk_idx,
                    total_chunks,
                    exc,
                )
                break
            has_more_chunks = chunk_idx < total_chunks
            has_more_admins = admin_idx + 1 < total_admins
            if has_more_chunks or has_more_admins:
                await asyncio.sleep(0.5)


def log_startup() -> None:
    logger.info("status_monitor 开服监控已启动，API: {} 延时{}分钟", STATUS_check_API, STATUS_check_time)
    logger.info("status_monitor 新闻监控已启动，API: {} 延时{}分钟", NEWS_API_URL, NEWS_records_time)
    logger.info("status_monitor 技改监控已启动，API: {} 延时{}分钟", SKILL_records_URL, NEWS_records_time)
    logger.info("status_monitor 日常监控已启动，每天{}点推送", _DAILY_GTE_HOUR)


def format_time(timestamp):
    t = time.localtime(timestamp)
    month = t.tm_mon
    day = t.tm_mday
    hour = t.tm_hour
    minute = t.tm_min
    second = t.tm_sec
    return f"{month}月{day}日 {hour:02d}:{minute:02d}:{second:02d}"


def extract_version(json_data):
    try:
        if not json_data:
            return "未知"

        data = json_data if isinstance(json_data, dict) else json.loads(json_data)

        if "data" in data and len(data["data"]) > 0:
            first_item = data["data"][0]
            title = first_item.get("title", "")

            version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", title)
            if version_match:
                return version_match.group(1)

        return "未知"
    except Exception as e:
        logger.warning("status_monitor 提取版本号失败: {}", e)
        return "未知"


def format_gte_message(gte_data):
    if not gte_data or "data" not in gte_data:
        return "获取每日GTE数据失败"

    data = gte_data["data"]

    date_str = data.get("date", "")
    week_str = data.get("week", "")

    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            date_str = f"{date_obj.year}年{date_obj.month}月{date_obj.day}日"
        except Exception:
            pass

    message = [f"当前时间：{date_str} 星期{week_str}"]
    message.append(f"秘境大战：{data.get('war', '无')}")
    message.append(f"战场任务：{data.get('battle', '无')}")
    message.append(f"宗门事件：{data.get('school', '无')}")
    message.append(f"驰援任务：{data.get('rescue', '无')}")
    message.append(f"阵营任务：{data.get('orecar', '无')}")
    message.append("帮会跑商：阴山商路(10:00)")

    luck_pets = ";".join(data.get("luck", []))
    message.append(f"福源宠物：{luck_pets}")

    if "draw" in data:
        message.append(f"美人图：{data.get('draw', '无')}")

    message.append("")
    message.append("家园声望·加倍道具")
    card_items = ";".join(data.get("card", []))
    message.append(card_items)

    if "team" in data and len(data["team"]) >= 3:
        message.append("武林通鉴·公共任务")
        message.append(data["team"][0])
        message.append("武林通鉴·秘境任务")
        message.append(data["team"][1])
        message.append("武林通鉴·团队秘境")
        message.append(data["team"][2])

    return "\n".join(message)


async def get_gte_data(url, server):
    try:
        url = f"{url}?server={server}"
        logger.debug("status_monitor 请求日常: {}", url)
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(url)
            if response.status_code != 200:
                logger.warning("status_monitor 日常API返回错误: {}", response.status_code)
                return None
            return normalize_jx3api_response(url, response.json())
    except Exception as e:
        logger.warning("status_monitor 请求日常API失败: {}", e)
        return None


async def get_server_status():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(STATUS_check_API)
            if response.status_code != 200:
                logger.warning("status_monitor 开服监测API返回错误: {}", response.status_code)
                return None
            return normalize_jx3api_response(STATUS_check_API, response.json())
    except Exception as e:
        logger.warning("status_monitor 开服监测请求失败: {}", e)
        return None


async def get_server_banben():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get("https://www.jx3api.com/news/announce")
            if response.status_code != 200:
                logger.warning("status_monitor 公告API返回错误: {}", response.status_code)
                return None
            return normalize_jx3api_response("https://www.jx3api.com/news/announce", response.json())
    except Exception as e:
        logger.warning("status_monitor 公告请求失败: {}", e)
        return None


async def get_news_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(NEWS_API_URL)
            if response.status_code != 200:
                logger.warning("status_monitor 新闻API返回错误: {}", response.status_code)
                return None
            return normalize_jx3api_response(NEWS_API_URL, response.json())
    except Exception as e:
        logger.warning("status_monitor 请求新闻API失败: {}", e)
        return None


async def get_records_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(SKILL_records_URL)
            if response.status_code != 200:
                logger.warning("status_monitor 技改API返回错误: {}", response.status_code)
                return None
            return normalize_jx3api_response(SKILL_records_URL, response.json())
    except Exception as e:
        logger.warning("status_monitor 请求技改API失败: {}", e)
        return None


async def get_jx3box_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(jx3box_URL)
            if response.status_code != 200:
                logger.warning("status_monitor 福利API返回错误: {}", response.status_code)
                return None
            return response.json()
    except Exception as e:
        logger.warning("status_monitor 请求福利API失败: {}", e)
        return None


def _is_onebot_status_healthy(payload: object) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, f"get_status 返回非字典: {payload!r}"

    # 兼容 OneBot V11 原始响应 {"status": "ok", "data": {"online": true, "good": true}}
    # 以及 NoneBot bot.get_status() 已解包的 {"online": true, "good": true}
    if "data" in payload and isinstance(payload.get("data"), dict):
        outer_status = str(payload.get("status", "ok")).lower()
        if outer_status != "ok":
            return False, f"status={outer_status}"
        inner = payload["data"]
    else:
        inner = payload

    online = inner.get("online")
    good = inner.get("good")
    if online is False or good is False:
        return False, f"online={online}, good={good}"
    if online is True and (good is True or good is None):
        return True, f"online={online}, good={good}"
    if good is True and online is None:
        return True, f"online={online}, good={good}"
    return False, f"状态字段异常: {json.dumps(inner, ensure_ascii=False)}"


async def check_napcat_connection_status() -> tuple[bool, str, str]:
    """基于 NoneBot 反向 WebSocket 连接与 bot.get_status() 检测 NapCat / QQ 在线状态。"""
    driver = get_driver()
    bots = getattr(driver, "bots", None) or {}
    if not bots:
        return False, "reverse_ws_disconnected", "未检测到已连接的 NapCat 机器人（反向 WebSocket 已断开或尚未连接）"

    bot_items = list(bots.items())
    for bot_id, bot in bot_items:
        get_status = getattr(bot, "get_status", None)
        if not callable(get_status):
            continue
        try:
            raw_status = await asyncio.wait_for(get_status(), timeout=10.0)
        except Exception as exc:
            return False, "get_status_failed", f"Bot {bot_id} get_status 探测失败: {exc!r}"

        healthy, detail = _is_onebot_status_healthy(raw_status)
        if not healthy:
            return False, "qq_offline", f"Bot {bot_id} QQ 掉线或状态异常（{detail}）"

    bot_ids = ", ".join(str(bid) for bid, _ in bot_items)
    return True, "ok", f"Bot {bot_ids} 在线正常"


async def _send_status_email(content: str) -> bool:
    return await asyncio.to_thread(send_email_via_163, content)


@scheduler.scheduled_job("interval", seconds=60, max_instances=1)
async def mail_records():
    global last_status_ok, _napcat_consecutive_failures, _napcat_offline_alert_sent

    current_status_ok, reason_code, status_info = await check_napcat_connection_status()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    grace_seconds = max(0, int(getattr(cfg, "STATUS_MONITOR_OFFLINE_GRACE_SECONDS", 90) or 0))
    fail_threshold = max(1, int(getattr(cfg, "STATUS_MONITOR_OFFLINE_FAIL_THRESHOLD", 2) or 1))

    if current_status_ok:
        _napcat_consecutive_failures = 0
        if _napcat_offline_alert_sent:
            recovery_content = (
                f"NapCat / QQ 状态已恢复正常！\n\n"
                f"恢复时间：{now_str}\n"
                f"当前状态：{status_info}"
            )
            send_result = await _send_status_email(recovery_content)
            if send_result:
                logger.info("status_monitor 恢复邮件发送成功")
                _napcat_offline_alert_sent = False
            else:
                logger.warning("status_monitor 恢复邮件发送失败")
        last_status_ok = True
        return

    # 启动宽限期内（Bot 尚未完成首次连接）不触发离线邮件，避免重启误报
    elapsed_since_start = time.monotonic() - _napcat_monitor_started_at
    if not BOT_INITIALIZED and not _napcat_offline_alert_sent and elapsed_since_start < grace_seconds:
        logger.info(
            "status_monitor 启动宽限期内等待 NapCat 连接 ({:.0f}s/{}s): {}",
            elapsed_since_start,
            grace_seconds,
            status_info,
        )
        return

    _napcat_consecutive_failures += 1
    last_status_ok = False
    logger.warning(
        "status_monitor 检测到 NapCat 状态异常 ({}/{}): reason={} detail={}",
        _napcat_consecutive_failures,
        fail_threshold,
        reason_code,
        status_info,
    )

    if _napcat_consecutive_failures >= fail_threshold and not _napcat_offline_alert_sent:
        email_content = (
            f"NapCat / QQ 掉线告警！\n\n"
            f"检测时间：{now_str}\n"
            f"异常类型：{reason_code}\n"
            f"连续失败次数：{_napcat_consecutive_failures}\n"
            f"当前状态信息：{status_info}"
        )
        send_result = await _send_status_email(email_content)
        if send_result:
            _napcat_offline_alert_sent = True
            logger.info("status_monitor 掉线告警邮件发送成功")
        else:
            logger.warning("status_monitor 掉线告警邮件发送失败")


@scheduler.scheduled_job("interval", minutes=NEWS_records_time, max_instances=1)
async def check_records():
    if BOT_INITIALIZED:
        global previous_records_ids
        try:
            if not previous_records_ids:
                previous_records_ids = await load_id_set("records_ids")
                if not previous_records_ids:
                    logger.info("status_monitor 没有发现技改缓存或缓存为空")
                else:
                    logger.info("status_monitor 从缓存加载了{}条技改ID", len(previous_records_ids))

            data = await get_records_data()
            if not data or data.get("error") or "data" not in data:
                logger.warning("status_monitor 获取技改数据失败")
                return

            current_records = data["data"]
            current_records_ids = {str(record.get("id", "")) for record in current_records}

            if not previous_records_ids:
                previous_records_ids = current_records_ids
                await save_id_set(previous_records_ids, "records_ids")
                logger.info("status_monitor 首次运行，已记录{}条技改ID", len(current_records_ids))
                return

            new_records_ids = current_records_ids - previous_records_ids
            if new_records_ids:
                logger.info("status_monitor 检测到{}条新增技改", len(new_records_ids))

                bots = get_driver().bots
                if not bots:
                    logger.warning(
                        "status_monitor QQ 未连接，暂缓推进技改缓存，等待重连后补推{}条新增技改",
                        len(new_records_ids),
                    )
                    return

                new_records = [
                    record
                    for record in current_records
                    if str(record.get("id", "")) in new_records_ids
                ]

                bot = list(bots.values())[0]
                groups_config = await group_config_repo.load()

                for gid, config in groups_config.items():
                    try:
                        if not isinstance(config, dict) or config.get("技改推送", False) is False:
                            continue

                        for record in new_records:
                            record_class = "官方公告"
                            title = record.get("title", "无标题")
                            url = record.get("url", "")
                            date = format_time(record.get("time", 0))

                            message = (
                                f"{record_class}\n"
                                f"标题：{title}\n"
                                f"链接：{url}\n"
                                f"日期：{date}"
                            )

                            await send_group_msg(bot, group_id=int(gid), message=message)
                            logger.info("status_monitor 向群{}推送技改: {}", gid, title)
                    except Exception as e:
                        logger.warning("status_monitor 向群{}推送技改失败: {}", gid, e)

            previous_records_ids = current_records_ids
            await save_id_set(previous_records_ids, "records_ids")
        except Exception as e:
            logger.warning("status_monitor 检查技改出错: {}", e)


@scheduler.scheduled_job("interval", minutes=NEWS_records_time, max_instances=1)
async def check_news():
    if BOT_INITIALIZED:
        global previous_news_ids
        try:
            if not previous_news_ids:
                previous_news_ids = {str(value) for value in await load_id_set("news_ids")}
                if not previous_news_ids:
                    logger.info("status_monitor 没有发现新闻缓存或缓存为空")
                else:
                    logger.info("status_monitor 从缓存加载了{}条新闻ID", len(previous_news_ids))

            data = await get_news_data()
            if not data or data.get("error") or "data" not in data:
                logger.warning("status_monitor 获取新闻数据失败")
                return

            current_news = data["data"]
            current_news = [
                item
                for item in current_news
                if "武学" not in item.get("title", "")
                and "版本" not in item.get("title", "")
                and "维护" not in item.get("title", "")
            ]
            current_news_ids = {str(news["id"]) for news in current_news}

            if not previous_news_ids:
                previous_news_ids = current_news_ids
                await save_id_set(previous_news_ids, "news_ids")
                logger.info("status_monitor 首次运行，已记录{}条新闻ID", len(current_news_ids))
                return

            new_news_ids = current_news_ids - previous_news_ids
            if new_news_ids:
                logger.info("status_monitor 检测到{}条新增新闻", len(new_news_ids))

                bots = get_driver().bots
                if not bots:
                    logger.warning(
                        "status_monitor QQ 未连接，暂缓推进新闻缓存，等待重连后补推{}条新增新闻",
                        len(new_news_ids),
                    )
                    return

                new_news = [news for news in current_news if str(news["id"]) in new_news_ids]

                bot = list(bots.values())[0]
                groups_config = await group_config_repo.load()

                for gid, config in groups_config.items():
                    try:
                        if not isinstance(config, dict) or config.get("新闻推送", False) is False:
                            continue

                        for news in new_news:
                            news_class = news.get("type", "公告")
                            title = news.get("title", "无标题")
                            url = news.get("url", "")
                            date = news.get("date", "")

                            message = (
                                f"{news_class}\n"
                                f"标题：{title}\n"
                                f"链接：{url}\n"
                                f"日期：{date}"
                            )

                            await send_group_msg(bot, group_id=int(gid), message=message)
                            logger.info("status_monitor 向群{}推送新闻: {}", gid, title)
                    except Exception as e:
                        logger.warning("status_monitor 向群{}推送新闻失败: {}", gid, e)

            previous_news_ids = current_news_ids
            await save_id_set(previous_news_ids, "news_ids")
        except Exception as e:
            logger.warning("status_monitor 检查新闻出错: {}", e)


@scheduler.scheduled_job("interval", minutes=200, max_instances=1)
async def check_event_codes():
    if BOT_INITIALIZED:
        global previous_codes_ids
        current_codes_ids = set()

        try:
            if not previous_codes_ids:
                previous_codes_ids = await load_id_set("event_codes_ids")
                if not previous_codes_ids:
                    logger.info("status_monitor 没有发现活动码缓存或缓存为空")
                else:
                    logger.info("status_monitor 从缓存加载了{}条活动码ID", len(previous_codes_ids))

            response = await get_jx3box_data()
            if not response or "data" not in response or "list" not in response["data"]:
                logger.warning("status_monitor 获取活动码数据失败")
                return

            current_codes = response["data"]["list"]
            current_codes_ids = {code["ID"] for code in current_codes}

            if not previous_codes_ids:
                previous_codes_ids = current_codes_ids
                await save_id_set(previous_codes_ids, "event_codes_ids")
                logger.info("status_monitor 首次运行，已记录{}条活动码ID", len(current_codes_ids))
                return

            new_codes_ids = current_codes_ids - previous_codes_ids
            if new_codes_ids:
                logger.info("status_monitor 检测到{}条新增活动码", len(new_codes_ids))
                active_new_codes = [
                    code
                    for code in current_codes
                    if code["ID"] in new_codes_ids and code.get("status") != 0
                ]

                if active_new_codes:
                    bots = get_driver().bots
                    if not bots:
                        logger.warning(
                            "status_monitor QQ 未连接，暂缓推进活动码缓存，等待重连后补推{}条有效活动码",
                            len(active_new_codes),
                        )
                        return

                    groups_config = await group_config_repo.load()
                    bot = list(bots.values())[0]

                    for code in active_new_codes:
                        title = code.get("title", "未知活动")
                        desc = code.get("desc", "无描述")
                        created_at = code.get("created_at", "").replace("T", " ").replace("Z", "")
                        message = (
                            f"检测到新活动码:\n奖励: {desc}\n兑换码:{title} \n创建时间: {created_at}\n输入 奖励 查看过往兑换码"
                        )

                        for gid, config in groups_config.items():
                            try:
                                if not isinstance(config, dict) or config.get("福利推送", False) is False:
                                    continue

                                await send_group_msg(bot, group_id=int(gid), message=message)
                                logger.info("status_monitor 向群{}推送活动码: {}", gid, title)
                            except Exception as e:
                                logger.warning("status_monitor 向群{}推送活动码失败: {}", gid, e)

            if current_codes_ids:
                previous_codes_ids = current_codes_ids
                await save_id_set(previous_codes_ids, "event_codes_ids")
        except Exception as e:
            logger.warning("status_monitor 检查活动码出错: {}", e)


@scheduler.scheduled_job("interval", minutes=STATUS_check_time, max_instances=1)
async def check_status():
    global previous_status
    try:
        if not previous_status:
            previous_status = await CacheManager.load_cache("server_status", {})
            if not previous_status:
                logger.info("status_monitor 没有发现服务器状态缓存或缓存为空")
                previous_status = {}
            else:
                logger.info("status_monitor 从缓存加载了{}条服务器状态数据", len(previous_status))

        data = await get_server_status()
        if not data or data.get("error"):
            logger.warning("status_monitor 获取服务器状态失败")
            return

        current_details = {s["server"]: s for s in server_status_items(data)}
        if not current_details:
            logger.warning("status_monitor 服务器状态为空，保留已有缓存")
            return
        current = {server: info.get("legacyStatus", info["status"]) for server, info in current_details.items()}
        current_time = int(time.time())

        status_history = await CacheManager.load_cache("status_history", {})

        if not previous_status:
            for server, status in current.items():
                if server not in status_history:
                    status_history[server] = {"last_maintenance": None, "last_open": None}

                if current_details[server].get("time_source") == "observed":
                    continue
                api_time = current_details[server].get("time", current_time)
                if status == 0:
                    status_history[server]["last_maintenance"] = api_time
                else:
                    status_history[server]["last_open"] = api_time

            logger.info("status_monitor 首次运行，已记录{}条服务器数据", len(current))
            previous_status = current

            await CacheManager.save_cache(previous_status, "server_status")
            await CacheManager.save_cache(status_history, "status_history")
            return

        changed_servers = set()
        for server, status in current.items():
            if server in previous_status and previous_status[server] != status:
                changed_servers.add(server)

                if server not in status_history:
                    status_history[server] = {"last_maintenance": None, "last_open": None}

                api_time = current_details[server].get("time", current_time)
                if status == 1:
                    status_history[server]["last_open"] = api_time
                else:
                    status_history[server]["last_maintenance"] = api_time

        if changed_servers:
            logger.info("status_monitor 检测到{}个服务器状态变化", len(changed_servers))
            await asyncio.sleep(5)

            if get_driver().bots:
                bot = list(get_driver().bots.values())[0]
                groups_config = await group_config_repo.load()
                target_groups = [
                    (gid, bound_server)
                    for gid, config in groups_config.items()
                    if isinstance(config, dict)
                    and config.get("开服推送", True) is not False
                    and isinstance((bound_server := config.get("servers")), str)
                    and bound_server in changed_servers
                ]

                if target_groups:
                    try:
                        banben = await get_server_banben()
                        banben = extract_version(banben)
                    except Exception as e:
                        logger.warning("status_monitor 获取版本号失败: {}", e)
                        banben = "未知"

                    for gid, bound_server in target_groups:
                        try:
                            server_info = current_details[bound_server]
                            zone = server_info["zone"]
                            if zone.endswith("区"):
                                zone = zone[:-1] + "大区"
                            status = server_info.get("legacyStatus", server_info["status"])

                            server_history = status_history.get(
                                bound_server, {"last_maintenance": None, "last_open": None}
                            )
                            last_maintenance_time = server_history.get("last_maintenance")
                            last_open_time = server_history.get("last_open")

                            maintenance_time_str = (
                                "无记录" if last_maintenance_time is None else format_time(last_maintenance_time)
                            )
                            open_time_str = "无记录" if last_open_time is None else format_time(last_open_time)

                            if status == 1:
                                message = (
                                    f"{zone}：{bound_server}「 已开服 」\n"
                                    f"开服时间：{open_time_str}\n"
                                    f"维护时间：{maintenance_time_str}"
                                )
                            else:
                                message = (
                                    f"{zone}：{bound_server}「 维护中 」\n"
                                    f"维护时间：{maintenance_time_str}\n"
                                    f"上次开服：{open_time_str}"
                                )

                            if banben != "未知":
                                message += f"\n最新版本：{banben}"

                            await send_group_msg(bot, group_id=int(gid), message=message)
                            logger.info("status_monitor 向群{}推送服务器状态变化: {}", gid, bound_server)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            logger.warning("status_monitor 向群{}推送服务器状态失败: {}", gid, e)

        previous_status = current
        await CacheManager.save_cache(previous_status, "server_status")
        await CacheManager.save_cache(status_history, "status_history")
    except Exception as e:
        logger.warning("status_monitor 开服检查出错: {}", e)


@scheduler.scheduled_job("cron", hour=_DAILY_GTE_HOUR, minute=0, max_instances=1)
async def push_daily_gte():
    if BOT_INITIALIZED:
        try:
            bots = get_driver().bots
            if not bots:
                return
            bot = list(bots.values())[0]
            groups_config = await group_config_repo.load()
            gte_cache: Dict[str, Optional[dict]] = {}

            for gid, config in groups_config.items():
                try:
                    if not isinstance(config, dict) or config.get("日常推送", False) is False:
                        continue

                    raw_server = config.get("servers", "")
                    if not isinstance(raw_server, str):
                        continue
                    server = raw_server.strip()
                    if not server:
                        continue

                    if server not in gte_cache:
                        gte_cache[server] = await get_gte_data(url=calendar_URL, server=server)
                    gte_data = gte_cache[server]
                    if not gte_data:
                        continue
                    message = format_gte_message(gte_data)
                    await send_group_msg(bot, group_id=int(gid), message=message)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning("status_monitor 向群{}推送日常失败: {}", gid, e)
        except Exception as e:
            logger.warning("status_monitor 推送日常出错: {}", e)


@scheduler.scheduled_job("cron", hour=9, minute=0, max_instances=1)
async def push_daily_jjc_peak_score_ranking():
    try:
        result = await jjc_peak_score_ranking_service.run_latest_two_snapshots()
        logger.info(
            "status_monitor JJC 14天最高分统计完成: anchors={} generated={} skipped={} failed={}".format(
                result.get("anchors"),
                result.get("generated"),
                result.get("skipped"),
                result.get("failed"),
            )
        )
    except Exception as e:
        logger.warning("status_monitor JJC 14天最高分统计出错: {}", e)


@scheduler.scheduled_job("cron", hour="3,21", minute=0, max_instances=2)
async def push_daily_jjc_ranking():
    bot = None
    try:
        ranking_result = await jjc_ranking_service.query_jjc_ranking()
        if not ranking_result:
            logger.warning("status_monitor 获取竞技场排行榜数据失败：返回为空")
            await notify_jjc_ranking_failure(bot, "获取竞技场排行榜数据失败：返回为空")
            return

        if ranking_result.get("error"):
            detail = ranking_result.get("message", "未知错误")
            logger.warning(
                "status_monitor 获取竞技场排行榜数据失败：{}",
                detail,
            )
            await notify_jjc_ranking_failure(bot, f"获取竞技场排行榜数据失败：{detail}")
            return

        if ranking_result.get("code") != 0:
            detail = ranking_result.get("code")
            logger.warning(
                "status_monitor 获取竞技场排行榜数据失败：API返回错误码 {}",
                detail,
            )
            await notify_jjc_ranking_failure(bot, f"获取竞技场排行榜数据失败：API返回错误码 {detail}")
            return

        default_week = ranking_result.get("defaultWeek")
        cache_time = ranking_result.get("cache_time")
        week_info = (
            jjc_ranking_service.calculate_season_week_info(default_week, cache_time)
            if default_week
            else "第12周"
        )

        ranking_data = await jjc_ranking_service.get_ranking_kungfu_data(ranking_data=ranking_result)
        if not ranking_data:
            logger.warning("status_monitor 获取心法统计数据失败：返回为空")
            await notify_jjc_ranking_failure(bot, "获取心法统计数据失败：返回为空")
            return

        if ranking_data.get("error"):
            detail = ranking_data.get("message", "未知错误")
            logger.warning(
                "status_monitor 获取心法统计数据失败：{}",
                detail,
            )
            await notify_jjc_ranking_failure(bot, f"获取心法统计数据失败：{detail}")
            return

        stats = ranking_data.get("kungfu_statistics", {})
        if not stats:
            logger.warning("status_monitor 心法统计数据为空")
            await notify_jjc_ranking_failure(bot, "心法统计数据为空")
            return

        # 统计落库不依赖 QQ、群订阅或图片渲染。
        save_task = jjc_ranking_service.save_ranking_stats(
            ranking_result=ranking_result,
            stats=stats,
            week_info=week_info,
            **({"payload": ranking_data} if any(key in ranking_data for key in ("kungfu_cache_scope", "refresh_degraded", "_sync_request", "equipment_view")) else {}),
        )
        if ranking_data.get("equipment_view") is not None and save_task is None:
            raise RuntimeError("equipment_publication_unavailable")
        if save_task is not None:
            await save_task

        # 采集可能耗时较长，发送前重新获取连接状态。
        bot = next(iter(get_driver().bots.values()), None)
        if bot is None:
            logger.info("status_monitor 竞技排名统计流程完成，QQ 未连接，跳过群推送与管理员私聊")
            return

        missing_kungfu_lines = ranking_data.get("missing_kungfu_lines") or []

        groups_config = await group_config_repo.load()
        target_groups = [
            gid
            for gid, config in groups_config.items()
            if isinstance(config, dict) and config.get("竞技排名推送", False)
        ]
        if not target_groups:
            logger.info("status_monitor 竞技排名统计流程完成，没有开启竞技排名推送的群组")
            if missing_kungfu_lines:
                await notify_jjc_ranking_missing_kungfu(bot, missing_kungfu_lines, week_info=week_info)
            return

        payload = await render_combined_ranking_image(
            env=env,
            render_template_image=render_template_image,
            current_season=cfg.CURRENT_SEASON,
            stats=stats,
            week_info=week_info,
            show_legendary=False,
        )
        if not payload:
            logger.warning("status_monitor 渲染竞技场统计图失败")
            await notify_jjc_ranking_failure(bot, "渲染竞技场统计图失败")
            if missing_kungfu_lines:
                await notify_jjc_ranking_missing_kungfu(bot, missing_kungfu_lines, week_info=week_info)
            return

        summary_text = (
            f"⏰ 每日03:00/21:00竞技排名推送（{week_info}）\n"
            f"统计范围：{payload['scope_desc']}\n"
            f"统计完成！共处理 {payload['total_valid_data']} 条有效数据（{payload['processed_label']}）"
        )

        for gid in target_groups:
            try:
                await send_group_msg(bot,
                    group_id=int(gid), message=MessageSegment.image(payload["image_bytes"])
                )
                await send_group_msg(bot, group_id=int(gid), message=summary_text)
                logger.info("status_monitor 向群{}推送每日竞技排名统计", gid)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning("status_monitor 向群{}推送竞技排名统计失败: {}", gid, e)

        if missing_kungfu_lines:
            await notify_jjc_ranking_missing_kungfu(bot, missing_kungfu_lines, week_info=week_info)

    except Exception as e:
        logger.warning("status_monitor 每日竞技排名推送任务出错: {}", e)
        await notify_jjc_ranking_failure(bot, f"每日竞技排名推送任务出错：{e}")
