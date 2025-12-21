import time

import httpx
from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.params import CommandArg

from src.services.jx3.singletons import group_config_repo

from .jobs import (
    extract_version,
    format_gte_message,
    format_time,
    get_gte_data,
    get_jx3box_data,
    get_server_banben,
    get_server_status,
)
try:
    from config import calendar_URL
except Exception:
    calendar_URL = ""


BASE_URL = "https://music.xxxxx.cn:88"
ADMIN_USERNAME = "useradmin"
ADMIN_PASSWORD = "useradmin"


# 查魔盒奖励
gte_cmd = on_regex(r"^\s*奖励\s*$", priority=5)


@gte_cmd.handle()
async def handle_codes(event: GroupMessageEvent):
    try:
        response = await get_jx3box_data()
        if not response or "data" not in response or "list" not in response["data"]:
            await gte_cmd.finish("暂无可用兑换码，请稍后再试")
            return

        codes = response["data"]["list"]
        if not codes:
            await gte_cmd.finish("当前没有可用的兑换码")
            return

        reply_msg = ""
        for i, code in enumerate(codes[:8]):
            title = code.get("title", "未知活动")
            desc = code.get("desc", "无描述")
            created_at = code.get("created_at", "").replace("T", " ").replace("Z", "")
            reply_msg += f"{i + 1}. 奖励: {desc}\n   兑换码: {title}\n   创建时间: {created_at}\n\n"

        await gte_cmd.finish(reply_msg)
    except Exception as e:
        print(e)


# 查询日常
gte_cmd = on_regex(r"^\s*日常\s*$", priority=5)


@gte_cmd.handle()
async def handle_daily(event: GroupMessageEvent):
    try:
        gid = str(event.group_id)
        cfg = group_config_repo.load()

        if gid not in cfg:
            await gte_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

        server = ""
        if isinstance(cfg[gid], dict) and "servers" in cfg[gid]:
            server = cfg[gid]["servers"]
        elif isinstance(cfg[gid], list) and cfg[gid]:
            server = cfg[gid][0]

        if not server:
            await gte_cmd.finish("未找到绑定的服务器")

        gte_data = await get_gte_data(url=calendar_URL, server=server)
        if not gte_data:
            await gte_cmd.finish(f"获取服务器 {server} 的日常数据失败")

        message = format_gte_message(gte_data)
        await gte_cmd.finish(message)
    except Exception as e:
        print(f"查询出错: {e}")


# 主动查询开服
gtekf_cmd = on_regex(r"^\s*开服\s*$", priority=5)


@gtekf_cmd.handle()
async def handle_kf_query(event: GroupMessageEvent):
    try:
        gid = str(event.group_id)
        cfg = group_config_repo.load()

        if gid not in cfg:
            await gtekf_cmd.send("请先绑定服务器，如: /绑定 梦江南")
            return

        server = ""
        if isinstance(cfg[gid], dict) and "servers" in cfg[gid]:
            server = cfg[gid]["servers"]
        elif isinstance(cfg[gid], list) and cfg[gid]:
            server = cfg[gid][0]

        if not server:
            await gtekf_cmd.send("未找到绑定的服务器")
            return

        gte_data = await get_gte_data(url="https://www.jx3api.com/data/server/status", server=server)
        if not gte_data or "data" not in gte_data:
            await gtekf_cmd.send(f"获取服务器 {server} 的开服数据失败")
            return

        server_data = gte_data["data"]

        real_time_status = server_data.get("status", "未知")

        zone = server_data["zone"]
        if zone.endswith("区"):
            zone = zone[:-1] + "大区"

        status_history = CacheManager.load_cache("status_history", {})

        if server not in status_history:
            status_history[server] = {"last_maintenance": None, "last_open": None}

        last_maintenance_time = status_history[server].get("last_maintenance")
        last_open_time = status_history[server].get("last_open")

        maintenance_time_str = "无记录" if last_maintenance_time is None else format_time(last_maintenance_time)
        open_time_str = "无记录" if last_open_time is None else format_time(last_open_time)

        try:
            banben = await get_server_banben()
            banben = extract_version(banben)
        except Exception as e:
            print(f"获取版本号出错: {e}")
            banben = "未知"

        if real_time_status != "维护":
            message = (
                f"{zone}：{server}「 已开服 」\n"
                f"当前状态：{real_time_status}\n"
                f"开服时间：{open_time_str}\n"
                f"维护时间：{maintenance_time_str}"
            )
        else:
            message = (
                f"{zone}：{server}「 维护中 」\n"
                f"维护时间：{maintenance_time_str}\n"
                f"上次开服：{open_time_str}"
            )

        if banben != "未知":
            message += f"\n最新版本：{banben}"

        await gtekf_cmd.send(message)

    except Exception as e:
        print(f"查询开服信息出错: {e}")
        await gtekf_cmd.send("查询服务器状态时出错，请联系管理员")


kftoggle_cmd = on_command("开服推送", priority=5)


@kftoggle_cmd.handle()
async def kfhandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = group_config_repo.load()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await kftoggle_cmd.finish("用法: /开服推送 开启/关闭")

    if gid not in cfg:
        await kftoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    if isinstance(cfg[gid], list):
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "开服推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        servers = []
        for key in cfg[gid]:
            if key != "开服推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "开服推送": cfg[gid].get("开服推送", True)}

    if status == "开启":
        cfg[gid]["开服推送"] = True
        group_config_repo.save(cfg)
        await kftoggle_cmd.finish("已开启本群开服推送功能")
    elif status == "关闭":
        cfg[gid]["开服推送"] = False
        group_config_repo.save(cfg)
        await kftoggle_cmd.finish("已关闭本群开服推送功能")
    else:
        await kftoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


xwtoggle_cmd = on_command("新闻推送", priority=5)


@xwtoggle_cmd.handle()
async def xwhandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = group_config_repo.load()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await xwtoggle_cmd.finish("用法: /新闻推送 开启/关闭")

    if gid not in cfg:
        await xwtoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    if isinstance(cfg[gid], list):
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "新闻推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        servers = []
        for key in cfg[gid]:
            if key != "新闻推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "新闻推送": cfg[gid].get("新闻推送", True)}

    if status == "开启":
        cfg[gid]["新闻推送"] = True
        group_config_repo.save(cfg)
        await xwtoggle_cmd.finish("已开启本群新闻推送功能")
    elif status == "关闭":
        cfg[gid]["新闻推送"] = False
        group_config_repo.save(cfg)
        await xwtoggle_cmd.finish("已关闭本群新闻推送功能")
    else:
        await xwtoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


xwtoggle_cmd = on_command("福利推送", priority=5)


@xwtoggle_cmd.handle()
async def welfare_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = group_config_repo.load()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await xwtoggle_cmd.finish("用法: /福利推送 开启/关闭")

    if gid not in cfg:
        await xwtoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    if isinstance(cfg[gid], list):
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "福利推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        servers = []
        for key in cfg[gid]:
            if key != "福利推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "福利推送": cfg[gid].get("福利推送", True)}

    if status == "开启":
        cfg[gid]["福利推送"] = True
        group_config_repo.save(cfg)
        await xwtoggle_cmd.finish("已开启本群福利推送功能")
    elif status == "关闭":
        cfg[gid]["福利推送"] = False
        group_config_repo.save(cfg)
        await xwtoggle_cmd.finish("已关闭本群福利推送功能")
    else:
        await xwtoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


jgtoggle_cmd = on_command("技改推送", priority=5)


@jgtoggle_cmd.handle()
async def jghandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = group_config_repo.load()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await jgtoggle_cmd.finish("用法: /技改推送 开启/关闭")

    if gid not in cfg:
        await jgtoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    if isinstance(cfg[gid], list):
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "技改推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        servers = []
        for key in cfg[gid]:
            if key != "技改推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "技改推送": cfg[gid].get("技改推送", True)}

    if status == "开启":
        cfg[gid]["技改推送"] = True
        group_config_repo.save(cfg)
        await jgtoggle_cmd.finish("已开启本群技改推送功能")
    elif status == "关闭":
        cfg[gid]["技改推送"] = False
        group_config_repo.save(cfg)
        await jgtoggle_cmd.finish("已关闭本群技改推送功能")
    else:
        await jgtoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


rctoggle_cmd = on_command("日常推送", priority=5)


@rctoggle_cmd.handle()
async def rchandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = group_config_repo.load()
    gid = str(event.group_id)
    status = args.extract_plain_text().strip()

    if not status:
        await rctoggle_cmd.finish("用法: /日常推送 开启/关闭")

    if gid not in cfg:
        await rctoggle_cmd.finish("请先绑定服务器，如: /绑定 梦江南")

    if isinstance(cfg[gid], list):
        servers = cfg[gid]
        cfg[gid] = {"servers": servers, "日常推送": True}
    elif isinstance(cfg[gid], dict) and "servers" not in cfg[gid]:
        servers = []
        for key in cfg[gid]:
            if key != "日常推送":
                servers.append(key)
        cfg[gid] = {"servers": servers, "日常推送": cfg[gid].get("日常推送", True)}

    if status == "开启":
        cfg[gid]["日常推送"] = True
        group_config_repo.save(cfg)
        await rctoggle_cmd.finish("已开启本群日常推送功能")
    elif status == "关闭":
        cfg[gid]["日常推送"] = False
        group_config_repo.save(cfg)
        await rctoggle_cmd.finish("已关闭本群日常推送功能")
    else:
        await rctoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


jjctoggle_cmd = on_command("竞技排名推送", priority=5)


@jjctoggle_cmd.handle()
async def jjchandle_toggle(event: GroupMessageEvent, args=CommandArg()):
    cfg = group_config_repo.load()
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
        cfg[gid] = {"servers": servers, "竞技排名推送": cfg[gid].get("竞技排名推送", False)}

    if isinstance(cfg[gid], dict) and "竞技排名推送" not in cfg[gid]:
        cfg[gid]["竞技排名推送"] = False

    if status == "开启":
        cfg[gid]["竞技排名推送"] = True
        group_config_repo.save(cfg)
        await jjctoggle_cmd.finish("已开启本群竞技排名推送功能")
    elif status == "关闭":
        cfg[gid]["竞技排名推送"] = False
        group_config_repo.save(cfg)
        await jjctoggle_cmd.finish("已关闭本群竞技排名推送功能")
    else:
        await jjctoggle_cmd.finish("参数错误，请使用'开启'或'关闭'")


bind_cmd = on_command("绑定", priority=5)


@bind_cmd.handle()
async def handle_bind(event: GroupMessageEvent, args=CommandArg()):
    server = args.extract_plain_text().strip()
    if not server:
        await bind_cmd.finish("用法: /绑定 服务器名")

    data = await get_server_status()
    if data:
        server_exists = any(s.get("server") == server for s in data.get("data", []))
        if not server_exists:
            await bind_cmd.finish(f"服务器 {server} 不存在")

    cfg = group_config_repo.load()
    gid = str(event.group_id)
    cfg[gid] = {
        "servers": server,
        "开服推送": True,
        "福利推送": True,
        "技改推送": True,
        "新闻推送": True,
        "日常推送": True,
        "竞技排名推送": False,
    }
    group_config_repo.save(cfg)
    await bind_cmd.finish(
        f"已绑定服务器: {server}\n"
        f"已默认开启：开服推送、福利推送、技改推送、新闻推送、日常推送\n"
        f"默认关闭：竞技排名推送，可使用「/竞技排名推送 开启」启用每日统计"
    )


unbind_cmd = on_command("解绑", aliases={"解除绑定"}, priority=5)


@unbind_cmd.handle()
async def handle_unbind(event: GroupMessageEvent):
    cfg = group_config_repo.load()
    gid = str(event.group_id)

    if gid not in cfg:
        await unbind_cmd.finish("当前群未绑定任何服务器")

    server = cfg[gid].get("servers", "未知服务器")
    del cfg[gid]
    group_config_repo.save(cfg)

    await unbind_cmd.finish(f"已解除与服务器 {server} 的绑定\n所有推送功能已关闭")


list_cmd = on_command("查看绑定", aliases={"服务器列表"}, priority=5)


@list_cmd.handle()
async def handle_list(event: GroupMessageEvent):
    gid = str(event.group_id)
    cfg = group_config_repo.load()

    if gid not in cfg:
        await list_cmd.finish("本群未绑定任何服务器")

    config = cfg[gid]

    if isinstance(config, dict):
        server = config.get("servers", "无")

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
        servers = config if isinstance(config, list) else []
        if not servers:
            await list_cmd.finish("本群未绑定任何服务器")

        await list_cmd.finish(f"绑定服务器：{', '.join(servers)}\n(使用旧版格式，建议重新绑定)")


reg_cmd = on_command("注册", priority=5)


@reg_cmd.handle()
async def handle_register(bot: Bot, event: GroupMessageEvent):
    user_id = str(event.user_id)

    await reg_cmd.send("正在处理注册请求，请稍候...")

    username = f"qq{user_id}"
    email = f"{user_id}@qq.com"

    success, result = await register_user(ADMIN_USERNAME, ADMIN_PASSWORD, username, email)

    if success:
        try:
            await bot.send_private_msg(
                user_id=int(user_id),
                message=(
                    "恭喜，注册成功！以下是您的账号信息：\n"
                    f"用户名: {result.get('username')}\n"
                    f"密码: {result.get('password')}\n"
                    f"网站: {BASE_URL}\n"
                    "云音乐服务器: ipv4.xohome.cn:88[https连接方式]\n"
                    "若需使用自建云音乐，可从设置开启，建议b站找一找Navidrome的使用教程，连接上服务器在进行推送音乐！"
                ),
            )

            await reg_cmd.finish("注册成功！账号信息已通过私聊发送。")

        except Exception:
            print("注册成功")

    else:
        await reg_cmd.finish(result)


async def login_admin(admin_username, admin_password):
    url = f"{BASE_URL}/api/login"

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                url,
                json={"username": admin_username, "password": admin_password},
                headers={"Content-Type": "application/json"},
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
    login_success, token, user_info = await login_admin(admin_username, admin_password)

    if not login_success:
        return False, "网站挂了，等待重启恢复再注册！"

    if not user_info or not user_info.get("is_admin", False):
        return False, "账号无管理员权限，无法邀请新用户"

    url = f"{BASE_URL}/api/register"

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                url,
                json={"username": new_username, "email": email},
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                cookies={"token": token},
            )

            try:
                result = response.json()
            except Exception:
                result = {"code": response.status_code, "message": "无法解析服务器响应"}

            if response.status_code == 400:
                return False, "该账号已注册，若您忘记密码可查看私聊或邮件！"
            elif response.status_code == 500:
                return False, "服务器内部错误，请稍后再试"
            elif response.status_code in {502, 503, 504}:
                return False, "网站暂时连接不上，请稍后再试"
            elif response.status_code != 200:
                return False, f"注册失败，错误码: {response.status_code}"

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
