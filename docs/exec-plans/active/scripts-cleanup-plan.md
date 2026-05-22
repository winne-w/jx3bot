# scripts 目录清理计划

## 背景

JJC 相关文件迁移、数据检查、临时修复、审计和备份恢复脚本已完成阶段性用途。当前运行态已切换到 MongoDB 正常读写，继续保留这些脚本会增加误操作风险和维护噪声。

## 目标

- 清理 `scripts/` 下临时清理、数据检查、数据修复、审计、旧迁移和备份恢复脚本。
- 保留从已同步 match/replay 补充身份信息的脚本：`scripts/backfill_jjc_role_id_from_match_replay.py`。
- 保留日常同步入口：`scripts/jjc_sync.py`。
- 删除仅覆盖被清理脚本的测试文件。
- 同步活跃计划、运行手册、数据库设计与项目上下文中的脚本引用，避免文档继续引导执行已删除脚本。

## 变更范围

- 删除脚本：
  - `scripts/audit_jjc_person_history_identity.py`
  - `scripts/backup_jjc_role_identity_collections.py`
  - `scripts/check_role_identity_migration.py`
  - `scripts/clear_jjc_match_detail_snapshot_cache.py`
  - `scripts/clear_jjc_role_identity_collections.py`
  - `scripts/fix_jjc_ranking_weapon_names.py`
  - `scripts/migrate_role_identity_and_jjc_cache.py`
  - `scripts/normalize_jjc_role_identity_schema.py`
  - `scripts/restore_jjc_role_identity_collections.py`
  - `scripts/verify_jjc_match_detail_snapshot_storage.py`
- 删除对应测试：
  - `tests/test_audit_jjc_person_history_identity.py`
  - `tests/test_normalize_jjc_role_identity_schema.py`
  - `tests/test_scripts_jjc_snapshot.py`
- 更新文档：
  - `PROJECT_CONTEXT.md`
  - `docs/design-docs/database-design.md`
  - `docs/references/runbook.md`
  - `docs/references/jjc-global-id-online-runbook.md`
  - `docs/exec-plans/active/*.md`
  - `docs/exec-plans/index.md`

## 验证

```bash
python -m unittest tests.test_backfill_jjc_role_id_from_match_replay
python -m py_compile scripts/backfill_jjc_role_id_from_match_replay.py scripts/jjc_sync.py
rg -n "audit_jjc_person_history_identity|check_role_identity_migration|clear_jjc_match_detail_snapshot_cache|clear_jjc_role_identity_collections|fix_jjc_ranking_weapon_names|backup_jjc_role_identity_collections|restore_jjc_role_identity_collections|verify_jjc_match_detail_snapshot_storage|normalize_jjc_role_identity_schema|migrate_role_identity_and_jjc_cache" PROJECT_CONTEXT.md docs/references docs/design-docs scripts tests
```

## 执行记录

- 2026-05-22：已删除目标脚本和对应测试；`scripts/` 仅保留 `backfill_jjc_role_id_from_match_replay.py` 与 `jjc_sync.py`。
- 2026-05-22：已更新项目上下文、数据库设计、运行手册、global_id 操作手册和活跃计划中的可执行引用。
- 2026-05-22：已通过验证命令；活跃计划中仅保留“脚本已删除”的历史说明。

## 回滚

若仍需要某个一次性脚本，从提交历史恢复对应文件和测试；恢复前应重新确认线上数据状态，避免旧脚本按过期数据模型写库。
