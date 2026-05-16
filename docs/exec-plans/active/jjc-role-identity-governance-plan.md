# JJC 角色身份治理计划

状态：待确认/待实现
更新时间：2026-05-15

## 背景

当前 JJC 身份相关规则已经分散在多个位置：

- `src/services/jx3/jjc_match_data_sync.py`
  - 负责同步链路中的 `person-history` 候选身份校验、对局详情玩家身份回填、同步队列写入。
- `scripts/audit_jjc_person_history_identity.py`
  - 负责离线审计历史 `person_id + global_role_id` 组合，并构造修复动作。
- `src/storage/mongo_repos/role_identity_repo.py`
  - 负责 `role_identities` 的身份 key 构建、升级和查询。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 负责 `jjc_sync_role_queue` 的身份 key 构建、队列写入和同步水位维护。

本次 `person-history` 角色级校验已先完成止血，但规则仍存在重复实现：线上写入链路和离线审计脚本各自实现候选字段提取、角色匹配、身份 key 降级和修复 update。后续如果继续增加身份来源、服务器别名、角色改名/转服处理、冲突记录或自动修复，重复规则容易漂移。

## 目标

- 将 JJC 角色身份匹配、候选证据、可信等级和冲突分类收敛到单一规则模块。
- 让线上写入、离线审计、历史修复使用同一套角色级校验规则。
- 明确身份可信等级，区分“已验证身份”“候选身份”“冲突身份”和“证据不足”。
- 收敛身份写入与修复入口，避免 service、script、repo 多处各自拼 Mongo update。
- 保持现有同步行为兼容：已有安全 fallback、同步队列调度、对局详情缓存流程不因治理改造而扩大变更。
- 形成可小步上线的数据治理路径：先 dry-run 报告，再小范围修复，再持续防回流。

## 非目标

- 不在本计划内立刻全量清洗线上数据。
- 不引入新的外部接口或改变推栏请求参数。
- 不改变 `match/history` 按 `global_role_id` 拉取对局历史的主流程。
- 不自动合并存在目标 `identity_key` 冲突的记录。
- 不重构与 JJC 身份无关的缓存、排名、前端或 QQ 命令。
- 不把审计脚本改成常驻任务；定期化观察可作为后续计划。

## 涉及文件

预计新增：

- `src/services/jx3/role_identity_matching.py`
  - 角色身份候选、预期身份、匹配结果、可信等级的纯函数/小数据结构。
- `src/services/jx3/role_identity_service.py`
  - 统一身份写入、升级、降级清理、冲突记录的业务服务入口。
- `tests/test_role_identity_matching.py`
  - 覆盖字段提取、角色匹配、可信等级和分类规则。
- `tests/test_role_identity_service.py`
  - 覆盖写入入口、修复动作构造、冲突不自动合并等业务行为。

预计调整：

- `src/services/jx3/jjc_match_data_sync.py`
  - 复用共享匹配规则，不再内联实现 `person-history` 角色匹配细节。
- `scripts/audit_jjc_person_history_identity.py`
  - 复用共享匹配/分类/修复规则，只保留参数解析、扫描、报告和调用。
- `src/storage/mongo_repos/role_identity_repo.py`
  - 必要时补充受控更新方法，避免上层直接拼复杂 Mongo update。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 必要时补充清理错误 `global_role_id` 和重置同步水位的仓储方法。
- `docs/design-docs/database-design.md`
  - 若新增字段、冲突集合或修复备注字段，必须同步更新。
- `docs/exec-plans/index.md`
  - 登记本计划。

## 设计方案

### 1. 抽取身份匹配单一事实源

新增 `src/services/jx3/role_identity_matching.py`，只包含纯逻辑，不依赖 Mongo、NoneBot、HTTP client 或脚本参数。

建议结构：

- `RoleIdentityExpected`
  - `person_id`
  - `global_role_id`
  - `server`
  - `role_name`
  - `zone`
  - `role_id`
- `RoleIdentityCandidate`
  - 来源字段同上，并保留 `source` 与原始候选摘要。
- `RoleIdentityMatchResult`
  - `matched`
  - `match_level`: `global_verified` / `game_verified` / `name_verified` / `candidate_unverified` / `conflict` / `unknown`
  - `reason`
  - `candidate`

核心纯函数：

- `normalize_identity_role_name(role_name, server)`
- `extract_expected_identity(doc_or_role)`
- `extract_person_history_candidate(item)`
- `match_role_identity(expected, candidate)`
- `classify_person_history_identity(expected, candidates)`
- `build_degraded_identity_key(expected_or_doc, collection_kind)`

规则：

- 强身份匹配：`zone + role_id` 完全一致。
- 名称匹配：`server + normalize_role_name(role_name, server)` 完全一致。
- 有强身份冲突时，默认不直接升级身份；若名称匹配但强身份冲突，先按规则返回可观测 reason，后续由调用方决定是否确认、降级或人工处理。
- 字段不足时返回 `unknown` 或 `candidate_unverified`，不得伪造验证成功。

### 2. 收敛线上写入入口

新增或扩展 `RoleIdentityService`，作为 service 层统一业务入口：

- `resolve_verified_from_person_history(expected, payload)`
  - 返回通过共享规则确认后的身份，不直接写库。
- `upsert_verified_identity(server, name, identity, source, observed_at=None)`
  - 统一写入 `role_identities`。
- `clean_mismatched_global_role_id(collection, doc, reason, apply=False)`
  - 统一构造并应用清理动作。
- `record_identity_conflict(...)`
  - 先可只返回报告结构；若决定新增集合或字段，再另行更新数据库设计。

`jjc_match_data_sync.py` 改为调用该服务或共享 pure helper：

- 队列角色缺少 `global_role_id` 时，使用 `resolve_verified_from_person_history`。
- 对局详情玩家缺少 `global_role_id` 时，使用同一规则。
- `_upsert_role_identity_from_resolved` 保持现有行为，但逐步迁移到统一写入入口。

### 3. 重构审计脚本为薄入口

`scripts/audit_jjc_person_history_identity.py` 只保留：

- 参数解析。
- Mongo 连接。
- 扫描集合。
- 调用 person-history。
- 调用共享规则分类。
- 输出报告。
- 在 `--apply --yes` 时调用统一修复入口。

脚本不再直接维护以下规则：

- 候选字段提取。
- 角色强/弱匹配。
- 可信等级判定。
- 身份 key 降级策略。
- 队列水位重置字段清单。

### 4. 身份可信等级与冲突策略

建议在代码层先定义枚举/常量，不急于落库：

- `global_verified`
  - `global_role_id` 经过角色级规则确认。
- `game_verified`
  - 有 `zone + role_id`，但没有可信 `global_role_id`。
- `name_verified`
  - 只有 `server + normalized_name`，可信度最低。
- `candidate_unverified`
  - 有候选身份，但字段不足或不能确认同一角色。
- `conflict`
  - 同一 `person_id/global_role_id` 与当前角色字段明确冲突。
- `unknown`
  - 接口失败、返回为空或证据不足。

后续如需落库，可在 `role_identities` 增加：

- `identity_status`
- `identity_conflict`
- `last_identity_audit_at`
- `identity_audit_reason`

是否新增字段必须在实施阶段评估，并同步 `docs/design-docs/database-design.md`。

### 5. 数据治理流程

治理分阶段执行：

1. 规则抽取与复用
   - 先让线上和审计脚本使用同一套规则。
   - 不改线上数据。
2. dry-run 审计
   - 只输出报告。
   - 先用 `--limit` 或指定 `--person-id` 小样本验证。
3. 小范围 confirmed_dirty 修复
   - 只修明确脏数据。
   - 清空错误 `global_role_id`，降级 key，重置队列水位。
4. 冲突与疑似脏人工处理
   - `conflict_needs_manual_merge` 和 `suspected_dirty` 不自动合并。
5. 防回流
   - 所有写入 `global_role_id` 的路径复用共享校验。
   - 定期 dry-run 审计可作为后续计划。

## 实施步骤

1. 新增共享匹配模块。
   - 从当前 `jjc_match_data_sync.py` 和审计脚本中提炼纯函数。
   - 补 `tests/test_role_identity_matching.py`。

2. 改造线上同步链路。
   - `extract_identity_from_person_history` 复用共享候选匹配。
   - 队列角色与对局详情玩家补全保持现有行为。
   - 跑 `tests.test_jjc_match_data_sync`。

3. 改造审计脚本。
   - 分类、降级 key、修复建议统一调用共享模块。
   - 保持 CLI 参数与报告路径兼容。
   - 跑 `tests.test_audit_jjc_person_history_identity`。

4. 收敛修复写入入口。
   - 若只需脚本内构造 update，可先抽到 service 纯函数。
   - 若需要调用 repo 修改数据，补充 `role_identity_repo` / `jjc_sync_repo` 的明确方法。
   - 禁止脚本散写复杂业务 update。

5. 文档联动。
   - 若新增字段或集合，更新 `docs/design-docs/database-design.md`。
   - 若新增回归命令，更新 `docs/references/runbook.md`。
   - 计划完成后保留在 active，待提交后再移入 completed。

## 验证方案

自动化验证：

```bash
python -m unittest tests.test_role_identity_matching
python -m unittest tests.test_jjc_match_data_sync
python -m unittest tests.test_audit_jjc_person_history_identity
python -m py_compile src/services/jx3/role_identity_matching.py src/services/jx3/jjc_match_data_sync.py scripts/audit_jjc_person_history_identity.py
```

重点用例：

- 同一输入下，线上同步和审计脚本分类结果一致。
- `zone + role_id` 匹配时返回 verified。
- `server + normalize_role_name` 匹配时返回 verified。
- `person_id` 相同但角色字段冲突时返回 conflict 或拒绝补全。
- 字段不足时返回 unknown/candidate_unverified，不写入 `global_role_id`。
- `confirmed_dirty` 修复只清空错误 `global_role_id`，不删除角色记录。
- `identity_key` 冲突时不自动合并。
- `--apply` 未带 `--yes` 时拒绝写库。

手工回归：

- 使用一个同 `person_id` 多角色样本，确认同步链路不会回填其他角色的 `global_role_id`。
- 使用一个 person-history 正确角色样本，确认仍能补全身份。
- 使用审计脚本 dry-run 小样本，确认报告分类与共享规则一致。
- 小范围 apply 后，确认队列水位被重置，后续同步不会继续使用错误 `global_role_id`。

## 风险与回滚

- 风险：抽规则时改变已有边界行为，导致原本可补全的身份被保守拒绝。
  - 缓解：先保持当前测试全部通过，再补共享规则一致性测试。
- 风险：service 与 script 迁移到共享模块过程中遗漏字段别名。
  - 缓解：保留现有字段提取兼容，如 `role_id/game_role_id`、`global_role_id/globalRoleId`、`role_name/roleName`。
- 风险：修复入口过早抽象，影响当前简单脚本可读性。
  - 缓解：先抽纯规则，再收敛写库入口，不一次性重构过大。
- 风险：新增身份状态字段后数据库文档含义不清。
  - 缓解：新增字段前先更新数据库设计文档，并保持老字段兼容。
- 回滚：
  - 共享模块改造可回退到当前 `person-history` 角色级校验实现。
  - 审计脚本可回退到当前 dry-run/apply 版本。
  - 若新增字段，回滚代码时保留字段不读写，不立即删除线上数据。
