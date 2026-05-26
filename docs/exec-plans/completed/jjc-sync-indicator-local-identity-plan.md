# JJC 同步 indicator 本地身份优先计划

状态：已完成并归档
更新时间：2026-05-25

## 背景

JJC 对局同步在保存每场 3v3 对局详情前，会对详情中的 6 名玩家调用 `/role/indicator`，用 `role_id + zone + server` 补齐 SK01 `global_role_id` 和 `person_id`。该字段用于后续 `match/history` 同步队列，但如果本地 `role_identities` 已经有更新且完整的身份记录，重复请求 indicator 会放大推栏压力。

## 目标

- 在 `_enrich_detail_with_indicator()` 内先查询本地身份表。
- 本地身份命中且包含 SK01 `global_role_id`，并且身份画像观测时间不早于当前对局时间时，直接回填玩家字段并跳过 indicator。
- 本地身份不存在、缺少 SK01 `global_role_id`、或当前对局时间晚于本地 `role_info_observed_match_time` 时，继续调用 indicator 刷新身份。
- 保持鉴权错误自动暂停、租约续租和现有详情保存流程不变。

## 涉及文件

- `src/services/jx3/jjc_match_data_sync.py`
  - 给 `_enrich_detail_with_indicator()` 增加 `match_time` 参数。
  - 增加本地身份是否可复用的判断函数。
  - `_sync_match_detail()` 调用时传入对局时间。
- `tests/test_jjc_match_data_sync.py`
  - 补充本地身份命中跳过 indicator、本地缺 SK01 仍请求、对局时间晚于本地观测时间仍请求的测试。

## 验证

```bash
python -m unittest tests.test_jjc_match_data_sync
python -m py_compile src/services/jx3/jjc_match_data_sync.py
```

结果：

- 2026-05-25：`python -m unittest tests.test_jjc_match_data_sync` 通过，87 个用例 OK。
- 2026-05-25：`python -m py_compile src/services/jx3/jjc_match_data_sync.py` 通过。

## 回滚

回滚本计划中的 service 与测试改动即可恢复为每个缺 SK01 的对局玩家都请求 indicator。
