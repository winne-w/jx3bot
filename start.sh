#!/bin/bash

# 确保mpimg目录存在
mkdir -p /app/mpimg

# 检查依赖安装
echo "检查依赖..."
pip show uvicorn || pip install uvicorn
pip show fastapi || pip install fastapi
pip show websockets || pip install websockets
pip show nb-cli || pip install nb-cli

# 在后台启动HTTP服务器
echo "启动HTTP服务器..."
cd /app/mpimg && python -m http.server 8000 &

# 启动NoneBot2机器人
echo "启动NoneBot2机器人..."
cd /app && python bot.py 