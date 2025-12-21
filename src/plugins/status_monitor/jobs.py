import asyncio
import json
import re
import time
from datetime import datetime
from functools import wraps

import httpx
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_apscheduler import scheduler

from src.services.jx3.singletons import jjc_ranking_service
from src.services.jx3.singletons import group_config_repo

from .notify import get_NapCat_data, send_email_via_163
from .storage import CacheManager, load_id_set, save_id_set

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


BOT_INITIALIZED = False
previous_status = {}
previous_news_ids = set()
previous_records_ids = set()
previous_codes_ids = set()
last_status_ok = True


def set_bot_initialized(value: bool) -> None:
    global BOT_INITIALIZED
    BOT_INITIALIZED = value


def log_startup() -> None:
    print(f"开服监控已启动，API: {STATUS_check_API} 延时{STATUS_check_time}分钟")
    print(f"新闻监控已启动，API: {NEWS_API_URL} 延时{NEWS_records_time}分钟")
    print(f"技改监控已启动，API: {SKILL_records_URL} 延时{NEWS_records_time}分钟")
    print(f"日常监控已启动，API: 每天{calendar_time}点推送")


def prevent_duplicate_runs(timeout_seconds=60):
    def decorator(func):
        last_run = 0

        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal last_run
            current_time = time.time()

            if current_time - last_run > timeout_seconds:
                last_run = current_time
                return await func(*args, **kwargs)
            else:
                print(f"Skipping duplicate run of {func.__name__}")

        return wrapper

    return decorator


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
        print(f"提取版本号出错: {e}")
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
        print(url)
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(url)
            if response.status_code != 200:
                print(f"GTE API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"请求GTE API出错: {e}")
        return None


async def get_server_status():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(STATUS_check_API)
            if response.status_code != 200:
                print(f"开服监测API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"开服监测请求API出错: {e}")
        return None


async def get_server_banben():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get("https://www.jx3api.com/data/news/announce")
            if response.status_code != 200:
                print(f"开服监测API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"开服监测请求API出错: {e}")
        return None


async def get_news_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(NEWS_API_URL)
            if response.status_code != 200:
                print(f"新闻API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"请求新闻API出错: {e}")
        return None


async def get_records_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(SKILL_records_URL)
            if response.status_code != 200:
                print(f"技改API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"请求技改API出错: {e}")
        return None


async def get_jx3box_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(jx3box_URL)
            if response.status_code != 200:
                print(f"技改API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"请求技改API出错: {e}")
        return None


@scheduler.scheduled_job("interval", seconds=60)
async def mail_records():
    global last_status_ok

    data = await get_NapCat_data()

    if data is None:
        current_status_ok = False
        status_info = "无法获取服务器状态，API请求失败"
    else:
        current_status_ok = data.get("status", "").lower() == "ok"
        status_info = json.dumps(data, ensure_ascii=False)

    if last_status_ok and not current_status_ok:
        print("检测到状态异常，发送邮件通知...")
        email_content = f"服务器状态异常！\n\n当前状态信息：\n{status_info}"
        send_result = send_email_via_163(email_content)
        if send_result:
            print("邮件发送成功")
        else:
            print("邮件发送失败")

    elif not last_status_ok and current_status_ok:
        recovery_content = "服务器状态已恢复正常！"
        send_email_via_163(recovery_content)

    last_status_ok = current_status_ok


@scheduler.scheduled_job("interval", minutes=NEWS_records_time)
async def check_records():
    if BOT_INITIALIZED:
        global previous_records_ids
        try:
            if not previous_records_ids:
                previous_records_ids = load_id_set("records_ids")
                if not previous_records_ids:
                    print("没有发现技改缓存或缓存为空")
                else:
                    print(f"从缓存加载了{len(previous_records_ids)}条技改ID")

            data = await get_records_data()
            if not data or "data" not in data:
                print("获取技改数据失败")
                return

            current_records = data["data"]
            current_records_ids = {record["id"] for record in current_records}

            if not previous_records_ids:
                previous_records_ids = current_records_ids
                save_id_set(previous_records_ids, "records_ids")
                print(f"首次运行，已记录{len(current_records_ids)}条技改ID")
                return

            new_records_ids = current_records_ids - previous_records_ids
            if new_records_ids:
                print(f"检测到{len(new_records_ids)}条新增技改")

                new_records = [record for record in current_records if record["id"] in new_records_ids]

                if get_driver().bots:
                    bot = list(get_driver().bots.values())[0]
                    groups_config = group_config_repo.load()

                    for gid, config in groups_config.items():
                        try:
                            if not isinstance(config, dict) or config.get("技改推送", False) is False:
                                continue

                            for record in new_records:
                                record_class = "官方公告"
                                title = record.get("title", "无标题")
                                url = record.get("url", "")
                                date = record.get("time", "")

                                message = (
                                    f"{record_class}\n"
                                    f"标题：{title}\n"
                                    f"链接：{url}\n"
                                    f"日期：{date}"
                                )

                                await bot.send_group_msg(group_id=int(gid), message=message)
                                print(f"向群{gid}推送了技改: {title}")
                        except Exception as e:
                            print(f"向群{gid}推送技改时出错: {e}")

            previous_records_ids = current_records_ids
            save_id_set(previous_records_ids, "records_ids")
        except Exception as e:
            print(f"检查技改出错: {e}")


@scheduler.scheduled_job("interval", minutes=NEWS_records_time)
async def check_news():
    if BOT_INITIALIZED:
        global previous_news_ids
        try:
            if not previous_news_ids:
                previous_news_ids = load_id_set("news_ids")
                if not previous_news_ids:
                    print("没有发现缓存或缓存为空")
                else:
                    print(f"从缓存加载了{len(previous_news_ids)}条新闻ID")

            data = await get_news_data()
            if not data or "data" not in data:
                print("获取新闻数据失败")
                return

            current_news = data["data"]
            current_news = [
                item
                for item in current_news
                if "武学" not in item.get("title", "")
                and "版本" not in item.get("title", "")
                and "维护" not in item.get("title", "")
            ]
            current_news_ids = {news["id"] for news in current_news}

            if not previous_news_ids:
                previous_news_ids = current_news_ids
                save_id_set(previous_news_ids, "news_ids")
                print(f"首次运行，已记录{len(current_news_ids)}条新闻ID")
                return

            new_news_ids = current_news_ids - previous_news_ids
            if new_news_ids:
                print(f"检测到{len(new_news_ids)}条新增新闻")
                new_news = [news for news in current_news if news["id"] in new_news_ids]

                if get_driver().bots:
                    bot = list(get_driver().bots.values())[0]
                    groups_config = group_config_repo.load()

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

                                await bot.send_group_msg(group_id=int(gid), message=message)
                                print(f"向群{gid}推送了新闻: {title}")
                        except Exception as e:
                            print(f"向群{gid}推送新闻时出错: {e}")

            previous_news_ids = current_news_ids
            save_id_set(previous_news_ids, "news_ids")
        except Exception as e:
            print(f"检查新闻出错: {e}")


@scheduler.scheduled_job("interval", minutes=200)
async def check_event_codes():
    if BOT_INITIALIZED:
        global previous_codes_ids
        current_codes_ids = set()

        try:
            if not previous_codes_ids:
                previous_codes_ids = load_id_set("event_codes_ids")
                if not previous_codes_ids:
                    print("没有发现活动码缓存或缓存为空")
                else:
                    print(f"从缓存加载了{len(previous_codes_ids)}条活动码ID")

            response = await get_jx3box_data()
            if not response or "data" not in response or "list" not in response["data"]:
                print("获取活动码数据失败")
                return

            current_codes = response["data"]["list"]
            current_codes_ids = {code["ID"] for code in current_codes}

            if not previous_codes_ids:
                previous_codes_ids = current_codes_ids
                save_id_set(previous_codes_ids, "event_codes_ids")
                print(f"首次运行，已记录{len(current_codes_ids)}条活动码ID")
                return

            new_codes_ids = current_codes_ids - previous_codes_ids
            if new_codes_ids:
                print(f"检测到{len(new_codes_ids)}条新增活动码")
                new_codes = [code for code in current_codes if code["ID"] in new_codes_ids]

                if get_driver().bots:
                    groups_config = group_config_repo.load()
                    bot = list(get_driver().bots.values())[0]

                    for code in new_codes:
                        if code["status"] == 0:
                            continue

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

                                await bot.send_group_msg(group_id=int(gid), message=message)
                                print(f"向群{gid}推送了活动码: {title}")
                            except Exception as e:
                                print(f"向群{gid}推送活动码时出错: {e}")

            if current_codes_ids:
                previous_codes_ids = current_codes_ids
                save_id_set(previous_codes_ids, "event_codes_ids")
        except Exception as e:
            print(f"检查活动码出错: {e}")


@scheduler.scheduled_job("interval", minutes=STATUS_check_time)
@prevent_duplicate_runs(timeout_seconds=3600)
async def check_status():
    global previous_status
    try:
        if not previous_status:
            previous_status = CacheManager.load_cache("server_status", {})
            if not previous_status:
                print("没有发现服务器状态缓存或缓存为空")
                previous_status = {}
            else:
                print(f"从缓存加载了{len(previous_status)}条服务器状态数据")

        data = await get_server_status()
        if not data:
            print("获取服务器状态失败")
            return

        current_details = {s["server"]: s for s in data.get("data", [])}
        current = {server: info["status"] for server, info in current_details.items()}
        current_time = int(time.time())

        status_history = CacheManager.load_cache("status_history", {})

        if not previous_status:
            for server, status in current.items():
                if server not in status_history:
                    status_history[server] = {"last_maintenance": None, "last_open": None}

                api_time = current_details[server].get("time", current_time)
                if status == 0:
                    status_history[server]["last_maintenance"] = api_time
                else:
                    status_history[server]["last_open"] = api_time

            print(f"首次运行，已记录{len(current)}条服务器数据")
            previous_status = current

            CacheManager.save_cache(previous_status, "server_status")
            CacheManager.save_cache(status_history, "status_history")
            return

        changed_servers = []
        for server, status in current.items():
            if server in previous_status and previous_status[server] != status:
                changed_servers.append(server)

                if server not in status_history:
                    status_history[server] = {"last_maintenance": None, "last_open": None}

                api_time = current_details[server].get("time", current_time)
                if status == 1:
                    status_history[server]["last_open"] = api_time
                else:
                    status_history[server]["last_maintenance"] = api_time

        if changed_servers:
            print(f"检测到{len(changed_servers)}个服务器状态变化")
            time.sleep(5)

            if get_driver().bots:
                bot = list(get_driver().bots.values())[0]
                groups_config = group_config_repo.load()

                for gid, config in groups_config.items():
                    try:
                        if not isinstance(config, dict) or config.get("开服推送", True) is False:
                            continue

                        bound_server = config.get("servers", "")
                        if not bound_server or bound_server not in changed_servers:
                            continue

                        try:
                            banben = await get_server_banben()
                            banben = extract_version(banben)
                        except Exception as e:
                            print(f"获取版本号出错: {e}")
                            banben = "未知"

                        server_info = current_details[bound_server]
                        zone = server_info["zone"]
                        if zone.endswith("区"):
                            zone = zone[:-1] + "大区"
                        status = server_info["status"]

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

                        await bot.send_group_msg(group_id=int(gid), message=message)
                        print(f"向群{gid}推送了服务器 {bound_server} 状态变化")
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"向群{gid}推送服务器状态时出错: {e}")

        previous_status = current
        CacheManager.save_cache(previous_status, "server_status")
        CacheManager.save_cache(status_history, "status_history")
    except Exception as e:
        print(f"开服检查出错: {e}")


@scheduler.scheduled_job("cron", hour=9, minute=0)
async def push_daily_gte():
    if BOT_INITIALIZED:
        try:
            if not get_driver().bots:
                return
            bot = list(get_driver().bots.values())[0]
            groups_config = group_config_repo.load()

            for gid, config in groups_config.items():
                try:
                    if not isinstance(config, dict) or config.get("日常推送", False) is False:
                        continue

                    server = config.get("servers", "")
                    if not server:
                        continue

                    gte_data = await get_gte_data(url=calendar_URL, server=server)
                    if not gte_data:
                        continue
                    message = format_gte_message(gte_data)
                    await bot.send_group_msg(group_id=int(gid), message=message)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"向群{gid}推送日常时出错: {e}")
        except Exception as e:
            print(f"推送日常出错: {e}")


@scheduler.scheduled_job("cron", hour=8, minute=30)
async def push_daily_jjc_ranking():
    if BOT_INITIALIZED:
        try:
            bots = get_driver().bots
            if not bots:
                print("没有可用的机器人")
                return

            bot = list(bots.values())[0]
            groups_config = group_config_repo.load()

            target_groups = [
                gid
                for gid, config in groups_config.items()
                if isinstance(config, dict) and config.get("竞技排名推送", False)
            ]

            if not target_groups:
                print("没有开启竞技排名推送的群组")
                return

            ranking_result = await jjc_ranking_service.query_jjc_ranking()
            if not ranking_result:
                print("获取竞技场排行榜数据失败：返回为空")
                return

            if ranking_result.get("error"):
                print(f"获取竞技场排行榜数据失败：{ranking_result.get('message', '未知错误')}")
                return

            if ranking_result.get("code") != 0:
                print(f"获取竞技场排行榜数据失败：API返回错误码 {ranking_result.get('code')}")
                return

            default_week = ranking_result.get("defaultWeek")
            cache_time = ranking_result.get("cache_time")
            week_info = (
                jjc_ranking_service.calculate_season_week_info(default_week, cache_time)
                if default_week
                else "第12周"
            )

            ranking_data = await jjc_ranking_service.get_ranking_kuangfu_data(ranking_data=ranking_result)
            if not ranking_data:
                print("获取心法统计数据失败：返回为空")
                return

            if ranking_data.get("error"):
                print(f"获取心法统计数据失败：{ranking_data.get('message', '未知错误')}")
                return

            stats = ranking_data.get("kuangfu_statistics", {})
            if not stats:
                print("心法统计数据为空")
                return

            payload = await jjc_ranking_service.render_combined_ranking_image(stats, week_info)
            if not payload:
                print("渲染竞技场统计图失败")
                return

            summary_text = (
                f"⏰ 每日08:30竞技排名推送（{week_info}）\n"
                f"统计范围：{payload['scope_desc']}\n"
                f"统计完成！共处理 {payload['total_valid_data']} 条有效数据（{payload['processed_label']}）"
            )

            for gid in target_groups:
                try:
                    await bot.send_group_msg(
                        group_id=int(gid), message=MessageSegment.image(payload["image_bytes"])
                    )
                    await bot.send_group_msg(group_id=int(gid), message=summary_text)
                    print(f"向群 {gid} 推送了每日竞技排名统计")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"向群 {gid} 推送竞技排名统计时出错: {e}")

        except Exception as e:
            print(f"每日竞技排名推送任务出错: {e}")
