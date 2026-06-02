# 执行计划索引

这里存放阶段性计划和技术债推进记录，按"进行中 / 已完成"组织。实现和验证完成但相关代码尚未提交时，计划仍放在 `active/`；代码提交后才移动到 `completed/`。

## Active

- `active/jjc-synced-matches-compact-refresh-all-server-plan.md`: JJC 对局查询紧凑列表、刷新按钮与全服候选计划
- `active/jjc-bot-managed-sync-workers-plan.md`: JJC bot 启动时按配置托管同步 worker 计划
- `active/refactor-plan.md`: 当前主线重构、遗留问题和优先级

## Completed

- `completed/jjc-query-timeout-diagnostics-plan.md`: JJC 对局查询超时阶段耗时诊断日志计划
- `completed/jjc-synced-matches-async-render-and-queue-state-plan.md`: JJC 对局查询异步展示与排队状态文案计划
- `completed/jjc-ranking-role-recent-cache-warmup-plan.md`: JJC 排名查询复用 match history 预热角色近期对局缓存计划
- `completed/jjc-synced-role-matches-index-and-participant-projection-plan.md`: JJC 已同步对局列表页面、identity-only 搜索、本地对局读取、页面入队与参与者投影回填脚本批次日志方案
- `completed/jjc-synced-match-list-page-plan.md`: JJC 已同步对局列表页面、identity-only 搜索、本地对局读取与页面入队方案
- `completed/jjc-synced-matches-not-found-guidance-plan.md`: JJC 对局查询未命中候选、引导、公告反馈与入口收敛计划
- `completed/jjc-synced-matches-server-select-plan.md`: JJC 对局查询页面服务器下拉选择计划
- `completed/jjc-display-copy-simplification-plan.md`: JJC 排名与已同步对局页面文案、地图名称和排队状态展示简化计划
- `completed/jjc-ranking-schedule-and-live-kungfu-plan.md`: JJC 排名统计时间与实时心法查询计划
- `completed/jjc-ranking-sleep-interval-plan.md`: JJC 排名心法查询 sleep 调整计划
- `completed/jjc-ranking-kungfu-defget-failure-fallback-plan.md`: JJC 排名心法在 defget 失败时继续使用已缓存对局胜场兜底计划
- `completed/jjc-ranking-sync-priority-plan.md`: JJC 排名统计触发同步队列优先级与同步成功归零计划
- `completed/jjc-identity-backed-sync-queue-plan.md`: JJC 对局保存后身份投影与基于 `role_identities._id` 的同步队列改造计划
- `completed/jjc-role-global-id-governance-plan.md`: JJC 角色 replay `global_id` 主键治理、防回流、重建与审计收敛总体计划
- `completed/jjc-sync-worker-queue-redesign-plan.md`: JJC 对局同步 worker 多进程队列、优先级和队列页面重设计计划
- `completed/jjc-ranking-kungfu-history-win-fallback-plan.md`: JJC 排名心法缺失时基于当前赛季已缓存对局胜场的保守兜底计划
- `completed/jjc-sync-queue-mode-filter-plan.md`: JJC 同步队列页面按入队同步类型筛选计划
- `completed/jjc-ranking-role-cache-ttl-plan.md`: JJC 排名角色弹窗后端缓存统一 24 小时计划
- `completed/jjc-sync-remove-person-history-global-role-id-plan.md`: JJC 同步移除 person-history 补 SK01 计划
- `completed/jjc-sync-indicator-local-identity-plan.md`: JJC 同步详情玩家 indicator 请求优先复用本地身份计划
- `completed/jjc-ranking-history-selector-plan.md`: JJC 排名历史列表按赛季、周次和结算状态筛选计划
- `completed/html-py-commit-ignore-plan.md`: 提交指定 HTML/Python 改动并忽略 JJC 审计输出目录计划
- `completed/admin-command-help-plan.md`: 管理员命令帮助入口计划
- `completed/found-field-deprecation-plan.md`: `found` 字段降级与 `kungfu` 主判定改造计划
- `completed/jjc-role-recent-indicator-summary-plan.md`: JJC 角色 indicator 指标接口与 Mongo 缓存计划
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
- `completed/announcement-system-plan.md`: 系统公告功能（数据库、API、QQ 管理命令、前端页面）实现计划
- `completed/jjc-match-qixue-tooltip-plan.md`: JJC 对局详情奇穴改为文字标签展示，悬浮浮窗显示奇穴描述
- `completed/frontend-github-link-plan.md`: 前端页面添加 GitHub 链接与 issue 入口计划
- `completed/jjc-role-recent-hydration-plan.md`: JJC 角色近期列表返回前统一按对局详情缓存补水计划
- `completed/jjc-ranking-scheduled-cache-warmup-plan.md`: JJC 定时统计预热页面 Mongo 缓存与 indicator 主动刷新计划
- `completed/tuilan-endpoint-lock-plan.md`: 推栏接口按端点互斥、不同端点并发计划
- `completed/jjc-ranking-cache-label-clarity-plan.md`: JJC 排名角色弹窗缓存文案澄清计划
- `completed/jjc-person-history-role-match-plan.md`: JJC person-history 身份补全增加角色级校验计划
- `completed/jjc-audit-duplicate-global-role-id-merge-plan.md`: JJC 审计脚本：同角色多 global_role_id 检测、合并与历史归档计划
- `completed/jjc-ranking-stats-mongo-migration-plan.md`: JJC 排名统计快照迁移 MongoDB、历史列表分页与纯 Mongo 读写计划
- `completed/jjc-role-identity-time-guard-plan.md`: JJC 角色身份写入入口统一时间保护计划
- `completed/jjc-role-identity-schema-normalization-plan.md`: JJC 角色身份表 indicator/backfill 写入 schema 归一化计划
- `completed/scripts-cleanup-plan.md`: 清理临时迁移、检查、修复、审计和备份恢复脚本
