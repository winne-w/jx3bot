# JJC 角色身份治理计划

状态：待确认/待实现
更新时间：2026-05-19

## 背景

当前 JJC 身份相关规则已经分散在多个位置：

- `src/services/jx3/jjc_match_data_sync.py`
  - 负责同步链路中的 `person-history` 候选身份校验、对局详情玩家身份回填、同步队列写入。
- `scripts/audit_jjc_person_history_identity.py`
  - 负责离线审计历史 `person_id + global_role_id` 组合、冲突链追溯、重复身份合并和修复动作构造。
- `src/storage/mongo_repos/role_identity_repo.py`
  - 负责 `role_identities` 的身份 key 构建、升级和查询。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 负责 `jjc_sync_role_queue` 的身份 key 构建、队列写入和同步水位维护。

本次 `person-history` 角色级校验已先完成止血，但规则仍重复存在：线上写入链路和离线审计脚本各自实现候选字段提取、角色匹配、身份 key 降级和修复 update。后续如果继续增加身份来源、服务器别名、角色改名/转服处理、冲突记录或自动修复，重复规则容易漂移。

## 目标

- 将 JJC 角色身份匹配、候选证据、匹配等级、审计分类和身份 key 构造逐步收敛到单一规则模块。
- 让线上同步、离线审计、历史修复最终使用同一套角色级校验规则。
- 明确两类概念：
  - 匹配等级：用于判断候选证据可信度，如 `global_verified`、`game_verified`、`name_verified`、`candidate_unverified`、`conflict`、`unknown`。
  - 审计分类：用于报告和修复动作，如 `confirmed_valid`、`confirmed_dirty`、`suspected_dirty`、`conflict_needs_manual_merge`、`api_failed`、`unknown`。
- 分阶段收敛身份写入与修复入口，避免 service、script、repo 多处各自拼 Mongo update。
- 保持现有同步行为兼容：已有安全 fallback、同步队列调度、对局详情缓存流程不因治理改造而扩大变更。
- 形成可小步上线的数据治理路径：先规则抽取和 dry-run 对齐，再小范围修复，再持续防回流。

## 非目标

- 不在本计划第一阶段全量清洗线上数据。
- 不引入新的外部接口或改变推栏请求参数。
- 不改变 `match/history` 按 `global_role_id` 拉取对局历史的主流程。
- 不自动合并存在目标 `identity_key` 冲突的记录。
- 不重构与 JJC 身份无关的缓存、排名、前端或 QQ 命令。
- 不把审计脚本改成常驻任务；定期化观察可作为后续计划。
- 不在第一阶段新增落库字段；身份状态字段、冲突集合和审计元数据在后续阶段单独评估。

## 涉及文件

预计新增：

- `src/services/jx3/role_identity_matching.py`
  - 角色身份候选、预期身份、匹配结果、审计分类、身份 key 构造的纯函数/小数据结构。
- `tests/test_role_identity_matching.py`
  - 覆盖字段提取、角色匹配、匹配等级、审计分类和身份 key 规则。

后续阶段按需新增：

- `src/services/jx3/role_identity_service.py`
  - 仅在确实需要跨 repo 编排写入、冲突记录或修复动作时新增；不作为第一阶段必选项。
- `tests/test_role_identity_service.py`
  - 仅在新增 service 后覆盖写入入口、修复动作、冲突不自动合并等业务行为。

预计调整：

- `src/services/jx3/jjc_match_data_sync.py`
  - 复用共享匹配规则，不再内联维护 `person-history` 角色匹配细节。
  - 保持 `extract_identity_from_person_history()` 的函数签名、返回 dict 结构和未传 expected 字段时的旧行为。
- `scripts/audit_jjc_person_history_identity.py`
  - 分阶段复用共享 expected/candidate 提取、强弱匹配、冲突判断、降级 key 和分类规则。
  - 保留现有参数解析、扫描、断点续跑、冲突链追溯、重复身份合并归档和报告输出流程。
- `src/storage/mongo_repos/role_identity_repo.py`
  - 将身份 key 构造逐步复用共享规则；必要时补充受控更新方法。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - 将同步队列 identity_key 构造逐步复用共享规则；必要时补充清理错误 `global_role_id` 和重置同步水位的仓储方法。
- `docs/design-docs/database-design.md`
  - 若新增字段、冲突集合、修复备注字段或索引，必须同步更新。
- `docs/references/runbook.md`
  - 若新增回归命令或治理操作流程，必须同步更新。

## 设计原则

- 先抽纯规则，再改线上调用，最后再考虑写库入口；不要第一步引入大 service。
- 现有行为兼容优先，尤其是 `extract_identity_from_person_history()` 未传 expected 字段时返回首个可用候选的旧行为。
- 匹配规则和审计分类分开表达，避免把“证据等级”和“修复动作”混为一类枚举。
- identity_key 生成最终应只有一个规则来源，repo 可保留轻量封装以兼容返回 `identity_level`。
- 审计脚本不能一次性改成“薄入口”；先替换重复规则，再在后续阶段收敛修复写入。
- 每个阶段都必须能独立验证并可回滚。

## 目标规则模型

### 共享纯模块

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
  - `match_level`
  - `reason`
  - `candidate`
- `IdentityKeyResult`
  - `identity_key`
  - `identity_level`

核心纯函数：

- `normalize_identity_role_name(role_name, server)`
- `extract_expected_identity(doc_or_role)`
- `extract_person_history_candidate(item)`
- `extract_person_history_candidates(payload)`
- `match_role_identity(expected, candidate)`
- `classify_person_history_identity(expected, candidates)`
- `build_identity_key(global_role_id=None, zone=None, role_id=None, server=None, name=None)`
- `build_degraded_identity_key(expected_or_doc)`

### 匹配等级

- `global_verified`
  - 候选 `global_role_id` 与预期 `global_role_id` 一致，并且角色字段匹配。
- `game_verified`
  - `zone + role_id` 完全一致，可确认同一游戏角色。
- `name_verified`
  - `server + normalize_role_name(role_name, server)` 完全一致，可信度低于强身份。
- `candidate_unverified`
  - 有候选身份，但字段不足或不能确认同一角色。
- `conflict`
  - 同一 `person_id/global_role_id` 与当前角色字段明确冲突。
- `unknown`
  - 接口失败、返回为空或证据不足。

### 审计分类

- `confirmed_valid`
  - 当前 `global_role_id` 可被 person-history 中同角色候选确认。
- `confirmed_dirty`
  - 当前 `global_role_id` 明确指向其他角色，且修复目标没有 identity_key 冲突。
- `conflict_needs_manual_merge`
  - 当前记录明确脏，但目标 identity_key 已存在，需要人工确认或走重复身份合并流程。
- `suspected_dirty`
  - `person_id` 下存在候选，但当前 `global_role_id` 没出现，证据不足以自动修复。
- `api_failed`
  - 外部接口失败，不能下结论。
- `unknown`
  - person-history 证据不足。

### identity_key 规则

最终统一为：

1. `global:{global_role_id}`
2. `game:{zone}:{role_id}`
3. `name:{normalized_server}:{normalized_name}`

实施时需要处理当前三处重复规则：

- `src/services/jx3/jjc_match_data_sync.py::build_identity_key`
- `src/storage/mongo_repos/role_identity_repo.py::build_identity_key`
- `src/storage/mongo_repos/jjc_sync_repo.py::_build_identity_key`

收敛方式：

- 阶段 1 先在共享模块提供统一规则和测试。
- 阶段 2/4 逐步让 service 和 repo 调用共享规则。
- `RoleIdentityRepo.build_identity_key()` 可保留兼容函数，内部调用共享规则并返回 `(identity_key, identity_level)`。
- `JjcSyncRepo._build_identity_key()` 可保留私有封装，内部调用共享规则并只返回 `identity_key`。

## 分阶段实施方案

### 阶段 1：抽取共享纯规则，不改变线上行为

目标：

- 新增 `role_identity_matching.py`，把候选字段提取、角色名规范化、强弱匹配、冲突判断、审计分类和 identity_key 构造集中到纯函数。
- 建立测试基线，证明共享规则和当前线上/审计脚本行为一致。
- 不改 Mongo 写入，不改审计脚本主流程，不改线上同步外部行为。

改动范围：

- 新增 `src/services/jx3/role_identity_matching.py`
- 新增 `tests/test_role_identity_matching.py`
- 可在 `jjc_match_data_sync.py` 中保留旧函数作为兼容包装，暂不大规模移动调用。

验收：

- `extract_person_history_candidate()` 兼容字段别名：`role_id/roleId/game_role_id`、`global_role_id/globalRoleId`、`role_name/roleName/name`。
- `normalize_identity_role_name()` 与当前 `normalize_role_name()` 行为一致。
- 强匹配、名称匹配、强身份冲突、字段不足、API 空数据都有测试。
- `build_identity_key()` 覆盖 global/game/name 三层优先级。
- 不产生数据库写入。

验证命令：

```bash
python -m unittest tests.test_role_identity_matching
python -m py_compile src/services/jx3/role_identity_matching.py
```

回滚：

- 删除新增模块和测试即可，不影响线上链路。

### 阶段 2：改造线上同步链路，保持接口兼容

目标：

- 让 `jjc_match_data_sync.py` 复用共享候选匹配规则。
- 保持 `extract_identity_from_person_history()` 的函数签名、返回 dict 结构和旧 fallback 行为。
- 线上同步仍按现有流程：本地身份优先，缺 `global_role_id` 时尝试 person-history，成功后写 `role_identities` 与同步队列。

改动范围：

- `src/services/jx3/jjc_match_data_sync.py`
  - `extract_identity_from_person_history()` 调用共享模块。
  - `_resolve_identity_from_person_history_pages()` 不改变分页、sleep、日志和错误处理。
  - `_upsert_role_identity_from_resolved()` 暂保留现有 repo 写入方式。
- `tests.test_jjc_match_data_sync`
  - 补充未传 expected 字段时仍返回首个可用 person_id 候选的兼容用例。
  - 补充同 `person_id` 多角色不会误回填其他角色 `global_role_id` 的用例。

验收：

- 队列角色缺 `global_role_id` 时，仍能通过正确 person-history 候选补全。
- 对局详情玩家缺 `global_role_id` 时，仍复用同一规则补全。
- person-history 中存在同 person_id 的其他角色时，不回填错误 `global_role_id`。
- 未传 expected 字段时保留旧行为。
- 不新增数据库字段，不调整推栏请求参数。

验证命令：

```bash
python -m unittest tests.test_jjc_match_data_sync
python -m py_compile src/services/jx3/role_identity_matching.py src/services/jx3/jjc_match_data_sync.py
```

回滚：

- 将 `extract_identity_from_person_history()` 恢复为阶段前实现即可。

### 阶段 3：改造审计脚本规则引用，保留执行流

目标：

- 让 `scripts/audit_jjc_person_history_identity.py` 复用共享 expected/candidate 提取、强弱匹配、冲突判断、降级 key 和分类规则。
- 保留现有 CLI、扫描过滤、`--reprocess`、断点续跑、冲突链追溯、重复身份合并归档、报告结构和 `--apply --yes` 保护。
- 不把脚本一次性重写成极薄入口，降低回归风险。

改动范围：

- `scripts/audit_jjc_person_history_identity.py`
  - 替换 `_expected_fields()`、`_candidate_fields()`、`role_fields_match()`、`role_fields_conflict()`、`build_degraded_identity_key()` 的本地实现或改为兼容包装。
  - `classify_identity_doc()` 可先复用共享分类结果，再保留脚本既有报告字段。
  - `build_repair_update()` 与 `build_correct_global_repair_update()` 暂保留，下一阶段再收敛。
- `tests.test_audit_jjc_person_history_identity`
  - 补充共享分类和脚本报告分类一致性用例。

验收：

- dry-run 报告分类与阶段前同样本结果一致，除非计划中明确记录为规则修正。
- `confirmed_dirty`、`conflict_needs_manual_merge`、`suspected_dirty`、`api_failed`、`unknown` 都有测试覆盖。
- `--apply` 未带 `--yes` 仍拒绝写库。
- `--reprocess` 仍可忽略已审计标记。

验证命令：

```bash
python -m unittest tests.test_audit_jjc_person_history_identity
python -m py_compile src/services/jx3/role_identity_matching.py scripts/audit_jjc_person_history_identity.py
```

手工回归：

```bash
python scripts/audit_jjc_person_history_identity.py --limit 20 --dry-run
python scripts/audit_jjc_person_history_identity.py --person-id <person_id> --dry-run
```

回滚：

- 恢复脚本本地规则函数，保留阶段前审计流程。

### 阶段 4：收敛 identity_key 与受控修复写入

目标：

- 让 `role_identity_repo`、`jjc_sync_repo` 的 identity_key 构造复用共享规则。
- 将清理错误 `global_role_id`、降级 identity_key、重置同步水位等写入动作收敛到明确的 repo 方法或轻量 service。
- 只有当单个动作需要同时编排多个 repo 时，才新增 `RoleIdentityService`。

改动范围：

- `src/storage/mongo_repos/role_identity_repo.py`
  - `build_identity_key()` 内部复用共享规则，保留返回 `(identity_key, identity_level)` 的兼容接口。
  - 必要时新增 `clean_mismatched_global_role_id(...)` 或 `apply_identity_repair(...)`。
- `src/storage/mongo_repos/jjc_sync_repo.py`
  - `_build_identity_key()` 内部复用共享规则。
  - 复用或扩展 `reset_role_progress()`，避免脚本直接拼水位字段。
- `scripts/audit_jjc_person_history_identity.py`
  - `--apply --yes` 时优先调用受控 repo/service 方法。
- 可选新增 `src/services/jx3/role_identity_service.py`
  - 仅承载跨 `role_identities` 与 `jjc_sync_role_queue` 的修复编排，不接管简单 upsert。

验收：

- identity_key 三层优先级在 service、role repo、sync repo 中一致。
- 清理错误 `global_role_id` 后，同步队列状态回到 `pending`，水位字段按现有规则重置。
- 目标 identity_key 已存在时仍不自动合并，进入 `conflict_needs_manual_merge` 或既有重复合并流程。
- 修复动作全部保留 `person_history_audit` 记录。

验证命令：

```bash
python -m unittest tests.test_role_identity_matching tests.test_audit_jjc_person_history_identity tests.test_jjc_sync_repo
python -m py_compile src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py scripts/audit_jjc_person_history_identity.py
```

手工回归：

```bash
python scripts/audit_jjc_person_history_identity.py --limit 20 --dry-run
python scripts/audit_jjc_person_history_identity.py --person-id <person_id> --apply --yes
```

回滚：

- repo 封装可恢复为阶段前本地构造；已写入的修复记录保留，不删除线上数据。

### 阶段 5：身份状态与冲突可观测性

目标：

- 在规则稳定后评估是否需要把身份状态、冲突摘要、最后审计时间等信息落库。
- 将“治理观察”从一次性报告扩展为可查询的状态或集合。

候选设计：

- 在 `role_identities` 增加：
  - `identity_status`
  - `identity_conflict`
  - `last_identity_audit_at`
  - `identity_audit_reason`
- 或新增冲突集合，例如 `role_identity_conflicts`：
  - 保存 `identity_key`、`expected`、`candidate`、`category`、`reason`、`created_at`、`resolved_at`。

实施前置条件：

- 阶段 1-4 已完成并验证。
- 明确查询入口、保留周期和是否需要索引。
- 先更新 `docs/design-docs/database-design.md`，再改代码。

验收：

- 新字段或新集合的 schema、索引、写入时机、回滚策略都有文档。
- 旧数据缺字段时不影响线上同步和审计脚本。
- 可通过 dry-run 或只写报告模式验证冲突记录内容。

验证命令：

```bash
python -m unittest tests.test_role_identity_matching tests.test_audit_jjc_person_history_identity
python -m py_compile src/services/jx3/role_identity_matching.py scripts/audit_jjc_person_history_identity.py
```

回滚：

- 代码停止读写新增字段或集合；线上已存在字段保留，不做破坏性删除。

### 阶段 6：数据治理执行与防回流

目标：

- 用统一规则执行可控治理，不一次性全量修复。
- 建立持续防回流路径，确保新写入 `global_role_id` 的入口都经过角色级校验。

执行步骤：

1. dry-run 基线
   - 全量或分批跑审计脚本，保存报告。
   - 统计各分类数量、冲突样本、API 失败比例。
2. 小样本修复
   - 先按 `--person-id`、`--global-role-id` 或 `--limit` 执行小范围 `--apply --yes`。
   - 修复后复跑 dry-run 验证同样本不再误判。
3. 分批修复 confirmed_dirty
   - 只处理明确脏数据。
   - `conflict_needs_manual_merge`、`suspected_dirty` 保持报告或人工处理，不自动合并。
4. 防回流检查
   - 检查所有写入 `global_role_id` 的线上入口是否复用共享规则。
   - 新增身份来源时必须补共享规则测试。
5. 运行手册更新
   - 将 dry-run、单样本 apply、回滚观察方式写入 `docs/references/runbook.md`。

验收：

- 治理报告可复现，修复前后分类数量变化可解释。
- 线上同步不会继续把同 `person_id` 的其他角色 `global_role_id` 回填到当前角色。
- 修复后的同步队列能够重新领取并按正确 `global_role_id` 同步。
- 冲突与疑似脏记录有明确人工处理清单。

回滚：

- 单次修复提交前保留报告；如发现误修，按 `person_history_audit.original_*` 信息反向修复。
- 代码回滚时保留已审计标记和修复记录，不删除历史治理痕迹。

## 总体验证方案

自动化验证：

```bash
python -m unittest tests.test_role_identity_matching
python -m unittest tests.test_jjc_match_data_sync
python -m unittest tests.test_audit_jjc_person_history_identity
python -m unittest tests.test_jjc_sync_repo
python -m py_compile src/services/jx3/role_identity_matching.py src/services/jx3/jjc_match_data_sync.py scripts/audit_jjc_person_history_identity.py src/storage/mongo_repos/role_identity_repo.py src/storage/mongo_repos/jjc_sync_repo.py
```

重点用例：

- 同一输入下，线上同步和审计脚本分类结果一致。
- `zone + role_id` 匹配时返回 `game_verified`。
- `server + normalize_role_name` 匹配时返回 `name_verified`。
- 当前 `global_role_id` 与角色字段一致时返回 `confirmed_valid`。
- 当前 `global_role_id` 与角色字段冲突且找到正确候选时返回 `confirmed_dirty` 或 `conflict_needs_manual_merge`。
- `person_id` 相同但角色字段冲突时拒绝补全或进入冲突分类。
- 字段不足时返回 `unknown/candidate_unverified`，不写入 `global_role_id`。
- `confirmed_dirty` 修复只清空或替换错误 `global_role_id`，不删除角色记录。
- `identity_key` 冲突时不自动合并。
- `extract_identity_from_person_history()` 未传 expected 字段时保持旧 fallback 行为。
- `--apply` 未带 `--yes` 时拒绝写库。

手工回归：

- 使用一个同 `person_id` 多角色样本，确认同步链路不会回填其他角色的 `global_role_id`。
- 使用一个 person-history 正确角色样本，确认仍能补全身份。
- 使用审计脚本 dry-run 小样本，确认报告分类与共享规则一致。
- 小范围 apply 后，确认队列水位被重置，后续同步不会继续使用错误 `global_role_id`。
- 若新增落库字段或冲突集合，确认旧数据缺字段时 API、同步任务和审计脚本都能正常运行。

## 风险与回滚

- 风险：抽规则时改变已有边界行为，导致原本可补全的身份被保守拒绝。
  - 缓解：阶段 1 先做纯规则测试，阶段 2 明确覆盖旧 fallback 行为。
- 风险：线上同步和审计脚本对“匹配等级”和“审计分类”理解混淆。
  - 缓解：在共享模块中分开定义 match result 与 audit classification。
- 风险：迁移到共享模块过程中遗漏字段别名。
  - 缓解：保留现有字段提取兼容，如 `role_id/roleId/game_role_id`、`global_role_id/globalRoleId`、`role_name/roleName/name`。
- 风险：修复入口过早抽象，影响当前审计脚本可读性和稳定性。
  - 缓解：前三阶段只抽纯规则和兼容调用，第四阶段再收敛写库入口。
- 风险：identity_key 规则收敛时影响已有 repo 查询。
  - 缓解：repo 保留原函数签名，内部复用共享规则；迁移前后用单测锁定 key 输出。
- 风险：新增身份状态字段后数据库文档含义不清。
  - 缓解：第五阶段单独评估并先更新数据库设计文档。
- 回滚：
  - 阶段 1 可删除新增模块和测试。
  - 阶段 2 可恢复 `extract_identity_from_person_history()` 旧实现。
  - 阶段 3 可恢复审计脚本本地规则函数。
  - 阶段 4 可回退 repo/service 封装，保留已写入审计记录。
  - 阶段 5/6 回滚代码时停止读写新增字段或集合，不做破坏性删除。
