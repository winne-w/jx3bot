"""Explicit, bounded role-ID maintenance; no Mongo initialization or scheduler.

Run --help before use. Operation files are private BSON-aware backups, not
runtime caches. A write requires --yes, a pinned manifest and exact DB target.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bson import json_util

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

JSON_OPTIONS = json_util.JSONOptions(tz_aware=True)
ID_FIELDS = ("game_role_id", "role_id", "global_role_id_refreshed_at",
             "global_role_id_refresh_source", "updated_at")


def _canonical(value):
    return json_util.dumps(value, sort_keys=True, json_options=JSON_OPTIONS)


def _same_snapshot(actual, expected):
    # Ordinary sync may change unrelated fields; the CAS contract owns these.
    from src.storage.mongo_repos.role_identity_repo import QUERY_ID_CAS_FIELDS
    if not isinstance(actual, dict):
        return False
    return all((key in actual) == (key in expected) and
               _canonical(actual.get(key)) == _canonical(expected.get(key))
               for key in QUERY_ID_CAS_FIELDS)


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".recovery-", dir=str(path.parent))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(tmp), str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_json(path):
    return json_util.loads(Path(path).read_text(encoding="utf-8"), json_options=JSON_OPTIONS)


@contextmanager
def operation_lock(run_dir, name="operation.lock"):
    import fcntl
    path = validate_run_directory(Path(run_dir)) / name
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def charge_calls(run_dir, *, count=1, max_calls=120, min_interval=1):
    if count < 1 or max_calls < 1 or min_interval < 0:
        raise ValueError("invalid budget")
    with operation_lock(run_dir, "budget.lock"):
        path = Path(run_dir) / "budget.json"
        state = read_json(path) if path.exists() else {"logical_calls": 0, "limit": min(100, max_calls)}
        # A conservative run == batch cap avoids resetting the batch on each
        # subcommand; public API reservations consume exactly the same ledger.
        limit = min(100, max_calls, state["limit"])
        if state["logical_calls"] + count > limit:
            raise ValueError("operation call budget exhausted")
        wait = min_interval - (time.time() - state.get("last_call_at", 0))
        if wait > 0:
            time.sleep(wait)
        state.update(logical_calls=state["logical_calls"] + count,
                     limit=limit, last_call_at=time.time())
        # Persist consumption before the network; a crash cannot reset it.
        atomic_write_json(path, state)
        return state["logical_calls"]


def load_manifest(path, expected_hash=None):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_hash is not None and digest != expected_hash:
        raise ValueError("manifest hash mismatch")
    value = read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ValueError("invalid manifest")
    return value


def validate_target(uri, confirm_target, *, write=False):
    parsed = urlsplit(uri)
    database = unquote(parsed.path.lstrip("/"))
    if parsed.scheme != "mongodb" or not parsed.hostname or not re.fullmatch(r"[A-Za-z0-9_-]+", database):
        raise ValueError("unsupported database target")
    target = "%s:%s/%s" % (parsed.hostname, parsed.port or 27017, database)
    if write and target != confirm_target:
        raise ValueError("write requires exact --confirm-target (host:port/database)")
    return target


def validate_run_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.absolute() != path.resolve() or path == Path(path.anchor):
        raise ValueError("operation directory must be absolute, non-root and without symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("operation directory must be owned by current user and private (0700)")
    return path


def expected_after_image(before, result):
    from src.services.jx3.role_identity_matching import STRICT_QUERY_ID_REFRESH_SOURCE
    after = copy.deepcopy(before)
    when = result["observed_at"]
    if not isinstance(when, datetime):
        raise ValueError("expected UTC datetime observation")
    after.update(game_role_id=result["candidate"]["role_id"],
                 role_id=result["candidate"]["role_id"],
                 global_role_id_refreshed_at=when,
                 global_role_id_refresh_source=STRICT_QUERY_ID_REFRESH_SOURCE,
                 updated_at=when)
    return after


async def process_role(repo, identity, candidates, probe, *, run_dir, apply=False,
                       backup_dir=None, cache_snapshot=None):
    key = str(identity["_id"])
    if not re.fullmatch(r"[a-fA-F0-9]{24}", key):
        raise ValueError("invalid identity ID")
    path = Path(run_dir) / (key + ".json")
    original = None
    if apply and path.exists():
        original = read_json(path)
        current = await repo.get_by_id(identity["_id"])
        if original["status"] in {"prepared", "applied_unverified", "recovered"}:
            if _same_snapshot(current, original["expected_after"]):
                original["status"] = "applied_unverified"
                atomic_write_json(path, original)
                return original
            if not _same_snapshot(current, original["before"]):
                return dict(original, status="conflict")
        if original["status"] == "rolled_back":
            return dict(original, status="rolled_back")

    result = await probe(identity, candidates)
    if result.get("status") != "ready" or not apply:
        return result
    after = expected_after_image(identity, result)
    record = {"status": "prepared", "before": copy.deepcopy(identity),
              "expected_after": after, "evidence": result,
              "caches_before": cache_snapshot or []}
    # This immutable before-image must be durable before any Mongo mutation.
    if backup_dir is not None:
        backup_path = Path(backup_dir) / (key + ".json")
        if backup_path.exists():
            previous = read_json(backup_path)
            if not _same_snapshot(previous["before"], identity):
                raise ValueError("backup belongs to another snapshot")
        else:
            atomic_write_json(backup_path, record)
    atomic_write_json(path, record)
    observed = result["observed_at"]
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if not 0 <= age < 15:
        record.update(status="unresolved", reason="evidence_expired_before_publication")
        atomic_write_json(path, record)
        return record
    matched = await repo.replace_query_ids_if_unchanged(
        identity, game_role_id=after["game_role_id"], role_id=after["role_id"],
        observed_at=result["observed_at"])
    if not matched:
        record["status"] = "conflict"
    else:
        current = await repo.get_by_id(identity["_id"])
        record["status"] = "applied_unverified" if _same_snapshot(current, after) else "conflict"
    atomic_write_json(path, record)
    return record


async def inventory(db, *, batch_size=500, replay_scan_limit=0):
    """Retained cache/history/ranking locators plus an explicitly bounded replay scan."""
    from src.services.jx3.role_identity_recovery import collect_query_id_candidates
    from src.services.jx3.role_identity_matching import extract_replay_players
    if not 0 <= replay_scan_limit <= 1000000 or not 1 <= batch_size <= 1000:
        raise ValueError("invalid inventory scan limit")
    roles, by_gid, by_sk = {}, defaultdict(list), defaultdict(list)
    fields = {key: 1 for key in ("identity_key", "global_id", "global_role_id", "server", "name",
                                "zone", "role_id", "game_role_id", "profile_history")}
    async for doc in db.role_identities.find({}, fields).batch_size(batch_size):
        key = str(doc["_id"])
        roles[key] = {"identity": doc, "candidates": collect_query_id_candidates(doc, *(doc.get("profile_history") or []))}
        if doc.get("global_id"):
            by_gid[str(doc["global_id"])].append(key)
        if doc.get("global_role_id"):
            by_sk[str(doc["global_role_id"])].append(key)
    source_counts = Counter()

    def observe(info, *, gid=None, sk=None):
        keys = by_gid.get(str(gid), []) if gid else by_sk.get(str(sk), [])
        if len(keys) != 1:
            source_counts["ambiguous_or_unlinked"] += 1
            return
        row = roles[keys[0]]
        row["candidates"] = collect_query_id_candidates(row["identity"], *row["candidates"], info)
        source_counts["linked_locators"] += 1

    async for doc in db.jjc_role_indicator.find({}, {"cache_key": 1, "global_id": 1, "raw": 1}).batch_size(batch_size):
        raw = doc.get("raw") or {}
        data = raw.get("data") or {}
        info = data.get("role_info") if isinstance(data, dict) else None
        if raw.get("code") == 0 and isinstance(info, dict):
            key = str(doc.get("cache_key") or "")
            gid = doc.get("global_id") or (key.split(":", 1)[1] if key.startswith("global_id:") else None)
            observe(info, gid=gid, sk=info.get("global_role_id"))
    for collection in ("role_jjc_cache", "role_identities_history"):
        async for doc in db[collection].find({}, fields).batch_size(batch_size):
            observe(doc, gid=doc.get("global_id"), sk=doc.get("global_role_id"))
    async for doc in db.jjc_ranking_stat_details.find({}, {"members": 1}).batch_size(100):
        for member in doc.get("members") or []:
            if isinstance(member, dict):
                observe(member, gid=member.get("global_id"), sk=member.get("global_role_id"))
    replay_scanned = 0
    if replay_scan_limit:
        cursor = db.jjc_match_detail.find({"data.replay": {"$exists": True}},
                                        {"match_id": 1, "data.replay": 1}).batch_size(100).limit(replay_scan_limit)
        async for doc in cursor:
            replay_scanned += 1
            replay = (doc.get("data") or {}).get("replay") or {}
            if replay.get("code") != 0:
                continue
            for player in extract_replay_players(replay):
                observe(dict(player, match_id=doc.get("match_id")), gid=player.get("global_id"))
    for row in roles.values():
        ident = row["identity"]
        alternatives = [c for c in row["candidates"] if str(c.get("role_id") or "") not in
                        {str(ident.get("role_id") or ""), str(ident.get("game_role_id") or "")}]
        row["classification"] = "unverified_alternatives" if alternatives else "unknown_no_alternative"
    return {"records": list(roles.values()), "input_count": len(roles),
            "source_counts": dict(source_counts), "upstream_calls": 0,
            "replay_coverage": {"requested": bool(replay_scan_limit), "scanned": replay_scanned,
                                "limit": replay_scan_limit,
                                "may_be_truncated": bool(replay_scan_limit and replay_scanned >= replay_scan_limit)},
            "snapshot_isolation": False, "health_not_verified": True}


def select_records(rows, progress, *, command, resume=False, name=None, server=None):
    seen = set()
    for row in rows:
        ident = row["identity"]
        key = str(ident["_id"])
        if key in seen or (server and server != ident.get("server")) or (name and name != ident.get("name")):
            continue
        seen.add(key)
        if resume and not name and key in progress.get(command, {}):
            continue
        yield row


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "verify", "apply", "verify-applied", "rollback"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--release-sha")
    parser.add_argument("--confirm-target")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--replay-scan-limit", type=int, default=0)
    parser.add_argument("--max-logical-calls", type=int, default=120)
    parser.add_argument("--min-interval", type=float, default=1)
    parser.add_argument("--reserve-api-calls", type=int, default=0)
    parser.add_argument("--server")
    parser.add_argument("--name")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--apply", dest="rollback_apply", action="store_true")
    return parser


async def run(args):
    import config as cfg
    from motor.motor_asyncio import AsyncIOMotorClient
    from src.services.jx3.role_identity_recovery import recover_query_ids
    from src.services.jx3.role_indicator import RoleIndicatorClient
    from src.services.jx3.match_replay import MatchReplayClient
    from src.services.jx3.match_history import MatchHistoryClient
    from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
    from src.utils.tuilan_request import tuilan_request

    writing = args.command == "apply" or (args.command == "rollback" and args.rollback_apply)
    target = validate_target(cfg.MONGO_URI, args.confirm_target, write=writing)
    if writing and not args.yes:
        raise ValueError("write requires --yes")
    run_dir = validate_run_directory(args.run_dir or args.output) if (args.run_dir or args.output) else None
    if run_dir is None:
        raise ValueError("explicit --run-dir or --output required")
    if not 1 <= args.limit <= 20 or not 1 <= args.max_logical_calls <= 120 or args.min_interval < 1:
        raise ValueError("limit <=20, calls <=120 and interval >=1 required")
    if args.resume_from and args.resume_from.resolve() != run_dir:
        raise ValueError("resume must use original run directory")
    client = AsyncIOMotorClient(cfg.MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    db = client[unquote(urlsplit(cfg.MONGO_URI).path.lstrip("/"))]
    repo = RoleIdentityRepo(db=db)
    try:
        with operation_lock(run_dir):
            if args.command == "inventory":
                result = await inventory(db, batch_size=args.batch_size, replay_scan_limit=args.replay_scan_limit)
                result["target"] = target
                atomic_write_json(run_dir / "manifest.json", result)
                return {"input_count": result["input_count"], "manifest_sha256":
                        hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest()}
            binding_path = run_dir / "run.json"
            if args.command in {"verify", "apply"}:
                if args.manifest is None or args.manifest_sha256 is None:
                    raise ValueError("pinned manifest and --manifest-sha256 required")
                manifest = load_manifest(args.manifest, args.manifest_sha256)
                if manifest.get("target") != target:
                    raise ValueError("manifest target mismatch")
                binding = {"target": target, "manifest_sha256": args.manifest_sha256,
                           "run_id": args.run_id or run_dir.name, "release_sha": args.release_sha}
                if binding_path.exists() and read_json(binding_path) != binding:
                    raise ValueError("run binding mismatch")
                if not binding_path.exists():
                    atomic_write_json(binding_path, binding)
            else:
                if not binding_path.exists() or read_json(binding_path)["target"] != target:
                    raise ValueError("missing or mismatched run target binding")

            if args.command in {"verify-applied", "rollback"}:
                if args.reserve_api_calls:
                    charge_calls(run_dir, count=args.reserve_api_calls,
                                 max_calls=args.max_logical_calls, min_interval=args.min_interval)
                results = []
                for path in sorted(run_dir.glob("[0-9a-f]" * 24 + ".json")):
                    record = read_json(path)
                    if record["status"] not in {"prepared", "applied_unverified", "recovered"}:
                        continue
                    actual = await repo.get_by_id(record["before"]["_id"])
                    matches = _same_snapshot(actual, record["expected_after"])
                    if args.command == "rollback":
                        status = "rollback_ready" if matches else "conflict"
                        if matches and args.rollback_apply:
                            ok = await repo.rollback_query_ids_if_unchanged(record["expected_after"], record["before"])
                            status = "rolled_back" if ok else "conflict"
                            record["status"] = status
                            atomic_write_json(path, record)
                    else:
                        status = "applied_unverified" if matches else "conflict"
                    results.append({"identity_id": str(record["before"]["_id"]), "status": status})
                return {"results": results, "counts": dict(Counter(r["status"] for r in results)),
                        "public_api_verified": False, "mongo_writes": writing}

            indicator = RoleIndicatorClient(cfg.API_URLS["推栏角色指标"], tuilan_request)
            replay = MatchReplayClient(cfg.API_URLS["竞技场战局回放"], tuilan_request)
            history = MatchHistoryClient(cfg.API_URLS["竞技场战局历史"], tuilan_request)
            batch_start = (read_json(run_dir / "budget.json")["logical_calls"]
                           if (run_dir / "budget.json").exists() else 0)

            def limited(function):
                def invoke(**kwargs):
                    state = read_json(run_dir / "budget.json") if (run_dir / "budget.json").exists() else {"logical_calls": 0}
                    if state["logical_calls"] - batch_start >= 100:
                        raise ValueError("batch call budget exhausted")
                    charge_calls(run_dir, max_calls=args.max_logical_calls, min_interval=args.min_interval)
                    return function(**kwargs)
                return invoke

            async def probe(identity, candidates):
                return await recover_query_ids(identity, identity_repo=repo, candidates=candidates,
                    indicator_fetcher=limited(indicator.get_role_indicator),
                    replay_fetcher=limited(replay.get_match_replay),
                    history_fetcher=limited(history.get_mine_match_history), publish=False)

            backup_dir = validate_run_directory(args.backup_dir) if args.backup_dir else None
            if writing and backup_dir is None:
                raise ValueError("apply requires private --backup-dir")
            progress_path = run_dir / "progress.json"
            progress = read_json(progress_path) if progress_path.exists() else {}
            results = []
            selected = select_records(manifest["records"], progress, command=args.command,
                                      resume=bool(args.resume_from), name=args.name, server=args.server)
            for row in selected:
                ident = row["identity"]
                key = str(ident["_id"])
                if not args.name and row.get("classification") == "unknown_no_alternative":
                    continue
                current = await repo.get_by_id(ident["_id"])
                stable = ("identity_key", "global_id", "global_role_id", "server", "name", "zone")
                if not current or any(current.get(k) != ident.get(k) for k in stable):
                    result = {"status": "conflict"}
                else:
                    caches = []
                    if writing:
                        for collection, query in (("jjc_role_indicator", {"cache_key": current["identity_key"]}),
                                                  ("role_jjc_cache", {"identity_key": current["identity_key"]})):
                            async for cache in db[collection].find(query):
                                caches.append({"collection": collection, "document": cache})
                    result = await process_role(repo, current, row["candidates"], probe,
                        run_dir=run_dir, backup_dir=backup_dir, apply=writing, cache_snapshot=caches)
                results.append({"identity_id": key, "status": result["status"]})
                progress.setdefault(args.command, {})[key] = results[-1]
                atomic_write_json(progress_path, progress)
                if result["status"] == "upstream_error" or len(results) >= args.limit:
                    break
            report = {"results": results, "input_count": len(results),
                      "counts": dict(Counter(r["status"] for r in results)),
                      "unselected_are_unknown": True}
            atomic_write_json(run_dir / (args.command + "-report.json"), report)
            return report
    finally:
        client.close()


if __name__ == "__main__":
    try:
        output = asyncio.run(run(make_parser().parse_args()))
        sys.stdout.write(json.dumps(output, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        # Do not expose connection strings or arbitrary upstream exception text.
        sys.stderr.write("operation stopped (%s); inspect protected operation records\n" % type(exc).__name__)
        sys.exit(1)
