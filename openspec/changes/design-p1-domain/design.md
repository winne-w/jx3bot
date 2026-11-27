# P1 统一领域规则层技术方案（design.md）

## 1. `src/domain/` 依赖约束

`src/domain/` 为最底层纯领域包，仅依赖 Python 标准库，禁止导入 `plugins`、`api`、`services`、`storage`、`infra`、`nonebot`、`motor`、`pymongo`。

## 2. 模块设计

- `src/domain/kungfu_catalog.py`：
  - 定义 `KungfuSpec(id, pinyin, name, category, school, aliases, display_order, in_jjc_catalog=True)`，覆盖全部 33 个心法（含 4 个坦克心法：铁牢律 10062、洗髓经 10002、铁骨衣 10389、明尊琉璃体 10243，以及问水诀 10144；其中洗髓经 `in_jjc_catalog=False` 保持 32 心法 JJC 对阵目录兼容）。
  - 导入时校验 ID、拼音、标准名、别名与歧义别名无冲突。
  - 提供：`build_kungfu_meta()`、`get_jjc_catalog_specs()`、`healer_names()`、`dps_names()`、`tank_names()`、`category_for_name(name)`、`name_by_id(kungfu_id)`、`resolve_kungfu_alias(value)`。
  - `config.KUNGFU_META` 由 `build_kungfu_meta()` 生成；`jjc_kungfu_meta.py`、`kungfu_aliases.py`、`singletons.py`、`jjc_ranking_display.py`、`jjc_ranking_equipment.py` 全部从此派生。
  - `jjc_ranking.py:count_kungfu_by_rank` 与 `jjc_ranking_stats.py:_build_peak_kungfu_statistics` 将坦克归入独立 `tank` 赛道（保留 `healer` / `dps` 既有字段结构兼容）。
- `src/domain/role_name.py`：
  - 提供 `strip_server_suffix(name, server)` 与 `split_display_name(raw, server="", known_servers=None)`：仅当后缀等于显式 `server` 或属于 `known_servers`（未传 `known_servers` 且无显式 `server` 时按最后一个 `·` 拆，避免破坏旧 replay 格式）时剥离服务器后缀，保证角色名自带 `·` 且给定服务器时不被误截断。
- `src/domain/role_identity.py`：
  - 承接 `role_identity_matching.py` 全部纯函数（`build_identity_key`、`legacy_identity_keys`、`should_overwrite_profile_fields`、`build_guarded_profile_set_fields` 等）与 `classify_replay_player_match(player, role_id=..., role_name=..., server=...) -> Optional[str]`（返回 `"strong"` / `"weak_name_only"` / `None`，当 `role_id` 与 `replay_role_id` 同时存在但不相等时严格返回 `None`）。
  - `src/services/jx3/role_identity_matching.py` 改为薄重导出。
- `src/domain/snapshots.py`：
  - 承接 `TALENT_SNAPSHOT_SCHEMA_VERSION` 与装备/奇穴归一化及 SHA-256 哈希纯函数；`src/services/jx3/match_detail_snapshots.py` 改为薄重导出。
- `src/domain/season.py`：
  - 承接 `parse_season_start_timestamp(season_start_str: str) -> int`；`jjc_kungfu_policy.py`、`jjc_match_data_sync.py`、`singletons.py`、`scripts/backfill_jjc_match_participant_season.py` 统一复用。
- `src/utils/coerce.py`：
  - 提供 `coerce_int`、`coerce_float`、`normalize_text`、`pick_text`、`strip_mongo_id`。
- `scripts/_common/mongo.py`：
  - 提供 `resolve_mongo_uri(explicit_uri=None)`、`resolve_db_name(uri, default="jx3bot")`、`open_sync_client(...)`、`open_async_client(...)`，统一各维护脚本连接解析逻辑。
