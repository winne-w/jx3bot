"""Server-side catalog for kungfus displayed by the JJC matchup page."""

from typing import Any, Dict, List

from config import KUNGFU_META
from src.domain.kungfu_catalog import ALLOWED_CATEGORIES, get_jjc_catalog_specs


_ALLOWED_CATEGORIES = ALLOWED_CATEGORIES

_CONFIG_META_BY_NAME: Dict[str, Dict[str, str]] = {}
for _meta in KUNGFU_META.values():
    if not isinstance(_meta, dict):
        continue
    _name = _meta.get("name")
    _category = _meta.get("category")
    if not isinstance(_name, str) or not _name.strip():
        continue
    _normalized_name = _name.strip()
    _config_meta = {"name": _normalized_name}
    if isinstance(_category, str) and _category.strip() in _ALLOWED_CATEGORIES:
        _config_meta["category"] = _category.strip()
    _CONFIG_META_BY_NAME[_normalized_name] = _config_meta


def get_jjc_kungfu_catalog() -> List[Dict[str, Any]]:
    """Return a fresh, display-ordered JJC kungfu catalog for API consumers."""
    catalog: List[Dict[str, Any]] = []
    for spec in get_jjc_catalog_specs():
        config_meta = _CONFIG_META_BY_NAME.get(spec.name, {})
        catalog.append({
            "id": spec.id,
            "name": config_meta.get("name") or spec.name,
            "category": config_meta.get("category") or spec.category,
            "icon_id": spec.id,
            "display_order": spec.display_order,
        })
    return catalog
