# JJC 角色 indicator 最佳次数展示修复计划

## 背景

竞技排名个人弹窗和已同步对局个人页的顶部赛季战绩卡片中，“最佳”应展示本赛季 3v3 总场次中获得最佳/MVP 的次数。当前前端读取 `indicator.best_score`，后端解析也按最高分相关字段生成 `best_score`，导致真实最佳次数字段存在时页面仍显示空值或口径错误。

## 目标

- 后端 `role/indicator` 规整结果新增 `best_count`，表示 3v3 最佳/MVP 次数。
- 前端两个页面的“最佳”卡片优先展示 `best_count`，兼容旧缓存或旧响应中的 `best_score`。
- 更新 `jjc_role_indicator.indicator` 文档说明，避免继续把“最佳次数”误写成“最佳评分”。

## 影响范围

- `src/services/jx3/indicator_utils.py`
- `public/jjc-ranking-stats.html`
- `public/jjc-synced-matches.html`
- `tests/test_indicator_utils.py`
- `docs/design-docs/database-design.md`

## 实施步骤

1. 扩展 `parse_3v3_indicator()`：
   - 从 3v3 indicator 顶层、`performance`、3v3 `metrics` 中提取最佳次数字段。
   - 字段候选包含 `best_count`、`bestCount`、`mvp_count`、`mvpCount`、`best`、`mvp`。
   - 输出字段命名为 `best_count`；保留原 `best_score` 兼容旧调用方，但不作为页面展示主口径。
2. 修改两个前端页面：
   - “最佳”卡片取值改为 `ind.best_count ?? ind.best_score ?? "-"`。
3. 修改数据库设计文档：
   - `jjc_role_indicator.indicator` 字段说明加入 `best_count`，并说明 `best_score` 仅为历史兼容/最高分字段。
4. 增加单测：
   - 覆盖 `best_count` 从 `performance.mvp_count` 或 `metrics.best_count` 中解析。

## 验证

- `python -m unittest tests.test_indicator_utils`
- `python -m py_compile src/services/jx3/indicator_utils.py`
- 手工回归：刷新排名个人弹窗和已同步对局个人页，确认“最佳”展示最佳次数；若后端仍返回旧缓存，页面按兼容逻辑不报错。

## 风险与回滚

- 风险：推栏字段名仍有未知变体。当前只接受明确的最佳次数/MVP 次数字段，未知字段继续显示 `-`。
- 回滚：恢复前端读取 `best_score`，移除 `best_count` 解析与文档说明。
