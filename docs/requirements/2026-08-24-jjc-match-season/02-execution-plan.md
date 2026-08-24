# JJC 对局赛季归属与查询隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让角色的 JJC 已同步对局列表只显示 `config.CURRENT_SEASON`，并把当前 Mongo 投影按当前赛季开始时间回填。

**Architecture:** 在 `jjc_match_participants` 这个列表读取模型写入可空 `season_id`，而不重复修改完整详情事实表。投影服务接收赛季配置并决定每场对局是否属于当前赛季；读取 service 将当前赛季传给仓储作精确匹配。独立脚本只更新投影表，默认 dry-run，显式确认后才写当前 Mongo。

**Tech Stack:** Python 3.9、NoneBot、Motor/MongoDB、unittest。

---

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

完成后，`GET /api/jjc/ranking-stats/synced-role-matches` 及对应页面只显示当前配置赛季的 3v3 对局。未来赛季只要同步修改 `config.py` 的 `CURRENT_SEASON` 与 `CURRENT_SEASON_START`，后续生成的投影会被标记为新赛季，旧赛季投影自然不再命中列表。历史详情和投影不删除。

## Progress

- [x] 完成需求和方案确认
- [x] 建立赛季归属的单元测试并验证 RED
- [x] 实现投影写入与当前赛季列表过滤
- [x] 增加 Mongo 索引、回填脚本和数据库文档
- [ ] 执行 Mongo dry-run、apply 与回填核验（当前环境未得到可核验输出）
- [ ] 完成自动化验证、手工冒烟和 review
- [ ] 填写测试、review、验收记录

## Surprises & Discoveries

- 当前 `jjc_match_participants` 的 `idx_global_available_time` 已按 `global_id`、展示条件和时间排序；赛季过滤需要新索引以保持该角色分页查询的等值前缀。
- 同步队列已有 `season_id`，但它是角色同步水位状态，不能作为玩家对局列表的筛选来源。
- 当前运行环境没有可见的本机 Mongo 监听端口。两次已授权的 dry-run 都没有返回统计或错误输出，因此没有执行 `--apply`。

## Decision Log

- 2026-08-24：用户选择在玩家投影持久化 `season_id`，而不是只在查询时用赛季起点过滤。
- 2026-08-24：不向 `jjc_match_detail` 添加赛季字段；它是完整详情事实，当前列表的查询边界应在 `jjc_match_participants` 读取模型中实现。
- 2026-08-24：历史或缺少 `match_time` 的投影回填为 `season_id: null`，而不是推测历史赛季名称；这保证新赛季不会泄漏历史记录。
- 2026-08-24：回填脚本在读取投影前显式执行 Mongo `ping`，让连接失败在扫描前暴露；实际回填只在 dry-run 有可核验输出后执行。
- 2026-08-24：代码审查要求读取侧同时精确匹配 `season_id` 与 `match_time >= season_start_time`。这使错误标记的历史行和无时间行也无法进入当前赛季列表。

## Outcomes & Retrospective

实现完成后填写实际回填统计、测试结果、偏离计划之处和遗留风险。

## Context and Orientation

- `config.py` 提供 `CURRENT_SEASON` 与 `CURRENT_SEASON_START`，日期语义为北京时间零点。
- `src/storage/mongo_repos/jjc_match_participant_repo.py` 的纯函数 `build_participants_from_match_detail()` 生成投影，`list_local_3v3_matches_by_global_id()` 负责分页读取。
- `src/services/jx3/match_detail_participant_projection.py` 是写入编排边界；它应接收赛季配置而不是让 storage 直接 import `config`。
- `src/services/jx3/jjc_ranking_inspect.py` 是已同步对局读取用例；它将当前赛季传给 repo。
- `src/services/jx3/singletons.py` 是所有运行期依赖与配置的装配点。
- `scripts/backfill_jjc_match_participants.py` 已有安全的 Mongo URI 解析和参数风格，可复用其模式，但本需求新增专用赛季回填脚本，避免重建参与者投影时意外清除既有行。

## Plan of Work

先以纯函数和仓储查询测试定义赛季归属，再最小化扩展投影 service、读取 service 和 singleton 注入。然后创建安全、幂等的投影字段回填脚本和索引，并同步数据库/运行文档。代码验证通过后，先对当前 Mongo 执行 dry-run 并核对输出，再取得已批准的 `--apply --yes` 命令结果，最后运行核验和 API 冒烟。

## Concrete Steps

### Task 1: 用测试锁定投影赛季归属与列表条件

**Files:**

- Modify: `tests/test_jjc_match_participant_repo.py`
- Modify: `tests/test_jjc_ranking_inspect.py`

- [ ] **Step 1: 写投影构建的失败测试**

在 `TestJjcMatchParticipantRepoBuild` 添加三个测试，调用新增的 `current_season` 与 `season_start_time` 参数：

```python
def test_assigns_current_season_to_match_at_or_after_boundary(self) -> None:
    rows = JjcMatchParticipantRepo.build_participants_from_match_detail(
        1001, _payload([_player("g1"), _player("g2"), _player("g3")], [_player("g4"), _player("g5"), _player("g6")], match_time=1777228800),
        current_season="新赛季", season_start_time=1777228800,
    )
    self.assertTrue(all(row["season_id"] == "新赛季" for row in rows))

def test_leaves_preseason_and_missing_time_unassigned(self) -> None:
    for match_time in (1777228799, None):
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
            match_time=match_time,
        )
        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(
            1001, payload, current_season="新赛季", season_start_time=1777228800,
        )
        self.assertTrue(all(row["season_id"] is None for row in rows))
```

并在 inspect service 测试中断言 `get_synced_role_matches()` 调用 repo 时携带 `season_id="暗影千机"`。

- [ ] **Step 2: 运行 RED 验证**

Run: `python -m unittest tests.test_jjc_match_participant_repo tests.test_jjc_ranking_inspect`

Expected: 新测试因 `build_participants_from_match_detail()` 和列表调用尚不接受赛季参数而失败；既有测试通过。

- [ ] **Step 3: 写最小实现使测试通过**

在 `JjcMatchParticipantRepo.build_participants_from_match_detail()` 增加可选参数：

```python
current_season: Optional[str] = None,
season_start_time: Optional[int] = None,
```

在提取完 `match_time` 后计算：

```python
season_id = None
if current_season and season_start_time is not None and match_time is not None:
    if match_time >= season_start_time:
        season_id = current_season
```

并将 `"season_id": season_id` 写入每条 participant。保持未传新参数的既有调用可用。

为 `list_local_3v3_matches_by_global_id()` 增加必填关键字参数 `season_id: str`，并把查询固定为：

```python
query = {
    "global_id": target_global_id,
    "season_id": target_season_id,
    "match_type": 3,
    "detail_available": True,
}
```

- [ ] **Step 4: 运行 GREEN 验证**

Run: `python -m unittest tests.test_jjc_match_participant_repo tests.test_jjc_ranking_inspect`

Expected: 全部通过。

- [ ] **Step 5: 提交这一独立测试与实现单元**

```bash
git add tests/test_jjc_match_participant_repo.py tests/test_jjc_ranking_inspect.py src/storage/mongo_repos/jjc_match_participant_repo.py
git commit -m "feat: add season to JJC participant projection"
```

### Task 2: 从装配层注入赛季并过滤已同步对局查询

**Files:**

- Modify: `src/services/jx3/match_detail_participant_projection.py`
- Modify: `src/services/jx3/jjc_ranking_inspect.py`
- Modify: `src/services/jx3/singletons.py`
- Modify: `tests/test_jjc_ranking_inspect.py`

- [ ] **Step 1: 写 service 传参的失败测试**

在 inspect service 的工厂中显式传入 `current_season="暗影千机"`，调用 `get_synced_role_matches()` 后断言 fake repo 接到 `season_id`。另为 participant projection fake repo 断言 `build_participants_from_match_detail()` 接到 `current_season` 与北京时间 Unix 秒起点。

- [ ] **Step 2: 运行 RED 验证**

Run: `python -m unittest tests.test_jjc_ranking_inspect`

Expected: fake repo 调用缺少 `season_id` 或 projection 调用缺少赛季参数而失败。

- [ ] **Step 3: 实现最小的依赖注入与转发**

给 `MatchDetailParticipantProjectionService` 新增冻结 dataclass 字段：

```python
current_season: Optional[str] = None
season_start_time: Optional[int] = None
```

并在 `project_payload()` 转发给 `build_participants_from_match_detail()`。给 `JjcRankingInspectService` 新增 `current_season: str = ""`，在 `get_synced_role_matches()` 传入 `season_id=self.current_season`。在 `singletons.py` 使用现有同步服务同样的北京时间解析规则，从 `cfg.CURRENT_SEASON_START` 生成整数时间戳，并将两个配置值注入两个 service。

- [ ] **Step 4: 运行 GREEN 验证与静态检查**

Run: `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_match_participant_repo && python -m py_compile src/services/jx3/match_detail_participant_projection.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/singletons.py src/storage/mongo_repos/jjc_match_participant_repo.py`

Expected: 全部通过，且 Python 3.9 兼容编译无报错。

- [ ] **Step 5: 提交查询隔离链路**

```bash
git add src/services/jx3/match_detail_participant_projection.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/singletons.py tests/test_jjc_ranking_inspect.py
git commit -m "feat: filter synced JJC matches by season"
```

### Task 3: 添加索引与安全的 Mongo 赛季回填工具

**Files:**

- Modify: `src/infra/mongo.py`
- Create: `scripts/backfill_jjc_match_participant_season.py`
- Create: `tests/test_backfill_jjc_match_participant_season.py`

- [ ] **Step 1: 写回填分类的失败测试**

为脚本中纯函数 `build_season_update(match_time, current_season, season_start_time)` 编写测试：边界时刻和之后返回 `{"$set": {"season_id": current_season}}`；赛季前或无时间返回 `{"$set": {"season_id": None}}`。测试 `--apply` 未同时传 `--yes` 时退出，默认参数进入 dry-run。

- [ ] **Step 2: 运行 RED 验证**

Run: `python -m unittest tests.test_backfill_jjc_match_participant_season`

Expected: 因脚本模块和函数不存在而失败。

- [ ] **Step 3: 实现回填脚本和索引**

脚本复用现有脚本的 URI/数据库解析模式，直接扫描 `jjc_match_participants`，每批按 `match_id`、`global_id` 和 `match_time` 计算更新；dry-run 只计数，`--apply --yes` 使用 `bulk_write` 批量写入 `UpdateOne(filter_doc, update_doc)` 操作。其核心分类函数为：

```python
def build_season_update(match_time, current_season, season_start_time):
    if match_time is not None and match_time >= season_start_time:
        return {"$set": {"season_id": current_season}}
    return {"$set": {"season_id": None}}
```

脚本从 `config` 读取当前配置；支持 `--mongo-uri`、`--db-name`、`--batch-size`、`--dry-run`、`--apply`、`--yes` 和 `--verify-only`，输出总扫描量、当前赛季行数、未归属行数、写入量、失败数。禁止默认写库。

在 `_ensure_indexes()` 加入：

```python
await _safe_index(
    "jjc_match_participants",
    [("global_id", 1), ("season_id", 1), ("match_type", 1), ("detail_available", 1), ("match_time", -1), ("match_id", -1)],
    name="idx_global_season_available_time",
)
```

- [ ] **Step 4: 运行 GREEN 验证与脚本帮助检查**

Run: `python -m unittest tests.test_backfill_jjc_match_participant_season && python scripts/backfill_jjc_match_participant_season.py --help && python -m py_compile scripts/backfill_jjc_match_participant_season.py src/infra/mongo.py`

Expected: 单测通过，帮助文本列出 dry-run、apply、yes 和 verify-only。

- [ ] **Step 5: 提交迁移工具和索引**

```bash
git add src/infra/mongo.py scripts/backfill_jjc_match_participant_season.py tests/test_backfill_jjc_match_participant_season.py
git commit -m "feat: add JJC participant season backfill"
```

### Task 4: 同步文档并执行受控回填与核验

**Files:**

- Modify: `docs/design-docs/database-design.md`
- Modify: `docs/references/runbook.md`
- Modify: `docs/requirements/2026-08-24-jjc-match-season/02-execution-plan.md`
- Modify: `docs/requirements/2026-08-24-jjc-match-season/03-test-plan.md`
- Modify: `docs/requirements/2026-08-24-jjc-match-season/04-review.md`
- Modify: `docs/requirements/2026-08-24-jjc-match-season/05-acceptance.md`

- [ ] **Step 1: 记录数据契约和回填命令**

在数据库设计中为 `jjc_match_participants` 增加 `season_id` 字段和 `idx_global_season_available_time` 索引；在 runbook 写明新赛季更新两个配置后，先运行：

```bash
python scripts/backfill_jjc_match_participant_season.py --dry-run
```

核对输出后才运行：

```bash
python scripts/backfill_jjc_match_participant_season.py --apply --yes
python scripts/backfill_jjc_match_participant_season.py --verify-only
```

- [ ] **Step 2: 跑全量离线验证**

Run: `python -m unittest tests.test_jjc_match_participant_repo tests.test_jjc_ranking_inspect tests.test_backfill_jjc_match_participant_season tests.test_jjc_match_detail_hydration`

Expected: 全部通过；不访问 Mongo。

- [ ] **Step 3: 对当前 Mongo 运行 dry-run 并人工核对**

Run: `python scripts/backfill_jjc_match_participant_season.py --dry-run`

Expected: 只输出统计且不写库；当前赛季名称、开始日期、扫描行数、可标记数和无归属数符合样本对局时间。

- [ ] **Step 4: 执行用户授权的回填并核验**

Run: `python scripts/backfill_jjc_match_participant_season.py --apply --yes && python scripts/backfill_jjc_match_participant_season.py --verify-only`

Expected: apply 输出写入统计且失败数为 0；verify-only 显示无不一致记录。该步骤仅在用户的“回填现在 Mongo 数据”授权范围内执行，且以真实命令输出为准。

- [ ] **Step 5: API 冒烟、review、验收并提交文档**

确认当前赛季角色的页面只显示 `season_id == CURRENT_SEASON` 的记录；任选一条旧赛季 `global_id` 记录确认不出现在列表。填写测试、review、验收文档，并执行：

```bash
git add docs/design-docs/database-design.md docs/references/runbook.md docs/requirements/2026-08-24-jjc-match-season/
git commit -m "docs: record JJC match season rollout"
```

## Validation and Acceptance

- 单元测试证明赛季边界、赛季前记录、无时间记录、投影写入、service 查询参数，以及 Mongo 查询的赛季开始时间条件均正确。
- `py_compile` 覆盖改动过的运行时模块和回填脚本，确认 Python 3.9 兼容。
- Mongo 操作按“dry-run → 人工核对 → `--apply --yes` → `--verify-only`”顺序执行；不跳过 dry-run。
- API 回归使用已有 `/api/jjc/ranking-stats/synced-role-matches` 参数，不新增客户端参数或改变响应格式。
- 回滚时恢复前一版应用代码即可恢复跨赛季读取；回填的新增 `season_id` 不破坏历史详情。字段保留不会影响旧版本，且本次不提供自动清除字段的回滚操作。
