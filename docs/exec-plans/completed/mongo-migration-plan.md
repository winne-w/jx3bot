# Mongo 迁移总体方案设计文本

## 1. 目标与原则
- 目标：将当前基于 JSON 文件的配置、缓存、历史数据迁移到 MongoDB，提升可扩展性与可维护性。
- 原则：
  - 业务层不直接依赖 Mongo 驱动，统一走 Repository 接口，保留未来切 MySQL 的能力。
  - 先“兼容迁移”再“完全切换”：迁移期间支持 JSON 与 Mongo 双实现。
  - API 保持现有统一响应格式：`{"status_code":0,"status_msg":"success","data":{}}`。
  - 排行榜采用“轻列表 + 按需详情 + 批量详情接口”，避免全量大包和 N+1 查询。

## 2. 现状与迁移范围
- 当前持久化介质：
  - `groups.json`（群绑定与推送开关）
  - `data/cache/*.json`（监控去重/状态缓存）
  - `data/wanbaolou_subscriptions.json`（订阅）
  - `data/cache/jjc_ranking_cache.json`、`data/cache/kungfu/*.json`（竞技缓存）
  - `data/jjc_ranking_stats/*.json`（统计快照）
- 迁移范围（优先）：
  1. 群绑定与推送配置
  2. 万宝楼订阅
  3. 服务器简称映射缓存
  4. 状态监控去重与状态历史
  5. JJC 排行榜与角色详情缓存
  6. 角色战绩历史（可选二期）

## 3. 数据模型（Mongo Collections）
### 3.1 配置与基础数据
- `group_bindings`
  - `_id`=`group_id`
  - `server`
  - `push_flags`: `kf/news/records/welfare/daily/jjc_ranking`
  - `updated_at`
  - 索引：`_id` 唯一，`server`

- `wanbaolou_subscriptions`
  - `_id`
  - `user_id`, `group_id`, `item_name`, `price_threshold`, `enabled`, `created_at`, `updated_at`
  - 唯一索引：`(user_id, group_id, item_name)`

- `server_aliases`
  - `_id`=`alias`
  - `master_name`, `zone`, `server_id`, `cached_at`, `expires_at`
  - TTL 索引：`expires_at`

### 3.2 JJC（重构后）
- `jjc_ranking_snapshots`
  - `_id`=`snapshot_id`
  - `season`, `week`, `generated_at`, `source_tag`, `member_count`
  - 索引：`generated_at desc`, `(season, week)`

- `jjc_ranking_members`（轻量）
  - `_id`
  - `snapshot_id`, `rank`, `role_id`, `role_global_id`, `role_name`, `server`, `score`, `detail_ready`
  - 索引：`(snapshot_id, rank)`，`(snapshot_id, role_global_id)`，`role_global_id`

- `role_profiles`（详情）
  - `_id` 建议 `role_global_id`（缺失时降级 `server:role_name`）
  - `role_id`, `role_global_id`, `role_name`, `server`, `zone`
  - `kungfu`, `kungfu_id`, `weapon`, `teammates`, `source`, `updated_at`
  - 索引：`_id` 唯一，`(server, role_name)`

- `role_jjc_history`（二期可上）
  - `_id`
  - `role_global_id`, `match_id`, `match_time`, `won`, `kungfu`, `raw_summary`
  - 索引：`(role_global_id, match_time desc)`，`match_id`
  - 可配置 TTL（如保留 90/180 天）

### 3.3 监控与去重
- `monitor_seen_items`
  - `_id`=`source:item_id`
  - `source`=`news|records|event_code`
  - `item_id`, `title`, `seen_at`, `published_at`
  - 索引：`(source, item_id)` 唯一

- `server_status_history`
  - `_id`
  - `server`, `status`, `zone`, `event_time`
  - 索引：`(server, event_time desc)`

## 4. 存储抽象与可切换设计
- 采用 Ports/Adapters：
  - `src/storage/ports.py`：定义 `GroupBindingRepo`、`SubscriptionRepo`、`JjcSnapshotRepo`、`RoleProfileRepo`、`MonitorRepo`、`ServerAliasRepo`
  - `src/storage/mongo_adapter/*`：Mongo 实现
  - `src/storage/json_adapter/*`：兼容现有 JSON 实现
  - `src/storage/factory.py`：按 `STORAGE_BACKEND` 选择实现（`json|mongo|mysql`）
- 业务层（services/plugins）仅依赖 ports，不直接调用 Mongo。

## 5. API 重构建议（JJC）
- `GET /api/jjc/rankings/latest`
  - 返回快照信息 + 轻量成员列表（分页）
- `GET /api/jjc/rankings/{snapshot_id}/members?page=&size=`
  - 分页轻量列表
- `POST /api/jjc/roles/details`
  - 入参 `role_global_ids[]`，批量返回详情（避免 N+1）
- `GET /api/jjc/roles/{role_global_id}/history?limit=20`
  - 角色历史（按需加载）

## 6. 迁移步骤（分阶段）
1. Phase A：引入存储抽象层与 Mongo 连接模块，不改业务逻辑。
2. Phase B：先切 `group_bindings`、`wanbaolou_subscriptions`、`server_aliases`（低风险）。
3. Phase C：切 `monitor_seen_items`、`server_status_history`。
4. Phase D：上线 JJC 新模型（快照/成员/详情分离）与新 API。
5. Phase E：停用旧 JSON 缓存路径，保留一次性回滚开关（`STORAGE_BACKEND=json`）。

## 7. 数据迁移与回滚
- 提供脚本：
  - `scripts/migrate_json_to_mongo.py`
  - `scripts/verify_migration.py`
- 迁移策略：
  - 先导入，再校验计数/抽样字段一致性，再切读路径。
- 回滚策略：
  - 配置开关回退 JSON。
  - Mongo 数据保留，不做 destructive 操作。

## 8. 性能与稳定性
- 索引先行；角色详情批量查询接口必须提供。
- 排行榜生成与详情补全解耦：列表先可用，详情异步补全。
- 设置连接池、超时、重试、日志上下文（命令/服务器/接口/request_id）。

## 9. 验收标准
- 现有命令行为不退化（绑定、推送、竞技查询、万宝楼订阅）。
- JJC 列表响应显著快于旧全量返回。
- 展开详情支持单查与批量查，平均响应稳定。
- 可通过配置切换 `json <-> mongo`，无需修改业务代码。

---

# 可让 AI 执行的 Prompt（可直接复制）

你是本仓库（`/home/songjingjing/codes/jx3bot`）的代码改造工程师。请按以下要求完成“迁移到 Mongo 的第一阶段改造”，并直接在仓库内落地代码与文档。

## 目标
1. 引入可插拔存储层，支持 `json` 与 `mongo` 两种后端（后续可加 mysql）。
2. 不改业务功能语义，先迁移：
   - 群绑定配置（原 `groups.json`）
   - 万宝楼订阅（原 `data/wanbaolou_subscriptions.json`）
   - 服务器简称缓存（原 `data/cache/server_master_cache.json`）
3. 保持 API 响应格式规范：`{"status_code":0,"status_msg":"success","data":{}}`。
4. 输出迁移说明文档和运行说明。

## 实施约束
1. 必须采用 Ports/Adapters：
   - `src/storage/ports.py`
   - `src/storage/factory.py`
   - `src/storage/json_adapter/*.py`
   - `src/storage/mongo_adapter/*.py`
2. 业务代码不得直接依赖 pymongo/motor；只能依赖 ports。
3. 默认后端为 `json`，通过环境变量 `STORAGE_BACKEND` 切换。
4. 新增依赖时同步更新 `requirements.txt` 与 `pyproject.toml`。
5. 不破坏现有命令入口与插件注册结构。
6. 新增代码使用 snake_case、四空格缩进、简洁日志。

## 具体任务
1. 新建存储抽象接口（group binding / subscription / server alias）。
2. 实现 JSON Adapter（复用现有文件路径与格式，保证兼容）。
3. 实现 Mongo Adapter（建议使用 `pymongo`，同步提供索引初始化函数）。
4. 加工厂与全局单例注入点（参考 `src/services/jx3/singletons.py` 风格）。
5. 替换以下调用点为存储接口：
   - `src/services/jx3/group_config_repo.py` 的使用路径
   - `src/plugins/status_monitor/commands.py` 的群配置读写
   - `src/plugins/wanbaolou/__init__.py` 的订阅读写
   - `src/services/jx3/server_resolver.py` 的简称缓存读写
6. 增加迁移脚本：
   - `scripts/migrate_json_to_mongo.py`（把现有 json 导入 mongo）
   - `scripts/verify_migration.py`（计数和样本校验）
7. 增加文档：
   - `docs/exec-plans/completed/mongo-migration-phase1.md`（设计、配置、索引、迁移、回滚）
   - README 增补“如何启用 Mongo”。

## 交付要求
1. 给出变更文件清单。
2. 给出关键设计说明（为什么这样分层）。
3. 给出本地验证步骤与命令。
4. 若存在未完成项，明确列出 blocker 和下一步。
