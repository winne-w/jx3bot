from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db
from src.services.jx3.match_detail_snapshots import (
    build_equipment_snapshot,
    build_talent_snapshot,
)
from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo


@dataclass(frozen=True)
class JjcInspectRepo:
    db: Optional[AsyncIOMotorDatabase] = None
    snapshot_repo: JjcMatchSnapshotRepo = field(default_factory=JjcMatchSnapshotRepo)
    participant_repo: Any = field(default_factory=JjcMatchParticipantRepo)

    async def load_role_recent(self, server: str, name: str, *, ttl_seconds: int) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_role_recent.find_one({"server": server, "name": name})
        except Exception as exc:
            logger.warning(f"读取 JJC 角色近期缓存失败: server={server} name={name} error={exc}")
            return None
        if doc is None:
            logger.info(f"JJC 角色近期缓存未命中: server={server} name={name}")
            return None
        cached_at = doc.get("cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        if time.time() - float(cached_at) > ttl_seconds:
            logger.info(f"JJC 角色近期缓存已过期: server={server} name={name}")
            return None
        return {"cached_at": cached_at, "data": doc.get("data")}

    async def save_role_recent(self, server: str, name: str, payload: dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.jjc_role_recent.update_one(
                {"server": server, "name": name},
                {"$set": {
                    "cached_at": payload.get("cached_at") or time.time(),
                    "data": payload.get("data") or payload,
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(f"保存 JJC 角色近期缓存失败: server={server} name={name} error={exc}")

    async def load_match_detail(self, match_id: Union[int, str]) -> Optional[dict[str, Any]]:
        try:
            normalized_id = int(match_id)
        except (ValueError, TypeError):
            return None
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_match_detail.find_one({"match_id": normalized_id})
        except Exception as exc:
            logger.warning(f"读取 JJC 对局详情缓存失败: match_id={match_id} error={exc}")
            return None
        if doc is None:
            return None
        await self._hydrate_match_detail(doc, normalized_id)
        return doc

    async def save_match_detail(self, match_id: Union[int, str], payload: dict[str, Any]) -> None:
        try:
            normalized_id = int(match_id)
        except (ValueError, TypeError):
            return
        db = self.db if self.db is not None else _get_db()
        data = payload.get("data") or payload
        mongo_data = copy.deepcopy(data)
        if not data.get("unavailable"):
            await self._extract_snapshots(mongo_data, payload.get("cached_at"))
        try:
            await db.jjc_match_detail.update_one(
                {"match_id": normalized_id},
                {"$set": {
                    "cached_at": payload.get("cached_at") or time.time(),
                    "data": mongo_data,
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(f"保存 JJC 对局详情缓存失败: match_id={match_id} error={exc}")

    async def _hydrate_match_detail(self, doc: dict[str, Any], match_id: int) -> None:
        """Fill players_info[].armors/talents from snapshot hashes in-place.

        Always uses equipment_snapshot_hash/talent_snapshot_hash to hydrate.
        Missing snapshots yield empty arrays with a warning instead of failing the match.
        """
        if self.snapshot_repo is None:
            return
        data = doc.get("data")
        if not isinstance(data, dict):
            return
        if data.get("unavailable"):
            return
        detail = data.get("detail")
        if not isinstance(detail, dict):
            return

        equip_hashes: set = set()
        talent_hashes: set = set()

        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info") or []
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                h = player.get("equipment_snapshot_hash")
                if isinstance(h, str) and h:
                    equip_hashes.add(h)
                h = player.get("talent_snapshot_hash")
                if isinstance(h, str) and h:
                    talent_hashes.add(h)

        equip_snapshots = await self.snapshot_repo.load_equipment_snapshots(list(equip_hashes)) if equip_hashes else {}
        talent_snapshots = await self.snapshot_repo.load_talent_snapshots(list(talent_hashes)) if talent_hashes else {}

        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info") or []
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                player.pop("armors", None)
                player.pop("talents", None)

                h = player.get("equipment_snapshot_hash")
                if isinstance(h, str) and h:
                    snap = equip_snapshots.get(h)
                    if snap is not None:
                        player["armors"] = snap.get("armors", [])
                    else:
                        logger.warning(f"装备快照缺失: match_id={match_id} equipment_snapshot_hash={h}")
                        player["armors"] = []

                h = player.get("talent_snapshot_hash")
                if isinstance(h, str) and h:
                    snap = talent_snapshots.get(h)
                    if snap is not None:
                        player["talents"] = snap.get("talents", [])
                    else:
                        logger.warning(f"奇穴快照缺失: match_id={match_id} talent_snapshot_hash={h}")
                        player["talents"] = []

    async def batch_load_cached_detail_summaries(self, match_ids: list) -> dict[int, dict[str, Any]]:
        """Return a dict keyed by normalized int match_id with compact summaries.

        Only includes documents whose data.unavailable is not true.
        """
        started_at = time.perf_counter()
        normalized: list[int] = []
        for mid in match_ids:
            try:
                normalized_mid = int(mid)
            except (ValueError, TypeError):
                continue
            if normalized_mid not in normalized:
                normalized.append(normalized_mid)
        if not normalized:
            return {}

        db = self.db if self.db is not None else _get_db()
        result = await self._batch_build_detail_summaries_from_participants(db, normalized)
        missing = [mid for mid in normalized if mid not in result]
        if not missing:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "JJC cached detail summaries loaded from participants: requested={} result={} elapsed_ms={}".format(
                    len(normalized),
                    len(result),
                    elapsed_ms,
                )
            )
            return result

        try:
            query = {"match_id": {"$in": missing}}
            projection = {
                "_id": 0,
                "match_id": 1,
                "cached_at": 1,
                "data.unavailable": 1,
                "data.detail.team1.won": 1,
                "data.detail.team1.players_info.kungfu_id": 1,
                "data.detail.team1.players_info.kungfu": 1,
                "data.detail.team1.players_info.role_name": 1,
                "data.detail.team1.players_info.server": 1,
                "data.detail.team2.won": 1,
                "data.detail.team2.players_info.kungfu_id": 1,
                "data.detail.team2.players_info.kungfu": 1,
                "data.detail.team2.players_info.role_name": 1,
                "data.detail.team2.players_info.server": 1,
            }
            try:
                cursor = db.jjc_match_detail.find(query, projection)
            except TypeError:
                cursor = db.jjc_match_detail.find(query)
            docs = await cursor.to_list(length=None)
        except Exception as exc:
            logger.warning(f"批量读取 JJC 对局详情缓存失败: error={exc}")
            return result

        for doc in docs:
            mid = doc.get("match_id")
            if not isinstance(mid, int):
                continue
            data = doc.get("data")
            if not isinstance(data, dict):
                continue
            if data.get("unavailable"):
                continue
            detail = data.get("detail")
            if not isinstance(detail, dict):
                continue
            summary = self._build_cached_detail_summary(mid, doc.get("cached_at"), detail)
            if summary is not None:
                result[mid] = summary
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "JJC cached detail summaries loaded: requested={} participant_hits={} detail_missing={} result={} elapsed_ms={}".format(
                len(normalized),
                len(normalized) - len(missing),
                len(missing),
                len(result),
                elapsed_ms,
            )
        )
        return result

    async def _batch_build_detail_summaries_from_participants(
        self,
        db: AsyncIOMotorDatabase,
        match_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        try:
            cursor = db.jjc_match_participants.find(
                {
                    "match_id": {"$in": match_ids},
                    "detail_available": True,
                },
                {
                    "_id": 0,
                    "match_id": 1,
                    "cached_at": 1,
                    "team_key": 1,
                    "won": 1,
                    "kungfu_id": 1,
                    "kungfu": 1,
                    "role_name": 1,
                    "server": 1,
                },
            )
            docs = await cursor.to_list(length=None)
        except Exception as exc:
            logger.warning(f"批量读取 JJC 对局参与者投影摘要失败: error={exc}")
            return {}

        summaries: dict[int, dict[str, Any]] = {}
        for doc in docs:
            mid = self._coerce_int(doc.get("match_id"))
            if mid is None:
                continue
            team_key = self._pick_str(doc.get("team_key"))
            if team_key not in {"team1", "team2"}:
                continue
            summary = summaries.setdefault(
                mid,
                {
                    "match_id": mid,
                    "cached_at": doc.get("cached_at"),
                    "team1": {"won": False, "players": []},
                    "team2": {"won": False, "players": []},
                },
            )
            if summary.get("cached_at") is None and doc.get("cached_at") is not None:
                summary["cached_at"] = doc.get("cached_at")
            team = summary[team_key]
            team["won"] = bool(doc.get("won"))
            player_summary: dict[str, Any] = {}
            for field in ("kungfu_id", "kungfu", "role_name", "server"):
                val = doc.get(field)
                if val is not None:
                    player_summary[field] = val
            if player_summary:
                team["players"].append(player_summary)
        return summaries

    @staticmethod
    def _coerce_object_id(value: Any) -> Optional[ObjectId]:
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, str) and ObjectId.is_valid(value):
            return ObjectId(value)
        return None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if isinstance(value, bool) or value is None:
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

    async def list_saved_local_3v3_matches_for_identity(
        self,
        *,
        identity_id: Any,
        identity_key: Optional[str],
        server: Optional[str] = None,
        name: Optional[str] = None,
        global_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        game_role_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List locally saved 3v3 matches associated with a role identity.

        Local-only: rows must have available local match details.
        Candidates are matched strictly by the stable replay global_id stored
        on match-detail players. Name/server fallback is deliberately avoided
        to prevent transfer or rename history from leaking into the result.
        """
        safe_page = max(1, page)
        safe_page_size = min(max(1, page_size), 100)
        target_global_id = self._pick_str(global_id)
        if not target_global_id:
            return self._empty_match_page(safe_page, safe_page_size)

        result = await self._list_saved_matches_from_projection(
            global_id=target_global_id,
            page=safe_page,
            page_size=safe_page_size,
        )
        return result

    @staticmethod
    def _empty_match_page(page: int, page_size: int) -> Dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "has_more": False,
        }

    async def _list_saved_matches_from_projection(
        self,
        *,
        global_id: str,
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        if self.participant_repo is None:
            raise RuntimeError("participant_repo_not_configured")

        result = await self.participant_repo.list_local_3v3_matches_by_global_id(
            global_id=global_id,
            page=page,
            page_size=page_size,
        )
        mapped_items = self._map_projection_to_match_rows(result.get("items") or [])
        await self._hydrate_projection_match_rows(mapped_items)
        total = self._coerce_int(result.get("total")) or 0
        result_page = self._coerce_int(result.get("page")) or page
        result_page_size = self._coerce_int(result.get("page_size")) or page_size
        return {
            "items": mapped_items,
            "total": total,
            "page": result_page,
            "page_size": result_page_size,
            "has_more": bool(result.get("has_more")),
        }

    @classmethod
    def _map_projection_to_match_rows(cls, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = cls._coerce_int(item.get("match_id"))
            if mid is None:
                continue
            rows.append({
                "match_id": mid,
                "won": bool(item.get("won")),
                "kungfu": item.get("kungfu"),
                "avg_grade": cls._coerce_int(item.get("avg_grade")),
                "total_mmr": cls._coerce_int(item.get("total_mmr")),
                "mmr_delta": cls._coerce_int(item.get("mmr_delta")),
                "mvp": bool(item.get("mvp")),
                "match_time": cls._coerce_int(item.get("match_time")),
                "start_time": cls._coerce_int(item.get("start_time")),
                "duration": cls._coerce_int(item.get("duration")),
                "sync": {
                    "status": cls._pick_str(item.get("sync_status")) or "not_synced",
                    "detail_saved_at": item.get("detail_saved_at"),
                    "match_time": item.get("match_time"),
                    "source_identity_id": str(item.get("source_identity_id")) if item.get("source_identity_id") is not None else None,
                    "source_identity_key": item.get("source_identity_key"),
                },
            })
        return rows

    async def _hydrate_projection_match_rows(self, rows: List[Dict[str, Any]]) -> None:
        match_ids: List[int] = []
        for row in rows:
            mid = self._coerce_int(row.get("match_id"))
            if mid is not None:
                match_ids.append(mid)
        if not match_ids:
            return
        try:
            summaries = await self.batch_load_cached_detail_summaries(match_ids)
        except Exception as exc:
            logger.warning(f"投影行补充 JJC 对局详情摘要失败: error={exc}")
            summaries = {}
        for row in rows:
            mid = self._coerce_int(row.get("match_id"))
            if mid is not None and mid in summaries:
                row["cached_detail_summary"] = summaries[mid]
            else:
                row.pop("cached_detail_summary", None)

    @staticmethod
    def _log_projection_diff_if_needed(
        global_id: str,
        detail_result: Dict[str, Any],
        projection_result: Dict[str, Any],
    ) -> None:
        detail_ids = [item.get("match_id") for item in detail_result.get("items") or [] if isinstance(item, dict)]
        projection_ids = [item.get("match_id") for item in projection_result.get("items") or [] if isinstance(item, dict)]
        detail_total = detail_result.get("total")
        projection_total = projection_result.get("total")
        detail_only = sorted(set(detail_ids) - set(projection_ids))
        projection_only = sorted(set(projection_ids) - set(detail_ids))
        order_diff = detail_ids != projection_ids
        total_diff = detail_total != projection_total
        if detail_only or projection_only or order_diff or total_diff:
            logger.warning(
                "JJC 参与者投影 shadow 差异: global_id={} detail_total={} projection_total={} "
                "detail_only={} projection_only={} order_diff={}".format(
                    global_id,
                    detail_total,
                    projection_total,
                    detail_only[:20],
                    projection_only[:20],
                    order_diff,
                )
            )

    async def _list_saved_matches_from_detail(
        self,
        *,
        identity_id: Any,
        identity_key: Optional[str],
        server: Optional[str],
        name: Optional[str],
        global_id: str,
        global_role_id: Optional[str],
        role_id: Optional[str],
        game_role_id: Optional[str],
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        del identity_id, identity_key
        skip = (page - 1) * page_size
        target_global_id = self._pick_str(global_id)
        if not target_global_id:
            return self._empty_match_page(page, page_size)

        db = self.db if self.db is not None else _get_db()
        detail_by_match_id: Dict[int, Dict[str, Any]] = {}
        participant_query = self._build_participant_detail_query(
            server=server,
            name=name,
            global_id=target_global_id,
            global_role_id=global_role_id,
            role_id=role_id,
            game_role_id=game_role_id,
        )
        try:
            participant_cursor = db.jjc_match_detail.find(participant_query)
            participant_docs = await participant_cursor.to_list(length=None)
        except Exception as exc:
            logger.warning(
                f"按 global_id 读取本地已同步 JJC 对局详情失败: global_id={target_global_id} error={exc}"
            )
            participant_docs = []

        participant_match_ids: List[int] = []
        for doc in participant_docs:
            mid = self._coerce_int(doc.get("match_id"))
            if mid is None:
                continue
            participant_match_ids.append(mid)
            detail_by_match_id[mid] = doc

        if not participant_match_ids:
            return self._empty_match_page(page, page_size)

        seen_by_match_id: Dict[int, Dict[str, Any]] = {}
        try:
            seen_cursor = db.jjc_sync_match_seen.find({
                "match_id": {"$in": participant_match_ids},
            })
            seen_docs = await seen_cursor.to_list(length=None)
            for doc in seen_docs:
                mid = self._coerce_int(doc.get("match_id"))
                if mid is not None:
                    seen_by_match_id[mid] = doc
        except Exception as exc:
            logger.warning(f"读取本地已同步 JJC 对局 seen 状态失败: global_id={target_global_id} error={exc}")

        detail_docs = list(detail_by_match_id.values())

        valid_items: List[Dict[str, Any]] = []
        for doc in detail_docs:
            mid = self._coerce_int(doc.get("match_id"))
            if mid is None:
                continue
            data = doc.get("data")
            if not isinstance(data, dict) or data.get("unavailable"):
                continue
            detail = data.get("detail")
            if not isinstance(detail, dict):
                continue
            basic_info = detail.get("basic_info") if isinstance(detail.get("basic_info"), dict) else {}
            if not self._is_local_3v3_detail(detail):
                continue
            summary = self._build_cached_detail_summary(mid, doc.get("cached_at"), detail)
            if summary is None:
                continue
            target = self._find_target_player_context(
                detail,
                server=server,
                name=name,
                global_id=target_global_id,
                global_role_id=global_role_id,
                role_id=role_id,
                game_role_id=game_role_id,
            )
            if target is None:
                continue
            target_team = target["team"]
            target_player = target["player"]
            seen = seen_by_match_id.get(mid) or {}
            match_time = (
                self._coerce_int(seen.get("match_time"))
                or self._coerce_int(detail.get("match_time"))
                or self._coerce_int(basic_info.get("start_time"))
            )
            valid_items.append({
                "match_id": mid,
                "won": bool(target_team.get("won")),
                "kungfu": target_player.get("kungfu"),
                "avg_grade": self._coerce_int(basic_info.get("grade") or detail.get("avg_grade")),
                "total_mmr": self._coerce_int(
                    target_player.get("total_mmr")
                    or target_player.get("totalMmr")
                    or target_player.get("total_score")
                    or target_player.get("score")
                    or target_player.get("mmr")
                    or target_team.get("total_mmr")
                    or detail.get("total_mmr")
                ),
                "mmr_delta": self._coerce_int(
                    target_player.get("mmr_delta")
                    or target_player.get("mmrDelta")
                    or target_player.get("score_delta")
                    or target_player.get("scoreDelta")
                    or detail.get("mmr_delta")
                ),
                "mvp": bool(target_player.get("mvp")),
                "match_time": match_time,
                "start_time": self._coerce_int(basic_info.get("start_time")) or match_time,
                "duration": self._coerce_int(basic_info.get("duration") or detail.get("duration")),
                "cached_detail_summary": summary,
                "sync": {
                    "status": seen.get("status") or "not_synced",
                    "detail_saved_at": seen.get("detail_saved_at"),
                    "match_time": seen.get("match_time"),
                    "source_identity_id": str(seen.get("source_identity_id")) if seen.get("source_identity_id") is not None else None,
                    "source_identity_key": seen.get("source_identity_key"),
                },
            })

        valid_items.sort(key=lambda item: item.get("match_time") or item.get("start_time") or 0, reverse=True)
        total = len(valid_items)
        items = valid_items[skip:skip + page_size]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    @classmethod
    def _is_local_3v3_detail(cls, detail: Dict[str, Any]) -> bool:
        return JjcMatchParticipantRepo.is_local_3v3_detail(detail)

    @classmethod
    def _build_participant_detail_query(
        cls,
        *,
        server: Optional[str],
        name: Optional[str],
        global_id: Optional[str],
        global_role_id: Optional[str],
        role_id: Optional[str],
        game_role_id: Optional[str],
    ) -> Dict[str, Any]:
        terms: List[Dict[str, Any]] = []
        value = cls._pick_str(global_id)
        if value:
            for team_key in ("team1", "team2"):
                terms.append({f"data.detail.{team_key}.players_info.global_id": value})

        if not terms:
            return {}
        return {
            "data.unavailable": {"$ne": True},
            "$or": terms,
        }

    @staticmethod
    def _normalize_match_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if "·" in text:
            text = text.split("·")[0]
        return text

    @classmethod
    def _pick_str(cls, *values: Any) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @classmethod
    def _find_target_player_context(
        cls,
        detail: Dict[str, Any],
        *,
        server: Optional[str],
        name: Optional[str],
        global_id: Optional[str],
        global_role_id: Optional[str],
        role_id: Optional[str],
        game_role_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        expected_global_id = cls._pick_str(global_id)
        if not expected_global_id:
            return None

        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info") or []
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                score = 0
                player_global_id = cls._pick_str(player.get("global_id"), player.get("globalId"))

                if player_global_id == expected_global_id:
                    score = 40

                if score > best_score:
                    best_score = score
                    best = {"team_key": team_key, "team": team, "player": player}

        return best

    @staticmethod
    def _extract_source_field(summary: Dict[str, Any], field: str) -> Optional[Any]:
        for team_key in ("team1", "team2"):
            team = summary.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players") or []
            if players and isinstance(players[0], dict) and players[0].get(field) is not None:
                return players[0].get(field)
        return None

    @staticmethod
    def _extract_source_won(summary: Dict[str, Any]) -> bool:
        team = summary.get("team1")
        if isinstance(team, dict):
            return bool(team.get("won"))
        return False

    @staticmethod
    def _build_cached_detail_summary(match_id: int, cached_at: Any, detail: dict[str, Any]) -> Optional[dict[str, Any]]:
        teams: dict[str, Any] = {}
        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players: list[dict[str, Any]] = []
            for p in (team.get("players_info") or []):
                if not isinstance(p, dict):
                    continue
                player_summary: dict[str, Any] = {}
                for field in ("kungfu_id", "kungfu", "role_name", "server"):
                    val = p.get(field)
                    if val is not None:
                        player_summary[field] = val
                if player_summary:
                    players.append(player_summary)
            teams[team_key] = {
                "won": bool(team.get("won")),
                "players": players,
            }
        if not teams:
            return None
        return {
            "match_id": match_id,
            "cached_at": cached_at,
            "team1": teams.get("team1", {"won": False, "players": []}),
            "team2": teams.get("team2", {"won": False, "players": []}),
        }

    async def save_role_indicator(self, cache_key: str, payload: dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.jjc_role_indicator.update_one(
                {"cache_key": cache_key},
                {"$set": {
                    "cache_key": cache_key,
                    "identity_key": payload.get("identity_key"),
                    "server": payload.get("server"),
                    "name": payload.get("name"),
                    "game_role_id": payload.get("game_role_id"),
                    "global_id": payload.get("global_id"),
                    "global_role_id": payload.get("global_role_id"),
                    "zone": payload.get("zone"),
                    "indicator": payload.get("indicator") or {},
                    "raw": payload.get("raw") or {},
                    "cached_at": payload.get("cached_at") or time.time(),
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(f"保存 JJC 角色 indicator 缓存失败: cache_key={cache_key} error={exc}")

    async def load_role_indicator(self, cache_key: str, *, ttl_seconds: int = 600) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_role_indicator.find_one({"cache_key": cache_key})
        except Exception as exc:
            logger.warning(f"读取 JJC 角色 indicator 缓存失败: cache_key={cache_key} error={exc}")
            return None
        if doc is None:
            return None
        cached_at = doc.get("cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        if time.time() - float(cached_at) > ttl_seconds:
            logger.info(f"JJC 角色 indicator 缓存已过期: cache_key={cache_key}")
            return None
        return {
            "cache_key": doc.get("cache_key"),
            "identity_key": doc.get("identity_key"),
            "server": doc.get("server"),
            "name": doc.get("name"),
            "game_role_id": doc.get("game_role_id"),
            "global_role_id": doc.get("global_role_id"),
            "zone": doc.get("zone"),
            "indicator": doc.get("indicator") or {},
            "raw": doc.get("raw") or {},
            "cached_at": cached_at,
        }

    async def _extract_snapshots(self, data: dict[str, Any], cached_at: Optional[float] = None) -> None:
        """For each player with armors/talents, save to snapshot collections and replace with hashes.

        Modifies *data* in-place.  If snapshot_repo is None, the method is a no-op.
        Exceptions from snapshot saving propagate so callers can abort the match_detail write.
        """
        if self.snapshot_repo is None:
            return
        if data.get("unavailable"):
            return
        detail = data.get("detail")
        if not isinstance(detail, dict):
            return
        seen_at = cached_at or time.time()

        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info") or []
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue

                armors = player.get("armors")
                if isinstance(armors, list) and armors:
                    snapshot = build_equipment_snapshot(armors)
                    h = snapshot["snapshot_hash"]
                    await self.snapshot_repo.save_equipment_snapshot(h, snapshot["armors"], seen_at=seen_at)
                    player["equipment_snapshot_hash"] = h
                    player.pop("armors", None)

                talents = player.get("talents")
                if isinstance(talents, list) and talents:
                    snapshot = build_talent_snapshot(talents)
                    h = snapshot["snapshot_hash"]
                    await self.snapshot_repo.save_talent_snapshot(h, snapshot["talents"], seen_at=seen_at)
                    player["talent_snapshot_hash"] = h
                    player.pop("talents", None)
