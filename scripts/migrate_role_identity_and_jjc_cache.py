"""
迁移 kungfu_cache 到 role_identities 和 role_jjc_cache。

用法:
  python scripts/migrate_role_identity_and_jjc_cache.py --limit 20          # dry-run
  python scripts/migrate_role_identity_and_jjc_cache.py --limit 20 --apply  # 实际写入
  python scripts/migrate_role_identity_and_jjc_cache.py --apply             # 全量迁移
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

SCHEMA_VERSION = 1


def _normalize(value: str) -> str:
    return (value or "").strip().lower()


def build_identity_key(
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    game_role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[str, str]:
    """按优先级生成 (identity_key, identity_level)。"""
    gid = (global_role_id or "").strip()
    if gid:
        return "global:{}".format(gid), "global"

    z = (zone or "").strip()
    grid = (game_role_id or "").strip()
    if z and grid:
        return "game:{}:{}".format(z, grid), "game_role"

    ns = _normalize(server or "")
    nn = _normalize(name or "")
    return "name:{}:{}".format(ns, nn), "name"


def extract_ids(doc: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """从 kungfu_cache 文档顶层字段提取外部 ID，不使用 teammates 避免误关联。"""
    ids: Dict[str, Optional[str]] = {
        "global_role_id": None,
        "zone": None,
        "game_role_id": None,
        "role_id": None,
        "person_id": None,
    }
    for field in ids:
        val = doc.get(field)
        if val is not None and val != "":
            ids[field] = str(val)
    return ids


def get_mongo_uri() -> str:
    """读取 MONGO_URI：优先 runtime_config.json（基于脚本所在仓库根目录解析），再 config.MONGO_URI/环境变量。"""
    _script_dir = Path(__file__).resolve().parent
    _runtime_cfg_path = _script_dir.parent / "runtime_config.json"
    if _runtime_cfg_path.is_file():
        try:
            with open(str(_runtime_cfg_path), "r", encoding="utf-8") as fh:
                runtime_cfg = json.load(fh)
            uri = runtime_cfg.get("MONGO_URI")
            if uri:
                return str(uri)
        except Exception:
            pass

    try:
        from config import MONGO_URI  # type: ignore
        if MONGO_URI:
            return str(MONGO_URI)
    except Exception:
        pass

    uri = os.getenv("MONGO_URI")
    if uri:
        return uri

    raise RuntimeError(
        "无法获取 MONGO_URI：runtime_config.json、config.MONGO_URI、环境变量均未配置"
    )


def _make_identity_doc(
    identity_key: str,
    identity_level: str,
    server: str,
    name: str,
    ids: Dict[str, Optional[str]],
    now: datetime,
) -> Dict[str, Any]:
    ns = _normalize(server)
    nn = _normalize(name)
    doc: Dict[str, Any] = {
        "identity_key": identity_key,
        "identity_level": identity_level,
        "server": server,
        "normalized_server": ns,
        "name": name,
        "normalized_name": nn,
        "aliases": [],
        "sources": ["migrated_kungfu_cache"],
        "first_seen_at": now,
        "last_seen_at": now,
        "updated_at": now,
        "schema_version": SCHEMA_VERSION,
    }
    for field in ("zone", "game_role_id", "global_role_id", "role_id", "person_id"):
        val = ids.get(field)
        if val:
            doc[field] = val
    return doc


def _make_jjc_cache_doc(
    identity_key: str,
    server: str,
    name: str,
    ids: Dict[str, Optional[str]],
    kf_doc: Dict[str, Any],
    now: datetime,
) -> Dict[str, Any]:
    ns = _normalize(server)
    nn = _normalize(name)
    jjc: Dict[str, Any] = {
        "identity_key": identity_key,
        "server": server,
        "name": name,
        "normalized_server": ns,
        "normalized_name": nn,
        "source": "migrated",
        "checked_at": now,
        "schema_version": SCHEMA_VERSION,
    }
    for field in ("zone", "game_role_id", "global_role_id", "role_id"):
        val = ids.get(field)
        if val:
            jjc[field] = val
    for field in (
        "kungfu", "kungfu_id", "kungfu_pinyin", "kungfu_indicator",
        "kungfu_match_history", "kungfu_selected_source",
        "weapon", "weapon_icon", "weapon_quality", "weapon_checked",
        "teammates", "teammates_checked",
        "match_history_checked", "match_history_win_samples",
    ):
        if field in kf_doc and kf_doc[field] is not None:
            jjc[field] = kf_doc[field]
    return jjc


async def _check_conflicts(
    db: AsyncIOMotorDatabase,
    identity_key: str,
    ids: Dict[str, Optional[str]],
) -> Optional[Dict[str, Any]]:
    """检查新身份是否与已有 role_identities 记录冲突。"""
    global_role_id = ids.get("global_role_id")
    if global_role_id:
        conflict = await db.role_identities.find_one({
            "global_role_id": global_role_id,
            "identity_key": {"$ne": identity_key},
        })
        if conflict:
            return {
                "reason": "global_role_id 已被占用",
                "identity_key": identity_key,
                "global_role_id": global_role_id,
                "conflict_identity_key": conflict["identity_key"],
                "conflict_identity_level": conflict.get("identity_level"),
            }

    zone = ids.get("zone")
    game_role_id = ids.get("game_role_id")
    if zone and game_role_id:
        conflict = await db.role_identities.find_one({
            "zone": zone,
            "game_role_id": game_role_id,
            "identity_key": {"$ne": identity_key},
        })
        if conflict:
            return {
                "reason": "zone+game_role_id 已被占用",
                "identity_key": identity_key,
                "zone": zone,
                "game_role_id": game_role_id,
                "conflict_identity_key": conflict["identity_key"],
                "conflict_identity_level": conflict.get("identity_level"),
            }

    return None


async def migrate(
    db: AsyncIOMotorDatabase,
    apply: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """执行迁移，返回统计字典。"""
    stats: Dict[str, int] = {
        "total": 0,
        "global": 0,
        "game_role": 0,
        "name": 0,
        "skipped": 0,
        "conflicts": 0,
        "inserted": 0,
        "updated": 0,
    }
    conflicts: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    start_time = time.time()

    cursor = db.kungfu_cache.find()
    if limit is not None:
        cursor = cursor.limit(limit)

    docs = await cursor.to_list(None)
    stats["total"] = len(docs)
    if stats["total"] == 0:
        return stats

    for idx, kf_doc in enumerate(docs):
        server = kf_doc.get("server") or ""
        name = kf_doc.get("name") or ""

        if not server or not name:
            stats["skipped"] += 1
            print("[{}/{}] 跳过(缺少 server/name): _id={}".format(
                idx + 1, stats["total"], kf_doc.get("_id"),
            ))
            continue

        ids = extract_ids(kf_doc)
        identity_key, identity_level = build_identity_key(
            global_role_id=ids["global_role_id"],
            zone=ids["zone"],
            game_role_id=ids["game_role_id"],
            server=server,
            name=name,
        )
        stats[identity_level] += 1

        # 查询是否已有同 identity_key 的记录（apply 和 dry-run 都需要）
        existing = await db.role_identities.find_one(
            {"identity_key": identity_key}
        )

        if apply:
            if existing:
                # 更新前检查写入的 global_role_id / zone+game_role_id 是否冲突
                conflict_info = await _check_conflicts(db, identity_key, ids)
                if conflict_info:
                    stats["conflicts"] += 1
                    conflicts.append(conflict_info)
                    print(
                        "[{}/{}] 冲突(update): {} server={} name={} reason={} conflict_with={}".format(
                            idx + 1, stats["total"],
                            identity_key, server, name,
                            conflict_info["reason"],
                            conflict_info["conflict_identity_key"],
                        )
                    )
                    continue

                stats["updated"] += 1
                ns = _normalize(server)
                nn = _normalize(name)
                set_fields: Dict[str, Any] = {
                    "server": server,
                    "normalized_server": ns,
                    "name": name,
                    "normalized_name": nn,
                    "last_seen_at": now,
                    "updated_at": now,
                }
                for field in (
                    "zone", "game_role_id", "global_role_id",
                    "role_id", "person_id",
                ):
                    val = ids.get(field)
                    if val:
                        set_fields[field] = val
                try:
                    await db.role_identities.update_one(
                        {"identity_key": identity_key},
                        {
                            "$set": set_fields,
                            "$addToSet": {"sources": "migrated_kungfu_cache"},
                        },
                    )
                except DuplicateKeyError:
                    stats["conflicts"] += 1
                    conflicts.append({
                        "reason": "update_one 触发 DuplicateKeyError",
                        "identity_key": identity_key,
                        "server": server,
                        "name": name,
                    })
                    print(
                        "[{}/{}] 冲突(DuplicateKeyError on update): identity_key={} server={} name={}".format(
                            idx + 1, stats["total"], identity_key, server, name,
                        )
                    )
                    continue
            else:
                conflict_info = await _check_conflicts(
                    db, identity_key, ids,
                )
                if conflict_info:
                    stats["conflicts"] += 1
                    conflicts.append(conflict_info)
                    print(
                        "[{}/{}] 冲突: {} server={} name={} reason={} conflict_with={}".format(
                            idx + 1, stats["total"],
                            identity_key, server, name,
                            conflict_info["reason"],
                            conflict_info["conflict_identity_key"],
                        )
                    )
                    continue

                identity_doc = _make_identity_doc(
                    identity_key, identity_level, server, name, ids, now,
                )
                try:
                    await db.role_identities.insert_one(identity_doc)
                except DuplicateKeyError:
                    stats["conflicts"] += 1
                    conflicts.append({
                        "reason": "identity_key 重复 (DuplicateKeyError)",
                        "identity_key": identity_key,
                        "server": server,
                        "name": name,
                    })
                    print(
                        "[{}/{}] 冲突(DuplicateKeyError): identity_key={} server={} name={}".format(
                            idx + 1, stats["total"], identity_key, server, name,
                        )
                    )
                    continue
                stats["inserted"] += 1

            # --- 写入 role_jjc_cache ---
            jjc_doc = _make_jjc_cache_doc(
                identity_key, server, name, ids, kf_doc, now,
            )
            await db.role_jjc_cache.update_one(
                {"identity_key": identity_key},
                {"$set": jjc_doc},
                upsert=True,
            )

            if (idx + 1) % 500 == 0:
                elapsed = time.time() - start_time
                print(
                    "进度: {}/{} inserted={} updated={} conflicts={} elapsed={:.1f}s".format(
                        idx + 1, stats["total"],
                        stats["inserted"], stats["updated"],
                        stats["conflicts"], elapsed,
                    )
                )
        else:
            # dry-run: 区分将新增 / 将更新 / 冲突
            if existing:
                conflict_info = await _check_conflicts(db, identity_key, ids)
                if conflict_info:
                    stats["conflicts"] += 1
                    conflicts.append(conflict_info)
                    print(
                        "[{}/{}] [DRY-RUN] 冲突(update): {} server={} name={} reason={} conflict_with={}".format(
                            idx + 1, stats["total"],
                            identity_key, server, name,
                            conflict_info["reason"],
                            conflict_info["conflict_identity_key"],
                        )
                    )
                else:
                    stats["updated"] += 1
            else:
                conflict_info = await _check_conflicts(db, identity_key, ids)
                if conflict_info:
                    stats["conflicts"] += 1
                    conflicts.append(conflict_info)
                    print(
                        "[{}/{}] [DRY-RUN] 冲突: {} server={} name={} reason={} conflict_with={}".format(
                            idx + 1, stats["total"],
                            identity_key, server, name,
                            conflict_info["reason"],
                            conflict_info["conflict_identity_key"],
                        )
                    )
                else:
                    stats["inserted"] += 1

            if (idx + 1) % 500 == 0:
                elapsed = time.time() - start_time
                print(
                    "进度: {}/{} would_insert={} would_update={} conflicts={} elapsed={:.1f}s".format(
                        idx + 1, stats["total"],
                        stats["inserted"], stats["updated"],
                        stats["conflicts"], elapsed,
                    )
                )

    elapsed = time.time() - start_time
    print("\n耗时: {:.1f}s".format(elapsed))

    if conflicts:
        print("\n" + "=" * 60)
        print("冲突摘要 ({} 条)".format(len(conflicts)))
        print("=" * 60)
        for c in conflicts:
            reason = c.get("reason", "unknown")
            ik = c.get("identity_key", "?")
            srv = c.get("server", "")
            nm = c.get("name", "")
            cik = c.get("conflict_identity_key", "")
            print("  reason={} new_key={} server={} name={} conflict_key={}".format(
                reason, ik, srv, nm, cik,
            ))

    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="迁移 kungfu_cache 到 role_identities 和 role_jjc_cache"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="实际写入数据库（默认 dry-run，不写入）",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="限制处理条数（用于小批量验证）",
    )
    args = parser.parse_args()

    try:
        uri = get_mongo_uri()
    except RuntimeError as exc:
        print("错误: {}".format(exc))
        sys.exit(1)

    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        uri, maxPoolSize=10, serverSelectionTimeoutMS=5000,
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:
        print("MongoDB 连接失败: {}".format(exc))
        sys.exit(1)

    db = client[db_name]
    print("MongoDB 连接成功: {}".format(db_name))
    print("模式: {}".format("APPLY (实际写入)" if args.apply else "DRY-RUN (不写入)"))
    if args.limit:
        print("限制: {} 条".format(args.limit))

    old_count = await db.kungfu_cache.estimated_document_count()
    print("kungfu_cache 现有文档数: {}".format(old_count))

    before_identity = await db.role_identities.estimated_document_count()
    before_jjc = await db.role_jjc_cache.estimated_document_count()
    print("role_identities 现有文档数: {}".format(before_identity))
    print("role_jjc_cache 现有文档数: {}".format(before_jjc))
    print()

    stats = await migrate(db, apply=args.apply, limit=args.limit)

    print()
    print("=" * 60)
    print("迁移统计")
    print("=" * 60)
    print("  处理总数:          {}".format(stats["total"]))
    print("  global 级身份:     {}".format(stats["global"]))
    print("  game_role 级身份:  {}".format(stats["game_role"]))
    print("  name 级身份:       {}".format(stats["name"]))
    print("  跳过(缺server/name): {}".format(stats["skipped"]))
    print("  冲突:              {}".format(stats["conflicts"]))
    if args.apply:
        print("  新增 (inserted):   {}".format(stats["inserted"]))
        print("  更新 (updated):    {}".format(stats["updated"]))
    else:
        print("  将新增 (would insert): {}".format(stats["inserted"]))
        print("  将更新 (would update): {}".format(stats["updated"]))

    if not args.apply:
        print()
        print(">>> DRY-RUN 模式，未实际写入。使用 --apply 参数执行实际写入 <<<")
    else:
        after_identity = await db.role_identities.estimated_document_count()
        after_jjc = await db.role_jjc_cache.estimated_document_count()
        delta_id = after_identity - before_identity
        delta_jjc = after_jjc - before_jjc
        print()
        print("迁移后 role_identities 文档数: {} (变化 {:+d})".format(
            after_identity, delta_id,
        ))
        print("迁移后 role_jjc_cache 文档数: {} (变化 {:+d})".format(
            after_jjc, delta_jjc,
        ))

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
