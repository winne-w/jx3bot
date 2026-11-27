# P1 统一领域规则层执行计划

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

建立无外部依赖的 `src/domain/` 领域层，统一心法目录（含坦克独立统计口径）、角色名拆分、身份匹配证据强度、快照哈希与赛季开赛时间解析；彻底消除 `src/storage/` 对 `src/services/` 的反向导入；并收敛脚本 Mongo 连接与公共类型转换工具。

## Progress
- [x] 完成 P1 方案设计与存量单测契约确认（2026-11-26）
- [ ] 子任务 P1-A：建立 `src/domain/kungfu_catalog.py` 并收口 5 处重复心法映射与坦克统计口径
- [ ] 子任务 P1-B：建立 `src/domain/{role_name,role_identity,snapshots,season}.py` 与 `src/utils/coerce.py`，消除全部 `storage -> services` 反向依赖并修复 replay 身份匹配冲突漏洞
- [ ] 子任务 P1-C：建立 `scripts/_common/mongo.py` 并收敛维护脚本的 URI/DB/赛季时间重复实现
- [ ] 整合复核、Python 3.9 与 Python 3.13 双版本验证、审查与本地提交

## Surprises & Discoveries

- `tests/test_kungfu_aliases.py:63` 显式断言 32 心法的 JJC 对阵目录不包含“洗髓经”，而 `KUNGFU_ALIASES` 包含 33 心法；通过 `KungfuSpec.in_jjc_catalog` 区分即可同时满足全量单一数据源与既有目录契约。
- `tests/test_jjc_kungfu_meta.py:134-162` 覆盖了运行时通过 `config.KUNGFU_META` 覆盖合法 `category` 并忽略非法 `category` 的行为，`jjc_kungfu_meta.get_jjc_kungfu_catalog()` 需保留该覆盖优先级。

## Decision Log

- 2026-11-26：负责人确认接受“坦克心法在统计中独立计入 `tank`，不再归入 DPS”。

## Outcomes & Retrospective

待完成后回填。

## Context and Orientation

分支 `refactor/design-p1-domain` 基于 P0 提交 `73a3d1b`，不触碰在途 `feat/unify-visual-style` 修改的模板与前端文件。

## Plan of Work

拆分为 P1-A、P1-B、P1-C 三个文件集合严格互斥的并行子任务，全部完成后由主 agent 统一跑 Python 3.9/3.13 测试、检查零 `storage -> services` 导入并提交。

## Concrete Steps

见 `design.md` 与并行子任务说明。

## Validation and Acceptance

- `grep -rn "from src\.services" src/storage/` 输出为空。
- `py_compile` 全部改动文件在 Python 3.9 下零错误。
- Python 3.9 与 Python 3.13 下心法、别名、排名、统计路由、身份、快照、脚本相关测试全部通过。
