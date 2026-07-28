# 最近 3v3 对局装备查询验收记录

验收日期：2026-07-28（Asia/Shanghai）。

## 已交付内容

`属性/装分` 已改为查询目标角色最近一场 3v3 对局的装备与属性快照：本地身份优先，字段不足时用 JX3API 角色详情补齐并回写；随后以推栏 indicator、history、detail 获取最新有效 3v3，并按同服同名精确定位玩家。成功图片包含对局时间、装备、属性和装分拆分，并固定声明其不是当前实时面板。失败不读取 Mongo 历史对局、详情或装备快照作为 fallback。

## 验收证据

2026-07-28 20:39（Asia/Shanghai）执行以下完整命令，退出码为 0：

```bash
python -m unittest tests.test_role_identity_repo tests.test_jjc_match_equipment tests.test_jjc_match_detail_hydration tests.test_jjc_ranking_inspect ; python -m py_compile config.py src/storage/mongo_repos/role_identity_repo.py src/services/jx3/jjc_match_equipment.py src/services/jx3/query_context.py src/services/jx3/singletons.py src/plugins/jx3bot_handlers/queries.py ; git diff --check
```

结果为 `Ran 141 tests in 0.852s`、`OK`；编译检查没有输出，`git diff --check` 没有空白错误（仅显示 Git 的 CRLF 提示）。完整原始输出和测试覆盖见 [03-test-plan.md](03-test-plan.md)。

## 线上验收与风险

QQ/OneBot 线上手工冒烟验收状态：**待执行**。本次未启动 QQ/OneBot 运行时，未声明 QQ runtime smoke；也没有进行需要真实 token/ticket 的在线 service 调用。因此没有真实角色的成功图片或失败文本可记录，相关验收状态为未验证，而不是失败或通过。

上线后必须分别执行：

1. 对有近期 3v3 的角色运行 `属性 <服务器> <角色>`，确认图片和非实时快照声明。
2. 对未知、身份不足或无近期 3v3 的角色运行相同命令，确认直接提示且无 Mongo 历史 fallback。

主要外部风险是 Mongo、JX3API `/role/detail`、推栏 indicator/history/detail 的可用性、数据延迟和接口响应变化。若需紧急回滚，恢复本需求前 `属性/装分` 的不可用提示即可；本需求没有新增集合、索引或迁移，Mongo 既有身份补齐数据无需回滚。
