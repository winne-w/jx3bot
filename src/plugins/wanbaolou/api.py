import asyncio
import ssl
import os
import time
from typing import Optional, Dict, List, Any, Union
from datetime import datetime
from pathlib import Path
import re
import httpx
from httpx import HTTPError, ConnectError, ReadTimeout, Response

from src.plugins.wanbaolou.config import config

import logging

# 创建logger
logger = logging.getLogger("jx3_trade")
# 缓存实现
class SimpleCache:
    def __init__(self, cache_ttl=300):
        self.cache = {}
        self.ttl = cache_ttl

    def get(self, key):
        """获取缓存内容，如果过期则返回None"""
        if key not in self.cache:
            return None

        data, expire_time = self.cache[key]
        if time.time() > expire_time:
            del self.cache[key]
            return None

        return data

    def set(self, key, value, ttl=None):
        """设置缓存内容及过期时间"""
        expire_time = time.time() + (ttl if ttl is not None else self.ttl)
        self.cache[key] = (value, expire_time)

    def clear(self):
        """清空缓存"""
        self.cache.clear()


# 创建缓存实例
cache = SimpleCache(cache_ttl=config.jx3_api_cache_ttl)


class JX3TradeAPI:
    """剑网3万宝楼交易API"""

    def __init__(self, timeout=None, retry_times=None, verify_ssl=True):
        """初始化API客户端"""
        self.verify_ssl = verify_ssl  # 添加这一行！
        self.timeout = timeout or config.jx3_api_timeout
        self.retry_times = retry_times or config.jx3_api_retry_times
        self.retry_delay = config.jx3_api_retry_delay
        self.base_url = config.jx3_api_base_url
        self.cdn_base_url = config.jx3_cdn_base_url
        self.endpoints = config.jx3_api_endpoints

        # 创建异步HTTP客户端
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            verify=verify_ssl,
            follow_redirects=True
        )

    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()

    async def _make_request(self, url, params=None, method="GET", cache_key=None):
        """发送HTTP请求并处理重试逻辑"""
        # 检查缓存
        if cache_key and method == "GET":
            cached_data = cache.get(cache_key)
            if cached_data:
                return cached_data

        # 发起请求
        for attempt in range(self.retry_times):
            try:
                if method == "GET":
                    response = await self.client.get(url, params=params)
                elif method == "POST":
                    response = await self.client.post(url, json=params)
                else:
                    raise ValueError(f"不支持的HTTP方法: {method}")

                # 检查状态码
                response.raise_for_status()

                # 解析JSON响应
                data = response.json()

                # 如果需要，更新缓存
                if cache_key and method == "GET":
                    cache.set(cache_key, data)

                return data

            except (ConnectError, ReadTimeout, ssl.SSLError) as e:
                # 网络连接错误
                if attempt == self.retry_times - 1:
                    raise Exception(f"网络连接失败: {str(e)}")
                await asyncio.sleep(self.retry_delay)

            except HTTPError as e:
                # HTTP错误
                status_code = getattr(response, 'status_code', None)
                if attempt == self.retry_times - 1:
                    raise Exception(f"HTTP请求失败: {status_code} {str(e)}")
                await asyncio.sleep(self.retry_delay)

            except Exception as e:
                # 其他错误
                if attempt == self.retry_times - 1:
                    raise Exception(f"请求失败: {str(e)}")
                await asyncio.sleep(self.retry_delay)

    async def _check_url_exists(self, url):
        """检查URL是否存在"""
        try:
            # 使用HEAD请求检查URL是否存在
            response = await self.client.head(
                url,
                timeout=5.0,
                follow_redirects=True
            )
            return response.status_code == 200
        except Exception:
            return False

    def _format_time(self, seconds):
        """将秒转换为更易读的时间格式 (小时:分钟:秒)"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60

        return f"{hours}时{minutes}分{seconds}秒"
    async def get_server_list(self):
        """获取服务器列表"""
        # 构建缓存键
        cache_key = "server_list"

        # 构建请求URL
        url = f"{self.base_url}/goods/server_list"

        # 发送请求
        response_data = await self._make_request(url, cache_key=cache_key)

        # 处理响应
        if response_data and response_data.get("code") == 1:
            return response_data.get("data", {}).get("server_list", [])
        else:
            error_msg = response_data.get("msg", "未知错误")
            raise Exception(f"获取服务器列表失败: {error_msg}")

    async def get_item_list(self, item_name=None, sort_type=None,
                            status_filter=None, min_price=None, max_price=None,
                            page=1, page_size=5, follow_sort=None, parse_data=True):
        """获取物品列表"""
        # 使用配置的端点
        url = f"{self.base_url}{self.endpoints['item_list']}"

        # 构建查询参数
        params = {
            "game_id": "jx3",
            "goods_type": 3,
            "page": page,
            "size": page_size
        }

        # 设置状态过滤
        if status_filter is not None:
            params["filter[state]"] = status_filter
        else:
            params["filter[state]"] = 0

        # 设置外观名称
        if item_name:
            params["filter[role_appearance]"] = item_name

        # 设置价格区间
        if min_price is not None and max_price is not None:
            params["filter[price]"] = f"{min_price},{max_price}"

        # 设置排序方式
        if sort_type is not None:
            params["sort[price]"] = sort_type

        # 关注度排序
        if follow_sort is not None:
            params["sort[followed_num]"] = follow_sort

        # 构建缓存键
        cache_key = f"item_list_{item_name}_{sort_type}_{status_filter}_{min_price}_{max_price}_{page}_{page_size}_{follow_sort}"

        # 发送请求
        response_data = await self._make_request(url, params, cache_key=cache_key)

        # 处理响应
        if response_data and response_data.get("code") == 1:
            data = response_data.get("data", {})

            # 如果需要解析数据
            if parse_data:
                result = {
                    "total_items": data.get("total_record", 0),
                    "current_page": data.get("current_page", 1),
                    "total_pages": data.get("total_page", 0),
                    "parsed_items": []
                }

                # 解析每个物品数据
                for item in data.get("list", []):
                    parsed_item = {
                        "name": item.get("info", ""),
                        "type": item.get("attrs", {}).get("appearance_type_name", ""),
                        "seller": item.get("seller_role_name", ""),
                        "price": item.get("single_unit_price", 0) / 100,
                        "remaining_time": item.get("remaining_time", 0),
                        "formatted_time": self._format_time(item.get("remaining_time", 0)),
                        "follows": item.get("followed_num", 0),
                        "server": item.get("server_name", ""),
                        "is_new": bool(item.get("is_new", 0)),
                        "thumb": item.get("thumb", ""),
                        "id": item.get("consignment_id", "")
                    }
                    result["parsed_items"].append(parsed_item)

                return result

            # 不解析，直接返回原始数据
            return data
        else:
            error_msg = response_data.get("msg", "未知错误")
            raise Exception(f"获取物品列表失败: {error_msg}")

    async def get_item_detail(self, item_id):
        """获取物品详情"""
        # 构建请求URL
        url = f"{self.base_url}{self.endpoints['item_detail']}"

        # 构建请求参数
        params = {
            "goods_id": item_id
        }

        # 构建缓存键
        cache_key = f"item_detail_{item_id}"

        # 发送请求
        response_data = await self._make_request(url, params, cache_key=cache_key)

        # 处理响应
        if response_data and response_data.get("code") == 1:
            return response_data.get("data", {})
        else:
            error_msg = response_data.get("msg", "未知错误")
            raise Exception(f"获取物品详情失败: {error_msg}")

    async def get_item_image(self, item_name):
        """获取物品图片URL并下载到本地缓存，返回文件名"""
        # 确保缓存目录存在
        cache_dir = Path("mpimg/wanbaolou")
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 生成安全的文件名
        safe_filename = re.sub(r'[\\/:*?"<>|]', '_', item_name)
        file_name = f"{safe_filename}.png"
        local_path = cache_dir / file_name
        base_url = f"{config.local_server_url}/wanbaolou"

        # 检查本地缓存
        if local_path.exists():
            logger.debug(f"使用本地缓存图片: {file_name}")
            return f"{base_url}/{file_name}"

        # 尝试所有模板
        for template in config.jx3_item_image_templates:
            try:
                image_url = template.format(cdn_base=self.cdn_base_url, item_name=item_name)

                # 先检查URL是否存在
                exists = False
                try:
                    async with httpx.AsyncClient(verify=False) as client:
                        head_response = await client.head(image_url, timeout=10)
                        exists = head_response.status_code == 200
                except Exception as e:
                    logger.debug(f"检查URL {image_url} 失败: {e}")
                    continue

                if not exists:
                    continue

                # URL有效，下载图片
                async with httpx.AsyncClient(verify=False) as client:
                    response = await client.get(image_url, timeout=10)
                    if response.status_code == 200:
                        # 保存到本地
                        local_path.write_bytes(response.content)
                        logger.info(f"图片已下载到: {file_name}")
                        return f"{base_url}/{file_name}"
            except Exception as e:
                logger.error(f"处理图片URL {image_url} 时出错: {e}")
                # 继续尝试下一个模板

        # 如果所有模板都失败，返回指定的默认URL格式
        logger.warning(f"未能获取物品 '{item_name}' 的图片，使用默认路径")
        return f"{config.local_server_url}/bg-empty.png"








# 创建全局API实例，禁用SSL验证
api = JX3TradeAPI(verify_ssl=False)


# 导出搜索函数
async def search_jx3_appearances(item_name, sort_type=None,
                                 status_filter=0, min_price=None, max_price=None,
                                 follow_sort=None, parse_data=True):
    """搜索剑网3外观"""
    try:
        result = await api.get_item_list(
            item_name=item_name,
            sort_type=sort_type,
            status_filter=status_filter,
            min_price=min_price,
            max_price=max_price,
            follow_sort=follow_sort,
            parse_data=parse_data
        )

        # 返回解析结果或物品列表
        return result
    except Exception as e:
        # 出错时返回空结果
        if parse_data:
            return {"total_items": 0, "current_page": 1, "total_pages": 0, "parsed_items": []}
        else:
            return {"list": []}