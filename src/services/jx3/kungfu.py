from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)


def get_role_indicator(
    role_id: str,
    zone: str,
    server: str,
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
    rank: int | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    """
    获取角色详细信息
    """
    url = "https://m.pvp.xoyo.com/role/indicator"
    params = {"role_id": role_id, "zone": zone, "server": server}

    logger.info(
        "正在获取角色信息: url={} params={}",
        url,
        json.dumps(params, ensure_ascii=False),
    )

    try:
        result = tuilan_request(url, params)
        if result is None:
            logger.warning("获取角色信息失败: 返回None")
            return None

        if "error" in result:
            logger.warning("获取角色信息失败: %s", result.get("error"))
            return None

        rank_text = f"#{rank}" if rank is not None else "#-"
        name_text = name or "未知"
        server_text = server or "未知"
        logger.info("角色信息获取成功: {} {} {}", rank_text, server_text, name_text)
        return result
    except Exception as exc:
        logger.exception("获取角色信息异常: %s", exc)
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


def _extract_match_id(match: dict[str, Any]) -> int | None:
    for key in ("match_id", "matchId", "matchID", "id"):
        value = match.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _find_latest_win_match_id(matches: list[dict[str, Any]]) -> int | None:
    for match in matches:
        if match.get("won") is True:
            match_id = _extract_match_id(match)
            if match_id is not None:
                return match_id
    return None


def _match_player_and_teammates(
    match_detail: dict[str, Any],
    *,
    role_id: str | None,
    global_role_id: str | None,
    role_name: str | None,
    server: str | None,
) -> tuple[dict[str, Any] | None, int | str | None, list[dict[str, Any]]]:
    data = match_detail.get("data") if isinstance(match_detail, dict) else None
    if not isinstance(data, dict):
        return None, None, []

    def _match_name(role_text: str | None) -> bool:
        if not role_name:
            return False
        if not role_text:
            return False
        if role_text == role_name:
            return True
        return role_text.split("·")[0] == role_name

    def _is_target(player: dict[str, Any]) -> bool:
        if role_id and player.get("role_id") == role_id:
            return True
        if global_role_id and player.get("global_role_id") == global_role_id:
            return True
        if _match_name(player.get("person_name")) or _match_name(player.get("role_name")):
            if server and player.get("server") not in (None, "", server):
                return False
            return True
        return False

    target_player: dict[str, Any] | None = None
    target_team_players: list[dict[str, Any]] = []

    for team_key in ("team1", "team2"):
        team = data.get(team_key)
        if not isinstance(team, dict):
            continue
        players = team.get("players_info") or []
        if not isinstance(players, list):
            continue
        for player in players:
            if not isinstance(player, dict):
                continue
            if _is_target(player):
                target_player = player
                target_team_players = [p for p in players if isinstance(p, dict)]
                break
        if target_player:
            break

    if not target_player:
        return None, None, []

    weapon_info = (target_player.get("armors") or [None])[0]
    if not isinstance(weapon_info, dict):
        weapon_info = None
    target_kungfu_id = target_player.get("kungfu_id")

    teammates: list[dict[str, Any]] = []
    for player in target_team_players:
        if not isinstance(player, dict):
            continue
        if _is_target(player):
            continue
        teammate: dict[str, Any] = {
            "role_name": player.get("role_name") or player.get("person_name"),
            "person_name": player.get("person_name"),
            "person_id": player.get("person_id"),
            "server": player.get("server"),
            "role_id": player.get("role_id"),
            "global_role_id": player.get("global_role_id"),
            "kungfu_id": player.get("kungfu_id"),
        }
        teammate_weapon = (player.get("armors") or [None])[0]
        if isinstance(teammate_weapon, dict):
            teammate["weapon"] = teammate_weapon
            teammate["weapon_icon"] = teammate_weapon.get("icon")
            teammate["weapon_quality"] = teammate_weapon.get("quality")
            teammate["weapon_name"] = teammate_weapon.get("name")
        teammates.append(teammate)

    return weapon_info, target_kungfu_id, teammates


def get_kungfu_detail_by_role_info(
    game_role_id: str,
    zone: str,
    server: str,
    *,
    tuilan_request: Callable[[str, dict[str, Any]], Any],
    kungfu_pinyin_to_chinese: dict[str, str],
    match_detail_url: str | None = None,
    role_name: str | None = None,
    rank: int | None = None,
) -> dict[str, Any] | None:
    """
    心法判定（用于缓存落盘）：
    1) indicator 接口选取胜场最高的心法（仅 items 非空的 metrics 参与）
    2) indicator 获取 global_role_id 后请求 match_history 最近40条，从中取10场胜场心法做多数投票
    3) 若对战(10胜场)心法与 indicator 心法不同，则以对战心法为准；若不足10胜场则以 indicator 为准
    """
    if game_role_id == "未知" or server == "未知" or zone == "未知":
        return None

    role_detail = get_role_indicator(
        game_role_id,
        zone,
        server,
        tuilan_request=tuilan_request,
        rank=rank,
        name=role_name,
    )
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
                        logger.info(
                            "⚠️ 胜场/场次心法不一致: role_id={} zone={} server={} "
                            "win_count={}({}) total_count={}({})",
                            game_role_id,
                            zone,
                            server,
                            indicator_kungfu_name,
                            max_win_count,
                            total_kungfu,
                            max_total_count,
                        )
                break

    match_history_kungfu_pinyin = None
    match_history_kungfu_name = None
    match_history_win_kungfu_samples: list[str] = []
    match_history_checked = 0

    weapon_info: dict[str, Any] | None = None
    kungfu_id: int | str | None = None
    teammates: list[dict[str, Any]] = []
    weapon_checked = False

    if global_role_id:
        matches: list[dict[str, Any]] = []
        resp = get_match_history(
            global_role_id,
            size=40,
            cursor=0,
            tuilan_request=tuilan_request,
        )
        if resp and isinstance(resp, dict) and resp.get("code") == 0 and resp.get("msg") == "success":
            page_data = resp.get("data") or []
            if isinstance(page_data, list):
                matches.extend([m for m in page_data if isinstance(m, dict)])

        match_history_checked = min(40, len(matches))
        won_kungfus: list[str] = []
        for match in matches[:40]:
            if match.get("won") is True and match.get("kungfu"):
                won_kungfus.append(match["kungfu"])
                if len(won_kungfus) >= 10:
                    break

        latest_win_match_id = _find_latest_win_match_id(matches)
        if match_detail_url:
            weapon_checked = True
        if latest_win_match_id and match_detail_url:
            try:
                detail_resp = tuilan_request(match_detail_url, {"match_id": latest_win_match_id})
                if isinstance(detail_resp, dict) and detail_resp.get("code") == 0:
                    weapon_info, kungfu_id, teammates = _match_player_and_teammates(
                        detail_resp,
                        role_id=role_id,
                        global_role_id=global_role_id,
                        role_name=role_name,
                        server=server,
                    )
            except Exception as exc:
                logger.exception("获取战局详情失败: %s", exc)

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

    result = {
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
    if weapon_info:
        result["weapon"] = weapon_info
        result["weapon_icon"] = weapon_info.get("icon")
        result["weapon_quality"] = weapon_info.get("quality")
    if kungfu_id is not None:
        result["kungfu_id"] = kungfu_id
    if teammates:
        result["teammates"] = teammates
    result["weapon_checked"] = weapon_checked
    result["teammates_checked"] = weapon_checked
    return result


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
