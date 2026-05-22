#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set
from urllib.parse import unquote

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import MONGO_URI  # noqa: E402
from src.infra.mongo import close_mongo, init_mongo  # noqa: E402
from src.services.jx3.weapon_quality import extract_member_weapon_name, is_jjc_legendary_weapon  # noqa: E402
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo  # noqa: E402


class RankingStatsRepoProtocol(Protocol):
    async def load_summary(self, timestamp: int) -> Optional[Dict[str, Any]]:
        ...

    async def upsert_summary(
        self,
        timestamp: int,
        payload: Dict[str, Any],
        source: str = "migration",
    ) -> None:
        ...

    async def upsert_detail(
        self,
        timestamp: int,
        range_key: str,
        lane: str,
        kungfu: str,
        members: List[Dict[str, Any]],
        source: str = "migration",
    ) -> None:
        ...

    async def save_snapshot(
        self,
        timestamp: int,
        summary_payload: Dict[str, Any],
        detail_payloads: List[Dict[str, Any]],
        source: str = "migration",
    ) -> None:
        ...


class DryRunRankingStatsRepo:
    async def load_summary(self, timestamp: int) -> Optional[Dict[str, Any]]:
        return None

    async def upsert_summary(
        self,
        timestamp: int,
        payload: Dict[str, Any],
        source: str = "migration",
    ) -> None:
        return None

    async def upsert_detail(
        self,
        timestamp: int,
        range_key: str,
        lane: str,
        kungfu: str,
        members: List[Dict[str, Any]],
        source: str = "migration",
    ) -> None:
        return None

    async def save_snapshot(
        self,
        timestamp: int,
        summary_payload: Dict[str, Any],
        detail_payloads: List[Dict[str, Any]],
        source: str = "migration",
    ) -> None:
        return None


@dataclass
class SnapshotPayload:
    timestamp: int
    summary: Dict[str, Any]
    details: List[Dict[str, Any]]
    source_path: Path


@dataclass
class MigrationStats:
    snapshots: int = 0
    summary_writes: int = 0
    summary_skips: int = 0
    detail_writes: int = 0
    detail_skips: int = 0
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshots": self.snapshots,
            "summary_writes": self.summary_writes,
            "summary_skips": self.summary_skips,
            "detail_writes": self.detail_writes,
            "detail_skips": self.detail_skips,
            "failures": self.failures,
        }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary_from_legacy(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary_payload = {
        key: value
        for key, value in payload.items()
        if key != "kungfu_statistics"
    }
    summary_payload["kungfu_statistics"] = {}

    kungfu_statistics = payload.get("kungfu_statistics") or {}
    for range_key, range_stats in kungfu_statistics.items():
        if not isinstance(range_stats, dict):
            summary_payload["kungfu_statistics"][range_key] = range_stats
            continue

        summary_range: Dict[str, Any] = {
            key: value
            for key, value in range_stats.items()
            if key not in {"healer", "dps"}
        }
        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name) or {}
            if not isinstance(lane, dict):
                summary_range[lane_name] = lane
                continue

            members_map = lane.get("members") or {}
            legendary_count_map: Dict[str, int] = {}
            for kungfu, members in members_map.items():
                legendary_count_map[str(kungfu)] = sum(
                    1
                    for member in (members or [])
                    if is_jjc_legendary_weapon(
                        (member or {}).get("weapon_quality"),
                        extract_member_weapon_name(member),
                    )
                )

            summary_lane = {
                key: value
                for key, value in lane.items()
                if key != "members"
            }
            summary_lane["legendary_count_map"] = legendary_count_map
            summary_range[lane_name] = summary_lane

        summary_payload["kungfu_statistics"][range_key] = summary_range

    return summary_payload


def build_details_from_legacy(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    for range_key, range_stats in (payload.get("kungfu_statistics") or {}).items():
        if not isinstance(range_stats, dict):
            continue
        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name) or {}
            members_map = lane.get("members") or {}
            if not isinstance(members_map, dict):
                continue
            for kungfu, members in members_map.items():
                details.append({
                    "range": range_key,
                    "lane": lane_name,
                    "kungfu": str(kungfu),
                    "members": members or [],
                })
    return details


def load_new_snapshot(timestamp_dir: Path) -> SnapshotPayload:
    timestamp = int(timestamp_dir.name)
    summary = _load_json(timestamp_dir / "summary.json")
    if not isinstance(summary, dict):
        raise ValueError("summary.json is not an object")

    details: List[Dict[str, Any]] = []
    details_root = timestamp_dir / "details"
    if details_root.is_dir():
        for detail_file in sorted(details_root.glob("*/*/*.json")):
            range_key = detail_file.parent.parent.name
            lane = detail_file.parent.name
            payload = _load_json(detail_file)
            if isinstance(payload, dict):
                detail = dict(payload)
                detail.setdefault("range", range_key)
                detail.setdefault("lane", lane)
                detail.setdefault("kungfu", unquote(detail_file.stem))
                detail.setdefault("members", [])
                details.append(detail)
    return SnapshotPayload(timestamp=timestamp, summary=summary, details=details, source_path=timestamp_dir)


def load_legacy_snapshot(path: Path) -> SnapshotPayload:
    timestamp = int(path.stem)
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("legacy json is not an object")
    return SnapshotPayload(
        timestamp=timestamp,
        summary=build_summary_from_legacy(payload),
        details=build_details_from_legacy(payload),
        source_path=path,
    )


def discover_snapshots(root: Path, timestamp: Optional[int] = None) -> List[SnapshotPayload]:
    snapshots: List[SnapshotPayload] = []
    if not root.exists():
        return snapshots

    if timestamp is not None:
        ts_name = str(timestamp)
        timestamp_dir = root / ts_name
        legacy_file = root / "{}.json".format(ts_name)
        if timestamp_dir.is_dir() and (timestamp_dir / "summary.json").is_file():
            snapshots.append(load_new_snapshot(timestamp_dir))
        elif legacy_file.is_file():
            snapshots.append(load_legacy_snapshot(legacy_file))
        return snapshots

    seen: Set[int] = set()
    for timestamp_dir in sorted(root.iterdir()):
        if not timestamp_dir.is_dir() or not timestamp_dir.name.isdigit():
            continue
        if not (timestamp_dir / "summary.json").is_file():
            continue
        snapshot = load_new_snapshot(timestamp_dir)
        snapshots.append(snapshot)
        seen.add(snapshot.timestamp)

    for legacy_file in sorted(root.glob("*.json")):
        if not legacy_file.stem.isdigit():
            continue
        ts = int(legacy_file.stem)
        if ts in seen:
            continue
        snapshots.append(load_legacy_snapshot(legacy_file))

    return sorted(snapshots, key=lambda item: item.timestamp)


async def migrate_snapshots(
    snapshots: List[SnapshotPayload],
    repo: RankingStatsRepoProtocol,
    *,
    dry_run: bool,
    overwrite: bool,
    progress: bool = False,
) -> MigrationStats:
    stats = MigrationStats(snapshots=len(snapshots))
    for index, snapshot in enumerate(snapshots, start=1):
        try:
            if progress:
                print(
                    "[{}/{}] timestamp={} details={} source={}".format(
                        index,
                        len(snapshots),
                        snapshot.timestamp,
                        len(snapshot.details),
                        snapshot.source_path,
                    ),
                    flush=True,
                )
            exists = await repo.load_summary(snapshot.timestamp)
            if exists is not None and not overwrite:
                stats.summary_skips += 1
                stats.detail_skips += len(snapshot.details)
                if progress:
                    print(
                        "[{}/{}] skipped existing timestamp={}".format(
                            index,
                            len(snapshots),
                            snapshot.timestamp,
                        ),
                        flush=True,
                    )
                continue

            if dry_run:
                stats.summary_writes += 1
                stats.detail_writes += len(snapshot.details)
                if progress:
                    print(
                        "[{}/{}] dry-run would write timestamp={} details={}".format(
                            index,
                            len(snapshots),
                            snapshot.timestamp,
                            len(snapshot.details),
                        ),
                        flush=True,
                    )
                continue

            await repo.upsert_summary(snapshot.timestamp, snapshot.summary, source="migration")
            stats.summary_writes += 1
            for detail_index, detail in enumerate(snapshot.details, start=1):
                await repo.upsert_detail(
                    snapshot.timestamp,
                    detail["range"],
                    detail["lane"],
                    detail["kungfu"],
                    detail.get("members", []),
                    source="migration",
                )
                stats.detail_writes += 1
                if progress and (detail_index == len(snapshot.details) or detail_index % 20 == 0):
                    print(
                        "[{}/{}] timestamp={} detail progress {}/{}".format(
                            index,
                            len(snapshots),
                            snapshot.timestamp,
                            detail_index,
                            len(snapshot.details),
                        ),
                        flush=True,
                    )
            if progress:
                print(
                    "[{}/{}] wrote timestamp={} details={}".format(
                        index,
                        len(snapshots),
                        snapshot.timestamp,
                        len(snapshot.details),
                    ),
                    flush=True,
                )
        except Exception as exc:
            stats.failures.append("{}: {}".format(snapshot.source_path, exc))
            if progress:
                print(
                    "[{}/{}] failed timestamp={}: {}".format(
                        index,
                        len(snapshots),
                        snapshot.timestamp,
                        exc,
                    ),
                    flush=True,
                )
    return stats


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="迁移 JJC 排名统计快照到 MongoDB")
    parser.add_argument("--root", default="data/jjc_ranking_stats", help="统计快照根目录")
    parser.add_argument("--timestamp", type=int, help="只迁移指定 timestamp")
    parser.add_argument("--dry-run", action="store_true", help="只扫描和统计，不写 Mongo")
    parser.add_argument("--overwrite", action="store_true", help="覆盖 Mongo 中已存在的 timestamp")
    parser.add_argument("--quiet", action="store_true", help="不输出逐快照迁移进度")
    return parser.parse_args(argv)


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    snapshots = discover_snapshots(root, timestamp=args.timestamp)
    if not args.quiet:
        print(
            "发现 {} 个 JJC ranking stats 快照，root={}".format(len(snapshots), root),
            flush=True,
        )
    if args.dry_run:
        stats = await migrate_snapshots(
            snapshots,
            DryRunRankingStatsRepo(),
            dry_run=True,
            overwrite=bool(args.overwrite),
            progress=not args.quiet,
        )
        print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
        return 0 if not stats.failures else 1

    await init_mongo(MONGO_URI)
    try:
        stats = await migrate_snapshots(
            snapshots,
            JjcRankingStatsRepo(suppress_errors=False),
            dry_run=False,
            overwrite=bool(args.overwrite),
            progress=not args.quiet,
        )
        print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
        return 0 if not stats.failures else 1
    finally:
        await close_mongo()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
