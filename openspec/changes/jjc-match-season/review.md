# JJC 对局赛季归属与查询隔离 Review 记录

## Review Checklist

- [x] 分层边界符合 `PROJECT_CONTEXT.md` 和相关架构文档
- [x] 外部依赖通过 `infra` / `storage` / `renderers` 等边界接入
- [x] 配置项、密钥和内网地址没有在本次新增代码中硬编码
- [x] Mongo、索引、迁移和兼容策略已同步记录
- [x] 自动化测试和 Mongo dry-run 门禁覆盖核心风险
- [ ] 真实 Mongo 回填与页面冒烟待环境恢复后完成

## Findings

- High（已修复）：最初列表仅按 `season_id` 筛选，误标的历史行仍可能泄漏。现已把 `season_start_time` 从 singleton 经 service/repo 传到 Mongo 查询，并强制 `match_time >= season_start_time`。
- Medium（已修复）：最初回填脚本未统计批量写入失败，部分失败可能没有最终统计。现已捕获 `BulkWriteError` 和批次异常，累计 `failed`、输出错误，并以非零退出码结束。
- 未发现本次新增的硬编码凭据或 Python 3.9 注解兼容问题。

## Follow-ups

- 在可连接目标 Mongo 的环境中，按 dry-run、apply、verify-only 顺序完成回填。
- 更新未来赛季配置后，重启 bot 使 singleton 注入的新赛季名称与起始时间生效。

## Approval

代码审查已完成；真实 Mongo 回填与页面冒烟仍待环境可用。
