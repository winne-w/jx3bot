import aiofiles
import aiohttp
import json
import os
import asyncio
from typing import Dict, List, Tuple
from nonebot.log import logger
from .config import config

# 排查期：直接使用 print 打印关键日志，不覆盖全局 logger

# 别名缓存：alias_name -> canonical_name(showName)
_alias_to_canonical: Dict[str, str] = {}
# 反向索引：canonical_name -> [alias_names]
_canonical_to_aliases: Dict[str, List[str]] = {}
_initialized: bool = False
_init_lock = asyncio.Lock()


def _get_value_case_insensitive(item: dict, key_lower: str) -> str:
    for k, v in item.items():
        if isinstance(k, str) and k.lower() == key_lower:
            return v if isinstance(v, str) else (str(v) if v is not None else "")
    return ""


def _collect_alias_pairs(obj, out: List[dict], category_ctx: str = ""):
    # 递归地从任意层级对象中收集带 name/showName 的条目，并传递分类上下文
    if isinstance(obj, dict):
        curr_cat = (
            (obj.get('searchDescType') or _get_value_case_insensitive(obj, 'searchdesctype'))
            or (obj.get('typeName') or _get_value_case_insensitive(obj, 'typename'))
            or category_ctx
            or ""
        )
        name = (obj.get('name') or _get_value_case_insensitive(obj, 'name') or '').strip()
        show_name = (obj.get('showName') or _get_value_case_insensitive(obj, 'showname') or '').strip()
        if name and show_name:
            out.append({'name': name, 'showName': show_name, 'category': str(curr_cat)})
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _collect_alias_pairs(v, out, curr_cat)
    elif isinstance(obj, list):
        for it in obj:
            _collect_alias_pairs(it, out, category_ctx)


def _flatten_alias_items(items: List[dict]) -> List[dict]:
    pairs: List[dict] = []
    _collect_alias_pairs(items, pairs)
    # 去重
    seen = set()
    flattened: List[dict] = []
    for it in pairs:
        key = (it['name'], it['showName'], it.get('category', ''))
        if key in seen:
            continue
        seen.add(key)
        flattened.append(it)
    print(f"[alias] flattened pairs: {len(flattened)}")
    for i, it in enumerate(flattened[:3]):
        print(f"[alias] flat[{i}] name={it['name']} showName={it['showName']} category={it.get('category','')}")
    return flattened


async def _build_from_items(items: List[dict]) -> Tuple[int, int]:
    loaded_alias = 0
    loaded_canonical = 0
    _alias_to_canonical.clear()
    _canonical_to_aliases.clear()
    total = len(items)
    miss_name = 0
    miss_show = 0
    miss_examples = []
    for it in items:
        if not isinstance(it, dict):
            if len(miss_examples) < 3:
                try:
                    miss_examples.append({
                        'type': str(type(it)),
                        'value': str(it)[:200]
                    })
                except Exception:
                    pass
            continue
        name = (it.get('name') or _get_value_case_insensitive(it, 'name') or '').strip()
        show_name = (it.get('showName') or _get_value_case_insensitive(it, 'showname') or '').strip()
        if not name or not show_name:
            if not name:
                miss_name += 1
            if not show_name:
                miss_show += 1
            if len(miss_examples) < 3:
                try:
                    miss_examples.append({
                        'keys': list(it.keys()),
                        'name': it.get('name') or _get_value_case_insensitive(it, 'name'),
                        'showName': it.get('showName') or _get_value_case_insensitive(it, 'showname')
                    })
                except Exception:
                    pass
            continue
        _alias_to_canonical[name] = show_name
        loaded_alias += 1
        if show_name not in _canonical_to_aliases:
            _canonical_to_aliases[show_name] = []
            loaded_canonical += 1
        if name not in _canonical_to_aliases[show_name]:
            _canonical_to_aliases[show_name].append(name)
    print(f"[alias] build index done: alias={loaded_alias}, canonical={loaded_canonical}, total={total}, miss_name={miss_name}, miss_showName={miss_show}")
    if miss_examples:
        try:
            print(f"[alias] missing field examples (up to 3): {json.dumps(miss_examples, ensure_ascii=False)}")
        except Exception:
            print(f"[alias] missing field examples (raw): {miss_examples}")
    return loaded_alias, loaded_canonical


async def _load_items_from_local_source(file_path: str) -> List[dict]:
    try:
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            text = await f.read()
        print(f"[alias] loading local source: {file_path}")
        try:
            data = json.loads(text)
            raw_items = data if isinstance(data, list) else data.get('data') or data.get('list') or []
        except Exception:
            raw_items: List[dict] = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_items.append(json.loads(line))
                except Exception:
                    continue
        items = _flatten_alias_items(raw_items)
        return items
    except FileNotFoundError:
        print(f"[alias] local file not found: {file_path}")
        return []
    except Exception as e:
        print(f"[alias] read local source failed: {e}")
        return []


async def _load_items_from_remote(url: str, method: str = "POST") -> List[dict]:
    try:
        print(f"[alias] fetching remote source: {url} method={method}")
        async with aiohttp.ClientSession() as session:
            if method.upper() == 'GET':
                async with session.get(url) as resp:
                    status = resp.status
                    text = await resp.text()
            else:
                # 模拟 curl -X POST 行为：无请求体，不设置 Content-Type
                async with session.post(url, headers={
                    "User-Agent": "curl/8.0",
                    "Accept": "*/*",
                }) as resp:
                    status = resp.status
                    text = await resp.text()
        print(f"[alias] remote status={status}")
        try:
            data = json.loads(text)
        except Exception as e:
            print(f"[alias] remote json decode failed: {e}, body_head={text[:200]!r}")
            return []
        payload = data.get('data') or []
        if not isinstance(payload, list):
            print("[alias] remote payload is not a list")
            return []
        print(f"[alias] remote payload size={len(payload)}")
        try:
            for i, it in enumerate(payload[:3]):
                try:
                    keys = list(it.keys()) if isinstance(it, dict) else f"<non-dict {type(it)}>"
                except Exception:
                    keys = "<keys-error>"
                try:
                    sn = it.get('showName') if isinstance(it, dict) else None
                    nm = it.get('name') if isinstance(it, dict) else None
                except Exception:
                    sn, nm = None, None
                print(f"[alias] sample[{i}] keys={keys} name={nm} showName={sn} raw={str(it)[:200]}")
        except Exception:
            pass
        items = _flatten_alias_items(payload)
        return items
    except Exception as e:
        print(f"[alias] fetch remote failed: {e}")
        return []


async def _load_cache_file(cache_path: str) -> List[dict]:
    try:
        async with aiofiles.open(cache_path, 'r', encoding='utf-8') as f:
            text = await f.read()
        print(f"[alias] loading cache file: {cache_path}")
        data = json.loads(text)
        alias_map = data.get('alias_to_canonical') or {}
        items: List[dict] = []
        for alias, canonical in alias_map.items():
            items.append({"name": alias, "showName": canonical})
        return items
    except FileNotFoundError:
        print(f"[alias] cache file not found: {cache_path}")
        return []
    except Exception as e:
        print(f"[alias] read cache file failed: {e}")
        return []


async def _save_cache_file(cache_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        payload = {
            "alias_to_canonical": _alias_to_canonical,
            "canonical_to_aliases": _canonical_to_aliases,
        }
        async with aiofiles.open(cache_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(payload, ensure_ascii=False))
        print(f"[alias] cache file saved: {cache_path}")
    except Exception as e:
        print(f"[alias] write cache file failed: {e}")


async def refresh_alias_cache() -> Tuple[int, int]:
    items: List[dict] = []
    if config.alias_local_path:
        items = await _load_items_from_local_source(config.alias_local_path)
    if not items and config.alias_source_url:
        items = await _load_items_from_remote(config.alias_source_url, config.alias_request_method)
    a, c = await _build_from_items(items)
    await _save_cache_file(config.alias_cache_path)
    print(f"[alias] refreshed cache: alias={a}, canonical={c}")
    return a, c


async def rebuild_waiguan_json() -> None:
    """合并现有 waiguan.json 与 aijx3 别名，生成包含 alias/name/category 的统一数据集。"""
    # 读取现有 waiguan.json
    base_items: List[dict] = []
    try:
        async with aiofiles.open('waiguan.json', 'r', encoding='utf-8') as f:
            text = await f.read()
            data = json.loads(text)
            base_items = data.get('data', []) if isinstance(data, dict) else []
    except FileNotFoundError:
        print('[alias] waiguan.json not found, will create new one')
    except Exception as e:
        print(f"[alias] read waiguan.json failed: {e}")

    # 从远端获取别名条目（已扁平化，含 category）
    alias_items = await _load_items_from_remote(config.alias_source_url, config.alias_request_method) if config.alias_source_url else []

    # 建立原名 -> 类别集合（基于 base 数据）
    base_map: Dict[str, str] = {}
    for it in base_items:
        if isinstance(it, dict) and 'name' in it and 'category' in it:
            base_map[it['name']] = it['category']

    combined: List[dict] = []
    seen_pairs = set()

    # 先加入别名条目（使用别名的分类；若 base 有该原名的分类，优先用 base 分类）
    for it in alias_items:
        alias_name = it.get('name')
        show_name = it.get('showName')
        cate = it.get('category') or base_map.get(show_name, '')
        if not alias_name or not show_name:
            continue
        key = (alias_name, show_name, cate)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        combined.append({'name': show_name, 'category': cate, 'alias': alias_name})

    # 再补充 base 中没有别名的原始条目
    for it in base_items:
        if not isinstance(it, dict):
            continue
        show_name = it.get('name')
        cate = it.get('category')
        if not show_name:
            continue
        # 如果该原名在别名列表中没有任意别名，则补一条无 alias 的项
        has_alias = any(x['name'] == show_name for x in combined)
        if not has_alias:
            combined.append({'name': show_name, 'category': cate})

    # 写回 waiguan.json
    out = {'data': combined}
    try:
        async with aiofiles.open('waiguan.json', 'w', encoding='utf-8') as f:
            await f.write(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"[alias] waiguan.json rebuilt: total={len(combined)} (with alias and original)")
    except Exception as e:
        print(f"[alias] write waiguan.json failed: {e}")


async def initialize_aliases() -> None:
    global _initialized
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        items = await _load_cache_file(config.alias_cache_path)
        if items:
            await _build_from_items(items)
            print("[alias] initialized from cache file")
        else:
            print("[alias] cache empty, waiting for refresh job")
        _initialized = True


async def setup_alias_refresh_job(scheduler) -> None:
    await initialize_aliases()
    try:
        scheduler.add_job(
            refresh_alias_cache,
            "interval",
            minutes=config.alias_refresh_minutes,
            id="wanbaolou_alias_refresh",
            replace_existing=True,
        )
        print(f"[alias] scheduled cache refresh every {config.alias_refresh_minutes} minutes")
    except Exception as e:
        print(f"[alias] schedule refresh job failed: {e}")
    try:
        a, c = await refresh_alias_cache()
        print(f"[alias] initial refresh done: alias={a}, canonical={c}")
        # 刷新完成后，重建 waiguan.json 数据供搜索使用
        await rebuild_waiguan_json()
    except Exception as e:
        print(f"[alias] initial refresh failed: {e}")


async def get_canonical_name(keyword: str) -> str:
    if not _initialized:
        await initialize_aliases()
    key = (keyword or "").strip()
    if key in _canonical_to_aliases:
        print(f"[alias] canonical lookup hit original: '{key}'")
        return key
    result = _alias_to_canonical.get(key, key)
    print(f"[alias] canonical lookup: '{key}' -> '{result}', alias_size={len(_alias_to_canonical)}")
    return result


async def search_aliases(keyword: str) -> List[str]:
    if not _initialized:
        await initialize_aliases()
    k = (keyword or "").strip().lower()
    candidates = set()
    for alias, canonical in _alias_to_canonical.items():
        a = alias.lower()
        if a.startswith(k) or k in a:
            candidates.add(canonical)
    for canonical in _canonical_to_aliases.keys():
        c = canonical.lower()
        if c.startswith(k) or k in c:
            candidates.add(canonical)
    return list(candidates)[:20] 