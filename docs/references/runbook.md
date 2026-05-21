# 运行与回归手册

更新时间：2026-05-07

本文面向维护者和 agent，记录当前仓库可执行的启动方式、验证命令和常见排查路径。

## 运行方式

### 本地 Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

前提:

- `config.py` 已配置
- MongoDB 已启动且 `runtime_config.json` 中 `MONGO_URI` 配置正确
- OneBot 反向 WebSocket 已准备完成

### 模拟容器入口

```bash
bash start.sh
```

该脚本会:

1. 创建 `/app/mpimg`
2. 检查并补装少量运行依赖
3. 启动 `mpimg/` 的静态 HTTP 服务
4. 启动 `python bot.py`

### Docker Compose

```bash
docker compose up --build -d
docker compose logs -f
```

## 关键配置

### 必备文件

- `config.py`

### 必备服务

- MongoDB（连接串通过 `runtime_config.json` 中的 `MONGO_URI` 配置）

### 常用环境变量

- `HOST`
- `PORT`
- `TZ`

## 最小验证集

这些命令不覆盖全部功能，但能快速发现明显损坏:

```bash
nb plugin list --json
python test_tuilan_match_history.py
```

说明:

- `nb plugin list --json` 用于确认插件仍能被 NoneBot 发现
- `test_tuilan_match_history.py` 依赖在线接口，失败时要先区分是代码回归还是外部服务异常

## 手工回归清单

### 1. 启动与初始化

- 启动后确认没有明显导入错误
- 观察缓存初始化日志，确认 `server_data.json`、竞技缓存、token 缓存、MongoDB 连接路径正常
- 若启用定时任务，观察 APScheduler 是否频繁 misfire

### 2. 基础命令

- `帮助`
- `更新`
- `活动`
- `技改`
- 管理员帮助：`/管理帮助`

预期:

- 能返回文本或渲染结果
- 无明显堆栈报错
- `/管理帮助` 只有 `config.py` 中 `ADMIN_QQ` 管理员可查看，返回 `/重启`、`/查看配置`、`/修改配置`、`/公告添加`、`/公告列表`、`/公告删除`、JJC 同步等管理命令用法

### 3. 交易行与万宝楼

- `交易行 <物品>`
- 相关万宝楼查询/订阅命令

预期:

- 外部接口成功时能返回价格信息
- 失败时返回可理解错误，而不是直接抛异常

### 4. 名片

- `名片 <角色>`
- `名片 <服务器> <角色>`

预期:

- 首次可生成或下载图片
- 再次查询应能复用缓存
- `mpimg/` 路径和图片访问 URL 正常

### 4.1 JX3API 查询回归

- `烟花 <角色>`
- `烟花 <服务器> <角色>`
- `奇遇 <角色>`
- `奇遇 <服务器> <角色>`
- `答题 <题目关键词>`
- `骗子 <QQ号>`
- `开服`
- `属性 <角色>` / `装分 <角色>`
- `副本 <角色>` / `秘境 <角色>`
- 管理员执行 `/查看配置`

预期:

- 烟花、奇遇、名片、答题、骗子、开服命令应访问当前 JX3API 地址，不再请求旧 404 地址
- `属性/装分` 返回装备查询接口暂不可用提示，不继续请求旧装备属性接口
- `副本/秘境` 返回副本查询接口暂不可用提示，不继续请求旧团队 CD 接口
- `/查看配置` 中 `token剩余` 无接口数据时显示 `未知`，不影响启动缓存初始化

### 5. 竞技相关

- `竞技查询`
- `竞技排名`
- `竞技排名 拆分`
- 添加角色：`/jjc同步添加 <服务器> <角色名> [global_role_id=...] [role_id=...] [zone=...]`
- 查看状态：`/jjc同步状态`
- 触发一轮同步：`/jjc同步开始 [default|full|incremental]`
- 暂停后续同步：`/jjc同步暂停 [原因]`
- 恢复同步：`/jjc同步恢复`
- 重置角色水位：`/jjc同步重置 <服务器> <角色名>`

预期:

- service 能返回结构化数据
- renderer 能生成图片
- 统计文件写入 `data/jjc_ranking_stats/`
  - 新结构优先写入 `data/jjc_ranking_stats/<timestamp>/summary.json`
  - 明细按需拆分在 `data/jjc_ranking_stats/<timestamp>/details/`
  - 历史兼容阶段可能仍存在旧的 `data/jjc_ranking_stats/<timestamp>.json`
- JJC 同步命令只有 `config.py` 中 `ADMIN_QQ` 管理员可执行
- `/jjc同步开始` 只触发一轮同步，不会启动常驻任务
- JJC 最终身份主键为 replay 数字 ID：`global_id:{global_id}`；`global_id` 来自 `/3c/mine/match/replay` 的 `players[].global_role_id`，不要与 SK01 `global_role_id` 混用。
- `global_role_id` 专指 `/role/indicator` 返回的 `SK01-...`，用于请求 `match/history`；角色缺少 SK01 且队列中已有 `person_id` 时，同步前仍保留 `mine/match/person-history` 兼容兜底。
- 同步详情应写入现有 `jjc_match_detail`，并从详情玩家回填 `jjc_sync_role_queue`；详情玩家身份补全主链路为 `match/detail + match/replay + role/indicator`，成功拿到 replay `global_id` 与 SK01 `global_role_id` 后才写入可执行同步队列。
- 单条详情临时失败不会中断当前角色同步，`/jjc同步开始` 输出中的 `详情失败` 表示对局详情已写入失败状态并等待 `detail_retry_after` 后重试
- 推栏返回 `code=-1`、`msg=no data found`、`data=null` 时，对局写入 `detail_unavailable` 终态；`/jjc同步开始` 输出中的 `详情不可用` 表示后续不会重复请求该对局详情
- 若状态中最近错误出现 `role_identity_not_found`，优先检查目标角色是否已能通过最近对局 replay 补到 `global_id`；仅缺 SK01 `global_role_id` 时再用带 `global_role_id=...` 的添加命令补充 history 请求字段。
- 若服务中断后状态长期存在 `syncing` 或 `detail_syncing`，再次执行 `/jjc同步开始` 会先恢复过期租约再领取角色

离线自动验证：

```bash
python -m unittest tests.test_jjc_match_data_sync_handler tests.test_jjc_match_data_sync tests.test_jjc_sync_repo
python -m unittest tests.test_jjc_match_detail_snapshots tests.test_jjc_snapshot_repo tests.test_jjc_match_detail_hydration tests.test_scripts_jjc_snapshot
python -m py_compile src/services/jx3/jjc_match_data_sync.py src/storage/mongo_repos/jjc_sync_repo.py src/plugins/jx3bot_handlers/jjc_match_data_sync.py src/infra/mongo.py
```

在线手工回归需要真实 QQ/推栏环境：先 `/jjc同步添加 <服务器> <角色名>`，再 `/jjc同步状态`、`/jjc同步开始 incremental`、`/jjc同步状态`，确认角色被领取、对局详情写入、单条详情失败时仍继续处理后续对局和后续页。

JJC 身份治理备份 / 恢复：

```bash
# 备份前 dry-run，默认覆盖 role_identities / jjc_sync_role_queue / role_jjc_cache / jjc_role_indicator / jjc_match_detail
python scripts/backup_jjc_role_identity_collections.py

# 执行备份，tag 不传则使用当前时间戳
python scripts/backup_jjc_role_identity_collections.py --tag before_global_id_20260521 --apply --yes

# 恢复前 dry-run
python scripts/restore_jjc_role_identity_collections.py --tag before_global_id_20260521

# 执行恢复；恢复前会先把当前目标集合备份为 *_pre_restore_backup_<时间戳>
python scripts/restore_jjc_role_identity_collections.py --tag before_global_id_20260521 --apply --yes

# 清理前 dry-run，默认只清 role_identities / jjc_sync_role_queue
python scripts/clear_jjc_role_identity_collections.py --backup-tag before_global_id_20260521

# 执行清理，要求备份集合已存在
python scripts/clear_jjc_role_identity_collections.py --backup-tag before_global_id_20260521 --apply --yes
```

预期:

- 备份集合命名为 `<原集合>_backup_<tag>`，保留原 `_id`。
- 恢复前会自动创建 `<原集合>_pre_restore_backup_<tag>`，再 drop 目标集合并从备份集合复制回来。
- 清理脚本默认只清空 `role_identities` 与 `jjc_sync_role_queue`；如需清缓存集合，必须显式传 `--collections`。
- 备份、恢复和清理都会写入 `jjc_backup_metadata`，用于核对 tag、集合名和文档数。

JJC replay 角色 ID / global_id 回填：

```bash
# 默认 dry-run，只处理最近 20 场 detail_saved 对局
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --dry-run

# 指定单场 dry-run
python scripts/backfill_jjc_role_id_from_match_replay.py --match-id <对局ID> --dry-run

# 确认写库
python scripts/backfill_jjc_role_id_from_match_replay.py --limit 20 --apply --yes
```

预期:

- 脚本请求推栏 `/3c/mine/match/replay`，从 `players[].role_id` 补齐 `role_id`，从 `players[].global_role_id` 补齐 replay 数字 `global_id`。
- 脚本默认每场对局后随机 sleep 1 到 3 秒；可用 `--sleep-min` / `--sleep-max` 调整，或用 `--sleep` 指定固定间隔。
- 当目标文档已有 `zone` 时，脚本会继续请求 `/role/indicator`，用 `role_id + zone + server` 补齐 `SK01-... global_role_id` 和 `person_id`。
- 脚本按 `role_info_observed_match_time` 判断是否更新：旧对局只补缺失字段，不覆盖已有完整字段。
- 若已有 `role_id` 与 replay 不一致、已有 `global_id` 与 replay 数字 ID 不一致，或已有 SK01 `global_role_id` 与 indicator 返回不一致，脚本跳过并记录 conflict。

JJC 身份治理只读核验：

```bash
python scripts/check_role_identity_migration.py
```

预期：

- 输出 `role_identities` / `role_jjc_cache` 的基础差异，以及 `role_identities` / `jjc_sync_role_queue` 中 `global_id` 重复、旧 `global:*` / `name:*` 主键残留、同一 `zone+role_id` 对应多个 `global_id` 的样本。
- 新数据应优先为 `global_id:{global_id}`；旧 `global:*` / `name:*` 记录需要通过重建或后续同步迁移，不在核验脚本中自动修改。

### 6. 资历 / 百战 / 骗子查询

- `资历 <角色>`
- `百战 <角色>`
- `骗子 <角色或关键字>`

预期:

- 参数解析正常
- 外部接口失败时有降级提示

### 7. HTTP API

请求:

```bash
curl "http://127.0.0.1:5288/api/arena/recent?server=梦江南&name=示例角色"
curl "http://127.0.0.1:5288/api/jjc/ranking-stats?action=list"
curl "http://127.0.0.1:5288/api/jjc/ranking-stats?action=read&timestamp=<时间戳>"
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/details?timestamp=<时间戳>&range=top_50&lane=healer&kungfu=云裳心经"
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/role-recent?server=梦江南&name=示例角色"
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/role-indicator?server=梦江南&name=示例角色&force_refresh=true"
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/match-detail?match_id=<对局ID>"
```

预期:

- 返回统一结构
- 参数非法时返回错误响应，而不是 500
- `action=read` 首屏摘要不再返回全量 `members`
- `details` 接口可按需返回单个心法成员明细
- 统计页点击角色时可按需返回最近 3v3 胜负和最近对局列表
- 统计页角色指标默认使用 1 天内 `jjc_role_indicator` 缓存；页面刷新按钮或 `force_refresh=true` 会绕过缓存并写回最新结果
- 统计页点击对局时可按需返回单局详情
- 不可用对局详情返回 `unavailable=true`、`code=-1`、`message=no data found`、`detail=null`，统计页应显示“该对局查询不到数据”
- 每日/手动 JJC 排名统计后，若统计过程已请求到 `role/indicator` 或最近胜场 `match/detail`，Mongo 中应可看到对应 `jjc_role_indicator`、`jjc_match_detail` 预热缓存；页面再次查看对应角色或对局时应命中缓存

## 故障排查

### 插件没有加载

检查:

- `pyproject.toml` 中 `plugin_dirs = ["src/plugins"]`
- 插件目录是否存在导入错误
- `nb plugin list --json` 输出是否异常

### API 能启动但消息命令失效

检查:

- OneBot 反向 WebSocket 是否连通
- NapCat 配置是否仍指向当前 `HOST` / `PORT`
- NoneBot 启动日志是否显示适配器注册成功

### 图片渲染失败

检查:

- `templates/` 是否缺文件
- `mpimg/` 是否可写
- 截图依赖与浏览器环境是否完整
- 相关字体或静态资源路径是否仍然存在

### 8. JJC 对局详情快照缓存

`jjc_match_detail` 只保存对局详情主体和玩家节点中的 `equipment_snapshot_hash` / `talent_snapshot_hash`。完整 `armors` / `talents` 分别保存在 `jjc_equipment_snapshot` / `jjc_talent_snapshot`，读取时由 `JjcInspectRepo` 按 hash 拼回 API 响应。

历史详情缓存不迁移；如需重建，直接清空详情和快照缓存，后续点击对局详情时重新请求外部接口并按新格式写入。

```bash
# dry-run：只统计，不清空
python scripts/clear_jjc_match_detail_snapshot_cache.py

# 清空详情缓存和快照缓存
python scripts/clear_jjc_match_detail_snapshot_cache.py --apply

# 验证最近 5 条是否按新格式保存
python scripts/verify_jjc_match_detail_snapshot_storage.py

# 验证指定对局
python scripts/verify_jjc_match_detail_snapshot_storage.py --match-id <对局ID>
```

### 存储或缓存表现异常

检查:

- MongoDB 连接是否正常（`GET /api/mongo/health` 返回 `connected: true`）
- 相关集合索引是否已创建
- `src/storage/` 的装配逻辑是否仍与代码实现一致
- 最近是否改动了缓存路径、运行目录或部署挂载

## 文档联动规则

以下变更必须同步更新本文:

- 启动命令变更
- 环境变量变更
- 新增或删除 HTTP API
- 手工回归路径变更
- 存储后端切换方式变更
