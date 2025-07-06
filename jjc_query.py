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
                "second_request_time": second_response_time
            }
            
            print(f"合并完成，总共获取到 {len(all_data)} 条排行榜数据")
            if second_response_time:
                print(f"第二次请求时间戳: {second_response_time}")
            
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
        result = asyncio.run(query_jjc_ranking(
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
    else:
        print(json_str)


if __name__ == "__main__":
    main() 