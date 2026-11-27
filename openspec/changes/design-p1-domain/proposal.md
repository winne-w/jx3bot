# P1 统一领域规则层与消除反向依赖（design-p1-domain）

日期：2026-11-26  
分支：`refactor/design-p1-domain`（基于 `refactor/design-p0-stabilize`）  
关联评审：`design_review.md` 阶段 1

## 背景与目标

1. **单一心法目录**：消除 `config.py:KUNGFU_META`、`jjc_kungfu_meta.py`、`kungfu_aliases.py`、`jjc_ranking_display.py`、`jjc_ranking_equipment.py`、`singletons.py`、`jjc_ranking_stats.py` 之间的 5 份重复心法映射；在统计口径中按负责人确认将坦克心法（铁牢律、洗髓经、铁骨衣、明尊琉璃体）单独归入 `tank` 赛道，不再误归 DPS。
2. **统一角色名拆分与身份证据规则**：新建 `src/domain/role_name.py` 与 `src/domain/role_identity.py`，收敛“名字·服务器”拆分规则（仅在后缀匹配已知服务器时剥离，保护角色名中合法中点 `·`），修正 `kungfu.py:_replay_player_matches_role` 在显式 `role_id` 冲突时仍兜底同名匹配的串号隐患。
3. **消除 `storage -> services` 反向依赖**：将纯函数模块（身份匹配、快照哈希、赛季开赛时间解析）下沉至 `src/domain/`，`src/storage/mongo_repos/*` 改为仅依赖 `src/domain/`；原 `src/services/jx3/` 路径保留薄重导出以兼容存量调用与单测。
4. **工具与脚本公共层收敛**：新建 `src/utils/coerce.py` 统一类型转换/文本清洗；新建 `scripts/_common/mongo.py` 统一 9 个维护脚本的 Mongo URI 与库名解析，消除 `parse_season_start_timestamp` 复制。
