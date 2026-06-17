# JJC 角色 indicator 最佳字段改为 mvp_count 计划

## 背景

真实 `role/indicator` 接口的 3v3 最佳次数字段是 `mvp_count`。当前仓库刚增加了中间语义字段 `best_count` 作为页面展示口径，但用户要求不要再做字段映射猜测，直接使用真实字段 `mvp_count`，并移除原本错误读取的 `best_score`。

## 目标

- 后端规整结果直接输出 `mvp_count`。
- 前端“最佳”卡片只读取 `mvp_count`。
- 删除本次修复里新增的 `best_count` 口径和对 `best_score` 的页面依赖。

## 影响范围

- `src/services/jx3/indicator_utils.py`
- `public/jjc-ranking-stats.html`
- `public/jjc-synced-matches.html`
- `tests/test_indicator_utils.py`
- `docs/design-docs/database-design.md`

## 实施步骤

1. 修改 `parse_3v3_indicator()`：
   - 直接从顶层、`performance`、`metrics` 读取 `mvp_count` / `mvpCount`。
   - 返回字段改为 `mvp_count`。
   - 删除 `best_count` 输出。
2. 修改前端页面：
   - “最佳”卡片只展示 `ind.mvp_count ?? "-"`。
   - 删除对 `best_count`、`best_score` 的展示依赖。
3. 修改单测：
   - 断言改为 `mvp_count`。
4. 更新文档：
   - `jjc_role_indicator.indicator` 说明改为 `mvp_count`，移除 `best_count` / `best_score` 口径描述。

## 验证

- `python -m unittest tests.test_indicator_utils`
- `python -m py_compile src/services/jx3/indicator_utils.py`
- 用真实 `role/indicator` 响应确认解析结果直接包含 `mvp_count`。

## 风险与回滚

- 风险：旧缓存里如果只有错误字段，页面会显示 `-`，但这是有意的，避免继续沿用错误口径。
- 回滚：恢复 `best_count` 中间字段和前端兜底逻辑。
