# 技改接口切换计划

## 背景

当前技改查询配置 `SKILL_records_URL` 指向 `https://www.jx3api.com/data/skills/records`，实测该接口返回 404。JX3API 当前文档 `doc/skill.rework.md` 指向 `https://www.jx3api.com/data/skill/rework`，实测返回 `code=200` 且数据结构包含 `id`、`title`、`url`、`time`。

## 目标

- 手动 `技改` 命令改用 `https://www.jx3api.com/data/skill/rework`。
- 定时 `技改推送` 监控改用同一接口。
- 兼容新接口返回的数字型 `id`，避免和已有字符串缓存比较时重复推送。

## 影响范围

- `config.py`: 更新 `SKILL_records_URL` 默认值。
- `src/plugins/status_monitor/jobs.py`: 技改记录 ID 比较统一转字符串。

不涉及数据库结构、索引、迁移脚本、HTTP API 路由或启动方式变更。

## 实施步骤

1. 将 `SKILL_records_URL` 从 `/data/skills/records` 改为 `/data/skill/rework`。
2. 在 `check_records` 中将 `record["id"]` 标准化为 `str(record.get("id", ""))` 后参与缓存集合比较。
3. 新增记录筛选时使用标准化后的 ID，保持推送消息字段不变。

## 验证

- 在线验证：
  - `curl -L https://www.jx3api.com/data/skill/rework`
- 静态验证：
  - `python -m py_compile config.py src/plugins/status_monitor/jobs.py src/plugins/jx3bot_handlers/announcements.py`

## 风险与回滚

- 风险：JX3API 接口字段未来变化会导致解析不到 `id`、`title`、`url` 或 `time`。
- 回滚：将 `config.py` 中 `SKILL_records_URL` 恢复到上一接口，并回退 `check_records` 的 ID 标准化逻辑。

## 完成状态

- 已完成接口替换和技改推送 ID 标准化。
- 已完成在线接口验证和 Python 编译检查。
