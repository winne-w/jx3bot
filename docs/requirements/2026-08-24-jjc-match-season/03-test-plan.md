# JJC 对局赛季归属与查询隔离 测试计划

## Test Scope

覆盖投影赛季归属、当前赛季列表查询、索引定义和回填脚本的 dry-run/apply/verify 安全边界。完整详情直查和历史赛季选择器不在本次范围。

## Automated Checks

- `tests/test_jjc_match_participant_repo.py`：赛季边界、赛季前、无 `match_time` 和现有投影字段兼容。
- `tests/test_jjc_ranking_inspect.py`：已同步列表把当前赛季传给 repo。
- `tests/test_backfill_jjc_match_participant_season.py`：分类、默认 dry-run 和 apply 双确认。
- `python -m py_compile`：所有改动的 Python 模块。

## Manual Smoke Tests

- 用当前赛季已同步角色打开 `/jx3/jjc-synced-matches.html`，确认列表正常分页。
- 对同一角色分别检查当前赛季和赛季前对局，确认 API 仅返回当前 `season_id`。
- 更新到未来赛季配置后，以空列表验证没有历史赛季泄漏；同步一条新对局后确认其出现。

## Data Regression

- 回填前读取至少一条 `match_time < CURRENT_SEASON_START` 和一条 `>= CURRENT_SEASON_START` 的样本。
- dry-run 统计与样本一致后才 apply。
- apply 后 verify-only 的不一致数必须为 0；同时记录当前赛季、未归属、失败数量。

## Observability

- 关注 `JJC match_participants 查询完成` 日志中的 total/items；新赛季切换后 total 应从当前赛季投影计算。
- 回填脚本输出不可包含 Mongo URI、token、cookie 或其他凭据。

## Result

待实现与回填后填写。
