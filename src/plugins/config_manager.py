import re
import os
import sys
import json
import time
import subprocess
import asyncio
from config import ADMIN_QQ  # 从config.py导入管理员QQ列表
from nonebot import on_command, get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent, Bot
from nonebot.params import CommandArg
import src.utils.shared_data


# 配置文件路径
CONFIG_FILE = "config.py"
RESTART_FLAG_FILE = "restart_info.json"

# 存储待发送的重启通知
pending_restart_info = None

# 读取配置文件
def read_config_file():
    if not os.path.exists(CONFIG_FILE):
        return "配置文件不存在"
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"读取配置文件失败: {e}"

# 写入配置文件
def write_config_file(content):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        return f"写入配置文件失败: {e}"

# 记录重启信息并执行重启
async def restart_bot(group_id=None, user_id=None, reason="手动重启"):
    try:
        # 记录重启信息
        restart_info = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason
        }
        
        if group_id:
            restart_info["group_id"] = group_id
        if user_id:
            restart_info["user_id"] = user_id
        
        # 写入重启信息到标记文件
        with open(RESTART_FLAG_FILE, "w", encoding="utf-8") as f:
            json.dump(restart_info, f, ensure_ascii=False, indent=2)
        
        print(f"已记录重启信息: {restart_info}")
        
        # 使用子进程启动新实例
        print("准备重启机器人...")
        
        # 获取当前脚本路径
        current_path = os.path.abspath(sys.argv[0])
        
        # 等待2秒，确保消息发送完成
        await asyncio.sleep(2)
        
        # 创建一个新的进程来启动机器人
        if sys.platform == 'win32':
            # Windows平台
            subprocess.Popen(f'python "{current_path}"', shell=True)
        else:
            # Linux/MacOS平台
            subprocess.Popen(f'python3 "{current_path}" &', shell=True)
        
        # 退出当前进程
        print("即将退出当前进程...")
        await asyncio.sleep(1)
        os._exit(0)
        
    except Exception as e:
        print(f"重启失败: {e}")
        return f"重启失败: {e}"

# 启动事件处理
driver = get_driver()

@driver.on_startup
async def startup_handler():
    """机器人启动时检查是否需要发送重启通知"""
    print("机器人启动中，检查重启标记...")
    
    # 检查重启标记文件
    if os.path.exists(RESTART_FLAG_FILE):
        print(f"找到重启标记文件: {RESTART_FLAG_FILE}")
        try:
            # 读取重启信息
            with open(RESTART_FLAG_FILE, "r", encoding="utf-8") as f:
                restart_info = json.load(f)
            
            print(f"重启信息: {restart_info}")
            
            # 保存待发送的重启信息，等待连接建立后回复
            global pending_restart_info
            pending_restart_info = restart_info
            print("已记录待发送的重启通知，等待 WebSocket 连接完成后发送")
        except Exception as e:
            print(f"处理重启标记失败: {e}")

@driver.on_bot_connect
async def handle_bot_connect(bot: Bot):
    """WebSocket 连接建立后发送重启完成通知"""
    global pending_restart_info

    try:
        # 如果内存中暂无信息但仍存在标记文件，则尝试加载一次
        if pending_restart_info is None and os.path.exists(RESTART_FLAG_FILE):
            with open(RESTART_FLAG_FILE, "r", encoding="utf-8") as f:
                pending_restart_info = json.load(f)
            print(f"从文件补充待发送的重启信息: {pending_restart_info}")

        if not pending_restart_info:
            return

        restart_info = pending_restart_info
        pending_restart_info = None

        restart_reason = restart_info.get("reason", "未知原因")
        group_id = restart_info.get("group_id")
        user_id = restart_info.get("user_id")

        message = f"启动完成，重启原因: {restart_reason}"

        if group_id:
            print(f"准备向群{group_id}发送重启完成通知")
            await bot.send_group_msg(group_id=int(group_id), message=message)
            print(f"已向群{group_id}发送重启完成通知")
        elif user_id:
            print(f"准备向用户{user_id}发送重启完成通知")
            await bot.send_private_msg(user_id=int(user_id), message=message)
            print(f"已向用户{user_id}发送重启完成通知")
        else:
            print("未找到群组或用户 ID，跳过重启通知发送")
    except Exception as e:
        print(f"发送重启通知时出错: {e}")
    finally:
        if os.path.exists(RESTART_FLAG_FILE):
            os.remove(RESTART_FLAG_FILE)
            print(f"已删除重启标记文件: {RESTART_FLAG_FILE}")

# 查看配置命令
view_config_cmd = on_command("查看配置", priority=5)
@view_config_cmd.handle()
async def handle_view_config(event):
    # 检查权限
    user_id = event.get_user_id()
    if int(user_id) not in ADMIN_QQ:
        await view_config_cmd.finish("您没有权限查看配置")
    
    # 读取配置文件
    config_content = read_config_file()
    if isinstance(config_content, str) and config_content.startswith("配置文件"):
        await view_config_cmd.finish(config_content)
    
    # 解析配置内容，提取关键配置项
    config_info = ""
    allowed_keys = [ "TICKET", "SESSION_data", "calendar_time", "STATUS_check_time"]
    
    for line in config_content.splitlines():
        for key in allowed_keys:
            if re.match(rf"{key}\s*=", line):
                config_info += line.strip() + "\n"
    
    await view_config_cmd.finish(f"当前配置:\n token剩余:{src.utils.shared_data.tokendata}\n{config_info}")

# 修改配置命令
config_cmd = on_command("修改配置", priority=5)
@config_cmd.handle()
async def handle_config(event, args=CommandArg()):
    # 检查权限
    user_id = event.get_user_id()
    if int(user_id) not in ADMIN_QQ:
        await config_cmd.finish("您没有权限修改配置")
    
    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await config_cmd.finish("用法: /修改配置 配置项=值\n可修改的配置项: TOKEN, TICKET, SESSION_data, calendar_time, STATUS_check_time")
    
    # 解析配置项和值
    try:
        key, value = arg_text.split('=', 1)
        key = key.strip()
        value = value.strip()
    except:
        await config_cmd.finish("格式错误，正确格式: 配置项=值")
    
    # 检查配置项是否允许修改
    allowed_keys = ["TOKEN", "TICKET", "SESSION_data", "calendar_time", "STATUS_check_time"]
    if key not in allowed_keys:
        await config_cmd.finish(f"不允许修改该配置项，允许的配置项: {', '.join(allowed_keys)}")
    
    # 读取当前配置
    config_content = read_config_file()
    if isinstance(config_content, str) and config_content.startswith("配置文件"):
        await config_cmd.finish(config_content)
    
    # 修改配置
    new_content = ""
    key_found = False
    
    for line in config_content.splitlines():
        # 查找并替换配置行
        if re.match(rf"{key}\s*=", line):
            # 根据配置项类型调整格式化方式
            if key in ["TOKEN", "TICKET", "SESSION_data"]:
                # 字符串类型的配置
                new_line = f'{key} = "{value}"'
            else:
                # 数值类型的配置
                new_line = f"{key} = {value}"
            
            new_content += new_line + "\n"
            key_found = True
        else:
            new_content += line + "\n"
    
    # 如果配置项不存在，添加到文件末尾
    if not key_found:
        if key in ["TOKEN", "TICKET", "SESSION_data"]:
            new_content += f'\n{key} = "{value}"\n'
        else:
            new_content += f"\n{key} = {value}\n"
    
    # 写入配置文件
    result = write_config_file(new_content)
    if result is not True:
        await config_cmd.finish(result)
    
    # 获取群组ID
    group_id = None
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
    
    # 告知用户配置已更新，并自动重启
    await config_cmd.send(f"配置项 {key} 已更新为 {value}，正在重启机器人...")
    await restart_bot(group_id=group_id, user_id=user_id, reason=f"修改配置 {key}={value}")

# 添加重启命令
restart_cmd = on_command("重启", priority=5)
@restart_cmd.handle()
async def handle_restart(event, args=CommandArg()):
    # 检查权限
    user_id = event.get_user_id()
    if int(user_id) not in ADMIN_QQ:
        await restart_cmd.finish("您没有权限重启机器人")
    
    # 获取重启原因
    reason = args.extract_plain_text().strip()
    if not reason:
        reason = "手动重启"
    
    # 获取群组ID
    group_id = None
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
    
    # 告知用户正在重启
    await restart_cmd.send(f"正在重启机器人，原因: {reason}")
    await restart_bot(group_id=group_id, user_id=user_id, reason=reason)
