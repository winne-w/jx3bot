"""Maintained kungfu aliases; thin re-export from src.domain.kungfu_catalog."""
from src.domain.kungfu_catalog import (
    AMBIGUOUS_KUNGFU_ALIASES,
    KUNGFU_ALIASES,
    KungfuAliasError,
    resolve_kungfu_alias,
)

__all__ = [
    "AMBIGUOUS_KUNGFU_ALIASES",
    "KUNGFU_ALIASES",
    "KungfuAliasError",
    "resolve_kungfu_alias",
]
