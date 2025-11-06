import json, os, httpx, asyncio
from nonebot import get_driver, on_command,on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.plugin import require
from datetime import datetime
from typing import Any, Set, List, Dict, Optional, Union
import smtplib
from email.message import EmailMessage
from functools import wraps
import time
import re

# 导入配置并设置默认值
try: 
    from config import STATUS_check_time,NEWS_records_time, STATUS_check_API,NEWS_API_URL,SKILL_records_URL,calendar_URL,calendar_time,jx3box_URL,mail

except ImportError:
      GROUP_CONFIG_FILE = "groups.json"

# 服务器地址
BASE_URL = "https://music.xxxxx.cn:88"
ADMIN_USERNAME = "useradmin"  # 管理员用户名
ADMIN_PASSWORD = "useradmin"  # 管理员密码
# 初始化
GROUP_CONFIG_FILE = "groups.json"
driver = get_driver()
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from src.plugins.jx3bot import (
    query_jjc_ranking,
    get_ranking_kuangfu_data,
    calculate_season_week_info,
    render_combined_ranking_image,
)


# 群组配置简化函数
def load_groups(): 
    return json.load(open(GROUP_CONFIG_FILE, 'r', encoding='utf-8')) if os.path.exists(GROUP_CONFIG_FILE) else {}
def save_groups(cfg): 
    json.dump(cfg, open(GROUP_CONFIG_FILE, 'w', encoding='utf-8'), ensure_ascii=False)


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
# 缓存基础目录
CACHE_DIR = "data/cache"

#缓存管理器
class CacheManager:
    """通用缓存管理器，可用于多种数据的缓存"""

    @staticmethod
    def ensure_cache_dir() -> None:
        """确保缓存目录存在"""
        os.makedirs(CACHE_DIR, exist_ok=True)

    @staticmethod
    def save_cache(data: Any, cache_name: str) -> bool:
        """
        保存数据到指定的缓存文件

        参数:
            data: 要缓存的数据(支持JSON序列化的任何数据)
            cache_name: 缓存文件名(不含路径和扩展名)

        返回:
            bool: 保存是否成功
        """
        try:
            CacheManager.ensure_cache_dir()
            cache_file = os.path.join(CACHE_DIR, f"{cache_name}.json")
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return True
        except Exception as e:
            print(f"保存缓存失败({cache_name}): {str(e)}")
            return False

    @staticmethod
    def load_cache(cache_name: str, default: Any = None) -> Any:
        """
        从指定的缓存文件加载数据

        参数:
            cache_name: 缓存文件名(不含路径和扩展名)
            default: 如果缓存不存在或加载失败时返回的默认值

        返回:
            缓存的数据，或者默认值(如果缓存不存在或加载失败)
        """
        try:
            cache_file = os.path.join(CACHE_DIR, f"{cache_name}.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"读取缓存失败({cache_name}): {str(e)}")
        return default


# 特定类型缓存的辅助函数
def save_id_set(ids: Set[str], cache_name: str) -> bool:
    """保存ID集合到缓存"""
    return CacheManager.save_cache({"ids": list(ids)}, cache_name)


def load_id_set(cache_name: str) -> Set[str]:
    """从缓存加载ID集合"""
    data = CacheManager.load_cache(cache_name, {"ids": []})
    return set(data.get("ids", []))



# 全局变量
previous_status = {}  # 上次检查的服务器状态
server_maintenance_times = {}  # 服务器进入维护的时间
server_open_times = {}  # 服务器开服的时间
previous_news_ids = set()  # 上次检查的新闻ID集合
previous_records_ids = set()  # 上次检查的技改ID集合
previous_codes_ids = set()  # 上次检查的魔盒ID集合
BOT_INITIALIZED = False    # 检查机器人启动
# 定时轮询服务器状态
# 全局变量
# 定义命令

def format_time(timestamp):
    """格式化时间戳，去除月份和日期前面的0"""
    t = time.localtime(timestamp)
    month = t.tm_mon  # 获取月份（1-12）
    day = t.tm_mday  # 获取日期（1-31）
    hour = t.tm_hour
    minute = t.tm_min
    second = t.tm_sec

    # 格式化为 "4月19日 21:21:10" 格式
    return f"{month}月{day}日 {hour:02d}:{minute:02d}:{second:02d}"
# 活动格式化数据为推送消息
#版本号获取
def extract_version(json_data):
    """从JSON中提取版本号"""
    try:
        if not json_data:
            return "未知"

        # 解析JSON
        data = json_data if isinstance(json_data, dict) else json.loads(json_data)

        # 获取第一个数据项
        if "data" in data and len(data["data"]) > 0:
            first_item = data["data"][0]
            title = first_item.get("title", "")

            # 使用正则表达式提取版本号
            version_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', title)
            if version_match:
                return version_match.group(1)

        return "未知"
    except Exception as e:
        print(f"提取版本号出错: {e}")
        return "未知"
# 格式化GTE数据为推送消息
def format_gte_message(gte_data):
    if not gte_data or "data" not in gte_data:
        return "获取每日GTE数据失败"

    data = gte_data["data"]

    # 获取日期和星期
    date_str = data.get("date", "")
    week_str = data.get("week", "")

    # 将日期格式从"2025-04-19"转换为"2025年04月19日"
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            date_str = f"{date_obj.year}年{date_obj.month}月{date_obj.day}日"
        except:
            pass

    # 构建消息
    message = [f"当前时间：{date_str} 星期{week_str}"]

    # 添加各种活动信息
    message.append(f"秘境大战：{data.get('war', '无')}")
    message.append(f"战场任务：{data.get('battle', '无')}")
    message.append(f"宗门事件：{data.get('school', '无')}")
    message.append(f"驰援任务：{data.get('rescue', '无')}")
    message.append(f"阵营任务：{data.get('orecar', '无')}")
    message.append("帮会跑商：阴山商路(10:00)")  # 固定内容

    # 福源宠物
    luck_pets = ";".join(data.get("luck", []))
    message.append(f"福源宠物：{luck_pets}")

    # 添加美人图信息
    if "draw" in data:
        message.append(f"美人图：{data.get('draw', '无')}")

    # 空行
    message.append("")
    message.append("家园声望·加倍道具")
    card_items = ";".join(data.get("card", []))
    message.append(card_items)

    # 团队秘境等信息
    if "team" in data and len(data["team"]) >= 3:
        message.append("武林通鉴·公共任务")
        message.append(data["team"][0])
        message.append("武林通鉴·秘境任务")
        message.append(data["team"][1])
        message.append("武林通鉴·团队秘境")
        message.append(data["team"][2])

    return "\n".join(message)
# 获取活动数据，添加server参数
async def get_gte_data(url,server):
    try:
        # 构建带参数的URL
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

# 从API获取服务器状态
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
# 从API获取服务器状态
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
# 从API获取新闻数据
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
# 从API获取技改数据
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


# 全局状态跟踪
last_status_ok = True



async def get_NapCat_data():
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get("http://192.168.100.1:3000/get_status")
            if response.status_code != 200:
                print(f"技改API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as e:
        print(f"请求技改API出错: {e}")
        return None


def send_email_via_163(content):
    # 创建邮件对象
    msg = EmailMessage()
    msg['Subject'] = '服务器状态提醒'
    msg['From'] = '17665092013@163.com'
    msg['To'] = '11010783@qq.com'
    msg.set_content(content)

    # 163邮箱SMTP服务器设置
    smtp_server = 'smtp.163.com'
    port = 465  # SSL加密端口

    # 连接到SMTP服务器并发送邮件
    try:
        with smtplib.SMTP_SSL(smtp_server, port) as server:
            # 登录邮箱账号
            server.login('17665092013@163.com', mail)
            # 发送邮件
            server.send_message(msg)
            print('邮件发送成功！')
            return True
    except Exception as e:
        print(f'发送邮件时出错: {e}')
        return False


# 离线邮件通知
@scheduler.scheduled_job("interval", seconds=60)  # 每3秒检查一次
async def mail_records():
    """定时检查API状态并发送邮件通知"""
    global last_status_ok

    # 获取API状态
    data = await get_NapCat_data()

    # 确定当前状态是否正常
    if data is None:
        # API请求失败，视为异常状态
        current_status_ok = False
        status_info = "无法获取服务器状态，API请求失败"
    else:
        # 检查status字段
        current_status_ok = data.get('status', '').lower() == 'ok'
        status_info = json.dumps(data, ensure_ascii=False)

    # 如果状态从正常变为异常，发送邮件
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

    # 更新状态跟踪
    last_status_ok = current_status_ok





#技改轮询seconds=3
@scheduler.scheduled_job("interval", minutes=NEWS_records_time)  # 分钟检查一次
async def check_records():
    if BOT_INITIALIZED:
        global previous_records_ids
        try:
            # 首次运行时，尝试从缓存加载上次的技改ID
            if not previous_records_ids:
                previous_records_ids = load_id_set("records_ids")
                if not previous_records_ids:
                    print("没有发现技改缓存或缓存为空")
                else:
                    print(f"从缓存加载了{len(previous_records_ids)}条技改ID")

            # 获取技改数据
            data = await get_records_data()
            if not data or "data" not in data:
                print("获取技改数据失败")
                return

            # 提取技改ID
            current_records = data["data"]
            current_records_ids = {record["id"] for record in current_records}

            # 首次运行，仅记录ID不推送
            if not previous_records_ids:
                previous_records_ids = current_records_ids
                # 保存到缓存文件
                save_id_set(previous_records_ids, "records_ids")
                print(f"首次运行，已记录{len(current_records_ids)}条技改ID")
                return

            # 找出新增的技改
            new_records_ids = current_records_ids - previous_records_ids
            if new_records_ids:
                print(f"检测到{len(new_records_ids)}条新增技改")

                # 找出新增技改的详细信息
                new_records = [record for record in current_records if record["id"] in new_records_ids]

                # 推送技改
                if get_driver().bots:
                    bot = list(get_driver().bots.values())[0]
                    groups_config = load_groups()

                    for gid, config in groups_config.items():
                        try:
                            # 检查是否启用了技改推送
                            if not isinstance(config, dict) or config.get("技改推送", False) == False:
                                continue

                            # 发送每条技改
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

            # 更新技改ID记录
            previous_records_ids = current_records_ids
            # 保存到缓存文件
            save_id_set(previous_records_ids, "records_ids")
        except Exception as e:
            print(f"检查技改出错: {e}")




# 新闻轮询新闻seconds=3
@scheduler.scheduled_job("interval", minutes=NEWS_records_time)
async def check_news():
    if BOT_INITIALIZED:
        global previous_news_ids
        try:
            # 首次运行时，尝试从缓存加载上次的新闻ID


            if not previous_news_ids:
                previous_news_ids = load_id_set("news_ids")
                if not previous_news_ids:
                    print("没有发现缓存或缓存为空")
                else:
                    print(f"从缓存加载了{len(previous_news_ids)}条新闻ID")

            # 获取新闻数据
            data = await get_news_data()
            if not data or "data" not in data:
                print("获取新闻数据失败")
                return

            # 提取新闻ID
            current_news = data["data"]
            current_news = [item for item in current_news if "武学" not in item.get("title", "") and "版本" not in item.get("title", "") and "维护" not in item.get("title", "")]
            current_news_ids = {news["id"] for news in current_news}

            # 首次运行或缓存为空，仅记录ID不推送
            if not previous_news_ids:
                previous_news_ids = current_news_ids
                # 保存到缓存文件
                save_id_set(previous_news_ids, "news_ids")
                print(f"首次运行，已记录{len(current_news_ids)}条新闻ID")
                return

            # 找出新增的新闻
            new_news_ids = current_news_ids - previous_news_ids
            if new_news_ids:
                print(f"检测到{len(new_news_ids)}条新增新闻")
                # 找出新增新闻的详细信息
                new_news = [news for news in current_news if news["id"] in new_news_ids]

                # 推送新闻
                if get_driver().bots:
                    bot = list(get_driver().bots.values())[0]
                    groups_config = load_groups()

                    for gid, config in groups_config.items():
                        try:
                            # 检查是否启用了新闻推送
                            if not isinstance(config, dict) or config.get("新闻推送", False) == False:
                                continue

                            # 发送每条新闻
                            for news in new_news:
                                news_class = news.get("class", "公告")
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



            # 更新新闻ID记录
            previous_news_ids = current_news_ids
            # 保存到缓存文件
            save_id_set(previous_news_ids, "news_ids")
        except Exception as e:
            print(f"检查新闻出错: {e}")


# 魔盒福利轮询检查
@scheduler.scheduled_job("interval", minutes=200)
async def check_event_codes():
    if BOT_INITIALIZED:
        global previous_codes_ids
        # 初始化变量，防止请求失败时出错
        current_codes_ids = set()

        try:
            # 首次运行时，尝试从缓存加载上次的活动码ID
            if not previous_codes_ids:
                previous_codes_ids = load_id_set("event_codes_ids")
                if not previous_codes_ids:
                    print("没有发现活动码缓存或缓存为空")
                else:
                    print(f"从缓存加载了{len(previous_codes_ids)}条活动码ID")

            # 获取活动码数据
            response = await get_jx3box_data()
            if not response or "data" not in response or "list" not in response["data"]:
                print("获取活动码数据失败")
                return

            # 提取活动码ID
            current_codes = response["data"]["list"]
            current_codes_ids = {code["ID"] for code in current_codes}

            # 首次运行或缓存为空，仅记录ID不推送
            if not previous_codes_ids:
                previous_codes_ids = current_codes_ids
                # 保存到缓存文件
                save_id_set(previous_codes_ids, "event_codes_ids")
                print(f"首次运行，已记录{len(current_codes_ids)}条活动码ID")
                return

            # 找出新增的活动码
            new_codes_ids = current_codes_ids - previous_codes_ids
            if new_codes_ids:
                print(f"检测到{len(new_codes_ids)}条新增活动码")

                # 获取新增活动码的详细信息
                new_codes = [code for code in current_codes if code["ID"] in new_codes_ids]

                if get_driver().bots:
                    groups_config = load_groups()
                    bot = list(get_driver().bots.values())[0] # 获取机器人实例

                    # 推送新活动码信息
                    for code in new_codes:
                        # 过滤掉状态为0的代码(不活跃的活动码)
                        if code["status"] == 0:
                            continue

                        # 构建消息内容
                        title = code.get("title", "未知活动")
                        desc = code.get("desc", "无描述")
                        created_at = code.get("created_at", "").replace("T", " ").replace("Z", "")
                        message = f"检测到新活动码:\n奖励: {desc}\n兑换码:{title} \n创建时间: {created_at}\n输入 奖励 查看过往兑换码"

                        # 向启用了福利推送的群发送消息
                        for gid, config in groups_config.items():
                            try:
                                # 检查是否启用了福利推送
                                if not isinstance(config, dict) or config.get("福利推送", False) == False:
                                    continue

                                await bot.send_group_msg(group_id=int(gid), message=message)
                                print(f"向群{gid}推送了活动码: {title}")
                            except Exception as e:
                                print(f"向群{gid}推送活动码时出错: {e}")

            # 更新活动码ID记录 - 只有当获取成功时才更新
            if current_codes_ids:
                previous_codes_ids = current_codes_ids
                # 保存到缓存文件
                save_id_set(previous_codes_ids, "event_codes_ids")
        except Exception as e:
            print(f"检查活动码出错: {e}")



# 开服轮询状态 seconds=3
@scheduler.scheduled_job("interval", minutes=STATUS_check_time)
@prevent_duplicate_runs(timeout_seconds=3600)  # 设置最小间隔时间
async def check_status():
    global previous_status
    try:
        # 从缓存加载历史数据
        if not previous_status:
            previous_status = CacheManager.load_cache("server_status", {})
            # 初始化为空字典而不是None
            if not previous_status:
                print("没有发现服务器状态缓存或缓存为空")
                previous_status = {}
            else:
                print(f"从缓存加载了{len(previous_status)}条服务器状态数据")

        # 从API获取数据
        data = await get_server_status()
        if not data:
            print("获取服务器状态失败")
            return

        # 当前状态: 服务器名 -> 服务器完整信息
        current_details = {s['server']: s for s in data.get("data", [])}
        current = {server: info["status"] for server, info in current_details.items()}
        current_time = int(time.time())

        # 获取状态历史数据
        status_history = CacheManager.load_cache("status_history", {})

        # 首次运行，仅保存状态不推送
        if not previous_status:
            # 初始化历史记录
            for server, status in current.items():
                if server not in status_history:
                    status_history[server] = {
                        "last_maintenance": None,
                        "last_open": None
                    }

                api_time = current_details[server].get("time", current_time)
                if status == 0:  # 维护中
                    status_history[server]["last_maintenance"] = api_time
                else:  # 开服中
                    status_history[server]["last_open"] = api_time

            print(f"首次运行，已记录{len(current)}条服务器数据")
            previous_status = current

            # 保存到缓存
            CacheManager.save_cache(previous_status, "server_status")
            CacheManager.save_cache(status_history, "status_history")
            return

        # 找出状态变化的服务器
        changed_servers = []
        for server, status in current.items():
            if server in previous_status and previous_status[server] != status:
                changed_servers.append(server)

                # 确保服务器在历史记录中
                if server not in status_history:
                    status_history[server] = {
                        "last_maintenance": None,
                        "last_open": None
                    }

                # 立即更新状态历史
                api_time = current_details[server].get("time", current_time)
                if status == 1:  # 变为开服状态
                    status_history[server]["last_open"] = api_time
                else:  # 变为维护状态
                    status_history[server]["last_maintenance"] = api_time

        if changed_servers:
            print(f"检测到{len(changed_servers)}个服务器状态变化")
            # 添加5秒延迟
            time.sleep(5)

            # 推送变化通知
            if get_driver().bots:
                bot = list(get_driver().bots.values())[0]
                groups_config = load_groups()

                for gid, config in groups_config.items():
                    try:
                        # 检查群组配置与开服推送开关
                        if not isinstance(config, dict) or config.get("开服推送", True) == False:
                            continue

                        # 获取该群绑定的服务器
                        bound_server = config.get("servers", "")
                        if not bound_server or bound_server not in changed_servers:
                            continue

                        # 获取版本号
                        try:
                            banben = await get_server_banben()
                            banben = extract_version(banben)
                        except Exception as e:
                            print(f"获取版本号出错: {e}")
                            banben = "未知"

                        # 获取服务器详细信息
                        server_info = current_details[bound_server]
                        zone = server_info["zone"]
                        if zone.endswith("区"):
                            zone = zone[:-1] + "大区"
                        status = server_info["status"]

                        # 从历史记录获取时间
                        server_history = status_history.get(bound_server, {"last_maintenance": None, "last_open": None})
                        last_maintenance_time = server_history.get("last_maintenance")
                        last_open_time = server_history.get("last_open")

                        # 根据状态变化格式化消息
                        if status == 1:  # 变为开服状态
                            maintenance_time_str = "无记录" if last_maintenance_time is None else format_time(
                                last_maintenance_time)
                            open_time = server_history["last_open"]  # 刚刚更新的开服时间

                            message = (
                                f"{zone}：{bound_server}「 已开服 」\n"
                                f"开服时间：{format_time(open_time)}\n"
                                f"维护时间：{maintenance_time_str}"
                            )
                        else:  # 变为维护状态
                            open_time_str = "无记录" if last_open_time is None else format_time(last_open_time)
                            maintenance_time = server_history["last_maintenance"]  # 刚刚更新的维护时间

                            message = (
                                f"{zone}：{bound_server}「 维护中 」\n"
                                f"维护时间：{format_time(maintenance_time)}\n"
                                f"上次开服：{open_time_str}"
                            )

                        # 添加版本信息
                        if banben != "未知":
                            message += f"\n最新版本：{banben}"

                        # 发送消息
                        await bot.send_group_msg(group_id=int(gid), message=message)
                        print(f"向群{gid}发送了服务器状态通知")
                    except Exception as e:
                        print(f"处理群{gid}时出错: {e}")

            # 保存历史记录
            CacheManager.save_cache(status_history, "status_history")

        # 更新状态记录
        previous_status = current
        # 保存当前状态
        CacheManager.save_cache(previous_status, "server_status")
    except Exception as e:
        print(f"检查服务器状态出错: {e}")

# 活动推送9点推送GTE
@scheduler.scheduled_job("cron", hour=9, minute=0)
async def daily_gte_report():
    try:
        print("开始执行每日GTE查询推送")

        # 获取所有群组配置
        groups_config = load_groups()
        if not groups_config:
            print("没有群组配置")
            return

        # 获取机器人
        if not get_driver().bots:
            print("没有可用的机器人")
            return

        bot = list(get_driver().bots.values())[0]

        # 为每个启用日常推送的群组推送
        for gid, config in groups_config.items():
            try:
                # 检查是否启用了日常推送
                if isinstance(config, dict) and config.get("日常推送", False) == False:
                    continue

                # 获取绑定的服务器
                server = ""
                if isinstance(config, dict) and "servers" in config:
                    server = config["servers"]
                elif isinstance(config, list) and config:
                    server = config[0]

                if not server:
                    print(f"群 {gid} 未绑定服务器，跳过GTE推送")
                    continue

                # 获取特定服务器的GTE数据
                gte_data = await get_gte_data(url=calendar_URL,server=server)
                if not gte_data:
                    print(f"获取服务器 {server} 的GTE数据失败")
                    continue

                # 格式化消息
                message = format_gte_message(gte_data)

                # 发送消息
                await bot.send_group_msg(group_id=int(gid), message=message)
                print(f"向群 {gid} 推送了服务器 {server} 的每日GTE信息")

            except Exception as e:
                print(f"向群 {gid} 推送GTE信息时出错: {e}")

    except Exception as e:
        print(f"执行每日GTE推送时出错: {e}")


# 竞技排名每日推送
@scheduler.scheduled_job("cron", hour=8, minute=30)
async def daily_jjc_ranking_report():
    try:
        print("开始执行每日竞技排名推送")

        groups_config = load_groups()
        if not groups_config:
            print("没有群组配置")
            return

        bots = get_driver().bots
        if not bots:
            print("没有可用的机器人")
            return

        bot = list(bots.values())[0]

        # 找到开启竞技排名推送的群
        target_groups = [
            gid for gid, config in groups_config.items()
            if isinstance(config, dict) and config.get("竞技排名推送", False)
        ]

        if not target_groups:
            print("没有开启竞技排名推送的群组")
            return

        ranking_result = await query_jjc_ranking()
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
        week_info = calculate_season_week_info(default_week, cache_time) if default_week else "第12周"

        ranking_data = await get_ranking_kuangfu_data(ranking_data=ranking_result)
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

        payload = await render_combined_ranking_image(stats, week_info)
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
                await bot.send_group_msg(group_id=int(gid), message=MessageSegment.image(payload["image_bytes"]))
                await bot.send_group_msg(group_id=int(gid), message=summary_text)
                print(f"向群 {gid} 推送了每日竞技排名统计")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"向群 {gid} 推送竞技排名统计时出错: {e}")

    except Exception as e:
        print(f"执行每日竞技排名推送时出错: {e}")


# 查魔盒奖励
gte_cmd = on_regex(r"^\s*奖励\s*$", priority=5)
@gte_cmd.handle()
async def handle_gte(event: GroupMessageEvent):
    try:
        # 获取活动码数据
        response = await get_jx3box_data()
        if not response or "data" not in response or "list" not in response["data"]:
            await gte_cmd.finish("暂无可用兑换码，请稍后再试")
            return

        # 获取活动码列表
        codes = response["data"]["list"]
        if not codes:
            await gte_cmd.finish("当前没有可用的兑换码")
            return

        # 构建回复消息
        reply_msg = ""

        # 最多显示5个最新的活动码
        for i, code in enumerate(codes[:8]):
            title = code.get("title", "未知活动")
            desc = code.get("desc", "无描述")
            created_at = code.get("created_at", "").replace("T", " ").replace("Z", "")
            reply_msg += f"{i + 1}. 奖励: {desc}\n   兑换码: {title}\n   创建时间: {created_at}\n\n"

        # 发送消息
        await gte_cmd.finish(reply_msg)
    except Exception as e:
        print(e)


# 查询日常
gte_cmd = on_regex(r"^\s*日常\s*$", priority=5)
@gte_cmd.handle()
async def handle_gte(event: GroupMessageEvent):
    try:
        gid = str(event.group_id)
        cfg = load_groups()

        # 检查群组配置
        if gid not in cfg:
            await gte_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

        # 获取绑定的服务器
        server = ""
        if isinstance(cfg[gid], dict) and "servers" in cfg[gid]:
            server = cfg[gid]["servers"]
        elif isinstance(cfg[gid], list) and cfg[gid]:
            server = cfg[gid][0]

        if not server:
            await gte_cmd.finish("未找到绑定的服务器")

        # 获取特定服务器的GTE数据
        gte_data = await get_gte_data(url=calendar_URL,server=server)
        if not gte_data:
            await gte_cmd.finish(f"获取服务器 {server} 的日常数据失败")

        # 格式化并发送消息
        message = format_gte_message(gte_data)
        await gte_cmd.finish(message)
    except Exception as e:
        print(f"查询出错: {e}")


# 主动查询开服
gtekf_cmd = on_regex(r"^\s*开服\s*$", priority=5)
@gtekf_cmd.handle()
async def handle_gte(event: GroupMessageEvent):
    try:
        gid = str(event.group_id)
        cfg = load_groups()

        # 检查群组配置
        if gid not in cfg:
            await gtekf_cmd.send("请先绑定服务器，如: /绑定 梦江南")
            return

        # 获取绑定的服务器
        server = ""
        if isinstance(cfg[gid], dict) and "servers" in cfg[gid]:
            server = cfg[gid]["servers"]
        elif isinstance(cfg[gid], list) and cfg[gid]:
            server = cfg[gid][0]

        if not server:
            await gtekf_cmd.send("未找到绑定的服务器")
            return

        # 从API获取当前服务器最新状态
        gte_data = await get_gte_data(url="https://www.jx3api.com/data/server/status", server=server)
        if not gte_data or "data" not in gte_data:
            await gtekf_cmd.send(f"获取服务器 {server} 的开服数据失败")
            return

        # 解析API返回的服务器数据
        server_data = gte_data["data"]
        api_time = gte_data.get("time", int(time.time()))

        # 直接使用API返回的实时状态
        real_time_status = server_data.get("status", "未知")

        # 格式化区服名称
        zone = server_data["zone"]
        if zone.endswith("区"):
            zone = zone[:-1] + "大区"

        # 从缓存读取状态历史记录
        status_history = CacheManager.load_cache("status_history", {})

        # 确保服务器在历史记录中
        if server not in status_history:
            status_history[server] = {
                "last_maintenance": None,
                "last_open": None
            }

        # 获取历史开服和维护时间
        last_maintenance_time = status_history[server].get("last_maintenance")
        last_open_time = status_history[server].get("last_open")

        # 格式化时间显示
        maintenance_time_str = "无记录" if last_maintenance_time is None else format_time(last_maintenance_time)
        open_time_str = "无记录" if last_open_time is None else format_time(last_open_time)

        # 获取版本号
        try:
            banben = await get_server_banben()
            banben = extract_version(banben)
        except Exception as e:
            print(f"获取版本号出错: {e}")
            banben = "未知"

        if real_time_status != "维护":  # 开服状态
            message = (
                f"{zone}：{server}「 已开服 」\n"
                f"当前状态：{real_time_status}\n"
                f"开服时间：{open_time_str}\n"
                f"维护时间：{maintenance_time_str}"
            )
        else:  # 维护状态
            message = (
                f"{zone}：{server}「 维护中 」\n"
                f"维护时间：{maintenance_time_str}\n"
                f"上次开服：{open_time_str}"
            )

        # 添加版本信息
        if banben != "未知":
            message += f"\n最新版本：{banben}"

        # 发送消息
        await gtekf_cmd.send(message)

    except Exception as e:
        print(f"查询开服信息出错: {e}")
        await gtekf_cmd.send(f"查询服务器状态时出错，请联系管理员")

# 开服推送命令
kftoggle_cmd = on_command("开服推送", priority=5)
@kftoggle_cmd.handle()
async def kfhandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = load_groups()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await kftoggle_cmd.finish("用法: /开服推送 开启/关闭")

    # 确保群组已绑定服务器
    if gid not in cfg:
        await kftoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    # 处理现有配置
    if isinstance(cfg[gid], list):
        # 旧格式转换
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "开服推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        # 处理只有开关没有服务器的情况
        servers = []
        for key in cfg[gid]:
            if key != "开服推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "开服推送": cfg[gid].get("开服推送", True)}

    # 设置推送状态
    if status == "开启":
        cfg[gid]["开服推送"] = True
        save_groups(cfg)
        await kftoggle_cmd.finish("已开启本群开服推送功能")
    elif status == "关闭":
        cfg[gid]["开服推送"] = False
        save_groups(cfg)
        await kftoggle_cmd.finish("已关闭本群开服推送功能")
    else:
        await kftoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")

# 新闻推送命令
xwtoggle_cmd = on_command("新闻推送", priority=5)
@xwtoggle_cmd.handle()
async def xwhandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = load_groups()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await xwtoggle_cmd.finish("用法: /新闻推送 开启/关闭")

    # 确保群组已绑定服务器
    if gid not in cfg:
        await xwtoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    # 处理现有配置
    if isinstance(cfg[gid], list):
        # 旧格式转换
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "新闻推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        # 处理只有开关没有服务器的情况
        servers = []
        for key in cfg[gid]:
            if key != "新闻推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "新闻推送": cfg[gid].get("新闻推送", True)}

    # 设置推送状态
    if status == "开启":
        cfg[gid]["新闻推送"] = True
        save_groups(cfg)
        await xwtoggle_cmd.finish("已开启本群新闻推送功能")
    elif status == "关闭":
        cfg[gid]["新闻推送"] = False
        save_groups(cfg)
        await xwtoggle_cmd.finish("已关闭本群新闻推送功能")
    else:
        await xwtoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")

# 魔盒福利推送命令
xwtoggle_cmd = on_command("福利推送", priority=5)
@xwtoggle_cmd.handle()
async def xwhandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = load_groups()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await xwtoggle_cmd.finish("用法: /福利推送 开启/关闭")

    # 确保群组已绑定服务器
    if gid not in cfg:
        await xwtoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    # 处理现有配置
    if isinstance(cfg[gid], list):
        # 旧格式转换
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "福利推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        # 处理只有开关没有服务器的情况
        servers = []
        for key in cfg[gid]:
            if key != "福利推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "福利推送": cfg[gid].get("福利推送", True)}

    # 设置推送状态
    if status == "开启":
        cfg[gid]["福利推送"] = True
        save_groups(cfg)
        await xwtoggle_cmd.finish("已开启本群福利推送功能")
    elif status == "关闭":
        cfg[gid]["福利推送"] = False
        save_groups(cfg)
        await xwtoggle_cmd.finish("已关闭本群福利推送功能")
    else:
        await xwtoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")

# 技改推送命令
jgtoggle_cmd = on_command("技改推送", priority=5)
@jgtoggle_cmd.handle()
async def jghandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = load_groups()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await jgtoggle_cmd.finish("用法: /技改推送 开启/关闭")

    # 确保群组已绑定服务器
    if gid not in cfg:
        await jgtoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    # 处理现有配置
    if isinstance(cfg[gid], list):
        # 旧格式转换
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "技改推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        # 处理只有开关没有服务器的情况
        servers = []
        for key in cfg[gid]:
            if key != "技改推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "技改推送": cfg[gid].get("技改推送", True)}

    # 设置推送状态
    if status == "开启":
        cfg[gid]["技改推送"] = True
        save_groups(cfg)
        await jgtoggle_cmd.finish("已开启本群技改推送功能")
    elif status == "关闭":
        cfg[gid]["技改推送"] = False
        save_groups(cfg)
        await jgtoggle_cmd.finish("已关闭本群技改推送功能")
    else:
        await jgtoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


# 日常推送命令
rctoggle_cmd = on_command("日常推送", priority=5)
@rctoggle_cmd.handle()
async def rchandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = load_groups()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await rctoggle_cmd.finish("用法: /日常推送 开启/关闭")

    # 确保群组已绑定服务器
    if gid not in cfg:
        await rctoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    # 处理现有配置
    if isinstance(cfg[gid], list):
        # 旧格式转换
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "日常推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        # 处理只有开关没有服务器的情况
        servers = []
        for key in cfg[gid]:
            if key != "日常推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "日常推送": cfg[gid].get("日常推送", True)}

    # 设置推送状态
    if status == "开启":
        cfg[gid]["日常推送"] = True
        save_groups(cfg)
        await rctoggle_cmd.finish("已开启本群日常推送功能")
    elif status == "关闭":
        cfg[gid]["日常推送"] = False
        save_groups(cfg)
        await rctoggle_cmd.finish("已关闭本群日常推送功能")
    else:
        await rctoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")

# 竞技排名推送命令
jjctoggle_cmd = on_command("竞技排名推送", priority=5)
@jjctoggle_cmd.handle()
async def jjchandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = load_groups()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await jjctoggle_cmd.finish("用法: /竞技排名推送 开启/关闭")

    if gid not in cfg:
        await jjctoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    if isinstance(cfg[gid], list):
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "竞技排名推送": False}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        servers = []
        for key in cfg[gid]:
            if key not in {"开服推送", "新闻推送", "技改推送", "福利推送", "日常推送", "竞技排名推送"}:
                servers.append(key)
        cfg[gid] = {
            "servers": servers,
            "竞技排名推送": cfg[gid].get("竞技排名推送", False)
        }

    if isinstance(cfg[gid], dict) and "竞技排名推送" not in cfg[gid]:
        cfg[gid]["竞技排名推送"] = False

    if status == "开启":
        cfg[gid]["竞技排名推送"] = True
        save_groups(cfg)
        await jjctoggle_cmd.finish("已开启本群竞技排名推送功能")
    elif status == "关闭":
        cfg[gid]["竞技排名推送"] = False
        save_groups(cfg)
        await jjctoggle_cmd.finish("已关闭本群竞技排名推送功能")
    else:
        await jjctoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


bind_cmd = on_command("绑定", priority=5)
@bind_cmd.handle()
async def handle_bind(event: GroupMessageEvent, args=CommandArg()):
    server = args.extract_plain_text().strip()
    if not server: await bind_cmd.finish("用法: /绑定 服务器名")
    # 验证服务器存在
    data = await get_server_status()
    if data:
        server_exists = any(s.get("server") == server for s in data.get("data", []))
        if not server_exists:
            await bind_cmd.finish(f"服务器 {server} 不存在")
    cfg = load_groups()
    gid = str(event.group_id)
    # 绑定服务器并默认开启所有推送功能
    cfg[gid] = {
        "servers": server,
        "开服推送": True,
        "福利推送": True,
        "技改推送": True,
        "新闻推送": True,
        "日常推送": True,  # 也添加日常推送选项
        "竞技排名推送": False  # 默认关闭竞技排名推送
    }
    save_groups(cfg)
    await bind_cmd.finish(
        f"已绑定服务器: {server}\n"
        f"已默认开启：开服推送、福利推送、技改推送、新闻推送、日常推送\n"
        f"默认关闭：竞技排名推送，可使用「/竞技排名推送 开启」启用每日统计"
    )


unbind_cmd = on_command("解绑", aliases={"解除绑定"}, priority=5)


@unbind_cmd.handle()
async def handle_unbind(event: GroupMessageEvent):
    cfg = load_groups()
    gid = str(event.group_id)

    # 检查群组是否已绑定
    if gid not in cfg:
        await unbind_cmd.finish("当前群未绑定任何服务器")

    # 如果已绑定，获取服务器名以便在消息中显示
    server = cfg[gid].get("servers", "未知服务器")

    # 从配置中移除该群组
    del cfg[gid]
    save_groups(cfg)

    await unbind_cmd.finish(f"已解除与服务器 {server} 的绑定\n所有推送功能已关闭")

# 查看绑定命令
list_cmd = on_command("查看绑定", aliases={"服务器列表"}, priority=5)


@list_cmd.handle()
async def handle_list(event: GroupMessageEvent):
    gid = str(event.group_id)
    cfg = load_groups()

    # 检查群组配置
    if gid not in cfg:
        await list_cmd.finish("本群未绑定任何服务器")

    # 获取绑定信息
    config = cfg[gid]

    # 构建回复消息
    if isinstance(config, dict):
        server = config.get("servers", "无")

        # 获取各推送功能的状态
        server_push = "开启" if config.get("开服推送", False) else "关闭"
        news_push = "开启" if config.get("新闻推送", False) else "关闭"
        records_push = "开启" if config.get("技改推送", False) else "关闭"
        daily_push = "开启" if config.get("日常推送", False) else "关闭"
        welfare_push = "开启" if config.get("福利推送", False) else "关闭"
        ranking_push = "开启" if config.get("竞技排名推送", False) else "关闭"

        message = [
            f"绑定区服：{server}",
            f"开服推送：{server_push}",
            f"新闻推送：{news_push}",
            f"技改推送：{records_push}",
            f"日常推送：{daily_push}",
            f"福利推送：{welfare_push}",
            f"竞技排名推送：{ranking_push}",
        ]

        await list_cmd.finish("\n".join(message))
    else:
        # 旧格式处理
        servers = config if isinstance(config, list) else []
        if not servers:
            await list_cmd.finish("本群未绑定任何服务器")

        await list_cmd.finish(f"绑定服务器：{', '.join(servers)}\n(使用旧版格式，建议重新绑定)")




# 注册账号
# 注册命令
reg_cmd = on_command("注册", priority=5)
@reg_cmd.handle()
async def handle_register(bot: Bot, event: GroupMessageEvent):
    """处理注册命令"""
    user_id = str(event.user_id)  # 获取QQ号
    group_id = str(event.group_id)  # 获取群号

    # 在群里回复
    await reg_cmd.send("正在处理注册请求，请稍候...")

    # 使用QQ号作为用户名和邮箱
    username = f"qq{user_id}"
    email = f"{user_id}@qq.com"  # 将QQ号作为邮箱

    # 调用API注册账号
    success, result = await register_user(ADMIN_USERNAME, ADMIN_PASSWORD, username, email)

    if success:
        # 注册成功，发送私聊消息
        try:
            await bot.send_private_msg(
                user_id=int(user_id),
                message=(
                    f"恭喜，注册成功！以下是您的账号信息：\n"
                    f"用户名: {result.get('username')}\n"
                    f"密码: {result.get('password')}\n"
                    f"网站: {BASE_URL}\n"
                    f"云音乐服务器: ipv4.xohome.cn:88[https连接方式]\n"
                    f"若需使用自建云音乐，可从设置开启，建议b站找一找Navidrome的使用教程，连接上服务器在进行推送音乐！"
                )
            )

            # 在群里通知（不包含敏感信息）
            await reg_cmd.finish(f"注册成功！账号信息已通过私聊发送。")

        except Exception as e:
            print("注册成功")


    else:
        # 注册失败
        await reg_cmd.finish(result)


async def login_admin(admin_username, admin_password):
    """管理员登录获取token"""
    url = f"{BASE_URL}/api/login"

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                url,
                json={
                    "username": admin_username,
                    "password": admin_password
                },
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                return False, f"登录失败，状态码: {response.status_code}", None

            result = response.json()

            if result.get("code") == 200:
                return True, result.get("token"), result.get("user")
            else:
                return False, result.get("message", "登录失败"), None

    except Exception as e:

        return False, f"登录请求异常: {str(e)}", None


async def register_user(admin_username, admin_password, new_username, email):
    """调用API注册新用户"""
    # 登录获取token
    login_success, token, user_info = await login_admin(admin_username, admin_password)

    if not login_success:
        return False, f"网站挂了，等待重启恢复再注册！"

    # 检查管理员权限
    if not user_info or not user_info.get('is_admin', False):
        return False, "账号无管理员权限，无法邀请新用户"

    # 注册新用户
    url = f"{BASE_URL}/api/register"

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                url,
                json={
                    "username": new_username,
                    "email": email
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}"
                },
                cookies={
                    "token": token
                }
            )

            # 解析响应
            try:
                result = response.json()
            except Exception:
                result = {"code": response.status_code, "message": "无法解析服务器响应"}

            # 处理不同的状态码
            if response.status_code == 400:
                # 400状态码通常表示用户已存在
                return False, "该账号已注册，若您忘记密码可查看私聊或邮件！"
            elif response.status_code == 500:
                return False, "服务器内部错误，请稍后再试"
            elif response.status_code == 502 or response.status_code == 503 or response.status_code == 504:
                return False, "网站暂时连接不上，请稍后再试"
            elif response.status_code != 200:
                return False, f"注册失败，错误码: {response.status_code}"

            # 检查返回的code字段
            if result.get("code") == 200:
                return True, result.get("data")
            elif result.get("code") == 400:
                return False, "该账号已注册，若您忘记密码可查看私聊或邮件！"
            else:
                return False, result.get("message", "注册失败，未知错误")

    except httpx.ConnectTimeout:
        return False, "连接网站超时，请稍后再试"
    except httpx.ReadTimeout:
        return False, "读取网站响应超时，请稍后再试"
    except httpx.ConnectError:
        return False, "无法连接到网站，请检查网络或稍后再试"
    except Exception as e:
        return False, f"注册请求异常: {str(e)}"
# 启动初始化
@driver.on_startup
async def init():

    print(f"开服监控已启动，API: {STATUS_check_API} 延时{STATUS_check_time}分钟")
    print(f"新闻监控已启动，API: {NEWS_API_URL} 延时{NEWS_records_time}分钟")
    print(f"技改监控已启动，API: {SKILL_records_URL} 延时{NEWS_records_time}分钟")
    print(f"日常监控已启动，API: 每天{calendar_time}点推送")

# 启动完成
@driver.on_bot_connect
async def _on_bot_connect(bot: Bot):
    global BOT_INITIALIZED
    BOT_INITIALIZED = True
