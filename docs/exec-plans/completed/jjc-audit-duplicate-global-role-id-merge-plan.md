# JJC 审计脚本：同角色多 global_role_id 合并归档 + 新角色发现补录

状态：已完成（8cf81e4）
更新时间：2026-05-17

## 背景

`scripts/audit_jjc_person_history_identity.py` 已支持按 person-history 审计 `role_identities` 和 `jjc_sync_role_queue` 中 global_role_id 的准确性，并能自动修复明确脏数据和链式交叉绑定。

但在实际跑全量时发现两个问题：

1. **同角色多 global_role_id**：同一个角色（同 server + 同 name）可以在 `role_identities` 中存在多条文档，各自持有不同的 `global_role_id`，且两个 ID **目前都有效**（查对局历史返回相同数据）。实例：一晴天一@乾坤一掷 同时有 `SK01-ECRIBP-...MGE` 和 `SK01-TX35AM-...AEM4` 两条文档。当前脚本对这种情况判定为 `conflict_needs_manual_merge`，无法自动处理。

2. **person-history 中存在未收录的角色**：审计时用 person_id 查 person-history，返回的对局列表里可能包含该 person 下的其他角色（不同 server/name），这些角色尚未录入 `role_identities` 和 `jjc_sync_role_queue`，属于遗漏数据。

## 目标

- 检测同一 server + normalized_name 下存在多条 role_identities 文档的场景，以 person-history 为准保留当前 ID，旧的归档到 `role_identities_history`
- 合并前用 match history 验证两个 global_role_id 返回相同对局，确认是同一角色
- 审计过程中发现 person-history 里有未收录的角色时，自动补录到 `role_identities` 和 `jjc_sync_role_queue`
- 保留文档缺失 role_id / game_role_id 时，从归档文档补全

## 非目标

- 不处理 `jjc_sync_role_queue` 的重复（那个集合本身允许多条同角色记录）
- 不修改 person-history 之外的分类/修复逻辑
- 不引入 indicator 接口交叉验证（留待后续）

## 改动范围

1. `scripts/audit_jjc_person_history_identity.py` — 新增合并归档 + 新角色补录逻辑
2. `src/infra/mongo.py` — 新增 `role_identities_history` 集合索引
3. `docs/design-docs/database-design.md` — 新增集合文档

## 具体设计

### 新集合 `role_identities_history`

字段：完整复制原文档所有字段，外加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `archived_at` | datetime | 归档时间 |
| `archive_reason` | string | `"duplicate_global_role_id_merged"` |
| `replaced_by_identity_key` | string | 保留文档的 identity_key |

索引：
- `identity_key` 普通索引
- `global_role_id` 普通索引
- `archived_at` 普通索引

### 新增函数：新角色发现补录

```python
async def discover_new_roles_from_person_history(
    db: Any,
    payload: Dict[str, Any],
    expected_person_id: str,
) -> int:
```

在每轮 person-history 查询完成后调用，遍历返回的所有对局条目：
1. 按 `(person_id, server, role_name, zone, role_id, global_role_id)` 去重
2. 对每条去重后的角色，检查 `role_identities` 中是否已存在（按 global_role_id 查，fallback zone+role_id，fallback server+name）
3. 不存在的 → 构造 identity 文档，写入 `role_identities`（identity_source=`"person_history_discovered"`）
4. 同时写入 `jjc_sync_role_queue`（status=`"pending"`，触发后续同步）
5. 返回补录数量

重复检测逻辑复用已有 `role_fields_match` 和 `_candidate_fields`。

### 新增函数 `detect_same_role_duplicates`

```python
def detect_same_role_duplicates(
    all_items: List[Tuple[...]],
) -> List[Tuple[str, List[Tuple[...]]]]:
```

输入 Phase 1 分类结果，按 `(collection, normalized_server, normalized_name)` 分组：
- 过滤出同一组内文档数 > 1 的
- 只关心至少有一条分类为 `confirmed_dirty` 或 `conflict_needs_manual_merge` 的组（说明组内存在不一致）
- 返回 `[(collection, group_items), ...]`

### 新增函数 `resolve_duplicate_merge`

```python
async def resolve_duplicate_merge(
    db: Any,
    collection: str,
    group_items: List[Tuple[...]],
    person_history_client: Any,
) -> Tuple[int, List[str]]:
```

对每组重复文档：
1. 用两个 global_role_id 各调一次 match history（size=1），比对返回的 match_id，相同则确认是同一角色
2. 在 person-history 中出现的 global_role_id → 当前有效，保留
3. 未出现的 → 旧 ID，归档：
   - insert 到 `role_identities_history`
   - delete 原文档
4. 保留文档缺失 role_id / game_role_id / zone 时，从归档文档补全并 update
5. match history 不一致 → 跳过，标记需人工判断

### 集成到 `run_audit`

```
Phase 1: 分类收集
  - 每轮 person-history 查询后调用 discover_new_roles_from_person_history
  - 分类逻辑不变
Phase 2: 应用修复
  2a. 同角色重复检测 → resolve_duplicate_merge（match history 交叉验证）
  2b. confirmed_dirty 应用
  2c. 冲突链式解析
```

### 日志格式

```
[DISCOVER] person_id=xxx 发现新角色: server=xxx name=xxx global_role_id=xxx（已补录 1 条）
[MERGE] collection=role_identities server=乾坤一掷 name=一晴天一
  keep:  identity_key=global:...AEM4 (person-history 出现)
  archive: identity_key=global:...MGE (person-history 未出现, role_id=26578440 → 已补全到保留文档)
  verified: match history 确认两个 gid 返回相同对局 match_id=255806091
```

## 验证

1. `python -m py_compile scripts/audit_jjc_person_history_identity.py`
2. 用一晴天一的 person_id 跑 dry-run，确认 `[MERGE]` 日志且 match history 验证通过
3. 用 `--apply --yes` 跑一晴天一：确认旧文档移入 history，保留文档 role_id 被补全
4. 跑全量 dry-run，确认 `[DISCOVER]` 日志出现且补录合理
5. `python -m unittest tests.test_audit_jjc_person_history_identity -v`
