# JX3Bot Docker 部署指南

## 部署步骤

### 1. 准备工作

确保您的服务器上已安装 Docker 和 Docker Compose：

```bash
# 安装 Docker (Windows/Mac 用户请直接下载 Docker Desktop)
curl -fsSL https://get.docker.com | sh

# 安装 Docker Compose
pip install docker-compose
```

### 2. 构建并启动容器

在项目根目录中运行：

```bash
# 构建并启动容器（后台运行）
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 3. 停止或重启服务

```bash
# 停止服务
docker-compose down

# 重新构建并启动（代码更新后）
docker-compose up -d --build
```

## 数据持久化

整个应用目录被挂载到主机的 `/mnt/sata6-1/jx3bot` 目录下，此外还有以下单独的数据挂载：

- `mpimg/`: 名片缓存目录
- `log.txt`: 日志文件
- `server_data.json`: 服务器数据
- `groups.json`: 群组配置

## 服务说明

容器启动后将会运行两个服务：

1. NoneBot2 机器人 - 端口 5288
2. mpimg 目录的 HTTP 文件服务器 - 端口 8000

您可以通过 http://服务器IP:8000 访问 mpimg 目录下的文件。

## 配置修改

如需修改配置，请编辑原始配置文件（如`.env.prod`、`config.py`等），然后重新构建容器：

```bash
docker-compose up -d --build
```

## 注意事项

1. 容器内使用的端口是 5288 和 8000，与外部映射相同。
2. 容器使用 Asia/Shanghai 时区。
3. HOST 设置为 0.0.0.0 以允许从容器外部访问。
4. 整个应用目录会被挂载到主机的 `/mnt/sata6-1/jx3bot` 目录。

# 移除之前的容器
docker rm jx3bot

# 重新构建镜像
docker build -t jx3bot .

# 运行容器
docker run -d --name jx3bot \
  -p 5288:5288 -p 8000:8000 \
  -v /mnt/sata6-1/jx3bot:/app \
  -v $(pwd)/mpimg:/app/mpimg \
  -v $(pwd)/log.txt:/app/log.txt \
  -v $(pwd)/server_data.json:/app/server_data.json \
  -v $(pwd)/groups.json:/app/groups.json \
  -e TZ=Asia/Shanghai \
  -e ENVIRONMENT=prod \
  -e DRIVER="~fastapi+~websockets" \
  -e HOST=0.0.0.0 \
  -e PORT=5288 \
  jx3bot 