from __future__ import annotations

import json
from typing import Any, Callable


def get_role_indicator(
    role_id: str,
    zone: str,
    server: str,
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any] | None:
    """
    获取角色详细信息
    """
    url = "https://m.pvp.xoyo.com/role/indicator"
    params = {"role_id": role_id, "zone": zone, "server": server}

    print("正在获取角色信息...")
    print(f"请求地址: {url}")
    print(f"请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

    try:
        result = tuilan_request(url, params)
        if result is None:
            print("\n❌ 获取角色信息失败: 请求返回None")
            return None

        if "error" in result:
            print(f"\n❌ 获取角色信息失败: {result['error']}")
            return None

        print("\n✅ 角色信息获取成功")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    except Exception as exc:
        print(f"\n❌ 获取角色信息时发生异常: {exc}")
        import traceback

        traceback.print_exc()
        return None


def make_kungfu_resolver(
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
    kungfu_pinyin_to_chinese: dict[str, str],
) -> Callable[[str, str, str], str | None]:
    """
    生成一个心法查询函数: (game_role_id, zone, server) -> 心法中文名 | None
    """

    def _get_kungfu_by_role_info(game_role_id: str, zone: str, server: str) -> str | None:
        return get_kungfu_by_role_info(
            game_role_id,
            zone,
            server,
            tuilan_request=tuilan_request,
            kungfu_pinyin_to_chinese=kungfu_pinyin_to_chinese,
        )

    return _get_kungfu_by_role_info


def get_kungfu_by_role_info(
    game_role_id: str,
    zone: str,
    server: str,
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
    kungfu_pinyin_to_chinese: dict[str, str],
) -> str | None:
    print("\n🔍 开始查询心法信息...")
    print(f"角色ID: {game_role_id}")
    print(f"大区: {zone}")
    print(f"服务器: {server}")

    if game_role_id == "未知" or server == "未知" or zone == "未知":
        print("❌ 参数无效，无法查询")
        return None

    role_detail = get_role_indicator(game_role_id, zone, server, tuilan_request=tuilan_request)
    if role_detail and "data" in role_detail and role_detail["data"] and "indicator" in role_detail["data"]:
        indicators = role_detail["data"]["indicator"]

        for indicator in indicators:
            if indicator.get("type") == "3c" or indicator.get("type") == "3d":
                metrics = indicator.get("metrics", [])
                if not metrics:
                    continue

                max_win_count = -1
                max_total_count = -1
                best_win_metric = None
                best_total_metric = None

                for metric in metrics:
                    if metric and metric.get("items"):
                        win_count = metric.get("win_count", 0) or 0
                        total_count = metric.get("total_count", 0) or 0

                        if win_count > max_win_count:
                            max_win_count = win_count
                            best_win_metric = metric
                        if total_count > max_total_count:
                            max_total_count = total_count
                            best_total_metric = metric

                if best_win_metric:
                    kungfu_pinyin = best_win_metric.get("kungfu")
                    kungfu_name = kungfu_pinyin_to_chinese.get(kungfu_pinyin)

                    if best_total_metric:
                        total_kungfu = kungfu_pinyin_to_chinese.get(best_total_metric.get("kungfu"))
                        if kungfu_name != total_kungfu:
                            print(
                                f"⚠️ 胜场/场次心法不一致: role_id={game_role_id}, zone={zone}, "
                                f"server={server}, win_count={kungfu_name}({max_win_count}), "
                                f"total_count={total_kungfu}({max_total_count})"
                            )

                    print(f"\n🎯 最终选择心法: {kungfu_pinyin} -> {kungfu_name}")
                    return kungfu_name

                print("❌ 未找到有效的心法数据")
    else:
        print("❌ 角色详情数据格式异常")
        if role_detail:
            print(f"响应结构: {list(role_detail.keys())}")

    return None
