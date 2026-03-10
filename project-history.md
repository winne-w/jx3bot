# Project History

更新时间：2026-03-10

本文记录已经发生的重要演进，避免“为什么变成现在这样”只存在于提交记录和口头记忆中。

## 已知历史阶段

### 早期阶段

- 项目以 NoneBot 机器人为核心，围绕剑网 3 查询能力持续叠加功能
- 很多业务最初集中在单插件和工具模块中，适合快速交付，但边界逐渐变得模糊

### 分层重构启动

- `src/plugins/jx3bot.py` 开始从“巨型功能文件”转向“入口 + handler 注册”
- `src/plugins/jx3bot_handlers/` 被引入，用于承接消息命令的表现层逻辑
- `src/services/jx3/` 被引入和扩充，用于承接业务编排和缓存策略
- `src/infra/` 开始承担 HTTP、截图、第三方接口等外部适配
- `src/storage/` 被引入，用于统一存储访问边界

### 状态监控拆包

- 原 `status_monitor.py` 已拆为模块包
- 调度、命令、通知、缓存逻辑已不再堆在单文件中
- 但缓存访问与通知边界仍在继续收口

### 文档体系重建

- `AGENTS.md` 从“大而全说明书”改为导航入口
- 增加了长期知识文档：
  - `project-architecture.md`
  - `project-roadmap.md`
  - `project-history.md`
- 增加了分层知识目录：
  - `docs/design-docs/`
  - `docs/exec-plans/`
  - `docs/references/`
  - `docs/tasks/`

## 当前已知遗留

- 仓库里仍有部分调试式输出和历史兼容层
- 许多运行验证仍依赖在线接口和手工回归
- 历史模块虽然已拆层，但尚未完全收口

## 2026-03 Mongo 缓存迁移首轮落地

- 为 `src/storage/` 补齐了 Mongo settings、provider、ports、singletons 和首批 adapter
- 把首批计划范围内的缓存与运行态数据接到 Mongo 主路径：
  - `status_monitor` JSON 缓存
  - `server_data`
  - `server_master_cache`
  - `jjc_ranking_cache`
  - `jjc_kungfu_cache`
  - `group_reminders`
  - `wanbaolou_subscriptions`
  - `jjc_ranking_stats`
- 把第二批中的 `wanbaolou_alias_cache` 和 `baizhan_data.json` 也接入 `cache_entries`
- 增加了 `scripts/mongo_backfill.py` 与 `scripts/mongo_verify.py`，可执行真实回填与核对
- 迁移策略当前停留在“Mongo 优先读取、文件回退、过渡期双写”，尚未进入单写清理阶段
- 为迁移路径补了一组最小 `unittest`，覆盖 repo CRUD、API fallback、脚本映射和第二批缓存接入

后续出现重要结构变化时，应在本文追加新阶段，而不是只修改现状描述文档。
