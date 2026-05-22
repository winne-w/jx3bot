# JJC global_id 身份治理线上操作手册

适用场景：上线 JJC 角色身份主键治理后，对 `role_identities` 与 `jjc_sync_role_queue` 做备份、清理、回填、核验和必要恢复。

核心原则：

- replay 数字 ID 统一叫 `global_id`，来源为 `/3c/mine/match/replay` 的 `players[].global_role_id`。
- SK01 字段仍叫 `global_role_id`，只用于请求 `/3c/mine/match/history`。
- 线上清理默认只清 `role_identities` 与 `jjc_sync_role_queue`。
- 不清 `jjc_sync_match_seen`、`jjc_match_detail`，避免丢已同步对局和详情缓存。

## 1. 发版前检查

确认线上代码已经包含以下脚本：

```bash
python -m py_compile \
  scripts/backup_jjc_role_identity_collections.py \
  scripts/clear_jjc_role_identity_collections.py \
  scripts/restore_jjc_role_identity_collections.py \
  scripts/backfill_jjc_role_id_from_match_replay.py \
  scripts/check_role_identity_migration.py
```

先跑一次只读核验，记录当前问题基线：

```bash
python scripts/check_role_identity_migration.py
```

重点记录：

- `global_id` 重复组数
- 旧 `global:*` / `name:*` key 数量
- 同一 `zone+role_id` 多 `global_id` 样本
- 同一 SK01 `global_role_id` 多记录样本

## 2. 备份

建议手动指定 tag，后续清理和恢复都要用这个 tag。

```bash
BACKUP_TAG=before_global_id_20260521
```

先 dry-run：

```bash
python scripts/backup_jjc_role_identity_collections.py --tag "$BACKUP_TAG"
```

确认输出包含以下默认集合：

```text
role_identities
jjc_sync_role_queue
role_jjc_cache
jjc_role_indicator
jjc_match_detail
```

执行备份：

```bash
python scripts/backup_jjc_role_identity_collections.py --tag "$BACKUP_TAG" --apply --yes
```

备份后会生成集合：

```text
role_identities_backup_<BACKUP_TAG>
jjc_sync_role_queue_backup_<BACKUP_TAG>
role_jjc_cache_backup_<BACKUP_TAG>
jjc_role_indicator_backup_<BACKUP_TAG>
jjc_match_detail_backup_<BACKUP_TAG>
```

如果备份时没有传 `--tag`，脚本会生成类似 `20260521_203000` 的时间戳 tag。可从脚本输出的 `tag` 字段获取，也可从 `jjc_backup_metadata` 查询。

## 3. 清理身份表

默认只清：

```text
role_identities
jjc_sync_role_queue
```

先 dry-run：

```bash
python scripts/clear_jjc_role_identity_collections.py --backup-tag "$BACKUP_TAG"
```

确认输出中的 `before_count` 合理后执行：

```bash
python scripts/clear_jjc_role_identity_collections.py --backup-tag "$BACKUP_TAG" --apply --yes
```

不要清这些集合：

```text
jjc_sync_match_seen
jjc_match_detail
```

如必须额外清缓存集合，需要显式指定 `--collections`，例如：

```bash
python scripts/clear_jjc_role_identity_collections.py \
  --collections role_identities,jjc_sync_role_queue,role_jjc_cache \
  --backup-tag "$BACKUP_TAG" \
  --apply --yes
```

## 4. 发版后防回流验证

发版启动后观察日志，确认 Mongo 索引初始化没有严重错误。

需要特别关注：

- `role_identities.global_id` unique partial index 是否创建成功。
- 旧 `idx_global_role_id` / `idx_zone_game_role_id` 是否被重建为普通索引。
- 如果日志出现数据冲突，先停止清理/回填，回到核验脚本定位冲突。

线上入口回归：

```text
/竞技排名
/jjc同步状态
/jjc同步开始 incremental
角色近期/详情下钻接口
```

确认：

- 新写入 `identity_key` 优先为 `global_id:<数字ID>`。
- `global_role_id` 保持 `SK01-...` 格式。
- `match/history` 请求参数没有 replay 数字 `global_id`。
- 队列水位没有因为 key 迁移被重置。

## 5. 小批回填

先 dry-run 最近 20 场：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --dry-run
```

检查日志中是否出现大量冲突：

```text
CONFLICT_GLOBAL_ID
CONFLICT_GLOBAL
CONFLICT_PERSON
role_id_conflict
```

确认可控后小批 apply：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --apply --yes
```

再扩大批量：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 100 --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 100 --apply --yes
```

如要按当前排序分段处理，使用 1-based 闭区间：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --start 21 --end 40 --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --start 21 --end 40 --apply --yes
```

如要指定单场：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --match-id <对局ID> --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --match-id <对局ID> --apply --yes
```

回填脚本会：

- 从 replay `players[].role_id` 补 `role_id`。
- 从 replay `players[].global_role_id` 补 `global_id`。
- 从 indicator 补 SK01 `global_role_id` 和 `person_id`。
- 有 `global_id` 时把 `identity_key` 迁移到 `global_id:{global_id}` 并写 `aliases`。

## 6. 规范化 role_identities schema

如果线上已经存在 `sources` 包含 `indicator` 或 `match_replay_indicator_backfill` 的历史数据，回填后先 dry-run 检查时间字段类型和 `profile_history` 空字段：

```bash
python scripts/normalize_jjc_role_identity_schema.py --source all --dry-run
```

小批执行：

```bash
python scripts/normalize_jjc_role_identity_schema.py --source match_replay_indicator_backfill --limit 100 --apply --yes
```

确认输出里的 `failed` 为 0 后全量执行：

```bash
python scripts/normalize_jjc_role_identity_schema.py --source all --apply --yes
```

该脚本只规范化 schema 形态：把 `updated_at`、`first_seen_at`、`last_seen_at`、`profile_observed_at` 等历史数字时间转为 datetime，清理 `profile_history` entry 中的空字段；不修改 `identity_key`、`global_id`、`global_role_id`、`role_id`、`zone`、`server`、`name` 等身份画像值。

## 7. 回填后核验

每轮 apply 后执行：

```bash
python scripts/check_role_identity_migration.py
```

预期：

- 新增数据逐步变成 `global_id:*`。
- 旧 `global:*` / `name:*` 数量下降。
- `global_id` 重复组数不增加。
- `zone+role_id` 多 `global_id` 样本可解释，不自动合并。

## 8. 恢复

如清理或回填出现明显错误，使用备份恢复。

先 dry-run：

```bash
python scripts/restore_jjc_role_identity_collections.py --tag "$BACKUP_TAG"
```

执行恢复：

```bash
python scripts/restore_jjc_role_identity_collections.py --tag "$BACKUP_TAG" --apply --yes
```

恢复脚本会先把当前目标集合备份成：

```text
<collection>_pre_restore_backup_<timestamp>
```

然后 drop 当前目标集合，并从：

```text
<collection>_backup_<BACKUP_TAG>
```

复制回来。

恢复后再次核验：

```bash
python scripts/check_role_identity_migration.py
```

## 9. 查询备份 tag

如果忘了备份 tag，可查 `jjc_backup_metadata`：

```bash
python - <<'PY'
from pymongo import MongoClient
import json

uri = json.load(open("runtime_config.json", encoding="utf-8")).get("MONGO_URI")
db = MongoClient(uri)[uri.rsplit("/", 1)[-1].split("?", 1)[0]]
for item in db.jjc_backup_metadata.find({"type": "jjc_role_identity_backup"}).sort("_id", -1).limit(10):
    print(item.get("tag"), item.get("created_at"))
PY
```

## 10. 推荐完整命令顺序

```bash
BACKUP_TAG=before_global_id_20260521

python scripts/check_role_identity_migration.py

python scripts/backup_jjc_role_identity_collections.py --tag "$BACKUP_TAG"
python scripts/backup_jjc_role_identity_collections.py --tag "$BACKUP_TAG" --apply --yes

python scripts/clear_jjc_role_identity_collections.py --backup-tag "$BACKUP_TAG"
python scripts/clear_jjc_role_identity_collections.py --backup-tag "$BACKUP_TAG" --apply --yes

python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --apply --yes

python scripts/normalize_jjc_role_identity_schema.py --source all --dry-run
python scripts/normalize_jjc_role_identity_schema.py --source all --apply --yes

python scripts/check_role_identity_migration.py
```

恢复命令：

```bash
python scripts/restore_jjc_role_identity_collections.py --tag "$BACKUP_TAG"
python scripts/restore_jjc_role_identity_collections.py --tag "$BACKUP_TAG" --apply --yes
python scripts/check_role_identity_migration.py
```
