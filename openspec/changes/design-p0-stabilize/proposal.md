# P0 止血与高风险缺陷修复（design-p0-stabilize）

日期：2026-11-26  
分支：`refactor/design-p0-stabilize`（基于 `origin/main` `8a21a2b`）  
关联评审：`design_review.md` 阶段 0

## 背景与目标

基于全仓代码与 MongoDB 设计评审结论，项目存在若干无需大范围结构搬迁即可独立修复的正确性、数据安全与运行稳定性缺陷（P0 止血阶段）：

1. **启动索引保护与声明补齐**：`src/infra/mongo.py:_ensure_indexes` 在索引定义变更时无条件先 `drop_index` 再重建，若唯一索引遇到存量重复数据重建失败，系统会在丢失唯一约束的状态下继续运行；`jjc_match_detail` 被 `hint` 强制指定的 3 个本地胜场装备索引缺少代码侧统一声明与校验入口；数字时间戳字段上的无效 TTL 声明与旧队列 `jjc_sync_role_queue` 的 7 个废弃运行索引每次启动仍在维护。
2. **奇穴快照版本升级闭环**：`JjcMatchSnapshotRepo.save_talent_snapshot` 将 `talents` 与 `schema_version` 放在 `$setOnInsert` 中，导致存量 `schema_version < 2` 的快照在回源重拉后仍无法升级为 v2，相关对局每次读取均重复回源。
3. **身份别名幂等去重**：`RoleIdentityRepo.upgrade_identity` 使用 `$push` 追加 `aliases`，重复升级路径会产生重复别名；统一改为 `$addToSet`。
4. **对局同步失败退避防空转与后台任务自愈**：单场对局进入 `failed`（最长 6 小时退避）或被其他 worker 持有租约时，角色被中断后立即回到 `queued` 且 `next_sync_after=None`，导致同一角色每约 10 秒从 `cursor=0` 重复翻页空转；`jjc_sync_worker_runtime` 的内置 worker 与 dispatcher 遇到未预期异常退出后无指数退避自愈监督；`jjc_match_data_sync.py` 残留零调用死代码。
5. **配置错误透出、时间工具修正与工程卫生**：`config_manager.py` 读取配置文件失败返回 `"读取配置文件失败: ..."`，调用方却判断 `startswith("配置文件")` 导致错误被吞；`time_utils.time_ago_filter` 计算天数未先扣除年份（`days % 30`）；`requirements.txt` 为 UTF-16LE 编码；`config.py` 默认 `MONGO_URI` 含示例弱口令 `root:password`。

## 非目标

- 本阶段不引入 `src/domain/`（归入 P1）。
- 本阶段不迁移附属缓存主键或删除 `role_*` 兼容方法（归入 P2）。
- 本阶段不拆分大类或触碰 `feat/unify-visual-style` 在途修改的模板、前端页面、截图与渲染文件（归入 P3 / P5）。
