# P0 止血技术方案（design.md）

## 1. MongoDB 索引安全、装备读索引声明与冗余索引收敛

### 1.1 唯一索引禁止自动 drop
- 位置：`src/infra/mongo.py:_ensure_indexes` 内 `_safe_index`。
- 规则：当同名索引已存在且 `key`、`unique`、`expireAfterSeconds`、`partialFilterExpression` 任一不一致时：
  - 若 `existing_unique or desired_unique` 为真，记录 `logger.error`（包含集合名、索引名、新旧定义），**直接返回，不执行 `drop_index` 与 `create_index`**，防止因 `DuplicateKeyError` 丢失唯一约束。
  - 若新旧均为普通非唯一索引（如 `jjc_match_facts.idx_active_combo_time` 的 `partialFilterExpression` 演进），保留原 `drop_index` + `create_index` 幂等收敛行为。

### 1.2 本地最新胜场装备读索引代码化声明
- 位置：`src/infra/mongo.py`。
- 新增常量 `EQUIPMENT_READ_V1_INDEXES`，精确对应 `docs/design-docs/database-design.md` 与 `jjc_inspect_repo.py` 的 `hint` 契约：
  - `idx_equipment_winner_latest_v1`: `[("equipment_winner_gids_v1", 1), ("equipment_read_time_v1", -1), ("equipment_match_id_v1", -1), ("_id", 1)]`
  - `idx_equipment_team1_state_time_source_v1`: `[("data.detail.team1.players_info.global_id", 1), ("equipment_read_valid_v1", 1), ("equipment_read_time_v1", 1), ("_id", 1)]`
  - `idx_equipment_team2_state_time_source_v1`: `[("data.detail.team2.players_info.global_id", 1), ("equipment_read_valid_v1", 1), ("equipment_read_time_v1", 1), ("_id", 1)]`
- 提供两个显式函数：
  - `ensure_equipment_read_indexes(db)`：幂等创建上述 3 个索引。
  - `verify_equipment_read_indexes(db) -> dict`：只读校验 3 个索引是否存在且 key 完全一致，返回 `{ready: bool, missing: [...], mismatched: [...]}`，供开启开关前预检使用。
- 在 `_ensure_indexes(db)` 中：仅当 `getattr(cfg, "JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0) == 1` 时自动调用 `ensure_equipment_read_indexes(db)`。这样默认关闭时不会在大表上意外触发首次构建阻塞启动，而新环境/恢复库开启开关启动时自动补齐索引，不会因 `hint` 缺失索引直接报错。

### 1.3 移除无效数字 TTL 声明与旧队列冗余索引
- `server_master_cache.idx_cached_at` 与 `jjc_role_recent.idx_cached_at`：字段为 int/float Unix 秒，MongoDB TTL 从未生效，去掉 `expireAfterSeconds` 参数，保留普通 `idx_cached_at` 索引（真正的 Date TTL 将在 P2 统一引入 `expires_at_dt`）。
- `jjc_sync_role_queue`：运行时已切换至 `jjc_sync_identity_queue`，启动时仅保留迁移幂等所需的 `idx_identity_key`（unique），不再在每次启动时声明其余 7 个旧运行索引（线上已有索引不主动删除，保证回滚兼容）。
- 同步更新 `docs/design-docs/database-design.md`。

## 2. 奇穴快照 `schema_version` 升级修复

- 位置：`src/storage/mongo_repos/jjc_match_snapshot_repo.py:save_talent_snapshot`。
- 根因：此前为规避 `$setOnInsert` 与 `$set` 同时写 `talents`/`schema_version` 引发的 MongoDB 路径冲突，误将二者仅留在 `$setOnInsert`，导致 v1 快照命中过期回源后无法写回 v2。
- 修复：`$setOnInsert` 仅保留 `{"created_at": now}`；`$set` 写入 `{"talents": talents, "schema_version": TALENT_SNAPSHOT_SCHEMA_VERSION, "last_seen_at": seen_at if seen_at is not None else now}`。新建与升级均单次 `update_one(..., upsert=True)` 原子完成且无字段路径冲突。

## 3. 角色身份升级别名去重

- 位置：`src/storage/mongo_repos/role_identity_repo.py:upgrade_identity`。
- 将 `"$push": {"aliases": current_identity_key}` 改为 `"$addToSet": {"aliases": current_identity_key}`，与 `_update_existing` 一致。

## 4. 同步对局退避防空转、后台监督自愈与死代码清理

### 4.1 非终态对局退避期间的角色延迟重排（保留水位正确性）
- 关键约束：当角色历史中某局处于 `failed`（退避中）或 `syncing`（被其他 worker 锁定）时，**不能直接跳过并推进角色同步水位**，否则水位越过该局后本角色后续增量同步会漏掉该局。
- 根因：`_sync_one_role` 捕获 `JjcSyncMatchDetailClaimError` 后调用 `_release_role_interrupted(..., requeue=True)`，仓储无条件将角色置为 `status="queued", next_sync_after=None`，导致下一轮 `claim_queued_role` 立即再次领取同一角色，6 小时退避期内每 ~10 秒从头翻页。
- 方案：
  1. `JjcSyncMatchDetailClaimError` 增加可选属性 `retry_after: Optional[float] = None`。
  2. `_sync_one_match_detail` 在 `claim is None` 且 `action != "skip"` 时计算建议重试时间：
     - `status == "failed"` 且 `detail_retry_after > now`：`retry_after = float(detail_retry_after)`；
     - `status == "syncing"` 且 `lease_expires_at > now`：`retry_after = min(float(lease_expires_at), now + 30.0)`；
     - 其余瞬时竞争或异常：`retry_after = None`。
  3. `_release_role_interrupted`、`release_identity_interrupted`、`release_role_interrupted` 新增可选关键字参数 `next_sync_after: Optional[float] = None`（向后兼容未支持该参数的测试替身，使用签名探测或默认参数）。
  4. 当 `requeue=True` 且 `next_sync_after is not None and next_sync_after > now` 时：将角色置为 `status="cooldown"`、`next_sync_after=float(next_sync_after)`、`queued_at=None`、`keep_front=False`，**不修改任何同步水位字段**。到期后由 `dispatch_queue_once -> enqueue_next_roles` 自动重新转入 `queued`。当 `next_sync_after is None` 时保持原有立即 `queued` 行为不变。

### 4.2 内置 worker 与 dispatcher 指数退避自愈监督
- 位置：`src/services/jx3/jjc_sync_worker_runtime.py`。
- `_run_worker` 与 `_run_dispatcher` 改为常驻监督循环：
  - 当 `run_worker` / `run_dispatcher` 抛出非 `CancelledError` 异常，或返回 `result.get("error") is True` 时，记录错误日志并按指数退避（默认初始 `1.0s`，上限 `60.0s`，模块级常量便于测试覆盖；若单轮运行存活超过 `60s` 则重置退避计数）等待后自动拉起。
  - 若 `run_worker` 因 `stopped_reason == "auto_paused"` 正常返回，等待 `idle_sleep`（默认 `10.0s`）后继续由 worker 循环观察全局暂停状态（或在管理员恢复后自动继续工作），不再让后台 task 永久死亡。
  - 收到 `asyncio.CancelledError` 时立即向上抛出，保证 `stop_jjc_sync_workers()` / `stop_jjc_sync_dispatcher()` 干净取消退出。

### 4.3 清理零调用死代码
- 删除 `src/services/jx3/jjc_match_data_sync.py` 中生产与测试均无引用的 `_sync_identity_snapshot_if_available`（仓储无 `sync_identity_snapshot` 方法）及 `_project_match_detail_if_configured` / `_project_match_detail_participants_if_configured` / `_clear_match_detail_participants_if_configured`（已被 `MatchDetailPersistenceService` 替代）。

## 5. 配置错误透出、时间计算修复与工程编码

- `src/plugins/config_manager.py`：`read_config_file()` 失败返回字符串，成功返回 `dict`；将 337 行与 379 行的 `startswith("配置文件")` 修正为 `isinstance(config_content, str)`，确保读取失败信息原样返回给管理员而非落入后续异常或被吞。
- `src/utils/time_utils.py:time_ago_filter`：`days = (time_difference.days % 365) % 30`，修正满整年时多算余数天的问题（例如 365 天前不再显示 `1年5天前`）。
- `requirements.txt`：从 UTF-16LE BOM（CRLF）重编码为标准 UTF-8（LF），内容与包版本保持不变。
- `config.py`：默认 `MONGO_URI` 改为无弱口令占位符的 `mongodb://127.0.0.1:27017/jx3bot`（环境变量 `MONGO_URI` 与 `runtime_config.json` 覆盖优先级保持不变；`TUILAN_SECRET_KEY` 与 `TUILAN_DEVICE_ID` 为客户端公开签名常量且单测直接依赖，保持兼容不置空）。

## 6. 风险与回滚

- 所有改动向后兼容现有 MongoDB 文档结构，无需停机迁移存量数据。
- 回滚方式：直接切回上一代码版本并重启进程；已升级为 `schema_version=2` 的奇穴快照与既有 reader 完全兼容；`status="cooldown"` 的中断角色在旧版本 dispatcher 下同样可按 `next_sync_after` 正常入队。
