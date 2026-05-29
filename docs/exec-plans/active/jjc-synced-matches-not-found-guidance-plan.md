# JJC 对局查询未命中引导与页面入口收敛计划

## 背景

`public/jjc-synced-matches.html` 当前只支持按服务器和角色名精确查询已同步身份。若 `role_identities` 中没有同服同名记录，页面只展示固定未找到提示，用户无法发现其他服务器同名角色、带 `@` 后缀的历史角色名，也不知道可以通过同步对局过的角色来间接拉取目标角色信息。页面右上角还保留同步队列入口，和当前查询页主流程不一致。

## 目标

1. 当精确查询未命中时，后端返回候选角色：同名其他服务器、同服/其他服务器中基础名相同且带 `@` 后缀的角色。
2. 前端未命中空态展示候选列表，用户可直接点击候选重新查询。
3. 前端未命中空态增加引导：如果目标角色完全未收录，可搜索和他打过 3v3 的角色，并通过同步该角色对局把目标角色投影进本地身份库。
4. 将公告弹窗和反馈悬浮入口加入 JJC 对局查询页，复用排行榜页现有 API 与交互风格。
5. 移除页面上的同步列表入口。

## 非目标

- 不改动 JJC 同步队列后端行为和同步列表页面。
- 不新增数据库集合或迁移脚本。候选查询若需要稳定使用 `normalized_name` 前缀匹配，可补充 `role_identities.normalized_name` 普通索引并同步数据库设计文档。
- 不主动调用外部接口为未命中角色实时补数据，仍只基于本地 `role_identities` 候选和用户手动同步入口。

## 变更方案

### 后端

- `src/storage/mongo_repos/role_identity_repo.py`
  - 新增候选查询方法，按规范化姓名查询：
    - `normalized_name == 查询名` 且服务器不同。
    - `normalized_name` 以 `查询名 + @` 开头，用于匹配带后缀的历史角色名。
  - 查询结果在 Mongo 聚合内按是否同服、身份强度、最近更新时间排序，再限制返回数量，避免先截断导致高质量候选遗漏。
- `src/infra/mongo.py`
  - 为 `role_identities.normalized_name` 增加普通索引，支撑同名跨服查询和 `@` 后缀前缀匹配。
- `docs/design-docs/database-design.md`
  - 同步记录新增 `idx_normalized_name` 索引。
- `src/services/jx3/jjc_ranking_inspect.py`
  - 新增候选序列化，复用已有 `_serialize_identity`，只返回前端需要的 `server/name/identity/sync_status/reason`。
  - `resolve_synced_role` 未命中时携带 `candidates` 和引导文案，不调用 live ranking 或推栏接口。
- `src/api/routers/jjc_ranking_stats.py`
  - 维持统一错误响应格式；错误 `data` 中透传 `candidates`。

### 前端

- `public/jjc-synced-matches.html`
  - 移除右上角“更新进度”链接和相关 query 参数处理。
  - 未命中状态渲染候选角色列表，点击候选写入服务器与角色名并重新查询。
  - 空态增加对局同步引导文案。
  - 增加公告弹窗、公告列表分页、localStorage 已读记录、反馈悬浮按钮。
  - Escape 和遮罩点击关闭公告弹窗；不影响对局详情弹窗。

### 测试与验证

- 增加/更新 `tests/test_jjc_ranking_inspect.py`，覆盖精确未命中时返回候选且不调用 live source。
- 增加/更新 `tests/test_role_identity_repo.py`，覆盖候选查询空名称、同服精确命中排除、同名跨服、`@` 后缀和确定性排序。
- 运行：
  - `python -m unittest tests.test_jjc_ranking_inspect tests.test_jjc_ranking_stats_router`
  - `python -m py_compile src/services/jx3/jjc_ranking_inspect.py src/storage/mongo_repos/role_identity_repo.py src/api/routers/jjc_ranking_stats.py`

## 风险与回滚

- 候选查询可能返回重名角色，需要前端明确标注服务器和匹配原因，避免用户误选。
- 新增 `idx_normalized_name` 会在 Mongo 初始化时幂等创建；首次创建可能占用少量后台资源，回滚时可撤回代码和数据库设计记录，线上索引可保留为无害冗余索引或按运维窗口删除。
- 回滚方式：撤回候选查询方法、`resolve_synced_role` 未命中 payload 变更和 `public/jjc-synced-matches.html` 页面新增交互。

## 执行记录

- 2026-05-27：创建计划，准备实现。
- 2026-05-27：已实现候选查询、未命中空态引导、公告反馈入口和同步列表入口移除；已补充 inspect service 单测并通过计划内验证。
- 2026-05-27：按评审意见修正候选查询：新增 `idx_normalized_name`，将排序前移到 Mongo 聚合，补充 RoleIdentityRepo 候选行为单测。
- 2026-05-27：第二轮评审修正：候选去重改为按规范化服务器+角色名保留 Mongo 排序中的最佳身份；修正单测 fake aggregate 混合排序方向并补充同角色重复身份与升序 tie-break 覆盖。验收命令已通过。
- 2026-05-27：第四轮评审修正：`find_synced_match_page_candidates` 在 `$group` + `$replaceRoot` 后新增基于候选 helper 字段的确定性 `$sort`，再执行最终 `$limit`；单测 fake aggregate 主动打乱 `$group` 输出顺序并断言最终排序位置。验收命令已通过。
