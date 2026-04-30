from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Optional, Union

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db
from src.services.jx3.match_detail_snapshots import (
    build_equipment_snapshot,
    build_talent_snapshot,
)
from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo


@dataclass(frozen=True)
class JjcInspectRepo:
    db: Optional[AsyncIOMotorDatabase] = None
    snapshot_repo: Optional[JjcMatchSnapshotRepo] = None

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

        Old-format players that already have armors/talents fields are left unchanged.
        Missing snapshots yield empty arrays with a warning instead of failing the match.
        """
        if self.snapshot_repo is None:
            return
        data = doc.get("data")
        if not isinstance(data, dict):
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
                if "armors" not in player:
                    h = player.get("equipment_snapshot_hash")
                    if isinstance(h, str) and h:
                        equip_hashes.add(h)
                if "talents" not in player:
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
                if "armors" not in player:
                    h = player.get("equipment_snapshot_hash")
                    if isinstance(h, str) and h:
                        snap = equip_snapshots.get(h)
                        if snap is not None:
                            player["armors"] = snap.get("armors", [])
                        else:
                            logger.warning(f"装备快照缺失: match_id={match_id} equipment_snapshot_hash={h}")
                            player["armors"] = []
                if "talents" not in player:
                    h = player.get("talent_snapshot_hash")
                    if isinstance(h, str) and h:
                        snap = talent_snapshots.get(h)
                        if snap is not None:
                            player["talents"] = snap.get("talents", [])
                        else:
                            logger.warning(f"奇穴快照缺失: match_id={match_id} talent_snapshot_hash={h}")
                            player["talents"] = []

    async def _extract_snapshots(self, data: dict[str, Any], cached_at: Optional[float] = None) -> None:
        """For each player with armors/talents, save to snapshot collections and replace with hashes.

        Modifies *data* in-place.  If snapshot_repo is None, the method is a no-op.
        Exceptions from snapshot saving propagate so callers can abort the match_detail write.
        """
        if self.snapshot_repo is None:
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
