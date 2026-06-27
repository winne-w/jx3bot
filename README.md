# JX3Bot

JX3Bot 是一个基于 NoneBot2 的剑网 3 QQ 机器人，运行在 OneBot V11 协议之上，同时暴露少量 HTTP API。仓库当前处于持续重构阶段，核心目标是把历史上集中在单插件中的逻辑，逐步收敛为更清晰的 `plugins / services / infra / storage / renderers` 分层。

## 当前能力

- QQ 群消息命令处理
- 剑网 3 常见查询能力，如公告、竞技、名片、资历、交易行、百战、骗子查询等
- 万宝楼检索与订阅能力
- 定时推送与状态监控
- HTTP API:
  - 生产代理路径通常带 `/jx3bot` 前缀，例如 `https://qike.rickchen.cn/jx3bot/api/...`；仓库内路由定义仍按 `/api/...` 记录。
  - `GET /api/arena/recent?server=<服务器>&name=<角色>`
  - `GET /api/jjc/ranking-stats?action=list`
  - `GET /api/jjc/ranking-stats?action=list&page=1&page_size=20`
  - `GET /api/jjc/ranking-stats?action=list&page=1&page_size=100&with_meta=1`
  - `GET /api/jjc/ranking-stats?action=read&timestamp=<时间戳>`
  - `GET /api/jjc/ranking-stats/details?timestamp=<时间戳>&range=<范围>&lane=<healer|dps>&kungfu=<心法>`
  - `GET /api/jjc/ranking-stats/flat-members?timestamp=<时间戳>&range=<top_1000|top_200|top_100|top_50>`：按原始名次返回当前推栏排名列表，不按心法分组
  - `GET /api/jjc/ranking-stats/peak-score?timestamp=<时间戳>&score_type=<tuilan|game>&range=<top_1000|top_200|top_100|top_50>`：读取 14 天历史最高分排名
  - `GET /api/jjc/ranking-stats/role-recent?server=<服务器>&name=<角色>`
  - `GET /api/jjc/ranking-stats/synced-role?server=<服务器>&name=<角色>`：查询本地已收录角色身份和同步状态；`server` 为空时按角色名返回本地候选
  - `GET /api/jjc/ranking-stats/synced-role-matches?server=<服务器>&name=<角色>&page=1&page_size=20`：按角色 `global_id` 分页读取其参与过的本地已同步 3v3 对局
  - `POST /api/jjc/ranking-stats/synced-role-sync`：将已收录角色加入 JJC 同步队列
  - `GET /api/jjc/ranking-stats/match-detail?match_id=<对局ID>`
  - `GET /api/jjc/sync/status`：同步队列汇总，包含 `worker_running/background_running`
  - `GET /api/jjc/sync/queue?status=queued&mode=full&server=梦江南&name=角色&page=1&page_size=50`：角色队列分页，支持队列状态、同步类型、服务器/角色名搜索，包含 `has_more`
  - `GET /api/jjc/sync/workers`
  - `GET /api/jx3/servers`：读取当前区服列表，用于前端服务器下拉选择
- 静态页面:
  - 生产静态页面通常由站点映射到 `/jx3/<page>.html`，不要加 `/jx3bot` API 前缀。
  - `GET /jx3/jjc-ranking-stats.html`: JJC 心法分布、当前推栏排名列表、7 天推栏/游戏最高分列表
  - `GET /jx3/jjc-sync-queue.html`: JJC 同步队列与 worker 状态页
  - `GET /jx3/jjc-synced-matches.html`: 按角色查询其参与过的本地已同步 JJC 3v3 对局
  - 本地直接由 bot 暴露静态目录时，可按实际挂载访问 `/public/<page>.html`。

统一响应格式:

```json
{"status_code":0,"status_msg":"success","data":{}}
```

## 仓库结构

```text
bot.py                       NoneBot 启动入口
src/plugins/                 QQ 命令入口与插件注册
src/plugins/jx3bot_handlers/ 各类命令 handler
src/plugins/status_monitor/  状态监控与定时任务
src/plugins/wanbaolou/       万宝楼相关逻辑
src/services/jx3/            业务编排与缓存策略
src/infra/                   外部 API / HTTP / 截图适配
src/storage/                 存储适配
src/renderers/               模板渲染与图片生成
src/api/routers/             HTTP API 路由
templates/                   Jinja 模板
data/                        缓存、统计与运行数据
mpimg/                       名片等图片缓存
docs/                        补充架构与运行文档
```

更具体的边界说明见 `project-architecture.md`。

## 运行前提

- Python 3.9+
- 已安装项目依赖
- 准备好 `config.py`
- 准备好 MongoDB 连接（通过环境变量、部署配置或本地 `runtime_config.json` 中的 `MONGO_URI` 配置）
- NapCat 或其他 OneBot V11 实现已配置反向 WebSocket

默认运行时会同时启用消息插件和 HTTP API，监听地址由 `HOST`/`PORT` 控制。
`runtime_config.json` 存放本地凭证和运行时覆盖项，不应提交到 Git；可从 `runtime_config.example.json` 复制后填写本地值。

## 本地启动

1. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 启动机器人

```bash
python bot.py
```

如果要模拟容器入口并同时暴露 `mpimg/` 静态目录，可运行:

```bash
bash start.sh
```

## JJC 同步 Worker

JJC 对局同步默认只入队，不会在 bot 进程内自动处理队列。需要单独扩容或排障时仍可启动独立 worker:

```bash
python scripts/jjc_sync.py worker
```

入队默认按 full 处理；需要限制本次入队同步窗口时使用 `days` 或 `until`，例如 `/jjc同步开始 full days=14` 或 `python scripts/jjc_sync.py enqueue --days=14`。worker 只消费队列，不决定同步窗口。

单进程部署也可以启用 bot 内置 worker 和自动补队列 dispatcher。最小配置示例:

```json
{
  "JJC_SYNC_WORKER_COUNT": 1,
  "JJC_SYNC_DISPATCHER_ENABLED": 1
}
```

`JJC_SYNC_WORKER_COUNT=0` 表示关闭内置 worker；大于 0 时，bot 在 Mongo 初始化完成后创建对应数量的后台 worker。`JJC_SYNC_DISPATCHER_ENABLED=1` 时，bot 还会启动一个自动补队列 dispatcher，在 `queued` 深度不足时把到期角色按最近 14 天窗口补入队列；它不直接同步对局，也不会替代页面 full 或手工 full 入队。也可以通过环境变量或管理员命令 `/修改配置 ...` 设置。QQ 修改配置会退出当前进程，自动拉起依赖 Docker、systemd、supervisor 等外部守护。

内置 worker 使用稳定槽位名 `bot:{host}:{index}`，例如 `bot:my-host:0`。同一部署实例重启后会复用同一条 worker 心跳记录，不会因为 pid 或启动时间变化持续新增离线 worker。

## 存储说明

当前分支只记录现有文件型运行数据和存储边界。

## 手工验证

仓库当前主要依赖手工回归和在线接口验证。最小检查集:

```bash
nb plugin list --json
python test_tuilan_match_history.py
```

更完整的回归路径见 `docs/references/runbook.md`。

## Docker

容器部署说明见 `README-Docker.md`。如果改动了 `Dockerfile`、`docker-compose.yml` 或 `start.sh`，请同步更新该文档与 `docs/references/runbook.md`。

## 文档索引

- `AGENTS.md`: agent 的最小入口和协作规则
- `project-architecture.md`: 当前架构、依赖方向与模块职责
- `project-roadmap.md`: 中期目标、优先级与阶段方向
- `project-history.md`: 已完成的重要演进与文档调整记录
- `docs/design-docs/development-guide.md`: 新需求落层、改造路径与提交前检查
- `docs/references/runbook.md`: 启动、验证、故障排查、部署注意事项
- `docs/exec-plans/active/refactor-plan.md`: 现阶段重构边界和未完成项
- `docs/tasks/all-tasks.md`: 当前任务清单与任务文档索引
