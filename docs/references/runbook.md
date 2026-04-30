# 运行与回归手册

更新时间：2026-04-30

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

预期:

- 能返回文本或渲染结果
- 无明显堆栈报错

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

### 5. 竞技相关

- `竞技查询`
- `竞技排名`
- `竞技排名 拆分`

预期:

- service 能返回结构化数据
- renderer 能生成图片
- 统计文件写入 `data/jjc_ranking_stats/`
  - 新结构优先写入 `data/jjc_ranking_stats/<timestamp>/summary.json`
  - 明细按需拆分在 `data/jjc_ranking_stats/<timestamp>/details/`
  - 历史兼容阶段可能仍存在旧的 `data/jjc_ranking_stats/<timestamp>.json`

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
curl "http://127.0.0.1:5288/api/jjc/ranking-stats/match-detail?match_id=<对局ID>"
```

预期:

- 返回统一结构
- 参数非法时返回错误响应，而不是 500
- `action=read` 首屏摘要不再返回全量 `members`
- `details` 接口可按需返回单个心法成员明细
- 统计页点击角色时可按需返回最近 33 胜负和最近对局列表
- 统计页点击对局时可按需返回单局详情

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
