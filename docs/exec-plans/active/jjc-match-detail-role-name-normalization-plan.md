# JJC 对局详情角色名规范化与历史数据修复计划

## 背景

JJC 对局详情同步从推栏 `match_detail` 的 `players_info[].role_name` 提取玩家名称，并写入 `role_identities` 与 `jjc_sync_role_queue`。推栏在对局详情里经常返回展示名，格式为 `角色名·服务器`，例如 `奈川寺·梦江南`；同一玩家节点同时还有独立的 `server` 字段。

当前同步链路直接把 `role_name` 原样作为角色名写入身份表，导致：

- `role_identities.name` / `normalized_name` 被写成 `奈川寺·梦江南`。
- `jjc_sync_role_queue.name` / `normalized_name` 也可能被写成同样格式。
- `sources` 中出现 `match_detail` 的记录有些正确、有些错误。原因是排行榜、indicator、部分历史迁移链路已经拆过 `·`，而对局详情自动发现链路没有统一处理；已有正确记录也可能只是追加了 `match_detail` source，没有被旧对局覆盖。

只读排查抽样结果：

- `role_identities` 总量约 14945。
- `sources` 包含 `match_detail` 且 `name` 带 `·` 的记录约 2962。
- `sources` 包含 `match_detail` 且 `name` 不带 `·` 的记录约 1854。
- 示例 `奈川寺·梦江南` 的 `jjc_match_detail` 原始节点为 `role_name=奈川寺·梦江南`、`server=梦江南`，应派生为 `name=奈川寺`、`server=梦江南`。

## 目标

1. 新增统一的推栏角色展示名解析规则，确保后续由 `match_detail` 派生出的身份与同步队列只保存纯角色名。
2. 保留 `jjc_match_detail` 中历史对局详情的原始 `role_name`，不把历史对局快照改成当前画像数据。
3. 修复已污染的 `role_identities` 与 `jjc_sync_role_queue` 历史数据。
4. 迁移脚本必须支持 dry-run、limit、按集合统计影响范围，并且幂等。

## 非目标

- 不修改推栏原始响应结构和 `jjc_match_detail.data.detail.*` 历史快照内容。
- 不重建装备/奇穴快照，不影响 `jjc_equipment_snapshot`、`jjc_talent_snapshot`。
- 不调整 `identity_key` 生成优先级。
- 不处理角色名本身合法包含 `·` 的极端情况；当前按推栏展示名约定，只在 `·` 右侧等于玩家节点 `server` 时拆分。

## 设计规则

### 角色名解析

新增一个小型纯函数，例如放在 `src/services/jx3/jjc_match_data_sync.py` 或可复用的 JJC 工具模块：

- 输入：`raw_role_name`、`server`。
- 输出：派生身份使用的 `role_name`。
- 规则：
  - 先 `strip()`。
  - 若不包含 `·`，原样返回。
  - 若包含 `·`，只拆最后一个 `·`，得到 `left` / `right`。
  - 当 `right.strip() == server.strip()` 且 `left` 非空时，返回 `left.strip()`。
  - 否则保留原样，避免误伤 `发神鲸@龙争虎斗·龙争虎斗` 这类角色名里已带历史服标记、且右侧仍是当前服的情况需要进一步判断。

更严格的最终规则建议为：

- 先拆最后一个 `·`。
- 只要右侧等于当前 `server`，右侧视为推栏附加服务器，返回左侧。
- 角色名中存在 `@旧服` 不再额外处理，例如 `发神鲸@龙争虎斗·龙争虎斗` 应修复成 `发神鲸@龙争虎斗`。这是推栏展示名的一部分，表示角色名中带转服标识或历史服标识，不能继续拆 `@`。

### 写入链路

修改 `extract_players_from_detail()`：

- 原始 `player["role_name"]` 仅作为输入。
- 返回的 `players[].role_name` 改为规范化后的纯角色名。
- 去重键 `name:{server}:{role_name}` 使用规范化后的角色名。
- 可选保留 `raw_role_name` 仅用于日志或调试，不写入身份表。

修改 `_backfill_player_from_identity()`：

- 从 `person-history` 或本地身份库回填 `role_name` 时，也走同一解析函数。
- 避免 person-history 未来返回 `角色名·服务器` 时再次污染。

修改 `_enqueue_players_from_detail()`：

- `name`、`normalized_name`、`upsert_from_match_detail(name=...)`、`upsert_role(name=...)` 全部使用规范化后的角色名。

不修改 `JjcRankingInspectService.get_match_detail()` 保存缓存时的 `role_name`：

- 这里保存的是对局详情快照，继续保留推栏返回的展示值，方便还原原始对局详情。

## 历史数据修复

新增脚本：`scripts/fix_jjc_match_detail_role_names.py`。

脚本能力：

- 读取 `MONGO_URI`，优先环境变量，其次 `runtime_config.json`。
- 默认 dry-run，不写库。
- 参数：
  - `--apply`：实际写入。
  - `--limit N`：限制处理条数，便于灰度。
  - `--collection role_identities|jjc_sync_role_queue|all`：指定集合。
  - `--only-source match_detail`：默认只处理 `sources` 包含 `match_detail` 或 `source=match_detail` 的记录。
  - `--backup-collection <name>`：apply 前把被修改文档快照写入备份集合，默认按时间生成。

修复范围：

- `role_identities`：
  - 条件：`name` 包含 `·`，且 `server` 非空。
  - 使用同一解析函数得到 `fixed_name`。
  - 仅当 `fixed_name != name` 时更新：
    - `name`
    - `normalized_name`
    - `updated_at`
  - `identity_key` 为 `global:*` 或 `game:*` 时不需要改 key。
  - `identity_key` 为 `name:*` 时必须重新计算新 key，并处理唯一键冲突：
    - 若新 key 不存在，更新 `identity_key`，旧 key 追加到 `aliases`。
    - 若新 key 已存在，优先合并来源、外部 ID、aliases、时间字段；旧记录标记为 merged 或删除需谨慎。第一版建议不自动合并冲突，输出冲突报告，由人工确认后再执行二阶段合并。
- `jjc_sync_role_queue`：
  - 条件：`name` 包含 `·`，且 `server` 非空。
  - 更新：
    - `name`
    - `normalized_name`
    - `updated_at`
  - 若 `identity_key` 是 `name:*`，同样重新计算并处理冲突。
  - 若 `identity_key` 是 `global:*` 或 `game:*`，只改展示字段，不改同步水位。

幂等性：

- 已修复记录再次执行时不会产生新变更。
- 备份集合以原 `_id` + 迁移批次号记录，避免同一批重复备份。
- dry-run 输出修改数量、冲突数量、示例前后对比。

回滚：

- 对 apply 批次记录 `batch_id`。
- 提供 `--rollback <batch_id>`，从备份集合恢复被改字段。
- 若仅更新 `name` / `normalized_name` / `identity_key` / `aliases` / `updated_at`，回滚范围也只恢复这些字段，不覆盖同步水位、租约、失败次数等运行时字段。

## 数据库文档更新

实现时同步更新 `docs/design-docs/database-design.md`：

- `role_identities.name` 说明补充：存纯角色名，不保存推栏 `角色名·服务器` 展示名。
- `jjc_sync_role_queue.name` 同步补充同样约束。
- `jjc_match_detail` 说明补充：对局详情玩家节点可保留推栏展示名，派生身份表时必须解析为纯角色名。
- 迁移脚本列表补充 `scripts/fix_jjc_match_detail_role_names.py`。

## 验证方案

自动化测试：

- `extract_players_from_detail()`：
  - `奈川寺·梦江南` + `server=梦江南` -> `奈川寺`。
  - `奈川寺` + `server=梦江南` -> `奈川寺`。
  - `发神鲸@龙争虎斗·龙争虎斗` + `server=龙争虎斗` -> `发神鲸@龙争虎斗`。
  - `角色A·别的服` + `server=梦江南` -> 保留原样或进入冲突报告，按最终规则断言。
- `_enqueue_players_from_detail()`：
  - 写入 `identity_repo.upsert_from_match_detail()` 的 `name` 为纯角色名。
  - 写入 `repo.upsert_role()` 的 `name` / `normalized_name` 为纯角色名。
- 迁移脚本：
  - dry-run 不写库。
  - apply 只改目标字段。
  - `global:*` key 记录只改展示字段。
  - `name:*` key 重算无冲突时更新 key 并追加 aliases。
  - key 冲突时输出冲突报告，不静默覆盖。

本地验证命令：

```bash
python -m unittest tests.test_jjc_match_data_sync
python -m py_compile src/services/jx3/jjc_match_data_sync.py scripts/fix_jjc_match_detail_role_names.py
python scripts/fix_jjc_match_detail_role_names.py --limit 20
```

线上/测试库手工验证：

```bash
python scripts/fix_jjc_match_detail_role_names.py --limit 20
python scripts/fix_jjc_match_detail_role_names.py --apply --limit 20
python scripts/fix_jjc_match_detail_role_names.py
```

观察指标：

- dry-run 中 `name` 带 `·` 的可修复数量下降。
- 抽查 `奈川寺·梦江南` 修复为 `奈川寺`，`server` 仍为 `梦江南`。
- `jjc_match_detail` 原始详情不被修改。
- 同步队列水位字段不变。

## 风险与处理

- 角色名本身可能包含 `·`：只在右侧等于当前 `server` 时拆分，降低误伤。
- `identity_key=name:*` 可能冲突：第一版迁移不自动合并冲突，输出报告，避免误合并不同角色。
- 同步任务运行中修改 `jjc_sync_role_queue`：执行历史迁移前建议暂停 JJC 同步，完成后再恢复。
- `profile_observed_at` 语义不变：修复历史名称不代表新的观测时间，不更新该字段。

## 执行步骤

1. 实现统一角色名解析函数，并接入 `match_detail` 玩家提取与身份回填链路。
2. 补充单元测试覆盖带 `·`、不带 `·`、带 `@旧服` 的样例。
3. 新增历史数据修复脚本，先完成 dry-run 与冲突报告。
4. 更新数据库设计文档，记录字段语义和迁移脚本。
5. 本地运行单测与 py_compile。
6. 对线上库先 dry-run，确认影响范围和冲突清单。
7. 暂停 JJC 同步任务，执行小批量 `--apply --limit 20`，抽查结果。
8. 无异常后全量 apply，保留备份批次号。
9. 恢复 JJC 同步任务，观察后续新增 `role_identities.name` 是否仍出现 `·服务器`。

## 当前状态

- 阶段：方案已编写，待确认后进入实现。
- 尚未修改业务代码。
- 尚未执行历史数据写入。
