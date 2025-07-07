from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment, Message, GroupMessageEvent
from nonebot import on_regex, on_command
from typing import Any, Annotated, Dict
from nonebot.params import RegexGroup, CommandArg, EventPlainText, Matcher
from jinja2 import Environment, FileSystemLoader, Template
from src.utils.defget import get, time_ago_filter, suijitext, jietu, time_ago_fenzhong, timestamp_jjc, jjcdaxiaoxie,convert_number, jiaoyiget, mp_image, sum_specified_keys, get_image, idget, jx3web,download_json
import time
import random
import asyncio
import aiohttp
from typing import List, Dict, Any, Tuple
import os
import json
import aiofiles  # 需要先安装: pip install aiofiles
from datetime import datetime
from nonebot.plugin import require
from src.utils.shared_data import user_sessions,SEARCH_RESULTS

# 导入配置文件
from config import TOKEN, TICKET, API_URLS, DEFAULT_SERVER, SESSION_TIMEOUT, REGEX_PATTERNS,NEWS_API_URL,SKILL_records_URL,IMAGE_CACHE_DIR

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
# 从配置文件中获取API URL
烟花查询 = API_URLS["烟花查询"]
奇遇查询 = API_URLS["奇遇查询"]
装备查询 = API_URLS["装备查询"]
竞技查询 = API_URLS["竞技查询"]
副本查询 = API_URLS["副本查询"]
名片查询 = API_URLS["名片查询"]
资历查询 = API_URLS["资历查询"]
百战查询 = API_URLS["百战查询"]
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


# 保存状态到文件，确保重启后不丢失信息
def save_status():
    try:
        with open(BOT_STATUS["status_file"], "w") as f:
            for key, value in BOT_STATUS.items():
                if key != "status_file":  # 不保存文件路径
                    f.write(f"{key}={value}\n")
    except Exception as e:
        print(f"保存状态失败: {e}")


# 从文件加载状态
def load_status():
    if not os.path.exists(BOT_STATUS["status_file"]):
        return

    try:
        with open(BOT_STATUS["status_file"], "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key in BOT_STATUS:
                        BOT_STATUS[key] = float(value)
    except Exception as e:
        print(f"加载状态失败: {e}")


# 使用驱动器的启动事件
@driver.on_startup
async def startup_handler():
    # 加载以前的状态
    load_status()

    # 记录当前启动时间
    BOT_STATUS["startup_time"] = time.time()
    save_status()

    print(f"机器人启动于 {datetime.fromtimestamp(BOT_STATUS['startup_time']).strftime('%Y-%m-%d %H:%M:%S')}")


# 使用驱动器的连接事件
@driver.on_bot_connect
async def connect_handler(bot: Bot):
    # 记录连接时间和增加连接计数
    BOT_STATUS["last_connect_time"] = time.time()
    BOT_STATUS["connection_count"] += 1
    save_status()

    print(f"机器人已连接，这是第 {int(BOT_STATUS['connection_count'])} 次连接")


# 使用驱动器的断开连接事件
@driver.on_bot_disconnect
async def disconnect_handler(bot: Bot):
    # 记录离线时间
    now = time.time()
    BOT_STATUS["last_offline_time"] = now

    # 计算离线持续时间（如果曾经连接过）
    if BOT_STATUS["last_connect_time"] > 0:
        BOT_STATUS["offline_duration"] = now - BOT_STATUS["last_connect_time"]

    save_status()

    print(f"机器人已断开连接于 {datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')}")


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
#将骗子查询结果格式化为回复消息
def format_scammer_reply(data):
    """
    将骗子查询结果格式化为回复消息

    Args:
        data: API返回的数据

    Returns:
        str: 格式化后的回复消息
    """
    if data['code'] != 200 or 'data' not in data or 'records' not in data['data'] or not data['data']['records']:
        return "未查询到相关骗子信息，该接口只能查剑网三相关的，别的不如百度请慎用！"

    records = data['data']['records']

    # 构建回复文本
    reply = "⚠️ 查询到骗子记录 ⚠️\n"
    reply += "------------------------\n"

    for i, record in enumerate(records, 1):
        server = record['server']
        tieba = record['tieba']

        reply += f"来源{i}: {tieba} ({server})\n"

        for j, item in enumerate(record['data'], 1):
            title = item['title']
            url = item['url']
            text = item['text'].replace('\n', ' ')

            # 将时间戳转换为可读时间
            import time
            time_str = time.strftime("%Y-%m-%d", time.localtime(item['time']))

            reply += f"• 标题: {title}\n"
            reply += f"• 内容: {text}\n"
            reply += f"• 时间: {time_str}\n"
            reply += f"• 链接: {url}\n"

            if j < len(record['data']):
                reply += "--------------------\n"

        if i < len(records):
            reply += "========================\n"

    reply += "\n⚠️ 请注意防范诈骗，谨慎交易 ⚠️"

    return reply

#将科举查询结果格式化为回复消息
def format_questions_reply(response):
    """
    将问题查询结果格式化为回复消息
    """
    # 打印输入值，帮助调试


    # 检查响应是否为None
    if response is None:
        return "错误：未收到数据"

    # 初始化回复文本
    reply = ""

    try:
        # 检查状态码
        code = response.get('code')
        msg = response.get('msg', '')

        # 如果状态码不是200或msg不是success，则显示错误信息
        if code != 200 or msg.lower() != 'success':
            reply += f"请求状态码：{code}\n"
            reply += f"状态：{msg}\n"
            return reply + "请求失败，请稍后再试"

        # 检查数据是否存在
        if 'data' not in response or not response['data']:
            return "没有找到题目数据"

        # 题目总数
        questions = response['data']
        reply += f"找到 {len(questions)} 道题目\n"

        # 遍历所有题目
        for i, question in enumerate(questions, 1):
            q_id = question.get('id', '未知ID')
            q_text = question.get('question', '未知问题')
            q_answer = question.get('answer', '未知答案')
            q_correctness = question.get('correctness')

            # 显示正确性状态
            if q_correctness == 1:
                status = "✓ 正确"
            elif q_correctness == 0:
                status = "✗ 错误"
            else:
                status = "- 未知"

            reply += f"{i}. 题目ID: {q_id}\n"
            reply += f"   问题: {q_text}\n"
            reply += f"   答案: {q_answer}\n"
            reply += f"   状态: {status}\n"

            # 除了最后一个题目，每个题目后添加分隔线
            if i < len(questions):
                reply += "------------------------\n"

    except Exception as e:
        # 捕获所有异常，确保函数始终返回字符串
        print(f"处理响应时出错: {e}")
        return f"处理数据时出错: {str(e)}"


    return reply
# 群组配置简化函数
def load_groups():
    return json.load(open(GROUP_CONFIG_FILE, 'r', encoding='utf-8')) if os.path.exists(GROUP_CONFIG_FILE) else {}

# 使用示例 - 确保正确使用函数
def process_response(response_data):
    # 调用格式化函数
    formatted_text = format_questions_reply(response_data)

    # 检查返回值
    if formatted_text is None:
        print("警告: format_questions_reply 返回了 None")
        return "处理数据时出错"

    # 返回格式化文本
    return formatted_text


# 异步获取群绑定的服务器
async def get_server_by_group(group_id):
    """
    根据群ID获取绑定的服务器名称（异步版本）

    参数:
        group_id: 群组ID，可以是整数或字符串

    返回:
        str: 服务器名称，如果未找到则返回None
    """
    # 服务器绑定关系存储文件
    SERVER_BINDING_FILE = "groups.json"

    # 确保group_id是字符串类型
    group_id = str(group_id)

    # 检查文件是否存在
    if not os.path.exists(SERVER_BINDING_FILE):
        return None

    try:
        # 异步打开并读取绑定关系文件
        async with aiofiles.open(SERVER_BINDING_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            bindings = json.loads(content)

        # 返回对应的服务器名称，如果不存在则返回None
        return bindings.get(group_id).get("servers")
    except Exception as e:
        print(f"读取服务器绑定关系失败: {e}")
        return None





# 解析JSON  时间数据
def format_time(time_str):
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        month = dt.month
        day = dt.day
        hour = dt.hour
        minute = dt.minute

        # 构建格式化的时间字符串
        if minute == 0:
            return f"{month}月{day}日 {hour}点"
        else:
            return f"{month}月{day}日 {hour}点{minute}分"
    except:
        return time_str



# 解析技改JSON数据，返回最新的相关公告列表
def parse_updates(data, keyword) -> List[Dict[str, str]]:
    try:
        # 解析JSON数据
        if isinstance(data, str):
            data = json.loads(data)
        elif not isinstance(data, dict):
            return []

        # 检查响应状态
        if data.get("code") != 200:
            return []

        # 获取数据列表
        items = data.get("data", [])

        # 筛选包含关键词的条目
        filtered_items = [item for item in items if keyword in item.get("title", "")]

        if not filtered_items:
            return []

        # 将时间字符串转换为datetime对象用于排序
        for item in filtered_items:
            item["datetime"] = datetime.strptime(item["time"], "%Y-%m-%d %H:%M:%S")

        # 按时间降序排序
        filtered_items.sort(key=lambda x: x["datetime"], reverse=True)

        # 获取最新的时间
        latest_time = filtered_items[0]["datetime"]

        # 筛选出时间相同且是最新的条目
        latest_items = [
            {"id": item["id"], "url": item["url"], "title": item["title"], "time": item["time"]}
            for item in filtered_items if item["datetime"] == latest_time
        ]

        return latest_items
    except Exception as e:
        print(f"解析出错: {str(e)}")
        return []

# 解析新闻活动JSON数据，返回最新的相关公告列表
def parse_updateshuodong(data, keyword) -> List[Dict[str, str]]:
    try:
        # 解析JSON数据
        if isinstance(data, str):
            data = json.loads(data)
        elif not isinstance(data, dict):
            return []

        # 检查响应状态
        if data.get("code") != 200:
            return []

        # 获取数据列表
        items = data.get("data", [])

        # 筛选包含关键词的条目
        filtered_items = [item for item in items if keyword in item.get("title", "")]

        if not filtered_items:
            return []

        # 处理日期格式，尝试根据id或token排序
        try:
            # 尝试按id或token降序排序（通常更大的id/token表示更新的内容）
            if "id" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["id"]), reverse=True)
            elif "token" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["token"]), reverse=True)
        except:
            pass  # 排序失败时不做处理

        # 提取前3条不同title的记录
        unique_titles = set()
        latest_items = []

        for item in filtered_items:
            title = item.get("title", "")

            # 如果标题不在已收集的集合中，添加这条记录
            if title not in unique_titles:
                unique_titles.add(title)
                latest_items.append(item)

            # 收集到3条不同标题的记录后结束
            if len(latest_items) >= 3:
                break

        # 格式化结果
        result_items = []
        for item in latest_items:
            result_items.append({
                "id": str(item.get("id", item.get("token", ""))),
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "time": item.get("date", "")
            })

        return result_items
    except Exception as e:
        print(f"解析出错: {str(e)}")
        return []
# 解析新闻JSON数据，返回最新的相关公告列表
def parse_updatesnew(data, keyword) -> List[Dict[str, str]]:
    try:
        # 解析JSON数据
        if isinstance(data, str):
            data = json.loads(data)
        elif not isinstance(data, dict):
            return []

        # 检查响应状态
        if data.get("code") != 200:
            return []

        # 获取数据列表
        items = data.get("data", [])

        # 筛选包含关键词的条目
        filtered_items = [item for item in items if keyword in item.get("title", "")]

        if not filtered_items:
            return []

        # 处理日期格式，尝试根据id或token排序
        try:
            # 尝试按id或token降序排序（通常更大的id/token表示更新的内容）
            if "id" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["id"]), reverse=True)
            elif "token" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["token"]), reverse=True)
        except:
            pass  # 排序失败时不做处理

        # 获取第一条记录的id/token（假设排序后第一条是最新的）
        latest_id = filtered_items[0].get("id") if "id" in filtered_items[0] else filtered_items[0].get("token")

        # 筛选具有相同id/token的记录（应该只有一条，但为了安全）
        if "id" in filtered_items[0]:
            latest_items = [item for item in filtered_items if item["id"] == latest_id]
        else:
            latest_items = [item for item in filtered_items if item["token"] == latest_id]

        # 如果上面的筛选失败，就取第一条记录
        if not latest_items:
            latest_items = [filtered_items[0]]

        # 格式化结果
        result_items = []
        for item in latest_items:
            result_items.append({
                "id": str(item.get("id", item.get("token", ""))),
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "time": item.get("date", "")
            })

        return result_items
    except Exception as e:
        print(f"解析出错: {str(e)}")
        return []


@huodong.handle()
async def huodong(bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]):
    try:
        # 获取数据
        data = await jiaoyiget(f"https://www.jx3api.com/data/news/allnews?limit=50")
        records = parse_updateshuodong(data,keyword="活动")


        if not records:
            await bot.send(event, f"未找活动相关公告")
            return

        # 构建响应消息
        msg_parts = [f"【活动更新公告】"]

        for i, record in enumerate(records):
            formatted_time = format_time(record['time'])

            msg_parts.append(f"{i + 1}. {record['title']}")
            msg_parts.append(f"   发布时间: {formatted_time}")
            msg_parts.append(f"   查看原文: {record['url']}")
            if i < len(records) - 1:
                msg_parts.append("─────────────")

        # 发送消息
        await bot.send(event, "\n".join(msg_parts))

    except Exception as e:
        await bot.send(event, f"获取活动相关公告失败: {str(e)[:100]}")

@gengxin.handle()
async def gengxin(bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]):
    try:
        # 获取数据
        data = await jiaoyiget(f"https://www.jx3api.com/data/news/announce?limit=5")
        records = parse_updatesnew(data,keyword="版本")


        if not records:
            await bot.send(event, f"未找到版本更新公告")
            return

        # 构建响应消息
        msg_parts = [f"【版本更新公告】"]

        for i, record in enumerate(records):
            formatted_time = format_time(record['time'])

            msg_parts.append(f"{i + 1}. {record['title']}")
            msg_parts.append(f"   发布时间: {formatted_time}")
            msg_parts.append(f"   查看原文: {record['url']}")
            if i < len(records) - 1:
                msg_parts.append("─────────────")

        # 发送消息
        await bot.send(event, "\n".join(msg_parts))

    except Exception as e:
        await bot.send(event, f"版本更新公告失败: {str(e)[:100]}")

@jigai.handle()
async def jigai(bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]):
    try:
        # 获取数据
        data = await jiaoyiget(SKILL_records_URL)
        records = parse_updates(data,keyword="武学")

        if not records:
            await bot.send(event, f"未找到最新的武学调整公告")
            return

        # 构建响应消息
        msg_parts = [f"【最新武学调整】"]

        for i, record in enumerate(records):
            formatted_time = format_time(record['time'])

            msg_parts.append(f"{i + 1}. {record['title']}")
            msg_parts.append(f"   发布时间: {formatted_time}")
            msg_parts.append(f"   查看原文: {record['url']}")
            if i < len(records) - 1:
                msg_parts.append("─────────────")

        # 发送消息
        await bot.send(event, "\n".join(msg_parts))

    except Exception as e:
        await bot.send(event, f"获取武学调整信息失败: {str(e)[:100]}")









# 查看帮助命令
help_cmd = on_regex(r"^帮助", priority=5)
@help_cmd.handle()
async def handle_help(bot: Bot, event: GroupMessageEvent):
    gid = str(event.group_id)

    try:
        cfg = load_groups()

        # 检查群组是否存在于配置中
        if gid not in cfg:
            await help_cmd.finish("本群未绑定任何服务器")

        # 获取绑定信息
        config = cfg[gid]

        # 获取群信息
        group_info = await bot.get_group_info(group_id=event.group_id)
        group_name = group_info.get("group_name", "未知群名")
        group_avatar_url = f"http://p.qlogo.cn/gh/{event.group_id}/{event.group_id}/100"
        # 计算当前运行时间
        now = time.time()
        uptime = now - BOT_STATUS["startup_time"]
        uptime_str = format_time_duration(uptime)

        # 获取启动时间的可读形式
        startup_time_str = datetime.fromtimestamp(BOT_STATUS["startup_time"]).strftime('%Y-%m-%d')

        # 获取上次离线时间的可读形式
        last_offline = BOT_STATUS["last_offline_time"]
        if last_offline > 0:
            last_offline_str = datetime.fromtimestamp(last_offline).strftime('%Y-%m-%d')
            offline_duration_str = format_time_duration(BOT_STATUS["offline_duration"])
        else:
            last_offline_str = "无记录"
            offline_duration_str = "无记录"
        # 获取服务器信息
        server = config.get("servers", "无")
        if not server:
            await help_cmd.finish("本群未绑定任何服务器")

        # 获取各推送功能的状态
        server_push = "开启" if config.get("开服推送", False) else "关闭"
        news_push = "开启" if config.get("新闻推送", False) else "关闭"
        records_push = "开启" if config.get("技改推送", False) else "关闭"
        daily_push = "开启" if config.get("日常推送", False) else "关闭"

        # 渲染HTML模板
        template = env.get_template('qun.html')
        html_content = template.render(
            server=server,
            server_push=server_push,
            news_push=news_push,
            records_push=records_push,
            daily_push=daily_push,
            group_name = group_name,
            group_avatar_url=group_avatar_url,
            startup_time=startup_time_str,
            uptime=uptime_str,
            connection_count=int(BOT_STATUS["connection_count"]),
            last_offline=last_offline_str,
            offline_duration=offline_duration_str,
            last_connect=datetime.fromtimestamp(BOT_STATUS["last_connect_time"]).strftime('%Y-%m-%d')
        )


        image_bytes = await jietu(html_content, 810, "ck")

        # 发送结果
        await bot.send(
            event,
            MessageSegment.at(event.user_id) +
            Message("   查询结果") +
            MessageSegment.image(image_bytes)
        )

    except Exception as e:
        await help_cmd.finish(f"获取帮助信息失败：{str(e)}")













@keju.handle()
async def keju(bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]):
    qqidtieba = foo[0]

    data = await jiaoyiget(f"https://www.jx3api.com/data/exam/answer?subject={qqidtieba}&limit=20")

    check_question = format_questions_reply(data)

    await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n{check_question}"))












@pianzi.handle()
async def pianzi(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    qqidtieba=foo[0]
    if qqidtieba.isdigit():
       if len(qqidtieba) >= 5:

           data =  await get(f"https://www.jx3api.com/data/fraud/detailed?uid={qqidtieba}",token=TOKEN)
           if data['code'] != 200:
               formatted_reply = format_scammer_reply(data)
               await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n{formatted_reply}"))
           else:
               await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n服务器访"))



    else:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请正确输入要查询的QQ号码"))


@baizhan.handle()
async def baizhan_to_image(bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]):
    import os
    import time

    # 检查本地图片文件目录
    image_dir = "data/baizhan_images"
    os.makedirs(image_dir, exist_ok=True)

    # 获取当前时间戳
    current_timestamp = int(time.time())

    # 尝试查找本地图片
    image_path = os.path.join(image_dir, "baizhan_latest.png")
    data_path = os.path.join(image_dir, "baizhan_data.json")

    # 检查是否有本地数据和图片
    use_local = False
    if os.path.exists(data_path) and os.path.exists(image_path):
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                end_timestamp = local_data.get("end_timestamp", 0)

                # 如果本地图片未过期，直接使用
                if end_timestamp > current_timestamp:
                    use_local = True
                    with open(image_path, "rb") as img_file:
                        image_bytes = img_file.read()
                    await bot.send(event,
                                   MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
                                       image_bytes))
        except Exception as e:
            print(f"读取本地数据出错: {e}")
            use_local = False

    # 如果没有本地数据或已过期，则请求新数据
    if not use_local:

        items = await get("https://www.jx3api.com/data/active/monster",token=TOKEN)

        if items["msg"] == "success":
            def parse_baizhan_data(json_data):
                """
                批量解析百战异闻录JSON数据，提取所有条目信息

                参数:
                    json_data: 字符串或已解析的字典

                返回:
                    包含解析结果的字典
                """
                # 检查输入类型并解析JSON
                if isinstance(json_data, str):
                    data = json.loads(json_data)
                elif isinstance(json_data, dict):
                    data = json_data
                else:
                    raise TypeError("输入必须是JSON字符串或字典")

                # 提取并格式化开始和结束时间
                start_timestamp = data["data"]["start"]
                end_timestamp = data["data"]["end"]
                start_date = datetime.fromtimestamp(start_timestamp).strftime("%m/%d")
                end_date = datetime.fromtimestamp(end_timestamp).strftime("%m/%d")

                # 所有条目的结果列表
                all_items = []

                # 遍历所有条目
                for item in data["data"]["data"]:
                    item_result = {
                        "level": item["level"],
                        "name": item["name"],
                        "skill": item["skill"],
                        "list_result": False,
                        "list_items": {}
                    }

                    # 检查list是否为空
                    if "data" in item and "list" in item["data"]:
                        item_list = item["data"]["list"]
                        if item_list and len(item_list) > 0:
                            item_result["list_result"] = True

                            # 提取list中的特定项
                            if len(item_list) > 0:
                                item_result["list_items"]["list_0"] = item_list[0]
                            if len(item_list) > 1:
                                item_result["list_items"]["list_1"] = item_list[1]

                    # 添加描述信息
                    if "data" in item and "desc" in item["data"]:
                        item_result["desc"] = item["data"]["desc"]

                    # 将当前条目添加到结果列表
                    all_items.append(item_result)

                # 返回完整结果，加上原始时间戳
                return {
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_timestamp": start_timestamp,
                    "end_timestamp": end_timestamp,
                    "total_items": len(all_items),
                    "items": all_items
                }

            result = parse_baizhan_data(items)

            # 保存解析数据到本地
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump({
                    "start_timestamp": result.get("start_timestamp"),
                    "end_timestamp": result.get("end_timestamp"),
                    "result": result
                }, f, ensure_ascii=False)
            text = suijitext()
            template = env.get_template('百战查询.html')
            html_content = template.render(
                start_date=result["start_date"],
                end_date=result["end_date"],
                items=result["items"],
                text=text
            )

            image_bytes = await jietu(html_content, 980, "ck")

            # 保存图片到本地
            with open(image_path, "wb") as f:
                f.write(image_bytes)

            await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
                image_bytes))
        else:
            if items["code"] == 406:
                await bot.send(event,
                               MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
            else:
                items = items["msg"]
                await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))


@yanhua.handle()
async def yanhua_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return

    items = await get(
        url=烟花查询,
        server=qufu,
        name=id,
        token=TOKEN,

    )








    if items["msg"] == "success":
        zcslist = len(items['data'])
        csid = sum(1 for item in items['data'] if item['sender'] == f'{id}')
        jieshou = zcslist - csid
        items = items["data"]
        env.filters['time'] = time_ago_filter
        template = env.get_template('烟花查询.html')
        text = suijitext()
        html_content = template.render(items=items, id=id,zcslist=zcslist,csid=csid,jieshou=jieshou,text=text,qufu=qufu)

        image_bytes = await jietu(html_content, 1194,"ck")
        await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
            image_bytes))
    else:
        if items["code"] == 406:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
        else:
            items = items["msg"]
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))

@qiyu.handle()
async def qiyu_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return
    items = await get(
        url=奇遇查询,
        server=qufu,
        name=id,
        token=TOKEN,
        ticket=TICKET,
    )


    if items["msg"] == "success":
        zcslist = len(items['data'])
        ptqiyu = sum(1 for item in items['data'] if item['level'] == 1)
        jsqiyu = sum(1 for item in items['data'] if item['level'] == 2)
        cwqiyu = sum(1 for item in items['data'] if item['level'] == 3)
        items = items["data"]
        env.filters['time'] = time_ago_fenzhong
        env.filters['timejjc'] = timestamp_jjc
        text = suijitext()
        template = env.get_template('奇遇查询.html')
        html_content = template.render(items=items, id=id,qufu=qufu,zcslist=zcslist,ptqiyu=ptqiyu,jsqiyu=jsqiyu,cwqiyu=cwqiyu,text=text)
        image_bytes = await jietu(html_content, 870,"ck")
        await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
            image_bytes))
    else:
        if items["code"] == 406:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
        else:
            items = items["msg"]
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))


@zhuangfen.handle()
async def zhuangfen_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return
    items = await get(
        url=装备查询,
        server=qufu,
        name=id,
        token=TOKEN,
        ticket=TICKET,
    )


    if items["msg"] == "success":
        menpai = items.get('data', {}).get('panelList', {}).get('panel', [{}])[0].get('name')
        items = items["data"]
        text = suijitext()
        newpng = "名片"
        mpimg = await get_image(qufu, id)







        template = env.get_template('装备查询.html')
        html_content = template.render(items=items, id=id, qufu=qufu, newpng=newpng, text=text,mpimg=mpimg, menpai=menpai)
        image_bytes = await jietu(html_content, 1119,1300)
        await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
            image_bytes))
    else:
        if items["code"] == 406:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
        else:
            items = items["msg"]
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))

@jjc.handle()
async def jjc_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return
    items = await get(
        url=竞技查询,
        server=qufu,
        name=id,
        token=TOKEN,
        ticket=TICKET,
    )


    if items["msg"] == "success":
        items = items["data"]


        if items["performance"]["2v2"] == [] and items["performance"]["3v3"] == [] and items["performance"]["5v5"] == []:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"  => 查询失败\n未找到，{qufu}，{id}，的jjc记录，等待api更新！"))
        else:
            text = suijitext()
            env.filters['time'] = time_ago_fenzhong
            env.filters['jjctime'] = jjcdaxiaoxie
            template = env.get_template('竞技查询.html')
            html_content = template.render(items=items, id=id, qufu=qufu, text=text)

            image_bytes = await jietu(html_content, 955, "ck")
            await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
                image_bytes))


    else:
        if items["code"] == 406:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
        else:
            items = items["msg"]
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))

@fuben.handle()
async def fuben_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return
    items = await get(
        url=副本查询,
        server=qufu,
        name=id,
        token=TOKEN,
        ticket=TICKET,
    )


    if items["msg"] == "success":
        items = items["data"]

        if items["data"] :
            text = suijitext()
            template = env.get_template('副本查询.html')
            html_content = template.render(items=items, id=id, qufu=qufu, text=text)

            image_bytes = await jietu(html_content, 800, "ck")
            await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
                image_bytes))

        else:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果: {qufu}，{id}，本周还没有清本！"))

    else:
        if items["code"] == 406:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
        else:
            items = items["msg"]
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))


@mingpian.handle()
async def mingpianxiu_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return
    mingpian = await get_image(qufu, id,free="1")

    if mingpian:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:"))
        current_iteration = 0  # 初始化计数器
        for item in mingpian:
            # 规范化路径格式
            item_path = os.path.abspath(item).replace('\\', '/')

            try:
                current_iteration += 1
                await bot.send(event,  Message(f"{qufu} / {id} / 第 {current_iteration} 张 名片")+ MessageSegment.image(f"file://{item_path}"))

            except Exception as e:
                await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   发送图片失败: {str(e)}"))
        items = await get(
            url=名片查询,
            server=qufu,
            name=id,
            token=TOKEN, )
        if items["msg"] == "success":
            items = items['data']
            urlmp = items['showAvatar']
            image_name = f"{qufu}-{id}-{items['showHash']}"
            img = await mp_image(url=urlmp, name=image_name)
            if img:  # 名片不存在追加
                await bot.send(event, Message(f"{qufu} / {id} / 当前名片 已缓存") + MessageSegment.image(img))

            else:
                return

        else:
            if items["code"] == 406:
                await bot.send(event,
                               MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
            else:
                items = items["msg"]
                await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))


    else:

        items = await get(url=名片查询, server=qufu,name=id,token=TOKEN)

        if items["msg"] == "success":

            items = items['data']

            urlmp = items['showAvatar']

            image_name = f"{qufu}-{id}-{items['showHash']}"

            img = await mp_image(urlmp, image_name)

            await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(

                img))



        else:

            if items["code"] == 406:

                await bot.send(event,

                               MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))

            else:

                items = items["msg"]

                await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))


@jiayi.handle()
async def jiayi_to_image(bot: Bot, event: Event,foo: Annotated[tuple[Any, ...], RegexGroup()]):
    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]

    else:
        id = foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return



    id = id.replace('[', '').replace(']', '').replace('&#91;', '').replace('&#93;', '').replace(" ", "")
    print("名称",id)
    jsonid = await jiaoyiget(url=f"http://node.jx3box.com/item_merged/name/{id}")


    if jsonid["total"] != 0:
        ico = jsonid['list'][0]['IconID']
        ico = f'http://icon.jx3box.com/icon/{ico}.png'

        id = jsonid['list'][0]['id']
        mz = jsonid['list'][0]['Name']
        Desc = None
        if 'list' in jsonid and isinstance(jsonid['list'], list) and len(jsonid['list']) > 0:
            first_item = jsonid['list'][0]
            if isinstance(first_item, dict):
                Desc = first_item.get('Desc', None)

        if Desc is not None:
            Desc = Desc.replace('<Text>text="', '').replace('\" font=105 </text>', '').replace(" ", "")








        newpm = await jiaoyiget(url=f"http://next2.jx3box.com/api/item-price/{id}/detail?server={qufu}")

        newpm = newpm.get('data', {}).get('prices', None)
        if newpm is not None:
            newpm = sorted(newpm, key=lambda item: item['n_count'], reverse=True)
        if newpm is None:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"  => 查询失败\n未找到交易行，{mz}，的价格，等待api更新！"))
        else:
            newxs = await jiaoyiget(url=f"http://next2.jx3box.com/api/item-price/{id}/logs?server={qufu}")
            if newxs is not None and \
                    'data' in newxs and newxs['data'] is not None and \
                    'logs' in newxs['data'] and isinstance(newxs['data']['logs'], list) and \
                    len(newxs['data']['logs']) > 0 and \
                    newxs['data']['logs'][0] is not None:
                newxs = newxs['data']['logs'][0]

            text = suijitext()
            env.filters['time'] = time_ago_fenzhong
            env.filters['timego'] = convert_number
            template = env.get_template('交易行查询.html')
            html_content = template.render(newpm=newpm, newxs=newxs, ico=ico, qufu=qufu, mz=mz, text=text, Desc=Desc)

            image_bytes = await jietu(html_content, 800, "ck")
            await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(
                image_bytes))
    else:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"  => 查询失败\n未找到，{id}\n1,大部分物品不支持模糊搜索!\n2,可以直接游戏复制不需要删除[]!"))


@zili.handle()
async def zili_to_image(bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]):
    # 删除万宝楼会话
    user_id = str(event.user_id)
    if user_id in SEARCH_RESULTS:
        del SEARCH_RESULTS[user_id]

    if foo[0] is None:
        qufu = foo[1]
        id = foo[2]
    else:
        id=foo[0]
        group_id = event.group_id
        qufu = await get_server_by_group(group_id)
        if qufu is None:
            # 可以在这里设置默认值或返回错误信息
            await bot.send(event, "本群未绑定服务器，请先绑定服务器或指定服务器名称")
            return
    
    if await idget(qufu) == False:
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n请输入正确的服务器！"))
        return
    items = await get(
        url=资历查询,
        server=qufu,
        name=id,
        token=TOKEN,
        ticket=TICKET,
        zili=3
    )



    if items["msg"] == "success":
        if items["data"]:
            itemss = items
            text = suijitext()
            tongji = [0, 0, 0, 0, 0, 0]
            tongji[5] = items["data"]["roleName"]
            items = items["data"]["data"]["total"]

            my_dict = {}  # 初始化一个空字典
            count = 0
            for i in range(2):
                count += 1  # 每次循环时增加计数器
                if count == 2:
                    xmldata = "maps"
                    xmlmz = "地图分布"
                else:
                    xmldata = "dungeons"
                    xmlmz = "秘境分布"
                result = sum_specified_keys(itemss["data"]["data"][xmldata], "pieces", "seniority")
                ydcj, wdcj, ydzl, wdzl = result
                jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0  # 避免除以零的错误
                my_dict[xmlmz] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
            for item in items.keys():
                result = sum_specified_keys(items[f"{item}"], "pieces", "seniority")
                ydcj, wdcj, ydzl, wdzl = result
                tongji[1] += ydcj
                tongji[2] += wdcj
                tongji[3] += ydzl
                tongji[4] += wdzl
                jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0  # 避免除以零的错误
                my_dict[f"{item}"] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}

            tongji[0] = round((tongji[3] / tongji[4]) * 100, 2)
            template = env.get_template('资历查询.html')
            html_content = template.render(text=text, tongji=tongji,qufu=qufu, items=my_dict)
            image_bytes = await jietu(html_content, 960, "ck")
            await bot.send(event, Message("   查询结果") + MessageSegment.image(
                image_bytes))
                
            # 在全局字典中保存用户数据，并设置30秒后过期时间
            user_id = str(event.user_id)
            expiry_time = time.time() + SESSION_TIMEOUT  # 30秒超时
            
            # 存储在全局字典中
            user_sessions[user_id] = {
                "expiry_time": expiry_time,
                "data": my_dict,
                "items": itemss,
                "nav_shown": False  # 添加导航显示标志，初始为False
            }
            
            # 首次显示导航提示
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目"))
            # 设置标志为已显示
            user_sessions[user_id]["nav_shown"] = True
        else:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果: {qufu}，{id}，难道根本没有资历？"))
    else:
        if items["code"] == 406:
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:406错误，推栏接口等待更新！"))
        else:
            items = items["msg"]
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"   查询结果:{items}"))

@zili_choice.handle()
async def handle_zili_choice(bot: Bot, event: Event, choice: Annotated[tuple[Any, ...], RegexGroup()]):
    user_id = str(event.user_id)
    
    # 检查用户是否有会话状态
    if user_id not in user_sessions:
        return

    # 删除万宝楼会话
    if user_id in SEARCH_RESULTS:
        del SEARCH_RESULTS[user_id]
    # 检查是否超时
    current_time = time.time()
    if current_time > user_sessions[user_id]["expiry_time"]:
        # 超时，删除会话
        del user_sessions[user_id]
        await bot.send(event, MessageSegment.at(event.user_id) + Message("   操作已超时，请重新输入资历 ID 查询"))
        return
    
    # 检查是否有特殊命令
    number = choice[0]
    if number == "返回" or number == "back":
        # 如果有导航路径并且不是在根目录，则返回上一级
        if "nav_path" in user_sessions[user_id] and len(user_sessions[user_id]["nav_path"]) > 0:
            user_sessions[user_id]["nav_path"].pop()  # 移除最后一个路径
            
            # 如果移除后路径为空，则显示初始数据
            if len(user_sessions[user_id]["nav_path"]) == 0:
                await display_zili_overview(bot, event, user_id)
            else:
                # 否则显示上一级的数据
                await navigate_to_path(bot, event, user_id)
            return
        else:
            await bot.send(event, Message("   已经在顶层目录，无法返回上一级"))
            return
    elif number == "0" or number == "home":
        await bot.send(event, Message("已返回资历分布，请输入1-20选择要查看的项目！"))
        if "nav_path" in user_sessions[user_id]:
            user_sessions[user_id]["nav_path"] = []
        return

    try:
        index = int(number) - 1
        
        # 根据当前导航路径获取相应的数据
        current_data = get_current_data(user_id)
        
        # 检查索引是否有效
        keys = list(current_data.keys())
        if index >= len(keys) or index < 0:
            await bot.send(event, Message(f"   无效的选择，请输入1-{len(keys)}之间的数字"))
            return

        # 获取选择的项目
        selected_key = keys[index]
        selected_item = current_data[selected_key]

        # 检查选择项是否还有子项目
        items = user_sessions[user_id]["items"]
        has_subitems = False
        
        # 追踪当前导航路径
        if "nav_path" not in user_sessions[user_id]:
            user_sessions[user_id]["nav_path"] = []
        
        # 构建新的路径并检查是否有子项目
        if len(user_sessions[user_id]["nav_path"]) == 0:

            # 当在顶层目录时
            if selected_key == "秘境分布":
                items_data = items["data"]["data"]["dungeons"]
                # 检查dungeons数据是否为空
                has_valid_items = check_valid_items(items_data)
                if not has_valid_items:
                    await bot.send(event, Message(f"   {selected_key} 没有可用的子项目，无法进入"))
                    return
                has_subitems = True
            elif selected_key == "地图分布":
                # 顶层地图分布应该显示完整的列表，而不是单项详情
                items_data = items["data"]["data"]["maps"]
                # 构建地图分布的数据列表
                map_dict = {}
                for item in items_data.keys():
                    if isinstance(items_data[item], dict):
                        result = sum_specified_keys(items_data[item], "pieces", "seniority")
                        ydcj, wdcj, ydzl, wdzl = result
                        jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                        map_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
                
                # 计算总计数据
                tongji = [0, 0, 0, 0, 0, 0]
                tongji[5] = items["data"]["roleName"]
                for item in map_dict.values():
                    tongji[1] += item['ydcj']
                    tongji[2] += item['wdcj']
                    tongji[3] += item['ydzl']
                    tongji[4] += item['wdzl']
                tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

                # 渲染HTML并发送图片
                text = suijitext()
                template = env.get_template('资历查询.html')
                html_content = template.render(text=text, tongji=tongji, zilizonglan="地图分布", items=map_dict)
                image_bytes = await jietu(html_content, 1120, "ck")
                await bot.send(event, Message("   地图分布") + MessageSegment.image(image_bytes))
                
                # 添加条件，只在首次或用户请求时显示导航
                if not user_sessions[user_id].get("nav_shown", True):
                    # 显示首页导航信息（使用文字）
                    data_keys = list(user_sessions[user_id]["data"].keys())
                    nav_text = "   首页导航：\n"
                    for i, key in enumerate(data_keys, 1):
                        nav_text += f"   {i}. {key}\n"
                    nav_text += "   请输入数字选择要查看的项目"
                    await bot.send(event, Message(nav_text))
                    user_sessions[user_id]["nav_shown"] = True
                
                # 重置超时时间
                user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                return
            else:
                # 顶层的其他类别，获取total中的子项目并显示完整列表
                items_data = items["data"]["data"]["total"][selected_key]
                # 检查是否有可用的子项目
                has_valid_items = check_valid_items(items_data)
                if not has_valid_items:
                    # 如果没有子项目，则直接显示选中项的详情
                    await display_item_details(bot, event, user_id, selected_key, selected_item)
                    
                    # 添加条件，只在首次或用户请求时显示导航
                    if not user_sessions[user_id].get("nav_shown", True):
                        # 显示首页导航信息（使用文字）
                        data_keys = list(user_sessions[user_id]["data"].keys())
                        nav_text = "   首页导航：\n"
                        for i, key in enumerate(data_keys, 1):
                            nav_text += f"   {i}. {key}\n"
                        nav_text += "   请输入数字选择要查看的项目"
                        await bot.send(event, Message(nav_text))
                        user_sessions[user_id]["nav_shown"] = True
                    
                    # 重置超时时间
                    user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                    return
                    
                # 有子项目，构建数据列表
                sub_dict = {}
                for item in items_data.keys():
                    if isinstance(items_data[item], dict):
                        result = sum_specified_keys(items_data[item], "pieces", "seniority")
                        ydcj, wdcj, ydzl, wdzl = result
                        jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                        sub_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
                
                # 计算总计数据
                tongji = [0, 0, 0, 0, 0, 0]
                tongji[5] = items["data"]["roleName"]
                for item in sub_dict.values():
                    tongji[1] += item['ydcj']
                    tongji[2] += item['wdcj']
                    tongji[3] += item['ydzl']
                    tongji[4] += item['wdzl']
                tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
                
                # 渲染HTML并发送图片
                text = suijitext()
                template = env.get_template('资历查询.html')
                html_content = template.render(text=text, tongji=tongji, zilizonglan=selected_key, items=sub_dict)
                image_bytes = await jietu(html_content, 1120, "ck")
                await bot.send(event, Message(f"   {selected_key}") + MessageSegment.image(image_bytes))
                
                # 添加条件，只在首次或用户请求时显示导航
                if not user_sessions[user_id].get("nav_shown", True):
                    # 显示首页导航信息（使用文字）
                    data_keys = list(user_sessions[user_id]["data"].keys())
                    nav_text = "   首页导航：\n"
                    for i, key in enumerate(data_keys, 1):
                        nav_text += f"   {i}. {key}\n"
                    nav_text += "   请输入数字选择要查看的项目"
                    await bot.send(event, Message(nav_text))
                    user_sessions[user_id]["nav_shown"] = True
                
                # 重置超时时间
                user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                return
        else:
            # 已经在子目录中
            current_path = user_sessions[user_id]["nav_path"]
            
            # 判断是否允许进入下一层 - 只有秘境分布允许且不超过最大深度
            if len(current_path) >= 1 and (current_path[0] != "秘境分布" or len(current_path) > MAX_DEPTH):
                # 非dungeons类别不支持二级目录，或者已达到最大深度，返回上一级
                # 弹出当前路径
                user_sessions[user_id]["nav_path"].pop()
                
                # 如果是因为达到最大深度而退出，重置为秘境分布
                if current_path[0] == "秘境分布" and len(current_path) > MAX_DEPTH:
                    # 重置为秘境分布的根目录
                    user_sessions[user_id]["nav_path"] = ["秘境分布"]
                    
                    # 获取秘境分布的数据
                    items_data = items["data"]["data"]["dungeons"]
                    # 构建秘境分布的数据列表
                    dungeon_dict = {}
                    for item in items_data.keys():
                        if isinstance(items_data[item], dict):
                            result = sum_specified_keys(items_data[item], "pieces", "seniority")
                            ydcj, wdcj, ydzl, wdzl = result
                            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                            dungeon_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
                    
                    # 计算总计数据
                    tongji = [0, 0, 0, 0, 0, 0]
                    tongji[5] = items["data"]["roleName"]
                    for item in dungeon_dict.values():
                        tongji[1] += item['ydcj']
                        tongji[2] += item['wdcj']
                        tongji[3] += item['ydzl']
                        tongji[4] += item['wdzl']
                    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
                    
                    # 渲染HTML并发送图片
                    text = suijitext()
                    template = env.get_template('资历查询.html')
                    html_content = template.render(text=text, tongji=tongji, zilizonglan="秘境分布", items=dungeon_dict)
                    image_bytes = await jietu(html_content, 1120, "ck")
                    await bot.send(event, Message("   秘境分布") + MessageSegment.image(image_bytes))
                    
                    # 添加条件，只在首次或用户请求时显示导航
                    if not user_sessions[user_id].get("nav_shown", True):
                        # 显示首页导航信息（使用文字）
                        data_keys = list(user_sessions[user_id]["data"].keys())
                        nav_text = "   首页导航：\n"
                        for i, key in enumerate(data_keys, 1):
                            nav_text += f"   {i}. {key}\n"
                        nav_text += "   请输入数字选择要查看的项目"
                        await bot.send(event, Message(nav_text))
                        user_sessions[user_id]["nav_shown"] = True
                    
                    # 只重置超时时间
                    user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                    return
                
                # 显示首页导航信息（使用文字）
                data_keys = list(user_sessions[user_id]["data"].keys())
                nav_text = "   可选项：\n"
                for i, key in enumerate(data_keys, 1):
                    nav_text += f"   {i}. {key}\n"
                nav_text += "   请输入数字选择要查看的项目"
                await bot.send(event, Message(nav_text))
                
                # 重置超时时间
                user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                return
            
            # 正常处理秘境分布(dungeons)的二级目录
            temp_data = items["data"]["data"]
            
            # 根据路径导航到当前数据节点
            if current_path[0] == "秘境分布":
                temp_data = temp_data["dungeons"]
            else:
                # 这段代码实际上不会执行到，因为上面已经拦截了非秘境分布的情况
                # 但为了保持代码完整性，保留这部分
                if current_path[0] == "地图分布":
                    temp_data = temp_data["maps"]
                else:
                    temp_data = temp_data["total"][current_path[0]]
            
            # 继续导航子路径
            for i in range(1, len(current_path)):
                if current_path[i] in temp_data:
                    temp_data = temp_data[current_path[i]]
            
            # 检查选中的项是否存在于当前数据中
            if selected_key in temp_data:
                items_data = temp_data[selected_key]
                has_subitems = isinstance(items_data, dict) and len(items_data) > 0
            else:
                items_data = None
                has_subitems = False
        
        # 检查是否达到最大深度限制
        if user_sessions[user_id]["nav_path"] and user_sessions[user_id]["nav_path"][0] == "秘境分布" and len(user_sessions[user_id]["nav_path"]) >= MAX_DEPTH:
            # 如果是秘境分布且已达到最大深度，重置为秘境分布的根目录
            user_sessions[user_id]["nav_path"] = ["秘境分布"]
            
            # 获取秘境分布的数据
            items_data = items["data"]["data"]["dungeons"]
            # 构建秘境分布的数据列表
            dungeon_dict = {}
            for item in items_data.keys():
                if isinstance(items_data[item], dict):
                    result = sum_specified_keys(items_data[item], "pieces", "seniority")
                    ydcj, wdcj, ydzl, wdzl = result
                    jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                    dungeon_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
            
            # 计算总计数据
            tongji = [0, 0, 0, 0, 0, 0]
            tongji[5] = items["data"]["roleName"]
            for item in dungeon_dict.values():
                tongji[1] += item['ydcj']
                tongji[2] += item['wdcj']
                tongji[3] += item['ydzl']
                tongji[4] += item['wdzl']
            tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
            
            # 渲染HTML并发送图片
            text = suijitext()
            template = env.get_template('资历查询.html')
            html_content = template.render(text=text, tongji=tongji, zilizonglan="秘境分布", items=dungeon_dict)
            image_bytes = await jietu(html_content, 1120, "ck")
            await bot.send(event, Message("   秘境分布") + MessageSegment.image(image_bytes))
            
            # 添加条件，只在首次或用户请求时显示导航
            if not user_sessions[user_id].get("nav_shown", True):
                # 显示首页导航信息（使用文字）
                data_keys = list(user_sessions[user_id]["data"].keys())
                nav_text = "   首页导航：\n"
                for i, key in enumerate(data_keys, 1):
                    nav_text += f"   {i}. {key}\n"
                nav_text += "   请输入数字选择要查看的项目"
                await bot.send(event, Message(nav_text))
                user_sessions[user_id]["nav_shown"] = True
            
            # 只重置超时时间
            user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
            return
        
        # 将选择添加到导航路径
        user_sessions[user_id]["nav_path"].append(selected_key)

        # 如果有子项目，则显示子项目列表
        if has_subitems:
            await display_subitems(bot, event, user_id, selected_key, items_data)
        else:
            # 如果没有子项目，显示当前选择的详细信息
            await display_item_details(bot, event, user_id, selected_key, selected_item)
            # 从导航路径中移除，因为这是叶子节点
            user_sessions[user_id]["nav_path"].pop()
        
        # 重置超时时间，允许继续选择
        user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT  # 30秒

    except ValueError:
        await bot.send(event, Message("   请输入有效的数字序号"))
    except Exception as e:
        print({str(e)})


    # 获取当前导航路径的数据
def get_current_data(user_id):
    if "nav_path" not in user_sessions[user_id] or len(user_sessions[user_id]["nav_path"]) == 0:
        # 在顶层目录时，返回初始数据
        return user_sessions[user_id]["data"]
    
    # 获取导航路径
    path = user_sessions[user_id]["nav_path"]
    items = user_sessions[user_id]["items"]
    
    # 从items数据中构建子项目字典
    my_dict = {}
    temp_data = items["data"]["data"]
    
    # 根据第一级路径确定从哪个分支开始
    if path[0] == "秘境分布":
        temp_data = temp_data["dungeons"]
    elif path[0] == "地图分布":
        temp_data = temp_data["maps"]
    else:
        temp_data = temp_data["total"][path[0]]
    
    # 继续导航子路径
    for i in range(1, len(path)):
        if path[i] in temp_data:
            temp_data = temp_data[path[i]]
        else:
            # 路径不存在
            return {}
    
    # 构建当前层级的项目字典
    for item in temp_data.keys():
        if isinstance(temp_data[item], dict):
            result = sum_specified_keys(temp_data[item], "pieces", "seniority")
            ydcj, wdcj, ydzl, wdzl = result
            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0  # 避免除以零的错误
            my_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
    
    return my_dict




# 显示资历总览
async def display_zili_overview(bot, event, user_id):
    items = user_sessions[user_id]["items"]
    data = user_sessions[user_id]["data"]
    
    text = suijitext()
    tongji = [0, 0, 0, 0, 0, 0]
    tongji[5] = items["data"]["roleName"]
    
    # 计算总体数据
    for item in data.keys():
        tongji[1] += data[item]['ydcj']
        tongji[2] += data[item]['wdcj']
        tongji[3] += data[item]['ydzl']
        tongji[4] += data[item]['wdzl']
    
    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
    
    # 渲染HTML并发送图片
    template = env.get_template('资历查询.html')
    html_content = template.render(text=text, tongji=tongji, items=data)
    image_bytes = await jietu(html_content, 960, "ck")
    await bot.send(event, Message("   资历总览") + MessageSegment.image(image_bytes))
    
    # 提示用户可以选择
    nav_tips = f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目"
    await bot.send(event, MessageSegment.at(event.user_id) + Message(nav_tips))

# 导航到当前路径
async def navigate_to_path(bot, event, user_id):
    # 获取当前导航路径下的数据
    current_data = get_current_data(user_id)
    path = user_sessions[user_id]["nav_path"]
    
    if not current_data:
        await bot.send(event, Message("   无法导航到请求的路径，请返回首页"))
        return
    
    # 构建当前位置的标题
    current_location = " > ".join(path)
    items = user_sessions[user_id]["items"]
    
    # 计算当前层级的总计数据
    tongji = [0, 0, 0, 0, 0, 0]
    tongji[5] = items["data"]["roleName"]
    
    for item in current_data.values():
        tongji[1] += item['ydcj']
        tongji[2] += item['wdcj']
        tongji[3] += item['ydzl']
        tongji[4] += item['wdzl']
    
    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
    
    # 渲染HTML并发送图片
    text = suijitext()
    template = env.get_template('资历查询.html')
    html_content = template.render(text=text, tongji=tongji, zilizonglan=current_location, items=current_data)
    image_bytes = await jietu(html_content, 1120, "ck")
    await bot.send(event, Message(f"   当前位置: {current_location}") + MessageSegment.image(image_bytes))
    

# 显示子项目列表
async def display_subitems(bot, event, user_id, selected_key, items_data):
    # 构建子项目字典
    my_dict = {}
    
    # 检查是否是秘境分布的第二层
    is_second_level = "nav_path" in user_sessions[user_id] and len(user_sessions[user_id]["nav_path"]) > 1 and user_sessions[user_id]["nav_path"][0] == "秘境分布"
    
    for item in items_data.keys():
        if isinstance(items_data[item], dict):
            result = sum_specified_keys(items_data[item], "pieces", "seniority")
            ydcj, wdcj, ydzl, wdzl = result
            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0  # 避免除以零的错误
            my_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
    
    # 在这里重新检查有效数据数量
    if not check_valid_items(items_data):
        # 如果子项目不是完全为空，则显示详细信息而不是子列表
        if my_dict and len(my_dict) > 0:
            # 如果只有一个或两个子项，直接显示它们的详细信息
            for key, item in my_dict.items():
                await display_item_details(bot, event, user_id, key, item)
        
        # 弹出当前路径，返回上一级
        if len(user_sessions[user_id]["nav_path"]) > 0:
            user_sessions[user_id]["nav_path"].pop()
        
        # 只发送文字提示，不发图片
        await bot.send(event, Message(f"   {selected_key} 子项目数量不足，已返回上一级"))
        return
    
    # 计算当前子列表的总计数据
    tongji = [0, 0, 0, 0, 0, 0]
    tongji[5] = user_sessions[user_id]["items"]["data"]["roleName"]
    
    for item in my_dict.values():
        tongji[1] += item['ydcj']
        tongji[2] += item['wdcj']
        tongji[3] += item['ydzl']
        tongji[4] += item['wdzl']
    
    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
    
    # 构建当前位置的标题
    path = user_sessions[user_id]["nav_path"]
    current_location = " > ".join(path)
    
    # 渲染HTML并发送图片
    text = suijitext()
    template = env.get_template('资历查询.html')
    html_content = template.render(text=text, tongji=tongji, zilizonglan=current_location, items=my_dict, is_second_level=is_second_level)
    width = 225*len(my_dict) if is_second_level else 1120  # 确保width始终为数字
    height = 390 if is_second_level else "ck"

    image_bytes = await jietu(html_content, width, height)
    await bot.send(event, Message(f"   {selected_key}") + MessageSegment.image(image_bytes))
    
    # 如果是第二层子项目，重置为第一层
    if is_second_level:
        # 只保留第一层路径，移除第二层
        user_sessions[user_id]["nav_path"] = [user_sessions[user_id]["nav_path"][0]]
    
    # 提示用户可以选择
    nav_tips = f" 请在{SESSION_TIMEOUT}秒内回复数字查看秘境详情！输入：0 返回总览"
    await bot.send(event, MessageSegment.at(event.user_id) + Message(nav_tips))

# 显示单个项目的详细信息
async def display_item_details(bot, event, user_id, selected_key, selected_item):
    # 特殊处理所有项目，显示完整子项目列表
    items = user_sessions[user_id]["items"]
    
    # 检查当前导航深度是否为第二层子项目（秘境分布的第二层）
    is_second_level = "nav_path" in user_sessions[user_id] and len(user_sessions[user_id]["nav_path"]) > 1 and user_sessions[user_id]["nav_path"][0] == "秘境分布"
    
    # 检查选择项目是否可能有子项目
    if selected_key == "地图分布":
        # 地图分布的子项目列表
        items_data = items["data"]["data"]["maps"]
    elif selected_key == "秘境分布":
        # 秘境分布的子项目列表
        items_data = items["data"]["data"]["dungeons"]
    else:
        # 其他项目可能是total下的子项目
        if "total" in items["data"]["data"] and selected_key in items["data"]["data"]["total"]:
            items_data = items["data"]["data"]["total"][selected_key]
        else:
            # 如果没有子项目路径，则显示单个项目详情
            # 创建一个只含选中项目的字典
            my_dict = {}
            my_dict[selected_key] = selected_item
            
            # 设置总计数据
            tongji = [0, 0, 0, 0, 0, 0]
            tongji[5] = items["data"]["roleName"]
            tongji[1] = selected_item['ydcj']
            tongji[2] = selected_item['wdcj']
            tongji[3] = selected_item['ydzl']
            tongji[4] = selected_item['wdzl']
            tongji[0] = round(selected_item['jindu'], 2)
            
            # 创建标题
            item_title = f"项目详情: {selected_key}"
            
            # 渲染HTML并发送图片
            text = suijitext()
            template = env.get_template('资历查询.html')
            html_content = template.render(text=text, tongji=tongji, zilizonglan=item_title, items=my_dict, is_second_level=is_second_level)
            image_bytes = await jietu(html_content, 800, "ck")
            await bot.send(event, Message(f"   {selected_key} 详细信息") + MessageSegment.image(image_bytes))
            
            # 如果是第二层子项目，显示完后自动返回到第一层
            if is_second_level:
                # 保留第一层路径，移除第二层
                user_sessions[user_id]["nav_path"] = [user_sessions[user_id]["nav_path"][0]]
                
                # 获取并显示第一层的数据
                first_level_data = get_current_data(user_id)
                path = user_sessions[user_id]["nav_path"]
                current_location = " > ".join(path)
                
                # 计算第一层的总计数据
                tongji = [0, 0, 0, 0, 0, 0]
                tongji[5] = items["data"]["roleName"]
                for item in first_level_data.values():
                    tongji[1] += item['ydcj']
                    tongji[2] += item['wdcj']
                    tongji[3] += item['ydzl']
                    tongji[4] += item['wdzl']
                tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
                
                # 稍后发送返回第一层的提示
                await bot.send(event, Message(f"   已自动返回到第一层: {path[0]}"))
                
                # 提示用户可以继续选择
                nav_tips = f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目！输入：0 返回总览"
                await bot.send(event, MessageSegment.at(event.user_id) + Message(nav_tips))
            
            return
    
    # 有子项目，构建数据列表
    sub_dict = {}
    for item in items_data.keys():
        if isinstance(items_data[item], dict):
            result = sum_specified_keys(items_data[item], "pieces", "seniority")
            ydcj, wdcj, ydzl, wdzl = result
            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
            sub_dict[item] = {'jindu': jindu, 'ydcj': ydcj, 'wdcj': wdcj, 'ydzl': ydzl, 'wdzl': wdzl}
    
    # 如果没有找到有效子项目，仍然显示单个项目详情
    if not sub_dict:
        my_dict = {}
        my_dict[selected_key] = selected_item
        
        # 设置总计数据
        tongji = [0, 0, 0, 0, 0, 0]
        tongji[5] = items["data"]["roleName"]
        tongji[1] = selected_item['ydcj']
        tongji[2] = selected_item['wdcj']
        tongji[3] = selected_item['ydzl']
        tongji[4] = selected_item['wdzl']
        tongji[0] = round(selected_item['jindu'], 2)
        
        # 创建标题
        item_title = f"项目详情: {selected_key}"
        
        # 渲染HTML并发送图片
        text = suijitext()
        template = env.get_template('资历查询.html')
        html_content = template.render(text=text, tongji=tongji, zilizonglan=item_title, items=my_dict, is_second_level=is_second_level)
        image_bytes = await jietu(html_content, 800, "ck")
        await bot.send(event, Message(f"   {selected_key} 详细信息") + MessageSegment.image(image_bytes))
        
        # 如果是第二层子项目，显示完后自动返回到第一层
        if is_second_level:
            # 保留第一层路径，移除第二层
            user_sessions[user_id]["nav_path"] = [user_sessions[user_id]["nav_path"][0]]
            
            # 获取并显示第一层的数据
            first_level_data = get_current_data(user_id)
            path = user_sessions[user_id]["nav_path"]
            current_location = " > ".join(path)
            
            # 计算第一层的总计数据
            tongji = [0, 0, 0, 0, 0, 0]
            tongji[5] = items["data"]["roleName"]
            for item in first_level_data.values():
                tongji[1] += item['ydcj']
                tongji[2] += item['wdcj']
                tongji[3] += item['ydzl']
                tongji[4] += item['wdzl']
            tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
            
            # 稍后发送返回第一层的提示
            await bot.send(event, Message(f"   已自动返回到第一层: {path[0]}"))
            
            # 提示用户可以继续选择
            nav_tips = f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目！输入：0 返回"
            await bot.send(event, MessageSegment.at(event.user_id) + Message(nav_tips))
        
        return
    
    # 有子项目，计算总计数据
    tongji = [0, 0, 0, 0, 0, 0]
    tongji[5] = items["data"]["roleName"]
    for item in sub_dict.values():
        tongji[1] += item['ydcj']
        tongji[2] += item['wdcj']
        tongji[3] += item['ydzl']
        tongji[4] += item['wdzl']
    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0
    
    # 渲染HTML并发送图片
    text = suijitext()
    template = env.get_template('资历查询.html')
    html_content = template.render(text=text, tongji=tongji, zilizonglan=selected_key, items=sub_dict, is_second_level=is_second_level)
    image_bytes = await jietu(html_content, 1120, "ck")
    await bot.send(event, Message(f"   {selected_key} 子项目列表") + MessageSegment.image(image_bytes))
    
    # 如果是第二层子项目，显示完后自动返回到第一层
    if is_second_level:
        # 保留第一层路径，移除第二层
        user_sessions[user_id]["nav_path"] = [user_sessions[user_id]["nav_path"][0]]
        
        # 获取并显示第一层的数据
        first_level_data = get_current_data(user_id)
        path = user_sessions[user_id]["nav_path"]
        current_location = " > ".join(path)
        
        # 稍后发送返回第一层的提示
        await bot.send(event, Message(f"   已自动返回到第一层: {path[0]}"))
        
        # 提示用户可以继续选择
        nav_tips = f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目！输入：0 返回"
        await bot.send(event, MessageSegment.at(event.user_id) + Message(nav_tips))

# 检查数据是否为空或无效
def check_valid_items(items_data):
    """检查数据是否有效且包含可用项目"""
    # 检查数据是否存在
    if items_data is None:
        return False
    
    # 检查是否为字典且有内容
    if not isinstance(items_data, dict) or len(items_data) == 0:
        return False
    
    # 检查是否有至少2个有效子项
    valid_count = 0
    for item in items_data.keys():
        if isinstance(items_data[item], dict):
            valid_count += 1
            # 找到足够数量的有效项就提前返回
            if valid_count >= 2:
                return True
    
    # 如果有效子项少于2个，也认为数据无效
    return False



# 启动时初始化：保存数据到文件并加载为全局变量
@driver.on_startup
async def init_cache():
    """初始化服务器数据：获取、保存到文件并设置为全局变量"""
    global server_data_cache,token_data

    try:
        await download_json()

        fresh_data = await jiaoyiget("https://www.jx3api.com/data/server/check")
        token_data = await jiaoyiget(f"https://www.jx3api.com/data/token/web-token?token={TOKEN}")

        if isinstance(fresh_data, str):
            data_obj = json.loads(fresh_data)
        else:
            data_obj = fresh_data

        # 保存到文件
        file_path = SERVER_DATA_FILE
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data_obj, f, ensure_ascii=False, indent=2)

        # 设置全局变量
        server_data_cache = data_obj
        print(f"服务器数据已获取并保存到: {file_path}")
        if token_data:
            import src.utils.shared_data
            src.utils.shared_data.tokendata =token_data['data']['limit']
            print(f"token剩余：{src.utils.shared_data.tokendata }")

    except Exception as e:
        print(f"获取新数据失败: {e}")
        # 如果获取新数据失败，尝试从本地文件读取
        try:
            if os.path.exists(SERVER_DATA_FILE):
                with open(SERVER_DATA_FILE, 'r', encoding='utf-8') as f:
                    server_data_cache = json.load(f)
                print(f"已从本地文件加载服务器数据")
            else:
                print(f"本地文件不存在，无法加载服务器数据")
        except Exception as read_error:
            print(f"读取本地文件失败: {read_error}")


# 使用全局数据的函数示例
async def check_server(server_name):
    """检查服务器是否存在"""
    global server_data_cache

    # 如果缓存为空，尝试从文件读取
    if server_data_cache is None:
        try:
            if os.path.exists(SERVER_DATA_FILE):
                with open(SERVER_DATA_FILE, 'r', encoding='utf-8') as f:
                    server_data_cache = json.load(f)
        except Exception:
            return False  # 无法读取数据

    # 检查服务器
    if server_data_cache and "data" in server_data_cache:
        for server in server_data_cache["data"]:
            if server.get("server") == server_name:
                return True

    return False

# ================== 战绩排名相关方法移植 ==================
async def query_jjc_data(server: str, name: str, token: str = None, ticket: str = None) -> dict:
    """
    查询剑网3竞技场数据
    
    Args:
        server: 服务器名称
        name: 角色名称
        token: API认证令牌（可选，默认从config文件获取）
        ticket: 推栏cookie（可选，默认从config文件获取）
    
    Returns:
        dict: API返回的原始数据
    """
    # 使用配置文件中的默认值
    if token is None:
        token = TOKEN
    if ticket is None:
        ticket = TICKET
    
    # API接口地址
    url = "https://www.jx3api.com/data/arena/recent"
    
    # 清理角色名中的特殊字符
    if name:
        name = name.replace('[', '').replace(']', '').replace('&#91;', '').replace('&#93;', '').replace(" ", "")
    
    # 构建请求参数
    params = {
        'server': server,
        'name': name,
        "mode": 33,
        'token': token,
        'ticket': ticket
    }
    
    print(f"正在查询: 服务器={server}, 角色={name}")
    print(f"请求URL: {url}")
    print(f"请求参数: {params}")
    print("-" * 50)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                print(f"HTTP状态码: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    error_text = await response.text()
                    return {
                        "error": True,
                        "status_code": response.status,
                        "message": f"HTTP请求失败: {response.status}",
                        "response_text": error_text
                    }
                    
    except aiohttp.ClientError as e:
        return {
            "error": True,
            "message": f"网络请求错误: {str(e)}"
        }
    except json.JSONDecodeError as e:
        return {
            "error": True,
            "message": f"JSON解析错误: {str(e)}"
        }
    except Exception as e:
        return {
            "error": True,
            "message": f"未知错误: {str(e)}"
        }


async def get_user_kuangfu(server: str, name: str, token: str = None, ticket: str = None) -> dict:
    """
    获取用户的kuangfu信息
    
    Args:
        server: 服务器名称
        name: 角色名称
        token: API认证令牌（可选，默认从config文件获取）
        ticket: 推栏cookie（可选，默认从config文件获取）
    
    Returns:
        dict: 包含kuangfu信息的结果
    """
    # 使用配置文件中的默认值
    if token is None:
        token = TOKEN
    if ticket is None:
        ticket = TICKET
    
    # 缓存配置
    cache_dir = "data/cache/kuangfu"
    cache_file = os.path.join(cache_dir, f"{server}_{name}.json")
    
    # 创建缓存目录
    os.makedirs(cache_dir, exist_ok=True)
    
    # 检查缓存是否存在
    if os.path.exists(cache_file):
        try:
            print(f"从缓存中读取 {server}_{name} 的kuangfu信息")
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            return cached_data
        except Exception as e:
            print(f"读取缓存文件失败: {e}")
    
    # 随机延迟1-5秒，防止被反爬虫检测
    delay = random.uniform(1, 5)
    print(f"等待 {delay:.2f} 秒后发起请求...")
    await asyncio.sleep(delay)
    
    # 查询用户的竞技场数据
    print(f"正在查询 {server}_{name} 的kuangfu信息")
    jjc_data = await query_jjc_data(server, name, token, ticket)
    
    if jjc_data.get("error") or jjc_data.get("msg") != "success":
        print(f"获取竞技场数据失败: {jjc_data}")
        return {
            "error": True,
            "message": f"获取竞技场数据失败: {jjc_data.get('message', '未知错误')}",
            "server": server,
            "name": name
        }
    
    # 从竞技场数据中提取kuangfu信息
    kuangfu_info = None
    
    # 从history数组中获取kuangfu信息
    history_data = jjc_data.get("data", {}).get("history", [])
    if history_data:
        # 查找最近一次获胜的记录
        for match in history_data:
            if match.get("won") == True:
                kuangfu_info = match.get("kungfu")
                break
    
    result = {
        "server": server,
        "name": name,
        "kuangfu": kuangfu_info,
        "found": kuangfu_info is not None,
        "cache_time": time.time()
    }

    print(f"尝试缓存数据到文件: {cache_file}")
    # 保存到缓存
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"kuangfu信息已缓存到: {cache_file}")
    except Exception as e:
        print(f"保存缓存失败: {e}")
    
    return result


async def query_jjc_ranking(token: str = None, ticket: str = None) -> dict:
    """
    查询剑网3竞技场排行榜数据
    
    Args:
        token: API认证令牌（可选，默认从config文件获取）
        ticket: 推栏cookie（可选，默认从config文件获取）
    
    Returns:
        dict: 合并后的排行榜数据
    """
    # 使用配置文件中的默认值
    if token is None:
        token = TOKEN
    if ticket is None:
        ticket = TICKET
    
    # 缓存配置
    cache_dir = "data/cache"
    cache_file = os.path.join(cache_dir, "jjc_ranking_cache.json")
    cache_duration = 2000 * 60  # 20分钟，单位秒
    
    # 创建缓存目录
    os.makedirs(cache_dir, exist_ok=True)
    
    # 检查缓存是否存在且有效
    if os.path.exists(cache_file):
        try:
            file_time = os.path.getmtime(cache_file)
            current_time = time.time()
            
            # 检查缓存是否在20分钟内
            if current_time - file_time < cache_duration:
                print("从缓存中读取竞技场排行榜数据")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                return cached_data
            else:
                print("缓存已过期，重新请求数据")
        except Exception as e:
            print(f"读取缓存文件失败: {e}")
    
    # API接口地址
    url = "https://www.jx3api.com/data/arena/awesome"
    
    # 请求参数
    params = {
        "mode": 33,
        "limit": 100,
        "ticket": ticket,
        "token": token
    }
    
    print(f"正在查询竞技场排行榜数据")
    print(f"请求URL: {url}")
    print(f"请求参数: {params}")
    print("-" * 50)
    
    try:
        async with aiohttp.ClientSession() as session:
            all_data = []
            second_response_time = None
            
            # 发起两次请求
            for i in range(2):
                print(f"第{i+1}次请求...")
                
                async with session.get(url, params=params) as response:
                    print(f"第{i+1}次请求HTTP状态码: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get("code") == 200 and data.get("msg") == "success":
                            # 记录第二次请求的时间
                            if i == 1:
                                second_response_time = data.get("time")
                            
                            # 添加数据到总列表
                            if "data" in data and isinstance(data["data"], list):
                                all_data.extend(data["data"])
                                print(f"第{i+1}次请求成功，获取到 {len(data['data'])} 条数据")
                            else:
                                print(f"第{i+1}次请求数据格式异常")
                        else:
                            print(f"第{i+1}次请求API返回错误: {data.get('msg', '未知错误')}")
                    else:
                        error_text = await response.text()
                        print(f"第{i+1}次请求HTTP错误: {response.status}")
                        print(f"错误响应: {error_text}")
            
            # 返回合并后的结果
            result = {
                "code": 200,
                "msg": "success",
                "data": all_data,
                "total_count": len(all_data),
                "second_request_time": second_response_time,
                "cache_time": time.time()
            }
            
            print(f"合并完成，总共获取到 {len(all_data)} 条排行榜数据")
            if second_response_time:
                print(f"第二次请求时间戳: {second_response_time}")
            
            # 保存到缓存
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                print(f"数据已缓存到: {cache_file}")
            except Exception as e:
                print(f"保存缓存失败: {e}")
            
            return result
                    
    except aiohttp.ClientError as e:
        print(f"query_jjc_ranking 网络请求错误: {str(e)}")
        return {
            "error": True,
            "message": f"网络请求错误: {str(e)}"
        }
    except json.JSONDecodeError as e:
        print(f"query_jjc_ranking JSON解析错误: {str(e)}")
        return {
            "error": True,
            "message": f"JSON解析错误: {str(e)}"
        }
    except Exception as e:
        print(f"query_jjc_ranking 未知错误: {str(e)}")
        return {
            "error": True,
            "message": f"未知错误: {str(e)}"
        }


async def get_ranking_kuangfu_data(ranking_data: dict, token: str = None, ticket: str = None) -> dict:
    """
    获取排行榜数据的kuangfu信息
    
    Args:
        ranking_data: 排行榜数据（query_jjc_ranking的返回值）
        token: API认证令牌（可选，默认从config文件获取）
        ticket: 推栏cookie（可选，默认从config文件获取）
    
    Returns:
        dict: 包含kuangfu信息的排行榜数据
    """
    # 使用配置文件中的默认值
    if token is None:
        token = TOKEN
    if ticket is None:
        ticket = TICKET
    
    # 检查排行榜数据是否有效
    if ranking_data.get("error") or ranking_data.get("code") != 200:
        print(f"排行榜数据无效，无法获取kuangfu信息: {ranking_data}");
        return {
            "error": True,
            "message": "排行榜数据无效，无法获取kuangfu信息",
            "ranking_data": ranking_data
        }
    
    # 获取排行榜数据
    all_data = ranking_data.get("data", [])
    print(f"all_data: len{len(all_data)}")

    if not all_data:
        return {
            "error": True,
            "message": "排行榜数据为空，无法获取kuangfu信息",
            "ranking_data": ranking_data
        }
    
    # 获取排行榜中用户的kuangfu信息
    print("正在获取排行榜用户的kuangfu信息...")
    kuangfu_results = []
    
    for i, player in enumerate(all_data):  # 遍历整个排行榜数据

        # 从新的数据格式中获取服务器和角色名
        person_info = player.get("personInfo", {})
        player_server = person_info.get("server")
        player_name = person_info.get("roleName")
  
        print(f"player_server: {player_server}, player_name: {player_name}")
        # 从roleName中提取·符号左边部分作为player_name
        if player_name and "·" in player_name:
            player_name = player_name.split("·")[0]
        
        if player_server and player_name:
            print(f"处理第{i+1}名: {player_server}_{player_name}")
            kuangfu_info = await get_user_kuangfu(player_server, player_name, token, ticket)
            kuangfu_results.append(kuangfu_info)

    # 将kuangfu信息添加到排行榜数据中
    result = ranking_data.copy()
    result["kuangfu_data"] = kuangfu_results
    print(f"kuangfu信息获取完成，共处理 {len(kuangfu_results)} 个用户")
    
    # 定义奶妈心法列表
    healer_kuangfu = ["离经易道", "补天诀", "云裳心经", "灵素", "相知"]
    
    # 统计各个排名段的kuangfu数量
    def count_kuangfu_by_rank(kuangfu_data, max_rank):
        """统计指定排名范围内的kuangfu数量，区分奶妈和DPS"""
        healer_count = {}
        dps_count = {}
        healer_valid_count = 0
        dps_valid_count = 0
        
        for i, player_data in enumerate(kuangfu_data[:max_rank]):
            if player_data.get("found") and player_data.get("kuangfu"):
                kuangfu = player_data["kuangfu"]
                
                # 判断是否为奶妈心法
                if kuangfu in healer_kuangfu:
                    healer_count[kuangfu] = healer_count.get(kuangfu, 0) + 1
                    healer_valid_count += 1
                else:
                    dps_count[kuangfu] = dps_count.get(kuangfu, 0) + 1
                    dps_valid_count += 1
        
        # 按数量降序排序
        sorted_healer = sorted(healer_count.items(), key=lambda x: x[1], reverse=True)
        sorted_dps = sorted(dps_count.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "total_players": max_rank,
            "healer": {
                "valid_count": healer_valid_count,
                "distribution": dict(sorted_healer),
                "list": sorted_healer
            },
            "dps": {
                "valid_count": dps_valid_count,
                "distribution": dict(sorted_dps),
                "list": sorted_dps
            },
            "total_valid_count": healer_valid_count + dps_valid_count
        }
    
    # 统计前200、前100、前50的kuangfu分布
    print("正在统计kuangfu分布...")
    kuangfu_stats = {
        "top_200": count_kuangfu_by_rank(kuangfu_results, 200),
        "top_100": count_kuangfu_by_rank(kuangfu_results, 100),
        "top_50": count_kuangfu_by_rank(kuangfu_results, 50)
    }
    
    result["kuangfu_statistics"] = kuangfu_stats
    
    # 打印统计结果
    print("\n" + "="*80)
    print("KUANGFU统计结果 (奶妈/DPS分类)")
    print("="*80)
    
    for rank_range, stats in kuangfu_stats.items():
        print(f"\n{rank_range.upper()} ({stats['total_players']}人，有效数据{stats['total_valid_count']}人):")
        print("=" * 60)
        
        # 奶妈统计
        print(f"\n【奶妈排名】({stats['healer']['valid_count']}人):")
        print("-" * 40)
        if stats['healer']['list']:
            for kuangfu, count in stats['healer']['list']:
                percentage = (count / stats['healer']['valid_count'] * 100) if stats['healer']['valid_count'] > 0 else 0
                print(f"  {kuangfu}: {count}人 ({percentage:.1f}%)")
        else:
            print("  无奶妈数据")
        
        # DPS统计
        print(f"\n【DPS排名】({stats['dps']['valid_count']}人):")
        print("-" * 40)
        if stats['dps']['list']:
            for kuangfu, count in stats['dps']['list']:
                percentage = (count / stats['dps']['valid_count'] * 100) if stats['dps']['valid_count'] > 0 else 0
                print(f"  {kuangfu}: {count}人 ({percentage:.1f}%)")
        else:
            print("  无DPS数据")
    
    print("="*80)
    
    return result

@zhanji_ranking.handle()
async def zhanji_ranking_to_image(bot: Bot, event: Event):
    """
    群聊输入"战绩排名"时，统计JJC排名并生成竞技场心法分布图片发送到群聊。
    """
    try:
        await bot.send(event, "正在统计竞技场心法排名，请稍候...")
        
        # 1. 查询JJC排行榜数据
        ranking_result = await query_jjc_ranking()
        
        # 检查排行榜数据是否有效
        if ranking_result is None:
            await bot.send(event, "获取竞技场排行榜数据失败：返回数据为空")
            return
            
        if ranking_result.get("error"):
            error_msg = ranking_result.get("message", "未知错误")
            await bot.send(event, f"获取竞技场排行榜数据失败：{error_msg}")
            return
            
        if ranking_result.get("code") != 200:
            await bot.send(event, f"获取竞技场排行榜数据失败：API返回错误码 {ranking_result.get('code')}")
            return
        
        # 2. 获取排行榜心法分布
        result = await get_ranking_kuangfu_data(ranking_data=ranking_result)
        
        # 检查心法分布数据是否有效
        if result is None:
            await bot.send(event, "获取心法分布数据失败：返回数据为空")
            return
            
        if result.get("error"):
            error_msg = result.get("message", "未知错误")
            await bot.send(event, f"获取心法分布数据失败：{error_msg}")
            return
        
        # 3. 组织模板数据
        stats = result.get("kuangfu_statistics", {})
        
        if not stats:
            await bot.send(event, "心法统计数据为空，无法生成统计图片")
            return
        
        # 准备模板数据，按数量降序排序
        def prepare_template_data(rank_data, rank_type):
            """准备模板数据，按数量降序排序"""
            if not rank_data or rank_type not in rank_data:
                return []
            distribution = rank_data[rank_type].get('distribution', {})
            if not distribution:
                return []
            # 按数量降序排序
            sorted_items = sorted(distribution.items(), key=lambda x: x[1], reverse=True)
            valid_count = rank_data[rank_type].get('valid_count', 0)
            return [(k, v, f"{v / valid_count * 100:.1f}%" if valid_count > 0 else "0%") for k, v in sorted_items]
        
        # 4. 渲染HTML
        template = env.get_template('竞技场心法排名统计.html')
        html_content = template.render(
            top_200_healer=prepare_template_data(stats.get('top_200', {}), 'healer'),
            top_200_dps=prepare_template_data(stats.get('top_200', {}), 'dps'),
            top_100_healer=prepare_template_data(stats.get('top_100', {}), 'healer'),
            top_100_dps=prepare_template_data(stats.get('top_100', {}), 'dps'),
            top_50_healer=prepare_template_data(stats.get('top_50', {}), 'healer'),
            top_50_dps=prepare_template_data(stats.get('top_50', {}), 'dps'),
        )
        
        # 5. 截图生成图片
        image_bytes = await jietu(html_content, 1120, "ck")
        
        # 6. 发送图片
        await bot.send(event, MessageSegment.image(image_bytes))
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"战绩排名统计详细错误：{error_traceback}")
        await bot.send(event, f"战绩排名统计失败：{str(e)}")
