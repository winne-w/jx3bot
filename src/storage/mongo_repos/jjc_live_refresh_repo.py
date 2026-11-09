"""Bounded durable refresh tasks and fenced, immutable summary snapshots."""
import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from src.infra.mongo import get_db


class JjcLiveRefreshRepo:
    def __init__(self, db=None, *, capacity=100, cooldown=120, clock=time.time):
        self.db = db
        self.capacity = int(capacity)
        self.cooldown = int(cooldown)
        self.clock = clock

    def collection(self, name):
        db = self.db if self.db is not None else get_db()
        return db.get_collection(name, write_concern=WriteConcern(w="majority", wtimeout=3000))

    @staticmethod
    def key(identity_id, season):
        return hashlib.sha256((str(identity_id) + ":" + str(season) + ":3").encode()).hexdigest()

    async def initialize(self):
        if not 1 <= self.capacity <= 1000 or self.cooldown < 1:
            raise ValueError("invalid live refresh configuration")
        slots = self.collection("jjc_live_refresh_slots")
        await slots.update_one({"_id": "configuration"}, {"$setOnInsert": {
            "capacity": self.capacity, "cooldown": self.cooldown}}, upsert=True)
        settings = await slots.find_one({"_id": "configuration"})
        if settings.get("capacity") != self.capacity or settings.get("cooldown") != self.cooldown:
            raise ValueError("live refresh configuration differs between processes")
        for index in range(self.capacity):
            await slots.update_one({"_id": index}, {"$setOnInsert": {"until": 0}}, upsert=True)
        await slots.create_index("task_key", unique=True,
                                 partialFilterExpression={"task_key": {"$type": "string"}})
        summaries = self.collection("jjc_live_match_summaries")
        await summaries.create_index([("task_key", 1), ("snapshot_id", 1), ("match_id", 1)], unique=True)
        await summaries.create_index("match_id")
        await summaries.create_index("expires_at_dt", expireAfterSeconds=0)
        await self.collection("jjc_live_source_limits").create_index("expires_at_dt", expireAfterSeconds=0)

    async def heartbeat(self, worker_id, *, online=True):
        await self.collection("jjc_live_workers").update_one({"_id": worker_id}, {"$set": {
            "until": self.clock() + 20 if online else 0}}, upsert=True)

    async def worker_online(self):
        return bool(await self.collection("jjc_live_workers").find_one({"until": {"$gt": self.clock()}}))

    async def state(self, key):
        doc = await self.collection("jjc_live_refresh_state").find_one({"_id": key}) or {}
        return self._state_from_doc(doc)

    def _state_from_doc(self, doc):
        now = self.clock()
        state = doc.get("state", "idle")
        if state in ("queued", "running") and doc.get("active_until", 0) <= now:
            state = "expired"
        retry = max(0, int(doc.get("next_allowed_at", 0) - now + 0.999))
        if state == "success" and retry:
            state = "cooldown"
        return {"state": state, "last_checked_at": doc.get("last_checked_at"),
                "retry_after_seconds": retry, "coverage_limited": doc.get("coverage_limited", False)}

    async def read(self, key):
        states = self.collection("jjc_live_refresh_state")
        doc = await states.find_one({"_id": key}) or {}
        items = []
        if doc.get("snapshot_id"):
            cursor = self.collection("jjc_live_match_summaries").find({
                "task_key": key, "snapshot_id": doc["snapshot_id"],
                "expires_at_dt": {"$gt": datetime.fromtimestamp(self.clock(), timezone.utc)}},
                {"_id": 0, "task_key": 0, "snapshot_id": 0, "expires_at_dt": 0})
            items = await cursor.sort([("match_time", -1), ("match_id", -1)]).limit(40).to_list(40)
        return {"latest_matches": items, "refresh": self._state_from_doc(doc)}

    async def submit(self, identity, season):
        now = self.clock()
        key = self.key(identity["_id"], season)
        states = self.collection("jjc_live_refresh_state")
        try:
            await states.update_one({"_id": key}, {"$setOnInsert": {
                "active_until": 0, "next_allowed_at": 0}}, upsert=True)
        except DuplicateKeyError:
            pass
        generation = uuid.uuid4().hex
        admission = await states.find_one_and_update({"_id": key,
            "active_until": {"$lte": now}, "next_allowed_at": {"$lte": now}},
            {"$set": {"generation": generation, "active_until": now + 120,
                      "state": "queued", "next_allowed_at": now + self.cooldown}},
            return_document=ReturnDocument.AFTER)
        if not admission:
            return await self.state(key)
        slots = self.collection("jjc_live_refresh_slots")
        # Expired keys must be removed before a new generation can reuse the unique key.
        await slots.update_many({"task_key": key, "until": {"$lte": now}}, {"$unset": {"task_key": ""}})
        try:
            slot = await slots.find_one_and_update({"_id": {"$type": "number"}, "until": {"$lte": now}},
                {"$set": {"task_key": key, "generation": generation, "until": now + 120,
                          "state": "queued", "identity": identity, "season": season}},
                return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            slot = None
        if not slot:
            await states.update_one({"_id": key, "generation": generation}, {"$set": {
                "state": "queue_full", "active_until": 0, "next_allowed_at": now + 10}})
        return await self.state(key)

    async def claim(self):
        now = self.clock()
        slot = await self.collection("jjc_live_refresh_slots").find_one_and_update(
            {"state": "queued", "until": {"$gt": now}}, {"$set": {"state": "running"}},
            return_document=ReturnDocument.AFTER)
        if slot:
            await self.collection("jjc_live_refresh_state").update_one(
                self._fence(slot), {"$set": {"state": "running"}})
        return slot

    def _fence(self, task):
        return {"_id": task["task_key"], "generation": task["generation"],
                "active_until": {"$gt": self.clock()}}

    async def publish(self, task, rows, *, limited=False):
        # Immutable snapshot + fenced pointer update: a late worker cannot overwrite newer data.
        snapshot = uuid.uuid4().hex
        expires = datetime.fromtimestamp(self.clock() + 7 * 86400, timezone.utc)
        if rows:
            await self.collection("jjc_live_match_summaries").insert_many([
                {**row, "task_key": task["task_key"], "snapshot_id": snapshot,
                 "expires_at_dt": expires} for row in rows[:40]])
        result = await self.collection("jjc_live_refresh_state").update_one(self._fence(task),
            {"$set": {"snapshot_id": snapshot, "coverage_limited": limited}})
        return bool(result.modified_count)

    async def finish(self, task, *, error=None, retry_after=0):
        now = self.clock()
        states = self.collection("jjc_live_refresh_state")
        doc = await states.find_one(self._fence(task))
        if not doc:
            return
        fails = min(int(doc.get("fail_count", 0)) + 1, 5) if error else 0
        delay = max(retry_after, min(60 * 2 ** (fails - 1), 900)) if error else self.cooldown
        values = {"state": error or "success", "active_until": 0, "fail_count": fails,
                  "next_allowed_at": now + delay}
        if not error:
            values["last_checked_at"] = now
        await states.update_one(self._fence(task), {"$set": values})
        await self.collection("jjc_live_refresh_slots").update_one(
            {"_id": task["_id"], "generation": task["generation"]},
            {"$set": {"until": 0, "state": "idle"}, "$unset": {"task_key": ""}})

    async def allow_source(self, key, *, limit=6, window=60):
        collection = self.collection("jjc_live_source_limits")
        for _ in range(8):
            now = self.clock()
            doc = await collection.find_one({"_id": key})
            if doc is None:
                try:
                    await collection.insert_one({"_id": key, "version": 0, "times": []})
                except DuplicateKeyError:
                    pass
                continue
            times = [t for t in doc.get("times", []) if t > now - window]
            if len(times) >= limit:
                return False
            result = await collection.update_one({"_id": key, "version": doc["version"]},
                {"$set": {"times": times + [now],
                          "expires_at_dt": datetime.fromtimestamp(now + window * 2, timezone.utc)},
                 "$inc": {"version": 1}})
            if result.modified_count:
                return True
        return False
