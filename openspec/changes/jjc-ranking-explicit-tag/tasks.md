# QQ 竞技排名 tag TDD 执行计划

## Purpose / Big Picture

实现 design.md 已确认用例：手动 tag 完全绕过时间标签查询及默认排行榜缓存，默认查询保持兼容。使用 Python 3.9+、NoneBot2、unittest；不增加依赖。用户已授权本轮直接执行并提交。

## Progress

- [x] 写入需求、方案、执行与测试计划。
- [x] A：service 测试先行、验证 RED、最小实现、验证 GREEN。
- [x] B：命令匹配和 handler 测试先行、验证 RED、最小实现、验证 GREEN。
- [x] C：主 agent 整合回归、文档同步、独立 review。
- [x] D：记录验证与验收结果、限定本需求提交。

## Surprises & Discoveries

已有代码使用 data.defaultWeek 而非标签列表最大值。整合回归在 Python 3.13 的 asyncio.Runner.close 阶段挂起；faulthandler 确认非业务断言失败，service 测试隔离 asyncio.to_thread 调度后正常退出，生产保持原调用方式。工作区存在其他需求未提交改动，config.py、README.md、runbook.md 已修改且含换行差异。

## Decision Log

用户 2026-10-09 确认方案并授权写入计划后进入开发，覆盖原先第二次确认要求。手动查询绕过默认缓存，不扩展存储。并行任务按文件分离，主 agent 统一提交；已存在的无关变更不暂存。提交历史无可用任务号，沿用本仓库既有 feat 中文标题格式，不虚构 Jira ID。当前是 feat/jjc-safe-live-refresh 功能分支，保留工作区以测试现有依赖，使用基线副本和定向补丁隔离提交内容，不切换或覆盖已有改动。

## Outcomes & Retrospective

开发与独立审查完成，63 tests 通过，记录已写入 test-plan.md、review.md、acceptance.md。QQ 在线验收未执行，保留 active change 待用户验收。

## Context and Orientation

config.py 定义命令正则；src/plugins/jx3bot_handlers/jjc_ranking.py 注册 handler 并将排名数据交给统计和 renderer；src/services/jx3/jjc_ranking.py 的 query_jjc_ranking 当前无参数并先读共享缓存；JjcApiClient 已支持整数 tag，无需修改。存储仓库无需改变。

## Plan of Work

任务 A 独占 src/services/jx3/jjc_ranking.py 与 tests/test_jjc_ranking_explicit_tag.py。先覆盖默认缓存/defaultWeek 基线，再新增显式 tag 测试；运行并记录缺少功能导致的失败。随后实现 query_jjc_ranking(self, tag: Optional[int] = None)，显式分支在任何缓存和外部调用前校验，省略参数分支保持原有逻辑。结果 defaultWeek 为实际 tag，手动查询不保存共享缓存。

任务 B 独占 config.py、src/plugins/jx3bot_handlers/jjc_ranking.py、tests/test_jjc_ranking_command_tag.py、tests/test_config_regex.py。先写命令别名、选项顺序、无效参数提示、透传与周次/存档测试并记录 RED。然后最小修改正则和 handler；无 tag 保持无参调用，有 tag 使用 query_jjc_ranking(tag=tag)。回调注解改为 Callable[..., Awaitable[dict]]。无效参数在开始统计提示和业务调用前拒绝。

任务 C 主 agent 修改 README.md、docs/references/runbook.md 说明命令与人工验收路径；合并两 agent 测试执行定向回归和语法检查，独立 reviewer 核对需求、分层、错误处理、缓存隔离及 diff。

任务 D 更新 test-plan.md、review.md、acceptance.md 与本文件进度。只暂存本需求新增文件、干净修改文件及已有脏文件中本需求增量。git diff --cached --check 和审阅暂存 diff 后提交；不 push。

## Concrete Steps

两个实现 agent 并行执行各自 RED → GREEN → REFACTOR，测试为真实 service/handler 控制流，外部 API、Mongo、发送和 renderer 使用隔离替身，禁止线上请求。RED 失败原因应是功能缺失，不是测试环境或拼写错误。通过后主 agent 运行 test-plan.md 的联合命令，review 有问题先补复现测试再修复。

## Validation and Acceptance

具体命令和矩阵见 test-plan.md。验收要求手动 tag 时零时间标签调用、零共享排行榜缓存读写，排行榜收到准确整数；QQ 非法输入不查询；图片周次与存档收到同一实际 tag；旧命令与定时任务默认调用兼容。回滚本需求提交，无数据库迁移。外部 QQ/推栏验证标注未执行及人工路径。
