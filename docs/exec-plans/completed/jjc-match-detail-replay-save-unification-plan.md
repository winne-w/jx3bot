# JJC match_detail 写入入口统一保存 replay 计划

状态：已完成，待提交
更新时间：2026-06-04

## 背景

线上发现 `258036857` 已进入 `jjc_match_detail` 与 `jjc_match_participants`，但 `jjc_match_detail.data.replay` 缺失。排查确认该对局由排名预热 `warmup` 路径写入，当前该路径只保存 match_detail，不像页面详情查询和 worker 同步路径一样查询并保存 replay。

## 目标

- 所有业务入口写入 `jjc_match_detail` 前都尽量查询并保存 replay。
- replay 补全逻辑与其他入口一致：保存 `data.replay`，并用 replay 回填 detail 玩家 `global_id/role_id/zone/server`。
- 保存后身份投影与参与者投影使用带 replay 的 payload。
- 若 replay 查询失败，不阻断 match_detail 保存；保留现有降级能力。

## 非目标

- 不修改推栏 replay 接口协议。
- 不做历史 `jjc_match_detail` 批量回填；后续可单独用脚本处理无 replay 的历史缓存。
- 不改变同步队列租约和投影表查询条件。

## 涉及文件

- `src/services/jx3/jjc_ranking.py`
  - 在 ranking warmup 写 match_detail 前，调用 replay 查询并合并。
  - 新增小型 helper，复用 `merge_replay_global_ids_into_match_detail()`。
- `tests/test_jjc_ranking_inspect.py`
  - 补 warmup 保存 replay 的单测。

## 验证

```bash
python -m py_compile src/services/jx3/jjc_ranking.py
python -m unittest tests.test_jjc_ranking_inspect
```

验证结果：

- 2026-06-15：代码对比确认 ranking warmup 已在保存 `match_detail` 前查询并合并 replay，保存后身份投影与参与者投影使用带 replay 的 payload。
- 2026-06-15：`python -m py_compile src/services/jx3/jjc_ranking.py` 通过。
- 2026-06-15：`python -m unittest tests.test_jjc_ranking_inspect` 通过，76 个测试 OK。
- 2026-06-15：计划归档到 completed。

## 回滚

回滚 `jjc_ranking.py` 的 warmup replay 补全逻辑和对应测试即可；页面详情查询和 worker 同步入口不受影响。
