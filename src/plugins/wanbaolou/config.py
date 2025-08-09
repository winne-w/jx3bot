from nonebot import get_driver
from pydantic import BaseModel


class Config(BaseModel):
    """配置类"""
    # API配置
    jx3_api_timeout: int = 10
    jx3_api_retry_times: int = 3
    jx3_api_retry_delay: int = 1
    jx3_api_cache_ttl: int = 300

    # API基础URL
    jx3_api_base_url: str = "https://trade-api.seasunwbl.com/api/buyer"
    jx3_cdn_base_url: str = "https://dl.pvp.xoyo.com/prod/icons"

    # 接口路径配置
    jx3_api_endpoints: dict = {
        "item_list": "/goods/list",
        "item_detail": "/goods/summary_data",
    }

    # 备用图片URL模板
    jx3_item_image_templates: list = [
        "{cdn_base}/handbook/image/{item_name}-详情-1.png",
        "{cdn_base}/handbook/image/{item_name}-详情-2.png",

    ]

    # 本地服务器配置
    local_server_url: str = "http://127.0.0.1:8000"


# 全局配置
driver = get_driver()
global_config = driver.config

# 创建配置实例
config = Config()

# 从NoneBot全局配置加载
if hasattr(global_config, "jx3_api_timeout"):
    config.jx3_api_timeout = global_config.jx3_api_timeout
if hasattr(global_config, "jx3_api_retry_times"):
    config.jx3_api_retry_times = global_config.jx3_api_retry_times
if hasattr(global_config, "jx3_api_retry_delay"):
    config.jx3_api_retry_delay = global_config.jx3_api_retry_delay
if hasattr(global_config, "jx3_api_cache_ttl"):
    config.jx3_api_cache_ttl = global_config.jx3_api_cache_ttl
if hasattr(global_config, "jx3_api_base_url"):
    config.jx3_api_base_url = global_config.jx3_api_base_url
if hasattr(global_config, "jx3_cdn_base_url"):
    config.jx3_cdn_base_url = global_config.jx3_cdn_base_url
if hasattr(global_config, "jx3_api_endpoints"):
    config.jx3_api_endpoints = global_config.jx3_api_endpoints
if hasattr(global_config, "jx3_item_image_templates"):
    config.jx3_item_image_templates = global_config.jx3_item_image_templates
if hasattr(global_config, "local_server_url"):
    config.local_server_url = global_config.local_server_url