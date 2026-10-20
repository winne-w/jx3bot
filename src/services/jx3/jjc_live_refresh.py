"""Latest-list refresh use case, independent from full history sync watermarks."""
import asyncio
import time
import uuid
from typing import Any, Dict, Optional

from nonebot import logger

from src.storage.mongo_repos.jjc_live_refresh_repo import JjcLiveRefreshRepo


def _integer(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_history(items, *, season_start, observed_at, names=None):
    rows = {}
    for item in items:
        if not isinstance(item, dict) or _integer(item.get("pvp_type", item.get("pvpType"))) != 3:
            continue
        match_id = _integer(item.get("match_id", item.get("matchId")))
        start = _integer(item.get("start_time", item.get("startTime")))
        if not match_id or match_id < 0 or not start or start < season_start or start > observed_at:
            continue
        end = _integer(item.get("end_time", item.get("endTime")))
        kungfu = str(item.get("kungfu") or "")
        rows[match_id] = {"match_id": match_id, "pvp_type": 3, "match_time": start,
            "start_time": start, "end_time": end, "duration": max(0, end - start) if end else None,
            "won": item.get("won") in (True, 1), "mvp": item.get("mvp") in (True, 1),
            "kungfu": (names or {}).get(kungfu, kungfu),
            "total_mmr": _integer(item.get("total_mmr")), "mmr_delta": _integer(item.get("mmr")),
            "observed_at": observed_at}
    return sorted(rows.values(), key=lambda row: (row["match_time"], row["match_id"]), reverse=True)[:40]


class LiveRefreshError(Exception):
    def __init__(self, state, retry_after=0):
        self.state, self.retry_after = state, retry_after


class JjcLiveRefreshService:
    def __init__(self, *, identity_repo, history_client, indicator_client, season,
                 season_start, repo=None, names=None, enabled=None, readiness=None):
        self.identity_repo = identity_repo
        self.history_client = history_client
        self.indicator_client = indicator_client
        self.season = season
        self.season_start = season_start
        self.repo = repo or JjcLiveRefreshRepo()
        self.names = names or {}
        self._enabled = enabled or (lambda: False)
        self._readiness = readiness

    def enabled(self):
        return bool(self._enabled())

    async def readiness(self):
        if self._readiness:
            return await asyncio.to_thread(self._readiness)
        import config as cfg
        required = (cfg.TUILAN_SECRET_KEY, cfg.TUILAN_DEVICE_ID, cfg.TICKET)
        return {"state": "ready" if all(str(value or "").strip() for value in required) else "invalid_config"}

    async def resolve(self, server, name):
        return await self.identity_repo.find_best_by_name_with_id(server, name)

    async def read(self, identity_id):
        # Purely local even with the live feature disabled or the official provider paused.
        data = await self.repo.read(self.repo.key(identity_id, self.season))
        data["refresh"]["enabled"] = self.enabled()
        if not self.enabled():
            data["refresh"]["state"] = "disabled"
        return data

    async def submit(self, *, server, name):
        if not self.enabled():
            return {"state": "disabled"}
        guard = await self.readiness()
        if guard.get("state") != "ready":
            return {"state": guard.get("state", "storage_unavailable"), "retry_after_seconds": 60}
        if not await self.repo.worker_online():
            return {"state": "worker_unavailable", "retry_after_seconds": 20}
        identity = await self.resolve(server, name)
        if not identity or not identity.get("_id"):
            return {"state": "identity_unavailable"}
        return await self.repo.submit(identity, self.season)

    async def _call(self, task, func, **kwargs):
        while time.time() < task["until"]:
            payload = await asyncio.to_thread(func, **kwargs)
            if not isinstance(payload, dict):
                raise LiveRefreshError("refresh_failed")
            error = payload.get("error")
            if error:
                retry = max(1, int(payload.get("retry_after_seconds") or 60))
                raise LiveRefreshError("refresh_failed", retry)
            if payload.get("code") != 0:
                raise LiveRefreshError("refresh_failed")
            return payload
        raise LiveRefreshError("expired")

    async def execute(self, task):
        try:
            identity = task["identity"]
            sk01 = str(identity.get("global_role_id") or "")
            if not sk01.startswith("SK01"):
                if not all(identity.get(key) for key in ("role_id", "zone", "server")):
                    raise LiveRefreshError("identity_unavailable")
                indicator = await self._call(task, self.indicator_client.get_role_indicator,
                    role_id=identity["role_id"], zone=identity["zone"], server=identity["server"])
                info = (indicator.get("data") or {}).get("role_info") or {}
                # Require positive matching identity evidence, not merely a returned SK01.
                if (str(info.get("role_id")) != str(identity["role_id"])
                        or str(info.get("server")) != str(identity["server"])
                        or str(info.get("zone")) != str(identity["zone"])):
                    raise LiveRefreshError("identity_unavailable")
                sk01 = str(info.get("global_role_id") or "")
                if not sk01.startswith("SK01"):
                    raise LiveRefreshError("identity_unavailable")
            previous = await self.repo.read(task["task_key"])
            known = {row["match_id"] for row in previous["latest_matches"]}
            raw = []
            for page in range(2):
                response = await self._call(task, self.history_client.get_mine_match_history,
                                           global_role_id=sk01, size=20, cursor=page * 20)
                items = response.get("data")
                if not isinstance(items, list):
                    raise LiveRefreshError("refresh_failed")
                raw.extend(items)
                rows = normalize_history(raw, season_start=self.season_start,
                                         observed_at=time.time(), names=self.names)
                boundary = any(row["match_id"] in known for row in rows)
                limited = len(items) >= 20 and not boundary
                merged = {row["match_id"]: row for row in previous["latest_matches"]}
                merged.update({row["match_id"]: row for row in rows})
                rows = sorted(merged.values(), key=lambda row: (row["match_time"], row["match_id"]), reverse=True)[:40]
                # First page is immediately visible; the immutable pointer is fenced.
                if not await self.repo.publish(task, rows, limited=limited):
                    raise LiveRefreshError("expired")
                if not limited:
                    break
            await self.repo.finish(task)
        except LiveRefreshError as exc:
            await self.repo.finish(task, error=exc.state, retry_after=exc.retry_after)
        except asyncio.CancelledError:
            # Threaded in-flight request may still finish after cancellation.
            raise
        except Exception as exc:
            logger.warning("JJC 最新刷新失败: exception_type={}", type(exc).__name__)
            await self.repo.finish(task, error="refresh_failed")

    async def run_worker(self):
        worker_id = uuid.uuid4().hex
        await self.repo.initialize()

        async def heartbeat():
            while True:
                await self.repo.heartbeat(worker_id)
                await asyncio.sleep(5)

        heart = asyncio.create_task(heartbeat())
        try:
            while self.enabled():
                if heart.done():
                    await heart
                task = await self.repo.claim()
                if task:
                    await self.execute(task)
                else:
                    await asyncio.sleep(1)
        finally:
            heart.cancel()
            await asyncio.gather(heart, return_exceptions=True)
            await self.repo.heartbeat(worker_id, online=False)
