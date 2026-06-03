# JJC 单角色参与者投影补齐脚本计划

## 目标

新增一个运维脚本，输入服务器名称和角色名称，定位该角色在 `jjc_match_detail` 中出现过的 3v3 对局；只要整场对局的 `jjc_match_participants` 投影与明细可构建参与者不一致，就按现有投影规则重建整场对局参与者投影。

## 范围

- 新增脚本：`scripts/backfill_jjc_match_participants_for_role.py`
- 复用现有仓储：`src/storage/mongo_repos/jjc_match_participant_repo.py`
- 不修改数据库集合、字段或索引。

## 行为设计

- 参数：
  - `server`：服务器名称
  - `name`：角色名称
  - `--mongo-uri`、`--db-name`：可选 Mongo 连接覆盖
  - `--limit`：限制处理整场投影不一致的对局数
  - `--apply --yes`：确认写库；默认 dry-run
- 查询角色身份：
  - 从 `role_identities` 读取 `normalized_server + normalized_name` 命中的 `global_id`
  - 同时按 `server + role_name/name` 从 `jjc_match_detail` 查展示名，兼容 `角色名` 与 `角色名·服务器`
- 缺失判断：
  - 如果输入角色明细玩家行带 `global_id`，将该对局纳入可投影候选
  - 对可投影候选对局，构建整场 3v3 参与者预期 `global_id` 集合，并与 `jjc_match_participants` 中同一 `match_id` 的整场投影 `global_id` 集合比较
  - 只要整场集合不一致，就将该对局纳入重建列表
  - 如果玩家行没有 `global_id`，记录为不可投影，不写库
- 写入：
  - 对整场投影不一致且可投影的 `match_id` 调用 `JjcMatchParticipantRepo.build_participants_from_match_detail()`
  - 用 `replace_match_participants()` 写入整场 3v3 参与者投影，确保同场每个带 `global_id` 的角色都有投影

## 验证

- `python -m py_compile scripts/backfill_jjc_match_participants_for_role.py`
- dry-run 查询指定角色，确认输出包含命中数、整场投影不一致数、不可投影数和样本。
- 如需线上写库，执行 `--apply --yes` 后复查同角色投影缺口归零或仅剩无 `global_id` 的不可投影明细。

## 执行状态

- 已新增 `scripts/backfill_jjc_match_participants_for_role.py`。
- 已通过 `python -m py_compile scripts/backfill_jjc_match_participants_for_role.py`。
- 已对 `唯满侠 桃桃白糖` 示例参数执行线上 dry-run，只读验证通过；未执行写库。
- 已将触发条件调整为整场投影集合比对；对 `天鹅坪 观剑生 --limit 3` dry-run 验证，待重建样本均为整场 6 个 `global_id` 缺失；未执行写库。

## 回滚

- 脚本为新增文件，不影响运行时。
- 如写入错误，可按 `match_id` 删除 `jjc_match_participants` 对应投影后重新运行通用回填脚本。
