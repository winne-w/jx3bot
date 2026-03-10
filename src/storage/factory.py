from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import config as cfg
except Exception:  # pragma: no cover
    cfg = None  # type: ignore


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MongoSettings:
    enabled: bool
    uri: str
    database: str


def load_mongo_settings() -> MongoSettings:
    env_uri = os.getenv("JX3BOT_MONGO_URI", "").strip()
    cfg_uri = str(getattr(cfg, "MONGO_URI", "") or "").strip()
    uri = env_uri or cfg_uri

    env_db = os.getenv("JX3BOT_MONGO_DB", "").strip()
    cfg_db = str(getattr(cfg, "MONGO_DB", "") or "").strip()
    database = env_db or cfg_db or "jx3bot"

    enabled_flag = os.getenv("JX3BOT_MONGO_ENABLED")
    cfg_enabled = getattr(cfg, "MONGO_ENABLED", None)
    enabled = _as_bool(enabled_flag, default=_as_bool(cfg_enabled, default=bool(uri)))

    return MongoSettings(enabled=enabled and bool(uri), uri=uri, database=database)
