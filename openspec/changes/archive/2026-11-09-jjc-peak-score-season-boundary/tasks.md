# 执行计划：14 日最高分赛季隔离

## Purpose / Big Picture
2026-11-09 用户明确要求“按照这个方案处理修复”，授权按 design.md 完成实现、验证与线上存量恢复。本计划将已确认方案细化为可核验工作项；不重复请求已有授权。

## Progress
- [x] 方案确认，保存原工作区状态并核对现有实现。
- [x] 主执行者实现统一赛季上下文、缓存校验、原子结果发布与 API 编排。
- [x] 子 agent 完成前端窗口说明、缓存标记及前端回归。
- [x] 子 agent 先行补充 service 边界、缓存失效及失败传播测试。
- [x] 主执行者实现定向 dry-run/apply/verify 工具及相关测试。
- [x] 运行 Python 3.9 兼容性、业务回归、隔离 Mongo 聚合与性能验证。
- [x] 子 agent 只读复核最终变更，主执行者闭环问题。
- [x] 生产只读预检、源码与结果备份、受控替换及重启。
- [x] 定向重建本赛季两类最高分结果，验证公网列表、分布、详情与旧赛季读取。
- [x] 同步数据库设计、运行手册、项目上下文及验收证据。

## Surprises & Discoveries
工作区有未提交的离线统计及身份恢复改动，本次保留，不覆盖或提交无关改动。status_monitor/jobs.py 已有独立修改，最高分使用默认配置装配时优先避免编辑该文件。

## Decision Log
沿用现有唯一键和 version=1，新增 aggregation_scope/season_id/season_start_time 及实际窗口校验。聚合前按 match_time 截断，不依赖存量 season_id 全量回填。历史缺少边界的结果仅保留原已存视图，不猜测重算。

## Outcomes & Retrospective
2026-11-09 11:05:23 已发布并完成线上恢复。8 个锚点两分数共 16 份结果重建/verify 通过，公网四范围及心法详情一致，开赛前来源为 0；旧赛季抽样文档哈希不变。153 项本地相关测试通过，生产 90 项通过/1 项 Node 跳过，另 1 项无关存量样式断言已原环境复现并记录。六文件哈希和原配置验证通过，4 worker 在线且本次暂停已恢复；修复已提交为 `e8a02dc`，规格已同步并归档本 change。见 acceptance.md。

## Context and Orientation
核心在 src/services/jx3/jjc_peak_score_ranking.py、src/storage/mongo_repos/jjc_peak_score_ranking_repo.py、src/api/routers/jjc_ranking_stats.py。聚合 repo 已支持时间窗口，保持单一查询条件控制排序/计数。public/index.html 与 public/jjc-ranking-stats.html 必须一致。

## Plan of Work
service 加入可注入赛季配置，校验摘要所属赛季、读取有效结果，提供统一只读 load_for_anchor 与受控 generate_for_anchor(force)；读路径缓存超时只能使用正确窗口重新聚合，未知历史边界拒绝重算。存储 save_done 失败严格传播，不提前覆盖有效结果。路由主列表与详情都通过同一 loader。前端根据返回窗口展示口径、隔离内存缓存。

新增 scripts/rebuild_jjc_peak_score_rankings.py，默认 dry-run，按指定赛季枚举全部锚点，可显式选锚点；apply 强制重算两类分数，verify 检查缓存契约与每项比赛时间。上线前在受限 release 目录备份候选源码与所有目标结果，逐文件校验基线后替换，仅重启本 bot；原配置及其他服务不变。生产和本地差异单独保留。

## Concrete Steps
开发后执行 .venv/bin/python -m unittest tests.test_jjc_peak_score_ranking tests.test_jjc_ranking_stats_router tests.test_jjc_match_participant_repo tests.test_jjc_ranking_stats_frontend tests.test_jjc_data_center_navigation，加上定向重建及隔离 Mongo 测试；相关 .py 做 py_compile。子 agent 测试/前端各持有独立文件，主执行者整合。生产命令由新工具 --help 与实际容器挂载核对后执行，不照搬历史目录。

## Validation and Acceptance
用真实隔离 Mongo 验证同角色旧高分/本季低分重新排名、边界前后一秒、未来与无时间记录、旧缓存失效、历史保留、两分数/来源计数一致，并 explain 命中时间索引。生产修正后每项 match_time 都在实际窗口、开赛前来源 0；四范围分布和详情人数一致；重复 apply 可恢复但无重复文档。聚合失败不回退错误结果，写失败不得标记成功。

回滚保存按文件哈希校验的源码、两 HTML 和结果备份；异常先恢复服务，正确结果优先保留。原始比赛与参与者不删除。上线与验收证据独立记录，不以本地通过代替生产恢复。