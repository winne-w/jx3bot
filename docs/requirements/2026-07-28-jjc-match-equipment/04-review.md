# 最近 3v3 对局装备查询 Review 记录

审查日期：2026-07-28（Asia/Shanghai）。审查范围为本需求已提交的生产代码、模板、单测及本次文档。

## 结论

离线审查未发现阻断项；自动化验证结果见 [测试记录](03-test-plan.md)。QQ 运行时和真实上游未冒烟，作为外部依赖风险保留，不能由本 review 声称已验证。

## 核对结果

- 分层：`queries.py` 只解析参数、调用 `JjcMatchEquipmentService` 并渲染/发送；身份、JX3API 与推栏编排位于 service/既有适配层，handler 未直接读 Mongo 或散写外部请求。
- 身份与同名保护：先取 `RoleIdentityRepo.find_best_by_name_with_id()`；缺少 `role_id`（兼容 `game_role_id`）或 `zone` 才调用 `/role/detail` 并通过 repo 回写。详情仅接受规范化后同服同名的唯一玩家，不以跨服同名兜底。
- 对局与失败语义：history 只采纳有效 `pvp_type/pvpType/type=3` 的记录并按时间倒序；身份、indicator、history、详情、目标玩家和装备缺失均返回明确错误。没有调用 `jjc_match_detail`、`jjc_equipment_snapshot` 或历史 Mongo 对局作为本查询 fallback。
- 并发与配置：外部 endpoint 通过 service 内的 asyncio lock 串行化；JX3API token 和推栏请求沿用既有 `config.py`/单例装配，需求新增文档未写入 token、ticket、Mongo URI 或其他凭据。
- 呈现与安全：模板标题、对局时间和固定文案说明数据是最近 3v3 对局快照、非实时面板；装备、属性和文案经 Jinja 自动转义，测试包含恶意 HTML/属性值。
- 文档一致性：运行手册改为成功/失败两条手工路径，明确非实时语义和无 Mongo 历史 fallback；方案、计划、测试和验收均使用相同口径。

## 剩余风险

真实角色身份可能过期、JX3API `/role/detail` 与推栏 indicator/history/detail 可能限流、失效或改变响应。离线测试无法证明 QQ 图片发送、Mongo 连接和真实数据的完整性；部署后应执行运行手册中的两条路径并观察错误提示与上游日志。出现问题时可回滚至本需求前的 matcher 不可用提示，不需要迁移或清理 Mongo 数据。
