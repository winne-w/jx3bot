# Mongo 迁移第一阶段说明

## 1. 改造目标
第一阶段只迁移以下三类数据，并保持业务语义不变：
- 群绑定配置（原 `groups.json`）
- 万宝楼订阅（原 `data/wanbaolou_subscriptions.json`）
- 服务器简称缓存（原 `data/cache/server_master_cache.json`）

存储层采用 Ports/Adapters 结构，业务层只依赖端口接口，不直接依赖 `pymongo`。

## 2. 分层设计
目录结构：
- `src/storage/ports.py`：端口定义与 `StorageBundle`
- `src/storage/factory.py`：按 `STORAGE_BACKEND` 构建后端
- `src/storage/singletons.py`：全局单例注入点
- `src/storage/json_adapter/*.py`：JSON 适配器（兼容原文件结构）
- `src/storage/mongo_adapter/*.py`：Mongo 适配器

后端切换：
- 默认：`STORAGE_BACKEND=json`
- 启用 Mongo：`STORAGE_BACKEND=mongo`

## 3. Mongo 配置
环境变量：
- `STORAGE_BACKEND=mongo`
- `MONGO_URI=mongodb://127.0.0.1:27017`
- `MONGO_DB=jx3bot`

Collection 映射：
- `group_bindings`
- `wanbaolou_subscriptions`
- `server_alias_cache`

## 4. 索引策略
在 Mongo 适配器中提供 `init_indexes()`，并由 `StorageBundle.init_indexes()` 统一调用。

当前索引：
- `group_bindings`：`updated_at`
- `wanbaolou_subscriptions`：`updated_at`
- `server_alias_cache`：`updated_at`、`payload.cached_at`

## 5. 迁移步骤
1. 安装依赖：
```bash
pip install -r requirements.txt
```
2. 执行迁移：
```bash
python scripts/migrate_json_to_mongo.py --mongo-uri mongodb://127.0.0.1:27017 --mongo-db jx3bot --init-indexes
```
3. 执行校验：
```bash
python scripts/verify_migration.py --mongo-uri mongodb://127.0.0.1:27017 --mongo-db jx3bot
```
4. 切换运行后端：
```bash
export STORAGE_BACKEND=mongo
python bot.py
```

## 6. 回滚方案
出现异常时，直接回滚到 JSON：
```bash
export STORAGE_BACKEND=json
python bot.py
```

本阶段不删除任何 JSON 文件，Mongo 数据也不执行 destructive 清理，可随时回切。

## 7. 兼容性说明
- JSON 后端继续使用原路径与原格式。
- 群绑定、万宝楼订阅、服务器简称缓存业务流程保持不变。
- HTTP API 响应规范保持：`{"status_code":0,"status_msg":"success","data":{}}`。
