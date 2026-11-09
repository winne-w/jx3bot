# 苍生铸世赛季配置更新

This execution plan is a living document and must be kept up to date according to `docs/PLANS.md`.

## Purpose / Big Picture

将当前 JJC 赛季切换为“苍生铸世”。用户已授权自行更新相关配置，并明确竞技场于 2026-11-05 开启、当周为第一周。沿用周一换周规则，2026-11-02 至 11-08 所在周为第一周，11-09 起为第二周。

## Progress

- [x] 检查配置、排名周次算法及同步、查询、参与者投影、最新对局刷新装配。
- [x] 核对官方资料片名称，并按用户指定的竞技场开放日期配置。
- [x] 更新配置及项目上下文。
- [x] 运行现有相关单测与新赛季日期边界离线冒烟。
- [x] 复核 diff，记录验收与回滚方式。
- [x] 按追加需求补齐近期对局、缓存、预热及心法对阵的当前赛季隔离。
- [x] 新增 10 个赛季隔离回归用例，并通过共 342 项相关测试。

## Surprises & Discoveries

Windows 工作目录仅存诊断材料，源码实际位于 WSL 仓库。`CURRENT_SEASON_START` 的消费者均为 JJC；排名周次按其所在周的周一计算，而同步、查询和投影将该日期按北京时间零点作为赛季边界。静态页面读取快照中的赛季和周次，无需硬编码赛季。

官网资料片于 10 月 29 日公测，竞技场开放日按用户明确指定的 11 月 5 日处理。不能用资料片公测日作为竞技场起点，否则本周会显示为第二周。赛季名称依据：[官方资料页列表](https://jx3.xoyo.com/list-2466-2.html)；[官网检索条目](https://jx3.xoyo.com/index/?from=androidqq)列出 10-29 公测新闻，直接读取首页时受动态页面限制。

## Decision Log

首轮为小范围配置维护，使用单文件计划，按用户“你看着更新”的授权执行。追加“对局历史只展示当前赛季”后，将近期记录和心法对阵隔离实现及回归纳入同一计划；保留自然周算法、上游 ISO week tag 和历史快照。新增测试验证历史隔离行为，不增加只断言配置字面值的测试。排名服务的赛季时间戳也固定为北京时间，避免预热与查询在 UTC 主机上相差 8 小时。

## Outcomes & Retrospective

2026-11-05 两轮本地实现与验证完成，随后按用户授权提交、推送并上线。首轮 171 项单测及 9 个临时日期冒烟通过。追加隔离需求后，15 组共 342 项相关测试全部通过，其中新增 10 项覆盖实际历史过滤、缓存、分页、预热和心法对阵。缺口已在业务层补齐，未修改历史数据。实现与测试计划已归档到 completed；用户已追加授权 commit、push、更新服务器代码并重启服务，发布记录随验收补充。

## Context and Orientation

`config.py` 定义赛季；`src/services/jx3/singletons.py` 将配置传给排名、同步、查询、参与者投影和最新对局刷新服务。`JjcRankingService.calculate_season_week_info()` 将上游 ISO week tag 转为赛季周次。项目存在无关的角色身份恢复改动，本次保留。

## Plan of Work

将 `CURRENT_SEASON` 改为“苍生铸世”，将 `CURRENT_SEASON_START` 改为 `2026-11-05`，注释明确该日期是竞技场开放日。同步 `PROJECT_CONTEXT.md` 的当前配置口径。验证开赛当天、首周末、下周一、第一周结算，以及北京时间赛季边界前后的对局归属。

用户追加授权：对局历史只展示当前赛季。继续在本计划完成这次赛季切换的遗漏收敛：`jjc_ranking_inspect.py` 对实时历史、分页及缓存命中统一按赛季起始时间过滤，缺少比赛时间的记录不作为本赛季记录展示；`jjc_ranking.py` 定时预热复用同一过滤与翻页规则。近期缓存 `data` 保存赛季名称及起点，读取时不接受旧赛季或无赛季标记缓存。`jjc_matchup.py` 在仓储查询前截断跨赛季时间区间，完全位于上赛季的请求返回空列表、零统计；`singletons.py` 注入边界。已同步列表已有赛季及时间双重过滤，保留该查询。仅隐藏旧历史，不清理或回填数据库。

为上述非简单配置行为增加回归用例，覆盖边界包含、时间字段别名、缺少时间、旧缓存失效、缓存命中安全过滤、全旧/混合页停止翻页、当前页使用原始记录数推进游标、预热与实时口径一致、心法对阵的时间与统计过滤。补充 `openspec/specs/jjc-ranking/spec.md`、数据库缓存字段说明及 runbook。主 agent 完成实现、测试和复核，不引入独立并行任务。

## Concrete Steps

运行 `.venv/bin/python -m unittest tests.test_config tests.test_jjc_ranking_explicit_tag tests.test_jjc_ranking_command_tag tests.test_jjc_match_participant_repo tests.test_jjc_match_participant_projection tests.test_jjc_match_data_sync tests.test_jjc_ranking_stats_repo tests.test_jjc_live_refresh tests.test_jjc_data_center_navigation`；临时脚本调用实际周次与投影函数，使用 mock 避免外部访问。运行 `.venv/bin/python -m py_compile config.py` 和 `git diff --check`。

追加回归与上述测试一并运行：`tests.test_jjc_current_season_history tests.test_jjc_ranking_inspect tests.test_jjc_matchup_service tests.test_jjc_matchups_router tests.test_jjc_inspect_repo tests.test_jjc_ranking_stats_router`。对本次修改的 4 个服务及新测试执行语法编译；复核仓储 `match_time` 为 `[start_time, end_time)`，确保跨赛季截断在聚合计数及分页前生效。

## Validation and Acceptance

预期 11-05 与 11-08 均显示第一周，11-09 当前 tag 显示第二周、上一周 tag 显示第一周结算；11-05 北京时间零点之前对局不归属新赛季，边界及之后归属“苍生铸世”。首轮实现仅修改本地仓库；用户后续授权发布后已受控重启生产 bot 及内部 worker，未执行生产数据回填。新赛季快照生成后页面自动出现新赛季。回滚仅恢复本次赛季配置和对应文档，不撤销其他工作区改动。

已通过的离线样本：11-05 21:00/tag 45 为“第1周 周4 21:00”，11-08 23:59/tag 45 为“第1周 周7 23:59”，11-09 00:00/tag 46 为“第2周 周1 00:00”，11-09 08:00/tag 45 为“第1周 结算”。跨年回归：2027-01-04/tag 1 为第10周，tag 53 为第9周结算。时间戳 `1793808000` 对应 2026-11-05T00:00:00+08:00；投影在该时刻前一秒不标新赛季，边界及后一秒标“苍生铸世”。

最终单测输出为 `Ran 342 tests ... OK`。语法编译和 `git diff --check` 均通过。新增用例先复现 7 个失败和 3 个错误，再完成实现；较大范围回归发现装配测试需要包含新增的边界参数，更新后全部通过。diff 复核确认改动落在配置、排名近期记录与预热、心法对阵、装配和对应测试/文档；无关身份恢复代码及已有工作区文件保持原状。回滚需同时恢复本次配置、4 个服务、测试和文档；缓存赛季标记为附加字段，无需迁移或删除旧数据。

## 生产发布（2026-11-05）

用户已明确授权本次提交、推送及服务器代码更新/服务重启。预检确认生产为 `jx3bot` 容器挂载宿主源码，内部 worker 数为 4，无独立 worker；当前运行配置与其他工作区改动保持原样。仅发布 `config.py` 和本次修改的 4 个服务文件：在生产副本上应用本次 delta，保留生产配置差异，处理 CRLF 上下文后补丁已检查通过。发布前创建私有备份并校验基线哈希，在生产依赖下验证候选；受控停止容器、原子替换 5 个文件并启动。重启后核对容器状态、配置、服务装配、周次、当前赛季列表及旧赛季查询空结果。若启动或关键检查失败，恢复本次 5 文件备份并重启。发布结果见下文。

### 发布与验收结果

代码提交 `1d78abaa9037460edf294902a69adfd7060af295` 已推送至 `origin/feat/jjc-safe-live-refresh`。本次仅提交 13 个赛季相关文件，其他角色身份恢复改动及已有工作区文件保持未提交。GitHub SSH 22 端口不可用，使用严格主机密钥校验的 SSH 443 通道完成推送。

生产 5 个源码文件以实际生产副本加本次 delta 部署，保留生产配置 helper 及所有运行配置。备份、manifest、原始日志与验证结果存放在服务器私有目录 `/mnt/sata6-1/jx3bot-releases/season-20261105-1d78abaa9037/`，含 `backup/`、`deployment.json`、`verification.json`、`worker-verification.json`。运行配置文件哈希未变，5 文件上线哈希与候选一致。

候选在生产 Python 3.9.9 下执行 342 项测试，新增 10 项全部通过；其余发现 3 项原有差异，分别是轻量刷新首屏历史合并与两个页面布局约束。将候选中的 5 文件恢复为发布前版本后重跑这 3 项，失败完全一致，确认是本次补丁之外的既有生产差异；没有扩展发布范围修改这些模块。排除已证明的 3 项基线失败后，339 项候选回归通过，0 errors、0 skipped。保留完整失败和基线复核证据，不将服务器验证表述为 342 项全绿。

生产容器于 `2026-11-05T08:02:32.887298323Z`（北京时间 16:02:32）重新启动；后续观察 `Running=true`、`RestartCount=0`、启动完成且无 Traceback。运行服务装配核实赛季为“苍生铸世”、起点 `2026-11-05`、边界 `1793808000`，本周输出“第1周”。4 个内部 worker 均重新加载并更新心跳。全局同步原本即为 paused，本次保持其原状态；不因发布自动恢复采集。

实际 HTTP 验收：上赛季时间区间的心法对阵列表与总数为 0；跨赛季区间的有效查询起点被限制为新赛季边界；抽查已有历史投影角色，本赛季列表为空、上赛季投影仍存在，证明隐藏而非删除。公网 `https://qike.rickchen.cn/jx3bot/api/jjc/matchups/search` 返回 HTTP 200、业务码 0、旧赛季总数 0。未触发全量排名统计、真实上游批量抓取或新赛季回填；排名页的新赛季快照由正常定时统计生成。
