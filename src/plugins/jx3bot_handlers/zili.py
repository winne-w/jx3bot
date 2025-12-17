from __future__ import annotations

import time
from typing import Any, Annotated

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import RegexGroup

from config import SESSION_TIMEOUT, TICKET, TOKEN, API_URLS
from src.renderers.jx3.image import render_template_image, send_image, send_text
from src.services.jx3.command_context import fetch_jx3api_or_reply_error, resolve_server_and_name
from src.utils.defget import sum_specified_keys, suijitext
from src.utils.shared_data import SEARCH_RESULTS, user_sessions


def register(zili_matcher: Any, zili_choice_matcher: Any, env: Environment, *, max_depth: int) -> None:
    def check_valid_items(items_data: Any) -> bool:
        if items_data is None:
            return False
        if not isinstance(items_data, dict) or len(items_data) == 0:
            return False
        valid_count = 0
        for item in items_data.keys():
            if isinstance(items_data[item], dict):
                valid_count += 1
                if valid_count >= 2:
                    return True
        return False

    def get_current_data(user_id: str) -> dict[str, Any]:
        if "nav_path" not in user_sessions[user_id] or len(user_sessions[user_id]["nav_path"]) == 0:
            return user_sessions[user_id]["data"]

        path = user_sessions[user_id]["nav_path"]
        items = user_sessions[user_id]["items"]
        temp_data = items["data"]["data"]

        if path[0] == "秘境分布":
            temp_data = temp_data["dungeons"]
        elif path[0] == "地图分布":
            temp_data = temp_data["maps"]
        else:
            temp_data = temp_data["total"][path[0]]

        for i in range(1, len(path)):
            if path[i] in temp_data:
                temp_data = temp_data[path[i]]
            else:
                return {}

        my_dict: dict[str, Any] = {}
        for item in temp_data.keys():
            if isinstance(temp_data[item], dict):
                result = sum_specified_keys(temp_data[item], "pieces", "seniority")
                ydcj, wdcj, ydzl, wdzl = result
                jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                my_dict[item] = {
                    "jindu": jindu,
                    "ydcj": ydcj,
                    "wdcj": wdcj,
                    "ydzl": ydzl,
                    "wdzl": wdzl,
                }
        return my_dict

    async def display_zili_overview(bot: Bot, event: Event, user_id: str) -> None:
        items = user_sessions[user_id]["items"]
        data = user_sessions[user_id]["data"]

        text = suijitext()
        tongji = [0, 0, 0, 0, 0, 0]
        tongji[5] = items["data"]["roleName"]

        for item in data.keys():
            tongji[1] += data[item]["ydcj"]
            tongji[2] += data[item]["wdcj"]
            tongji[3] += data[item]["ydzl"]
            tongji[4] += data[item]["wdzl"]

        tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

        image_bytes = await render_template_image(
            env,
            "资历查询.html",
            {"text": text, "tongji": tongji, "items": data},
            width=960,
            height="ck",
        )
        await send_image(bot, event, image_bytes, at_user=False, prefix="   资历总览")
        await bot.send(
            event,
            MessageSegment.at(event.user_id) + Message(f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目"),
        )

    async def navigate_to_path(bot: Bot, event: Event, user_id: str) -> None:
        current_data = get_current_data(user_id)
        path = user_sessions[user_id]["nav_path"]

        if not current_data:
            await bot.send(event, Message("   无法导航到请求的路径，请返回首页"))
            return

        current_location = " > ".join(path)
        items = user_sessions[user_id]["items"]

        tongji = [0, 0, 0, 0, 0, 0]
        tongji[5] = items["data"]["roleName"]
        for item in current_data.values():
            tongji[1] += item["ydcj"]
            tongji[2] += item["wdcj"]
            tongji[3] += item["ydzl"]
            tongji[4] += item["wdzl"]
        tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

        text = suijitext()
        image_bytes = await render_template_image(
            env,
            "资历查询.html",
            {"text": text, "tongji": tongji, "zilizonglan": current_location, "items": current_data},
            width=1120,
            height="ck",
        )
        await send_image(bot, event, image_bytes, at_user=False, prefix=f"   当前位置: {current_location}")

    async def display_item_details(
        bot: Any, event: Any, user_id: str, selected_key: str, selected_item: dict[str, Any]
    ) -> None:
        items = user_sessions[user_id]["items"]
        is_second_level = (
            "nav_path" in user_sessions[user_id]
            and len(user_sessions[user_id]["nav_path"]) > 1
            and user_sessions[user_id]["nav_path"][0] == "秘境分布"
        )

        # 有子项目，获取子项列表
        sub_dict: dict[str, Any] = {}
        temp_data = items["data"]["data"]
        if selected_key == "秘境分布":
            temp_data = temp_data["dungeons"]
        elif selected_key == "地图分布":
            temp_data = temp_data["maps"]
        else:
            temp_data = temp_data["total"].get(selected_key, {})

        for key in temp_data.keys():
            if isinstance(temp_data[key], dict):
                result = sum_specified_keys(temp_data[key], "pieces", "seniority")
                ydcj, wdcj, ydzl, wdzl = result
                jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                sub_dict[key] = {"jindu": jindu, "ydcj": ydcj, "wdcj": wdcj, "ydzl": ydzl, "wdzl": wdzl}

        if not sub_dict:
            sub_dict = {selected_key: selected_item}

        tongji = [0, 0, 0, 0, 0, 0]
        tongji[5] = items["data"]["roleName"]
        tongji[1] = selected_item["ydcj"]
        tongji[2] = selected_item["wdcj"]
        tongji[3] = selected_item["ydzl"]
        tongji[4] = selected_item["wdzl"]
        tongji[0] = round(selected_item["jindu"], 2)

        item_title = f"项目详情: {selected_key}"
        text = suijitext()
        image_bytes = await render_template_image(
            env,
            "资历查询.html",
            {
                "text": text,
                "tongji": tongji,
                "zilizonglan": item_title,
                "items": sub_dict,
                "is_second_level": is_second_level,
            },
            width=800,
            height="ck",
        )
        await send_image(bot, event, image_bytes, at_user=False, prefix=f"   {selected_key} 详细信息")

        if is_second_level:
            user_sessions[user_id]["nav_path"] = [user_sessions[user_id]["nav_path"][0]]
            await bot.send(event, Message(f"   已自动返回到第一层: {user_sessions[user_id]['nav_path'][0]}"))
            await bot.send(
                event,
                MessageSegment.at(event.user_id)
                + Message(f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目！输入：0 返回"),
            )

    async def display_subitems(
        bot: Any, event: Any, user_id: str, selected_key: str, items_data: dict[str, Any]
    ) -> None:
        my_dict: dict[str, Any] = {}
        is_second_level = (
            "nav_path" in user_sessions[user_id]
            and len(user_sessions[user_id]["nav_path"]) > 1
            and user_sessions[user_id]["nav_path"][0] == "秘境分布"
        )

        for item in items_data.keys():
            if isinstance(items_data[item], dict):
                result = sum_specified_keys(items_data[item], "pieces", "seniority")
                ydcj, wdcj, ydzl, wdzl = result
                jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                my_dict[item] = {"jindu": jindu, "ydcj": ydcj, "wdcj": wdcj, "ydzl": ydzl, "wdzl": wdzl}

        if not check_valid_items(items_data):
            if my_dict:
                for key, item in my_dict.items():
                    await display_item_details(bot, event, user_id, key, item)
            if len(user_sessions[user_id]["nav_path"]) > 0:
                user_sessions[user_id]["nav_path"].pop()
            await bot.send(event, Message(f"   {selected_key} 子项目数量不足，已返回上一级"))
            return

        tongji = [0, 0, 0, 0, 0, 0]
        tongji[5] = user_sessions[user_id]["items"]["data"]["roleName"]
        for item in my_dict.values():
            tongji[1] += item["ydcj"]
            tongji[2] += item["wdcj"]
            tongji[3] += item["ydzl"]
            tongji[4] += item["wdzl"]
        tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

        path = user_sessions[user_id]["nav_path"]
        current_location = " > ".join(path)
        text = suijitext()
        width = 225 * len(my_dict) if is_second_level else 1120
        height = 390 if is_second_level else "ck"
        image_bytes = await render_template_image(
            env,
            "资历查询.html",
            {
                "text": text,
                "tongji": tongji,
                "zilizonglan": current_location,
                "items": my_dict,
                "is_second_level": is_second_level,
            },
            width=width,
            height=height,
        )
        await send_image(bot, event, image_bytes, at_user=False, prefix=f"   {selected_key}")

        if is_second_level:
            user_sessions[user_id]["nav_path"] = [user_sessions[user_id]["nav_path"][0]]

        await bot.send(
            event,
            MessageSegment.at(event.user_id)
            + Message(f" 请在{SESSION_TIMEOUT}秒内回复数字查看秘境详情！输入：0 返回总览"),
        )

    @zili_matcher.handle()
    async def zili_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        user_id = str(event.user_id)
        if user_id in SEARCH_RESULTS:
            del SEARCH_RESULTS[user_id]

        resolved = await resolve_server_and_name(bot, event, foo)
        if not resolved:
            return
        server, role_name = resolved

        items = await fetch_jx3api_or_reply_error(
            bot,
            event,
            url=API_URLS["资历查询"],
            server=server,
            name=role_name,
            token=TOKEN,
            ticket=TICKET,
            zili=3,
        )
        if not items:
            return

        if not items.get("data"):
            await bot.send(
                event,
                MessageSegment.at(event.user_id)
                + Message(f"   查询结果: {server}，{role_name}，难道根本没有资历？"),
            )
            return

        itemss = items
        text = suijitext()
        tongji = [0, 0, 0, 0, 0, 0]
        tongji[5] = items["data"]["roleName"]
        total_items = items["data"]["data"]["total"]

        my_dict: dict[str, Any] = {}
        count = 0
        for _ in range(2):
            count += 1
            if count == 2:
                xmldata = "maps"
                xmlmz = "地图分布"
            else:
                xmldata = "dungeons"
                xmlmz = "秘境分布"
            result = sum_specified_keys(itemss["data"]["data"][xmldata], "pieces", "seniority")
            ydcj, wdcj, ydzl, wdzl = result
            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
            my_dict[xmlmz] = {"jindu": jindu, "ydcj": ydcj, "wdcj": wdcj, "ydzl": ydzl, "wdzl": wdzl}

        for item in total_items.keys():
            result = sum_specified_keys(total_items[f"{item}"], "pieces", "seniority")
            ydcj, wdcj, ydzl, wdzl = result
            tongji[1] += ydcj
            tongji[2] += wdcj
            tongji[3] += ydzl
            tongji[4] += wdzl
            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
            my_dict[f"{item}"] = {"jindu": jindu, "ydcj": ydcj, "wdcj": wdcj, "ydzl": ydzl, "wdzl": wdzl}

        tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] else 0

        image_bytes = await render_template_image(
            env,
            "资历查询.html",
            {"text": text, "tongji": tongji, "qufu": server, "items": my_dict},
            width=960,
            height="ck",
        )
        await send_image(bot, event, image_bytes, at_user=False, prefix="   查询结果")

        expiry_time = time.time() + SESSION_TIMEOUT
        user_sessions[user_id] = {"expiry_time": expiry_time, "data": my_dict, "items": itemss, "nav_shown": False}
        await bot.send(
            event, MessageSegment.at(event.user_id) + Message(f"   请在{SESSION_TIMEOUT}秒内回复数字选择要查看的项目")
        )
        user_sessions[user_id]["nav_shown"] = True

    @zili_choice_matcher.handle()
    async def handle_zili_choice(
        bot: Bot, event: Event, choice: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        user_id = str(event.user_id)
        if user_id not in user_sessions:
            return

        if user_id in SEARCH_RESULTS:
            del SEARCH_RESULTS[user_id]

        current_time = time.time()
        if current_time > user_sessions[user_id]["expiry_time"]:
            del user_sessions[user_id]
            await bot.send(event, MessageSegment.at(event.user_id) + Message("   操作已超时，请重新输入资历 ID 查询"))
            return

        number = choice[0]
        if number in ("返回", "back"):
            if "nav_path" in user_sessions[user_id] and len(user_sessions[user_id]["nav_path"]) > 0:
                user_sessions[user_id]["nav_path"].pop()
                if len(user_sessions[user_id]["nav_path"]) == 0:
                    await display_zili_overview(bot, event, user_id)
                else:
                    await navigate_to_path(bot, event, user_id)
                return
            await bot.send(event, Message("   已经在顶层目录，无法返回上一级"))
            return
        if number in ("0", "home"):
            await bot.send(event, Message("已返回资历分布，请输入1-20选择要查看的项目！"))
            if "nav_path" in user_sessions[user_id]:
                user_sessions[user_id]["nav_path"] = []
            return

        try:
            index = int(number) - 1
            current_data = get_current_data(user_id)
            keys = list(current_data.keys())
            if index >= len(keys) or index < 0:
                await bot.send(event, Message(f"   无效的选择，请输入1-{len(keys)}之间的数字"))
                return

            selected_key = keys[index]
            selected_item = current_data[selected_key]
            items = user_sessions[user_id]["items"]
            has_subitems = False

            if "nav_path" not in user_sessions[user_id]:
                user_sessions[user_id]["nav_path"] = []

            if len(user_sessions[user_id]["nav_path"]) == 0:
                if selected_key == "秘境分布":
                    items_data = items["data"]["data"]["dungeons"]
                    if not check_valid_items(items_data):
                        await bot.send(event, Message(f"   {selected_key} 没有可用的子项目，无法进入"))
                        return
                    has_subitems = True
                elif selected_key == "地图分布":
                    items_data = items["data"]["data"]["maps"]
                    map_dict: dict[str, Any] = {}
                    for item in items_data.keys():
                        if isinstance(items_data[item], dict):
                            result = sum_specified_keys(items_data[item], "pieces", "seniority")
                            ydcj, wdcj, ydzl, wdzl = result
                            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                            map_dict[item] = {
                                "jindu": jindu,
                                "ydcj": ydcj,
                                "wdcj": wdcj,
                                "ydzl": ydzl,
                                "wdzl": wdzl,
                            }

                    tongji = [0, 0, 0, 0, 0, 0]
                    tongji[5] = items["data"]["roleName"]
                    for item in map_dict.values():
                        tongji[1] += item["ydcj"]
                        tongji[2] += item["wdcj"]
                        tongji[3] += item["ydzl"]
                        tongji[4] += item["wdzl"]
                    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

                    image_bytes = await render_template_image(
                        env,
                        "资历查询.html",
                        {"text": suijitext(), "tongji": tongji, "zilizonglan": "地图分布", "items": map_dict},
                        width=1120,
                        height="ck",
                    )
                    await send_image(bot, event, image_bytes, at_user=False, prefix="   地图分布")

                    if not user_sessions[user_id].get("nav_shown", True):
                        data_keys = list(user_sessions[user_id]["data"].keys())
                        nav_text = "   首页导航：\n" + "".join(
                            f"   {i}. {key}\n" for i, key in enumerate(data_keys, 1)
                        )
                        nav_text += "   请输入数字选择要查看的项目"
                        await bot.send(event, Message(nav_text))
                        user_sessions[user_id]["nav_shown"] = True

                    user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                    return
                else:
                    items_data = items["data"]["data"]["total"][selected_key]
                    if not check_valid_items(items_data):
                        await display_item_details(bot, event, user_id, selected_key, selected_item)
                        if not user_sessions[user_id].get("nav_shown", True):
                            data_keys = list(user_sessions[user_id]["data"].keys())
                            nav_text = "   首页导航：\n" + "".join(
                                f"   {i}. {key}\n" for i, key in enumerate(data_keys, 1)
                            )
                            nav_text += "   请输入数字选择要查看的项目"
                            await bot.send(event, Message(nav_text))
                            user_sessions[user_id]["nav_shown"] = True
                        user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                        return

                    sub_dict: dict[str, Any] = {}
                    for item in items_data.keys():
                        if isinstance(items_data[item], dict):
                            result = sum_specified_keys(items_data[item], "pieces", "seniority")
                            ydcj, wdcj, ydzl, wdzl = result
                            jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                            sub_dict[item] = {
                                "jindu": jindu,
                                "ydcj": ydcj,
                                "wdcj": wdcj,
                                "ydzl": ydzl,
                                "wdzl": wdzl,
                            }

                    tongji = [0, 0, 0, 0, 0, 0]
                    tongji[5] = items["data"]["roleName"]
                    for item in sub_dict.values():
                        tongji[1] += item["ydcj"]
                        tongji[2] += item["wdcj"]
                        tongji[3] += item["ydzl"]
                        tongji[4] += item["wdzl"]
                    tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

                    image_bytes = await render_template_image(
                        env,
                        "资历查询.html",
                        {"text": suijitext(), "tongji": tongji, "zilizonglan": selected_key, "items": sub_dict},
                        width=1120,
                        height="ck",
                    )
                    await send_image(bot, event, image_bytes, at_user=False, prefix=f"   {selected_key}")

                    if not user_sessions[user_id].get("nav_shown", True):
                        data_keys = list(user_sessions[user_id]["data"].keys())
                        nav_text = "   首页导航：\n" + "".join(
                            f"   {i}. {key}\n" for i, key in enumerate(data_keys, 1)
                        )
                        nav_text += "   请输入数字选择要查看的项目"
                        await bot.send(event, Message(nav_text))
                        user_sessions[user_id]["nav_shown"] = True

                    user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                    return
            else:
                current_path = user_sessions[user_id]["nav_path"]
                if len(current_path) >= 1 and (current_path[0] != "秘境分布" or len(current_path) > max_depth):
                    user_sessions[user_id]["nav_path"].pop()
                    if current_path[0] == "秘境分布" and len(current_path) > max_depth:
                        user_sessions[user_id]["nav_path"] = ["秘境分布"]
                        items_data = items["data"]["data"]["dungeons"]
                        dungeon_dict: dict[str, Any] = {}
                        for item in items_data.keys():
                            if isinstance(items_data[item], dict):
                                result = sum_specified_keys(items_data[item], "pieces", "seniority")
                                ydcj, wdcj, ydzl, wdzl = result
                                jindu = (ydzl / wdzl) * 100 if wdzl != 0 else 0
                                dungeon_dict[item] = {
                                    "jindu": jindu,
                                    "ydcj": ydcj,
                                    "wdcj": wdcj,
                                    "ydzl": ydzl,
                                    "wdzl": wdzl,
                                }

                        tongji = [0, 0, 0, 0, 0, 0]
                        tongji[5] = items["data"]["roleName"]
                        for item in dungeon_dict.values():
                            tongji[1] += item["ydcj"]
                            tongji[2] += item["wdcj"]
                            tongji[3] += item["ydzl"]
                            tongji[4] += item["wdzl"]
                        tongji[0] = round((tongji[3] / tongji[4]) * 100, 2) if tongji[4] > 0 else 0

                        image_bytes = await render_template_image(
                            env,
                            "资历查询.html",
                            {
                                "text": suijitext(),
                                "tongji": tongji,
                                "zilizonglan": "秘境分布",
                                "items": dungeon_dict,
                            },
                            width=1120,
                            height="ck",
                        )
                        await send_image(bot, event, image_bytes, at_user=False, prefix="   秘境分布")
                        user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                        return

                    data_keys = list(user_sessions[user_id]["data"].keys())
                    nav_text = "   可选项：\n" + "".join(f"   {i}. {key}\n" for i, key in enumerate(data_keys, 1))
                    nav_text += "   请输入数字选择要查看的项目"
                    await bot.send(event, Message(nav_text))
                    user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                    return

                items_data = items["data"]["data"]["dungeons"]
                temp_data = items_data
                for p in current_path[1:]:
                    temp_data = temp_data.get(p, {})
                items_data = temp_data.get(selected_key, {})
                if not check_valid_items(items_data):
                    await bot.send(event, Message(f"   {selected_key} 没有可用的子项目，无法进入"))
                    user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
                    return
                has_subitems = True

            user_sessions[user_id]["nav_path"].append(selected_key)
            if has_subitems:
                await display_subitems(bot, event, user_id, selected_key, items_data)
            else:
                await display_item_details(bot, event, user_id, selected_key, selected_item)
                user_sessions[user_id]["nav_path"].pop()

            user_sessions[user_id]["expiry_time"] = time.time() + SESSION_TIMEOUT
        except ValueError:
            await bot.send(event, Message("   请输入有效的数字序号"))
        except Exception as e:
            await send_text(bot, event, f"   处理失败: {str(e)}", at_user=True)
