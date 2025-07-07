#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剑网3竞技场数据查询脚本
直接请求JJC数据接口并输出原始JSON结果
"""

import asyncio
import aiohttp
import json
import sys
import argparse
import os
import time
import random
from typing import Optional

# 导入配置文件
from config import TOKEN, TICKET


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
    
    return result


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='剑网3竞技场数据查询工具')
    parser.add_argument('--ranking', action='store_true', help='查询竞技场排行榜数据')
    parser.add_argument('server', nargs='?', help='服务器名称 (例如: 梦江南)')
    parser.add_argument('name', nargs='?', help='角色名称')
    parser.add_argument('--token', help='API认证令牌（可选，默认从config文件获取）')
    parser.add_argument('--ticket', help='推栏cookie（可选，默认从config文件获取）')
    parser.add_argument('--pretty', action='store_true', help='格式化输出JSON (美化显示)')
    parser.add_argument('--output', help='输出到文件 (可选)')
    
    args = parser.parse_args()
    
    # 检查参数
    if args.ranking:
        # 查询排行榜数据
        ranking_result = asyncio.run(query_jjc_ranking(
            token=args.token,
            ticket=args.ticket
        ))
        # 获取排行榜数据的kuangfu信息
        result = asyncio.run(get_ranking_kuangfu_data(
            ranking_data=ranking_result,
            token=args.token,
            ticket=args.ticket
        ))
    else:
        # 查询个人数据
        if not args.server or not args.name:
            print("错误: 查询个人数据需要提供服务器名称和角色名称")
            print("用法: python jjc_query.py 服务器名 角色名")
            print("或者: python jjc_query.py --ranking (查询排行榜)")
            sys.exit(1)
        
        result = asyncio.run(query_jjc_data(
            server=args.server,
            name=args.name,
            token=args.token,
            ticket=args.ticket
        ))
    
    # 格式化输出
    if args.pretty:
        json_str = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        json_str = json.dumps(result, ensure_ascii=False)
    
    # 输出结果
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(json_str)
            print(f"结果已保存到文件: {args.output}")
        except Exception as e:
            print(f"保存文件失败: {e}")
            print(json_str)
    # else:
        # print(json_str)
    # todo


if __name__ == "__main__":
    main() 