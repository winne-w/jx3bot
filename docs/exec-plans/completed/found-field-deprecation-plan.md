# `found` 字段降级与 `kungfu` 主判定改造计划

状态：已完成
更新时间：2026-05-07

## 背景

当前 JJC 心法缓存与排名统计链路里，`found` 与 `kungfu` 同时存在，但两者并不是同等级事实：

- `kungfu` 是实际查询结果，表示角色最终判定出的心法
- `found` 更像派生字段，通常等价于 `kungfu` 是否非空

这次线上问题已经暴露出该设计的脆弱性：

- `role_jjc_cache` 历史文档中存在 `kungfu` 已写入、但 `found` 缺失的情况
- 统计逻辑使用 `if player_item.get("found") and player_item.get("kungfu")`
- 导致“缓存命中且有心法”的角色，最终仍被误判为无效数据

当前已经通过运行时兜底修复：

- 读取缓存时，若缺少 `found`，按 `kungfu` 是否为空自动补齐
- 后续写入新集合时，一并持久化 `found`

但从设计上，仍需进一步收敛：让业务主判断依赖 `kungfu`，而不是依赖 `found + kungfu` 双字段。

## 目标

- 明确 `kungfu` 是“是否有有效心法数据”的主判断字段
- 将 `found` 从核心业务判断条件降级为兼容/冗余字段
- 避免未来再次出现“事实字段有值，但派生字段缺失导致误判”的问题
- 在不破坏现有缓存、接口、统计结构的前提下平滑完成改造

## 改造原则

1. 是否有心法结果，优先看 `kungfu`
2. 是否完成缓存检查流程，继续看 `weapon_checked`、`teammates_checked`、`match_history_checked`
3. `found` 如保留，仅作为兼容字段和调试辅助字段，不再承担核心业务语义
4. 历史数据兼容优先，本地推导优先，不为了补 `found` 单独重打外部接口

## 范围

重点检查以下链路：

- `src/services/jx3/jjc_ranking.py`
- `src/services/jx3/jjc_cache_repo.py`
- `src/services/jx3/jjc_ranking_inspect.py`
- `src/storage/mongo_repos/role_jjc_cache_repo.py`
- `scripts/migrate_role_identity_and_jjc_cache.py`
- `scripts/check_role_identity_migration.py`
- `docs/design-docs/database-design.md`

## 阶段 1：现状盘点

目标：确认 `found` 当前到底承担了哪些职责。

执行项：

- 全局搜索 `found` 的读取、写入和判断位置
- 区分以下三类使用方式：
  - 真实需要表达“是否查到结果”的兼容字段
  - 只是拿它判断“是否有心法”的业务逻辑
  - 仅用于日志、调试或导出
- 输出一份使用点清单，标记哪些地方可以直接改成看 `kungfu`

验收：

- 能明确列出所有核心判断点
- 能识别出哪些逻辑仍然错误依赖 `found`

## 阶段 2：业务判断收敛

目标：把“是否有有效心法数据”的核心判断改成以 `kungfu` 为主。

建议改法：

- 将统计逻辑中的：

```python
if player_item.get("found") and player_item.get("kungfu")
```

逐步收敛为更接近：

```python
if player_item.get("kungfu")
```

同时保留流程型校验字段：

- `weapon_checked`
- `teammates_checked`
- `match_history_checked`

注意：

- 不要把“有心法结果”与“缓存是否完整新鲜”混为同一个布尔字段
- 对无效明细日志，继续保留原因拆解，但 `found_false` 不应再是主原因

验收：

- 命中新缓存且 `kungfu` 非空的角色，能稳定进入排名统计
- 缺少 `found` 的历史文档不会再影响统计结果

## 阶段 3：数据模型降级

目标：把 `found` 从“核心字段”降级为“兼容字段”。

执行项：

- 在文档中明确：
  - `kungfu` 是主事实字段
  - `found` 是兼容字段，可由 `kungfu` 推导
- 评估 `role_jjc_cache` 是否仍需长期持久化 `found`
- 若继续保留：
  - 明确它是冗余字段
  - 新写入时允许继续补齐
- 若计划移除：
  - 先移除所有核心判断依赖
  - 再安排迁移和文档变更

验收：

- 新文档不再把 `found` 描述为核心业务判断字段
- 新代码即使完全不依赖 `found` 也能正确工作

## 阶段 4：历史数据治理

目标：降低运行时兜底的长期负担。

执行项：

- 补一个只针对 `role_jjc_cache` 的回填脚本或一次性 Mongo 更新方案：
  - 条件：`found` 不存在
  - 更新：`found = bool(kungfu)`
- 在核验脚本中增加统计项：
  - 缺少 `found` 的文档数
  - `kungfu` 非空但 `found=False` 的异常文档数

说明：

- 该阶段不需要重新调用排行榜、indicator 或战绩接口
- 这是本地 schema 修正，不是外部数据重新采集

验收：

- `role_jjc_cache` 中缺少 `found` 的文档数可见
- 回填后历史数据结构更一致

## 阶段 5：回归验证

至少覆盖以下用例：

1. 新集合文档有 `kungfu`，但没有 `found`
   - 读取后应被自动补齐
   - 排名统计应计入有效心法

2. 新集合文档 `kungfu=""` 或 `None`
   - 应仍被视为无有效心法数据

3. 新写入缓存文档
   - `kungfu` 与 `found` 一致

4. 角色近期与对局详情链路
   - 不因 `found` 语义调整而回退

5. 排名统计结果
   - 有心法的命中新缓存角色不再被错误过滤

## 风险

- 如果一次性直接删除 `found`，可能影响旧代码、旧导出或隐式依赖判断
- 如果只保留运行时兜底、不推进业务判断收敛，后续仍可能在别的链路重复踩坑
- 如果把 `kungfu` 主判定和 freshness 流程判断混在一起，可能引入新的误判

## 推荐顺序

1. 先盘点 `found` 使用点
2. 先改业务判断，主逻辑收敛为 `kungfu`
3. 再补历史数据回填和核验项
4. 最后决定 `found` 是长期保留为兼容字段，还是进一步移除
