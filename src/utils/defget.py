from typing import Optional
import aiofiles
import os
import glob
import json
import asyncio
from config import IMAGE_CACHE_DIR

from src.infra.http_client import HttpClient
from src.infra.browser_storage import download_json_from_local_storage
from src.infra.image_fetch import mp_image
from src.infra.screenshot import jietu, jx3web
from src.infra.jx3api_get import get, idget
from src.utils.data_sum import sum_specified_keys
from src.utils.jjc_text import jjcdaxiaoxie
from src.utils.money_format import convert_number
from src.utils.random_text import suijitext
from src.utils.time_utils import time_ago_filter, time_ago_fenzhong, timestamp_jjc

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


async def download_json(url="https://jx3.seasunwbl.com/buyer?t=skin", key_name="skin_appearance_cache_key", output_filename="waiguan.json"):
    return await download_json_from_local_storage(
        url=url, key_name=key_name, output_filename=output_filename
    )
