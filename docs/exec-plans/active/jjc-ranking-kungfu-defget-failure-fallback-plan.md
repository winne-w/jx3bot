# JJC 排名心法 defget 失败时历史胜场兜底修复计划

## 背景

当前 JJC 排名心法判定已经有基于 `jjc_match_detail` 已缓存对局的历史胜场兜底逻辑：同一角色同一心法在当前赛季获胜对局中出现不少于 3 场时，可作为排名统计心法，来源标记为 `cached_match_detail_win_history`。

实际排查发现，部分今日排名角色在已有对局中已经满足胜场阈值，但仍进入 `missing_kungfu_lines`：

- `梦江南 忆绘`：已有对局可判定 `孤锋诀`，4 胜。
- `斗转星移 睁眼说瞎话`：已有对局可判定 `幽罗引`，10 胜。
- `梦江南 睿智才打渊@绝代天骄`：已有对局可判定 `傲血战意`，3 胜。
- `天鹅坪 小猪`：已有对局 `幽罗引` 仅 2 胜，不达标，仍应缺失。

根因是 `get_user_kungfu()` 中历史胜场兜底位置过晚：只有 `defget` 竞技查询成功后，才会继续尝试 `get_kungfu_from_cached_match_detail_win_history()`；一旦 `defget` 返回错误或不可用，当前代码直接返回 error，不会再查本地已有对局。

## 目标

- 当 indicator / match_history 未能给出心法，且 `defget` 竞技查询失败时，仍尝试从本地已缓存 `jjc_match_detail` 中按历史胜场推断心法。
- 保持现有胜场阈值不变：同一心法获胜场次 `>= 3` 才算。
- 兜底成功后本轮排名统计不再把角色放入 `missing_kungfu_lines`。
- 兜底成功后继续写入 `role_jjc_cache`，并保留 `cached_match_detail_*` 诊断字段。
- `天鹅坪 小猪` 这类未满 3 胜样本仍保持缺失，不放宽口径。

## 非目标

- 不改变 `get_kungfu_from_cached_match_detail_win_history()` 的角色匹配、赛季过滤和排序规则。
- 不主动请求新的 `match/detail` 或 `match/replay`；只读已缓存数据。
- 不调整 `role_identities`、同步队列、JJC 对局同步策略。
- 不改变 HTTP API 外层响应结构、统计 JSON schema 的既有字段含义。
- 不修改胜场阈值，不将失败对局或总出场次数作为成功依据。

## 设计

### 1. 收敛兜底调用

在 `src/services/jx3/jjc_ranking.py` 中新增一个私有辅助方法，例如 `_get_cached_match_detail_win_kungfu(...)`：

- 参数包含 `server`、`name`、`role_id` 或可用的排名 `gameRoleId`。
- 内部统一调用 `self._cache().get_kungfu_from_cached_match_detail_win_history(...)`。
- 返回现有格式的 `history_win_result`，不重新实现 Mongo 查询。

这样可以让 `defget` 成功但无心法、`defget` 失败、后续异常路径复用同一段代码，避免再次出现兜底位置不一致。

### 2. 调整 `get_user_kungfu()` 分支顺序

保持现有优先级：

1. 有效 `role_jjc_cache`。
2. 排行榜角色信息 + `get_kungfu_detail_by_role_info()`。
3. `defget` 竞技查询 history 胜场心法。
4. 本地 `jjc_match_detail` 历史胜场兜底。

关键修复点：

- 当 `defget` 返回 `error` 或 `msg != "success"` 时，不立即 `return error`。
- 先调用本地历史胜场兜底。
- 如果兜底命中，则构造成功结果并保存缓存。
- 如果兜底仍未命中，再返回原有 defget error 结构，保留失败原因。

### 3. 结果构造与缓存写入

新增或复用一个结果合并辅助逻辑，确保兜底成功时结果包含：

- `server`
- `name`
- `kungfu`
- `found=True`
- `cache_time`
- `weapon_checked=True` 或沿用 `_merge_cached_weapon()` 结果
- `kungfu_selected_source="cached_match_detail_win_history"`
- `kungfu_id`
- `cached_match_detail_win_count`
- `cached_match_detail_total_count`
- `cached_match_detail_latest_win_match_id`
- `cached_match_detail_latest_win_time`
- `cached_match_detail_win_samples`

保存仍走 `self._cache().save_kungfu_cache(server, name, result)`，不在 service 中直接写 Mongo。

### 4. 排名统计输出

`get_ranking_kungfu_data()` 已透传 `cached_match_detail_*` 和 `kungfu_selected_source` 字段，原则上无需修改输出结构。

修复后满足阈值的角色会通过 `kungfu_info.get("found") and kungfu_info.get("kungfu")` 分支进入 `ranking_kungfu_lines`，不再进入 `missing_kungfu_lines`。

### 5. 日志

补充清晰日志，区分以下场景：

- `defget` 失败，开始尝试本地历史胜场兜底。
- `defget` 失败但本地兜底命中。
- `defget` 失败且本地兜底未命中，返回原 defget 错误。

日志中包含 `server`、`name`、`role_id`、命中心法、胜场数和最近胜场 `match_id`，便于后续排查。

## 涉及文件

- `src/services/jx3/jjc_ranking.py`
  - 调整 `get_user_kungfu()` 中 `defget` 失败分支。
  - 可新增私有辅助方法统一本地历史胜场兜底和结果合并。
- `tests/test_jjc_ranking_history_win_kungfu.py`
  - 增加 `defget` 失败但本地历史胜场兜底成功的用例。
  - 增加 `defget` 失败且本地兜底未命中时仍返回原错误的用例。
  - 增加未满 3 胜不算成功的回归用例，如 `wins=2`。
- `docs/exec-plans/active/jjc-ranking-kungfu-defget-failure-fallback-plan.md`
  - 本计划文件。

本次不预计修改数据库结构、索引或 API 文档。

## 验证

自动化验证：

```bash
python -m unittest tests.test_jjc_ranking_history_win_kungfu
python -m py_compile src/services/jx3/jjc_ranking.py src/services/jx3/jjc_cache_repo.py
```

如改动影响缓存保存字段，再追加：

```bash
python -m unittest tests.test_jjc_kungfu_global_id tests.test_jjc_weapon_quality
```

手工数据验证：

1. 在真实 Mongo 中只读调用同一兜底方法确认样本基线：
   - `梦江南 忆绘` 命中 `孤锋诀`，胜场 4。
   - `斗转星移 睁眼说瞎话` 命中 `幽罗引`，胜场 10。
   - `梦江南 睿智才打渊@绝代天骄` 命中 `傲血战意`，胜场 3。
   - `天鹅坪 小猪` 不命中，只有 2 胜。
2. 模拟或 monkeypatch `defget_get()` 返回失败，确认前三个样本仍能返回 `found=True`。
3. 确认 `小猪` 在相同失败路径下仍返回未找到或原 defget 错误，不被计入心法统计。
4. 手动跑一次排名统计 debug，确认符合阈值的角色不再出现在 `missing_kungfu_lines`。

## 风险

- 风险：`defget` 失败后多一次 Mongo 查询，排名统计耗时略增。
  - 缓解：仅在前置心法链路失败时触发，且复用已有窄查询与索引。
- 风险：兜底成功时可能缺少完整队友/武器字段，影响缓存 freshness。
  - 缓解：保持 `_merge_cached_weapon()` 和现有保存逻辑；本次目标是本轮统计可用，完整缓存后续仍按现有流程补齐。
- 风险：错误处理改动导致原 `defget` 错误被吞。
  - 缓解：仅在本地兜底成功时覆盖为成功结果；兜底失败时返回原错误结构。

## 回滚

回滚 `get_user_kungfu()` 中 `defget` 失败后继续调用历史胜场兜底的改动，即可恢复原行为。

已写入 `role_jjc_cache` 的 `cached_match_detail_win_history` 记录可等待 TTL 自然过期；如需立即清理，可按 `kungfu_selected_source="cached_match_detail_win_history"` 和具体角色 identity 定点删除或更新。

## 状态

- 2026-05-26：实现已完成，自动化验证已通过；代码尚未提交，计划继续保留在 active。
