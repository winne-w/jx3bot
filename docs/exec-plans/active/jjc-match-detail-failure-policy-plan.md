# JJC 对局详情失败策略调整计划

## 背景

当前 JJC 同步在处理某个角色的历史页时，如果任意一条对局详情请求失败，会把该角色本次同步标记失败并停止继续处理当前页后续对局和后续页。线上已观察到推栏详情接口对部分 `match_id` 返回：

```json
{"code": -1, "msg": "no data found", "data": null}
```

这类结果不是临时网络错误，而是接口明确表示该对局详情不可用。继续重试会浪费请求，并且会阻塞同一角色后续对局同步。

## 目标

1. 对临时性详情错误增加有限重试。
2. 单条详情失败不再中断当前角色同步：继续处理当前页剩余对局，并继续请求后续页。
3. 临时失败的对局保留失败标记，后续该角色或其他角色再次遇到这个 `match_id` 时允许再尝试一次。
4. `code=-1` 且 `msg=no data found`、`data=null` 的详情结果作为终态保存，不重试、不再重复查询。
5. 前端/API 查询该 `match_id` 时返回“该对局查询不到数据”的稳定结果，而不是反复请求推栏。

## 非目标

- 不改变 JJC 历史列表分页接口参数和推栏签名逻辑。
- 不调整角色队列发现、身份补全、赛季水位计算的整体策略。
- 不做旧失败数据的大规模自动修复；如需回填历史 `no data found` 记录，可单独补迁移脚本或手工脚本。

## 现状代码入口

- 同步编排：`src/services/jx3/jjc_match_data_sync.py`
  - `_sync_one_role(...)` 当前在 `detail_result == "failed"` 时抛出 `match_detail_failed:<match_id>`。
  - `_sync_match_detail(...)` 当前把所有详情异常统一返回 `"failed"`。
- 同步状态仓储：`src/storage/mongo_repos/jjc_sync_repo.py`
  - `jjc_sync_match_seen.status` 当前包含 `discovered`、`detail_syncing`、`detail_saved`、`failed`。
  - `claim_match_detail(...)` 当前会领取 `discovered` 和 `failed`。
- 详情缓存与查询：`src/storage/mongo_repos/jjc_inspect_repo.py`、`src/services/jx3/jjc_ranking_inspect.py`
  - 详情成功时保存到 `jjc_match_detail`。
  - 查询命中缓存后直接返回缓存数据；未命中时请求推栏。
- 前端页面：`public/jjc-ranking-stats.html`
  - 通过 `/api/jjc/ranking-stats/match-detail?match_id=...` 查询对局详情。

## 数据设计

### `jjc_sync_match_seen`

扩展详情状态，建议增加：

- `detail_unavailable`: 终态，表示推栏明确返回 `no data found`，无需再请求。

建议增加字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `detail_unavailable_at` | float/null | 标记不可用的时间 Unix 秒 |
| `unavailable_reason` | string/null | 不可用原因，如 `no data found` |
| `detail_retry_after` | float/null | 临时失败后下一次允许重试详情的时间 |

`claim_match_detail(...)` 调整为：

- 可领取 `discovered`。
- 可领取 `failed` 且 `detail_retry_after <= now` 或为空的记录。
- 不领取 `detail_saved`、`detail_unavailable`、`detail_syncing` 未过期租约。

### `jjc_match_detail`

继续作为按 `match_id` 的详情查询缓存。为 `no data found` 结果保存一个轻量终态文档：

```json
{
  "match_id": 254734531,
  "cached_at": 1778138076.0,
  "data": {
    "match_id": 254734531,
    "unavailable": true,
    "code": -1,
    "message": "no data found",
    "detail": null
  }
}
```

读取时如果 `data.unavailable == true`，API 返回稳定业务结果：

```json
{
  "match_id": 254734531,
  "unavailable": true,
  "code": -1,
  "message": "no data found",
  "detail": null,
  "cache": {"hit": true, "cached_at": 1778138076.0}
}
```

## 行为规则

### 详情请求重试

在 `_sync_match_detail(...)` 内部对临时错误做有限重试：

- 默认最多请求 3 次：首次 + 2 次重试。
- 每次请求前沿用现有 `sleep_func`，避免打爆推栏。
- 只有网络错误、非结构化响应、接口临时错误等可重试。
- 命中 `code=-1`、`msg == "no data found"`、`data is None` 时立即停止重试，并进入不可用终态。

### 单条失败不阻塞角色

调整 `_sync_one_role(...)`：

- `_sync_match_detail(...)` 返回 `"saved"`：计入 `saved_details`。
- 返回 `"skipped"`：计入 `skipped_details`。
- 返回 `"unavailable"`：计入新增 `unavailable_details`，继续循环。
- 返回 `"failed"`：计入新增 `failed_details`，继续循环，不抛出角色级异常。
- 仅历史页请求失败、重复页安全阀、最大页安全阀、身份缺失等角色级问题才 `release_role_failure(...)`。

水位推进规则：

- 如果历史页完整扫描到边界，即使其中有少量详情临时失败，也允许释放角色成功并推进 `full_synced_until_time`。
- 失败详情自身由 `jjc_sync_match_seen.status=failed` 与 `detail_retry_after` 管理，后续再次遇到该对局时重试。
- 因 `match_id` 全局去重，同一失败对局可能由同角色后续同步或其他角色历史同步再次触发重试。

### `no data found` 终态

当详情接口返回 `{"code": -1, "msg": "no data found", "data": null}`：

1. 写入 `jjc_match_detail` 的 unavailable 轻量文档。
2. 将 `jjc_sync_match_seen.status` 标记为 `detail_unavailable`。
3. 不计入临时失败，不设置后续重试。
4. 后续同步再次遇到该 `match_id` 时 `claim_match_detail(...)` 返回 `None`，同步侧按 skipped 或 unavailable skipped 处理。
5. 前端/API 查询该 `match_id` 命中缓存并返回 unavailable 结果，不再请求推栏。

## 实施步骤

1. 更新仓储层 `JjcSyncRepo`
   - 新增 `mark_match_detail_unavailable(match_id, reason, code)`。
   - 调整 `claim_match_detail(...)` 过滤条件，排除 `detail_unavailable`，并支持 `detail_retry_after`。
   - 调整 `mark_match_detail_failed(...)` 写入 `detail_retry_after`，建议退避策略为 5 分钟、30 分钟、2 小时递增，上限 6 小时。

2. 更新详情缓存仓储 `JjcInspectRepo`
   - 新增保存 unavailable 详情的方法，或复用 `save_match_detail(...)` 写入标准 unavailable payload。
   - 确保快照拆表逻辑遇到 `detail == null` 或 `unavailable == true` 时直接跳过，不进入玩家装备/奇穴拆表。
   - 确保 `load_match_detail(...)` 能原样读回 unavailable payload。

3. 更新查询服务 `JjcRankingInspectService`
   - 识别推栏 `MatchDetailResponse(code=-1, msg="no data found", data=None)`。
   - 未命中缓存时如果实时请求得到 no data found，写入 unavailable 缓存后返回 unavailable 业务结果。
   - 命中 unavailable 缓存时直接返回，不再请求推栏。

4. 更新同步服务 `JjcMatchDataSyncService`
   - `_sync_match_detail(...)` 增加临时错误重试与 no data found 分支。
   - `_sync_one_role(...)` 不再因单条详情 `"failed"` 抛角色级异常。
   - `run_once(...)` 汇总新增 `failed_details`、`unavailable_details`，管理员状态消息同步展示。

5. 更新前端 `public/jjc-ranking-stats.html`
   - 详情弹窗/面板识别 `unavailable == true`。
   - 展示“该对局查询不到数据”以及 `match_id`，不展示空白详情或通用错误。

6. 更新文档
   - `docs/design-docs/database-design.md` 同步 `jjc_sync_match_seen.status`、新增字段、`jjc_match_detail` unavailable payload。
   - 如管理员命令输出新增统计字段，必要时更新 `docs/references/runbook.md` 的手工回归路径。

## 验证计划

自动化测试：

```bash
python -m unittest tests.test_jjc_match_data_sync tests.test_jjc_match_detail_hydration tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/jjc_sync_repo.py src/storage/mongo_repos/jjc_inspect_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py
```

新增/调整用例：

- 同一页 3 条对局，第 2 条详情临时失败，第 3 条仍继续请求，角色最终成功释放。
- 第一页存在临时失败，仍继续请求第二页。
- 临时失败写入 `status=failed`、`fail_count`、`detail_retry_after`，到期后可重新 claim。
- `no data found` 不重试，写入 `jjc_match_detail` unavailable 文档，并标记 `jjc_sync_match_seen.status=detail_unavailable`。
- 已标记 unavailable 的对局再次同步时不请求详情接口。
- API 查询 unavailable 对局返回稳定 payload，前端显示“该对局查询不到数据”。

手工验证：

1. 使用已知 `match_id=254734531` 请求 `/api/jjc/ranking-stats/match-detail?match_id=254734531`。
2. 确认 Mongo `jjc_match_detail` 存在 unavailable 文档。
3. 再次请求同一接口，确认命中缓存且无推栏详情请求日志。
4. 构造或选取一个临时失败 match，确认角色同步继续处理后续 match 和后续页。

## 风险与回滚

- 风险：允许角色在详情临时失败时推进水位，可能让失败详情只依赖后续再次遇到该 `match_id` 才重试。缓解方式是 `claim_match_detail(...)` 支持 `failed` 到期后重试，并可后续补独立的失败详情补偿任务。
- 风险：前端若未识别 unavailable payload，可能显示通用错误。需要前端专门处理 `unavailable == true`。
- 回滚：保留旧状态兼容。若需回滚代码，`detail_unavailable` 文档不会破坏唯一索引；旧代码读取到 unavailable 缓存可能无法展示详情，但不会重复写大对象。必要时可手工将相关 `jjc_sync_match_seen.status` 改回 `failed` 或删除 unavailable 缓存重新请求。

## 待确认

- 临时失败重试次数是否固定为 3 次。
- `detail_retry_after` 退避时间是否采用 5 分钟、30 分钟、2 小时、6 小时上限。
- 管理员 `/jjc同步状态` 是否需要展示 `详情临时失败` 与 `详情不可用` 的累计数量。
