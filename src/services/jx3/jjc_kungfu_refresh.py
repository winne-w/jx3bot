"""Single-consumer orchestration with monotonic role publication then guarded ack."""
import asyncio
import time
from typing import Any, Callable, Dict, Optional, Union

from nonebot import logger

from src.infra.tuilan_kungfu_client import KungfuQueryError
from src.services.jx3.jjc_kungfu_classifier import select_kungfu
from src.services.jx3.jjc_kungfu_meta import get_jjc_kungfu_catalog
from src.services.jx3.jjc_kungfu_policy import KungfuPolicy, positive_integer, retry_delay, valid_timestamp
from src.storage.mongo_repos.jjc_kungfu_refresh_repo import QueueIntegrityError

_LOCATOR_FIELDS = ("server", "name", "zone", "game_role_id", "role_id", "global_id", "global_role_id")
_LEASE_SECONDS = 90


def _locator(identity: Dict[str, Any]) -> Dict[str, Any]:
    # Missing and explicitly null are distinct parts of the publication guard.
    return {key: identity[key] for key in _LOCATOR_FIELDS if key in identity}


def _same_publication(value: Any, generation: int, scope: Dict[str, Any]) -> bool:
    return (isinstance(value, dict) and positive_integer(value.get("publish_version"))
            and value["publish_version"] == generation
            and all(type(value.get(key)) is type(expected) and value.get(key) == expected
                    for key, expected in scope.items()))


class JjcKungfuRefreshService:
    def __init__(
        self, identity_repo: Any, queue_repo: Any, client: Any,
        policy: Union[KungfuPolicy, Callable[[], KungfuPolicy]],
        mapping: Dict[str, str], clock: Callable[[], float] = time.time,
    ) -> None:
        self.identity_repo, self.queue_repo, self.client = identity_repo, queue_repo, client
        self.policy, self.mapping, self.clock = policy, mapping, clock
        self.cooldown_until = 0.0
        self._execution_lock: Optional[asyncio.Lock] = None
        self._canonical_ids = {entry["name"]: entry["id"] for entry in get_jjc_kungfu_catalog()}

    def _policy(self) -> KungfuPolicy:
        policy = self.policy() if callable(self.policy) else self.policy
        if not isinstance(policy, KungfuPolicy):
            raise ValueError("invalid kungfu refresh policy")
        return policy

    async def initialize(self) -> None:
        self._policy()
        # Leave a fixed margin for the two Mongo writes and uncertain-write readback.
        if not 0 < self.client.attempt_timeout < _LEASE_SECONDS - 10:
            raise ValueError("kungfu attempt budget must leave lease finalization time")
        await self.queue_repo.ensure_indexes()

    async def _complete(self, task: Dict[str, Any], next_run_at: float,
                        error_code: Optional[str] = None) -> None:
        accepted = await self.queue_repo.complete(task, self.clock(), next_run_at,
                                                  error_code=error_code)
        if not accepted:
            logger.warning("JJC kungfu refresh lost task lease: identity_id={}", task["_id"])

    async def _failure(self, task: Dict[str, Any], code: str,
                       minimum_delay: float = 0) -> None:
        delay = max(retry_delay(task.get("consecutive_failures", 0) + 1), minimum_delay)
        logger.warning("JJC kungfu refresh failed: identity_id={} code={}", task["_id"], code)
        await self._complete(task, self.clock() + delay, code)

    async def _still_owned(self, task: Dict[str, Any], policy: KungfuPolicy) -> bool:
        if self._policy().scope != policy.scope:
            return False
        current = await self.queue_repo.get_by_id(task["_id"])
        return bool(current and current.get("status") == "running"
                    and current.get("generation") == task["generation"]
                    and current.get("lease_token") == task["lease_token"]
                    and current.get("scope") == task["scope"]
                    and current.get("lease_expires_at", 0) > self.clock())

    async def _publish(
        self, task: Dict[str, Any], locator: Dict[str, Any], result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Resolve uncertain writes by reading; a failed read leaves the lease alone."""
        uncertain = False
        try:
            published = await self.identity_repo.publish_jjc_kungfu_if_newer(
                task["_id"], locator, task["generation"], result)
        except Exception as exc:
            # CancelledError is a BaseException on supported Python versions.
            # Do not confirm an attempt whose caller is cancelling.
            uncertain = True
            published = False
            logger.warning("JJC kungfu publication response unknown: identity_id={} exception_type={}",
                           task["_id"], type(exc).__name__)
        if published:
            return result
        # This await must propagate database errors: no safe conclusion was reached.
        current = await self.identity_repo.get_by_id(task["_id"])
        saved = current.get("jjc_kungfu") if current else None
        if _same_publication(saved, task["generation"], task["scope"]):
            return saved
        if not current:
            code = "identity_missing"
        elif _locator(current) != locator:
            code = "identity_changed"
        elif (isinstance(saved, dict) and positive_integer(saved.get("publish_version"))
              and saved["publish_version"] > task["generation"]):
            code = "superseded"
        else:
            code = "publication_unconfirmed" if uncertain else "publication_rejected"
        await self._failure(task, code)
        return None

    def _execution_position(self) -> asyncio.Lock:
        # Python 3.9 binds locks to a loop at construction: create it at runtime.
        if self._execution_lock is None:
            self._execution_lock = asyncio.Lock()
        return self._execution_lock

    async def run_once(self) -> bool:
        async with self._execution_position():
            if self.clock() < self.cooldown_until:
                return False
            policy = self._policy()
            await self.queue_repo.recover_expired(self.clock())
            task = await self.queue_repo.claim(policy.scope, self.clock(), lease_seconds=_LEASE_SECONDS)
            if task is None:
                return False
            await self._execute(task, policy)
            return True

    async def query_now(self, identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Query and persist this role in the current call, never wait for a worker.

        Without a durable generation reservation, no safe publication is possible.
        Database or upstream failures return unknown; cancellation still propagates.
        """
        async with self._execution_position():
            identity_id = identity.get("_id")
            if self.clock() < self.cooldown_until:
                logger.warning("JJC direct kungfu query skipped: identity_id={} code=upstream_cooldown", identity_id)
                return None
            try:
                policy = self._policy()
                await self.queue_repo.register([identity], policy.scope, self.clock(),
                                               track_seconds=policy.track_seconds)
                task = await self.queue_repo.claim_identity(identity_id, policy.scope, self.clock(),
                                                            lease_seconds=_LEASE_SECONDS)
            except Exception as exc:
                logger.error("JJC direct kungfu query failed: identity_id={} code=reservation_failed exception_type={}",
                             identity_id, type(exc).__name__)
                return None
            if task is None:
                logger.warning("JJC direct kungfu query failed: identity_id={} code=reservation_unavailable", identity_id)
                return None
            try:
                return await self._execute(task, policy, expected_locator=_locator(identity))
            except QueueIntegrityError:
                logger.error("JJC direct kungfu query failed: identity_id={} code=queue_integrity_error", identity_id)
                return None
            except Exception as exc:
                logger.error("JJC direct kungfu query failed: identity_id={} code=persistence_failed exception_type={}",
                             identity_id, type(exc).__name__)
                # Publication may have succeeded before acknowledgement failed. Use
                # only this exact durable result, leaving task recovery to its lease.
                try:
                    current = await self.identity_repo.get_by_id(identity_id)
                except Exception as read_error:
                    logger.error("JJC direct kungfu readback failed: identity_id={} code=readback_failed exception_type={}",
                                 identity_id, type(read_error).__name__)
                    return None
                saved = current.get("jjc_kungfu") if current else None
                return saved if _same_publication(saved, task["generation"], task["scope"]) else None

    async def _execute(
        self, task: Dict[str, Any], policy: KungfuPolicy,
        expected_locator: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        identity = await self.identity_repo.get_by_id(task["_id"])
        if identity is None:
            await self._failure(task, "identity_missing")
            return None
        if "jjc_kungfu" in identity:
            old = identity["jjc_kungfu"]
            if (not isinstance(old, dict) or not positive_integer(old.get("publish_version"))):
                await self._failure(task, "invalid_publication_schema")
                return None
            if old["publish_version"] >= task["generation"]:
                if not await self._still_owned(task, policy):
                    logger.warning("JJC kungfu query discarded: identity_id={} code=execution_lost", task["_id"])
                    return None
                logger.error("JJC kungfu queue version regressed: identity_id={} claimed={} published={}",
                             task["_id"], task["generation"], old["publish_version"])
                # A fresh claim must be above every preexisting publication.
                # Retrying would silently rebuild a corrupted counter online.
                raise QueueIntegrityError("claimed generation does not exceed role publication")
        locator = _locator(identity)
        if expected_locator is not None and locator != expected_locator:
            await self._failure(task, "identity_changed")
            return None
        try:
            evidence = await self.client.query(identity, task["scope"])
        except KungfuQueryError as exc:
            delay = exc.retry_after or 0
            if exc.auth or exc.code == "rate_limited":
                delay = min(3600, max(300 if exc.auth or not delay else 1, delay))
                self.cooldown_until = max(self.cooldown_until, self.clock() + delay)
                logger.error("JJC kungfu upstream cooling down: code={} seconds={}", exc.code, delay)
            await self._failure(task, exc.code, delay)
            return None
        except Exception as exc:
            logger.warning("JJC kungfu query failed: exception_type={}", type(exc).__name__)
            await self._failure(task, "query_failed")
            return None
        try:
            selected = select_kungfu(evidence["indicator_data"], evidence["matches"], self.mapping)
            name = selected["kungfu"]
            requested_at = evidence["requested_at"]
        except (KeyError, TypeError, AttributeError, ValueError):
            await self._failure(task, "invalid_query_response")
            return None
        if name not in self._canonical_ids:
            await self._failure(task, "unknown_kungfu")
            return None
        verified_at = self.clock()
        if not valid_timestamp(requested_at) or requested_at > verified_at:
            await self._failure(task, "invalid_query_time")
            return None
        if not await self._still_owned(task, policy):
            logger.warning("JJC kungfu query discarded: identity_id={} code=execution_lost", task["_id"])
            return None
        result = {**task["scope"], "name": name, "kungfu_id": self._canonical_ids[name],
                  "source": selected["kungfu_selected_source"], "requested_at": requested_at,
                  "verified_at": verified_at,
                  "win_sample_count": len(selected["match_history_win_samples"]),
                  "publish_version": task["generation"]}
        saved = await self._publish(task, locator, result)
        if saved is not None:
            await self._complete(task, saved["verified_at"] + policy.refresh_seconds)
        return saved
