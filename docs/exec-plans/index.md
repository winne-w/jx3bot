# 执行计划索引

这里存放阶段性计划和技术债推进记录，按“进行中 / 已完成”组织。实现和验证完成但相关代码尚未提交时，计划仍放在 `active/`；代码提交后才移动到 `completed/`。

## Active

- `active/refactor-plan.md`: 当前主线重构、遗留问题和优先级
- `active/jjc-ranking-stats-mongo-migration-plan.md`: JJC 排名统计快照迁移 MongoDB、历史列表分页与文件 fallback 计划
- `active/jjc-role-recent-indicator-summary-plan.md`: JJC 角色 indicator 指标接口与 Mongo 缓存计划
- `active/jjc-role-recent-hydration-plan.md`: JJC 角色近期列表返回前统一按对局详情缓存补水计划

## Completed

- `completed/admin-command-help-plan.md`: 管理员命令帮助入口计划
- `completed/found-field-deprecation-plan.md`: `found` 字段降级与 `kungfu` 主判定改造计划
- `completed/jjc-match-data-sync-person-history-cache-plan.md`: JJC 对局同步先查 Mongo 身份、减少 person-history 请求计划
- `completed/jjc-match-detail-failure-policy-plan.md`: JJC 对局详情失败重试、不中断角色同步与 no data found 终态缓存计划
- `completed/jjc-match-data-sync-batch-plan.md`: JJC 对局同步批量领取、多轮执行与后台运行计划
- `completed/jjc-match-data-sync-plan.md`: JJC 官方接口对局数据同步、QQ 管理入口、时间水位续拉与重启恢复计划
- `completed/jjc-ranking-date-url-decoupling-plan.md`: JJC 排行榜日期选择不再依赖或写入 URL timestamp 计划
- `completed/jjc-ranking-role-inspect-plan.md`: JJC 排名统计页角色下钻、最近 3v3 战绩与对局详情按需缓存计划
- `completed/jjc-ranking-stats-split-plan.md`: JJC 统计页 summary/details 拆分、按需明细加载与历史数据迁移计划
- `completed/jjc-role-recent-cached-team-icons-plan.md`: JJC 角色近期对局列表展示已缓存详情双方心法图标计划
- `completed/jx3api-endpoint-migration-plan.md`: JX3API 接口地址切换、不可用接口降级与回归计划
- `completed/mongo-migration-plan.md`: MongoDB 迁移总体计划与阶段性落地记录
- `completed/role-identity-jjc-cache-plan.md`: 角色身份模型、JJC 缓存拆分、旧 `kungfu_cache` 迁移、运行时切换与最终清理计划
- `completed/skill-rework-api-plan.md`: 技改查询与推送接口切换到 JX3API `skill/rework` 计划
- `completed/jjc-sync-log-enhancement-plan.md`: JJC 同步日志增加角色昵称、服务器、对局时间输出
- `completed/jjc-match-detail-role-name-normalization-plan.md`: JJC 对局详情角色名规范化与历史数据修复计划
- `completed/jjc-weapon-quality-classification-plan.md`: JJC 橙武名称白名单、紫武模式与橙武占比口径统一计划
