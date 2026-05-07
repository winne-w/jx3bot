# JJC 排名统计角色下钻计划

状态：已实现/已验证，待提交
更新时间：2026-05-07

## 执行状态

- 2026-05-07：代码侧已具备角色下钻 API、600 秒被动缓存、按需对局详情缓存、统计页角色点击与对局详情弹窗、README 与 runbook 回归说明。
- 2026-05-07：确认“33”语义为 3v3 对局而非 33 条记录；默认窗口保持 20 条，并补充后端单测覆盖 `match_history` 请求 size 与 3v3 过滤。
- 验证已执行：`python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_match_detail_hydration`；`python -m py_compile src/api/routers/jjc_ranking_stats.py src/services/jx3/*.py src/storage/mongo_repos/jjc_inspect_repo.py`。
- 当前计划保持 active，待相关代码提交后再移动到 completed。

## 背景

`docs/tasks/in-progress/jjc-ranking-role-inspect.md` 已记录竞技场统计页角色下钻任务，但缺少可执行的阶段性计划。按当前文档规则，跨文件功能改动进入实现前需要在 `docs/exec-plans/active/` 下维护具体实施方案。

## 目标

- 在竞技场统计页支持点击角色查看最近 3v3 战绩和最近对局列表。
- 支持点击最近对局后按需查看单局详情。
- 角色战绩与对局详情均采用被动缓存，不在排名统计生成阶段预热。
- 首屏统计页仍只依赖 summary/details 数据。

## 非目标

- 不改变 JJC 排名统计 summary/details 的文件结构。
- 不把角色最近战绩或对局详情写入排名统计快照。
- 不新增主动预热任务。

## 涉及文件

- `src/api/routers/jjc_ranking_stats.py`
  - 新增或补齐角色下钻、最近对局、对局详情相关 HTTP 入口。
  - 仅做参数校验、统一响应封装和 service 转发。
- `src/services/jx3/`
  - 增加角色最近战绩查询编排、600 秒缓存策略和对局详情按需缓存编排。
- `src/storage/`
  - 复用或补充缓存仓储能力，避免新增裸文件读写。
- `public/jjc-ranking-stats.html`
  - 角色行点击、最近 3v3 战绩面板、最近对局列表和详情展示。
- `README.md`
  - 同步新增 API 或页面行为说明。
- `docs/references/runbook.md`
  - 补充手工回归路径。

## 实施步骤

1. 梳理现有统计页 API、service、storage 与前端调用链路。
2. 设计角色最近战绩查询返回结构，明确 `server + name` 缓存 key 和 600 秒 TTL。
3. 在 service 层实现最近战绩和最近对局查询编排，外部请求能力优先走现有 infra 适配。
4. 在 storage 层实现或复用被动缓存，不在统计快照内扩展预热字段。
5. 在 API 路由层新增参数校验和统一响应封装。
6. 更新统计页前端交互：角色下钻、对局列表、单局详情、加载态和错误态。
7. 同步 README 与 runbook。
8. 执行自动化检查和手工回归。

## 验证

自动化检查：

```bash
python -m py_compile src/api/routers/jjc_ranking_stats.py
python -m py_compile src/services/jx3/*.py
```

手工回归：

- 打开 JJC 排名统计页，确认首屏仍能加载 summary/details。
- 点击角色，确认展示最近 3v3 战绩和最近对局列表。
- 600 秒内重复点击同一 `server + name`，确认命中角色战绩缓存。
- 点击最近对局，确认可展示单局详情。
- 外部接口失败时，确认前端显示明确错误且不影响首屏统计展示。

## 风险与回滚

- 风险：外部接口不可用时下钻体验失败。需要 service 返回稳定错误结构，前端局部展示错误。
- 风险：前端一次性渲染过多详情导致页面卡顿。默认只在点击时加载单个角色或单场对局。
- 回滚：删除新增 API、service/storage 缓存方法和前端下钻入口，保留原统计 summary/details 页面行为。
