# JJC 本地收录角色对局查询索引优化与参与者投影表计划

## 2026-05-29 修订：固定读取参与者投影表

后续超时排查中已移除 `JJC_MATCH_PARTICIPANTS_READ_MODE` 运行时开关，`GET /api/jjc/ranking-stats/synced-role-matches` 当前固定读取 `jjc_match_participants` 投影表，不再通过 `off/shadow/on` 切换，也不再在投影查询异常时 fallback 到 `jjc_match_detail` 详情扫描。

本文件下方关于 `JJC_MATCH_PARTICIPANTS_READ_MODE`、`off/shadow/on`、通过切回 `off` 回滚的内容仅保留为历史计划记录，不代表当前实现。当前回滚方式是代码回滚到详情查询路径，或修复/回填 `jjc_match_participants` 投影数据。

## 附加变更：回填脚本批次日志

### 目标

- 为 `scripts/backfill_jjc_match_participants.py` 增加每个批次的 stderr 日志。
- 日志输出批次编号、批次文档数、`match_id` 范围、处理模式、批次增量统计和累计统计。
- 不改变回填、校验、dry-run、apply 的业务逻辑和写库语义。

### 变更文件

- `scripts/backfill_jjc_match_participants.py`
  - 在 `run()` 中对每次 `process_batch()` 调用增加统一批次日志包装。
  - 保留最终 JSON 汇总输出。

### 验证

- 执行：
  ```bash
  python -m py_compile scripts/backfill_jjc_match_participants.py
  ```

## 背景

`GET /api/jjc/ranking-stats/synced-role-matches` 当前通过 `role_identities` 解析角色后，按 `identity.global_id` 查询 `jjc_match_detail.data.detail.team*.players_info.global_id`，再与 `jjc_sync_match_seen.status='detail_saved'` 做交集过滤，最后在 Python 内存中排序分页。

产品语义调整为“本地已收录可展示对局”：只要 `jjc_match_detail` 中存在当前有效详情，且详情里玩家 `global_id` 命中目标角色，就可以在对局页面展示；`jjc_sync_match_seen` 只补充同步状态，不再作为展示门槛。当前接口路径暂保持不变，后续前端文案应从“已同步对局”收敛为“本地已收录对局”。

现有 `jjc_match_detail` 索引覆盖了 `match_id`、`data.detail.match_time`、按服务器与角色名查玩家、以及 `data.replay.data.players.*`，但没有覆盖当前接口真正使用的 `players_info.global_id` 查询路径。随着 `jjc_match_detail` 增长，该接口容易退化为扫描大详情集合。

## 阶段 1：补充最小索引

### 目标

- 为 `jjc_match_detail.data.detail.team1.players_info.global_id` 和 `team2` 对应字段补普通索引。
- 不改变接口响应结构，不改变查询逻辑，不新增集合。
- 通过 Mongo 初始化的 `_ensure_indexes()` 幂等创建索引。

### 变更文件

- `src/infra/mongo.py`
  - 在 `jjc_match_detail` 索引初始化段新增：
    - `idx_detail_team1_player_global_id`
    - `idx_detail_team2_player_global_id`
- `docs/design-docs/database-design.md`
  - 同步记录新增索引。

### 验证

- 执行：
  ```bash
  python -m py_compile src/infra/mongo.py
  ```
- 线上/测试环境启动后观察 Mongo index 创建日志。
- 对慢接口使用 `explain` 验证查询不再走 `COLLSCAN`：
  ```javascript
  db.jjc_match_detail.find({
    "data.unavailable": {"$ne": true},
    "$or": [
      {"data.detail.team1.players_info.global_id": "<global_id>"},
      {"data.detail.team2.players_info.global_id": "<global_id>"}
    ]
  }).explain("executionStats")
  ```

## 阶段 2：参与者投影表方案

### 统一业务语义

本阶段统一 `GET /api/jjc/ranking-stats/synced-role-matches` 的业务语义为“本地已收录可展示对局”：展示门槛只取决于 `jjc_match_detail` 中是否存在当前有效详情，且详情玩家里能用 `global_id` 命中目标角色；`jjc_sync_match_seen` 只补充同步状态，不再决定是否展示。

因此 `off`、`shadow`、`on` 三种读取模式必须使用同一过滤语义。`off` 只能表示“不读 `jjc_match_participants`，直接查 `jjc_match_detail`”，不能继续保留 `jjc_sync_match_seen.status='detail_saved'` 作为展示门槛。

### 触发条件

满足任一条件时进入实现：

- `jjc_match_detail` 超过 10 万且接口 p95 仍高于 1 秒。
- 热门角色单次命中对局超过 500 场，Python 侧过滤排序仍明显耗时。
- `explain.executionStats.totalDocsExamined / nReturned > 100`。
- 接口请求频率上升，详情大文档读取成为 Mongo 或应用 CPU 热点。

### 新集合

集合名：`jjc_match_participants`

用途：保存每场 3v3 对局的玩家级轻量投影，用于按角色稳定身份快速分页查询本地已收录可展示对局列表。每场对局最多 6 条。

本集合是“列表查询读取模型”，不要和现有 `MatchDetailIdentityProjectionService` 混淆：

- `src/services/jx3/match_detail_identity_projection.py` 负责把详情玩家身份投影到 `role_identities` 和同步队列，解决身份治理和入队关联；该服务在 `singletons.py` 中以 `match_detail_projection_service` 注入多个 JJC service。
- 新增的 `jjc_match_participants` 只服务 `/ranking-stats/synced-role-matches` 这类按玩家查本地对局列表的读取路径。
- 两者可以在同一个详情保存流程后被调用，但职责、集合和测试必须分开。新增参与者投影不得复用 `match_detail_projection_service` 变量名，也不得让 `MatchDetailIdentityProjectionService` 写 `jjc_match_participants`。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | MongoDB 自动主键 |
| `match_id` | int | 对局 ID |
| `global_id` | string | replay 稳定角色 ID，对应 `role_identities.global_id`；只写非空值 |
| `identity_id` | ObjectId/null | 写入时可解析到的 `role_identities._id`，只作冗余加速与诊断 |
| `identity_key` | string/null | 写入时可解析到的身份 key |
| `source_identity_id` | ObjectId/null | `jjc_sync_match_seen.source_identity_id` 冗余，用于诊断 |
| `source_identity_key` | string/null | `jjc_sync_match_seen.source_identity_key` 冗余，用于诊断 |
| `sync_status` | string | 同步状态冗余；无 `jjc_sync_match_seen` 时固定为 `not_synced` |
| `detail_available` | bool | 当前 `jjc_match_detail` 是否存在可展示详情；接口只读取 `true` |
| `detail_source` | string | 详情来源，如 `sync_worker`、`ranking_detail`、`warmup`、`manual`、`unknown` |
| `server` | string/null | 对局详情中的服务器 |
| `role_name` | string/null | 对局详情中的原始展示名或规范化名 |
| `team_key` | string | `team1` 或 `team2` |
| `won` | bool | 所在队伍是否获胜 |
| `kungfu` | string/null | 当前场心法 |
| `match_type` | int/null | 对局类型，3 表示 3v3 |
| `match_time` | int/null | 对局时间 |
| `start_time` | int/null | 开始时间 |
| `duration` | int/null | 时长 |
| `avg_grade` | int/null | 平均段位/分段 |
| `total_mmr` | int/null | 当前场总评分 |
| `mmr_delta` | int/null | 当前场评分变化 |
| `mvp` | bool | 是否 MVP |
| `detail_saved_at` | float/null | 详情保存时间 |
| `cached_at` | float/null | `jjc_match_detail` 缓存时间 |
| `updated_at` | float | 投影更新时间 |

建议索引：

| 索引名 | 字段 | 约束 |
|---|---|---|
| `idx_match_global_id` | `[("match_id", 1), ("global_id", 1)]` | unique |
| `idx_global_available_time` | `[("global_id", 1), ("match_type", 1), ("detail_available", 1), ("match_time", -1), ("match_id", -1)]` | 普通复合索引 |
| `idx_match_id` | `[("match_id", 1)]` | 普通索引 |

### 写入路径

#### 新增 `JjcMatchParticipantRepo`

新增 `src/storage/mongo_repos/jjc_match_participant_repo.py`，提供：

- `build_participants_from_match_detail(match_id, cached_at, detail, *, seen_doc=None, detail_source=”unknown”, identity_id=None, identity_key=None)` → `List[Dict]`：纯函数，从可用详情和可选 seen 文档构造玩家投影列表。`identity_id`/`identity_key` 为外部可选传入（第一版不解析 `role_identity_repo`），未传入时对应字段写 `null`。`server`/`role_name` 缺失时写 `null`（不阻塞写入）。
- `replace_match_participants(match_id, participants)`：按 `match_id` 替换当前对局全部投影。实现优先采用“upsert 新 `global_id` 集合，再删除本 `match_id` 下不在新集合内的旧行”，降低 `on` 模式读到短暂空结果的概率；如果第一版使用 `delete_many + insert_many`，必须记录该短暂空窗风险，并在 insert 失败时记 warning 交由后续保存重试或回填修复。
- `clear_match_participants(match_id)`：删除该 `match_id` 的全部投影行，详情不可用或需要回滚时使用。
- `refresh_sync_status(match_id)`：读取 `jjc_sync_match_seen` 当前文档，更新该 `match_id` 所有投影行的 `sync_status`、`detail_saved_at`、`source_identity_id`、`source_identity_key` 等 sync 冗余字段。只更新已存在的投影行，不新增。
- `list_local_3v3_matches_by_global_id(global_id, page, page_size)` → `Dict[str, Any]`：投影表读取入口，返回 `items/total/page/page_size/has_more`。

#### 新增 `MatchDetailParticipantProjectionService`

文件：`src/services/jx3/match_detail_participant_projection.py`。

新增参与者投影 service，负责在业务层把已保存的 `jjc_match_detail` 转成 `jjc_match_participants`。它可以依赖 `JjcMatchParticipantRepo` 和 `JjcSyncRepo`；`JjcInspectRepo` 保持纯存储职责，不在 `save_match_detail()` 内部依赖其他 repo 或 service。

建议接口：

```python
@dataclass(frozen=True)
class MatchDetailParticipantProjectionService:
    participant_repo: Any
    sync_repo: Any = None

    async def project_saved_match_detail(self, *, match_id: Any, payload: dict, detail_source: str) -> None:
        ...

    async def clear_for_unavailable_detail(self, *, match_id: Any) -> None:
        ...

    async def refresh_sync_status(self, *, match_id: Any) -> None:
        ...
```

关键点：

- `project_saved_match_detail()` 从传入 payload 中读取 `cached_at`、`data.detail` 或直接的 `detail`，必要时按 `match_id` 读取 seen 文档补充 `sync_status/detail_saved_at/source_identity_*`，再调用 `replace_match_participants()`。
- `clear_for_unavailable_detail()` 调用 `clear_match_participants(match_id)`。
- `refresh_sync_status()` 只更新已有投影行的 sync 冗余字段，不新增投影行。
- 投影失败只记 warning，不回滚 `jjc_match_detail` 已保存的数据；后续回填可修复。
- `detail_source` 由调用方显式传入，不修改 `JjcInspectRepo.save_match_detail()` 签名，也不把 `_detail_source` 塞进 payload。

#### `singletons.py` 装配变更

文件 `src/services/jx3/singletons.py`。

新增 `JjcMatchParticipantRepo` 和 `MatchDetailParticipantProjectionService` 共享实例，并注入需要保存详情的 service：

```python
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo
from src.services.jx3.match_detail_participant_projection import MatchDetailParticipantProjectionService

match_participant_repo = JjcMatchParticipantRepo()
match_detail_participant_projection_service = MatchDetailParticipantProjectionService(
    participant_repo=match_participant_repo,
    sync_repo=jjc_sync_repo,
)
```

现有 `match_detail_projection_service` 变量名继续保留给 `MatchDetailIdentityProjectionService`，不要复用给参与者投影。参与者投影建议使用 `match_detail_participant_projection_service` 这类明确名称。

读路径还需要把 `match_participant_repo` 注入 `JjcInspectRepo`，仅用于 `list_saved_local_3v3_matches_for_identity()` 在 `shadow/on` 模式下查询投影表：

```python
jjc_inspect_cache_repo = JjcInspectRepo(participant_repo=match_participant_repo)
```

该注入只用于读委托，不允许 `JjcInspectRepo.save_match_detail()` 调用参与者投影。若测试或临时实例未传 `participant_repo`，`shadow/on` 应按计划 fallback 到直接详情查询并记录 warning。

#### 业务保存路径接入

参与者投影不挂在 `JjcInspectRepo.save_match_detail()` 内部，避免 storage 层反向依赖其他 repo/service。所有当前业务层保存详情的入口必须在 `save_match_detail()` 成功返回后显式调用参与者投影 service：

1. `src/services/jx3/jjc_ranking_inspect.py`
   - `get_match_detail()` 缓存命中后补 replay 并保存详情：保存成功后调用 `project_saved_match_detail(..., detail_source="ranking_detail")`。
   - `get_match_detail()` 缓存未命中实时获取并保存详情：保存成功后调用 `project_saved_match_detail(..., detail_source="ranking_detail")`。
   - `no data found` 或保存 `data.unavailable=true`：保存成功后调用 `clear_for_unavailable_detail(match_id=...)`。
2. `src/services/jx3/jjc_ranking.py`
   - `_warmup_inspect_cache_from_kungfu_detail()` 保存详情成功后调用 `project_saved_match_detail(..., detail_source="warmup")`。
   - 该 service 当前通过 `_inspect_cache()` 创建 `JjcInspectRepo()`，不需要为了参与者投影改造 repo 注入；只需要给 `JjcRankingService` 注入 `match_detail_participant_projection_service`。
3. `src/services/jx3/jjc_match_data_sync.py`
   - 同步 worker 保存详情成功后可先生成基础参与者投影，`detail_source="sync_worker"`。
   - `JjcSyncRepo.mark_match_detail_saved()` 返回 `marked=True` 后，必须调用 `refresh_sync_status(match_id=...)` 刷新投影中的 sync 冗余；刷新失败只记 warning，不影响展示。
4. 后续新增任何直接调用 `save_match_detail()` 的业务入口，必须同步接入参与者投影；脚本或手工修复若绕过 service 直接写详情，需在写后调用参与者投影 service 或执行回填脚本。

#### 写入规则总结

1. `jjc_match_detail` 是展示主事实：只有存在 `data.detail` 且 `data.unavailable != true` 才生成 `detail_available=true` 的投影。
2. `jjc_sync_match_seen` 仅作同步状态补充；无 seen 文档也可生成可展示投影。
3. 同步 worker 在 `mark_match_detail_saved()` 后调用 `refresh_sync_status()` 刷新 sync 冗余；失败只记日志。
4. 保存 `data.unavailable=true` 后调用 `clear_for_unavailable_detail(match_id)`。
5. 每个 `match_id` 投影采用 replace 语义：优先 upsert 当前玩家集合，再删除该 `match_id` 下不在当前集合内的旧行；如果第一版使用 `delete_many + insert_many`，必须记录短暂空窗风险。
6. 只写 `global_id` 非空玩家。
7. 首版优先按 `basic_info.match_type/detail.match_type/detail.pvp_type` 判断 3v3；若字段缺失但 `team1/team2.players_info` 均存在且两队玩家总数为 6，则推断为 3v3，写入 `match_type=3`、`match_type_inferred=true`。直接详情查询路径也同步使用同一判断逻辑，确保 `off/shadow/on` 三种模式语义一致。无法确认 3v3 的详情不写可读投影，并统计 `skipped_missing_match_type`。
8. 投影写入失败不回滚 `jjc_match_detail` 保存，只记 warning，后续回填可补。

### 身份解析策略（第一版）

**第一版 participant_repo 不解析 `role_identity_repo`**，避免新增 repo 依赖和增加写入阶段复杂度。

- `identity_id`：写入投影时写 `null`。后续优化可在写入或回填阶段按 `global_id` 反查 `role_identities` 回填。
- `identity_key`：写入投影时写 `null` 或来自 `build_participants_from_match_detail()` 的可选外部参数（如调用方已知 identity_key）。
- 查询路径只依赖 `global_id + match_type + detail_available`，不依赖 `identity_id`/`identity_key`，因此 `identity_id`/`identity_key` 为 `null` 不影响接口可用性。
- `source_identity_id`/`source_identity_key`：来自 `jjc_sync_match_seen` 文档的冗余，无 seen 文档时写 `null`。
- 后续优化（非本计划范围）可补：在投影写入或回填时查询 `role_identities` 回填 `identity_id`，使投影可支持按 `identity_id` 聚合查询或关联 `role_identities` 做展示增强。

### 查询切换

#### 配置

在 `config.py` 增加配置项并加入 `RUNTIME_CONFIG_KEYS`：

```python
# config.py 全局区
JJC_MATCH_PARTICIPANTS_READ_MODE = os.getenv("JJC_MATCH_PARTICIPANTS_READ_MODE", "off")

# RUNTIME_CONFIG_KEYS 字典内新增
RUNTIME_CONFIG_KEYS = {
    # ... 现有项 ...
    "JJC_MATCH_PARTICIPANTS_READ_MODE": str,   # 新增
}
```

配置项名：`JJC_MATCH_PARTICIPANTS_READ_MODE`，入 `RUNTIME_CONFIG_KEYS`（类型 `str`），允许通过 `runtime_config.json` 覆盖。读取时统一规范化为小写；非法值记录 warning 并按 `off` 处理。

配置取值：
- `off`：直接查询 `jjc_match_detail`，不读投影表；使用新业务语义，不再以 `jjc_sync_match_seen.status='detail_saved'` 作为展示门槛。
- `shadow`：接口返回直接查询 `jjc_match_detail` 的结果，同时读取投影结果并记录 `match_id` 集合差异、排序差异、`total` 差异、单行字段差异与耗时；投影异常只记录日志。默认只记录有差异或异常的请求（避免日志噪声）。
- `on`：主读投影；仅在投影查询异常或集合/索引不可用时 fallback 到直接详情查询。投影返回空结果不 fallback。

#### 查询委托：`JjcInspectRepo.list_saved_local_3v3_matches_for_identity()`

文件 `src/storage/mongo_repos/jjc_inspect_repo.py`，方法 `list_saved_local_3v3_matches_for_identity()`。

在方法开头读取配置并分支：

```python
async def list_saved_local_3v3_matches_for_identity(self, *, ...):
    # ... 现有 safe_page/skip/target_global_id 逻辑 ...
    if not target_global_id:
        return {"items": [], "total": 0, "page": safe_page, "page_size": safe_page_size, "has_more": False}

    # 读取配置
    import config as cfg
    read_mode = str(getattr(cfg, 'JJC_MATCH_PARTICIPANTS_READ_MODE', 'off') or 'off').strip().lower()
    if read_mode not in ('off', 'shadow', 'on'):
        logger.warning("JJC_MATCH_PARTICIPANTS_READ_MODE 非法值: %s，按 off 处理", read_mode)
        read_mode = 'off'

    # off: 走直接详情查询路径
    if read_mode == 'off':
        return await self._list_saved_matches_from_detail(...)

    # on/shadow: 委托投影 repo
    participant_repo = getattr(self, 'participant_repo', None)
    if participant_repo is None:
        return await self._list_saved_matches_from_detail(...)

    try:
        projection_result = await participant_repo.list_local_3v3_matches_by_global_id(
            global_id=target_global_id, page=safe_page, page_size=safe_page_size,
        )
    except Exception as exc:
        logger.warning("投影查询失败: global_id=%s error=%s", target_global_id, exc)
        if read_mode == 'on':
            return await self._list_saved_matches_from_detail(...)   # fallback
        projection_result = None

    if read_mode == 'on' and projection_result is not None:
        result = self._map_projection_to_match_rows(projection_result)
        # 批量补充 cached_detail_summary（复用现有 batch_load_cached_detail_summaries）
        await self._hydrate_cached_summaries(result["items"])
        return result

    if read_mode == 'shadow':
        detail_result = await self._list_saved_matches_from_detail(...)
        if projection_result is not None:
            self._compare_and_log_diff(target_global_id, detail_result, projection_result)
        return detail_result
```

**`list_local_3v3_matches_by_global_id()` 委托细节**：

- 查询条件：`{"global_id": global_id, "match_type": 3, "detail_available": True}`
- `total`：使用同一 filter 的 `count_documents()`，不得全量拉回 Python 计算。
- 排序：`[("match_time", -1), ("match_id", -1)]`，命中索引 `idx_global_available_time`。
- 分页：Mongo 侧 `skip(offset).limit(page_size)`。
- 返回结构：`{"items": [...], "total": N, "page": page, "page_size": page_size, "has_more": bool}`。

**`_map_projection_to_match_rows()` 映射规则**：

| 投影字段 | 行字段 |
|---|---|
| `match_id` | `match_id` |
| `won` | `won` |
| `kungfu` | `kungfu` |
| `avg_grade` | `avg_grade` |
| `total_mmr` | `total_mmr` |
| `mmr_delta` | `mmr_delta` |
| `mvp` | `mvp` |
| `match_time` | `match_time` |
| `start_time` | `start_time` |
| `duration` | `duration` |
| — | `cached_detail_summary`（后续批量补充）|
| `sync_status` | `sync.status`，无 seen 时固定为 `not_synced` |
| `detail_saved_at` | `sync.detail_saved_at` |
| `match_time` | `sync.match_time` |
| `source_identity_id` | `sync.source_identity_id` |
| `source_identity_key` | `sync.source_identity_key` |

`cached_detail_summary` 仍按当前页 `match_id` 批量从 `jjc_match_detail` 构造（调用 `batch_load_cached_detail_summaries()`）。补充失败只记录日志并返回不含摘要的行，不中断接口。

**`_compare_and_log_diff()` 差异比较（shadow 模式）**：

比较项（全部记录在一条 warning 中）：
- 当前页 `match_id` 集合差异：`detail_only = set(detail_ids) - set(proj_ids)`，`proj_only = set(proj_ids) - set(detail_ids)`
- 排序差异：比较两个列表的前 N 个 `match_id` 顺序
- `total` 差异

**差异阈值**：满足以下任一条件时阻止切 `on`：
- `abs(detail_total - proj_total) > max(5, detail_total * 0.05)`（即差异不超过 5 或 5%）
- `match_id` 集合对称差超过 5 个
- 排序 diff 中前 20 个 match 有任一位置不同

#### 直接详情查询路径提取为独立方法

将现有 `list_saved_local_3v3_matches_for_identity()` 的直接详情查询逻辑提取为 `_list_saved_matches_from_detail()`，保持签名一致。原方法变为路由入口。

该方法必须同步新语义：

- `jjc_sync_match_seen` 查询继续按 `match_id in participant_match_ids` 读取，但不再限制 `status='detail_saved'`；seen 只用于填充 `sync` 元数据。
- 移除 `mid not in seen_by_match_id` 展示过滤，仅在 `mid is None`、详情不可用、无 `data.detail`、非 3v3、缺目标玩家时跳过。
- `match_time` 优先使用 `detail.match_time` 或 `basic_info.start_time`，seen 的 `match_time` 只作为兜底或 `sync.match_time`。
- `sync` 子对象允许没有 seen 文档：`status` 固定返回 `not_synced`，`detail_saved_at/source_identity_id/source_identity_key` 返回 `null`。
- 直接查询路径使用与投影构造相同的 3v3 判断逻辑：优先读 `match_type` 字段，缺失时允许通过双方玩家总数为 6 推断为 3v3，无法确认时跳过。

#### `cached_detail_summary` 补充

- 不投影到新集合（避免字段膨胀），仍按当前页 `match_id` 批量从 `jjc_match_detail` 构造。
- 后续如仍慢，可把双方心法摘要也投影到新集合或独立摘要集合（非本计划范围）。
- `server`/`role_name` 缺失时：写 `null`，不影响接口（接口依赖 `player.identity` 中的 server/name，不依赖投影中的值）。

#### `detail_source` 常量

在 `JjcMatchParticipantRepo` 模块中定义常量：

```python
DETAIL_SOURCE_SYNC_WORKER = "sync_worker"
DETAIL_SOURCE_RANKING_DETAIL = "ranking_detail"
DETAIL_SOURCE_WARMUP = "warmup"
DETAIL_SOURCE_MANUAL = "manual"
DETAIL_SOURCE_UNKNOWN = "unknown"
```

各调用方按来源传入对应常量；未传时默认 `"unknown"`。

### 回填脚本

新增脚本建议：`scripts/backfill_jjc_match_participants.py`

行为：

- 从 `jjc_match_detail` 分批驱动，projection 只取 `match_id`、`cached_at`、`data.detail`、`data.unavailable`；这是展示主事实，不能只扫描 `jjc_sync_match_seen.status='detail_saved'`。
- 为避免全集合大对象扫描，回填游标必须带 projection，并按 `match_id` 升序分批；若线上 `jjc_match_detail.match_id` 唯一索引已存在，则利用 `idx_match_id` 做稳定遍历。
- 每批按 `$in` 批量查询 `jjc_sync_match_seen`，projection 只取 `match_id`、`status`、`match_time`、`detail_saved_at`、`source_identity_id`、`source_identity_key`、`source_server`、`source_role_name`，用于补充同步状态。
- 从 `data.detail.team1/team2.players_info` 拆出玩家投影。
- 每个 match 使用与运行时相同的 `replace_match_participants(match_id, participants)`；不得只按 `(match_id, global_id)` 单行 upsert 后保留旧玩家行。
- 支持 `--dry-run`、`--limit`、`--batch-size`、`--match-id`、`--resume-after-match-id`、`--verify-only`。
- 固定按 `match_id` 升序稳定遍历；`--resume-after-match-id` 对应同一排序键，输出可复制的续跑参数。
- 统计输出：
  - `scanned_detail`
  - `saved_participants`
  - `replaced_matches`
  - `skipped_unavailable`
  - `skipped_non_3v3`
  - `skipped_missing_match_type`
  - `skipped_no_global_id`
  - `seen_missing`
  - `projection_write_failed`
  - `errors`
- `--verify-only` 比较：
  - `eligible_available_3v3_match_count` 与 `distinct projected match_id count`；eligible 口径排除不可用详情、非 3v3、缺 `match_type` 且无法推断 3v3、缺全部玩家 `global_id` 等合法跳过项。
  - 随机或指定角色直接详情查询与投影查询的 `match_id` 集合、排序、`total`。
  - 单独输出 `missing_match_type` 导致的新旧差异数量，便于判断是否需要先做数据修复。
  - 差异超过阈值时禁止切换 `JJC_MATCH_PARTICIPANTS_READ_MODE=on`。

回填脚本必须复用运行时构造逻辑：

- 构造参与者行时调用 `build_participants_from_match_detail()` 或 `MatchDetailParticipantProjectionService` 的同一构造路径，不复制第二套玩家解析逻辑。
- `--verify-only` 不写库。
- `--dry-run` 只统计将要 replace 的 match 数和 participant 数。
- 写入失败时输出当前 `match_id` 和可续跑的 `--resume-after-match-id`。
- 回填完成前生产只允许 `off` 或 `shadow`，禁止直接切 `on`。

### 上线灰度流程

1. 发布写入代码，配置保持 `JJC_MATCH_PARTICIPANTS_READ_MODE=off`。
2. 执行回填脚本 `--dry-run`，确认 `skipped_*` 和 `seen_missing` 统计符合预期。
3. 小批量执行 `--limit` 回填，并用 `--verify-only` 对指定角色和随机样本校验。
4. 全量回填。
5. 切 `shadow`，观察至少 1 天或至少 N 次真实请求，记录当前页 `match_id` 差异、排序差异、`total` 差异和字段差异。
6. 差异低于阈值后切 `on`。
7. 若出现差异或用户反馈异常，立即切回 `off`；保留投影写入，修复后重新回填和 shadow。

`on` 模式下投影返回空结果不 fallback，所以切 `on` 前必须依赖回填和 shadow 验证。

### 阶段2变更文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `src/storage/mongo_repos/jjc_match_participant_repo.py` | **新增** | 参与者投影 repo，含 build/replace/clear/list/refresh_sync_status |
| `src/storage/mongo_repos/jjc_inspect_repo.py` | 修改 | 新增可选 `participant_repo` 字段，仅供读路径投影委托；`list_saved_local_3v3_matches_for_identity()` 改为读模式路由+投影委托+直接详情 fallback；提取 `_list_saved_matches_from_detail()`；`save_match_detail()` 不触发参与者投影 |
| `src/services/jx3/match_detail_participant_projection.py` | **新增** | 参与者投影 service，业务层保存详情后显式调用 |
| `src/services/jx3/singletons.py` | 修改 | 创建 `JjcMatchParticipantRepo` 与 `match_detail_participant_projection_service`；将 `match_participant_repo` 注入共享 `JjcInspectRepo` 读路径，将 projection service 注入需要保存详情的业务 service；现有 `match_detail_projection_service` 继续只表示身份投影 |
| `src/services/jx3/jjc_ranking.py` | 修改 | warmup 保存详情成功后显式调用参与者投影 service |
| `src/services/jx3/jjc_ranking_inspect.py` | 修改 | `get_match_detail()` 保存可用详情后显式调用参与者投影；保存 unavailable 后显式 clear |
| `src/services/jx3/jjc_match_data_sync.py` | 修改 | `_sync_match_detail()` 保存详情后显式调用参与者投影；`mark_match_detail_saved()` 成功后调用 `refresh_sync_status()` |
| `config.py` | 修改 | 新增 `JJC_MATCH_PARTICIPANTS_READ_MODE` 并入 `RUNTIME_CONFIG_KEYS` |
| `src/infra/mongo.py` | 修改 | `_ensure_indexes()` 新增 `jjc_match_participants` 集合索引 |
| `docs/design-docs/database-design.md` | 修改 | 记录 `jjc_match_participants` 集合、字段及索引 |
| `docs/exec-plans/index.md` | 修改 | 更新计划文件索引 |
| `scripts/backfill_jjc_match_participants.py` | **新增** | 回填脚本 |
| `tests/test_jjc_match_participant_repo.py` | **新增** | 投影 repo 单测 |
| `tests/test_jjc_inspect_repo.py` | 修改 | 补充直接详情查询语义、读模式切换等单测 |
| `tests/test_jjc_ranking_inspect.py` | 修改 | 补充按需详情保存后显式调用参与者投影、unavailable 后 clear |
| `tests/test_jjc_ranking_stats_repo.py` 或对应 ranking service 单测 | 修改 | 补充 warmup 保存详情后显式调用参与者投影 |
| `tests/test_jjc_match_data_sync.py` | 修改 | 补充同步 worker 保存详情后参与者投影、mark saved 后 refresh sync |

### 验证

**验证命令**：
```bash
python -m py_compile src/storage/mongo_repos/jjc_match_participant_repo.py
python -m py_compile src/storage/mongo_repos/jjc_inspect_repo.py
python -m py_compile src/services/jx3/singletons.py
python -m py_compile src/services/jx3/jjc_ranking.py
python -m py_compile src/services/jx3/jjc_match_data_sync.py
python -m py_compile config.py
python -m py_compile src/infra/mongo.py

# 单测
python -m unittest tests.test_jjc_match_participant_repo
python -m unittest tests.test_jjc_inspect_repo
```

**单测覆盖**（`tests/test_jjc_match_participant_repo.py`）：
- 投影 repo 从详情生成 6 条玩家记录（3v3 + global_id 非空）。
- 缺少 `global_id` 的玩家跳过不写入。
- 非 3v3（`match_type != 3`）跳过。
- `match_type` 缺失但双方玩家总数为 6 时推断为 3v3，并写入 `match_type_inferred=true`。
- `match_type` 缺失且无法推断时跳过并计入 `skipped_missing_match_type`。
- 同一 `match_id` 内重复 `global_id` 时只保留第一条有效玩家并统计 `duplicate_global_id`。
- 相同 `(match_id, global_id)` 重跑幂等覆盖（replace 语义）。
- 按 `match_id` replace 时旧玩家投影被清理。
- `server`/`role_name` 缺失时对应字段写 `null`。
- `identity_id`/`identity_key` 未传入时写 `null`。
- `detail_source` 传入时写入对应常量值，未传时默认 `"unknown"`。
- `refresh_sync_status()` 正确更新 sync 冗余字段。

**单测覆盖**（`tests/test_jjc_inspect_repo.py` 补充）：
- `save_match_detail()` 不触发参与者投影，保持 storage 纯职责。
- `participant_repo` 注入后 `shadow/on` 会调用投影查询；未注入时按计划 fallback 到直接详情查询。
- `_list_saved_matches_from_detail()` 不再要求 `jjc_sync_match_seen.status='detail_saved'`。
- 没有 seen 文档时仍展示本地有效详情，`sync.status='not_synced'`。
- `list_saved_local_3v3_matches_for_identity()` 在 `off`/`shadow`/`on` 三模式下行为正确。
- `on` 模式：查询异常 fallback 直接详情查询；空结果不 fallback。
- `shadow` 模式：返回直接详情查询结果，同时记录当前页 `match_id` 集合差异、排序差异、`total` 差异。
- 投影查询的 `total/has_more/page/page_size` 与直接详情查询一致。
- 只返回 3v3 和有 `global_id` 的记录。
- `cached_detail_summary` 补充失败不中断接口。

**业务 service 单测补充**：
- `JjcRankingInspectService.get_match_detail()` 可用详情保存成功后调用参与者投影。
- `JjcRankingInspectService.get_match_detail()` unavailable 保存后调用 clear。
- `JjcRankingService` warmup 保存详情后调用参与者投影。
- `JjcMatchDataSyncService` 保存详情后先 project，`mark_match_detail_saved()` 成功后 refresh sync status。
- 身份投影 service 与参与者投影 service 各自被调用，mock 断言不会串用。

**手工验证**：
- 对同一个角色比较旧查询和投影查询返回的 `match_id` 集合与排序。
- 请求 `/api/jjc/ranking-stats/synced-role-matches?...`，分别在 `off`、`shadow`、`on` 模式下对比响应结构和分页字段。
- 用 `explain` 确认命中 `idx_global_available_time`。
- 观察接口 p95 和 Mongo `docsExamined`。
- 回填脚本 dry-run、幂等、断点续跑、不可用详情、非 3v3、缺 global_id、seen 缺失的统计正确。

### 回滚

- 将 `JJC_MATCH_PARTICIPANTS_READ_MODE` 切回 `off`，立即恢复旧查询。
- `on` 模式下仅查询异常 fallback；发现数据差异时按运行配置回滚为 `off` 或 `shadow`。
- 如投影数据异常，关闭投影查询开关或删除新集合，不影响 `jjc_match_detail` 和 `jjc_sync_match_seen` 原始数据。

## 当前状态

- 阶段 1：已实现，`python -m py_compile src/infra/mongo.py` 已通过；待线上索引创建观察。
- 阶段 2：已按计划实现参与者投影表、读模式切换、保存入口投影、sync metadata 刷新、回填脚本与数据库设计文档更新。
- 2026-05-29：已随提交 `99b01e6` 落地并归档到 `completed/`。
- 已验证：
  - `python -m py_compile config.py src/infra/mongo.py src/storage/mongo_repos/jjc_match_participant_repo.py src/storage/mongo_repos/jjc_inspect_repo.py src/storage/mongo_repos/jjc_sync_repo.py src/services/jx3/match_detail_participant_projection.py src/services/jx3/singletons.py src/services/jx3/jjc_ranking_inspect.py src/services/jx3/jjc_ranking.py src/services/jx3/jjc_match_data_sync.py scripts/backfill_jjc_match_participants.py`
  - `python -m unittest tests.test_jjc_match_participant_repo tests.test_jjc_ranking_inspect tests.test_jjc_match_data_sync tests.test_jjc_sync_repo`
- 子 agent 审核/修复循环：
  - 第一轮抽象/简洁性审核发现重复 `_coerce_int`、死方法/薄 wrapper、日志风格问题；已修复。
  - 第一轮鲁棒性审核发现回填脚本单条异常会中断批次、`singletons.py` 可选导入处理不稳；已修复。
  - 第二轮功能正确性审核返回 `No findings`。
