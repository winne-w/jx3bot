# JJC 审计冲突链环路修复计划

> 已合并至 `docs/exec-plans/active/jjc-role-global-id-governance-plan.md`，本文仅作历史参考。

## 背景

`scripts/audit_jjc_person_history_identity.py` 在 `--apply` 修复 `role_identities` / `jjc_sync_role_queue` 时，会追溯 `global_role_id` 冲突链。当前日志 `/tmp/repair.log` 显示两个 `global_role_id` 在链路追溯中交替出现，脚本未能退出。

已定位原因：链路去重把 `_id` 转成字符串保存，但 Mongo 查询用原始 `_id` 字段做 `$nin`，当 `_id` 为 `ObjectId` 时排除条件失效，已访问文档会再次被查询到。同时脚本缺少冲突链环路的兜底处理。

## 目标

- 修复冲突链追溯的访问去重，避免重复审计同一 Mongo 文档。
- 对 A/B 互指或更长链路环路做显式检测。
- 环路出现时优先复用现有同角色重复合并逻辑；不能自动证明可合并时标记为手工冲突并退出链路，保证审计脚本继续处理后续数据。
- 不改变 Mongo 集合结构、不新增索引、不调整运行时机器人逻辑。

## 涉及文件

- `scripts/audit_jjc_person_history_identity.py`
- `docs/exec-plans/index.md`
- 本计划文档

## 实施方案

1. 在 `_resolve_conflict_chain` 中保留原始 `_id` 作为 Mongo 查询排除值，同时维护字符串形式的访问集合用于日志和环路判断。
2. 增加 `seen_global_role_ids` / `seen_identity_keys`，当下一个 `target_gid` 指向链上已有文档时判定为环路。
3. 增加最大链长兜底，异常数据超过阈值时按环路/过长链处理。
4. 发现环路后停止继续追溯，进入后续合并策略；若合并失败，对链上仍处于 `conflict_needs_manual_merge` 的结果写入 `reason=conflict_chain_cycle_detected` 或 `conflict_chain_too_deep`。
5. `--apply` 模式下对未自动修复的链上文档标记审计时间，避免同一轮无限重复；明细 JSON 保留手工处理依据。

## 验证方式

- 已执行：`python -m py_compile scripts/audit_jjc_person_history_identity.py`
- 已执行：`git diff --check -- scripts/audit_jjc_person_history_identity.py docs/exec-plans/index.md docs/exec-plans/active/jjc-audit-conflict-chain-cycle-plan.md`
- 离线代码检查确认 `_id` 排除条件使用原始类型。
- 如需线上验证，用较小 `--limit` 或指定过滤条件复跑审计脚本，观察日志出现 `CHAIN_CYCLE` 后继续推进，不再重复输出同两条 `CHAIN_TRACE`。

## 风险与回滚

- 自动合并仍依赖既有 match history 交叉验证；验证失败时不强行合并，保守标记为手工冲突。
- 回滚方式：恢复本次脚本改动；不会产生 schema 或索引层面的不可逆变化。
