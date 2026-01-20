from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchDetailMetric:
    metric_id: int | None
    name: str
    value: float | int | None
    grade: str
    ranking: int | None


@dataclass(frozen=True)
class MatchDetailArmor:
    ui_id: str
    quality: str
    name: str
    strength_evel: str
    permanent_enchant: str
    temporary_enchant: str
    mount1: str
    mount2: str
    mount3: str
    mount4: str
    pos: int | None
    icon: str
    equip_box_strength_level: str


@dataclass(frozen=True)
class MatchDetailTalent:
    talent_id: str
    name: str
    icon: str
    desc: str
    level: str


@dataclass(frozen=True)
class MatchDetailBodyQuality:
    name: str
    value: str


@dataclass(frozen=True)
class MatchDetailPlayerInfo:
    role_name: str
    global_role_id: str
    role_id: str
    person_id: str
    person_name: str
    person_avatar: str
    zone: str
    server: str
    total_count: int | None
    win_count: int | None
    win_rate: int | None
    mvp_count: int | None
    mmr: int | None
    score: int | None
    total_score: int | None
    ranking: str
    kungfu: str
    kungfu_id: int | None
    mvp: bool
    equip_score: int | None
    equip_strength_score: int | None
    stone_score: int | None
    max_hp: int | None
    metrics: list[MatchDetailMetric]
    armors: list[MatchDetailArmor]
    talents: list[MatchDetailTalent]
    body_qualities: list[MatchDetailBodyQuality]
    odd: bool
    fight_seconds: int | None


@dataclass(frozen=True)
class MatchDetailTeamInfo:
    won: bool
    team_name: str
    players_info: list[MatchDetailPlayerInfo]


@dataclass(frozen=True)
class MatchDetailBasicInfo:
    video_url: str
    screen_shot_url: str
    start_time: int | None
    duration: int | None
    map: str
    match_type: int | None
    grade: int | None


@dataclass(frozen=True)
class MatchDetailData:
    match_id: int | None
    match_time: int | None
    query_backend: bool
    basic_info: MatchDetailBasicInfo | None
    team1: MatchDetailTeamInfo | None
    team2: MatchDetailTeamInfo | None
    videos: list[Any]
    hidden: bool


@dataclass(frozen=True)
class MatchDetailResponse:
    code: int | None
    msg: str
    data: MatchDetailData | None


def _parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _parse_metric(raw: dict[str, Any]) -> MatchDetailMetric:
    return MatchDetailMetric(
        metric_id=_parse_int(raw.get("id")),
        name=str(raw.get("name") or ""),
        value=raw.get("value"),
        grade=str(raw.get("grade") or ""),
        ranking=_parse_int(raw.get("ranking")),
    )


def _parse_armor(raw: dict[str, Any]) -> MatchDetailArmor:
    return MatchDetailArmor(
        ui_id=str(raw.get("ui_id") or ""),
        quality=str(raw.get("quality") or ""),
        name=str(raw.get("name") or ""),
        strength_evel=str(raw.get("strength_evel") or ""),
        permanent_enchant=str(raw.get("permanent_enchant") or ""),
        temporary_enchant=str(raw.get("temporary_enchant") or ""),
        mount1=str(raw.get("mount1") or ""),
        mount2=str(raw.get("mount2") or ""),
        mount3=str(raw.get("mount3") or ""),
        mount4=str(raw.get("mount4") or ""),
        pos=_parse_int(raw.get("pos")),
        icon=str(raw.get("icon") or ""),
        equip_box_strength_level=str(raw.get("equip_box_strength_level") or ""),
    )


def _parse_talent(raw: dict[str, Any]) -> MatchDetailTalent:
    return MatchDetailTalent(
        talent_id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        icon=str(raw.get("icon") or ""),
        desc=str(raw.get("desc") or ""),
        level=str(raw.get("level") or ""),
    )


def _parse_body_quality(raw: dict[str, Any]) -> MatchDetailBodyQuality:
    return MatchDetailBodyQuality(
        name=str(raw.get("name") or ""),
        value=str(raw.get("value") or ""),
    )


def _parse_player_info(raw: dict[str, Any]) -> MatchDetailPlayerInfo:
    metrics = raw.get("metrics") or []
    armors = raw.get("armors") or []
    talents = raw.get("talents") or []
    body_qualities = raw.get("body_qualities") or []
    return MatchDetailPlayerInfo(
        role_name=str(raw.get("role_name") or ""),
        global_role_id=str(raw.get("global_role_id") or ""),
        role_id=str(raw.get("role_id") or ""),
        person_id=str(raw.get("person_id") or ""),
        person_name=str(raw.get("person_name") or ""),
        person_avatar=str(raw.get("person_avatar") or ""),
        zone=str(raw.get("zone") or ""),
        server=str(raw.get("server") or ""),
        total_count=_parse_int(raw.get("total_count")),
        win_count=_parse_int(raw.get("win_count")),
        win_rate=_parse_int(raw.get("win_rate")),
        mvp_count=_parse_int(raw.get("mvp_count")),
        mmr=_parse_int(raw.get("mmr")),
        score=_parse_int(raw.get("score")),
        total_score=_parse_int(raw.get("total_score")),
        ranking=str(raw.get("ranking") or ""),
        kungfu=str(raw.get("kungfu") or ""),
        kungfu_id=_parse_int(raw.get("kungfu_id")),
        mvp=bool(raw.get("mvp")),
        equip_score=_parse_int(raw.get("equip_score")),
        equip_strength_score=_parse_int(raw.get("equip_strength_score")),
        stone_score=_parse_int(raw.get("stone_score")),
        max_hp=_parse_int(raw.get("max_hp")),
        metrics=[_parse_metric(item) for item in metrics if isinstance(item, dict)],
        armors=[_parse_armor(item) for item in armors if isinstance(item, dict)],
        talents=[_parse_talent(item) for item in talents if isinstance(item, dict)],
        body_qualities=[_parse_body_quality(item) for item in body_qualities if isinstance(item, dict)],
        odd=bool(raw.get("odd")),
        fight_seconds=_parse_int(raw.get("fight_seconds")),
    )


def _parse_team_info(raw: dict[str, Any]) -> MatchDetailTeamInfo:
    players = raw.get("players_info") or []
    return MatchDetailTeamInfo(
        won=bool(raw.get("won")),
        team_name=str(raw.get("team_name") or ""),
        players_info=[_parse_player_info(item) for item in players if isinstance(item, dict)],
    )


def _parse_basic_info(raw: dict[str, Any]) -> MatchDetailBasicInfo:
    return MatchDetailBasicInfo(
        video_url=str(raw.get("video_url") or ""),
        screen_shot_url=str(raw.get("screen_shot_url") or ""),
        start_time=_parse_int(raw.get("start_time")),
        duration=_parse_int(raw.get("duration")),
        map=str(raw.get("map") or ""),
        match_type=_parse_int(raw.get("type")),
        grade=_parse_int(raw.get("grade")),
    )


def parse_match_detail_response(raw: dict[str, Any]) -> MatchDetailResponse:
    data_raw = raw.get("data") if isinstance(raw, dict) else None
    data = None
    if isinstance(data_raw, dict):
        data = MatchDetailData(
            match_id=_parse_int(data_raw.get("match_id")),
            match_time=_parse_int(data_raw.get("match_time")),
            query_backend=bool(data_raw.get("query_backend")),
            basic_info=_parse_basic_info(data_raw.get("basic_info") or {})
            if isinstance(data_raw.get("basic_info"), dict)
            else None,
            team1=_parse_team_info(data_raw.get("team1") or {})
            if isinstance(data_raw.get("team1"), dict)
            else None,
            team2=_parse_team_info(data_raw.get("team2") or {})
            if isinstance(data_raw.get("team2"), dict)
            else None,
            videos=list(data_raw.get("videos") or []),
            hidden=bool(data_raw.get("Hidden")),
        )
    return MatchDetailResponse(
        code=_parse_int(raw.get("code")) if isinstance(raw, dict) else None,
        msg=str(raw.get("msg") or "") if isinstance(raw, dict) else "",
        data=data,
    )


@dataclass(frozen=True)
class MatchDetailClient:
    """
    推栏：获取 3c 战局详情

    接口: POST https://m.pvp.xoyo.com/3c/mine/match/detail
    body: {"match_id": 123, "ts": "..."}  (ts 由 tuilan_request 自动补充)
    """

    match_detail_url: str
    tuilan_request: Callable[[str, dict[str, Any]], Any]

    def get_match_detail(self, *, match_id: int | str) -> dict[str, Any]:
        url = self.match_detail_url
        params = {"match_id": int(match_id)}

        logger.info(f"推栏战局详情请求: url={url} params={json.dumps(params, ensure_ascii=False)}")

        try:
            result = self.tuilan_request(url, params)

            if result is None:
                logger.warning("推栏战局详情请求失败: 返回None")
                return {"error": "请求返回None"}

            if isinstance(result, dict) and "error" in result:
                logger.warning("推栏战局详情请求失败: %s", result.get("error"))
                return result

            logger.info("推栏战局详情请求成功")
            return result
        except Exception as exc:
            logger.exception("推栏战局详情请求异常: %s", exc)
            return {"error": f"请求异常: {exc}"}

    def get_match_detail_obj(self, *, match_id: int | str) -> MatchDetailResponse:
        raw = self.get_match_detail(match_id=match_id)
        if not isinstance(raw, dict):
            return MatchDetailResponse(code=None, msg="invalid_response", data=None)
        return parse_match_detail_response(raw)
