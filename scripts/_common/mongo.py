"""Shared MongoDB connection and URI resolution helpers for maintenance scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlsplit

DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27017/jx3bot"
DEFAULT_DB_NAME = "jx3bot"

_ROOT = Path(__file__).resolve().parents[2]


def _ensure_repo_root_on_path() -> None:
    root_str = str(_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def resolve_mongo_uri(explicit_uri: Optional[str] = None) -> str:
    """Resolve MongoDB URI: explicit argument > MONGO_URI env > config.MONGO_URI > default."""
    if explicit_uri is not None:
        cleaned = str(explicit_uri).strip()
        if cleaned:
            return cleaned

    env_uri = os.getenv("MONGO_URI")
    if env_uri is not None:
        cleaned_env = str(env_uri).strip()
        if cleaned_env:
            return cleaned_env

    _ensure_repo_root_on_path()
    try:
        import config  # type: ignore

        cfg_uri = getattr(config, "MONGO_URI", None)
        if cfg_uri is not None:
            cleaned_cfg = str(cfg_uri).strip()
            if cleaned_cfg:
                return cleaned_cfg
    except Exception:
        pass

    return DEFAULT_MONGO_URI


def resolve_db_name(uri: str, default: str = DEFAULT_DB_NAME) -> str:
    """Extract database name from a MongoDB URI, falling back to ``default`` when absent."""
    path = urlsplit(str(uri or "").strip()).path.lstrip("/")
    db_name = unquote(path).split("/", 1)[0].strip()
    return db_name or default


def resolve_database(
    client: Any,
    uri: str,
    default: str = DEFAULT_DB_NAME,
    *,
    db_name: Optional[str] = None,
) -> Any:
    """Return the selected database from ``client`` using an explicit name or URI path."""
    if db_name is not None and str(db_name).strip():
        return client[str(db_name).strip()]
    return client[resolve_db_name(uri, default=default)]


def open_sync_client(
    uri: Optional[str] = None,
    *,
    server_selection_timeout_ms: int = 8000,
    **kwargs: Any,
) -> Any:
    """Open a synchronous ``pymongo.MongoClient`` with resolved URI and timeout."""
    from pymongo import MongoClient

    resolved_uri = resolve_mongo_uri(uri)
    kwargs.setdefault("serverSelectionTimeoutMS", server_selection_timeout_ms)
    return MongoClient(resolved_uri, **kwargs)


def open_async_client(
    uri: Optional[str] = None,
    *,
    server_selection_timeout_ms: int = 8000,
    **kwargs: Any,
) -> Any:
    """Open an asynchronous ``AsyncIOMotorClient`` with resolved URI and timeout."""
    from motor.motor_asyncio import AsyncIOMotorClient

    resolved_uri = resolve_mongo_uri(uri)
    kwargs.setdefault("serverSelectionTimeoutMS", server_selection_timeout_ms)
    return AsyncIOMotorClient(resolved_uri, **kwargs)
