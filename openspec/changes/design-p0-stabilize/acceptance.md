# P0 止血验收记录（acceptance.md）

日期：2026-11-26  
分支：`refactor/design-p0-stabilize`

## 验收结果

- [x] 启动不再自动 drop 唯一索引，定义不一致时仅记录错误并保留原唯一约束。
- [x] 本地胜场装备 3 个索引代码化声明并提供 `ensure_equipment_read_indexes` / `verify_equipment_read_indexes`。
- [x] `server_master_cache` 与 `jjc_role_recent` 移除无效数字 TTL 声明；`jjc_sync_role_queue` 启动仅维护 `idx_identity_key`。
- [x] `save_talent_snapshot` 修复 v1 -> v2 升级闭环且无字段冲突。
- [x] `upgrade_identity` 改用 `$addToSet` 防别名重复增长。
- [x] 对局退避期中断角色转 `cooldown` + `next_sync_after`，保水位且防空转；内置 worker/dispatcher 增加指数退避自愈监督；清理 4 个零调用死方法。
- [x] 修复 `config_manager` 读取错误吞没、`time_utils` 整年天数计算错误、`config.py` 默认 `MONGO_URI` 弱口令及 `requirements.txt` UTF-16 编码。
- [x] Python 3.9 与 Python 3.13 单元测试全部通过，未触碰在途 `feat/unify-visual-style` 修改文件。

## 回滚方式

切回基线 commit `8a21a2b` 对应源码并重启容器即可，无破坏性数据结构变更。
