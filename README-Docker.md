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
5. 若使用 Mongo，已额外注入 `STORAGE_BACKEND`、`MONGO_URI`、`MONGO_DB`

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
