# JX3Bot Docker 部署指南

本文只描述当前仓库里已经存在的容器运行方式，不扩展额外编排方案。

## 当前容器行为

- 容器内主进程由 `start.sh` 启动
- `start.sh` 会先确保 `mpimg/` 存在
- 再后台启动 `python -m http.server 8000` 暴露 `mpimg/`
- 最后执行 `python bot.py` 启动 NoneBot 与 HTTP API

因此，容器内会同时开放:

- `5288`: NoneBot / HTTP API
- `8000`: `mpimg/` 静态文件

## docker-compose 启动

```bash
docker compose up --build -d
docker compose logs -f
```

停止与重建:

```bash
docker compose down
docker compose up --build -d
```

## compose 配置摘要

当前 `docker-compose.yml` 的关键设置:

- 容器名: `jx3bot`
- 时区: `Asia/Shanghai`
- 环境变量:
  - `ENVIRONMENT=prod`
  - `DRIVER=~fastapi+~websockets`
  - `HOST=0.0.0.0`
  - `PORT=5288`
  - 可选 `JJC_SYNC_WORKER_COUNT=1`，让 bot 启动后内置 1 个 JJC 同步 worker；默认 `0` 不启动
- 端口映射:
  - `5288:5288`
  - `8000:8000`

## 数据挂载

当前 compose 文件挂载了以下路径:

- `/mnt/sata6-1/jx3bot:/app`
- `./mpimg:/app/mpimg`
- `./log.txt:/app/log.txt`
- `./server_data.json:/app/server_data.json`
- `./groups.json:/app/groups.json`

这意味着:

- 应用代码目录会整体挂载到容器内 `/app`
- 名片图片缓存、日志、服务器数据和群配置都直接保存在宿主机

如果调整这些挂载，请同步更新:

- `docker-compose.yml`
- `start.sh`
- `README.md`
- `docs/references/runbook.md`
- `docs/tasks/all-tasks.md`（如影响部署任务或回归路径）

## 部署前检查

1. 宿主机已安装 Docker 与 Docker Compose
2. `config.py` 已准备完成
3. `groups.json`、`server_data.json` 的读写权限正确
4. OneBot 反向 WebSocket 已指向容器可访问地址
5. 容器环境变量只维护现有运行必需项
6. `runtime_config.json` 由本地从 `runtime_config.example.json` 复制后填写，不提交真实凭证

## JJC 同步 Worker

默认容器只启动 bot 和 `mpimg/` 静态服务，JJC 同步 worker 不自动启动。启用方式任选其一:

- 在 compose 环境变量中增加 `JJC_SYNC_WORKER_COUNT=1`
- 在本地 `runtime_config.json` 中写入 `"JJC_SYNC_WORKER_COUNT": 1`
- 通过 QQ 管理命令 `/修改配置 JJC_SYNC_WORKER_COUNT=1` 写入运行时配置

内置 worker 与 `python scripts/jjc_sync.py worker --mode=incremental_or_full` 独立 worker 可以共存，总并发数等于所有 bot 实例和独立 worker 数量之和。通过 QQ 修改配置时当前实现会退出进程，容器需要 `restart` 策略或其他外部守护来自动拉起。

内置 worker 使用稳定槽位名 `bot:{host}:{index}`。同一容器或主机重启后会复用同一条 worker 心跳记录，不会因为 pid 或启动时间变化持续新增离线 worker；如果同一 host 上同时部署多个 bot 实例，需要先用不同 hostname 或后续实例名配置区分。

## 常见问题

### 容器启动后图片无法访问

先确认:

- `mpimg/` 在宿主机和容器内都存在
- `8000` 端口已暴露
- `start.sh` 是否正常拉起了 `python -m http.server 8000`

### 机器人启动了但 HTTP API 不通

先确认:

- `HOST=0.0.0.0`
- `PORT=5288`
- `bot.py` 已正常注册 `src/api/routers/`
- 端口没有被宿主机防火墙或其他服务占用

### 容器内依赖不完整

`start.sh` 会补装少量运行依赖，但不应依赖它来解决全部环境问题。基础依赖仍应通过镜像构建阶段和 `requirements.txt` 保证一致性。
