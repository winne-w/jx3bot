# JX3Bot

JX3Bot 是一个基于 NoneBot2 的剑网 3 QQ 机器人，运行在 OneBot V11 协议之上，同时暴露少量 HTTP API。仓库当前处于持续重构阶段，核心目标是把历史上集中在单插件中的逻辑，逐步收敛为更清晰的 `plugins / services / infra / storage / renderers` 分层。

## 当前能力

- QQ 群消息命令处理
- 剑网 3 常见查询能力，如公告、竞技、名片、资历、交易行、百战、骗子查询等
- 万宝楼检索与订阅能力
- 定时推送与状态监控
- HTTP API:
  - `GET /api/arena/recent?server=<服务器>&name=<角色>`
  - `GET /api/jjc/ranking-stats?action=list`
  - `GET /api/jjc/ranking-stats?action=read&timestamp=<时间戳>`

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
- 准备好 `groups.json`
- NapCat 或其他 OneBot V11 实现已配置反向 WebSocket

默认运行时会同时启用消息插件和 HTTP API，监听地址由 `HOST`/`PORT` 控制。

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
