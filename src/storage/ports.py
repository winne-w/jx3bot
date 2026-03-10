from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class CacheEntryStorage(Protocol):
    def get_payload(self, namespace: str, key: str) -> Any | None: ...

    def upsert_payload(
        self,
        namespace: str,
        key: str,
        payload: Any,
        *,
        expires_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None: ...


class JjcCacheStorage(Protocol):
    def load_ranking_cache(self) -> dict[str, Any] | None: ...

    def save_ranking_cache(self, ranking_result: dict[str, Any], *, ttl_seconds: int) -> None: ...

    def load_kungfu_cache(self, server: str, name: str, *, allow_expired: bool = False) -> dict[str, Any] | None: ...

    def save_kungfu_cache(
        self,
        server: str,
        name: str,
        result: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None: ...


class ReminderStorage(Protocol):
    def load_grouped(self) -> dict[str, list[dict[str, Any]]]: ...

    def list_pending_by_group(self, group_id: str) -> list[dict[str, Any]]: ...

    def list_pending_by_user(self, group_id: str, user_id: str) -> list[dict[str, Any]]: ...

    def create(self, reminder: dict[str, Any]) -> None: ...

    def update_pending(self, reminder_id: str, updates: dict[str, Any]) -> bool: ...

    def find_pending(self, reminder_id: str) -> dict[str, Any] | None: ...


class SubscriptionStorage(Protocol):
    def load_grouped_by_user(self) -> dict[str, list[dict[str, Any]]]: ...

    def replace_grouped_by_user(self, subscriptions: dict[str, list[dict[str, Any]]]) -> None: ...

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]: ...

    def list_all_grouped_by_user(self) -> dict[str, list[dict[str, Any]]]: ...

    def add(self, user_id: str, item: dict[str, Any]) -> dict[str, Any] | None: ...

    def remove_by_index(self, user_id: str, index: int) -> dict[str, Any] | None: ...


class JjcRankingStatsStorage(Protocol):
    def list_timestamps(self) -> list[int]: ...

    def read(self, timestamp: int) -> dict[str, Any] | None: ...

    def save(self, timestamp: int, payload: dict[str, Any]) -> None: ...
