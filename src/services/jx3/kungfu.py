from __future__ import annotations

import json
from collections import Counter
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


def get_match_history(
    global_role_id: str,
    *,
    size: int,
    cursor: int,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
) -> dict[str, Any] | None:
    """
    推栏：分页请求 3c 战局历史
    """
    url = "https://m.pvp.xoyo.com/3c/mine/match/history"
    params = {"global_role_id": global_role_id, "size": int(size), "cursor": int(cursor)}
    try:
        return tuilan_request(url, params)
    except Exception as exc:
        print(f"\n❌ 获取战局历史时发生异常: {exc}")
        import traceback

        traceback.print_exc()
        return None


def get_kungfu_detail_by_role_info(
    game_role_id: str,
    zone: str,
    server: str,
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
    kungfu_pinyin_to_chinese: dict[str, str],
) -> dict[str, Any] | None:
    """
    心法判定（用于缓存落盘）：
    1) indicator 接口选取胜场最高的心法（仅 items 非空的 metrics 参与）
    2) indicator 获取 global_role_id 后请求 match_history 最近40条，从中取10场胜场心法做多数投票
    3) 若对战(10胜场)心法与 indicator 心法不同，则以对战心法为准；若不足10胜场则以 indicator 为准
    """
    if game_role_id == "未知" or server == "未知" or zone == "未知":
        return None

    role_detail = get_role_indicator(game_role_id, zone, server, tuilan_request=tuilan_request)
    if not role_detail or "data" not in role_detail or not role_detail["data"]:
        return None

    data = role_detail.get("data") or {}
    role_info = data.get("role_info") or {}
    role_id = role_info.get("role_id") or role_info.get("roleId") or game_role_id
    global_role_id = role_info.get("global_role_id") or role_info.get("globalRoleId")

    indicator_kungfu_pinyin = None
    indicator_kungfu_name = None

    indicators = data.get("indicator") or []
    if isinstance(indicators, list):
        for indicator in indicators:
            if not isinstance(indicator, dict):
                continue
            if indicator.get("type") not in {"3c", "3d"}:
                continue

            metrics = indicator.get("metrics") or []
            if not isinstance(metrics, list) or not metrics:
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
                indicator_kungfu_pinyin = best_win_metric.get("kungfu")
                indicator_kungfu_name = kungfu_pinyin_to_chinese.get(
                    indicator_kungfu_pinyin, indicator_kungfu_pinyin
                )

                if best_total_metric:
                    total_kungfu = kungfu_pinyin_to_chinese.get(
                        best_total_metric.get("kungfu"), best_total_metric.get("kungfu")
                    )
                    if indicator_kungfu_name != total_kungfu:
                        print(
                            f"⚠️ 胜场/场次心法不一致: role_id={game_role_id}, zone={zone}, "
                            f"server={server}, win_count={indicator_kungfu_name}({max_win_count}), "
                            f"total_count={total_kungfu}({max_total_count})"
                        )
                break

    match_history_kungfu_pinyin = None
    match_history_kungfu_name = None
    match_history_win_kungfu_samples: list[str] = []
    match_history_checked = 0

    if global_role_id:
        matches: list[dict[str, Any]] = []
        for cursor in (0, 20):
            resp = get_match_history(
                global_role_id,
                size=20,
                cursor=cursor,
                tuilan_request=tuilan_request,
            )
            if not resp or not isinstance(resp, dict):
                break
            if resp.get("code") != 0 or resp.get("msg") != "success":
                break
            page_data = resp.get("data") or []
            if not isinstance(page_data, list):
                break
            matches.extend([m for m in page_data if isinstance(m, dict)])
            if len(page_data) < 20:
                break

        match_history_checked = min(40, len(matches))
        won_kungfus: list[str] = []
        for match in matches[:40]:
            if match.get("won") is True and match.get("kungfu"):
                won_kungfus.append(match["kungfu"])
                if len(won_kungfus) >= 10:
                    break

        if len(won_kungfus) >= 10:
            sample = won_kungfus[:10]
            match_history_win_kungfu_samples = sample
            counts = Counter(sample)
            first_index: dict[str, int] = {}
            for idx, item in enumerate(sample):
                if item not in first_index:
                    first_index[item] = idx
            match_history_kungfu_pinyin = max(
                counts.items(),
                key=lambda kv: (kv[1], -first_index.get(kv[0], 9999)),
            )[0]
            match_history_kungfu_name = kungfu_pinyin_to_chinese.get(
                match_history_kungfu_pinyin, match_history_kungfu_pinyin
            )

    chosen_source = "indicator"
    chosen_kungfu_pinyin = indicator_kungfu_pinyin
    chosen_kungfu_name = indicator_kungfu_name

    if match_history_kungfu_name and match_history_win_kungfu_samples and len(match_history_win_kungfu_samples) >= 10:
        if not indicator_kungfu_name:
            chosen_source = "match_history"
            chosen_kungfu_pinyin = match_history_kungfu_pinyin
            chosen_kungfu_name = match_history_kungfu_name
        elif match_history_kungfu_name != indicator_kungfu_name:
            chosen_source = "match_history"
            chosen_kungfu_pinyin = match_history_kungfu_pinyin
            chosen_kungfu_name = match_history_kungfu_name

    return {
        "role_id": role_id,
        "global_role_id": global_role_id,
        "kungfu": chosen_kungfu_name,
        "kungfu_pinyin": chosen_kungfu_pinyin,
        "kungfu_indicator": indicator_kungfu_name,
        "kungfu_indicator_pinyin": indicator_kungfu_pinyin,
        "kungfu_match_history": match_history_kungfu_name,
        "kungfu_match_history_pinyin": match_history_kungfu_pinyin,
        "kungfu_selected_source": chosen_source,
        "match_history_checked": match_history_checked,
        "match_history_win_samples": match_history_win_kungfu_samples,
    }


def get_kungfu_by_role_info(
    game_role_id: str,
    zone: str,
    server: str,
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
    kungfu_pinyin_to_chinese: dict[str, str],
) -> str | None:
    detail = get_kungfu_detail_by_role_info(
        game_role_id,
        zone,
        server,
        tuilan_request=tuilan_request,
        kungfu_pinyin_to_chinese=kungfu_pinyin_to_chinese,
    )
    if not detail:
        return None
    return detail.get("kungfu")
