# P1 统一领域规则层审查与验收记录（review.md & acceptance.md）

日期：2026-11-26  
分支：`refactor/design-p1-domain`

## 审查与验收结论：通过

- [x] `src/domain/kungfu_catalog.py` 成为 33 心法单一事实源（含 4 坦克心法与 `问水诀`，保留 32 心法 JJC 对阵目录过滤与导入期冲突校验）。
- [x] `config.KUNGFU_META`、`jjc_kungfu_meta`、`kungfu_aliases`、`jjc_ranking_display`、`jjc_ranking_equipment`、`singletons`、`jjc_ranking`、`jjc_ranking_stats` 全部统一派生；坦克心法在排名与峰值统计中归入独立 `tank` 赛道。
- [x] `src/domain/role_name.py` 统一“名字·服务器”拆分与后缀剥离，保护含中点 `·` 角色名。
- [x] `src/domain/role_identity.py` 与 `kungfu.py` 消除显式 `role_id` 冲突时兜底同名匹配的串号漏洞。
- [x] `src/storage/` 对 `src/services/` 反向依赖降为 0；`src/domain/` AST 依赖守护测试纳入常驻单测。
- [x] `scripts/_common/mongo.py` 收口 9 个维护脚本的连接与库名解析。
- [x] 未触碰 `feat/unify-visual-style` 在途修改的模板与前端文件。
