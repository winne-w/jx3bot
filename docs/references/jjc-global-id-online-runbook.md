# JJC global_id 身份补充操作手册

适用场景：线上需要从已同步 JJC 对局的 match/replay 数据补充 `role_identities` 与 `jjc_sync_role_queue` 的身份字段。

当前只保留一个可执行辅助脚本：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --dry-run
```

## 核心原则

- replay 数字 ID 统一叫 `global_id`，来源为 `/3c/mine/match/replay` 的 `players[].global_role_id`。
- SK01 字段仍叫 `global_role_id`，只用于请求 `/3c/mine/match/history`。
- 脚本只用于从 match/replay 补充身份信息，不再承担备份、清表、恢复、审计、schema 规范化或批量修复职责。
- 执行 `--apply --yes` 前必须先 dry-run，确认冲突数量可控。

## 小批回填

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

再按需扩大批量：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 100 --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 100 --apply --yes
```

## 分段或单场

按当前排序分段处理，使用 1-based 闭区间：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --start 21 --end 40 --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --start 21 --end 40 --apply --yes
```

指定单场：

```bash
python scripts/backfill_jjc_role_id_from_match_replay.py --match-id <对局ID> --dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --match-id <对局ID> --apply --yes
```

## 脚本行为

- 从 replay `players[].role_id` 补 `role_id`。
- 从 replay `players[].global_role_id` 补 `global_id`。
- 从 indicator 补 SK01 `global_role_id` 和 `person_id`。
- 有 `global_id` 时把 `identity_key` 迁移到 `global_id:{global_id}` 并写 `aliases`。
- 按 `role_info_observed_match_time` 保护当前画像，旧对局只补缺失字段，不覆盖已有完整字段。

## 验证

离线验证脚本本身：

```bash
python -m unittest tests.test_backfill_jjc_role_id_from_match_replay
python -m py_compile scripts/backfill_jjc_role_id_from_match_replay.py
```

线上执行后通过 `/jjc同步状态`、角色近期和对局详情下钻确认身份命中与同步队列状态。需要数据级抽样时直接查 Mongo 集合，不再依赖已删除的一次性检查脚本。
