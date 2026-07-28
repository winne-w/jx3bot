# 最近 3v3 对局装备查询测试记录

## 范围

离线测试覆盖角色身份仓储、最近 3v3 装备查询 service、渲染模型与模板、QQ handler，以及既有 JJC 详情快照水合和排名 inspect 回归。

`tests.test_jjc_match_equipment` 覆盖本地身份直用而不请求 JX3API、身份不足时 `/role/detail` 补齐并回写、只选最新有效 3v3、同服同名精确匹配、缺身份/历史/详情/装备和上游异常的稳定错误；也覆盖快照时间与装分拆分、完整装备/属性渲染、HTML 转义、异常集合归一化以及 handler 成功和失败分支。

`tests.test_role_identity_repo` 回归 JX3API 角色详情字段映射、身份强度与更新保护、global ID 优先级和候选身份选择。`tests.test_jjc_match_detail_hydration` 回归装备/奇穴快照拆分、水合、缺快照和不可用详情语义。`tests.test_jjc_ranking_inspect` 回归并发锁、详情投影、角色近期对局、indicator、已同步对局检索和本地投影无 fallback 行为。

## 自动化验证

执行日期：2026-07-28（Asia/Shanghai，20:39:11 起）。

```bash
python -m unittest tests.test_role_identity_repo tests.test_jjc_match_equipment tests.test_jjc_match_detail_hydration tests.test_jjc_ranking_inspect ; python -m py_compile config.py src/storage/mongo_repos/role_identity_repo.py src/services/jx3/jjc_match_equipment.py src/services/jx3/query_context.py src/services/jx3/singletons.py src/plugins/jx3bot_handlers/queries.py ; git diff --check
```

实际输出（测试期间的 warning 来自 mock 的异常/缺失数据分支）：

```text
.............[2026-07-28 20:39:11,010 nonebot] WARNING: 归档角色身份旧画像失败: identity_key=global_id:99999 replaced_by=global_id:99999 error=archive down
....................................[2026-07-28 20:39:11,101 nonebot] WARNING: 装备快照缺失: match_id=300 equipment_snapshot_hash=h_missing
.[2026-07-28 20:39:11,103 nonebot] WARNING: 奇穴快照缺失: match_id=301 talent_snapshot_hash=t_missing
......................[2026-07-28 20:39:11,230 nonebot] WARNING: JJC 对局详情身份投影失败: match_id=12345 source=inspect_cache_miss error=projection failed
..................[2026-07-28 20:39:11,262 nonebot] WARNING: JJC 已同步对局参与者投影查询失败: server=梦江南 name=示例角色 page=1 page_size=20 identity_id=6a68a2efdd95910b20b1720e global_id=987 error=projection_down
.............[2026-07-28 20:39:11,274 nonebot] WARNING: 批量读取 JJC 对局参与者投影摘要失败: error=object MagicMock can't be used in 'await' expression
......................................
----------------------------------------------------------------------
Ran 141 tests in 0.852s

OK
warning: LF will be replaced by CRLF in docs/requirements/2026-07-28-jjc-match-equipment/02-execution-plan.md.
The file will have its original line endings in your working directory
```

`py_compile` 没有 stdout/stderr；`git diff --check` 除上面的 Git 行尾提示外没有报告空白错误。整条命令退出码为 0。

## 手工回归与外部依赖

QQ/OneBot 线上手工冒烟状态：**待执行**。本次未执行 QQ/OneBot 运行时冒烟，也未发起需要真实 token、推栏 ticket、Mongo 数据和真实角色的直接在线 service 调用，避免输出凭据或把本地环境状态误当成线上结果。因此线上成功图、失败文本和上游联通性仍未验证。

部署后按 [运行手册](../../references/runbook.md) 的成功与失败路径回归：有近期 3v3 的角色必须生成明确标注为非实时的图片；未知/无身份/无 3v3 的角色必须直接得到失败文本，并确认不读取 Mongo 历史对局或装备快照作为 fallback。
