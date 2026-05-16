# JJC person-history 身份补全角色校验计划

状态：已实现/已验证，待提交
更新时间：2026-05-16

## 背景

当前 JJC 对局同步在缺少 `global_role_id` 但存在 `person_id` 时，会调用推栏 `mine/match/person-history` 补全身份。现有 `extract_identity_from_person_history(payload, person_id)` 只按 `person_id` 过滤，并选取第一条可提取身份字段的记录。

实际线上存在同一 `person_id` 下关联多个角色的情况。只按 `person_id` 取 `global_role_id` 可能把当前角色错误绑定到其他角色的 `global_role_id`，进而污染 `role_identities` 与 `jjc_sync_role_queue`，后续同步会持续沿用错误身份。

## 目标

- 将 `person-history` 返回记录从“可信身份”降级为“候选身份”，必须通过角色级校验后才允许使用 `global_role_id`。
- 同时覆盖两个补全入口：
  - 队列角色缺少 `global_role_id` 时的 `_resolve_role_identity_from_person_history(role)`。
  - 对局详情玩家缺少 `global_role_id` 时的 `_resolve_player_identity_from_person_history(player)`。
- 优先使用强身份校验：`zone + role_id`。
- 在没有强身份时，使用 `server + normalize_role_name(role_name, server)` 校验。
- 无法确认同一角色时返回空身份，让现有 fallback 继续处理，宁可不补全也不写错身份。
- 保持现有本地身份库优先、inspect resolver fallback、同步队列写入和对局详情缓存流程不变。

## 非目标

- 不改变推栏 `person-history` API 的签名或限速策略；允许按现有 `cursor` 参数分页读取直到返回空页。
- 不新增 MongoDB 集合、字段、索引或迁移脚本。
- 不修复已经写入 MongoDB 的历史错误身份；如需清理，另开数据修复计划。
- 不改变 `match/history` 按 `global_role_id` 拉取战局历史的主流程。
- 不引入并发请求或批量预取。

## 涉及文件

- `src/services/jx3/jjc_match_data_sync.py`
  - 扩展 `extract_identity_from_person_history` 的匹配参数。
  - 调整 `_resolve_role_identity_from_person_history` 传入队列角色的预期身份字段。
  - 调整 `_resolve_player_identity_from_person_history` 传入对局详情玩家的预期身份字段。
  - 对生产补全入口分页读取 `person-history`，直到找到同一角色候选或接口返回空页。
  - 增加角色级匹配逻辑和必要日志。
- `tests/test_jjc_match_data_sync.py`
  - 增加 `person_id` 相同但角色不一致时拒绝补全的单测。
  - 增加第一条不匹配、后续记录匹配时选择正确记录的单测。
  - 增加 `zone + role_id` 匹配优先的单测。
  - 增加对局详情玩家入队不写入错误 `global_role_id` 的单测。
- `scripts/audit_jjc_person_history_identity.py`
  - 新增历史身份审计脚本，默认 dry-run。
  - 扫描 MongoDB 中已写入的 `person_id + global_role_id` 组合，分页读取完整 `person-history` 后按本计划的角色校验规则判断是否疑似错绑。
  - 输出明确脏数据、无法确认数据和确认正确数据的报告。
- `tests/test_audit_jjc_person_history_identity.py`
  - 覆盖审计判断、dry-run 输出和修复建议构造。
- `docs/exec-plans/index.md`
  - 登记本计划。

## 设计方案

1. 扩展 `extract_identity_from_person_history` 参数。
   - 保留 `payload` 与 `person_id` 参数。
   - 新增可选参数：`expected_server`、`expected_role_name`、`expected_zone`、`expected_role_id`。
   - 继续兼容旧调用：如果没有传入任何预期角色字段，函数可保持原提取行为，避免影响未改造调用点；本次两个生产调用点必须传入预期字段。

2. 抽取候选记录匹配规则。
   - 对每条记录先校验 `person_id`：若传入了 expected `person_id`，且记录也带 `person_id`，两者不一致则跳过。
   - 提取候选字段：`global_role_id`、`role_id`、`zone`、`server`、规范化后的 `role_name`。
   - 计算强身份匹配：expected `zone + role_id` 与候选 `zone + role_id` 都存在且完全一致。
   - 计算名称匹配：expected `server + role_name` 与候选 `server + role_name` 都存在，且角色名经过 `normalize_role_name` 后完全一致。
   - 若传入了预期角色字段，只有强身份匹配或名称匹配成立时才返回候选身份。
   - 若候选记录角色字段与 expected 明确冲突，跳过该记录并继续检查下一条。

3. 收紧队列角色补全入口。
   - `_resolve_role_identity_from_person_history(role)` 从 role 提取：
     - `server`
     - `name`
     - `zone`
     - `role_id` 或 `game_role_id`
   - 分页调用 `person-history`，每页调用 `extract_identity_from_person_history` 时传入这些 expected 字段。
   - 每次 `cursor += size`，不设页数上限，直到接口返回空列表为止。
   - 找到匹配候选后立即停止翻页并返回身份。
   - 如果接口只返回同 `person_id` 的其他角色，返回空身份，继续走 `_resolve_role_identity_for_sync(role)`。

4. 收紧对局详情玩家补全入口。
   - `_resolve_player_identity_from_person_history(player)` 从 player 提取：
     - `server`
     - `role_name`
     - `zone`
     - `role_id`
   - 分页调用 `person-history`，每页调用 `extract_identity_from_person_history` 时传入这些 expected 字段。
   - 每次 `cursor += size`，不设页数上限，直到接口返回空列表为止。
   - 找到匹配候选后立即停止翻页并返回身份。
   - 如果 `person-history` 没有可确认同一角色的记录，不回填 `global_role_id`，后续 `_enqueue_players_from_detail` 按现有逻辑只写入已有可信字段。

5. 日志与观测。
   - 当 `person-history` 有同 `person_id` 记录但全部因角色不匹配被跳过时，记录 debug 或 info 日志，包含 expected `server/name/zone/role_id` 与候选数量，不记录敏感配置。
   - 避免 warning 噪音；角色不匹配属于可预期数据分歧，不应标记为异常。

6. `person-history` 分页策略。
   - 生产同步补全和审计脚本统一使用 `size=20`、`cursor=0,20,40...` 读取。
   - 不设置最大页数；优先以找到相同 `server + name`（或更强的 `zone + role_id`）角色作为停止条件。
   - 如果一直找不到同一角色，则继续往前翻，直到接口返回空页。
   - 第一页后每次继续翻页前都执行推栏限速 sleep，避免连续请求 person-history。
   - 审计脚本只聚合“从第一页到命中目标角色或空页”为止的已读取页，避免无意义拉取全量历史。
   - 接口失败时停止并归类为 `api_failed` 或返回空身份，不写库。

## 历史脏数据审计与修复

### 处理原则

- 先止血，再修复：先完成生产写入链路的角色校验，再运行历史数据审计。
- 默认只读：审计脚本默认 `--dry-run`，不允许默认写库。
- 不删除整条角色记录：只处理被证实错误的身份字段，保留仍可信的 `server/name/zone/role_id/person_id`。
- 证据不足不自动修：person-history 字段缺失、接口失败、候选记录无法确认时，只进入报告，不写库。
- 修复后必须可追踪：写入 `identity_source` 或修复备注字段时标记来源，便于后续排查。

### 审计范围

第一阶段扫描：

- `role_identities`
  - 重点字段：`identity_key`、`server`、`name`、`role_name`、`zone`、`role_id`、`game_role_id`、`person_id`、`global_role_id`、`identity_source`。
- `jjc_sync_role_queue`
  - 重点字段：`identity_key`、`server`、`name`、`zone`、`role_id`、`person_id`、`global_role_id`、同步水位字段和最近错误。

第二阶段按需要扩展扫描：

- `role_jjc_cache`
  - 只检查冗余身份字段是否与主身份冲突；不作为第一阶段自动修复对象。

### 判定规则

对每条同时存在 `person_id` 和 `global_role_id` 的记录：

1. 调用 `person-history` 分页查询该 `person_id`，直到找到相同 `server + name` 角色、空页或接口失败。
2. 在返回记录中查找相同 `global_role_id` 的候选。
3. 对候选执行角色级校验：
   - `zone + role_id` 与库中记录一致：判定为确认正确。
   - 或 `server + normalize_role_name(role_name, server)` 与库中记录一致：判定为确认正确。
   - `global_role_id` 相同但角色级字段明确冲突：判定为明确脏。
   - 找不到相同 `global_role_id`，但同 `person_id` 下存在其他角色记录：判定为疑似脏。
   - 接口失败、返回为空、字段不足或无法形成角色级校验：判定为无法确认。

### 修复动作

对明确脏数据，修复脚本在 `--apply` 模式下执行：

1. 清空错误的 `global_role_id`。
2. 保留 `person_id`、`zone`、`role_id/game_role_id`、`server`、`name/role_name` 等仍可信字段。
3. 重新计算 `identity_key`：
   - 有 `zone + role_id/game_role_id` 时降级为 `game:{zone}:{role_id}`。
   - 否则降级为 `name:{normalized_server}:{normalized_name}`。
4. 写入修复来源：
   - `identity_source = "person_history_mismatch_cleaned"`。
   - 如集合已有错误字段或备注字段，记录原 `global_role_id`、修复时间和原因。
5. 对 `jjc_sync_role_queue` 额外处理同步水位：
   - 清空错误 `global_role_id` 后，不能继续沿用基于错误身份产生的 `full_synced_until_time`、`oldest_synced_match_time`、`latest_seen_match_time`。
   - 将角色状态重置为可重新同步，保留最近错误信息或写入修复备注。
   - 若队列实现要求 `identity_key` 唯一，修复前检查目标降级 key 是否已存在；存在冲突时不自动合并，只输出人工处理项。

### 脚本设计

新增 `scripts/audit_jjc_person_history_identity.py`：

- 默认行为：
  - 连接 MongoDB。
  - 扫描目标集合。
  - 分页调用 person-history 进行校验。
  - 输出 JSON 报告到 `data/jjc_identity_audit/<timestamp>/summary.json` 和明细文件。
  - 不写数据库。
- 参数：
  - `--collection role_identities|jjc_sync_role_queue|all`
  - `--limit <n>`
  - `--person-id <id>`：只审计指定 person_id。
  - `--global-role-id <id>`：只审计指定 global_role_id。
  - `--apply`：执行明确脏数据修复。
  - `--yes`：与 `--apply` 配合，避免误触发；未传 `--yes` 时拒绝写库。
- 输出分类：
  - `confirmed_valid`
  - `confirmed_dirty`
  - `suspected_dirty`
  - `unknown`
  - `api_failed`
  - `conflict_needs_manual_merge`

### 上线顺序

1. 合入 person-history 角色校验代码，阻断新增错绑。
2. 运行 dry-run 审计，先限定 `--limit` 或指定已知问题 `person_id`。
3. 人工检查报告，确认判定规则没有误杀。
4. 对明确脏的小范围样本运行 `--apply --yes`。
5. 观察同步队列重新补全和同步结果。
6. 扩大到全量 dry-run，再按报告分批修复。

## 验证方案

自动化验证：

```bash
python -m unittest tests.test_jjc_match_data_sync
python -m unittest tests.test_audit_jjc_person_history_identity
python -m py_compile src/services/jx3/jjc_match_data_sync.py
python -m py_compile scripts/audit_jjc_person_history_identity.py
```

重点用例：

- `person_id` 相同且 `server + role_name` 匹配：返回该记录的 `global_role_id`。
- `person_id` 相同但 `server + role_name` 不匹配：返回空身份。
- 第一条同 `person_id` 但角色名不匹配，第二条同 `person_id` 且角色名匹配：返回第二条。
- `zone + role_id` 匹配、角色名缺失或格式不完整：允许返回该记录。
- `zone + role_id` 不匹配，即使 `person_id` 相同也拒绝返回。
- `_enqueue_players_from_detail` 中，`person-history` 返回其他角色时，不写入错误 `global_role_id` 到 `role_identities` 或 `jjc_sync_role_queue`。
- `_sync_one_role` 中，队列角色通过 `person-history` 返回其他角色时，应继续进入 inspect resolver fallback；若 fallback 也失败，则保持原失败处理。
- 审计脚本 dry-run 对明确脏数据只输出修复建议，不写 MongoDB。
- 审计脚本 `--apply --yes` 对明确脏数据清空错误 `global_role_id`，并按 `zone + role_id` 或 `server + name` 降级重建身份键。
- 审计脚本遇到目标 `identity_key` 冲突时不自动合并，输出 `conflict_needs_manual_merge`。

手工回归：

- 准备一个同 `person_id` 多角色的线上样本或 mock 响应。
- 对目标角色执行一次同步，确认日志显示不匹配记录被跳过，Mongo 中未写入其他角色的 `global_role_id`。
- 对 `person-history` 返回正确角色的样本执行同步，确认仍能补全 `global_role_id` 并继续拉取 `match/history`。
- 对已知疑似脏的 `person_id` 运行审计脚本 dry-run，确认报告能指出当前库内身份和 person-history 候选之间的冲突。
- 小范围执行 `--apply --yes` 后，确认错误 `global_role_id` 被清空，队列角色可通过后续安全链路重新补全或进入待人工补充状态。

## 风险与回滚

- 风险：推栏返回记录缺少 `server/role_name/zone/role_id`，导致原本能补全的身份现在被拒绝。该行为符合保守策略，避免错绑；可通过 inspect resolver fallback 或手工补充 `global_role_id` 解决。
- 风险：服务器名存在别名或格式差异，导致名称匹配失败。缓解方式是优先使用 `zone + role_id`；如后续发现稳定别名规则，再单独引入服务器规范化。
- 风险：历史已污染身份不会被本次改动自动纠正。需要通过单独脚本排查 `role_identities` 和 `jjc_sync_role_queue`。
- 风险：自动修复时目标降级 `identity_key` 已存在，可能需要人工合并历史水位和队列状态。脚本不得自动合并冲突记录。
- 风险：清空错误 `global_role_id` 后，相关角色会重新进入身份补全或同步失败状态，短期内可能增加 inspect resolver 或人工补充需求。
- 回滚代码改动：恢复 `extract_identity_from_person_history(payload, person_id)` 只按 `person_id` 提取的旧行为，并移除两个调用点传入 expected 字段的改动。
- 回滚数据修复：审计脚本在 `--apply` 前必须输出原值。若误修，按报告中的原 `global_role_id` 和原 `identity_key` 手工恢复；对已经重置的同步水位，需要重新触发该角色同步。
