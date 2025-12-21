import aiohttp
from typing import Optional
from datetime import datetime, timedelta
from cacheout import Cache
import aiofiles
import time
import os
import glob
import json
import asyncio
from config import IMAGE_CACHE_DIR,SESSION_data,texts

from src.infra.http_client import HttpClient
from src.infra.browser_storage import download_json_from_local_storage
from src.infra.image_fetch import mp_image
from src.infra.screenshot import jietu, jx3web


# 全局变量
SERVER_DATA_FILE = "server_data.json"  # 文件路径
server_data_cache = None  # 缓存
cache = Cache(maxsize=256, ttl=SESSION_data, timer=time.time, default=None)
def jjcdaxiaoxie(timestamp):
    if timestamp == 0:
        return "零"
    if timestamp == 1:
        return "一"
    if timestamp == 2:
        return "二"
    if timestamp == 3:
        return "三"
    if timestamp == 4:
        return "四"
    if timestamp == 5:
        return "五"
    if timestamp == 6:
        return "六"
    if timestamp == 7:
        return "七"
    if timestamp == 8:
        return "八"
    if timestamp == 9:
        return "九"
    if timestamp == 10:
        return "十"
    if timestamp == 11:
        return "十一"
    if timestamp == 12:
        return "十二"
    if timestamp == 13:
        return "十三"
    if timestamp == 14:
        return "十四"
    if timestamp == 15:
        return "十五"
def convert_number(amount):
    thousands = amount // 100000000
    thousands = "" if thousands == 0 else f" {thousands}<img src='http://192.168.100.1:5244/img/qiyu/img/zhuan.png' alt='砖'>"
    remainder = (amount % 100000000) // 10000
    remainder = "" if remainder == 0 else f" {remainder}<img src='http://192.168.100.1:5244/img/qiyu/img/jin.png' alt='金'>"
    billions = (amount % 10000) // 100
    billions = "" if billions == 0 else f" {billions}<img src='http://192.168.100.1:5244/img/qiyu/img/yin.png' alt='银'>"
    return f"{thousands}{remainder}{billions}"
def suijitext():

    # 获取当前时间戳的毫秒部分
    microseconds = int(time.time() * 1000000) % len(texts)


    # 使用毫秒部分作为索引来选择列表中的一个元素
    selected_text = texts[microseconds]
    return selected_text
def timestamp_jjc(timestamp, format="%Y-%m-%d %H:%M:%S"):
    dt_object = datetime.fromtimestamp(timestamp)
    return dt_object.strftime(format)


def time_ago_fenzhong(timestamp):
    if timestamp == 0:
        return "被遗忘的时间"

    now = datetime.now()
    then = datetime.fromtimestamp(timestamp)

    # 计算总时间差（单位：秒）
    total_seconds = int((now - then).total_seconds())

    # 处理未来时间
    if total_seconds < 0:
        return "未来时间"

    # 如果差异小于60秒
    if total_seconds < 60:
        return "刚刚"

    # 计算天、小时、分钟
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    # 格式化相对时间字符串
    relative_time = []
    if days > 0:
        relative_time.append(f"{days}天")
    if hours > 0:
        relative_time.append(f"{hours:02d}小时")
    if minutes > 0:
        relative_time.append(f"{minutes:02d}分钟")

    # 连接字符串并返回结果
    return "".join(relative_time) + "前"
def time_ago_filter(timestamp):
    now = datetime.now()
    then = datetime.fromtimestamp(timestamp)
    time_difference = now - then
    # 提取年、月、日、小时等时间差信息（简化计算）
    years = time_difference.days // 365
    months = (time_difference.days % 365) // 30
    days = time_difference.days % 30
    hours = time_difference.seconds // 3600
    # 格式化相对时间字符串
    relative_time = []
    if years > 0:
        relative_time.append(f"{years}年")
    if months > 0:
        relative_time.append(f"{months}月")
    if days > 0:
        relative_time.append(f"{days}天")
    if hours > 0:
        relative_time.append(f"{hours}小时")
    return "".join(relative_time) + "前"
def sum_specified_keys(data, keys_to_sum, keys_to_sum2):
    """
    遍历数据结构，对两组指定键的'total'和'speed'进行累加。

    :param data: 要遍历的数据结构（字典或列表）
    :param keys_to_sum: 第一个包含需要累加的键名的列表
    :param keys_to_sum2: 第二个包含需要累加的键名的列表
    :return: 一个包含四个累加结果的元组，顺序为(keys_to_sum中键的total累加和, keys_to_sum中键的speed累加和, keys_to_sum2中键的total累加和, keys_to_sum2中键的speed累加和)
    """
    # 初始化累加结果
    total_sum1 = 0
    speed_sum1 = 0
    total_sum2 = 0
    speed_sum2 = 0

    def recurse(data):
        nonlocal total_sum1, speed_sum1, total_sum2, speed_sum2

        if isinstance(data, dict):
            for key, value in data.items():
                if key in keys_to_sum and isinstance(value, dict):
                    if 'total' in value and isinstance(value['total'], (int, float)):
                        total_sum1 += value['total']
                    if 'speed' in value and isinstance(value['speed'], (int, float)):
                        speed_sum1 += value['speed']
                elif key in keys_to_sum2 and isinstance(value, dict):
                    if 'total' in value and isinstance(value['total'], (int, float)):
                        total_sum2 += value['total']
                    if 'speed' in value and isinstance(value['speed'], (int, float)):
                        speed_sum2 += value['speed']
                recurse(value)
        elif isinstance(data, list):
            for item in data:
                recurse(item)

    # 开始递归处理
    recurse(data)

    # 返回累加结果
    return speed_sum1,total_sum1, speed_sum2,total_sum2
# get请求函数

async def get(url: str, server: Optional[str] = None, name: Optional[str] = None,
              token: Optional[str] = None, ticket: Optional[str] = None, zili: Optional[str] = None) -> dict:
    """
    异步GET请求方法

    Args:
        url: 请求URL（必填）
        server: 服务器名称（可选）
        name: 角色名称（可选）
        token: 认证令牌（可选）
        ticket: 票据（可选）
        zili: 资历分布（可选）

    Returns:
        dict: 响应数据
    """
    if name is not None:
        name = name.replace('[', '').replace(']', '').replace('&#91;', '').replace('&#93;', '').replace(" ", "")

    params = {}
    if server:
        params['server'] = server
    if name:
         params['name'] = name
    if token:
        params['token'] = token
    if ticket:
        params['ticket'] = ticket
    if zili:
        params['class'] = zili
    if name is not None:
        if 'name' in params:
            params['name'] = name





    cache_data = cache.get(f'{url}{server}{name}')
    if cache_data:
        print("从缓存中获取数据")
        data=cache_data

    else:
        print("获取NEW数据")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                
                # 检查响应状态码
                if response.status != 200:
                    print(f"HTTP请求失败，状态码: {response.status}")
                    return {"error": True, "message": f"HTTP请求失败，状态码: {response.status}"}
                
                # 检查响应内容类型
                content_type = response.headers.get('content-type', '')
                if 'application/json' not in content_type and 'text/plain' not in content_type:
                    print(f"响应内容类型不支持: {content_type}")
                    return {"error": True, "message": f"响应内容类型不支持: {content_type}"}
                
                try:
                    # 获取响应文本
                    response_text = await response.text()
                    
                    # 检查响应是否为空
                    if not response_text.strip():
                        print("响应内容为空")
                        return {"error": True, "message": "响应内容为空"}
                    
                    # 尝试解析JSON
                    data = json.loads(response_text)
                    
                    # 缓存成功的结果
                    cache.set(f'{url}{server}{name}', data)
                    
                except json.JSONDecodeError as e:
                    print(f"JSON解析失败: {e}")
                    print(f"响应内容: {response_text[:200]}...")  # 只打印前200个字符
                    return {"error": True, "message": f"JSON解析失败: {e}"}
                except Exception as e:
                    print(f"处理响应时出错: {e}")
                    return {"error": True, "message": f"处理响应时出错: {e}"}

    return data


# 检查并获取最新的名片图片
async def get_image(server, role_name,free=None):
    """
    检查mpimg目录下是否有指定服务器和角色名的图片，如果有则返回最新的一张（不带目录的路径）

    参数:
    server: 服务器名，如"梦江南"
    role_name: 角色名，如"冽弦"

    返回:
    如果找到图片，返回最新图片的文件名（不带目录）；如果没有找到，返回None
    """
    try:
        # 确保目录存在
        if not os.path.exists(IMAGE_CACHE_DIR):
            os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
            return None

        # 构建搜索模式
        search_pattern = f"{IMAGE_CACHE_DIR}/{server}-{role_name}-*.png"

        # 获取所有匹配的文件
        matching_files = glob.glob(search_pattern)

        # 如果没有匹配的文件，返回None
        if not matching_files:
            return None

        # 过滤掉不存在或无法访问的文件
        valid_files = [f for f in matching_files if os.path.isfile(f) and os.access(f, os.R_OK)]

        if not valid_files:
            return None

        # 按文件修改时间排序，获取最新的文件
        latest_file = max(valid_files, key=os.path.getmtime)

        # 检查文件大小是否为0

        if os.path.getsize(latest_file) == 0:
            return None


        if free=="1":
            valid_files = [
                f
                for f in matching_files
                if os.path.isfile(f) and os.access(f, os.R_OK) and os.path.getsize(f) > 0
            ]
            valid_files.sort(key=os.path.getmtime, reverse=True)
            return valid_files
        # 返回最新文件的文件名（不带目录）
        return os.path.basename(latest_file)
    except Exception as e:
        print(f"获取名片图片时出错: {str(e)}")
        return None
#交易行get
async def fetch_json(url: str) -> dict:
    http_client = HttpClient(timeout=30.0, retries=2, backoff_seconds=0.5, verify=False)
    return await http_client.arequest_json("GET", url, verify=False)


async def jiaoyiget(url: str) -> dict:
    return await fetch_json(url)

async def idget(server_name):
    """
    检查服务器名称是否存在于服务器数据中

    参数:
        server_name: 要检查的服务器名称

    返回:
        bool: 服务器是否存在
    """
    global server_data_cache, SERVER_DATA_FILE

    # 如果缓存为空，从文件加载数据
    if server_data_cache is None:
        try:
            if os.path.exists(SERVER_DATA_FILE):
                with open(SERVER_DATA_FILE, 'r', encoding='utf-8') as f:
                    server_data_cache = json.load(f)
                print(f"已从{SERVER_DATA_FILE}加载服务器数据")
            else:
                print(f"错误：{SERVER_DATA_FILE}文件不存在")
                return False
        except Exception as e:
            print(f"读取服务器数据文件失败: {e}")
            return False

    # 检查服务器是否存在
    try:
        for server in server_data_cache.get("data", []):
            if server.get("server") == server_name:
                return True
        return False
    except Exception as e:
        print(f"解析服务器数据时出错: {e}")
        return False


async def download_json(url="https://jx3.seasunwbl.com/buyer?t=skin", key_name="skin_appearance_cache_key", output_filename="waiguan.json"):
    return await download_json_from_local_storage(
        url=url, key_name=key_name, output_filename=output_filename
    )
